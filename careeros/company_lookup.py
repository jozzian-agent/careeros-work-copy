"""New external-fetch pipeline for company sector/size (Section 3).

Distinct from careeros.enrich, which only re-summarizes fields the vault
already has from linked jobs and performs no network IO. Everything in this
module reaches an external host, so every fetch is routed through
intake.check_url/fetch_url's redirect-free, public-IP-only, bounded-size
guard before any response body is read.

This pipeline only ever runs from an explicit, owner-triggered backfill
action (see backfill()); it never runs automatically.
"""
import email.utils
import ipaddress
import json
import math
import re
import threading
import time
import urllib.error
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

from careeros import intake, sectors, vault


def _rejects_unsafe_target(url):
    """Shared guard for _safe_fetch and the Wikidata retry path: a literal
    private/loopback/link-local host in the URL must never reach a fetcher,
    without a DNS lookup, the same guard intake.check_url applies to posting
    fetches. Also true for a structurally invalid URL."""
    try:
        intake.check_url_format(url)
    except Exception:
        return True
    host = urlsplit(url).hostname
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return intake.is_unsafe_ip(literal_ip)


def _safe_fetch(url, fetch):
    if _rejects_unsafe_target(url):
        return None
    try:
        return fetch(url)
    except Exception:
        return None


def _safe_fetch_status(url, fetch):
    """Like _safe_fetch, but distinguishes an exception raised during the
    fetch itself (status 'error', e.g. an HTTP 500 from the company's own
    site) from a safety-rejected or merely empty response (status 'ok', value
    None) -- needed by signal wrappers that must report a fetch failure
    differently from "fetched cleanly, nothing useful there." _safe_fetch
    itself (used by OSM, out of scope here) is untouched and keeps returning
    a bare value with no status distinction."""
    if _rejects_unsafe_target(url):
        return None, 'ok'
    try:
        return fetch(url), 'ok'
    except Exception:
        return None, 'error'


# --- Wikidata retry/backoff + request pacing --------------------------------
# Wikidata rate-limits (HTTP 429) mid-sweep when a backfill runs over many
# companies. A bounded, exponential-backoff retry (honoring Retry-After when
# the server sends one) survives a transient limit; pacing successive
# Wikidata calls a little apart keeps a long sweep from triggering the limit
# in the first place. Only Wikidata gets this treatment: it is the only
# signal source observed to rate-limit (see BUILD_NOTES.md).
WIKIDATA_MAX_RETRIES = 3
WIKIDATA_BACKOFF_SECONDS = 1
WIKIDATA_MIN_INTERVAL = 0.1
# A Retry-After value is advisory input from an external server: bound how
# long a single retry will ever wait on it, so a misbehaving or malicious
# response can't stall a sweep for an arbitrary amount of time.
RETRY_AFTER_MAX_SECONDS = 30

_last_wikidata_call = [float('-inf')]
# Flask serves requests on multiple threads; a concurrent backfill sweep (or
# two sweeps overlapping) would otherwise race on the read-sleep-update of
# _last_wikidata_call. This is pacing-only -- a dedicated lock, never the
# vault write lock, which this module's network phase must not hold (see
# plan_backfill).
_wikidata_pace_lock = threading.Lock()


def _wikidata_pace():
    # Always the real clock, deliberately not the injectable `sleep` that
    # fetch_wikidata's backoff uses: pacing is a courtesy to the real
    # Wikidata API between distinct calls, not a retry a test needs to fake
    # out to assert against.
    with _wikidata_pace_lock:
        now = time.monotonic()
        elapsed = now - _last_wikidata_call[0]
        if elapsed < WIKIDATA_MIN_INTERVAL:
            time.sleep(WIKIDATA_MIN_INTERVAL - elapsed)
        _last_wikidata_call[0] = time.monotonic()


