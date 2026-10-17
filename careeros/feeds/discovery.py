"""Tenant discovery: who has a Personio career site, and is it in Zurich.

A tenant is a company's Personio subdomain -- `acme` in
`acme.jobs.personio.de`. Owner ruling 2026-10-17 makes this the PRIMARY
way companies enter the CareerOS universe (Personio-first; the Zefix bulk
seed is parked), so the routes below are what the universe grows through.

## The routes, in the spec's own priority order

1. **The existing universe.** Every posting URL already parsed as
   Personio gives a tenant, and so does a company's stored website.
   `org_intake.ats.detect_ats` is what reads both -- it already
   recognises Personio and already extracts the tenant, so nothing here
   re-implements that.
2. **Company websites.** A careers page that links, iframes or scripts
   to `*.jobs.personio.de` names its tenant in the host. `detect_ats`
   only answers for a POSTING-shaped URL (it wants `/job/<id>` or a
   `jobId` parameter, deliberately -- see its docstring on lookalike
   hosts), so a bare `https://acme.jobs.personio.de/` link needs the
   host-pattern reading, and `tenant_from_url` says which of the two it
   used. A host-only match is still a tenant: the host IS the tenant id,
   and the feed probe is what confirms it either way.
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
    names out of the index and nothing else, never a crawled page body
    and never a person. (2) Users must respect third-party copyrights in
    the material, and the crawled content "may be subject to separate
    terms of use" from its owners -- which is why the tenant that comes
    out of the index is then read from Personio's own documented feed
    under Personio's own terms, not from Common Crawl's copy of the
    page. (3) The terms call out use "in connection with artificial
    intelligence, machine learning, or other similar technologies,
    including ... large language models" as something the user remains
    liable for. **That last one is worth the owner's attention**, because
    the golden set this pool feeds exists to evaluate a classifier: what
    is used here is a list of HOST NAMES, no crawled content reaches the
    pool, and the posting text comes from Personio -- but the sentence is
    in the terms and the owner should read it rather than take this
    reading on trust (recorded in data/personio/TRIAL_REPORT.md).
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
  * **What it actually returns, measured 2026-10-17.** A domain match on
    both Personio hosts against `CC-MAIN-2026-39` (September 2026):
    13 927 indexed URLs across **1 448 distinct tenants**. Adding
    `CC-MAIN-2026-34` brought the total to **2 467**, of which 1 019 were
    new -- so the marginal yield of another index is high and declining,
    and 128 indexes exist. The API is unreliable in two ways that the
    code has to handle and did not at first: it **504s** (one call in
    three in the morning, every call for several minutes later on, which
    is rate limiting rather than slowness), and it sometimes returns a
    **truncated body** -- one page came back cut after 943 of its lines.
    Both are measured and reported rather than absorbed.

## Zurich is filtered at the POSTING level, not the tenant level

The spec's own words for route 3 are "this gives a list of all tenants
seen on the web, Swiss or not; the Zurich filter later sorts them", and
that is what this module does: discovery decides nothing about location.
A tenant is `candidate` until its feed has been fetched, then
`confirmed_zurich` if any posting's office geocodes to canton Zurich, or
`no_zurich_office` if none does. The reason is that the feed is the only
place a tenant's offices are stated at all -- a subdomain name says
nothing about geography, and two and a half thousand mostly German
tenant ids cannot be filtered by inspection. The cost is that confirming
a tenant means fetching it, which is why `--max-tenants` and `--sample`
exist. Measured on the trial: 3% of the tenants whose feed is readable
have a Zurich office, and a third of all discovered tenants no longer
serve a feed at all.

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
from urllib.parse import urlsplit, urlencode

from careeros.feeds import personio

from org_intake.ats import detect_ats

_logger = logging.getLogger(__name__)


def _normalized_name(name):
    """The capability's normalisation rule, repeated rather than called;
    see the docstring's dedupe note on why."""
    return re.sub(r'[^a-z0-9]+', ' ', (name or '').casefold()).strip()

#: The Common Crawl index API, and the host pattern Personio tenants live
#: under. `collinfo.json` is the one call that needs no crawl id.
CDX_BASE = 'https://index.commoncrawl.org'
CDX_COLLECTIONS = f'{CDX_BASE}/collinfo.json'
CDX_TERMS = 'https://commoncrawl.org/terms-of-use'

