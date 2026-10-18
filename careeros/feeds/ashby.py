"""The Ashby adapter: the public job-posting API.

## The endpoint, verified 2026-10-17

Documentation:
https://developers.ashbyhq.com/docs/public-job-posting-api (read
2026-10-17). It documents one GET, no authentication:

    https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true

Ashby also has a GraphQL posting API, which the brief names as a
possibility. It is NOT used: this endpoint answers the same question in
one unauthenticated GET, and `includeCompensation=true` adds the
compensation block the GraphQL one is usually reached for. Measured live
on the `ashby` board: 63 postings, 1.9 MB with compensation, one
request, `ETag` served (so an unchanged board costs one 304).

## What a posting carries, as seen live

`id` (uuid), `title`, `department`, `team`, `employmentType`, `location`,
`secondaryLocations: [{location, address.postalAddress}]`, `publishedAt`,
`isListed`, `isRemote`, `workplaceType`, `address.postalAddress:
{postalCode, addressRegion, addressCountry, addressLocality}`, `jobUrl`,
`applyUrl`, `descriptionHtml`, `descriptionPlain`, `compensation`,
`shouldDisplayCompensationOnJobPostings`.

`descriptionPlain` is Ashby's own plain rendering and is what this
adapter stores, for the same reason as Lever: the provider's plain text
is the provider's own statement of the posting.

**`isListed: false` postings are kept, not dropped.** They are stored
with `is_listed: False` so the pool can decide: a posting the API
returns but the board does not list is a fact about the posting, and
dropping it here would be this adapter deciding something the pool is
better placed to decide (PROJECT.md: a dead or hidden thing is a
recorded status, never a silent drop).

## The two fields that needed a decision

`employmentType` is a closed Ashby vocabulary -- `FullTime`, `PartTime`,
`Intern`, `Contract`, `Temporary` -- and it mixes two facts, exactly
like Lever's `commitment`: the first two name a WORKLOAD and the last
three name a CONTRACT. So `Intern`, `Contract` and `Temporary` map onto
`contract`; `FullTime` and `PartTime` map onto `workload` and leave
`contract` `unknown` with the field in the evidence, because answering
`permanent` for "FullTime" would be inventing a contract the API never
stated.

`workplaceType` (`OnSite` / `Remote` / `Hybrid`) maps straight onto the
taxonomy's `work_model`.

## The addresses are the best location evidence of any provider here

`address.postalAddress` carries a postal code, a locality and a country
NAME. The stated country is handed to the geocoder, which uses it to
rule out a foreign place that shares a Swiss municipality name -- the
one false positive CAREER-53's geocoder documented and could not fix
("Lindau" is in canton Zurich and on the German side of the Bodensee).
A posting with a Swiss postal code resolves corroborated rather than
name-only.

## Source check (owner rule)

  * Documented public API, no key (link above).
  * `api.ashbyhq.com/robots.txt`, read 2026-10-17: the host answers
    **401** for it, with no body. Under RFC 9309 a 4xx robots.txt means
    "no restrictions published", which is how `polite_http.robots_allows`
    reads it, and the posting endpoint itself answers 200
    unauthenticated. So there is no robots directive to respect or to
    breach here -- recorded rather than interpreted, because "the host
    publishes no robots.txt" is a weaker statement than Greenhouse's
    explicit allow.
  * Terms: the board is what a company publishes for applicants.
    Nothing is republished.
"""
import json
import logging
import re
import sys
from urllib.parse import urlsplit

from careeros.feeds import base

from org_intake.ats import detect_ats

_logger = logging.getLogger(__name__)

PROVIDER = 'ashby'

DOC_URL = 'https://developers.ashbyhq.com/docs/public-job-posting-api'
DOC_ACCESSED = '2026-10-17'

SNAPSHOT_SUFFIX = 'json'

API_HOST = 'api.ashbyhq.com'
BOARD_HOSTS = ('jobs.ashbyhq.com',)

CDX_PATTERNS = (('jobs.ashbyhq.com', 'host'),)

TENANT_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}')

