"""The adapter contract: what a provider supplies, and what it never has to.

CAREER-54. CAREER-53 said the next adapter must be "a new mapper, not a
new pipeline". This module is what makes that a contract instead of an
intention: it states the five things a provider adapter owns, supplies
everything else, and REFUSES a posting that skips the part the owner
cares about most (provenance, owner ruling 2026-10-17 2a).

## What a provider adapter owns

A provider adapter is a module. `careeros.feeds.registry` lists them.
Required, and checked by `check_adapter` (which the suite runs over every
registered adapter, so a new adapter cannot half-exist):

    PROVIDER          the id, which is also the first field of a posting key
    DOC_URL           the provider's own documentation of this endpoint
    DOC_ACCESSED      the date that documentation was last read (ISO)
    SNAPSHOT_SUFFIX   'xml' or 'json': what a raw feed body is
    HASHED_FIELDS     the posting fields the content hash is taken over
    CDX_PATTERNS      ((url, matchType), ...) for Common Crawl discovery
    TENANT_ID         a compiled pattern a tenant id must match

    feed_variants(tenant, **options) -> [Variant]
    tenant_from_url(url)             -> {'tenant', 'host', 'how'} | None
    parse_feed(body)                 -> [raw posting, ...]
    map_posting(raw, *, tenant, variant, guide_version) -> mapped posting
    posting_url(tenant, posting_id)  -> the canonical link back

Optional, with the defaults in this module when an adapter has no need:

    VARIANT_OPTIONS    option names `feed_variants` accepts from the CLI
    variant_carries_text(parsed)        -> bool   (default: True)
    next_page(variant, parsed, seen)    -> Variant | None (default: None)
    detail_variant(mapped)              -> Variant | None (default: None)
    merge_detail(mapped, parsed, ...)   -> mapped (required with the above)

## What the shared pipeline owns, and no adapter reimplements

`fetch` (requests, retries, conditional requests, paging, the raw
snapshot, the detail pass), `geocode` (office text -> BFS municipality),
`store` (immutable snapshots, the run manifest, closure detection),
`discovery` (the Common Crawl route, the vault route, the website probe,
tenant merging) and `export` (the golden-set pool). Five providers landed
on 2026-10-17 without any of those five modules growing a provider name.

## The field-mapping rule, stated once

Every mapped field that becomes a CareerOS dimension is a
`taxonomy.make_value_record(..., 'feed')` carrying the raw field it came
from as evidence. A field the feed does not state is **not omitted**: it
is a record with the value `unknown` and a reason (D4: `unknown` is a
real value, and "we looked and the feed says nothing" is a different fact
from no record at all). `unknown_record` below is how an adapter says
that, and `map_value` is how it says the other thing, so neither has to
restate the shape.

Nothing is guessed. A provider vocabulary word that is not in an
adapter's own mapping table becomes `unknown` with the word in the
evidence and a log line naming it, never the nearest code.

## Provenance (owner ruling 2026-10-17, priority a: "keep the source of
the job")

Every posting carries a `provenance` block, and the store refuses to
write one that does not. The block is built in two halves because its two
halves are known at different times:

  * `posting_provenance`, at mapping time: provider, tenant, posting id,
    the canonical posting URL, the content hash, and the provider's own
    documentation of the endpoint it came from.
  * `attach_fetch_provenance`, after the request: the exact feed URL, the
    variant, the raw-feed snapshot path and the fetch time and run id.

`require_provenance` is what `store.write_posting_snapshot` and
`store.record_run` call. It raises `ProvenanceError`, which is a bug in an
adapter and not a bad posting -- so it is loud, not counted.
"""
import gzip
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field as dataclass_field

from careeros import ingest, intake, taxonomy

_logger = logging.getLogger(__name__)


# --- the variant: one request a feed is read through ------------------------

