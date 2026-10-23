"""The Personio adapter: feed URL, XML parse, field mapping.

Everything Personio-specific is in this module. CAREER-54 turned the
"same three entry points" this file's first version promised into the
contract in `careeros.feeds.base`, and this adapter is its first
implementation: what moved out is the gzip codec, the HTML-to-text pass,
the Pensum reader, the content hash and the provenance block, all of
which five more adapters now share. What stayed is every sentence below.

## What was verified live, 2026-10-17

The spec says the documentation is old and tells the builder to check the
field list against real feeds before writing the parser. Checked against
`bring-labs.jobs.personio.de` and the tenants of the trial run:

  * **The endpoint is `/xml`, with the language as a QUERY parameter.**
    `https://{tenant}.jobs.personio.de/xml?language=de` answers 200;
    `https://{tenant}.jobs.personio.de/de/xml` answers **404**. The
    brief's "check whether /de/xml vs /xml matters" is answered: only
    `/xml` exists.
  * **`.de` and `.com` are the same host.** `bring-labs.jobs.personio.com/xml`
    returned a byte-identical feed to the `.de` one. The spec's "try .de
    first, then .com" is still implemented and the working host is still
    recorded, because that costs nothing and the spec asks for it -- but
    the expectation that some tenants live only on `.com` was not borne
    out on any tenant tried.
  * **An unsupported language is a 200, not a 404.** Asking for a
    language the tenant does not publish returns every position with the
    structural fields intact and `<jobDescriptions></jobDescriptions>`
    empty. So "does this tenant publish English" cannot be answered by a
    status code; `has_descriptions` is what answers it.
  * **The root element is `workzag-jobs`** (Personio's pre-rename
    codename), with `position` children.
  * **The documented field list is accurate and complete.** Every
    element the reference lists was seen live, and nothing outside it was
    seen except `additionalOffices`, which the spec already names.

## The open question the spec asked, answered

> Does the live feed contain fields beyond the documented ones that are
> worth mapping, such as keywords or occupation categories?

Yes, and they are the most useful thing in the feed for this ticket:

  * `occupation` and `occupationCategory` are **Personio's own
    machine-readable occupation taxonomy** (`product_management` inside
    `marketing_and_product`, `business_development_and_new_accounts`
    inside `sales_and_business_development`, `other` inside `other`).
    They are snake-case ids, not free text, which makes them a
    stratification key for the golden-set sample that needs no model at
    all. CAREER-53 is forbidden from classifying occupations with an LLM
    (that is CAREER-57), so these carry the export's strata.
  * `keywords` is a comma-separated list the tenant typed. Kept raw.
  * `recruitingCategory` is the tenant's own pipeline name ("Leadership
    Roles", "Bewerberpool"). Kept raw; it is a tenant's vocabulary and
    not a CareerOS dimension.

They are NOT mapped onto `occupation_family`. Personio's ids and the 40
CareerOS families are different vocabularies and a crosswalk between them
would be a mapping this module invented. They are stored as what they
are, with their own key, and the crosswalk is a decision for CAREER-57.

## Field mapping, and the two places it departs from the spec table

The spec's mapping table is followed field for field, with these two
notes, both of which need an owner ruling (recorded in
`data/personio/TRIAL_REPORT.md` as well):

1. **`seniority: entry-level`.** The spec maps `student` AND
   `entry-level` to `s0`. Decision sheet CAREER-58's own D6 scale calls
   s0 "Student or intern" and s1 "Entry", and its crosswalk maps the old
   value `entry-level` to `entry` to **s1**. Following the spec's letter
   would file a graduate role under "Student or intern", which D6's own
   label contradicts. This module follows D6's crosswalk (s1) and leaves
   the raw hint on the posting either way, so a re-reading costs nothing.
2. **`seniority: experienced` and `executive`.** The spec leaves both to
   the classifier ("s1 or s2", "s4 or s5"). A value record cannot hold a
   range, so these are stored as the value `unknown` -- which under D4 is
   a real value meaning classified-and-came-up-empty -- with the raw hint
   in the evidence. Nothing is lost: `seniority_hint` keeps the feed's
   own word for CAREER-57.

`employmentType` and `schedule` map onto the taxonomy's `contract` and
`workload` dimensions. A `schedule` of `part-time` is the spec's weakest
field: the spec says 20-90 at low confidence unless a percentage is
stated, so this module looks for a Pensum in the title and the posting
text first (`80-100%`, `60 %`, `80 - 100 %`) and only falls back to the
range. A value record holds one code, so a workload RANGE is two records,
`workload_min` and `workload_max`, over the same dimension -- which is
what workload.yaml's own `range` block describes.

**The feed states no work model.** Four of the six adapters can fill the
`work_model` dimension because their APIs carry a remote/hybrid/on-site
field; Personio's XML does not, so this adapter declares five dimensions
(`MAPPED_DIMENSIONS`) rather than writing a sixth record whose `unknown`
would mean "this provider has no such field" and not "this posting left
it empty". Which provider can state what is a line in the trial report.

## Reuse

`careeros.intake.Posting` is the repository's HTML-to-text parser and it
takes a fragment, which is what a `jobDescription` value is (CDATA
HTML). It is reused through `base.html_to_text` together with
`intake._collapse_lines`, a private helper, rather than writing a fourth
HTML-to-text pass. `org_intake.ats.detect_ats` is reused in
`tenant_from_url` for the same reason.
"""
import logging
import re
import sys
from urllib.parse import urlsplit
from xml.etree import ElementTree

