"""The Lever adapter: the public postings API.

## The endpoint, verified 2026-10-17

Documentation: https://github.com/lever/postings-api (Lever's own
repository for this API, read 2026-10-17). It documents the base URL
`https://api.lever.co/v0/postings/` and the EU instance
`https://api.eu.lever.co/v0/postings/`, the `mode`, `skip`, `limit` and
grouping parameters, and the posting fields. No key.

    https://api.lever.co/v0/postings/{company}?mode=json
    https://api.eu.lever.co/v0/postings/{company}?mode=json

**BOTH instances are fetched, and that is not politeness theatre.**
Measured on 2026-10-17: the slug `leverdemo` exists on both and they are
different boards -- 10 postings on the global instance and 324 on the EU
one. So unlike Personio's two hosts (which are one career site), a
Lever tenant id is instance-scoped, the two answers are merged, and a
posting records the instance it came from. A slug that exists on neither
answers 404 on both, which costs two requests and is the price of not
silently missing an EU-hosted Swiss employer.

## What a posting carries, as seen live

`id` (a uuid), `text` (the title), `categories: {commitment, department,
team, location, allLocations}`, `country` (ISO-3166 alpha-2),
`workplaceType` (`onsite` / `hybrid` / `remote`), `description` and
`descriptionPlain`, `descriptionBody(Plain)`, `opening(Plain)`,
`lists: [{text, content}]`, `additional(Plain)`, `salaryRange`,
`salaryDescription(Plain)`, `createdAt` (epoch milliseconds),
`hostedUrl`, `applyUrl`, `opportunityLocation`.

The API serves its own plain-text rendering of every rich field
(`descriptionPlain`), so this adapter reads THAT rather than putting
Lever's HTML through our own pass: the provider's plain text is the
provider's own statement of the posting, and the shared HTML pass is
used only for `lists[].content`, which has no plain twin.

`createdAt` is milliseconds since the epoch. It is stored as both the
raw number (`created_at_raw`) and an ISO timestamp, because every other
provider states a date and the pool has one column for it.

## The one field that needed a decision: `commitment`

`categories.commitment` is **customer-defined free text**, not a closed
vocabulary: the live values include "Regular Full Time (Salary)",
"Part time" and "Full-time". It mixes two different facts -- how much of
a week the job is, and what kind of contract it is -- so:

  * a commitment that names a CONTRACT ("Intern", "Contractor",
    "Temporary", "Apprentice") maps onto the `contract` dimension;
  * a commitment that names a WORKLOAD ("Full time", "Part time") maps
    onto `workload`, at the confidences CAREER-53's spec set for the
    same two words, and leaves `contract` `unknown` with the field in
    the evidence -- because "Full time" is not a contract type and
    answering `permanent` would be this module inventing one;
  * a Pensum written in the title or the posting text beats the field,
    exactly as it does for Personio.

`workplaceType` is a closed Lever vocabulary and maps straight onto the
taxonomy's `work_model`.

## Source check (owner rule)

  * Documented public API, no key (link above).
  * `api.lever.co/robots.txt` and `api.eu.lever.co/robots.txt`, read
    2026-10-17: `User-agent: * / Allow: / / Crawl-delay: 1`. Allowed,
    and the crawl delay Lever asks for is one second, which is exactly
    the shared limiter's interval -- so the whole run already obeys it.
  * Terms: the postings are what a company publishes for applicants.
    The posting text belongs to the employer; nothing is republished.
"""
import json
import logging
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit

from careeros.feeds import base

from org_intake.ats import detect_ats

_logger = logging.getLogger(__name__)

PROVIDER = 'lever'

DOC_URL = 'https://github.com/lever/postings-api'
DOC_ACCESSED = '2026-10-17'

SNAPSHOT_SUFFIX = 'json'

#: (api host, career-site host, instance name). Both instances, in the
#: order the documentation lists them.
INSTANCES = (('api.lever.co', 'jobs.lever.co', 'global'),
             ('api.eu.lever.co', 'jobs.eu.lever.co', 'eu'))

BOARD_HOSTS = tuple(site for _, site, _ in INSTANCES)
API_HOSTS = tuple(api for api, _, _ in INSTANCES)

CDX_PATTERNS = tuple((site, 'host') for site in BOARD_HOSTS)

TENANT_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}')

RESERVED = frozenset({'robots.txt', 'favicon.ico', 'apply', 'api', 'v0', 'postings'})

MAPPED_DIMENSIONS = ('contract', 'work_model', 'workload_min', 'workload_max')

HASHED_FIELDS = ('posting_id', 'title', 'department', 'team', 'offices', 'country_raw',
                 'commitment_raw', 'workplace_raw', 'published_at', 'description',
                 'salary_raw')

