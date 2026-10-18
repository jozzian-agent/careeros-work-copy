"""The Recruitee adapter: the careers-site offers API.

## The endpoint, verified 2026-10-17

    https://{tenant}.recruitee.com/api/offers/

Recruitee has three APIs and only one of them is this: the main ATS API
needs a bearer token, the Marketplace API needs OAuth, and the
**careers-site API needs nothing**. Recruitee's own support article on
putting jobs on another website states it in those words -- "The public
API doesn't require any authentication"
(https://support.recruitee.com/en/articles/1066286-show-jobs-on-your-own-website,
read 2026-10-17). That article does not spell the path out, so the
`/api/offers/` shape below was **verified live** on 2026-10-17 (200, a
`{"offers": [...]}` body of 505 KB for the `accso` tenant) rather than
taken from a page that names it. `docs.recruitee.com/reference/offers`
documents a DIFFERENT, token-authenticated `/offers/` endpoint on
`api.recruitee.com`, and is not what this adapter calls.

No `ETag` is served (checked live), so this is the one adapter whose
conditional requests never fire. The fetcher sends no `If-None-Match`
it was not given and records the absence; nothing breaks, an unchanged
feed simply costs a full body.

## What an offer carries, as seen live

The richest payload of the six providers. Mapped: `id`, `slug`, `title`,
`description` (HTML), `requirements` (HTML), `company_name`,
`department`, `locations: [{city, state, country}]`, `city`,
`postal_code`, `country_code`, `state_name`, `location` (the whole line),
`remote` / `hybrid` / `on_site` (three booleans), `employment_type_code`,
`experience_code`, `education_code`, `category_code`,
`min_hours` / `max_hours` (per week), `salary: {min, max, currency,
period}`, `published_at`, `created_at`, `updated_at`, `status`,
`careers_url`, `tags`, `translations` (one key per published language).

**Two fields are deliberately not stored.** `mailbox_email` is an
address (a per-offer mailbox, `job.<guid>@<tenant>.recruitee.com`) and
nothing here needs it, so it is left in the raw snapshot and kept out of
every record and every export -- the same rule the Common Crawl source
check applies to personal information. `open_questions` is the
application form, not the posting.

## The fields that needed a decision

**`employment_type_code` is compound.** The live value is
`fulltime_permanent`: one token for the workload and one for the
contract. So the code is split, the contract half maps onto `contract`
and the workload half onto `workload`, and each records the whole
original value as its evidence. `..._temporary` maps to `fixed_term`
rather than `temporary_assignment`, because Recruitee's own label for it
is a fixed-length employment and `temporary_assignment` in contract.yaml
is placement work; that reading is flagged for the owner in
`data/ats/TRIAL_REPORT.md` rather than presented as settled.

**`min_hours` / `max_hours` are hours a week, not a Pensum**, and
turning 32 hours into 76% needs a full-time basis (42 hours in
Switzerland, 40 in the Netherlands where most of these tenants are) that
the API never states. So they are stored raw as `hours_per_week_raw` and
**not converted**: a Pensum written in the title or the text is used
where it exists, otherwise the compound employment code carries the
workload. Converting hours with an assumed basis is the kind of invented
number PROJECT.md forbids; whether to adopt a stated basis is an owner
question.

**The three booleans are one dimension.** `remote`, `hybrid` and
`on_site` are read in that order onto `work_model`, with all three
recorded as the evidence, because they are three statements about one
fact and the taxonomy has one field for it.

**Language comes from `translations`.** An offer published in exactly
one language names it; an offer with several is `unknown` with the key
list in the evidence, because the offers endpoint returns every
translation at once and nothing says which is primary.

## Source check (owner rule)

  * Documented as public and unauthenticated by the provider (quote and
    link above); the path verified live.
  * `{tenant}.recruitee.com/robots.txt`, read 2026-10-17 on the `accso`
    careers site: `User-Agent: * / Disallow: /v/`. The API path is not
    `/v/`, so robots allows it. The check runs per tenant in the sweep
    anyway, because a careers site is the tenant's own host and a tenant
    may publish its own rules.
  * Terms: the careers site is what the employer publishes to be read.
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

PROVIDER = 'recruitee'

DOC_URL = 'https://support.recruitee.com/en/articles/1066286-show-jobs-on-your-own-website'
DOC_ACCESSED = '2026-10-17'

SNAPSHOT_SUFFIX = 'json'

CAREERS_DOMAIN = 'recruitee.com'

CDX_PATTERNS = ((CAREERS_DOMAIN, 'domain'),)

#: A careers-site subdomain as Recruitee issues them.
TENANT_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,62}')

#: Subdomains of `recruitee.com` that are Recruitee's own infrastructure
#: rather than a customer. Measured: a single Common Crawl page for the
#: domain yielded 585 subdomains, of which these are the platform's.
#: They are listed rather than probed because probing them would be
#: knocking on the provider's own door to be told 404.
PLATFORM_LABELS = frozenset({
    'www', 'app', 'api', 'auth', 'ats', 'cdn', 'assets', 'static', 'help', 'support',
    'blog', 'docs', 'status', 'mail', 'automation', 'azubi', 'go', 'links', 'jobs',
    'careers-api', 'admin', 'files', 'images', 'media', 'test', 'staging', 'demo',
})

MAPPED_DIMENSIONS = ('contract', 'seniority', 'language', 'work_model',
                     'workload_min', 'workload_max')

HASHED_FIELDS = ('posting_id', 'title', 'employer_name', 'department', 'offices',
                 'country_raw', 'employment_type_raw', 'experience_raw', 'education_raw',
                 'hours_per_week_raw', 'remote_raw', 'published_at', 'description',
                 'salary_raw', 'tags')

#: The contract half of `employment_type_code`. The compound value is
#: split on `_` and the LAST token is looked up here; a value that is not
#: compound is looked up whole.
EMPLOYMENT_CONTRACT = {
    'permanent': 'permanent',
    'temporary': 'fixed_term',
    'internship': 'internship',
    'intern': 'internship',
    'traineeship': 'trainee_programme',
    'trainee': 'trainee_programme',
    'freelance': 'freelance_mandate',
    'contractor': 'freelance_mandate',
    'apprenticeship': 'apprenticeship',
    'seasonal': 'seasonal',
    'oncall': 'on_call',
    'on_call': 'on_call',
    'workingstudent': 'working_student',
}

#: The workload half of the same code.
EMPLOYMENT_WORKLOAD = {
    'fulltime': ((100, 100), 0.9),
    'parttime': ((20, 90), 0.2),
}

#: `experience_code` onto the D6 seniority scale. A value mapping to
#: None is in the vocabulary and names a span rather than a step, which
#: `base.optional_code_record` records as `unknown` with the word kept.
EXPERIENCE_MAP = {
    'student': 's0',
    'internship': 's0',
    'intern': 's0',
    'entry_level': 's1',
    'entry': 's1',
    'junior': 's1',
    'senior': 's3',
    'executive': 's5',
    'experienced': None,
    'associate': None,
    'mid_level': None,
    'manager': None,
    'director': None,
    'not_applicable': None,
}


def feed_url(tenant):
    if not re.fullmatch(TENANT_ID, tenant or ''):
        raise ValueError(f'not a Recruitee careers-site subdomain: {tenant!r}')
    return f'https://{tenant}.{CAREERS_DOMAIN}/api/offers/'


def feed_variants(tenant):
    return [base.Variant(key=f'{tenant}.{CAREERS_DOMAIN}:offers', url=feed_url(tenant),
                         slug='offers', host=f'{tenant}.{CAREERS_DOMAIN}',
                         group=f'{tenant}.{CAREERS_DOMAIN}')]


def posting_url(tenant, posting_id):
    """The link back by id. The API's own `careers_url` is preferred,
    because the readable URL uses the offer's slug."""
    return f'https://{tenant}.{CAREERS_DOMAIN}/o/{posting_id}'


