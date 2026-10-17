"""The Personio mapper: feed URL, XML parse, field mapping.

Everything Personio-specific in CAREER-53 is in this module. A Greenhouse
adapter is a sibling with the same three entry points -- `feed_urls`,
`parse_feed`, `map_posting` -- and the rest of `careeros.feeds` does not
change (the spec: "a new mapper, not a new pipeline").

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
text first (`80-100%`, `60 %`, `80 – 100 %`) and only falls back to the
range. A value record holds one code, so a workload RANGE is two records,
`workload_min` and `workload_max`, over the same dimension -- which is
what workload.yaml's own `range` block describes.

## Reuse

`careeros.intake.Posting` is the repository's HTML-to-text parser and it
takes a fragment, which is what a `jobDescription` value is (CDATA
HTML). It is reused here together with `intake._collapse_lines`, a
private helper, rather than writing a fourth HTML-to-text pass: the
alternative is duplicating block-tag handling that already exists and is
already tested. `org_intake.ats.detect_ats` is reused for tenant
recognition in `careeros.feeds.discovery` for the same reason.
"""
import gzip
import hashlib
import json
import logging
import re
from xml.etree import ElementTree

from careeros import intake, taxonomy

_logger = logging.getLogger(__name__)

PROVIDER = 'personio'

#: Both hosts Personio serves a career site on. `.de` first, per the
#: spec; see the module docstring on what checking that actually found.
HOSTS = ('jobs.personio.de', 'jobs.personio.com')

#: The languages the feed accepts, from Personio's own reference. A
#: language outside this list is not refused by the server -- it answers
#: 200 with empty descriptions -- so the list is ours to respect.
FEED_LANGUAGES = ('de', 'en', 'fr', 'es', 'nl', 'it', 'pt')

#: What CAREER-53 fetches. German first because most Zurich postings are
#: in German (the spec's own reason for Personio first); English second
#: and only kept when it actually carries descriptions.
DEFAULT_LANGUAGES = ('de', 'en')

ROOT_TAG = 'workzag-jobs'
POSITION_TAG = 'position'

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
    'working-student': 'working_student',
    'working_student': 'working_student',
    'temporary': 'temporary_assignment',
    'fixed-term': 'fixed_term',
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

#: A Pensum as a Swiss posting writes it: "80-100%", "60 %", "80 – 100%".
#: Checked against the title and the posting text before the part-time
#: fallback, per the spec.
_PENSUM = re.compile(r'(\d{2,3})\s*(?:[-–—]|\bbis\b|\bto\b)\s*(\d{2,3})\s*%'
                     r'|(?<![\d.,])(\d{2,3})\s*%')

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
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', tenant or ''):
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


def posting_url(tenant, posting_id, *, host=HOSTS[0], language=None):
    """The link back, per the spec's table. The language is appended only
    when asked for, because the bare URL is the canonical one."""
    url = f'https://{tenant}.{host}/job/{posting_id}'
    return f'{url}?language={language}' if language else url


def posting_key(tenant, posting_id):
    """`personio:{tenant}:{id}`, the spec's stable key."""
    return f'{PROVIDER}:{tenant}:{posting_id}'


def _text(element):
    return (element.text or '').strip() if element is not None else ''


def _html_to_text(fragment):
    """A `jobDescription` value (CDATA HTML) as plain lines.

    Reuses the repository's own HTML-to-text parser; see the docstring's
    Reuse note on why `_collapse_lines` is called despite being private.
    """
    parser = intake.Posting()
    parser.feed(fragment or '')
    parser.close()
    return intake._collapse_lines(parser.text)


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


def description_text(blocks):
    """The spec's rule: concatenate the named blocks in order and keep
    the block names as headings."""
    parts = []
    for block in blocks or ():
        lines = _html_to_text(block.get('value'))
        name = (block.get('name') or '').strip()
        if name:
            parts.append(name)
        parts.extend(lines)
        if name or lines:
            parts.append('')
    return '\n'.join(parts).strip()


def _pensum(*texts):
    """A workload range stated in the title or the text, or None.

    The first match wins and a single figure is (n, n), per
    workload.yaml's range rule. Anything outside 10-100 is ignored
    rather than clamped: "150%" is not a Pensum and a clamped 100 would
    invent one.
    """
    for text in texts:
        for match in _PENSUM.finditer(text or ''):
            low, high, single = match.groups()
            pair = (int(low), int(high)) if low else (int(single), int(single))
            if 10 <= pair[0] <= pair[1] <= 100:
                return pair, match.group(0).strip()
    return None, None