#: Both Personio host suffixes, as the thing a CDX domain match is run
#: against. `jobs.personio.de` as a domain match also returns
#: `*.jobs.personio.de`, which is what gives the tenants.
CDX_DOMAINS = personio.HOSTS

#: The CDX API answers 504 fairly often on a domain-wide query and
#: succeeds on a retry (measured 2026-10-17). Backoff is exponential from
#: one second, per the spec's politeness rule ("no retries faster than
#: exponential backoff after errors").
#: Measured again later the same day: the API went from "504s one call in
#: three" to "504s every call for several minutes", so it is rate-limited
#: rather than merely slow. Six attempts backing off 2, 4, 8, 16, 32
#: seconds is two minutes of patience per page, which is the difference
#: between a discovery run that works and one that reports zero tenants.
CDX_ATTEMPTS = 6
CDX_BACKOFF = 2.0
#: An index page for a busy domain is a few hundred kilobytes and the
#: endpoint is slow, so it gets its own timeout rather than the shared
#: 20-second default.
CDX_TIMEOUT = 180

#: A tenant id as Personio issues them: lower-case, digits, hyphens.
TENANT_ID = re.compile(r'^[a-z0-9][a-z0-9-]*$')

# Tenant status vocabulary. `candidate` is the only status discovery can
# reach on its own; the rest need a feed.
CANDIDATE = 'candidate'
CONFIRMED_ZURICH = 'confirmed_zurich'
NO_ZURICH_OFFICE = 'no_zurich_office'
SKIPPED = 'skipped'


def tenant_from_url(url):
    """`{'tenant', 'host', 'how'}` for a Personio URL, or None.

    `how` is `posting_url` when `detect_ats` recognised a posting-shaped
    URL (the confident reading) and `host_pattern` when only the host
    said so. Both are kept because the second is how a careers-page link
    to a bare career site is found, and a report should be able to tell
    them apart.
    """
    match = detect_ats(url or '')
    host = (urlsplit(url or '').hostname or '').casefold()
    if match and match['provider'] == personio.PROVIDER:
        return {'tenant': match['tenant'], 'host': _host_suffix(host), 'how': 'posting_url'}
    for suffix in personio.HOSTS:
        if host.endswith('.' + suffix):
            tenant = host[:-(len(suffix) + 1)]
            # A nested label ("careers.acme.jobs.personio.de") is not a
            # tenant id and is not guessed at.
            if TENANT_ID.match(tenant):
                return {'tenant': tenant, 'host': suffix, 'how': 'host_pattern'}
    return None


def _host_suffix(host):
    for suffix in personio.HOSTS:
        if host == suffix or host.endswith('.' + suffix):
            return suffix
    return personio.HOSTS[0]


def tenants_from_urls(urls, *, discovered_via, company=None):
    """Every Personio tenant named by a list of URLs."""
    found = {}
    for url in urls or ():
        match = tenant_from_url(url)
        if not match:
            continue
        found.setdefault(match['tenant'], {
            'tenant': match['tenant'], 'host': match['host'],
            'discovered_via': discovered_via, 'evidence': url, 'how': match['how'],
            'company_name': company,
        })
    return found


def tenants_from_vault(companies, jobs=()):
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
                    f'{personio.PROVIDER}:'):
                tenant = str(item['value']).split(':', 1)[1]
                if TENANT_ID.match(tenant):
                    found.setdefault(tenant, {
                        'tenant': tenant, 'host': personio.HOSTS[0],
                        'discovered_via': 'vault_identifier',
                        'evidence': item['value'], 'how': 'stored_identifier',
                        'company_name': record.get('name')})
        for source in record.get('sources') or ():
            urls.append(source.get('url'))
        found.update({key: value for key, value in tenants_from_urls(
            urls, discovered_via='vault_company', company=record.get('name')).items()
            if key not in found})
    for job in jobs or ():
        if job.get('ats_provider') == personio.PROVIDER and job.get('ats_tenant'):
            tenant = str(job['ats_tenant'])
            if TENANT_ID.match(tenant):
                found.setdefault(tenant, {
                    'tenant': tenant, 'host': personio.HOSTS[0],
                    'discovered_via': 'vault_job', 'evidence': job.get('url'),
                    'how': 'stored_posting', 'company_name': job.get('company_name')})
        found.update({key: value for key, value in tenants_from_urls(
            [job.get('url'), job.get('normalized_url'), job.get('original_url')],
            discovered_via='vault_job').items() if key not in found})
    return found


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