@dataclass(frozen=True)
class Variant:
    """One feed request for one tenant, as the shared fetcher sees it.

    Personio reads a tenant through four of these (two hosts x two
    languages); Greenhouse, Ashby and Recruitee through one; Lever
    through two (its US and EU instances are separate boards that share a
    slug -- measured 2026-10-17: `leverdemo` has 10 postings on one and
    324 on the other); SmartRecruiters through one per page of 100.

    The fields that are not just "a URL" each exist because one provider
    needs them:

      * `slug` goes in the raw snapshot's file name, so a snapshot path
        stays readable and stable. Personio's slug is its language, which
        is what keeps CAREER-53's own snapshot paths unchanged.
      * `group` collects the variants of one career site. A `primary`
        variant answering 404 means the whole group is absent, so the
        rest of it is not requested (measured on Personio: a third of
        discovered tenants serve no feed at all, and each of them would
        otherwise cost four requests instead of one).
      * `optional` variants are skipped once the store knows they carry
        no posting text -- Personio's second language, which answers 200
        with empty descriptions rather than 404.
      * `stop_after_group` says a successful group is the whole answer.
        True for Personio (.com is the same career site as .de) and
        False for Lever (both instances are real boards).
    """
    key: str
    url: str
    slug: str
    host: str = ''
    language: str = None
    group: str = ''
    primary: bool = True
    optional: bool = False
    stop_after_group: bool = True
    page: int = 0
    detail_of: str = None
    options: dict = dataclass_field(default_factory=dict)

    @property
    def group_key(self):
        return self.group or self.host or self.key


# --- the snapshot codec, shared because gzip is not a provider concern -----

def compress(text):
    """A raw feed body as the bytes a snapshot file holds. gzip with
    mtime=0, so two identical bodies compress to identical bytes and a
    byte comparison of two snapshots means what it looks like."""
    return gzip.compress(text.encode(), mtime=0)


def decompress(blob):
    return gzip.decompress(blob).decode()


#: The mapped fields that hold text a person reads, and therefore the
#: ones `finalize` runs plain text over. Deliberately a list of names and
#: not "every string in the posting": a provider id, a tenant, a URL, a
#: posting id and a raw vocabulary word are data, not prose, and must
#: reach the store exactly as the feed stated them.
TEXT_FIELDS = ('title', 'employer_name', 'department', 'team',
               'recruiting_category', 'location_raw', 'description')


def html_to_text(fragment):
    """An HTML description as plain lines.

    Reuses the repository's own HTML-to-text parser rather than a fourth
    pass over block tags. Four of the six adapters need it: Personio's
    CDATA `jobDescription`, Greenhouse's entity-escaped `content`,
    Lever's `description` and Ashby's `descriptionHtml`.
    """
    parser = intake.Posting()
    parser.feed(fragment or '')
    parser.close()
    return intake._collapse_lines(parser.text)


# --- keys and hashes -------------------------------------------------------

def posting_key(provider, tenant, posting_id):
    """`{provider}:{tenant}:{id}`, the key the store is sharded by. One
    shape for every provider, which is what lets one store hold them
    all."""
    return f'{provider}:{tenant}:{posting_id}'


def content_hash(mapped, fields):
    """sha256 over the feed's own statement of a posting, canonicalised.

    Only the listed fields, in the adapter's own order: a re-fetch of an
    unchanged posting has to hash the same, or the snapshot store would
    grow a new snapshot every day. Value records are deliberately NOT
    hashable material -- they carry a `classified_at` and a taxonomy
    version, so hashing them would make every snapshot new after a
    taxonomy bump even though the posting had not changed.
    """
    payload = {name: mapped.get(name) for name in fields}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                           default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# --- value records: the two sentences every adapter needs ------------------

def _mapping_logger(provider):
    """The adapter's own logger, so an unmapped vocabulary word is
    reported against the module that owns the mapping table rather than
    against this shared one. `careeros.feeds.greenhouse` is where a
    maintainer looks for it."""
    return logging.getLogger(f'careeros.feeds.{provider}')


def unknown_record(dimension, *, raw=None, raw_field='raw', rule, guide_version=None, log=None):
    """"The feed says nothing this dimension can read", as a D4 record.

    `raw` is whatever the provider did say and `raw_field` is the name it
    said it under, so the evidence names the provider's own field
    (`{'employmentType': 'zivildienst'}`) rather than a generic key: the
    brief's "the raw field or snippet it came from". `rule` is why the
    mapping stopped. `log` is `(provider, word)` and is logged when
    given, because an unmapped vocabulary word is the thing a maintainer
    has to see to extend a mapping table -- field VALUES stay out of the
    log, per CAREER-30, and a provider's closed vocabulary is not one.
    """
    if log:
        _mapping_logger(log[0]).info('%s: %r has no %s mapping; stored unknown',
                                     log[0], log[1], dimension)
    return taxonomy.make_value_record(
        dimension, taxonomy.UNKNOWN, 'feed',
        evidence={raw_field: raw, 'rule': rule}, guide_version=guide_version)


