"""Tenant discovery: who has a career site on which platform, and is it
in Zurich.

A tenant is a company's account on a hiring platform -- `acme` in
`acme.jobs.personio.de`, in `boards.greenhouse.io/acme`, in
`jobs.lever.co/acme`. Owner ruling 2026-10-17 makes this the PRIMARY way
companies enter the CareerOS universe (the Zefix bulk seed is parked), so
the routes below are what the universe grows through -- and, since
CAREER-54, what the ATS platform map is built from.

PROVIDER-AGNOSTIC SINCE CAREER-54. Every function here takes an adapter
(`careeros.feeds.base`'s contract) and asks it two questions: which URL
patterns to query a crawl index for (`CDX_PATTERNS`) and what tenant a
URL names (`tenant_from_url`). The default adapter is Personio's,
because CAREER-53's runner and tests call these functions with one
argument; every caller added since names its provider.

## The routes, in the spec's own priority order

1. **The existing universe.** Every posting URL already parsed as this
   provider gives a tenant, and so does a company's stored website.
   `org_intake.ats.detect_ats` is what reads both -- it already
   recognises all five CAREER-54 providers plus Personio, Workday,
   Teamtailor, Join and Refline, and already extracts the tenant, so
   nothing here re-implements that.
2. **Company websites.** A careers page that links, iframes or scripts
   to a provider's board names its tenant in the host or the path.
   `detect_ats` only answers for a POSTING-shaped URL (it wants
   `/job/<id>` or a `jobId` parameter, deliberately -- see its docstring
   on lookalike hosts), so a bare `https://acme.jobs.personio.de/` or
   `https://boards.greenhouse.io/acme` link needs each adapter's own
   board-URL reading, and `how` says which of the two it used.
3. **The Common Crawl URL index.** See the source check below.
4. **The Zefix seed is PARKED** (owner ruling 2026-10-17). The staging
   file is used for dedupe by name only, never as a discovery route:
   Zefix carries no domain for any company, so it cannot propose a
   tenant without guessing one.

Rejected, and why: **Google and LinkedIn are not scraped.** Both forbid
it in their terms, both would need a key or a browser, and a search
engine's result page is not a source we could cite in a value record.
**No tenant-id guessing either** -- generating `{company-slug}` from a
company name and probing it would be a dictionary attack on someone
else's host, would produce name-collision false positives, and would
make the request count unbounded. Discovery only follows links that
exist.

## Source check: Common Crawl

  * **What it is.** A free, public URL index of a web crawl, queryable
    over the CDX API at `https://index.commoncrawl.org/{crawl}-index`.
    No key. `collinfo.json` lists the available crawls (128 of them as
    of 2026-10-17, back to 2013).
  * **Terms, read 2026-10-17** (https://commoncrawl.org/terms-of-use).
    They grant a "limited, non-assignable, non-transferable,
    non-sublicensable, non-exclusive" licence to access and use the
    Service, impose NO attribution requirement, and carry three
    restrictions that matter here. (1) Users must not collect or harvest
    "any personally identifiable information or personal information for
    use separately from the Crawled Content" -- this module reads host
    names and path segments out of the index and nothing else, never a
    crawled page body and never a person. (2) Users must respect
    third-party copyrights in the material, and the crawled content "may
    be subject to separate terms of use" from its owners -- which is why
    the tenant that comes out of the index is then read from the
    provider's own documented feed under the provider's own terms, not
    from Common Crawl's copy of the page. (3) The terms call out use "in
    connection with artificial intelligence, machine learning, or other
    similar technologies, including ... large language models" as
    something the user remains liable for. **That last one is worth the
    owner's attention**, because the golden set this pool feeds exists to
    evaluate a classifier: what is used here is a list of HOST NAMES and
    PATH SEGMENTS, no crawled content reaches the pool, and the posting
    text comes from the provider -- but the sentence is in the terms and
    the owner should read it rather than take this reading on trust
    (recorded in data/ats/TRIAL_REPORT.md).
  * **robots.txt, checked live 2026-10-17.**
    `index.commoncrawl.org/robots.txt` is `Disallow: /` for every agent,
    with an allow-list of six static files including `collinfo.json`.
    The CDX endpoint is therefore disallowed to a page crawler. Applied
    here is the reasoning the owner already accepted for the LINDAS
    SPARQL route (`scripts/seed_zefix_zurich.py`): robots.txt governs
    crawlers walking pages, not a service's own documented machine API,
    and the CDX API is exactly that -- Common Crawl publishes it as the
    way to query the index programmatically. The call stays at one
    request a second through the shared limiter, identifies itself with
    the shared CareerOS user agent, and is capped. If the owner
    disagrees, `--from-file` replays a saved index response and no live
    call happens.
  * **What it actually returns, measured.** Personio, 2026-10-17: a
    domain match on both hosts against `CC-MAIN-2026-39` gave 13 927
    indexed URLs across **1 448 distinct tenants**; adding
    `CC-MAIN-2026-34` brought it to **2 467**. The five providers of
    CAREER-54 are measured in `data/ats/TRIAL_REPORT.md`. The API is
    unreliable in two ways that the code has to handle and did not at
    first: it **502s and 504s** (rate limiting rather than slowness),
    and it sometimes returns a **truncated body**. Both are measured and
    reported rather than absorbed.
  * **PAGING IS WHAT MAKES IT COMPLETE, and `limit` is a trap.** The
    index is sorted by SURT key, which puts `recruitee.com/` before
    `anything.recruitee.com/`, so a query with `limit=500` against a
    provider that also runs a marketing site returns 500 marketing-page
    URLs and **zero tenants**. Measured 2026-10-17: that exact query
    found 0 Recruitee tenants, and the same query paged properly found
    **585**. So pages are walked and `limit` is never used.

## Zurich is filtered at the POSTING level, not the tenant level

The spec's own words for route 3 are "this gives a list of all tenants
seen on the web, Swiss or not; the Zurich filter later sorts them", and
that is what this module does: discovery decides nothing about location.
A tenant is `candidate` until its feed has been fetched, then
`confirmed_zurich` if any posting's office geocodes to canton Zurich, or
`no_zurich_office` if none does. The reason is that the feed is the only
place a tenant's offices are stated at all -- a subdomain name says
nothing about geography. The cost is that confirming a tenant means
fetching it, which is why `--max-tenants` and `--sample` exist.

## Dedupe against the Zefix staging file

By normalised name, repeating the capability's own normalisation rule
(fold case, every run of non-alphanumerics to one space) the same way
`scripts/seed_zefix_zurich.py` does and for the same reason its own note
gives: `identity._normalize_name` is private and the public matcher
re-normalises every record on every call, which would be quadratic over
a 5 000-row staging file. The rule is one line and the two callers have
to agree on it, so it is `_normalized_name` below and nothing else.
A name-only match is a CANDIDATE and never a fact (PROJECT.md's
ambiguity rule, and the Zefix seeder's own note: "Meier AG" in Zurich is
several unrelated companies). The match is recorded with
`confident: false` and the UID it would point at, for the owner to accept
or reject.
"""
import json
import logging
import re
import time
from urllib.parse import urlencode

