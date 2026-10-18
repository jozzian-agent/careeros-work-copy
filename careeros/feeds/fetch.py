"""Fetching one tenant's feeds: retries, conditional requests, paging,
details, locating.

Provider-agnostic orchestration over the adapter contract in
`careeros.feeds.base`. An adapter supplies the variants, the parse and
the mapping; this module supplies everything that would otherwise be
written six times: the retry policy, the conditional request, the raw
snapshot, the paging walk, the detail pass, the geocode pass, the
provenance completion and the per-tenant fetch status.

NO NETWORK OF ITS OWN. `fetch` is a callable with
`scripts/polite_http.request_text`'s signature and return shape. The
runner wires the real one in; a test passes a transport that answers out
of a recorded fixture. That is why the whole package is testable offline
against real feed shapes.

## Politeness, per the spec

  * One request a second, which is the shared `polite_http.RateLimiter`
    the runner passes in. Each tenant can be a distinct host, so a
    per-host limit would allow a burst across tenants; the runner
    therefore uses ONE limiter for the whole run, which is a global cap
    of one request a second and strictly politer than the spec asks for.
    It also satisfies the `Crawl-delay: 1` Lever's robots.txt asks for.
  * `robots.txt` is checked per provider API host and recorded in each
    adapter's own source check. Five of the six hosts allow this;
    `smartrecruiters` does not, and the runner refuses it without an
    explicit exception flag.
  * Retries are exponential from one second and capped, per the spec's
    "no retries faster than exponential backoff after errors".

## Conditional requests

The spec asks for them "where the server supports them, so unchanged
feeds cost nothing". Five of the six providers serve an `ETag`
(Personio, Greenhouse, Lever, Ashby and SmartRecruiters -- all verified
live 2026-10-17); Recruitee does not, so its conditional requests never
fire and nothing pretends otherwise.

A 304 carries no body, so the postings it implies are read back from the
last raw snapshot for that tenant and variant and re-parsed. That keeps
closure detection correct: a 304 is a SUCCESSFUL fetch that saw every
posting it saw last time, not a fetch that saw none of them. If the
snapshot it refers to is missing, the conditional request is retried
unconditionally rather than guessed at.

## Variants, groups, pages and details

One tenant is read through one or more `base.Variant`s, in the order the
adapter lists them:

  * variants of one GROUP are one career site. A 404 on a group's
    `primary` variant skips the rest of that group -- measured on
    Personio, a third of discovered tenants serve no feed at all and
    each would otherwise cost four requests.
  * a variant marked `optional` is skipped once the store knows it
    carries no posting text (Personio's second language, which answers
    200 with every description empty).
  * when a group succeeds and its variants say `stop_after_group`, the
    remaining groups are not requested. Personio says so (`.com` is the
    same career site as `.de`); Lever does not, because its two
    instances are genuinely different boards.
  * PAGING is the adapter's `next_page`: SmartRecruiters answers 100
    postings at a time with a `totalFound`, and the walk stops at the
    adapter's own page cap and records that it was capped.
  * DETAILS are the adapter's `detail_variant`: one extra request per
    posting, made only for the postings the Zurich filter kept
    (`DETAIL_IN_AREA`, the default). SmartRecruiters is the only
    provider whose list endpoint states no description, and fetching
    every posting's text would cost hundreds of requests for postings
    the pool excludes anyway. A posting whose detail was not fetched
    says so in `description_status`.
"""
import logging
import time

from careeros.feeds import base, geocode, personio, store as store_module

_logger = logging.getLogger(__name__)

#: A transient failure is worth up to this many attempts, with the delay
#: doubling from `BACKOFF` seconds each time.
ATTEMPTS = 3
BACKOFF = 1.0

#: Statuses that are worth trying again. A 404 is a settled answer ("no
#: such tenant"), a 403 is a refusal; neither gets quieter on a retry.
RETRY_STATUSES = (None, 408, 425, 429, 500, 502, 503, 504)

#: A feed body cap of its own, because the shared default is too small
#: for this job and finding that out cost a parse failure. `polite_http`
#: inherits `org_intake.fetch.MAX_BODY_SIZE` (2 MB), which is the right
#: size for a job posting page; the Personio feed of one large employer
#: measured 2 212 621 bytes on 2026-10-17 and Ashby's own board 1 936 523,
#: so the shared cap truncated them mid-element. 32 MB is the same cap
#: `scripts/seed_zefix_zurich.py` uses for its own bulk responses: far
#: out of the way of a real feed, still not unbounded.
FEED_MAX_BODY = 32_000_000