def _retry_after_http_date(value):
    """Parse the HTTP-date form of Retry-After (RFC 7231), returning seconds
    from now, clamped at zero for a date already in the past. None when the
    value does not parse as an HTTP date at all."""
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max((when - datetime.now(timezone.utc)).total_seconds(), 0.0)


def _retry_after_seconds(error):
    """Retry-After may be sent as either delay-seconds or an HTTP-date
    (RFC 7231 7.1.3); parse both. A garbage value that is neither returns
    None, so the caller falls back to its own exponential delay instead of
    not sleeping at all. Any value is clamped to RETRY_AFTER_MAX_SECONDS, and
    a negative/zero result is floored at zero, so a malformed or hostile
    header can never stall a retry far beyond what the backoff itself would."""
    headers = getattr(error, 'headers', None)
    value = headers.get('Retry-After') if headers else None
    if value is None:
        return None
    value = value.strip()
    try:
        seconds = float(value)
        if not math.isfinite(seconds):
            # float() accepts 'NaN'/'inf'; treat as garbage and fall back to
            # the caller's exponential delay rather than clamping to a
            # degenerate zero/infinite wait.
            return None
    except (TypeError, ValueError):
        seconds = _retry_after_http_date(value)
        if seconds is None:
            return None
    return max(0.0, min(seconds, RETRY_AFTER_MAX_SECONDS))


def _wikidata_get(url, fetch, sleep):
    """One safety-checked Wikidata fetch with bounded exponential backoff on
    HTTP 429. Returns (payload_or_None, status), status one of 'ok', 'error',
    'rate_limited' -- the latter only once every retry is exhausted, so a
    429 that succeeds on retry is never reported as rate-limited."""
    if _rejects_unsafe_target(url):
        return None, 'error'
    delay = WIKIDATA_BACKOFF_SECONDS
    for attempt in range(WIKIDATA_MAX_RETRIES + 1):
        _wikidata_pace()
        try:
            return fetch(url), 'ok'
        except urllib.error.HTTPError as error:
            if error.code != 429:
                return None, 'error'
            if attempt == WIKIDATA_MAX_RETRIES:
                return None, 'rate_limited'
            retry_after = _retry_after_seconds(error)
            sleep(retry_after if retry_after is not None else delay)
            delay *= 2
        except Exception:
            return None, 'error'
    return None, 'rate_limited'


def fetch_company_jsonld(website, fetch=None):
    """Scan a company's own website for JSON-LD industry/employee fields.

    A single page fetch backs both industry and employee_count here (unlike
    Wikidata, which hits industry and size via partially independent calls),
    so a fetch failure (e.g. HTTP 500) is reported via 'industry_status' and
    'size_status' together -- it is a genuine, total failure for both
    fields, not a partial one. A safety-rejected destination or a page that
    simply has no JSON-LD is reported as empty, not a failure."""
    fetch = fetch or intake.fetch_url
    if not website:
        return {}
    html, status = _safe_fetch_status(website, fetch)
    if status != 'ok':
        return {'industry_status': status, 'size_status': status}
    if not html:
        return {}
    parser = intake.Posting()
    parser.feed(html)
    industry, employees = None, None
    for block in parser.json_blocks:
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            if industry is None and isinstance(node.get('industry'), str):
                industry = node['industry']
            if employees is None:
                count = node.get('numberOfEmployees')
                if isinstance(count, dict):
                    count = count.get('value')
                if count is not None:
                    employees = count
    return {'industry': industry, 'employee_count': sectors.resolve_employee_count(employees)}


def _claim_value(claim):
    return claim.get('mainsnak', {}).get('datavalue', {}).get('value')