from careeros.feeds import personio

_logger = logging.getLogger(__name__)


def _normalized_name(name):
    """The capability's normalisation rule, repeated rather than called;
    see the docstring's dedupe note on why."""
    return re.sub(r'[^a-z0-9]+', ' ', (name or '').casefold()).strip()

#: The Common Crawl index API. `collinfo.json` is the one call that needs
#: no crawl id.
CDX_BASE = 'https://index.commoncrawl.org'
CDX_COLLECTIONS = f'{CDX_BASE}/collinfo.json'
CDX_TERMS = 'https://commoncrawl.org/terms-of-use'

#: The default adapter's own patterns, kept as a module name because
#: CAREER-53's tests and runner read it. Every other provider's patterns
#: come from its adapter's `CDX_PATTERNS`.
CDX_DOMAINS = personio.HOSTS

#: The CDX API answers 502/504 fairly often on a domain-wide query and
#: succeeds on a retry (measured 2026-10-17). Backoff is exponential from
#: two seconds, per the spec's politeness rule ("no retries faster than
#: exponential backoff after errors"). Six attempts backing off 2, 4, 8,
#: 16, 32 seconds is two minutes of patience per page, which is the
#: difference between a discovery run that works and one that reports
#: zero tenants.
CDX_ATTEMPTS = 6
CDX_BACKOFF = 2.0
#: An index page for a busy domain is megabytes and the endpoint is slow,
#: so it gets its own timeout rather than the shared 20-second default.
CDX_TIMEOUT = 180