RESERVED = frozenset({'robots.txt', 'favicon.ico', 'posting-api', 'api', 'application',
                      'assets', '_next'})

MAPPED_DIMENSIONS = ('contract', 'work_model', 'workload_min', 'workload_max')

HASHED_FIELDS = ('posting_id', 'title', 'department', 'team', 'offices', 'country_raw',
                 'employment_type_raw', 'workplace_raw', 'published_at', 'description',
                 'compensation_raw', 'is_listed')

#: Ashby's `employmentType` -> a taxonomy `contract` code. `FullTime` and
#: `PartTime` are deliberately absent: see the docstring.
EMPLOYMENT_CONTRACT = {
    'intern': 'internship',
    'internship': 'internship',
    'contract': 'freelance_mandate',
    'contractor': 'freelance_mandate',
    'temporary': 'temporary_assignment',
    'apprenticeship': 'apprenticeship',
    'trainee': 'trainee_programme',
}

#: The same field read as a workload, with CAREER-53's own two numbers.
EMPLOYMENT_WORKLOAD = {
    'fulltime': ((100, 100), 0.9),
    'parttime': ((20, 90), 0.2),
}

WORKPLACE_MAP = {'onsite': 'onsite', 'on_site': 'onsite', 'hybrid': 'hybrid', 'remote': 'remote'}


def feed_url(tenant, *, compensation=True):
    if not re.fullmatch(TENANT_ID, tenant or ''):
        raise ValueError(f'not an Ashby job board name: {tenant!r}')
    return (f'https://{API_HOST}/posting-api/job-board/{tenant}'
            + ('?includeCompensation=true' if compensation else ''))


def feed_variants(tenant):
    return [base.Variant(key=f'{API_HOST}:job-board', url=feed_url(tenant), slug='job-board',
                         host=API_HOST, group=API_HOST)]


def posting_url(tenant, posting_id):
    """The canonical link back; the API's own `jobUrl` is preferred."""
    return f'https://{BOARD_HOSTS[0]}/{tenant}/{posting_id}'


def tenant_from_url(url):
    match = detect_ats(url or '')
    parts = urlsplit(url or '')
    host = (parts.hostname or '').casefold()
    if match and match['provider'] == PROVIDER:
        return {'tenant': match['tenant'], 'host': host, 'how': 'posting_url'}
    segments = [segment for segment in (parts.path or '').split('/') if segment]
    if host == API_HOST and len(segments) >= 3 and segments[:2] == ['posting-api', 'job-board']:
        return _candidate(segments[2], host, 'api_url')
    if host in BOARD_HOSTS and segments:
        return _candidate(segments[0], host, 'board_url')
    return None


def _candidate(token, host, how):
    token = (token or '').strip()
    if token.casefold() in RESERVED or not re.fullmatch(TENANT_ID, token):
        return None
    return {'tenant': token, 'host': host, 'how': how}


def parse_feed(body):
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
        raise ValueError('not an Ashby job board: the body has no "jobs" list')
    return list(data['jobs'])


def _postal_address(entry):
    return ((entry or {}).get('address') or {}).get('postalAddress') or {}


def offices_of(raw):
    """Every place this posting names, with the country each one states.

    The primary location first, then its postal address written as a
    Swiss address is written (`8001 Zürich`) when the API gives both
    parts, then each secondary location the same way. Nothing is
    composed out of parts the API did not state, and the country goes
    beside the text rather than into it, so the geocoder can use it as
    evidence without it being read as a place.
    """
    places, seen = [], set()

    def add(text, country):
        text = (text or '').strip()
        if text and (text, country) not in seen:
            seen.add((text, country))
            places.append({'text': text, 'country': country})

    for entry in [raw] + list(raw.get('secondaryLocations') or ()):
        address = _postal_address(entry)
        country = address.get('addressCountry')
        add(entry.get('location'), country)
        locality, postal = address.get('addressLocality'), address.get('postalCode')
        if locality:
            add(' '.join(part for part in (postal, locality) if part), country)
    return places