def cdx_page_count(crawl, domain, *, fetch, limiter=None):
    """How many pages the index has for this domain, and the page size."""
    url = _cdx_query(crawl, domain, showNumPages='true')
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
    """One CDX call with exponential backoff. The API 504s often enough
    that a single attempt is not a measurement (see the docstring)."""
    last = {'ok': False, 'error': 'not attempted', 'status': None, 'text': ''}
    for attempt in range(1, attempts + 1):
        last = fetch(url, limiter=limiter, timeout=CDX_TIMEOUT)
        if last['ok']:
            return {**last, 'attempts': attempt}
        if attempt < attempts:
            sleep(CDX_BACKOFF * (2 ** (attempt - 1)))
    return {**last, 'attempts': attempts}


def tenants_from_cdx_lines(lines, *, discovered_via):
    """Tenants out of CDX JSONL, with a truncation guard.

    Returns `(tenants, stats)`. The guard matters: the CDX API is served
    through a CDN that sometimes returns a short body, and a page that
    ends mid-object would silently drop every tenant after the cut. A
    line that is not parseable JSON is counted in `malformed`, and
    `truncated` is True when it was the LAST line -- which is what a cut
    body looks like and what makes the whole page untrustworthy.
    """
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
        match = tenant_from_url(entry.get('url', ''))
        if match:
            tenants.setdefault(match['tenant'], {
                'tenant': match['tenant'], 'host': match['host'],
                'discovered_via': discovered_via,
                'evidence': entry['url'], 'how': match['how'],
                'company_name': None})
    return tenants, stats


def cdx_tenants(crawl, *, fetch, limiter=None, domains=CDX_DOMAINS, max_pages=None,
                sleep=time.sleep):
    """Route 3: every Personio tenant the crawl index has seen.

    Returns `(tenants, report)`. The report carries the page count, the
    attempts each page took and every page that never came back, because
    the spec's open question is "how many tenants does the Common Crawl
    query return" and a number with unknown gaps in it is not an answer.

    A page whose body came back truncated is counted as FAILED and its
    tenants are still kept: dropping the tenants would lose real ones,
    and not reporting the failure would make the count look complete.
    """
    tenants, report = {}, {'crawl': crawl, 'domains': list(domains), 'pages': [], 'urls': 0,
                           'failed_pages': 0, 'truncated_pages': 0, 'malformed_lines': 0,
                           'terms': CDX_TERMS, 'raw_lines': []}
    for domain in domains:
        meta = cdx_page_count(crawl, domain, fetch=fetch, limiter=limiter)
        pages = meta['pages'] if max_pages is None else min(meta['pages'], max_pages)
        report['pages'].append({'domain': domain, 'available': meta['pages'],
                                'queried': pages, 'error': meta.get('error'),
                                'attempts': meta.get('attempts')})
        for page in range(pages):
            url = _cdx_query(crawl, domain, fl='url', page=str(page))
            result = _with_retry(url, fetch=fetch, limiter=limiter, sleep=sleep)
            if not result['ok']:
                report['failed_pages'] += 1
                _logger.warning('common crawl: %s page %s failed after %s attempts: %s',
                                domain, page, result['attempts'], result['error'])
                continue
            report['raw_lines'].extend(result['text'].splitlines())
            found, stats = tenants_from_cdx_lines(result['text'].splitlines(),
                                                  discovered_via=f'common_crawl:{crawl}')
            report['urls'] += stats['urls']
            report['malformed_lines'] += stats['malformed']
            if stats['truncated']:
                report['truncated_pages'] += 1
                report['failed_pages'] += 1
                _logger.warning('common crawl: %s page %s came back truncated after %s lines; '
                                'its tenants are kept and the page is counted as failed',
                                domain, page, stats['urls'])
            tenants.update({key: value for key, value in found.items() if key not in tenants})
    report['tenants'] = len(tenants)
    return tenants, report


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

    A tenant's company name -- which comes from its feed's `subcompany`
    or from the vault record that named it -- normalised by
    `_normalized_name` and looked up against the seeded Zurich entities.
    Returns `{tenant: match}`, where every match
    carries `confident: false`: a shared name is a candidate for the
    owner to confirm, not a duplicate (PROJECT.md's ambiguity rule).
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