#: A body cap of its own, for the same reason `fetch.FEED_MAX_BODY`
#: exists -- and it is what CAREER-53's "the CDX API sometimes returns a
#: truncated body" finding actually was. `polite_http` inherits
#: `org_intake.fetch.MAX_BODY_SIZE` (2 MB), and one index page for
#: `job-boards.greenhouse.io` is bigger than that: the first CAREER-54
#: discovery run reported FOUR truncated pages in a row, each cut after
#: 11 000 lines, which is 2 MB of JSONL and not a CDN fault. With this
#: cap a truncation report means what it says. The Personio trial's one
#: truncated page was almost certainly the same thing, and its report is
#: corrected in `data/ats/TRIAL_REPORT.md`.
CDX_MAX_BODY = 64_000_000

# Tenant status vocabulary. `candidate` is the only status discovery can
# reach on its own; the rest need a feed.
CANDIDATE = 'candidate'
CONFIRMED_ZURICH = 'confirmed_zurich'
NO_ZURICH_OFFICE = 'no_zurich_office'
SKIPPED = 'skipped'


def tenant_from_url(url, *, adapter=personio):
    """`{'tenant', 'host', 'how'}` for one provider's URL, or None.

    The reading itself lives in the adapter, because what counts as a
    board URL is the one thing every provider does differently. `how` is
    `posting_url` when `detect_ats` recognised a posting-shaped URL (the
    confident reading) and `board_url`, `host_pattern`, `embed_url` or
    `api_url` when a weaker pattern said so. The distinction is kept
    because a report should be able to tell them apart.
    """
    return adapter.tenant_from_url(url)


def tenants_from_urls(urls, *, discovered_via, company=None, adapter=personio):
    """Every tenant of one provider named by a list of URLs."""
    found = {}
    for url in urls or ():
        match = tenant_from_url(url, adapter=adapter)
        if not match:
            continue
        found.setdefault(match['tenant'], {
            'tenant': match['tenant'], 'host': match['host'], 'provider': adapter.PROVIDER,
            'discovered_via': discovered_via, 'evidence': url, 'how': match['how'],
            'company_name': company,
        })
    return found


def tenants_from_vault(companies, jobs=(), *, adapter=personio):
    """Route 1: what the universe already knows. No network.

    Reads the stored website and the stored identifiers of every company
    and the URL of every job. The live vault is opened read-only by the
    caller; nothing here writes.
    """
    found = {}
    for record in companies or ():
        urls = [record.get('website')]
        for item in record.get('identifiers') or ():
            if item.get('type') == 'ats_tenant' and str(item.get('value') or '').startswith(
                    f'{adapter.PROVIDER}:'):
                tenant = str(item['value']).split(':', 1)[1]
                if re.fullmatch(adapter.TENANT_ID, tenant):
                    found.setdefault(tenant, {
                        'tenant': tenant, 'host': _default_host(adapter),
                        'provider': adapter.PROVIDER,
                        'discovered_via': 'vault_identifier',
                        'evidence': item['value'], 'how': 'stored_identifier',
                        'company_name': record.get('name')})
        for source in record.get('sources') or ():
            urls.append(source.get('url'))
        found.update({key: value for key, value in tenants_from_urls(
            urls, discovered_via='vault_company', company=record.get('name'),
            adapter=adapter).items()
            if key not in found})
    for job in jobs or ():
        if job.get('ats_provider') == adapter.PROVIDER and job.get('ats_tenant'):
            tenant = str(job['ats_tenant'])
            if re.fullmatch(adapter.TENANT_ID, tenant):
                found.setdefault(tenant, {
                    'tenant': tenant, 'host': _default_host(adapter),
                    'provider': adapter.PROVIDER,
                    'discovered_via': 'vault_job', 'evidence': job.get('url'),
                    'how': 'stored_posting', 'company_name': job.get('company_name')})
        found.update({key: value for key, value in tenants_from_urls(
            [job.get('url'), job.get('normalized_url'), job.get('original_url')],
            discovered_via='vault_job', adapter=adapter).items() if key not in found})
    return found


def _default_host(adapter):
    """The host to record for a tenant found without one -- a stored
    `ats_tenant` identifier names no URL. The adapter's first CDX
    pattern, which is its own career-site host."""
    patterns = getattr(adapter, 'CDX_PATTERNS', ())
    return patterns[0][0] if patterns else adapter.PROVIDER


