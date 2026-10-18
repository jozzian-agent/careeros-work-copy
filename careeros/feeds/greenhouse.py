"""The Greenhouse adapter: the public job board API.

## The endpoint, verified against the provider's own documentation and
## against live boards on 2026-10-17

Documentation: https://docs.greenhouse.io/job-board.html (read
2026-10-17; `https://developers.greenhouse.io/job-board.html`, which the
brief names, answers 301 to it). It states in its own words that "Job
Board data is publicly available, so authentication is not required for
any GET endpoints".

    https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true

`content=true` is what makes this one request per tenant instead of one
per posting: without it a job carries no description, no departments and
no offices. Measured live on the `figma` board: 139 jobs, 88 KB without
content, one request. The per-job endpoint
(`/v1/boards/{board}/jobs/{id}`) exists and is NOT used -- 139 extra
requests for data the list already returned.

An `ETag` is served (`W/"dfd20445..."`), so conditional requests work and
an unchanged board costs one 304.

## What a job object carries, as seen live

`id`, `internal_job_id`, `requisition_id`, `title`, `updated_at`,
`first_published`, `absolute_url`, `company_name`, `language`,
`location: {name}`, `departments: [{name}]`, `offices: [{name, location}]`,
`content`, `metadata`, `pay_input_ranges`, `data_compliance`, and three
`ai_*` keys. Nothing is dropped silently: everything this adapter does
not map is either in a raw field below or in the raw feed snapshot.

**`content` is entity-escaped HTML** (`&lt;div class=&quot;...`), not
HTML. It is unescaped once and then read by the shared HTML-to-text
pass; feeding it in raw would store the markup as if it were prose.

**The location is free text and often several places in one string**:
`"San Francisco, CA * New York, NY * United States"` (the separator is a
bullet). So the office list this adapter hands the geocoder is
`offices[].name`, each `offices[].location` the board filled in, and
every bullet-separated part of `location.name` -- each tried
independently, which is exactly how the Zurich filter already works
("in scope when at least ONE office geocodes to canton Zurich").

## What it cannot state, and therefore does not pretend to

The board API has **no employment-type, no seniority and no workload
field**. A board may carry such a thing in `metadata`, but those are
per-board free-text questions ("Is this role remote?", "Visa
sponsorship") with no shared vocabulary, so mapping them onto
`contract` would be this module inventing a crosswalk. `metadata` is
kept raw under `metadata_raw` and `MAPPED_DIMENSIONS` names only what
this feed can actually say: the posting's own `language`, and a workload
read off a stated Swiss Pensum in the title or the text.

## Source check (owner rule)

  * Documented public API, no key, authentication explicitly not
    required (link and quote above).
  * `boards-api.greenhouse.io/robots.txt`, read 2026-10-17:
    `User-agent: * / Disallow: /embed/`. The API path used here is not
    `/embed/`, so robots allows it outright -- no exception reasoning is
    needed for this provider.
  * Terms: the board data is what a company publishes for applicants to
    read. The posting text belongs to the employer that wrote it; this
    repository stages it and republishes nothing.
"""
import html
import json
import logging
import re
import sys
from urllib.parse import parse_qsl, urlsplit

from careeros.feeds import base

from org_intake.ats import detect_ats

_logger = logging.getLogger(__name__)

PROVIDER = 'greenhouse'

DOC_URL = 'https://docs.greenhouse.io/job-board.html'
DOC_ACCESSED = '2026-10-17'

SNAPSHOT_SUFFIX = 'json'

API_HOST = 'boards-api.greenhouse.io'

#: The hosts a board token can be read out of. The first two are the
#: career-site hosts (`boards` is the old one, `job-boards` the current
#: embed host); the `.eu` pair exists for EU data residency and is
#: recognised but not crawled, because no EU-hosted board turned up in
#: the index sample and a CDX query per host is not free.
BOARD_HOSTS = ('boards.greenhouse.io', 'job-boards.greenhouse.io',
               'boards.eu.greenhouse.io', 'job-boards.eu.greenhouse.io')

CDX_PATTERNS = (('boards.greenhouse.io', 'host'), ('job-boards.greenhouse.io', 'host'))

#: A board token as Greenhouse issues them. Case is preserved rather than
#: folded: the token is a path segment and nothing documents it as
#: case-insensitive.
TENANT_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,80}')

#: Path segments that are a Greenhouse feature rather than a board, so
#: `.../embed/...` never becomes a tenant called "embed".
RESERVED = frozenset({'embed', 'v1', 'boards', 'jobs', 'api', 'applications', 'robots.txt',
                      'favicon.ico', 'error', 'assets'})

MAPPED_DIMENSIONS = ('language', 'workload_min', 'workload_max')

HASHED_FIELDS = ('posting_id', 'title', 'employer_name', 'departments', 'offices',
                 'location_raw', 'requisition_id', 'published_at', 'updated_at',
                 'description', 'metadata_raw')

#: The bullet Greenhouse joins several locations with, plus the ordinary
#: separators a board types by hand.
_LOCATION_SPLIT = re.compile(r'\s*(?:•|\||;|/| - |,\s*(?=and\b))\s*')


def feed_url(tenant, *, content=True):
    """The one request per board. `content=true` by default; see the
    docstring on why the per-job endpoint is not used."""
    if not re.fullmatch(TENANT_ID, tenant or ''):
        raise ValueError(f'not a Greenhouse board token: {tenant!r}')
    return (f'https://{API_HOST}/v1/boards/{tenant}/jobs'
            + ('?content=true' if content else ''))