FETCH_TRUNCATED = 'truncated'

FETCH_OK = store_module.FETCH_OK
FETCH_NOT_FOUND = 'not_found'
FETCH_HTTP_ERROR = 'http_error'
FETCH_PARSE_ERROR = 'parse_error'
FETCH_UNREACHABLE = 'unreachable'

#: Which postings get a second request for their text. See the
#: docstring's detail note.
DETAIL_IN_AREA = 'in_area'
DETAIL_ALL = 'all'
DETAIL_NONE = 'none'

#: How many pages one tenant may be walked for, whatever its adapter
#: says. A floor under the adapter's own cap, so a provider that starts
#: answering an unbounded `totalFound` cannot spend a whole run.
MAX_PAGES = 20


def with_retry(url, *, fetch, limiter=None, headers=None, attempts=ATTEMPTS,
               backoff=BACKOFF, sleep=time.sleep, retry_statuses=RETRY_STATUSES, **options):
    """One GET with exponential backoff on a transient failure.

    Returns the fetcher's own dict plus `attempts`. Nothing raises: the
    caller counts failures (PROJECT.md: failures are visible states with
    a reason, never silent). `options` is passed through to the fetcher,
    which is how `max_body` reaches it.
    """
    result = {'ok': False, 'status': None, 'text': '', 'error': 'not attempted', 'headers': {}}
    if headers:
        options['headers'] = headers
    for attempt in range(1, max(1, attempts) + 1):
        result = fetch(url, limiter=limiter, **options)
        if result['ok'] or result.get('status') not in retry_statuses:
            return {**result, 'attempts': attempt}
        if attempt < attempts:
            sleep(backoff * (2 ** (attempt - 1)))
    return {**result, 'attempts': max(1, attempts)}


def locate(mapped, *, guide_version=None):
    """Add the location layer to a mapped posting.

    Separate from `map_posting` because geocoding is not a provider
    concern: every provider's office line goes through exactly this
    function. Returns a new dict; the input is not mutated.

    `offices_stated` is preferred over `offices` where an adapter has it:
    the four providers whose API states a country beside the place pass
    the pair, which is what lets the geocoder rule out a foreign town
    that shares a Swiss municipality name.
    """
    offices, summary = geocode.geocode_offices(mapped.get('offices_stated')
                                               or mapped.get('offices') or ())
    located = dict(mapped)
    located['offices_geocoded'] = offices
    located['location'] = summary
    located['area_status'] = summary['status']
    located['municipality'] = summary['municipality']
    located['municipality_label'] = geocode.municipality_label(summary['municipality'])
    located['canton'] = summary['canton']
    located['swiss_evidence'] = summary.get('swiss_evidence', False)
    located['corroborated'] = summary.get('corroborated', False)
    located['values'] = {**(mapped.get('values') or {}),
                         **geocode.location_value_records(summary, guide_version=guide_version)}
    return located


def _conditional_headers(etag):
    return {'If-None-Match': etag} if etag else None


def _replay_snapshot(store, tenant, variant, snapshot_path, *, adapter):
    """The body behind a 304: the last raw snapshot for this tenant and
    variant, or None when it is not on disk any more.

    `snapshot_path` is store-relative, which is how the tenant record
    holds it, so a store that moved directory still replays.
    """
    if not snapshot_path:
        return None
    path = store.root / snapshot_path
    if not path.exists():
        _logger.info('%s: %s/%s answered 304 but %s is gone; fetching unconditionally',
                     adapter.PROVIDER, tenant, variant.slug, snapshot_path)
        return None
    try:
        return adapter.decompress(path.read_bytes())
    except (OSError, ValueError) as error:
        _logger.warning('%s: could not replay %s for %s/%s: %s',
                        adapter.PROVIDER, snapshot_path, tenant, variant.slug, error)
        return None