from careeros.feeds import base

from org_intake.ats import detect_ats

_logger = logging.getLogger(__name__)

PROVIDER = 'personio'

#: Personio's own documentation of this endpoint, and the day it was last
#: read. Part of every stored posting's provenance.
DOC_URL = 'https://developer.personio.de/v1.0/reference/get_xml'
DOC_ACCESSED = '2026-10-17'

SNAPSHOT_SUFFIX = 'xml'

#: Both hosts Personio serves a career site on. `.de` first, per the
#: spec; see the module docstring on what checking that actually found.
HOSTS = ('jobs.personio.de', 'jobs.personio.com')

#: What a Common Crawl domain match is run against. A domain match on
#: `jobs.personio.de` also returns `*.jobs.personio.de`, which is what
#: gives the tenants.
CDX_PATTERNS = tuple((host, 'domain') for host in HOSTS)

#: A tenant id as Personio issues them: lower-case, digits, hyphens.
TENANT_ID = re.compile(r'[a-z0-9][a-z0-9-]*')

#: The languages the feed accepts, from Personio's own reference. A
#: language outside this list is not refused by the server -- it answers
#: 200 with empty descriptions -- so the list is ours to respect.
FEED_LANGUAGES = ('de', 'en', 'fr', 'es', 'nl', 'it', 'pt')

#: What CAREER-53 fetches. German first because most Zurich postings are
#: in German (the spec's own reason for Personio first); English second
#: and only kept when it actually carries descriptions.
DEFAULT_LANGUAGES = ('de', 'en')

#: What the runner may pass through to `feed_variants`.
VARIANT_OPTIONS = ('languages', 'hosts')

ROOT_TAG = 'workzag-jobs'
POSITION_TAG = 'position'

#: The taxonomy dimensions this feed can state. See the docstring on why
#: `work_model` is not one of them.
MAPPED_DIMENSIONS = ('contract', 'seniority', 'language', 'workload_min', 'workload_max')

#: Personio's `employmentType` -> the taxonomy `contract` code. The four
#: on the left of the spec's table, plus the values seen live. A value
#: that is not here becomes `unknown` with the raw value in the evidence
#: and a log line, never a guess at the nearest code.
CONTRACT_MAP = {
    'permanent': 'permanent',
    'intern': 'internship',
    'internship': 'internship',
    'trainee': 'trainee_programme',
    'freelance': 'freelance_mandate',
    'working_student': 'working_student',
    'temporary': 'temporary_assignment',
    'fixed_term': 'fixed_term',
    'apprenticeship': 'apprenticeship',
}