#: `categories.commitment` -> a taxonomy `contract` code. Matched as a
#: SUBSTRING of the folded field, because the field is customer text
#: ("Regular Full Time (Salary)") and not an enum. Order matters: the
#: first match wins, so the more specific words come first.
COMMITMENT_CONTRACT = (
    ('working student', 'working_student'),
    ('werkstudent', 'working_student'),
    ('intern', 'internship'),
    ('praktik', 'internship'),
    ('apprentice', 'apprenticeship'),
    ('lehre', 'apprenticeship'),
    ('trainee', 'trainee_programme'),
    ('graduate programme', 'trainee_programme'),
    ('contractor', 'freelance_mandate'),
    ('contract', 'freelance_mandate'),
    ('freelance', 'freelance_mandate'),
    ('consultant', 'freelance_mandate'),
    ('temporary', 'temporary_assignment'),
    ('temp', 'temporary_assignment'),
    ('seasonal', 'seasonal'),
    ('saison', 'seasonal'),
    ('on call', 'on_call'),
    ('fixed term', 'fixed_term'),
    # `unbefristet` BEFORE `befristet`, because the second is a substring
    # of the first and these are substring matches: "Festanstellung,
    # unbefristet" read as fixed-term is the opposite of what it says.
    ('unbefristet', 'permanent'),
    ('befristet', 'fixed_term'),
    ('permanent', 'permanent'),
)

#: The same field read as a workload instead, with the two confidences
#: CAREER-53's spec set for the same two words.
COMMITMENT_WORKLOAD = (
    ('part time', ((20, 90), 0.2)),
    ('part-time', ((20, 90), 0.2)),
    ('teilzeit', ((20, 90), 0.2)),
    ('full time', ((100, 100), 0.8)),
    ('full-time', ((100, 100), 0.8)),
    ('vollzeit', ((100, 100), 0.8)),
)

#: Lever's own closed vocabulary, which the taxonomy has the same three
#: codes for.
WORKPLACE_MAP = {'onsite': 'onsite', 'on_site': 'onsite', 'hybrid': 'hybrid',
                 'remote': 'remote', 'unspecified': None}


def feed_url(tenant, *, host=INSTANCES[0][0]):
    if not re.fullmatch(TENANT_ID, tenant or ''):
        raise ValueError(f'not a Lever company slug: {tenant!r}')
    if host not in API_HOSTS:
        raise ValueError(f'unknown Lever API host {host!r}')
    return f'https://{host}/v0/postings/{tenant}?mode=json'


def feed_variants(tenant):
    """One variant per instance, each its own group: see the docstring on
    why a successful global fetch does not end the tenant."""
    return [base.Variant(key=f'{api}:postings', url=feed_url(tenant, host=api), slug=instance,
                         host=api, group=api, primary=True, stop_after_group=False,
                         options={'instance': instance, 'site': site})
            for api, site, instance in INSTANCES]


def posting_url(tenant, posting_id, *, site=BOARD_HOSTS[0]):
    """The canonical link back. The API's own `hostedUrl` is preferred
    where present, because it names the instance's career-site host."""
    return f'https://{site}/{tenant}/{posting_id}'


def tenant_from_url(url):
    match = detect_ats(url or '')
    parts = urlsplit(url or '')
    host = (parts.hostname or '').casefold()
    if match and match['provider'] == PROVIDER:
        return {'tenant': match['tenant'], 'host': host, 'how': 'posting_url'}
    segments = [segment for segment in (parts.path or '').split('/') if segment]
    if host in API_HOSTS and len(segments) >= 3 and segments[:2] == ['v0', 'postings']:
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
    """A response body -> the raw posting list.

    Lever answers a bare JSON array, so "is this a Lever board" is "is
    this a list of objects with an id and a text".
    """
    data = json.loads(body)
    if not isinstance(data, list):
        raise ValueError('not a Lever postings feed: the body is not a JSON list')
    for item in data[:1]:
        if not isinstance(item, dict) or 'id' not in item:
            raise ValueError('not a Lever postings feed: the first entry has no id')
    return list(data)


def offices_of(raw):
    """Every place this posting names, with the country it states.

    Returned as the mapping shape `geocode` reads, so the stated
    `country` can rule a foreign office out instead of a Swiss
    municipality name being matched by accident -- which is the one false
    positive CAREER-53's geocoder could not rule out and this API can.
    """
    categories = raw.get('categories') or {}
    country = raw.get('country')
    places, seen = [], set()
    for value in [categories.get('location')] + list(categories.get('allLocations') or ()):
        text = (value or '').strip()
        if text and text not in seen:
            seen.add(text)
            places.append({'text': text, 'country': country})
    return places


def _description(raw):
    """The posting's text, from the API's own plain renderings.

    Returns `(blocks, text)`. `lists[].content` is the one rich field
    with no plain twin, so it is the only one that goes through the
    shared HTML pass.
    """
    blocks = []
    for name, value in (('Opening', raw.get('openingPlain')),
                        (None, raw.get('descriptionPlain'))):
        if (value or '').strip():
            blocks.append({'name': name, 'text': value.strip()})
    for item in raw.get('lists') or ():
        lines = base.html_to_text(item.get('content'))
        if lines:
            blocks.append({'name': (item.get('text') or '').strip() or None,
                           'text': '\n'.join(lines)})
    for name, value in (('Additional', raw.get('additionalPlain')),
                        ('Salary', raw.get('salaryDescriptionPlain'))):
        if (value or '').strip():
            blocks.append({'name': name, 'text': value.strip()})
    parts = []
    for block in blocks:
        if block['name']:
            parts.append(block['name'])
        parts.extend([block['text'], ''])
    return blocks, '\n'.join(parts).strip()