def fetch_tenant(tenant, *, store, run, fetch, limiter=None, adapter=personio,
                 conditional=None, at=None, guide_version=None, sleep=time.sleep,
                 detail=DETAIL_IN_AREA, **variant_options):
    """Fetch, parse, map and locate every posting of one tenant.

    `conditional` is `{variant slug: {'etag', 'snapshot', 'publishes'}}`
    from the tenant's own record, so a second run of an unchanged feed
    costs one conditional request and no parsing. Anything else in
    `variant_options` is passed to the adapter's `feed_variants`, which
    is how `languages=('de',)` still reaches Personio.

    Returns a result dict:

        {'tenant', 'fetch_status', 'error', 'host', 'languages': {...},
         'postings': [located, ...], 'publishes': {slug: bool},
         'parse_failures': [...], 'posting_failures': [...],
         'requests': int, 'etags': {...}, 'details': {...}}

    `parse_failures` is per FEED and `posting_failures` is per posting,
    because the spec's 99% parse-success rate is counted over feeds.

    `fetch_status` is `ok` only when at least one variant gave a
    parseable feed. Everything else is a named failure, and a failure is
    what `store.record_run` refuses to count toward closure.
    """
    at = at or store_module.now()
    result = {'tenant': tenant, 'provider': adapter.PROVIDER, 'fetch_status': FETCH_UNREACHABLE,
              'error': None, 'host': None, 'languages': {}, 'postings': [], 'publishes': {},
              'parse_failures': [], 'posting_failures': [], 'requests': 0, 'etags': {},
              'snapshots': {}, 'pages': 0,
              'details': {'requested': 0, 'ok': 0, 'failed': 0}}
    conditional = conditional or {}
    by_key = {}

    variants = adapter.feed_variants(tenant, **variant_options)
    groups = []
    for variant in variants:
        if variant.group_key not in groups:
            groups.append(variant.group_key)

    for group in groups:
        group_ok, stop_after = False, True
        for variant in [item for item in variants if item.group_key == group]:
            stop_after = variant.stop_after_group
            known = conditional.get(variant.slug, {})
            # An optional variant is fetched on the first run of a
            # tenant and then only while it is known to carry postings
            # (Personio's "a second call with language=en only if the
            # tenant publishes English postings"). The first run is what
            # finds out, because an unsupported language answers 200.
            if variant.optional and known and known.get('publishes') is False:
                result['languages'][variant.key] = {
                    'skipped': f'this tenant publishes no {variant.slug} postings'}
                continue
            attempt = _fetch_one(tenant, variant, adapter=adapter, fetch=fetch, limiter=limiter,
                                 store=store, run=run, known=known, sleep=sleep)
            result['requests'] += attempt['requests']
            result['languages'][variant.key] = attempt['report']
            if attempt['status'] != FETCH_OK:
                if result['fetch_status'] != FETCH_OK:
                    result['fetch_status'] = attempt['status']
                    result['error'] = attempt['report'].get('error')
                if attempt['status'] == FETCH_PARSE_ERROR:
                    result['parse_failures'].append({'tenant': tenant, 'host': variant.host,
                                                     'language': variant.language,
                                                     'variant': variant.key,
                                                     'reason': attempt['report'].get('error')})
                if attempt['status'] == FETCH_NOT_FOUND and variant.primary:
                    # No career site on this group at all, so every other
                    # variant of it is one more 404.
                    break
                continue

            group_ok = True
            result['fetch_status'] = FETCH_OK
            # A tenant whose feed was read has no error, even if an
            # earlier variant failed. Lever's two instances are the live
            # case: a slug that exists only on the EU one answers 404 on
            # the global one first, and reporting that 404 beside a
            # successful fetch reads as a half-failure it is not. Each
            # variant's own failure stays in `languages`.
            result['error'] = None
            result['host'] = result['host'] or variant.host
            _absorb(result, attempt, tenant=tenant, variant=variant, adapter=adapter,
                    guide_version=guide_version, at=at, run=run, by_key=by_key)

            # Paging, for the one provider that answers in pages.
            page_variant, parsed, pages = variant, attempt['positions'], 0
            while pages < MAX_PAGES:
                following = base.feature(adapter, 'next_page')(page_variant, parsed,
                                                               len(by_key))
                if following is None:
                    break
                pages += 1
                result['pages'] += 1
                attempt = _fetch_one(tenant, following, adapter=adapter, fetch=fetch,
                                     limiter=limiter, store=store, run=run,
                                     known=conditional.get(following.slug, {}), sleep=sleep)
                result['requests'] += attempt['requests']
                result['languages'][following.key] = attempt['report']
                if attempt['status'] != FETCH_OK:
                    result['parse_failures'] += (
                        [{'tenant': tenant, 'host': following.host, 'variant': following.key,
                          'language': None, 'reason': attempt['report'].get('error')}]
                        if attempt['status'] == FETCH_PARSE_ERROR else [])
                    break
                _absorb(result, attempt, tenant=tenant, variant=following, adapter=adapter,
                        guide_version=guide_version, at=at, run=run, by_key=by_key)
                page_variant, parsed = following, attempt['positions']
        if group_ok and stop_after:
            break

    postings = [by_key[key] for key in sorted(by_key)]
    if detail != DETAIL_NONE:
        postings = _fetch_details(postings, tenant=tenant, adapter=adapter, store=store, run=run,
                                  fetch=fetch, limiter=limiter, sleep=sleep, at=at,
                                  guide_version=guide_version, detail=detail, result=result)
    result['postings'] = postings
    return result


