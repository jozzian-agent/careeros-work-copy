"""The SmartRecruiters adapter: the Posting API, with paging and details.

## The endpoints, verified 2026-10-17

Documentation:
https://developers.smartrecruiters.com/reference/v1listpostings.md (read
2026-10-17), which states "number of elements to return. max value is
100" for `limit`, `offset` for the skip, and that authentication is
optional -- "For public postings only, no authentication is needed".

    https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset=N
    https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}

**This is the one provider that needs two kinds of request**, and the
reason is in its data: the list endpoint states the location (city,
postal code, country, remote/hybrid), the employment type, the
experience level, the function, the industry, the language and the
visibility -- but **no description**. The text lives in the per-posting
endpoint, under `jobAd.sections` (`companyDescription`, `jobDescription`,
`qualifications`, `additionalInformation`), which is the only thing the
second request is for.

So the fetcher asks for a detail **only for the postings the Zurich
filter kept** (`fetch.DETAIL_IN_AREA`). That is not a shortcut: the list
already carries the location, so the filter can run before the text is
fetched, and a Zurich-only detail pass turns "492 extra requests for one
large employer" into a handful. A posting outside canton Zurich is
stored with its structured fields, `has_description: False` and a reason
saying the text was never fetched, which is a recorded state and not a
silent gap.

Measured live on 2026-10-17: `AveryDennison` has `totalFound: 492` over
five pages of 100; `smartrecruiters` itself answers 200 with
`totalFound: 0`, which is the "a tenant with an empty board stays valid"
case. An `ETag` is served on both endpoints.

## What a posting carries, as seen live

List: `id`, `name`, `uuid`, `jobAdId`, `refNumber`, `company:
{identifier, name}`, `releasedDate`, `location: {city, country,
postalCode, address, remote, hybrid, fullLocation}`, `industry`,
`department`, `function`, `typeOfEmployment`, `experienceLevel`,
`language: {code}`, `visibility`, `ref`,
`customField: [{fieldLabel, valueLabel}]`.
Detail adds: `jobAd.sections`, `postingUrl`, `applyUrl`, `jobId`,
`active`, `creator`.

`creator` (a recruiter's name and avatar) is **not stored**: it is a
person, and nothing here needs it. `customField` IS stored raw -- it is
the employer's own structured metadata ("Country of vacancy",
"Department") and the one place a workload sometimes appears.

## The fields that needed a decision

`typeOfEmployment.id` is SmartRecruiters' own closed vocabulary
(`permanent`, `temporary`, `contractor`, `internship`, ...) and maps onto
`contract`. `temporary` maps to `fixed_term` for the same reason as
Recruitee's (the label is a fixed-length employment, not placement
work), and that reading is flagged for the owner rather than presented
as settled.

`experienceLevel.id` names a SPAN as often as a step
(`mid_senior_level`, `associate`), so it goes through the same
three-case reader Personio's `seniority` uses: a step where the word
pins one, `unknown` with the word kept where it does not.

`location.remote` and `location.hybrid` are two booleans about one fact
and are read onto `work_model` in that order, with both recorded as the
evidence. Neither being set is read as `onsite`, because the API sets
them explicitly on the postings that are remote or hybrid.

## Source check (owner rule) -- THE ONE THAT NEEDS AN OWNER RULING

  * **Documented public API, no key.** Quote and link above.
  * **robots.txt says no.** `api.smartrecruiters.com/robots.txt`, read
    2026-10-17, is::

        User-agent: LinkedInBot
        Allow: /v1/companies/
        User-agent: *
        Disallow: /

    So the host disallows every agent except LinkedIn's from the exact
    path this adapter reads. That is a stronger signal than Common
    Crawl's blanket `Disallow: /` (which the owner accepted on
    2026-10-17 for a documented machine API): SmartRecruiters has
    explicitly allowed ONE named aggregator and excluded the rest.
  * **What this adapter does about it.** Nothing silently. The runner
    refuses to fetch this provider unless it is passed
    `--robots-exception smartrecruiters`, so no scheduled or unattended
    run can touch it by accident, and the refusal prints the robots
    lines above. The capped trial of 2026-10-17 was run WITH that flag
    (one request a second, our own identifying user agent, 150 tenants)
    so that the owner has the numbers to rule on; the ruling itself is
    question 1 of `data/ats/TRIAL_REPORT.md`. If the owner rules against
    it, this module and its fixtures stay and the provider is simply not
    fetched -- the platform map still counts its tenants, because those
    come from the crawl index and not from this host.
"""
import json
import logging
import re
import sys
from urllib.parse import urlencode, urlsplit

from careeros.feeds import base

from org_intake.ats import detect_ats

_logger = logging.getLogger(__name__)

PROVIDER = 'smartrecruiters'