def tenant_from_url(url):
    match = detect_ats(url or '')
    parts = urlsplit(url or '')
    host = (parts.hostname or '').casefold()
    if match and match['provider'] == PROVIDER:
        return {'tenant': match['tenant'], 'host': host, 'how': 'posting_url'}
    if host.endswith('.' + CAREERS_DOMAIN):
        label = host[:-(len(CAREERS_DOMAIN) + 1)]
        if label in PLATFORM_LABELS or not re.fullmatch(TENANT_ID, label):
            return None
        return {'tenant': label, 'host': host, 'how': 'host_pattern'}
    return None


def parse_feed(body):
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get('offers'), list):
        raise ValueError('not a Recruitee careers feed: the body has no "offers" list')
    return list(data['offers'])


def offices_of(raw):
    """Every place this offer names, with the country it states.

    The primary office first, written the way a Swiss address is written
    when the API gives both parts (`8001 Zürich`), then every entry of
    `locations`. `country_code` is ISO-3166 alpha-2, which is exactly
    what the geocoder can use to rule a foreign office out.
    """
    places, seen = [], set()

    def add(text, country):
        text = ' '.join(str(text or '').split())
        if text and (text, country) not in seen:
            seen.add((text, country))
            places.append({'text': text, 'country': country})

    country = raw.get('country_code') or raw.get('country')
    add(' '.join(part for part in (raw.get('postal_code'), raw.get('city')) if part), country)
    add(raw.get('city'), country)
    for entry in raw.get('locations') or ():
        if isinstance(entry, dict):
            add(entry.get('city') or entry.get('name'),
                entry.get('country_code') or entry.get('country'))
    add(raw.get('location'), country)
    return places