def cdx_collections(*, fetch, limiter=None):
    """The crawls the index API offers, newest first. The one CDX call
    robots.txt allows outright."""
    result = fetch(CDX_COLLECTIONS, limiter=limiter)
    if not result['ok']:
        raise RuntimeError(f"Common Crawl collinfo failed: {result['error']}")
    return json.loads(result['text'])


def _cdx_query(crawl, domain, **params):
    query = {'url': domain, 'matchType': 'domain', 'output': 'json'}
    query.update(params)
    return f'{CDX_BASE}/{crawl}-index?{urlencode(query)}'


def cdx_page_count(crawl, domain, *, fetch, limiter=None, match_type='domain', page_size=None):
    """How many pages the index has for this pattern, and the page size.

    `page_size` is the index's own `pageSize` (blocks per page), which
    the truncation recovery below asks for in ones.
    """
    extra = {'pageSize': str(page_size)} if page_size else {}
    url = _cdx_query(crawl, domain, matchType=match_type, showNumPages='true', **extra)
    result = _with_retry(url, fetch=fetch, limiter=limiter)
    if not result['ok']:
        return {'pages': 0, 'error': result['error'], 'attempts': result['attempts']}
    try:
        data = json.loads(result['text'])
    except ValueError:
        return {'pages': 0, 'error': 'showNumPages did not answer JSON',
                'attempts': result['attempts']}
    return {'pages': int(data.get('pages') or 0), 'page_size': data.get('pageSize'),
            'blocks': data.get('blocks'), 'error': None, 'attempts': result['attempts']}


def _with_retry(url, *, fetch, limiter=None, attempts=CDX_ATTEMPTS, sleep=time.sleep):
    """One CDX call with exponential backoff. The API 502s and 504s often
    enough that a single attempt is not a measurement (see the
    docstring)."""
    last = {'ok': False, 'error': 'not attempted', 'status': None, 'text': ''}
    for attempt in range(1, attempts + 1):
        last = fetch(url, limiter=limiter, timeout=CDX_TIMEOUT, max_body=CDX_MAX_BODY)
        if last['ok']:
            return {**last, 'attempts': attempt}
        if attempt < attempts:
            sleep(CDX_BACKOFF * (2 ** (attempt - 1)))
    return {**last, 'attempts': attempts}


def tenants_from_cdx_lines(lines, *, discovered_via, adapter=personio, extract=None):
    """Tenants out of CDX JSONL, with a truncation guard.

    Returns `(tenants, stats)`. The guard matters: the CDX API is served
    through a CDN that sometimes returns a short body, and a page that
    ends mid-object would silently drop every tenant after the cut. A
    line that is not parseable JSON is counted in `malformed`, and
    `truncated` is True when it was the LAST line -- which is what a cut
    body looks like and what makes the whole page untrustworthy.

    `extract` overrides the adapter's own reading, which is how the ATS
    platform map counts the tenants of a provider that has no adapter
    (Workday above all).
    """
    read = extract or (lambda url: adapter.tenant_from_url(url))
    provider = adapter.PROVIDER if extract is None else None
    tenants = {}
    stats = {'urls': 0, 'malformed': 0, 'truncated': False}
    rows = [line.strip() for line in lines if line.strip()]
    for index, line in enumerate(rows):
        try:
            entry = json.loads(line)
        except ValueError:
            stats['malformed'] += 1
            if index == len(rows) - 1:
                stats['truncated'] = True
            continue
        stats['urls'] += 1
        match = read(entry.get('url', ''))
        if match:
            tenants.setdefault(match['tenant'], {
                'tenant': match['tenant'], 'host': match['host'],
                'provider': match.get('provider') or provider,
                'discovered_via': discovered_via,
                'evidence': entry['url'], 'how': match['how'],
                'company_name': None})
    return tenants, stats