#: Personio's `seniority` -> a taxonomy `seniority` code, or None when
#: the feed's word does not pin one step. See the docstring's note 1 and
#: 2 on both halves of this table.
SENIORITY_MAP = {
    'student': 's0',
    'intern': 's0',
    'internship': 's0',
    'entry-level': 's1',
    'entry_level': 's1',
    'entry level': 's1',
    'experienced': None,
    'executive': None,
    'manager': None,
    'lead': None,
}

#: Personio's `schedule` -> a workload range as (min, max). The
#: part-time range is the spec's own 20-90 and carries the spec's own
#: "low confidence" as a number.
SCHEDULE_MAP = {
    'full-time': ((100, 100), 0.9),
    'full_time': ((100, 100), 0.9),
    'part-time': ((20, 90), 0.2),
    'part_time': ((20, 90), 0.2),
}

#: Only the posting fields the feed itself states go into the content
#: hash, in this order. Not the fetch time, not the run id, not anything
#: derived: a re-fetch of an unchanged posting has to hash the same, or
#: the snapshot store would grow a new snapshot every day (the spec's
#: "snapshots stable" criterion).
HASHED_FIELDS = ('posting_id', 'title', 'employer_name', 'department', 'recruiting_category',
                 'offices', 'employment_type_raw', 'schedule_raw', 'seniority_hint',
                 'years_of_experience', 'occupation', 'occupation_category', 'keywords',
                 'published_at', 'description_blocks')


def feed_url(tenant, *, language='de', host=HOSTS[0]):
    """The one feed URL shape that exists. See the docstring: `/de/xml`
    is a 404, the language is a query parameter."""
    if not re.fullmatch(TENANT_ID, tenant or ''):
        raise ValueError(f'not a Personio tenant id: {tenant!r}')
    if language not in FEED_LANGUAGES:
        raise ValueError(f'Personio serves {", ".join(FEED_LANGUAGES)}, not {language!r}')
    if host not in HOSTS:
        raise ValueError(f'unknown Personio host {host!r}')
    return f'https://{tenant}.{host}/xml?language={language}'


def feed_urls(tenant, *, languages=DEFAULT_LANGUAGES, hosts=HOSTS):
    """Every (host, language, url) worth trying for one tenant, in the
    order to try them."""
    return [(host, language, feed_url(tenant, language=language, host=host))
            for host in hosts for language in languages]


def feed_variants(tenant, *, languages=DEFAULT_LANGUAGES, hosts=HOSTS):
    """The contract's view of the same list: four requests, grouped by
    host, with the second language optional.

    One group per host and `stop_after_group`, because `.com` is the same
    career site as `.de` (docstring). The first language of a host is the
    `primary` one, so a 404 on it skips the rest of that host instead of
    spending one request per language on a tenant that has no career site
    at all.
    """
    languages = tuple(languages or DEFAULT_LANGUAGES)
    return [base.Variant(key=f'{host}:{language}',
                         url=feed_url(tenant, language=language, host=host),
                         slug=language, host=host, language=language, group=host,
                         primary=(index == 0), optional=(index > 0), stop_after_group=True)
            for host in (hosts or HOSTS)
            for index, language in enumerate(languages)]


def posting_url(tenant, posting_id, *, host=HOSTS[0], language=None):
    """The link back, per the spec's table. The language is appended only
    when asked for, because the bare URL is the canonical one."""
    url = f'https://{tenant}.{host}/job/{posting_id}'
    return f'{url}?language={language}' if language else url


def posting_key(tenant, posting_id):
    """`personio:{tenant}:{id}`, the spec's stable key."""
    return base.posting_key(PROVIDER, tenant, posting_id)


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
    if match and match['provider'] == PROVIDER:
        return {'tenant': match['tenant'], 'host': _host_suffix(host), 'how': 'posting_url'}
    for suffix in HOSTS:
        if host.endswith('.' + suffix):
            tenant = host[:-(len(suffix) + 1)]
            # A nested label ("careers.acme.jobs.personio.de") is not a
            # tenant id and is not guessed at.
            if re.fullmatch(TENANT_ID, tenant):
                return {'tenant': tenant, 'host': suffix, 'how': 'host_pattern'}
    return None


def _host_suffix(host):
    for suffix in HOSTS:
        if host == suffix or host.endswith('.' + suffix):
            return suffix
    return HOSTS[0]