def _description(raw):
    """`description` and `requirements`, both HTML, as blocks."""
    blocks = []
    for name, value in (('Description', raw.get('description')),
                        ('Requirements', raw.get('requirements'))):
        lines = base.html_to_text(value) if value else []
        if lines:
            blocks.append({'name': name, 'text': '\n'.join(lines)})
    parts = []
    for block in blocks:
        parts += [block['name'], block['text'], '']
    return blocks, '\n'.join(parts).strip()


def _employment_halves(code):
    """`fulltime_permanent` -> ('fulltime', 'permanent').

    Returns `(workload_token, contract_token)`. A value with no `_` is
    both halves at once, because `internship` names a contract and no
    workload and `fulltime` the reverse; each lookup table answers for
    its own half and misses harmlessly on the other.
    """
    text = (code or '').strip().casefold().replace('-', '_')
    if not text:
        return '', ''
    tokens = text.split('_')
    workload = next((token for token in tokens if token in EMPLOYMENT_WORKLOAD), text)
    contract = next((token for token in tokens if token in EMPLOYMENT_CONTRACT),
                    '_'.join(tokens[1:]) or text)
    return workload, contract


def _contract_record(code, *, guide_version):
    """The contract half of the compound code, with the WHOLE code as the
    evidence.

    Not `base.coded_record`, because that looks a value up and records
    the same value: here the lookup is on one half (`permanent`) and the
    evidence has to be the field as the API stated it
    (`fulltime_permanent`), or a reader cannot check the reading.
    """
    _, contract = _employment_halves(code)
    mapped = EMPLOYMENT_CONTRACT.get(contract)
    if mapped:
        return base.map_value(
            'contract', mapped, raw=code, raw_field='employment_type_code', confidence=0.8,
            guide_version=guide_version,
            rule="the contract half of Recruitee's compound employment_type_code; see the "
                 'module docstring on temporary reading as fixed_term')
    if not str(code or '').strip():
        return base.unknown_record('contract', raw=None, raw_field='employment_type_code',
                                   guide_version=guide_version,
                                   rule='the offer states no employment type')
    return base.unknown_record(
        'contract', raw=code, raw_field='employment_type_code', guide_version=guide_version,
        rule='the offer states an employment type this mapping does not cover',
        log=(PROVIDER, code))


def _workload_records(code, title, text, hours, *, guide_version):
    pair, quote = base.pensum(title, text)
    if pair:
        return base.workload_records(
            pair, raw=quote, raw_field='pensum_quote', confidence=0.9,
            guide_version=guide_version, rule='a Pensum stated in the title or the posting text')
    workload, _ = _employment_halves(code)
    if workload in EMPLOYMENT_WORKLOAD:
        pair, confidence = EMPLOYMENT_WORKLOAD[workload]
        return base.workload_records(
            pair, raw=code, raw_field='employment_type_code', confidence=confidence,
            guide_version=guide_version,
            rule="the workload half of Recruitee's compound employment_type_code; no "
                 'percentage is stated in the title or the text')
    return base.workload_records(
        None, raw=code or None, raw_field='employment_type_code', guide_version=guide_version,
        rule=('the offer states hours a week rather than a Pensum, and converting them needs a '
              'full-time basis the API does not state (see the module docstring)'
              if any(hours.values()) else
              'neither the employment code nor the text states a workload'))