def cdx_tenants(crawl, *, fetch, limiter=None, adapter=personio, patterns=None, extract=None,
                max_pages=None, sleep=time.sleep, keep_lines=True):
    """Route 3: every tenant of one provider the crawl index has seen.

    Returns `(tenants, report)`. The report carries the page count, the
    attempts each page took and every page that never came back, because
    the spec's open question is "how many tenants does the Common Crawl
    query return" and a number with unknown gaps in it is not an answer.

    A page whose body came back truncated is counted as FAILED and its
    tenants are still kept: dropping the tenants would lose real ones,
    and not reporting the failure would make the count look complete.
    """
    patterns = patterns or adapter.CDX_PATTERNS
    tenants = {}
    report = {'crawl': crawl, 'provider': adapter.PROVIDER if extract is None else None,
              'domains': [pattern[0] for pattern in patterns], 'pages': [], 'urls': 0,
              'failed_pages': 0, 'truncated_pages': 0, 'malformed_lines': 0,
              'recovered_pages': [], 'terms': CDX_TERMS, 'raw_lines': []}
    for domain, match_type in patterns:
        meta = cdx_page_count(crawl, domain, fetch=fetch, limiter=limiter, match_type=match_type)
        pages = meta['pages'] if max_pages is None else min(meta['pages'], max_pages)
        # `blocks` is how many index blocks the crawl holds for this
        # host, and it is the one number here that does NOT depend on how
        # much of the index a capped run read. It is the honest way to
        # compare two providers' size in a crawl: measured 2026-10-17,
        # `boards.greenhouse.io` + `job-boards.greenhouse.io` hold 29
        # blocks and `jobs.lever.co` holds 1, which is a fact about the
        # index and not yet a fact about market share.
        report['pages'].append({'domain': domain, 'match_type': match_type,
                                'available': meta['pages'], 'queried': pages,
                                'blocks': meta.get('blocks'), 'page_size': meta.get('page_size'),
                                'error': meta.get('error'), 'attempts': meta.get('attempts')})
        block_size = meta.get('page_size') or DEFAULT_PAGE_SIZE
        for page in range(pages):
            url = _cdx_query(crawl, domain, matchType=match_type, fl='url', page=str(page))
            result = _with_retry(url, fetch=fetch, limiter=limiter, sleep=sleep)
            if not result['ok']:
                report['failed_pages'] += 1
                _logger.warning('common crawl: %s page %s failed after %s attempts: %s',
                                domain, page, result['attempts'], result['error'])
                continue
            if keep_lines:
                report['raw_lines'].extend(result['text'].splitlines())
            found, stats = tenants_from_cdx_lines(result['text'].splitlines(),
                                                  discovered_via=f'common_crawl:{crawl}',
                                                  adapter=adapter, extract=extract)
            report['urls'] += stats['urls']
            report['malformed_lines'] += stats['malformed']
            if stats['truncated']:
                report['truncated_pages'] += 1
                _logger.warning('common crawl: %s page %s came back truncated after %s lines; '
                                'its tenants are kept and the page is re-read block by block',
                                domain, page, stats['urls'])
                recovered, recovery = _recover_page(
                    crawl, domain, page, match_type=match_type, block_size=block_size,
                    fetch=fetch, limiter=limiter, sleep=sleep, adapter=adapter,
                    extract=extract, report=report, keep_lines=keep_lines)
                found.update({key: value for key, value in recovered.items()
                              if key not in found})
                report['recovered_pages'].append(recovery)
                if not recovery['complete']:
                    report['failed_pages'] += 1
            tenants.update({key: value for key, value in found.items() if key not in tenants})
    report['tenants'] = len(tenants)
    return tenants, report


#: The index's own default blocks-per-page, used to work out which
#: single-block pages one truncated page covers.
DEFAULT_PAGE_SIZE = 5