def _description(raw):
    text = (raw.get('descriptionPlain') or '').strip()
    if not text and raw.get('descriptionHtml'):
        text = '\n'.join(base.html_to_text(raw.get('descriptionHtml'))).strip()
    return ([{'name': None, 'text': text}] if text else []), text


def _contract_record(employment_type, *, guide_version):
    key = (employment_type or '').strip().casefold().replace(' ', '').replace('_', '')
    if key in EMPLOYMENT_WORKLOAD:
        return base.unknown_record(
            'contract', raw=employment_type, raw_field='employmentType',
            guide_version=guide_version,
            rule='the employment type states a workload rather than a contract type, so the '
                 'contract is unknown and the workload carries the field')
    return base.coded_record(
        'contract', employment_type, EMPLOYMENT_CONTRACT, provider=PROVIDER,
        raw_field='employmentType', guide_version=guide_version,
        rule="Ashby's own employmentType vocabulary",
        missing_rule='the posting states no employment type',
        unmapped_rule='the posting states an employment type this mapping does not cover')


def _workload_records(employment_type, title, text, *, guide_version):
    pair, quote = base.pensum(title, text)
    if pair:
        return base.workload_records(
            pair, raw=quote, raw_field='pensum_quote', confidence=0.9,
            guide_version=guide_version, rule='a Pensum stated in the title or the posting text')
    key = (employment_type or '').strip().casefold().replace(' ', '').replace('_', '')
    if key in EMPLOYMENT_WORKLOAD:
        pair, confidence = EMPLOYMENT_WORKLOAD[key]
        return base.workload_records(
            pair, raw=employment_type, raw_field='employmentType', confidence=confidence,
            guide_version=guide_version,
            rule="Ashby's employmentType read as a workload; no percentage is stated in the "
                 'title or the text')
    return base.workload_records(
        None, raw=employment_type or None, raw_field='employmentType',
        guide_version=guide_version,
        rule='neither the employment type nor the text states a workload')


def map_posting(raw, *, tenant, variant=None, guide_version=None):
    posting_id = raw.get('id')
    if not posting_id:
        raise ValueError('an Ashby posting with no id cannot be keyed')
    title = raw.get('title') or ''
    blocks, text = _description(raw)
    offices = offices_of(raw)
    address = _postal_address(raw)
    mapped = {
        'provider': PROVIDER,
        'tenant': tenant,
        'posting_id': str(posting_id),
        'url': raw.get('jobUrl') or posting_url(tenant, posting_id),
        'feed_host': API_HOST,
        'feed_language': None,
        'title': title,
        'employer_name': None,
        'department': raw.get('department'),
        'team': raw.get('team'),
        'offices': [office['text'] for office in offices],
        'offices_stated': offices,
        'location_raw': raw.get('location'),
        'country_raw': address.get('addressCountry'),
        'postal_code_raw': address.get('postalCode'),
        'employment_type_raw': raw.get('employmentType'),
        'workplace_raw': raw.get('workplaceType'),
        'is_remote': raw.get('isRemote'),
        'is_listed': raw.get('isListed'),
        'published_at': raw.get('publishedAt'),
        'compensation_raw': raw.get('compensation'),
        'apply_url': raw.get('applyUrl'),
        'description_blocks': blocks,
        'description': text,
        'has_description': bool(text),
    }
    mapped['values'] = {
        'contract': _contract_record(mapped['employment_type_raw'], guide_version=guide_version),
        'work_model': base.coded_record(
            'work_model', mapped['workplace_raw'], WORKPLACE_MAP, provider=PROVIDER,
            raw_field='workplaceType', guide_version=guide_version,
            rule="Ashby's own workplaceType vocabulary, which the taxonomy shares",
            missing_rule='the posting states no workplace type',
            unmapped_rule='the posting states a workplace type this mapping does not cover'),
        **_workload_records(mapped['employment_type_raw'], title, text,
                            guide_version=guide_version),
    }
    return base.finalize(mapped, adapter=sys.modules[__name__])


compress = base.compress
decompress = base.decompress