def _most_recent_dated_quantity(claims):
    """Prefer the most recently dated P1128 statement; refuse undated ones
    rather than treating them as current, per the owner's decision."""
    dated = []
    for claim in claims or []:
        qualifiers = claim.get('qualifiers', {})
        point_in_time = qualifiers.get('P585')
        if not point_in_time:
            continue
        when = _claim_value({'mainsnak': point_in_time[0]}).get('time') if isinstance(
            _claim_value({'mainsnak': point_in_time[0]}), dict) else None
        amount = _claim_value(claim)
        amount = amount.get('amount') if isinstance(amount, dict) else None
        if when and amount is not None:
            dated.append((when, amount))
    if not dated:
        return None
    dated.sort(key=lambda pair: pair[0])
    return sectors.resolve_employee_count(str(dated[-1][1]).lstrip('+'))


def _resolve_entity_label(entity_id, fetch, sleep):
    """P452 (industry) resolves to another Wikidata item id, e.g. Q880371
    for "software industry," not a free-text string the keyword matcher can
    read. A second lookup fetches that item's own English label so the
    matcher receives readable text instead of an opaque id. Returns
    (label_or_None, status): a 429 here must surface the same as one on the
    primary lookup, not get silently swallowed."""
    entity_url = f'https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json'
    payload, status = _wikidata_get(entity_url, fetch, sleep)
    if status != 'ok':
        return None, status
    if not payload:
        return None, 'ok'
    try:
        entity = json.loads(payload).get('entities', {}).get(entity_id, {})
    except (ValueError, TypeError):
        return None, 'error'
    return entity.get('labels', {}).get('en', {}).get('value'), 'ok'


def fetch_wikidata(name, fetch=None, sleep=None):
    """Query Wikidata for P452 (industry) and the most recently dated P1128
    (employees) statement for the best name match.

    Industry and employee_count are reported via independent 'industry_status'
    and 'size_status' keys whenever something other than a clean fetch
    happened for that field ('rate_limited' after retries are exhausted,
    'error' for any other fetch/parse failure, 'not_attempted' when there was
    no name to query). The two underlying lookups that fetch the search
    result and the entity's own claims (including P1128) are shared by both
    fields, so a failure there sets both statuses identically -- genuinely
    nothing was fetched for either field. Only the industry *label*
    resolution (P452's id -> English text) is a separate, later call, so a
    failure there sets 'industry_status' alone: employee_count was already
    read from the claims payload that succeeded, and must not be discarded
    just because the unrelated label lookup failed. Both status keys are
    omitted on a clean fetch (empty or populated), so existing exact-equality
    callers of this function for the success path are unaffected."""
    fetch = fetch or intake.fetch_url
    sleep = sleep or time.sleep
    if not name:
        return {'industry': None, 'employee_count': None,
                'industry_status': 'not_attempted', 'size_status': 'not_attempted'}
    try:
        search_url = ('https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json'
                      f'&language=en&type=item&search={quote(name)}')
        payload, status = _wikidata_get(search_url, fetch, sleep)
        if status != 'ok':
            return {'industry': None, 'employee_count': None,
                    'industry_status': status, 'size_status': status}
        if not payload:
            return {'industry': None, 'employee_count': None}
        entity_id = (json.loads(payload).get('search') or [{}])[0].get('id')
        if not entity_id:
            return {'industry': None, 'employee_count': None}
        entity_url = f'https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json'
        payload, status = _wikidata_get(entity_url, fetch, sleep)
        if status != 'ok':
            return {'industry': None, 'employee_count': None,
                    'industry_status': status, 'size_status': status}
        if not payload:
            return {'industry': None, 'employee_count': None}
        claims = json.loads(payload).get('entities', {}).get(entity_id, {}).get('claims', {})
        industry, industry_status = None, 'ok'
        industry_claims = claims.get('P452')
        if industry_claims:
            value = _claim_value(industry_claims[0])
            industry_entity = value.get('id') if isinstance(value, dict) else None
            if industry_entity:
                industry, industry_status = _resolve_entity_label(industry_entity, fetch, sleep)
        employees = _most_recent_dated_quantity(claims.get('P1128'))
        result = {'industry': industry, 'employee_count': employees}
        if industry_status != 'ok':
            result['industry_status'] = industry_status
        return result
    except Exception:
        return {'industry': None, 'employee_count': None,
                'industry_status': 'error', 'size_status': 'error'}