def _recover_page(crawl, domain, page, *, match_type, block_size, fetch, limiter, sleep,
                  adapter, extract, report, keep_lines):
    """Re-read one truncated page as single blocks.

    WHY THIS EXISTS. The index server returns a short body on its
    biggest pages: measured 2026-10-17 on `job-boards.greenhouse.io`,
    where every page of five blocks came back cut after 2 300 to 11 900
    of its lines, with no error and no pattern. A body cap of our own was
    ruled out first (see `CDX_MAX_BODY`); raising it to 64 MB changed
    nothing, so the truncation is the service's.

    A page of five blocks that truncates at line 2 300 loses most of its
    URLs. The same range read as five pages of ONE block is five smaller
    responses, and a response that is a fifth of the size is far more
    likely to arrive whole -- and when one of them still truncates, the
    loss is one block instead of five. That is the whole trick:
    `pageSize=1` and `page = page * block_size + offset`.

    Returns `(tenants, report)`. The report says how many blocks were
    re-read, how many of them still truncated, and therefore whether the
    page is `complete` -- so a count never claims to be a census when it
    is not.
    """
    tenants = {}
    recovery = {'domain': domain, 'page': page, 'blocks': block_size, 'blocks_read': 0,
                'blocks_truncated': 0, 'urls': 0, 'complete': False}
    for offset in range(block_size):
        url = _cdx_query(crawl, domain, matchType=match_type, fl='url',
                         pageSize='1', page=str(page * block_size + offset))
        result = _with_retry(url, fetch=fetch, limiter=limiter, sleep=sleep)
        if not result['ok']:
            # A block past the end of the index answers 404, which is an
            # answer and not a loss: `pages * blocks` over-counts when
            # the last page is partial.
            if result.get('status') == 404:
                recovery['complete'] = recovery['blocks_truncated'] == 0
                break
            recovery['blocks_truncated'] += 1
            continue
        recovery['blocks_read'] += 1
        if keep_lines:
            report['raw_lines'].extend(result['text'].splitlines())
        found, stats = tenants_from_cdx_lines(result['text'].splitlines(),
                                             discovered_via=f'common_crawl:{crawl}',
                                             adapter=adapter, extract=extract)
        recovery['urls'] += stats['urls']
        report['urls'] += stats['urls']
        report['malformed_lines'] += stats['malformed']
        if stats['truncated']:
            recovery['blocks_truncated'] += 1
            _logger.warning('common crawl: %s page %s block %s is still truncated after %s '
                            'lines', domain, page, offset, stats['urls'])
        tenants.update({key: value for key, value in found.items() if key not in tenants})
    else:
        recovery['complete'] = recovery['blocks_truncated'] == 0
    _logger.info('common crawl: %s page %s re-read as %s block(s), %s still truncated, '
                 '%s URL(s) recovered', domain, page, recovery['blocks_read'],
                 recovery['blocks_truncated'], recovery['urls'])
    return tenants, recovery


def merge_tenants(stored, found, *, first_seen):
    """Fold newly found tenants into what the store holds.

    Idempotent, and never downgrades: a tenant already `confirmed_zurich`
    stays confirmed when a second route finds it again, and its
    `first_seen` is the first run that saw it. A second route IS recorded,
    under `also_discovered_via`, because "three routes found this tenant"
    is the kind of thing a discovery report should be able to say.
    """
    merged = {key: dict(value) for key, value in stored.items()}
    added = []
    for tenant, entry in sorted(found.items()):
        existing = merged.get(tenant)
        if existing is None:
            merged[tenant] = {**entry, 'first_seen': first_seen, 'status': CANDIDATE,
                              'status_reason': 'discovered; the feed has not been fetched yet',
                              'also_discovered_via': []}
            added.append(tenant)
            continue
        routes = list(existing.get('also_discovered_via') or ())
        if (entry['discovered_via'] != existing.get('discovered_via')
                and entry['discovered_via'] not in routes):
            routes.append(entry['discovered_via'])
        existing['also_discovered_via'] = routes
        if not existing.get('company_name') and entry.get('company_name'):
            existing['company_name'] = entry['company_name']
    return merged, added


def zefix_matches(tenants, seeded):
    """Name-only dedupe against the parked Zefix staging file.

    A tenant's company name -- which comes from its feed or from the
    vault record that named it -- normalised by `_normalized_name` and
    looked up against the seeded Zurich entities. Returns
    `{tenant: match}`, where every match carries `confident: false`: a
    shared name is a candidate for the owner to confirm, not a duplicate
    (PROJECT.md's ambiguity rule).
    """
    by_name = {}
    for company in seeded or ():
        name = _normalized_name(company.get('name'))
        if name:
            by_name.setdefault(name, []).append(company)
    matches = {}
    for tenant, entry in (tenants or {}).items():
        name = _normalized_name(entry.get('company_name'))
        candidates = by_name.get(name) or []
        if not candidates:
            continue
        matches[tenant] = {
            'matched_on': 'name',
            'confident': False,
            'normalized_name': name,
            'candidates': [{'name': company.get('name'), 'uid': company.get('uid'),
                            'seat': company.get('seat')} for company in candidates],
            'note': ('a shared normalised name is a candidate, not a duplicate: several '
                     'unrelated Zurich entities share a name. The owner confirms or rejects.'),
        }
    return matches