DOC_URL = 'https://developers.smartrecruiters.com/reference/v1listpostings.md'
DOC_ACCESSED = '2026-10-17'

SNAPSHOT_SUFFIX = 'json'

API_HOST = 'api.smartrecruiters.com'
BOARD_HOSTS = ('jobs.smartrecruiters.com', 'careers.smartrecruiters.com')

CDX_PATTERNS = (('jobs.smartrecruiters.com', 'host'),)

#: A company identifier as SmartRecruiters issues them. Case matters and
#: is preserved: the live identifiers are `AveryDennison` and
#: `smartrecruiters`, and the path segment is what the API keys on.
TENANT_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}')

RESERVED = frozenset({'robots.txt', 'favicon.ico', 'v1', 'companies', 'postings',
                      'external-referrals', 'oneclick-ui', 'publications', 'assets'})

#: The documented maximum, and how many pages a trial will walk. The cap
#: exists so one employer with thousands of postings cannot spend a whole
#: run's request budget; a capped tenant is recorded as capped.
PAGE_SIZE = 100
MAX_PAGES = 10

#: The host robots.txt disallows us from, which the runner refuses
#: without an explicit exception. See the docstring's source check.
ROBOTS_EXCEPTION_REQUIRED = True
ROBOTS_TXT = ('User-agent: LinkedInBot\nAllow: /v1/companies/\nUser-agent: *\nDisallow: /')

MAPPED_DIMENSIONS = ('contract', 'seniority', 'language', 'work_model',
                     'workload_min', 'workload_max')

HASHED_FIELDS = ('posting_id', 'title', 'employer_name', 'department', 'offices',
                 'country_raw', 'employment_type_raw', 'experience_raw', 'function_raw',
                 'industry_raw', 'remote_raw', 'published_at', 'description',
                 'custom_fields_raw', 'reference_raw')

EMPLOYMENT_CONTRACT = {
    'permanent': 'permanent',
    'temporary': 'fixed_term',
    'fixed_term': 'fixed_term',
    'contractor': 'freelance_mandate',
    'freelance': 'freelance_mandate',
    'internship': 'internship',
    'intern': 'internship',
    'apprenticeship': 'apprenticeship',
    'trainee': 'trainee_programme',
    'traineeship': 'trainee_programme',
    'seasonal': 'seasonal',
    'on_call': 'on_call',
    'working_student': 'working_student',
    'student': 'working_student',
}

EXPERIENCE_MAP = {
    'student': 's0',
    'internship': 's0',
    'intern': 's0',
    'entry_level': 's1',
    'graduate': 's1',
    'senior': 's3',
    'executive': 's5',
    'associate': None,
    'mid_senior_level': None,
    'manager': None,
    'director': None,
    'not_applicable': None,
}

#: The order `jobAd.sections` is concatenated in, with the headings the
#: API's own section titles give.
SECTION_ORDER = ('companyDescription', 'jobDescription', 'qualifications',
                 'additionalInformation')


def feed_url(tenant, *, offset=0, limit=PAGE_SIZE):
    if not re.fullmatch(TENANT_ID, tenant or ''):
        raise ValueError(f'not a SmartRecruiters company identifier: {tenant!r}')
    query = urlencode({'limit': limit, 'offset': offset})
    return f'https://{API_HOST}/v1/companies/{tenant}/postings?{query}'


def detail_url(tenant, posting_id):
    return f'https://{API_HOST}/v1/companies/{tenant}/postings/{posting_id}'


def feed_variants(tenant):
    """The first page. The rest come from `next_page`, because how many
    there are is in the first answer's `totalFound`."""
    return [base.Variant(key=f'{API_HOST}:postings:0', url=feed_url(tenant), slug='postings-0',
                         host=API_HOST, group=API_HOST, options={'tenant': tenant})]


def next_page(variant, parsed, seen):
    """The next page of 100, or None.

    `parsed` is this page's posting list and the paging numbers are read
    off the body it came from, which `parse_feed` keeps on the list as
    `_paging` (a list cannot carry attributes, so it is a plain key on
    each entry's shared parent -- see `parse_feed`).
    """
    paging = getattr(parsed, 'paging', None) or {}
    total = int(paging.get('totalFound') or 0)
    offset = int(paging.get('offset') or 0) + int(paging.get('limit') or PAGE_SIZE)
    if offset >= total or variant.page + 1 >= MAX_PAGES:
        if offset < total:
            _logger.info('smartrecruiters: %s has %s postings and this run reads %s pages',
                         variant.options.get('tenant'), total, MAX_PAGES)
        return None
    tenant = variant.options.get('tenant')
    return base.Variant(key=f'{API_HOST}:postings:{offset}',
                        url=feed_url(tenant, offset=offset), slug=f'postings-{offset}',
                        host=API_HOST, group=API_HOST, page=variant.page + 1,
                        options=dict(variant.options))