def feed_variants(tenant):
    """One variant, which is the whole contract for this provider."""
    return [base.Variant(key=f'{API_HOST}:jobs', url=feed_url(tenant), slug='jobs',
                         host=API_HOST, group=API_HOST)]


def posting_url(tenant, posting_id):
    """The canonical link back. The API also returns `absolute_url` per
    job and that is preferred when present, because it carries the
    board's own host and its `gh_jid` parameter."""
    return f'https://job-boards.greenhouse.io/{tenant}/jobs/{posting_id}'


def tenant_from_url(url):
    """`{'tenant', 'host', 'how'}` for a Greenhouse URL, or None.

    Three readings, strongest first: `detect_ats` for a posting-shaped
    URL, the API path, and a bare board URL
    (`boards.greenhouse.io/acme`) or an embed (`...?for=acme`), which is
    what a company careers page actually links to.
    """
    match = detect_ats(url or '')
    parts = urlsplit(url or '')
    host = (parts.hostname or '').casefold()
    if match and match['provider'] == PROVIDER:
        return {'tenant': match['tenant'], 'host': host, 'how': 'posting_url'}
    segments = [segment for segment in (parts.path or '').split('/') if segment]
    if host == API_HOST and len(segments) >= 3 and segments[:2] == ['v1', 'boards']:
        return _candidate(segments[2], host, 'api_url')
    if host in BOARD_HOSTS:
        board = dict(parse_qsl(parts.query or '')).get('for')
        if board:
            return _candidate(board, host, 'embed_url')
        if segments:
            return _candidate(segments[0], host, 'board_url')
    return None


def _candidate(token, host, how):
    token = (token or '').strip()
    if token.casefold() in RESERVED or not re.fullmatch(TENANT_ID, token):
        return None
    return {'tenant': token, 'host': host, 'how': how}


def parse_feed(body):
    """A response body -> the raw job list, in the API's own order.

    Raises `ValueError` for JSON that is not a Greenhouse job board, so
    the fetcher can tell "this board does not exist" (a 404) from "this
    answer is not a board" -- which is what the parse-success rate is
    counted over.
    """
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
        raise ValueError('not a Greenhouse job board: the body has no "jobs" list')
    return list(data['jobs'])


def offices_of(raw):
    """The office lines the geocoder is given, in the order they are
    tried.

    `offices[].name` first (a board's own office list is the most
    structured thing here), then anything the board put in
    `offices[].location`, then each part of the free-text
    `location.name`. Duplicates are dropped and nothing is composed out
    of parts the API did not state.
    """
    offices = []
    for office in raw.get('offices') or ():
        for value in (office.get('name'), office.get('location')):
            if value and value not in offices:
                offices.append(value)
    location = ((raw.get('location') or {}).get('name') or '').strip()
    for part in ([location] + _LOCATION_SPLIT.split(location) if location else []):
        part = part.strip()
        if part and part not in offices:
            offices.append(part)
    return offices


def description_of(raw):
    """`content` as plain text. Unescaped once, then the shared pass."""
    content = raw.get('content') or ''
    return '\n'.join(base.html_to_text(html.unescape(content))).strip()


def map_posting(raw, *, tenant, variant=None, guide_version=None):
    """One job object -> the shared posting shape.

    Three layers, the same three every adapter has: the API's own words
    under their own keys, the D4 value records for what this feed can
    state, and the key, hash and provenance block from `base.finalize`.
    """
    posting_id = raw.get('id')
    if not posting_id:
        raise ValueError('a Greenhouse job with no id cannot be keyed')
    title = raw.get('title') or ''
    text = description_of(raw)
    mapped = {
        'provider': PROVIDER,
        'tenant': tenant,
        'posting_id': str(posting_id),
        'url': raw.get('absolute_url') or posting_url(tenant, posting_id),
        'feed_host': API_HOST,
        'feed_language': raw.get('language'),
        'title': title,
        'employer_name': raw.get('company_name'),
        'department': next((item.get('name') for item in raw.get('departments') or ()
                            if item.get('name')), None),
        'departments': [item.get('name') for item in raw.get('departments') or ()
                        if item.get('name')],
        'offices': offices_of(raw),
        'location_raw': (raw.get('location') or {}).get('name'),
        'requisition_id': raw.get('requisition_id'),
        'internal_job_id': raw.get('internal_job_id'),
        'published_at': raw.get('first_published'),
        'updated_at': raw.get('updated_at'),
        # Per-board free-text questions. Kept raw rather than mapped;
        # see the docstring on why they are not a contract vocabulary.
        'metadata_raw': raw.get('metadata') or [],
        'pay_input_ranges_raw': raw.get('pay_input_ranges') or [],
        'description_blocks': [{'name': None, 'text': text}] if text else [],
        'description': text,
        'has_description': bool(text),
    }
    pair, quote = base.pensum(title, text)
    mapped['values'] = {
        'language': base.language_record(
            raw.get('language'), raw_field='language', guide_version=guide_version,
            rule="the job object's own language field, which is the language the board "
                 'publishes the posting in rather than a detection of the text'),
        **base.workload_records(
            pair, raw=quote, raw_field='pensum_quote', guide_version=guide_version,
            rule=('a Pensum stated in the title or the posting text; the job board API has no '
                  'workload field of its own')
                 if pair else
                 ('the job board API states no workload and no Pensum is written in the title '
                  'or the text')),
    }
    return base.finalize(mapped, adapter=sys.modules[__name__])


compress = base.compress
decompress = base.decompress