def _text(element):
    return (element.text or '').strip() if element is not None else ''


def parse_feed(xml):
    """A feed body -> a list of raw position dicts, in feed order.

    Raises `ElementTree.ParseError` for a body that is not XML and
    `ValueError` for XML that is not a Personio feed, so a caller can
    tell "this tenant does not exist" from "this tenant's feed broke" --
    which is the difference the spec's 99% parse-success criterion is
    counted over.

    Every field is treated as optional, per the spec. An absent element
    becomes an absent key, never an empty string that looks like a value
    the tenant set.
    """
    root = ElementTree.fromstring(xml)
    if root.tag != ROOT_TAG:
        raise ValueError(f'not a Personio feed: root element is {root.tag!r}, '
                         f'expected {ROOT_TAG!r}')
    return [_parse_position(node) for node in root.findall(POSITION_TAG)]


def _parse_position(node):
    """One `<position>` as the feed states it, with nothing mapped yet."""
    raw = {}
    for child in node:
        if child.tag == 'jobDescriptions':
            blocks = []
            for block in child.findall('jobDescription'):
                blocks.append({'name': _text(block.find('name')),
                               'value': (block.find('value').text or '')
                                        if block.find('value') is not None else ''})
            raw['jobDescriptions'] = blocks
        elif child.tag == 'additionalOffices':
            raw['additionalOffices'] = [_text(office) for office in child.findall('office')
                                        if _text(office)]
        else:
            value = _text(child)
            if value:
                raw[child.tag] = value
    return raw


def has_descriptions(positions):
    """Whether this feed variant actually carries posting text.

    The one way to tell a language the tenant publishes from a language
    the server merely accepted: an unsupported language answers 200 with
    every `jobDescriptions` empty (see the docstring).
    """
    return any(block.get('value', '').strip()
               for position in positions
               for block in position.get('jobDescriptions') or ())


#: The contract's name for the same question.
variant_carries_text = has_descriptions


def description_text(blocks):
    """The spec's rule: concatenate the named blocks in order and keep
    the block names as headings."""
    parts = []
    for block in blocks or ():
        lines = base.html_to_text(block.get('value'))
        name = (block.get('name') or '').strip()
        if name:
            parts.append(name)
        parts.extend(lines)
        if name or lines:
            parts.append('')
    return '\n'.join(parts).strip()


def _workload_records(schedule, title, text, *, guide_version):
    """`workload_min` / `workload_max` value records.

    A Pensum stated in the title or the text beats Personio's own
    `schedule` field, per the spec; the shared reader and the shared
    rounding rule are `base.pensum` and `base.workload_records`, because
    a Swiss percentage is written the same way in every provider's feed.
    """
    pair, quote = base.pensum(title, text)
    if pair:
        return base.workload_records(
            pair, raw=schedule or None, confidence=0.9, guide_version=guide_version,
            rule='stated in the title or the posting text')
    if (schedule or '').casefold() in SCHEDULE_MAP:
        pair, confidence = SCHEDULE_MAP[(schedule or '').casefold()]
        return base.workload_records(
            pair, raw=schedule, confidence=confidence, guide_version=guide_version,
            rule=("the spec's mapping of Personio's schedule field; no percentage is stated "
                  'in the title or the text'))
    if schedule:
        _logger.info('personio: schedule %r has no workload mapping; stored unknown', schedule)
    return base.workload_records(
        None, raw=schedule or None, guide_version=guide_version,
        rule='the feed states no schedule this taxonomy can read as a Pensum')


def _contract_record(employment_type, *, guide_version):
    return base.coded_record(
        'contract', employment_type, CONTRACT_MAP, provider=PROVIDER,
        raw_field='employmentType', guide_version=guide_version,
        rule="the spec's employmentType mapping",
        missing_rule='the feed states no employment type',
        unmapped_rule='the feed states an employment type this mapping does not cover')