def _absorb(result, attempt, *, tenant, variant, adapter, guide_version, at, run, by_key):
    """Map, locate and keep every posting one successful variant
    returned, and record what the variant itself said."""
    carries_text = base.feature(adapter, 'variant_carries_text')(attempt['positions'])
    result['publishes'][variant.language or variant.slug] = carries_text
    result['etags'][variant.slug] = {'etag': attempt['report'].get('etag'),
                                     'snapshot': attempt['report'].get('snapshot'),
                                     'publishes': carries_text}
    if attempt['report'].get('snapshot'):
        result['snapshots'][variant.key] = attempt['report']['snapshot']

    for raw in attempt['positions']:
        try:
            mapped = adapter.map_posting(raw, tenant=tenant, variant=variant,
                                         guide_version=guide_version)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            # A posting-level failure, kept apart from `parse_failures`
            # on purpose: the spec's parse-success rate is counted per
            # FEED, and folding a posting that could not be mapped into
            # the feed failures would make one broken posting look like
            # a broken feed.
            result['posting_failures'].append({'tenant': tenant, 'host': variant.host,
                                               'language': variant.language,
                                               'variant': variant.key,
                                               'reason': f'{type(error).__name__}: {error}'[:300]})
            continue
        base.attach_fetch_provenance(mapped, variant=variant,
                                     feed_snapshot=attempt['report'].get('snapshot'),
                                     run=run, at=at)
        located = locate(mapped, guide_version=guide_version)
        by_key[located['key']] = _prefer(by_key.get(located['key']), located)


def _fetch_details(postings, *, tenant, adapter, store, run, fetch, limiter, sleep, at,
                   guide_version, detail, result):
    """The second request per posting, for the one provider that needs it.

    Only the postings the Zurich filter kept, unless asked for all of
    them. A posting whose detail could not be fetched keeps its
    list-mapped record and its `description_status` says so, because a
    missing description is a visible state and not a dropped posting.
    """
    wanted = base.feature(adapter, 'detail_variant')
    answered = []
    for posting in postings:
        variant = wanted(posting)
        if variant is None or (detail == DETAIL_IN_AREA
                               and posting.get('area_status') != geocode.IN_AREA):
            answered.append(posting)
            continue
        result['details']['requested'] += 1
        attempt = _fetch_one(tenant, variant, adapter=adapter, fetch=fetch, limiter=limiter,
                             store=store, run=run, known={}, sleep=sleep,
                             parser=adapter.parse_detail)
        result['requests'] += attempt['requests']
        result['languages'][variant.key] = attempt['report']
        if attempt['status'] != FETCH_OK:
            result['details']['failed'] += 1
            answered.append(posting)
            continue
        try:
            merged = adapter.merge_detail(posting, attempt['positions'], tenant=tenant,
                                          guide_version=guide_version)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            result['details']['failed'] += 1
            result['posting_failures'].append({'tenant': tenant, 'host': variant.host,
                                               'variant': variant.key, 'language': None,
                                               'reason': f'detail: {type(error).__name__}: '
                                                         f'{error}'[:300]})
            answered.append(posting)
            continue
        # The list snapshot stays the posting's feed snapshot and the
        # detail gets its own entry, so the provenance block names both
        # requests the record came from.
        base.attach_fetch_provenance(merged, variant=variant,
                                     feed_snapshot=posting['provenance']['feed_snapshot'],
                                     run=run, at=at)
        merged['provenance'].update({'feed_url': posting['provenance']['feed_url'],
                                     'feed_variant': posting['provenance']['feed_variant'],
                                     'detail_url': variant.url,
                                     'detail_snapshot': attempt['report'].get('snapshot')})
        result['details']['ok'] += 1
        answered.append(locate(merged, guide_version=guide_version))
    return answered