def _step(value, *, up):
    """A percentage onto the taxonomy's steps of ten. Rounds the way
    workload.yaml says: a minimum rounds down and a maximum rounds up, so
    the stored range never overstates what the posting asks for."""
    step = ((value + 9) // 10 * 10) if up else (value // 10 * 10)
    return str(max(10, min(100, step)))


def _workload_records(schedule, title, text, *, guide_version):
    """`workload_min` / `workload_max` value records, or None.

    Two records over one dimension, because a value record holds one code
    and a Pensum is a pair (workload.yaml's `range` block).
    """
    pair, quote = _pensum(title, text)
    if pair:
        method, confidence = 'stated in the title or the posting text', 0.9
        evidence = {'schedule': schedule or None, 'stated': quote, 'rule': method}
    elif (schedule or '').casefold() in SCHEDULE_MAP:
        (pair, confidence) = SCHEDULE_MAP[(schedule or '').casefold()]
        evidence = {'schedule': schedule,
                    'rule': "the spec's mapping of Personio's schedule field; no percentage "
                            'is stated in the title or the text'}
    else:
        if schedule:
            _logger.info('personio: schedule %r has no workload mapping; stored unknown', schedule)
        evidence = {'schedule': schedule or None,
                    'rule': 'the feed states no schedule this taxonomy can read as a Pensum'}
        return {'workload_min': taxonomy.make_value_record(
                    'workload', taxonomy.UNKNOWN, 'feed', evidence=evidence,
                    guide_version=guide_version),
                'workload_max': taxonomy.make_value_record(
                    'workload', taxonomy.UNKNOWN, 'feed', evidence=evidence,
                    guide_version=guide_version)}
    return {'workload_min': taxonomy.make_value_record(
                'workload', _step(pair[0], up=False), 'feed', confidence=confidence,
                evidence=evidence, guide_version=guide_version),
            'workload_max': taxonomy.make_value_record(
                'workload', _step(pair[1], up=True), 'feed', confidence=confidence,
                evidence=evidence, guide_version=guide_version)}


def _contract_record(employment_type, *, guide_version):
    key = (employment_type or '').casefold().replace(' ', '-')
    code = CONTRACT_MAP.get(key)
    if code is None and employment_type:
        _logger.info('personio: employmentType %r has no contract mapping; stored unknown',
                     employment_type)
    return taxonomy.make_value_record(
        'contract', code or taxonomy.UNKNOWN, 'feed',
        confidence=0.9 if code else None,
        evidence={'employmentType': employment_type or None,
                  'rule': "the spec's employmentType mapping" if code else
                          ('the feed states no employment type' if not employment_type else
                           'the feed states an employment type this mapping does not cover')},
        guide_version=guide_version)


def _seniority_record(hint, *, guide_version):
    key = (hint or '').casefold()
    code = SENIORITY_MAP.get(key)
    if hint and key not in SENIORITY_MAP:
        _logger.info('personio: seniority %r is not in the mapping; stored unknown', hint)
    rule = ('CAREER-58 D6, which this module follows over the spec table for entry-level; '
            'see the module docstring'
            if code else
            "the spec leaves this hint to the classifier, so the value is unknown and the "
            'feed word is kept in seniority_hint')
    return taxonomy.make_value_record(
        'seniority', code or taxonomy.UNKNOWN, 'feed',
        confidence=0.8 if code else None,
        evidence={'seniority': hint or None, 'rule': rule},
        guide_version=guide_version)


def _language_record(language, *, guide_version):
    """The feed variant this posting was read from, as a language record.

    Honest about what it is: the language the TENANT publishes this feed
    variant in, which is a real fact, and not a detection of the text.
    A tenant that publishes a German feed containing an English posting
    exists, so the confidence is not 1.0.
    """
    return taxonomy.make_value_record(
        'language', language if taxonomy.valid_code('language', language) else taxonomy.UNKNOWN,
        'feed', confidence=0.9,
        evidence={'feed_language': language,
                  'rule': 'the language parameter of the feed variant this posting came from, '
                          'which is the language the tenant publishes it in rather than a '
                          'detection of the text'},
        guide_version=guide_version)


def content_hash(mapped):
    """The posting's content hash: sha256 over the feed's own statement
    of it, canonicalised.

    Only `HASHED_FIELDS`, so a re-fetch of an unchanged posting hashes
    the same and the store writes no second snapshot. Value records are
    deliberately NOT hashed: they carry a `classified_at` timestamp and a
    taxonomy version, so hashing them would make every snapshot new after
    a taxonomy bump even though the posting had not changed.
    """
    payload = {field: mapped.get(field) for field in HASHED_FIELDS}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


def map_posting(raw, *, tenant, language, host=HOSTS[0], guide_version=None):
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
      * `content_hash`, over the first layer only. See `content_hash`.

    Absent is absent: a field the feed does not carry is None or an empty
    list, never a guess (PROJECT.md: no fabricated data anywhere).
    """
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
        'key': posting_key(tenant, posting_id),
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
            _html_to_text(block.get('value')))} for block in blocks],
        'description': text,
        'has_description': bool(text),
    }
    mapped['values'] = {
        'contract': _contract_record(mapped['employment_type_raw'], guide_version=guide_version),
        'seniority': _seniority_record(mapped['seniority_hint'], guide_version=guide_version),
        'language': _language_record(language, guide_version=guide_version),
        **_workload_records(mapped['schedule_raw'], title, text, guide_version=guide_version),
    }
    mapped['content_hash'] = content_hash(mapped)
    return mapped


def compress(text):
    """A raw feed body as the bytes a snapshot file holds. gzip with
    mtime=0, so two identical bodies compress to identical bytes and a
    byte comparison of two snapshots means what it looks like."""
    return gzip.compress(text.encode(), mtime=0)


def decompress(blob):
    return gzip.decompress(blob).decode()