def _seniority_record(hint, *, guide_version):
    """Personio's `seniority` word onto the D6 scale.

    `base.optional_code_record` rather than `base.coded_record`, because
    this table has a third case: a word that IS in the table and
    deliberately maps to no code ("experienced" is "s1 or s2" in the
    spec, and a value record holds one code). That is a different fact
    from a word the table has never seen, and the rule text says which.
    """
    return base.optional_code_record(
        'seniority', hint, SENIORITY_MAP, provider=PROVIDER, raw_field='seniority',
        guide_version=guide_version,
        rule_mapped='CAREER-58 D6, which this module follows over the spec table for '
                    'entry-level; see the module docstring',
        rule_ambiguous="the spec leaves this hint to the classifier, so the value is unknown "
                       'and the feed word is kept in seniority_hint')


def content_hash(mapped):
    """The posting's content hash over `HASHED_FIELDS`. See
    `base.content_hash` for why value records are not in it."""
    return base.content_hash(mapped, HASHED_FIELDS)


def map_posting(raw, *, tenant, variant=None, language=None, host=None, guide_version=None):
    """One raw position -> the CareerOS record, per the spec's table.

    The record has three layers, kept apart on purpose:

      * the feed's own words, under their own keys (`title`,
        `employer_name`, `offices`, `employment_type_raw`,
        `seniority_hint`, `occupation`, ...). Nothing is lost and
        nothing is interpreted.
      * `values`, the D4 value records for the dimensions this feed can
        actually state (contract, workload min/max, seniority, language).
        The location records are added by the caller, which is the only
        part that needs the geocoder.
      * `key`, `content_hash` and `provenance`, all three from
        `base.finalize`, so no adapter can forget any of them.

    `variant` is the contract's way of saying which feed this came from;
    `language` and `host` are CAREER-53's and still work, because a
    Personio posting is named by both.

    Absent is absent: a field the feed does not carry is None or an empty
    list, never a guess (PROJECT.md: no fabricated data anywhere).
    """
    language = language or (variant.language if variant else None) or DEFAULT_LANGUAGES[0]
    host = host or (variant.host if variant else None) or HOSTS[0]
    posting_id = raw.get('id')
    if not posting_id:
        raise ValueError('a position with no id cannot be keyed')
    offices = [office for office in [raw.get('office')] + list(raw.get('additionalOffices') or ())
               if office]
    keywords = [word.strip() for word in (raw.get('keywords') or '').split(',') if word.strip()]
    blocks = raw.get('jobDescriptions') or []
    title = raw.get('name') or ''
    text = description_text(blocks)
    mapped = {
        'provider': PROVIDER,
        'tenant': tenant,
        'posting_id': posting_id,
        'url': posting_url(tenant, posting_id, host=host),
        'feed_host': host,
        'feed_language': language,
        'title': title,
        'employer_name': raw.get('subcompany'),
        'department': raw.get('department'),
        'recruiting_category': raw.get('recruitingCategory'),
        'offices': offices,
        'employment_type_raw': raw.get('employmentType'),
        'schedule_raw': raw.get('schedule'),
        'seniority_hint': raw.get('seniority'),
        'years_of_experience': raw.get('yearsOfExperience'),
        'occupation': raw.get('occupation'),
        'occupation_category': raw.get('occupationCategory'),
        'keywords': keywords,
        'published_at': raw.get('createdAt'),
        'description_blocks': [{'name': block.get('name'), 'text': '\n'.join(
            base.html_to_text(block.get('value')))} for block in blocks],
        'description': text,
        'has_description': bool(text),
    }
    mapped['values'] = {
        'contract': _contract_record(mapped['employment_type_raw'], guide_version=guide_version),
        'seniority': _seniority_record(mapped['seniority_hint'], guide_version=guide_version),
        'language': base.language_record(
            language, raw_field='feed_language', guide_version=guide_version,
            rule='the language parameter of the feed variant this posting came from, which is '
                 'the language the tenant publishes it in rather than a detection of the text'),
        **_workload_records(mapped['schedule_raw'], title, text, guide_version=guide_version),
    }
    return base.finalize(mapped, adapter=sys.modules[__name__])


#: The snapshot codec, shared with every other adapter. Kept as names of
#: this module because the fetcher asks the adapter for them.
compress = base.compress
decompress = base.decompress