def map_value(dimension, code, *, raw, raw_field='raw', rule, confidence=0.9,
              guide_version=None, extra=None):
    """One mapped dimension as a D4 record with its evidence.

    `raw` is the provider field the code was read from, under its own
    name, and `rule` names the table that read it, so a stored value can
    always answer "why".
    """
    evidence = {raw_field: raw, 'rule': rule}
    evidence.update(extra or {})
    return taxonomy.make_value_record(dimension, code, 'feed', confidence=confidence,
                                      evidence=evidence, guide_version=guide_version)


def coded_record(dimension, raw, table, *, provider, raw_field, rule, missing_rule=None,
                 unmapped_rule=None, confidence=0.9, guide_version=None):
    """A provider vocabulary word through an adapter's mapping table.

    The one shape for contract, work model and anything else a provider
    states as its own enum: a hit is a record with the table named as its
    rule, a word the table does not carry is `unknown` with the word in
    the evidence and a log line, and no word at all is `unknown` with a
    different reason. Never the nearest code.

    The lookup folds case and treats `-`, `_` and a space as the same
    separator, because the same provider writes `working-student` and
    `working_student` in different fields.
    """
    key = (raw or '').strip().casefold().replace(' ', '_').replace('-', '_')
    code = table.get(key)
    if code:
        return map_value(dimension, code, raw=raw, raw_field=raw_field, rule=rule,
                         confidence=confidence, guide_version=guide_version)
    if not str(raw or '').strip():
        return unknown_record(dimension, raw=None, raw_field=raw_field,
                              rule=missing_rule or f'the feed states no {dimension}',
                              guide_version=guide_version)
    return unknown_record(
        dimension, raw=raw, raw_field=raw_field,
        rule=unmapped_rule or f'the feed states a {dimension} this mapping does not cover',
        guide_version=guide_version, log=(provider, raw))


def optional_code_record(dimension, raw, table, *, provider, raw_field, rule_mapped,
                         rule_ambiguous, confidence=0.8, guide_version=None):
    """A provider vocabulary where some words pin a code and others
    deliberately do not.

    Three cases, because three different things can be true and a
    stored value has to say which:

      * the word maps onto a code -> the code, with `rule_mapped`;
      * the word is in the table and maps to None -> `unknown` with
        `rule_ambiguous`. "Experienced" and "mid-senior level" name a
        span of the seniority scale and a value record holds one code,
        so the honest answer is classified-and-came-up-empty with the
        provider's word kept in the evidence;
      * the word is not in the table at all -> the same `unknown`, plus
        a log line, because that is a vocabulary this mapping has never
        seen and the maintainer is the one who can extend it.

    Introduced for Personio's `seniority` and reused by Recruitee's
    `experience_code` and SmartRecruiters' `experienceLevel`, which are
    three spellings of the same problem.
    """
    key = (raw or '').strip().casefold().replace(' ', '_').replace('-', '_')
    code = table.get(key)
    if code:
        return map_value(dimension, code, raw=raw, raw_field=raw_field, rule=rule_mapped,
                         confidence=confidence, guide_version=guide_version)
    if raw and key not in table:
        _mapping_logger(provider).info('%s: %s %r is not in the mapping; stored unknown',
                                       provider, dimension, raw)
    return unknown_record(dimension, raw=raw or None, raw_field=raw_field,
                          rule=rule_ambiguous, guide_version=guide_version)


#: A Pensum as a Swiss posting writes it: "80-100%", "60 %", "80 - 100%".
#: Shared because every provider's postings are written by the same Swiss
#: employers, and only Personio has a `schedule` field to fall back on.
_PENSUM = re.compile(r'(\d{2,3})\s*(?:[-–—]|\bbis\b|\bto\b)\s*(\d{2,3})\s*%'
                     r'|(?<![\d.,])(\d{2,3})\s*%')


#: Words that make a percentage a Pensum rather than a percentage.
#: Required for a match inside a posting TEXT and not for one in the
#: title; see `pensum`.
_PENSUM_WORD = re.compile(
    r'pensum|arbeitszeit|besch[aä]ftigungsgrad|anstellungsgrad|stellenprozent|'
    r'arbeitsumfang|workload|work\s?load|teilzeit|vollzeit|part[-\s]?time|full[-\s]?time|'
    r'\bfte\b|stellenumfang|t[aä]tigkeitsgrad', re.I)

#: How far from a percentage a Pensum word may be and still be about it.
_PENSUM_WINDOW = 60