def fetch_osm(name, fetch=None):
    """Lowest-confidence source: an office=*/shop=* tag has no employee-count
    equivalent at all, so this only ever contributes a sector hint. Matches
    a node carrying either tag key, not only office, so a shop-only result
    (no office tag at all) is not silently excluded."""
    fetch = fetch or intake.fetch_url
    if not name:
        return {}
    try:
        query = ('[out:json];node["name"~"' + re.escape(name) + '",i]'
                 '[~"^(office|shop)$"~"."];out 1;')
        url = 'https://overpass-api.de/api/interpreter?data=' + quote(query)
        payload = _safe_fetch(url, fetch)
        if not payload:
            return {}
        elements = json.loads(payload).get('elements') or [{}]
        tags = elements[0].get('tags', {})
        return {'industry': tags.get('office') or tags.get('shop'), 'employee_count': None}
    except Exception:
        return {}


# Each signal function takes the company record and returns a dict with
# optional 'industry' (free text) and 'employee_count' (raw int or None),
# plus optional 'industry_status'/'size_status' keys ('rate_limited'/'error'/
# 'not_attempted') when that field's fetch did not complete cleanly. The two
# are independent so a partial failure (e.g. Wikidata's industry-label lookup
# fails but its employee_count claim was already read) never discards the
# field that did succeed. The precondition check (is there even a
# website/name to query) happens here, in the wrapper, rather than inside
# fetch_company_jsonld/fetch_wikidata/fetch_osm, so those functions' existing
# return shapes for direct callers/tests are untouched.
def _jsonld_signal(company, fetch=None):
    if not company.get('website'):
        return {'industry_status': 'not_attempted', 'size_status': 'not_attempted'}
    return fetch_company_jsonld(company.get('website'), fetch)


def _wikidata_signal(company, fetch=None):
    if not company.get('name'):
        return {'industry_status': 'not_attempted', 'size_status': 'not_attempted'}
    return fetch_wikidata(company.get('name'), fetch)


def _osm_signal(company, fetch=None):
    if not company.get('name'):
        return {'industry_status': 'not_attempted', 'size_status': 'not_attempted'}
    return fetch_osm(company.get('name'), fetch)


SECTOR_SIGNALS = (_jsonld_signal, _wikidata_signal, _osm_signal)
SIZE_SIGNALS = (_jsonld_signal, _wikidata_signal)

# Human-readable names for accounting output; any signal function not listed
# here (e.g. a test double) falls back to its __name__. promote_aggregated_
# sectors is listed here too: the zero-network promotion tier also produces
# an accounting event (see sectors_cascade), so it needs a readable name just
# like the external-fetch signals do.
_SIGNAL_NAMES = {_jsonld_signal: 'jsonld', _wikidata_signal: 'wikidata', _osm_signal: 'osm'}

# Flag vocabulary for decisions 20-21 and the partially-populated-pair rule.
FLAG_SECTOR_AMBIGUOUS = 'sector-ambiguous'
FLAG_SECTOR_CONFLICT = 'sector-source-conflict'
FLAG_SIZE_INCONSISTENT = 'size-inconsistent'


# --- Per-signal outcome accounting (JOZ-260) --------------------------------
# A backfill sweep over many companies was silently swallowing the
# difference between "no usable data" and "Wikidata rate-limited us" or "the
# fetch errored." BackfillAccounting is an optional collector: passing one
# to plan_backfill (or the cascades directly) records one outcome per
# (company, signal, field) seen; passing none (the default everywhere)
# costs nothing and changes no existing behavior. This was chosen over
# extending plan_backfill's own (plan, scanned) return shape because that
# tuple is unpacked positionally by the server route and by existing tests;
# an optional, additive parameter needs no changes there at all.
_STATUS_OUTCOMES = {'rate_limited': 'rate-limited', 'error': 'fetch-error', 'not_attempted': 'not-attempted'}