def _prefer(existing, candidate):
    """One posting id, two variants: which one is THE record.

    Personio asks for German first -- but only if it actually carries
    posting text. A tenant that publishes in English alone still answers
    the German feed with 200 and every `jobDescriptions` empty, and a
    golden-set posting with no text is useless. So a later variant with
    text beats an earlier one without, and the loser is kept beside the
    winner as a translation rather than thrown away.
    """
    if existing is None:
        return candidate
    winner, loser = ((candidate, existing)
                     if candidate.get('has_description') and not existing.get('has_description')
                     else (existing, candidate))
    translations = dict(winner.get('translations') or {})
    translations[loser.get('feed_language') or loser.get('feed_host') or 'other'] = {
        'title': loser['title'], 'description': loser['description'],
        'content_hash': loser['content_hash'], 'has_description': loser['has_description']}
    winner = dict(winner)
    winner['translations'] = translations
    return winner


def _fetch_one(tenant, variant, *, adapter, fetch, limiter, store, run, known, sleep,
               max_body=FEED_MAX_BODY, parser=None):
    """One variant: request, snapshot, parse.

    `parser` overrides the adapter's own `parse_feed`, which is how a
    posting DETAIL (an object, not a list) goes through the same request,
    snapshot and failure accounting as a feed.
    """
    report = {'url': variant.url, 'variant': variant.key, 'status': None, 'error': None,
              'bytes': 0, 'positions': 0, 'etag': None, 'snapshot': None, 'conditional': False,
              'attempts': 0}
    response = with_retry(variant.url, fetch=fetch, limiter=limiter, sleep=sleep,
                          max_body=max_body, headers=_conditional_headers(known.get('etag')))
    requests_made = response.get('attempts', 1)
    report['attempts'] = requests_made
    report['status'] = response.get('status')

    body = None
    if response.get('status') == 304:
        report['conditional'] = True
        body = _replay_snapshot(store, tenant, variant, known.get('snapshot'), adapter=adapter)
        if body is None:
            # The tag matched but the evidence is gone, so ask again
            # without the tag rather than report postings we cannot show.
            response = with_retry(variant.url, fetch=fetch, limiter=limiter, sleep=sleep,
                                  max_body=max_body)
            requests_made += response.get('attempts', 1)
            report['attempts'] = requests_made
            report['status'] = response.get('status')
        else:
            report['etag'] = known.get('etag')
            report['snapshot'] = known.get('snapshot')
            report['replayed'] = True

    if body is None:
        if not response['ok']:
            status = response.get('status')
            report['error'] = response.get('error') or 'no response'
            kind = (FETCH_NOT_FOUND if status == 404 else
                    FETCH_HTTP_ERROR if status else FETCH_UNREACHABLE)
            return {'status': kind, 'report': report, 'positions': [],
                    'requests': requests_made}
        body = response['text']
        report['bytes'] = len(body.encode())
        report['etag'] = (response.get('headers') or {}).get('etag')
        # A body that stopped exactly at the cap is a body we cut, and
        # the parser's complaint would blame the provider for it. Named
        # rather than counted as a parse failure, so the spec's
        # parse-success rate measures the provider's feeds and not our
        # own ceiling. See FEED_MAX_BODY.
        if report['bytes'] >= max_body:
            report['error'] = (f"the response reached the {max_body}-byte body cap, so what "
                               'arrived is a truncated feed rather than a broken one')
            return {'status': FETCH_TRUNCATED, 'report': report, 'positions': [],
                    'requests': requests_made}

    try:
        positions = (parser or adapter.parse_feed)(body)
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'[:300]
        return {'status': FETCH_PARSE_ERROR, 'report': report, 'positions': [],
                'requests': requests_made}

    report['positions'] = len(positions) if isinstance(positions, (list, tuple)) else 1
    if not report['snapshot']:
        path, created = store.write_feed_snapshot(tenant, run, variant.slug,
                                                  adapter.compress(body),
                                                  suffix=adapter.SNAPSHOT_SUFFIX)
        report['snapshot'] = str(path.relative_to(store.root))
        report['snapshot_created'] = created
    return {'status': FETCH_OK, 'report': report, 'positions': positions,
            'requests': requests_made}