def pensum(title, *texts):
    """A workload stated in a title or a posting text, or None.

    Returns `(pair, quote)`. The first match wins and a single figure is
    (n, n), per workload.yaml's range rule. Anything outside 10-100 is
    ignored rather than clamped: "150%" is not a Pensum and a clamped
    100 would invent one.

    A match in the TITLE is taken as it stands, because a Swiss posting
    writes the Pensum there and a title has no room for another kind of
    percentage. **A match in the posting TEXT needs a Pensum word beside
    it** (`_PENSUM_WORD`, within `_PENSUM_WINDOW` characters), which
    CAREER-54 added after the first live run of the Ashby adapter read
    "30%" out of a 20 000-character English description -- about
    something else entirely -- and stored it as a workload of 30. A
    percentage in prose is usually a statistic; the whole point of this
    reader is the Swiss "Pensum 80-100%" line, and that line says so.
    """
    for match in _PENSUM.finditer(title or ''):
        pair = _pair(match)
        if pair:
            return pair, match.group(0).strip()
    for text in texts:
        body = text or ''
        for match in _PENSUM.finditer(body):
            pair = _pair(match)
            if not pair:
                continue
            window = body[max(0, match.start() - _PENSUM_WINDOW):
                          match.end() + _PENSUM_WINDOW]
            if _PENSUM_WORD.search(window):
                return pair, ' '.join(window.split())[:160]
    return None, None


def _pair(match):
    low, high, single = match.groups()
    pair = (int(low), int(high)) if low else (int(single), int(single))
    return pair if 10 <= pair[0] <= pair[1] <= 100 else None