class BackfillAccounting:
    OUTCOMES = ('matched', 'ambiguous', 'rate-limited', 'fetch-error', 'empty', 'not-attempted')

    def __init__(self):
        self.counts = {outcome: 0 for outcome in self.OUTCOMES}
        self.events = []

    def record(self, company_id, signal, field, outcome):
        name = _SIGNAL_NAMES.get(signal, getattr(signal, '__name__', 'signal'))
        self.counts[outcome] += 1
        self.events.append({'company_id': company_id, 'signal': name, 'field': field, 'outcome': outcome})

    def summary(self):
        return dict(self.counts)


def _record_outcome(collector, company, signal, field, outcome):
    if collector is not None:
        collector.record(company.get('id'), signal, field, outcome)


def promote_aggregated_sectors(company):
    """Zero-network tier: run enrich.py's already-aggregated raw industry
    strings through the keyword matcher. Confident matches promote; the rest
    drop, since they were never validated ISIC codes to begin with.

    Decision 20: promotion alone never yields a multi-sector claim. A single
    confident match promotes. Two or more distinct matches are only a
    genuine multi-sector result when the underlying raw industry strings
    provide independent evidence of materially different activities, which
    in practice means the confident matches come from distinct raw strings
    that themselves describe distinct activities rather than one string
    repeated under different labels; anything weaker is refused as an
    unresolved conflict and the caller flags it for owner review."""
    raw = [text for text in company.get('enrichment', {}).get('sectors', []) if isinstance(text, str)]
    matches = {}
    for text in raw:
        for code in sectors.match_sectors(text):
            matches.setdefault(code, set()).add(text.strip().casefold())
    if len(matches) <= 1:
        return sorted(matches)
    # Distinct activity evidence: every pair of matched codes must trace back
    # to raw strings that do not share any word longer than three characters,
    # so "Software" plus "Software development" is not evidence of two lines
    # of business, while "Software" plus "Retail banking" is.
    codes = sorted(matches)
    for i, first in enumerate(codes):
        for second in codes[i + 1:]:
            if not any(_distinct_activities(a, b)
                       for a in matches[first] for b in matches[second]):
                return None
    return codes

def _distinct_activities(first, second):
    words_a = {w for w in re.split(r'[^a-z0-9]+', first) if len(w) > 3}
    words_b = {w for w in re.split(r'[^a-z0-9]+', second) if len(w) > 3}
    return bool(words_a) and bool(words_b) and not (words_a & words_b)


_SIGNAL_NAMES[promote_aggregated_sectors] = 'promotion'


def _record_not_attempted(collector, company, signals, field):
    for signal in signals:
        _record_outcome(collector, company, signal, field, 'not-attempted')


def external_sectors(company, signals=SECTOR_SIGNALS, fetch=None, collector=None):
    """Independent confident matches from distinct sources. Returns a tuple
    (codes, flag) where flag names the review reason when the result was
    refused: FLAG_SECTOR_CONFLICT when two or more distinct confident
    matches arrived without distinct-activity evidence (decisions 20-21),
    FLAG_SECTOR_AMBIGUOUS when a signal matched several sections at once
    (decision 20), or None when there was simply no usable signal.

    collector, when given, records one outcome per signal: matched/ambiguous
    (from keyword-matching the returned industry text), rate-limited/
    fetch-error/not-attempted (from the signal's own 'industry_status'), or
    empty (fetched cleanly but no usable industry text came back)."""
    found, ambiguous = set(), False
    for signal in signals:
        result = signal(company, fetch)
        status = result.get('industry_status', 'ok')
        if status in _STATUS_OUTCOMES:
            _record_outcome(collector, company, signal, 'sectors', _STATUS_OUTCOMES[status])
            continue
        industry = result.get('industry')
        if not industry:
            _record_outcome(collector, company, signal, 'sectors', 'empty')
            continue
        matched = sectors.match_sectors(industry)
        if not matched:
            if sectors.all_matched_sections(industry):
                ambiguous = True  # signal matched several sections: refused
                _record_outcome(collector, company, signal, 'sectors', 'ambiguous')
            else:
                _record_outcome(collector, company, signal, 'sectors', 'empty')
            continue
        found.add(tuple(matched))
        _record_outcome(collector, company, signal, 'sectors', 'matched')
    if len(found) == 1:
        return sorted(found.pop()), None
    if found:
        # Two or more confident classifications of possibly the same
        # activity: confidence alone never resolves it, no source priority
        # exists, so refuse and flag (decisions 20-21).
        return None, FLAG_SECTOR_CONFLICT
    return None, FLAG_SECTOR_AMBIGUOUS if ambiguous else None