def detail_variant(mapped):
    """The one extra request this provider needs, for one posting."""
    tenant, posting_id = mapped['tenant'], mapped['posting_id']
    return base.Variant(key=f'{API_HOST}:posting:{posting_id}',
                        url=detail_url(tenant, posting_id), slug=f'posting-{posting_id}',
                        host=API_HOST, group=API_HOST, detail_of=mapped['key'],
                        options={'tenant': tenant})


def posting_url(tenant, posting_id):
    """The canonical link back. The detail endpoint returns a
    slug-carrying `postingUrl` and that is preferred once fetched."""
    return f'https://{BOARD_HOSTS[0]}/{tenant}/{posting_id}'


def tenant_from_url(url):
    match = detect_ats(url or '')
    parts = urlsplit(url or '')
    host = (parts.hostname or '').casefold()
    if match and match['provider'] == PROVIDER:
        return {'tenant': match['tenant'], 'host': host, 'how': 'posting_url'}
    segments = [segment for segment in (parts.path or '').split('/') if segment]
    if host == API_HOST and len(segments) >= 3 and segments[:2] == ['v1', 'companies']:
        return _candidate(segments[2], host, 'api_url')
    if host in BOARD_HOSTS and segments:
        if segments[0] == 'external-referrals' and 'company' in segments:
            index = segments.index('company')
            if len(segments) > index + 1:
                return _candidate(segments[index + 1], host, 'referral_url')
        return _candidate(segments[0], host, 'board_url')
    return None


def _candidate(token, host, how):
    token = (token or '').strip()
    if token.casefold() in RESERVED or not re.fullmatch(TENANT_ID, token):
        return None
    return {'tenant': token, 'host': host, 'how': how}


class _Postings(list):
    """The posting list, carrying its own paging numbers.

    A plain list cannot answer "how many are there in total", and the
    paging block (`offset`, `limit`, `totalFound`) is what tells the
    fetcher whether to ask for another page. A list subclass keeps
    `parse_feed`'s contract -- a sequence of raw postings -- without a
    second return value that five other adapters would have to carry.
    """

    def __init__(self, items, paging):
        super().__init__(items)
        self.paging = paging


def parse_feed(body):
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get('content'), list):
        raise ValueError('not a SmartRecruiters posting list: the body has no "content" list')
    return _Postings(data['content'], {key: data.get(key) for key in
                                       ('offset', 'limit', 'totalFound')})


def parse_detail(body):
    """One posting's detail response. Its own function, because a detail
    is an object and not a list."""
    data = json.loads(body)
    if not isinstance(data, dict) or not data.get('id'):
        raise ValueError('not a SmartRecruiters posting: the body has no id')
    return data


def offices_of(raw):
    """The one place a posting names, with the country it states.

    `location` is the richest location block of the six providers:
    `{city, country (ISO-3166 alpha-2), postalCode, address,
    fullLocation}`. The office line is the postal code and the city,
    which is how a Swiss address is written, and the country goes beside
    it as evidence rather than into it.
    """
    location = raw.get('location') or {}
    country = location.get('country')
    places, seen = [], set()
    for text in (' '.join(part for part in (location.get('postalCode'), location.get('city'))
                          if part),
                 location.get('city'),
                 location.get('fullLocation')):
        text = ' '.join(str(text or '').split())
        if text and text not in seen:
            seen.add(text)
            places.append({'text': text, 'country': country})
    return places


def _sections(detail):
    """`jobAd.sections` as blocks, in the API's own order."""
    sections = ((detail.get('jobAd') or {}).get('sections') or {})
    blocks = []
    for name in list(SECTION_ORDER) + [key for key in sections if key not in SECTION_ORDER]:
        section = sections.get(name) or {}
        lines = base.html_to_text(section.get('text')) if section.get('text') else []
        if lines:
            blocks.append({'name': (section.get('title') or name), 'text': '\n'.join(lines)})
    parts = []
    for block in blocks:
        parts += [block['name'], block['text'], '']
    return blocks, '\n'.join(parts).strip()


def _work_model_record(raw, *, guide_version):
    location = raw.get('location') or {}
    stated = {name: bool(location.get(name)) for name in ('remote', 'hybrid')}
    code = 'remote' if stated['remote'] else 'hybrid' if stated['hybrid'] else 'onsite'
    return base.map_value(
        'work_model', code, raw=stated, raw_field='location_remote_hybrid',
        confidence=0.9 if any(stated.values()) else 0.7, guide_version=guide_version,
        rule="the posting's own remote and hybrid flags, read remote then hybrid then on site; "
             'neither flag set is read as on site because the API sets them explicitly')