def workload_step(value, *, up):
    """A percentage onto the taxonomy's steps of ten. Rounds the way
    workload.yaml says: a minimum rounds down and a maximum rounds up, so
    the stored range never overstates what the posting asks for."""
    step = ((value + 9) // 10 * 10) if up else (value // 10 * 10)
    return str(max(10, min(100, step)))


def workload_records(pair, *, raw, raw_field='raw', rule, confidence=0.9, guide_version=None):
    """`workload_min` / `workload_max`, or two `unknown`s when `pair` is
    None. Two records over one dimension, because a value record holds one
    code and a Pensum is a pair (workload.yaml's own `range` block)."""
    if not pair:
        return {name: unknown_record('workload', raw=raw, raw_field=raw_field, rule=rule,
                                     guide_version=guide_version)
                for name in ('workload_min', 'workload_max')}
    return {
        'workload_min': map_value('workload', workload_step(pair[0], up=False), raw=raw,
                                  raw_field=raw_field, rule=rule, confidence=confidence,
                                  guide_version=guide_version),
        'workload_max': map_value('workload', workload_step(pair[1], up=True), raw=raw,
                                  raw_field=raw_field, rule=rule, confidence=confidence,
                                  guide_version=guide_version),
    }


def language_record(language, *, rule, raw_field='language', guide_version=None, confidence=0.9):
    """The language a posting was read in, as a D4 record.

    Honest about what it is: the language the TENANT publishes this feed
    variant (or this posting's own `language` field) in, which is a real
    fact, and not a detection of the text -- so the confidence is not 1.0
    and the rule says which of the two it was.
    """
    if not language:
        return unknown_record('language', raw=None, raw_field=raw_field,
                              rule='the feed states no language for this posting',
                              guide_version=guide_version)
    code = str(language).split('-')[0].casefold()
    if not taxonomy.valid_code('language', code):
        return unknown_record('language', raw=language, raw_field=raw_field,
                              rule='the feed states a language outside the taxonomy list',
                              guide_version=guide_version, log=('feed', language))
    return map_value('language', code, raw=language, raw_field=raw_field, rule=rule,
                     confidence=confidence, guide_version=guide_version)


# --- provenance ------------------------------------------------------------

class ProvenanceError(ValueError):
    """A posting the store refuses, because its source chain is broken.

    Raised rather than counted: a posting with no provenance is an
    adapter that skipped the contract, not a tenant with a bad feed.
    """


#: What `posting_provenance` fills, at mapping time.
MAPPED_PROVENANCE = ('provider', 'tenant', 'posting_id', 'url', 'content_hash',
                     'api_doc_url', 'api_doc_accessed')
#: What `attach_fetch_provenance` fills, after the request.
FETCH_PROVENANCE = ('feed_url', 'feed_variant', 'feed_snapshot', 'fetched_at', 'run_id')
#: The whole block. The store requires every one of them.
PROVENANCE_FIELDS = MAPPED_PROVENANCE + FETCH_PROVENANCE

#: A D4 value record's own required keys, checked on the way into the
#: store so a hand-built dict cannot pass for one.
VALUE_RECORD_FIELDS = ('value', 'source', 'taxonomy_version', 'classified_at')


def posting_provenance(mapped, *, adapter):
    """The half of the provenance block mapping knows.

    Called by `finalize`, so an adapter gets it by returning through the
    contract rather than by remembering to build it.
    """
    return {
        'provider': mapped.get('provider'),
        'tenant': mapped.get('tenant'),
        'posting_id': str(mapped.get('posting_id') or '') or None,
        'url': mapped.get('url'),
        'content_hash': mapped.get('content_hash'),
        'api_doc_url': getattr(adapter, 'DOC_URL', None),
        'api_doc_accessed': getattr(adapter, 'DOC_ACCESSED', None),
    }


def finalize(mapped, *, adapter):
    """The last line of every adapter's `map_posting`.

    Adds the four things no adapter should be able to forget: plain text
    in the fields that hold text, the posting key, the content hash over
    the adapter's own `HASHED_FIELDS`, and the mapping half of the
    provenance block. Raises for a posting that cannot be keyed or that
    states no value record at all, because both are adapter bugs and
    would otherwise surface as a store refusal much later.

    The text pass is here rather than in each adapter for the same
    reason the hash is: six adapters read a feed that states a title,
    an employer name and an office as text, and a feed that puts markup
    or an entity in one of them ("Smith &amp; Co") would otherwise put
    it in the vault. `html_to_text` already covers the description
    bodies the adapters parse out of HTML; this covers the short fields,
    and the employer name loses a leading internal site code at the same
    time (careeros.ingest.company_name_text). It runs BEFORE the hash,
    so the hash is taken over what is actually stored and a re-fetch of
    an unchanged posting still hashes the same.
    """
    for name in ('provider', 'tenant', 'posting_id', 'url'):
        if not mapped.get(name):
            raise ProvenanceError(f'{adapter.PROVIDER}: a posting with no {name} cannot be stored')
    if not mapped.get('values'):
        raise ProvenanceError(f'{adapter.PROVIDER}: a posting with no value records cannot be '
                              'stored; an absent field is an unknown record, not no record')
    for name in TEXT_FIELDS:
        if isinstance(mapped.get(name), str):
            mapped[name] = (ingest.company_name_text(mapped[name]) if name == 'employer_name'
                            else ingest.plain_text(mapped[name]))
    mapped['key'] = posting_key(mapped['provider'], mapped['tenant'], mapped['posting_id'])
    mapped['content_hash'] = content_hash(mapped, adapter.HASHED_FIELDS)
    mapped['provenance'] = posting_provenance(mapped, adapter=adapter)
    return mapped


def attach_fetch_provenance(mapped, *, variant, feed_snapshot, run, at):
    """The half of the provenance block the request knows. Mutates and
    returns the posting, which is what the fetch loop wants."""
    provenance = dict(mapped.get('provenance') or {})
    provenance.update({'feed_url': variant.url, 'feed_variant': variant.key,
                       'feed_snapshot': feed_snapshot, 'fetched_at': at, 'run_id': run})
    mapped['provenance'] = provenance
    # The same three facts stay at the top level too, because CAREER-53's
    # own state entries, pool rows and tests read them there.
    mapped['feed_snapshot'] = feed_snapshot
    mapped['fetched_at'] = at
    mapped['run_id'] = run
    return mapped


def check_provenance(mapped):
    """Everything wrong with one posting's source chain, in words.

    Returns a list, empty when the posting is storable. Separate from
    `require_provenance` so a report can count what a run would have
    refused without the run dying on the first one.
    """
    problems = []
    provenance = mapped.get('provenance')
    if not isinstance(provenance, dict):
        return ['no provenance block at all']
    for name in PROVENANCE_FIELDS:
        if not provenance.get(name):
            problems.append(f'provenance.{name} is missing')
    for name in ('provider', 'tenant', 'posting_id', 'url', 'content_hash'):
        if provenance.get(name) and str(mapped.get(name) or '') != str(provenance[name]):
            problems.append(f'provenance.{name} disagrees with the posting itself')
    expected = posting_key(mapped.get('provider'), mapped.get('tenant'), mapped.get('posting_id'))
    if mapped.get('key') != expected:
        problems.append(f'the posting key is {mapped.get("key")!r} and its own source chain '
                        f'says {expected!r}')
    values = mapped.get('values')
    if not isinstance(values, dict) or not values:
        problems.append('no D4 value record: an absent field is an unknown record, not silence')
        return problems
    for dimension, record in sorted(values.items()):
        if not isinstance(record, dict) or [name for name in VALUE_RECORD_FIELDS
                                            if name not in record]:
            problems.append(f'the {dimension} value is not a D4 value record')
    if not any(isinstance(record, dict) and record.get('source') == 'feed'
               for record in values.values()):
        problems.append("no value record carries source='feed', so nothing says the feed "
                        'stated it')
    return problems


def require_provenance(mapped):
    """Raise unless this posting carries its whole source chain."""
    problems = check_provenance(mapped)
    if problems:
        raise ProvenanceError(
            f'{mapped.get("key") or mapped.get("posting_id") or "a posting"} cannot be stored: '
            + '; '.join(problems))
    return mapped


# --- the optional half of the contract, with its defaults ------------------

def variant_carries_text(parsed):
    """Whether a feed variant actually carries posting text.

    True by default: only Personio has a variant that answers 200 with
    every description empty.
    """
    return True


def next_page(variant, parsed, seen):
    """The next page of a paged feed, or None. Only SmartRecruiters pages."""
    return None


def detail_variant(mapped):
    """A second request that fills in a posting's text, or None.

    Only SmartRecruiters needs one: its list endpoint states location,
    employment type and function but no description. The fetcher asks for
    it only for postings the Zurich filter kept, which is what keeps a
    150-tenant sample inside one request a second.
    """
    return None


#: Names an adapter may define; anything here that it does not define
#: falls back to this module's own version above.
OPTIONAL = ('VARIANT_OPTIONS', 'variant_carries_text', 'next_page', 'detail_variant',
            'merge_detail', 'DETAIL_SUFFIX')

REQUIRED_ATTRIBUTES = ('PROVIDER', 'DOC_URL', 'DOC_ACCESSED', 'SNAPSHOT_SUFFIX',
                       'HASHED_FIELDS', 'CDX_PATTERNS', 'TENANT_ID', 'MAPPED_DIMENSIONS')
REQUIRED_CALLABLES = ('feed_variants', 'tenant_from_url', 'parse_feed', 'map_posting',
                      'posting_url')


def feature(adapter, name):
    """One optional contract function, the adapter's own or this
    module's."""
    return getattr(adapter, name, globals()[name])


def check_adapter(adapter):
    """Everything missing from one adapter module, in words.

    Returns a list, empty for a conforming adapter. The suite runs it
    over every registered adapter, which is what makes the contract a
    contract: a provider module that forgets its documentation URL or its
    tenant pattern fails before anything is fetched through it.
    """
    problems = []
    for name in REQUIRED_ATTRIBUTES:
        if getattr(adapter, name, None) in (None, '', (), {}):
            problems.append(f'{name} is missing or empty')
    for name in REQUIRED_CALLABLES:
        if not callable(getattr(adapter, name, None)):
            problems.append(f'{name}() is missing')
    if getattr(adapter, 'SNAPSHOT_SUFFIX', None) not in ('xml', 'json'):
        problems.append("SNAPSHOT_SUFFIX must be 'xml' or 'json'")
    if getattr(adapter, 'detail_variant', None) and not getattr(adapter, 'merge_detail', None):
        problems.append('detail_variant() needs merge_detail() to fold the answer back in')
    accessed = str(getattr(adapter, 'DOC_ACCESSED', ''))
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', accessed):
        problems.append('DOC_ACCESSED must be an ISO date: the day the endpoint documentation '
                        'was read is part of what a stored posting cites')
    for name in getattr(adapter, 'MAPPED_DIMENSIONS', ()) or ():
        dimension = re.sub(r'_(min|max)$', '', name)
        if dimension not in taxonomy.DIMENSIONS:
            problems.append(f'MAPPED_DIMENSIONS names {name!r}, which is not a taxonomy '
                            'dimension')
    return problems


def check_mapped_dimensions(adapter, mapped):
    """Whether a mapped posting states every dimension its adapter claims.

    The other half of the no-silence rule: `MAPPED_DIMENSIONS` is what a
    provider's API can state, and a posting that leaves one of them out
    is a drop rather than an `unknown`. A dimension the API has no field
    for at all is not on the list -- see the Personio docstring on
    `work_model`.
    """
    values = mapped.get('values') or {}
    return [f'{name} has no value record' for name in adapter.MAPPED_DIMENSIONS
            if name not in values]