def sectors_cascade(company, signals=SECTOR_SIGNALS, fetch=None, collector=None):
    """sectors is eligible whenever it is empty. Promotion from job
    aggregation is tried first (no network); the external-fetch pipeline is
    the fallback. Returns (codes_or_None, review_flag_or_None): an ambiguous
    promotion refusal (multiple matches without distinct-activity evidence)
    is itself a review event, so it stops the cascade with a flag rather
    than falling through to external fetch and masking the conflict.

    Every early return here -- the field already populated, or promotion
    settling the result either way -- still produces one accounting event per
    (signal, 'sectors') pair the cascade did NOT invoke: 'not-attempted' for
    every external signal skipped, plus a 'matched'/'ambiguous' event for the
    zero-network promotion step itself, so collector.summary() covers every
    pair the sweep considers rather than only the ones that happened to reach
    a network call."""
    if company.get('sectors'):
        _record_not_attempted(collector, company, (promote_aggregated_sectors,) + tuple(signals), 'sectors')
        return None, None
    promoted = promote_aggregated_sectors(company)
    if promoted:
        _record_outcome(collector, company, promote_aggregated_sectors, 'sectors', 'matched')
        _record_not_attempted(collector, company, signals, 'sectors')
        return promoted, None
    if promoted is None:
        _record_outcome(collector, company, promote_aggregated_sectors, 'sectors', 'ambiguous')
        _record_not_attempted(collector, company, signals, 'sectors')
        return None, FLAG_SECTOR_CONFLICT
    # promoted == []: promotion ran but had nothing to offer (no aggregated
    # raw industry data). Account it as 'empty' so the promotion step itself
    # is never missing from collector coverage when the sweep falls through
    # to the external signals.
    _record_outcome(collector, company, promote_aggregated_sectors, 'sectors', 'empty')
    return external_sectors(company, signals, fetch, collector)


def size_cascade(company, signals=SIZE_SIGNALS, fetch=None, collector=None):
    """size_range/size_class is eligible whenever either is empty. There is
    no zero-network tier for size, so this goes straight to external fetch,
    and obeys the partially-populated-pair consistency rule: a freshly
    fetched count that contradicts an already-populated field fills nothing
    and raises a review flag, since silently leaving a half-filled pair with
    no pending indication violates Section 3.

    Both the already-populated-pair early return and the loop's break on the
    first successful count record 'not-attempted' for every ('size') signal
    that was skipped as a result, so collector.summary() covers every signal
    the sweep considers for this company, not only the ones actually
    invoked."""
    size_range, size_class = company.get('size_range'), company.get('size_class')
    signals = tuple(signals)
    if size_range and size_class:
        _record_not_attempted(collector, company, signals, 'size')
        return None, None
    count = None
    for index, signal in enumerate(signals):
        result = signal(company, fetch)
        status = result.get('size_status', 'ok')
        if status in _STATUS_OUTCOMES:
            _record_outcome(collector, company, signal, 'size', _STATUS_OUTCOMES[status])
            continue
        count = result.get('employee_count')
        _record_outcome(collector, company, signal, 'size', 'matched' if count else 'empty')
        if count:
            _record_not_attempted(collector, company, signals[index + 1:], 'size')
            break
    updates = sectors.fill_size_updates(count, size_range, size_class)
    if updates:
        return updates, None
    if count:
        # A count arrived but nothing was written: it contradicted the
        # already-populated field (or failed validation). Flag for review.
        return None, FLAG_SIZE_INCONSISTENT
    return None, None