def _published_at(raw):
    """`createdAt` (epoch milliseconds) as an ISO timestamp, or None."""
    value = raw.get('createdAt')
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).isoformat(
            timespec='seconds')
    except (TypeError, ValueError):
        return None


def _contract_record(commitment, *, guide_version):
    """`commitment` read as a contract type, or an honest `unknown`.

    See the docstring: the field is customer text and it mixes contract
    with workload, so a workload word is recorded as "this names a
    workload" rather than mapped to a contract code.
    """
    folded = (commitment or '').casefold()
    for word, code in COMMITMENT_CONTRACT:
        if word in folded:
            return base.map_value('contract', code, raw=commitment, raw_field='commitment',
                                  confidence=0.8, guide_version=guide_version,
                                  rule="a contract word inside Lever's customer-defined "
                                       'commitment field')
    if not folded.strip():
        return base.unknown_record('contract', raw=None, raw_field='commitment',
                                   guide_version=guide_version,
                                   rule='the posting states no commitment')
    if any(word in folded for word, _ in COMMITMENT_WORKLOAD):
        return base.unknown_record(
            'contract', raw=commitment, raw_field='commitment', guide_version=guide_version,
            rule='the commitment states a workload rather than a contract type, so the '
                 'contract is unknown and the workload carries the field')
    return base.unknown_record(
        'contract', raw=commitment, raw_field='commitment', guide_version=guide_version,
        rule='the commitment field is customer-defined text this mapping does not cover',
        log=(PROVIDER, commitment))


def _workload_records(commitment, title, text, *, guide_version):
    pair, quote = base.pensum(title, text)
    if pair:
        return base.workload_records(
            pair, raw=quote, raw_field='pensum_quote', confidence=0.9,
            guide_version=guide_version, rule='a Pensum stated in the title or the posting text')
    folded = (commitment or '').casefold()
    for word, (pair, confidence) in COMMITMENT_WORKLOAD:
        if word in folded:
            return base.workload_records(
                pair, raw=commitment, raw_field='commitment', confidence=confidence,
                guide_version=guide_version,
                rule="a workload word inside Lever's commitment field; no percentage is "
                     'stated in the title or the text')
    return base.workload_records(
        None, raw=commitment or None, raw_field='commitment', guide_version=guide_version,
        rule='neither the commitment field nor the text states a workload')


def map_posting(raw, *, tenant, variant=None, guide_version=None):
    posting_id = raw.get('id')
    if not posting_id:
        raise ValueError('a Lever posting with no id cannot be keyed')
    categories = raw.get('categories') or {}
    site = (variant.options.get('site') if variant else None) or BOARD_HOSTS[0]
    instance = (variant.options.get('instance') if variant else None) or INSTANCES[0][2]
    title = raw.get('text') or ''
    blocks, text = _description(raw)
    offices = offices_of(raw)
    mapped = {
        'provider': PROVIDER,
        'tenant': tenant,
        'posting_id': str(posting_id),
        'url': raw.get('hosted_url') or raw.get('hostedUrl') or posting_url(
            tenant, posting_id, site=site),
        'feed_host': (variant.host if variant else INSTANCES[0][0]),
        'feed_instance': instance,
        'feed_language': None,
        'title': title,
        'employer_name': None,
        'department': categories.get('department'),
        'team': categories.get('team'),
        'offices': [office['text'] for office in offices],
        'offices_stated': offices,
        'location_raw': categories.get('location'),
        'country_raw': raw.get('country'),
        'commitment_raw': categories.get('commitment'),
        'workplace_raw': raw.get('workplaceType'),
        'published_at': _published_at(raw),
        'created_at_raw': raw.get('createdAt'),
        'salary_raw': raw.get('salaryRange'),
        'apply_url': raw.get('applyUrl'),
        'description_blocks': blocks,
        'description': text,
        'has_description': bool(text),
    }
    mapped['values'] = {
        'contract': _contract_record(mapped['commitment_raw'], guide_version=guide_version),
        'work_model': base.coded_record(
            'work_model', mapped['workplace_raw'], WORKPLACE_MAP, provider=PROVIDER,
            raw_field='workplaceType', guide_version=guide_version,
            rule="Lever's own workplaceType vocabulary, which the taxonomy shares",
            missing_rule='the posting states no workplace type',
            unmapped_rule='the posting states a workplace type this mapping does not cover'),
        **_workload_records(mapped['commitment_raw'], title, text, guide_version=guide_version),
    }
    return base.finalize(mapped, adapter=sys.modules[__name__])


compress = base.compress
decompress = base.decompress