def _workload_records(title, text, custom_fields, *, guide_version):
    quoted = ' '.join(str(field.get('valueLabel') or '') for field in custom_fields or ())
    pair, quote = base.pensum(title, text, quoted)
    if pair:
        return base.workload_records(
            pair, raw=quote, raw_field='pensum_quote', confidence=0.9,
            guide_version=guide_version,
            rule='a Pensum stated in the title, the posting text or a custom field')
    return base.workload_records(
        None, raw=None, raw_field='pensum_quote', guide_version=guide_version,
        rule='the Posting API has no workload field and no Pensum is written in the title, the '
             'text or a custom field')


def map_posting(raw, *, tenant, variant=None, guide_version=None, detail=None):
    """One list entry (plus its detail, when it has been fetched).

    `detail` is None on the first pass. `merge_detail` calls this again
    with it, so there is one mapping and not a mapping and a patcher.
    """
    posting_id = raw.get('id')
    if not posting_id:
        raise ValueError('a SmartRecruiters posting with no id cannot be keyed')
    detail = detail or {}
    title = raw.get('name') or detail.get('name') or ''
    blocks, text = _sections(detail) if detail else ([], '')
    offices = offices_of(detail or raw)
    location = (detail or raw).get('location') or {}
    custom_fields = (detail or raw).get('customField') or []
    employment = ((detail or raw).get('typeOfEmployment') or {})
    experience = ((detail or raw).get('experienceLevel') or {})
    language = ((detail or raw).get('language') or {}).get('code')
    mapped = {
        'provider': PROVIDER,
        'tenant': tenant,
        'posting_id': str(posting_id),
        'url': detail.get('postingUrl') or posting_url(tenant, posting_id),
        'feed_host': API_HOST,
        'feed_language': language,
        'title': title,
        'employer_name': ((detail or raw).get('company') or {}).get('name'),
        'department': ((detail or raw).get('department') or {}).get('label'),
        'offices': [office['text'] for office in offices],
        'offices_stated': offices,
        'location_raw': location.get('fullLocation'),
        'country_raw': location.get('country'),
        'postal_code_raw': location.get('postalCode'),
        'employment_type_raw': employment.get('id') or employment.get('label'),
        'experience_raw': experience.get('id') or experience.get('label'),
        'function_raw': ((detail or raw).get('function') or {}).get('id'),
        'industry_raw': ((detail or raw).get('industry') or {}).get('id'),
        'remote_raw': {name: location.get(name) for name in ('remote', 'hybrid')},
        'reference_raw': (detail or raw).get('refNumber'),
        'uuid_raw': (detail or raw).get('uuid'),
        'custom_fields_raw': [{'label': field.get('fieldLabel'),
                               'value': field.get('valueLabel')} for field in custom_fields],
        'published_at': (detail or raw).get('releasedDate'),
        'visibility_raw': (detail or raw).get('visibility'),
        'active_raw': detail.get('active'),
        'description_blocks': blocks,
        'description': text,
        'has_description': bool(text),
        'description_status': (
            'read from the posting detail endpoint' if text else
            'not fetched: the list endpoint states no description and the detail request is '
            'made only for postings inside the Zurich filter'),
    }
    mapped['values'] = {
        'contract': base.coded_record(
            'contract', mapped['employment_type_raw'], EMPLOYMENT_CONTRACT, provider=PROVIDER,
            raw_field='typeOfEmployment', guide_version=guide_version, confidence=0.85,
            rule="SmartRecruiters' own typeOfEmployment vocabulary; see the module docstring on "
                 'temporary reading as fixed_term',
            missing_rule='the posting states no employment type',
            unmapped_rule='the posting states an employment type this mapping does not cover'),
        'seniority': base.optional_code_record(
            'seniority', mapped['experience_raw'], EXPERIENCE_MAP, provider=PROVIDER,
            raw_field='experienceLevel', guide_version=guide_version,
            rule_mapped="SmartRecruiters' experienceLevel onto the D6 scale",
            rule_ambiguous='the experience level names a span of the scale rather than a step, '
                           'so the value is unknown and the level is kept beside it'),
        'language': base.language_record(
            language, raw_field='language', guide_version=guide_version,
            rule="the posting's own language field, which both the list and the detail "
                 'endpoint state'),
        'work_model': _work_model_record(detail or raw, guide_version=guide_version),
        **_workload_records(title, text, custom_fields, guide_version=guide_version),
    }
    return base.finalize(mapped, adapter=sys.modules[__name__])


def merge_detail(mapped, parsed, *, tenant, guide_version=None):
    """Fold a fetched detail into a list-mapped posting.

    Re-maps rather than patches, so there is one statement of the field
    mapping. The content hash changes, which is correct: a posting with
    its text is not the same record as a posting without it, and the
    store freezes a snapshot of each.
    """
    return map_posting(parsed, tenant=tenant, guide_version=guide_version, detail=parsed)


compress = base.compress
decompress = base.decompress
