"""Fetching one tenant's feeds: retries, conditional requests, locating.

Provider-agnostic orchestration over a provider mapper. `careeros.feeds.
personio` supplies the URLs, the parse and the mapping; this module
supplies everything that would be identical for Greenhouse: the retry
policy, the conditional request, the raw snapshot, the geocode pass and
the per-tenant fetch status.

NO NETWORK OF ITS OWN. `fetch` is a callable with
`scripts/polite_http.request_text`'s signature and return shape. The
runner wires the real one in; a test passes a transport that answers out
of a recorded fixture. That is why the whole adapter is testable offline
against real feed shapes.

## Politeness, per the spec

  * One request a second, which is the shared `polite_http.RateLimiter`
    the runner passes in. Each tenant is a distinct host, so a per-host
    limit would allow a burst across tenants; the runner therefore uses
    ONE limiter for the whole run, which is a global cap of one request a
    second and strictly politer than the spec asks for.
  * `robots.txt` on a Personio career site was checked live on
    2026-10-17 and is `User-agent: * / Allow: /`. So no exception
    reasoning is needed for the feeds themselves -- the one robots
    tension in this ticket is the Common Crawl index, and that is
    recorded in `careeros.feeds.discovery`.
  * Retries are exponential from one second and capped, per the spec's
    "no retries faster than exponential backoff after errors".

## Conditional requests

The spec asks for them "where the server supports them, so unchanged
feeds cost nothing". Personio serves an `ETag` on the XML feed (verified
live 2026-10-17), so the stored tag goes back as `If-None-Match` and a
304 means the feed is byte-identical to the last one stored.

A 304 carries no body, so the postings it implies are read back from the
last raw snapshot for that tenant and language and re-parsed. That keeps
closure detection correct: a 304 is a SUCCESSFUL fetch that saw every
posting it saw last time, not a fetch that saw none of them. If the
snapshot it refers to is missing, the conditional request is retried
unconditionally rather than guessed at.
"""
import logging
import time

from careeros.feeds import geocode, personio, store as store_module

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
#: measured 2 212 621 bytes on 2026-10-17, so the shared cap truncated it
#: mid-element and the XML parser reported "unclosed token" -- a failure
#: that looked like a broken feed and was our own ceiling. 32 MB is the
#: same cap `scripts/seed_zefix_zurich.py` uses for its own bulk
#: responses: far out of the way of a real feed, still not unbounded.
FEED_MAX_BODY = 32_000_000

FETCH_TRUNCATED = 'truncated'