def _work_model_record(raw, *, guide_version):
    """The three booleans as one `work_model` value."""
    stated = {name: _boolean(raw.get(name)) for name in ('remote', 'hybrid', 'on_site')}
    code = ('remote' if stated['remote'] else 'hybrid' if stated['hybrid']
            else 'onsite' if stated['on_site'] else None)
    if code is None:
        return base.unknown_record(
            'work_model', raw=stated, raw_field='remote_hybrid_on_site',
            guide_version=guide_version,
            rule='the offer sets none of the remote, hybrid and on_site flags')
    return base.map_value('work_model', code, raw=stated, raw_field='remote_hybrid_on_site',
                          confidence=0.9, guide_version=guide_version,
                          rule="Recruitee's three location flags, read remote then hybrid then "
                               'on site')


def _boolean(value):
    """Recruitee serialises booleans as JSON booleans and, in some
    fields, as the strings "True"/"False". Both are read; anything else
    is not a yes."""
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in ('true', 'yes', '1')


def _language_record(raw, *, guide_version):
    keys = sorted((raw.get('translations') or {}).keys()) if isinstance(
        raw.get('translations'), dict) else []
    if len(keys) == 1:
        return base.language_record(
            keys[0], raw_field='translations', guide_version=guide_version,
            rule='the offer carries exactly one translation, so that is the language it is '
                 'published in')
    return base.unknown_record(
        'language', raw=keys or None, raw_field='translations', guide_version=guide_version,
        rule=('the offer carries several translations and nothing says which is primary'
              if keys else 'the offer carries no translation block'))


def map_posting(raw, *, tenant, variant=None, guide_version=None):
    posting_id = raw.get('id')
    if not posting_id:
        raise ValueError('a Recruitee offer with no id cannot be keyed')
    title = raw.get('title') or ''
    blocks, text = _description(raw)
    offices = offices_of(raw)
    hours = {'min_hours': raw.get('min_hours') or raw.get('min_hours_per_week'),
             'max_hours': raw.get('max_hours') or raw.get('max_hours_per_week')}
    mapped = {
        'provider': PROVIDER,
        'tenant': tenant,
        'posting_id': str(posting_id),
        'url': raw.get('careers_url') or posting_url(tenant, raw.get('slug') or posting_id),
        'feed_host': f'{tenant}.{CAREERS_DOMAIN}',
        'feed_language': None,
        'title': title,
        'employer_name': raw.get('company_name'),
        'department': raw.get('department'),
        'offices': [office['text'] for office in offices],
        'offices_stated': offices,
        'location_raw': raw.get('location'),
        'country_raw': raw.get('country_code') or raw.get('country'),
        'postal_code_raw': raw.get('postal_code'),
        'employment_type_raw': raw.get('employment_type_code'),
        'experience_raw': raw.get('experience_code'),
        'education_raw': raw.get('education_code'),
        'category_raw': raw.get('category_code'),
        'hours_per_week_raw': hours,
        'remote_raw': {name: raw.get(name) for name in ('remote', 'hybrid', 'on_site')},
        'salary_raw': raw.get('salary'),
        'tags': list(raw.get('tags') or ()),
        'offer_status_raw': raw.get('status'),
        'published_at': raw.get('published_at'),
        'updated_at': raw.get('updated_at'),
        'slug': raw.get('slug'),
        'description_blocks': blocks,
        'description': text,
        'has_description': bool(text),
    }
    mapped['values'] = {
        'contract': _contract_record(mapped['employment_type_raw'],
                                     guide_version=guide_version),
        'seniority': base.optional_code_record(
            'seniority', mapped['experience_raw'], EXPERIENCE_MAP, provider=PROVIDER,
            raw_field='experience_code', guide_version=guide_version,
            rule_mapped="Recruitee's experience_code onto the D6 scale",
            rule_ambiguous='the experience code names a span of the scale rather than a step, '
                           'so the value is unknown and the code is kept beside it'),
        'language': _language_record(raw, guide_version=guide_version),
        'work_model': _work_model_record(raw, guide_version=guide_version),
        **_workload_records(mapped['employment_type_raw'], title, text, hours,
                            guide_version=guide_version),
    }
    return base.finalize(mapped, adapter=sys.modules[__name__])


compress = base.compress
decompress = base.decompress