def _merge_flags(existing, new_flag):
    flags = [f for f in existing or [] if isinstance(f, str)]
    if new_flag and new_flag not in flags:
        flags.append(new_flag)
    return flags

def _clear_flags(existing, resolved):
    return [f for f in existing or [] if isinstance(f, str) and f not in resolved]

def plan_backfill(root, sector_signals=SECTOR_SIGNALS, size_signals=SIZE_SIGNALS, fetch=None, collector=None):
    """Read-only planning phase: run both cascades over every employer and
    collect (company, changes) pairs. All network I/O happens here, so the
    caller must NOT hold the vault write lock while running this (a cold
    pass over many companies can take minutes; holding the lock that long
    deadlocks every other write in the app).

    collector is an optional BackfillAccounting instance; passing one
    records a matched/ambiguous/rate-limited/fetch-error/empty/not-attempted
    outcome for every (company, signal) pair the sweep looks at, readable
    afterwards via collector.summary(). This keeps the (plan, scanned)
    return shape exactly as it was -- both server.py's route handler and
    existing tests unpack it positionally -- rather than growing it into a
    3-tuple every caller would have to be updated for."""
    vault.backfill_company_kind(root)
    plan = []
    scanned = 0
    for company in vault.list_companies(root):
        if company.get('kind', 'employer') != 'employer':
            continue
        scanned += 1
        changes = {}
        new_sectors, sector_flag = sectors_cascade(company, sector_signals, fetch, collector)
        if new_sectors:
            changes['sectors'] = new_sectors
            changes['review_flags'] = _clear_flags(
                changes.get('review_flags', company.get('review_flags')),
                (FLAG_SECTOR_AMBIGUOUS, FLAG_SECTOR_CONFLICT))
        elif sector_flag:
            changes['review_flags'] = _merge_flags(
                changes.get('review_flags', company.get('review_flags')), sector_flag)
        size_changes, size_flag = size_cascade(company, size_signals, fetch, collector)
        if size_changes:
            changes.update(size_changes)
            changes['review_flags'] = _clear_flags(
                changes.get('review_flags', company.get('review_flags')),
                (FLAG_SIZE_INCONSISTENT,))
        elif size_flag:
            changes['review_flags'] = _merge_flags(
                changes.get('review_flags', company.get('review_flags')), size_flag)
        if changes:
            plan.append((company, changes))
    return plan, scanned


def apply_backfill(root, plan):
    """Fast persistence phase for a plan_backfill result; safe under the
    vault write lock because it only touches the local filesystem."""
    updated = []
    for company, changes in plan:
        vault.save_company(root, changes, company['id'])
        updated.append(company['id'])
    return updated


def backfill(root, sector_signals=SECTOR_SIGNALS, size_signals=SIZE_SIGNALS, fetch=None, collector=None):
    """Explicit, owner-triggered backfill (decision 27). Scoped to
    kind == 'employer'; sectors and size run as independent per-field
    cascades over the same company list, never as a single combined pass.
    Every ambiguity refusal, source conflict, and size inconsistency the
    cascades surface is persisted on review_flags, and a flag is removed
    once its field resolves. Runs the one-time kind backfill first, so a
    company record that predates the kind field is never skipped merely
    because it has not been migrated yet."""
    plan, _scanned = plan_backfill(root, sector_signals, size_signals, fetch, collector)
    return apply_backfill(root, plan)