FETCH_OK = store_module.FETCH_OK
FETCH_NOT_FOUND = 'not_found'
FETCH_HTTP_ERROR = 'http_error'
FETCH_PARSE_ERROR = 'parse_error'
FETCH_UNREACHABLE = 'unreachable'


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

    Separate from `map_posting` because geocoding is not a Personio
    concern: a Greenhouse posting's office line goes through exactly this
    function. Returns a new dict; the input is not mutated.
    """
    offices, summary = geocode.geocode_offices(mapped.get('offices') or ())
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


def _replay_snapshot(store, tenant, language, snapshot_path, *, mapper):
    """The body behind a 304: the last raw snapshot for this tenant and
    language, or None when it is not on disk any more.

    `snapshot_path` is store-relative, which is how the tenant record
    holds it, so a store that moved directory still replays.
    """
    if not snapshot_path:
        return None
    path = store.root / snapshot_path
    if not path.exists():
        _logger.info('personio: %s/%s answered 304 but %s is gone; fetching unconditionally',
                     tenant, language, snapshot_path)
        return None
    try:
        return mapper.decompress(path.read_bytes())
    except (OSError, ValueError) as error:
        _logger.warning('personio: could not replay %s for %s/%s: %s',
                        snapshot_path, tenant, language, error)
        return None


def fetch_tenant(tenant, *, store, run, fetch, limiter=None, mapper=personio,
                 languages=personio.DEFAULT_LANGUAGES, hosts=personio.HOSTS,
                 conditional=None, at=None, guide_version=None, sleep=time.sleep):
    """Fetch, parse, map and locate every posting of one tenant.

    `conditional` is `{language: {'etag', 'snapshot'}}` from the tenant's
    own record, so a second run of an unchanged feed costs one
    conditional request and no parsing.

    Returns a result dict:

        {'tenant', 'fetch_status', 'error', 'host', 'languages': {...},
         'postings': [located, ...], 'publishes': {lang: bool},
         'parse_failures': [...], 'posting_failures': [...],
         'requests': int, 'etags': {...}}

    `parse_failures` is per FEED and `posting_failures` is per position,
    because the spec's 99% parse-success rate is counted over feeds.

    `fetch_status` is `ok` only when at least one language of one host
    gave a parseable feed. Everything else is a named failure, and a
    failure is what `store.record_run` refuses to count toward closure.
    """
    at = at or store_module.now()
    result = {'tenant': tenant, 'fetch_status': FETCH_UNREACHABLE, 'error': None, 'host': None,
              'languages': {}, 'postings': [], 'publishes': {}, 'parse_failures': [],
              'posting_failures': [], 'requests': 0, 'etags': {}, 'snapshots': {}}
    conditional = conditional or {}
    by_key = {}

    for host in hosts:
        for language in languages:
            # English is fetched on the first run of a tenant and then
            # only while it is known to carry postings, per the spec's
            # "a second call with language=en only if the tenant
            # publishes English postings". The first run is what finds
            # out, because an unsupported language answers 200.
            known = conditional.get(language, {})
            if language != languages[0] and known and known.get('publishes') is False:
                result['languages'][f'{host}:{language}'] = {
                    'skipped': f'this tenant publishes no {language} postings'}
                continue
            attempt = _fetch_one(tenant, host, language, mapper=mapper, fetch=fetch,
                                 limiter=limiter, store=store, run=run, known=known,
                                 sleep=sleep)
            result['requests'] += attempt['requests']
            result['languages'][f'{host}:{language}'] = attempt['report']
            if attempt['status'] != FETCH_OK:
                if result['fetch_status'] != FETCH_OK:
                    result['fetch_status'] = attempt['status']
                    result['error'] = attempt['report'].get('error')
                if attempt['status'] == FETCH_PARSE_ERROR:
                    result['parse_failures'].append({'tenant': tenant, 'host': host,
                                                     'language': language,
                                                     'reason': attempt['report'].get('error')})
                if attempt['status'] == FETCH_NOT_FOUND and language == languages[0]:
                    # No career site on this host at all, so every other
                    # language of it is one more 404. Worth skipping:
                    # measured on the trial, 33% of the tenants Common
                    # Crawl knows about no longer serve a feed, which is
                    # a third of any sweep's request budget.
                    break
                continue

            result['fetch_status'] = FETCH_OK
            result['host'] = result['host'] or host
            publishes = mapper.has_descriptions(attempt['positions'])
            result['publishes'][language] = publishes
            result['etags'][language] = {'etag': attempt['report'].get('etag'),
                                         'snapshot': attempt['report'].get('snapshot'),
                                         'publishes': publishes}
            if attempt['report'].get('snapshot'):
                result['snapshots'][f'{host}:{language}'] = attempt['report']['snapshot']

            for raw in attempt['positions']:
                try:
                    mapped = mapper.map_posting(raw, tenant=tenant, language=language, host=host)
                except ValueError as error:
                    # A posting-level failure, kept apart from
                    # `parse_failures` on purpose: the spec's parse-success
                    # rate is counted per FEED, and folding a position
                    # that could not be mapped into the feed failures
                    # would make one broken position look like a broken
                    # feed -- or several of them look like more broken
                    # feeds than were fetched.
                    result['posting_failures'].append({'tenant': tenant, 'host': host,
                                                       'language': language,
                                                       'reason': f'{error}'})
                    continue
                mapped['feed_snapshot'] = attempt['report'].get('snapshot')
                mapped['fetched_at'] = at
                mapped['run_id'] = run
                located = locate(mapped, guide_version=guide_version)
                by_key[located['key']] = _prefer(by_key.get(located['key']), located)
        if result['fetch_status'] == FETCH_OK:
            # `.de` answered, so `.com` is the same career site; see the
            # personio module docstring. The spec's "try .de first, then
            # .com" is satisfied without a second request per tenant.
            break

    result['postings'] = [by_key[key] for key in sorted(by_key)]
    return result


def _prefer(existing, candidate):
    """One posting id, two feed languages: which one is THE record.

    The spec asks for German first, so the first language wins -- but
    only if it actually carries posting text. A tenant that publishes in
    English alone still answers the German feed with 200 and every
    `jobDescriptions` empty (see the personio docstring), and a golden-set
    posting with no text is useless. So a later language with text beats
    an earlier one without, and the loser is kept beside the winner as a
    translation rather than thrown away.
    """
    if existing is None:
        return candidate
    winner, loser = ((candidate, existing)
                     if candidate.get('has_description') and not existing.get('has_description')
                     else (existing, candidate))
    translations = dict(winner.get('translations') or {})
    translations[loser['feed_language']] = {
        'title': loser['title'], 'description': loser['description'],
        'content_hash': loser['content_hash'], 'has_description': loser['has_description']}
    winner = dict(winner)
    winner['translations'] = translations
    return winner


def _fetch_one(tenant, host, language, *, mapper, fetch, limiter, store, run, known, sleep,
               max_body=FEED_MAX_BODY):
    """One (host, language) feed: request, snapshot, parse."""
    url = mapper.feed_url(tenant, language=language, host=host)
    report = {'url': url, 'status': None, 'error': None, 'bytes': 0, 'positions': 0,
              'etag': None, 'snapshot': None, 'conditional': False, 'attempts': 0}
    response = with_retry(url, fetch=fetch, limiter=limiter, sleep=sleep, max_body=max_body,
                          headers=_conditional_headers(known.get('etag')))
    requests_made = response.get('attempts', 1)
    report['attempts'] = requests_made
    report['status'] = response.get('status')

    body = None
    if response.get('status') == 304:
        report['conditional'] = True
        body = _replay_snapshot(store, tenant, language, known.get('snapshot'), mapper=mapper)
        if body is None:
            # The tag matched but the evidence is gone, so ask again
            # without the tag rather than report postings we cannot show.
            response = with_retry(url, fetch=fetch, limiter=limiter, sleep=sleep,
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
        # the XML parser's "unclosed token" would blame the tenant for
        # it. Named rather than counted as a parse failure, so the
        # spec's parse-success rate measures Personio's feeds and not
        # our own ceiling. See FEED_MAX_BODY.
        if report['bytes'] >= max_body:
            report['error'] = (f"the response reached the {max_body}-byte body cap, so what "
                               'arrived is a truncated feed rather than a broken one')
            return {'status': FETCH_TRUNCATED, 'report': report, 'positions': [],
                    'requests': requests_made}

    try:
        positions = mapper.parse_feed(body)
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'[:300]
        return {'status': FETCH_PARSE_ERROR, 'report': report, 'positions': [],
                'requests': requests_made}

    report['positions'] = len(positions)
    if not report['snapshot']:
        path, created = store.write_feed_snapshot(tenant, run, language, mapper.compress(body))
        report['snapshot'] = str(path.relative_to(store.root))
        report['snapshot_created'] = created
    return {'status': FETCH_OK, 'report': report, 'positions': positions,
            'requests': requests_made}
