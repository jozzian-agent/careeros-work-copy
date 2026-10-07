"""New external-fetch pipeline for company sector/size (Section 3).

Distinct from careeros.enrich, which only re-summarizes fields the vault
already has from linked jobs and performs no network IO. Everything in this
module reaches an external host, so every fetch is routed through
intake.check_url/fetch_url's redirect-free, public-IP-only, bounded-size
guard before any response body is read.

This pipeline only ever runs from an explicit, owner-triggered backfill
action (see backfill()); it never runs automatically.
"""
import ipaddress
import json
import re
from urllib.parse import quote, urlsplit

from careeros import intake, sectors, vault


def _safe_fetch(url, fetch):
    """Reject a literal private/loopback/link-local host before ever calling
    the injected fetcher, without a DNS lookup: this pipeline fetches
    company websites and other owner- or signal-derived URLs, so a literal
    unsafe IP address in the host position must never reach fetch, the same
    guard intake.check_url applies to posting fetches."""
    try:
        intake.check_url_format(url)
        host = urlsplit(url).hostname
        try:
            literal_ip = ipaddress.ip_address(host)
        except ValueError:
            literal_ip = None
        if literal_ip is not None and intake.is_unsafe_ip(literal_ip):
            return None
        return fetch(url)
    except Exception:
        return None


def fetch_company_jsonld(website, fetch=None):
    """Scan a company's own website for JSON-LD industry/employee fields."""
    fetch = fetch or intake.fetch_url
    if not website:
        return {}
    html = _safe_fetch(website, fetch)
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


def _resolve_entity_label(entity_id, fetch):
    """P452 (industry) resolves to another Wikidata item id, e.g. Q880371
    for "software industry," not a free-text string the keyword matcher can
    read. A second lookup fetches that item's own English label so the
    matcher receives readable text instead of an opaque id."""
    entity_url = f'https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json'
    payload = _safe_fetch(entity_url, fetch)
    if not payload:
        return None
    try:
        entity = json.loads(payload).get('entities', {}).get(entity_id, {})
    except (ValueError, TypeError):
        return None
    return entity.get('labels', {}).get('en', {}).get('value')


def fetch_wikidata(name, fetch=None):
    """Query Wikidata for P452 (industry) and the most recently dated P1128
    (employees) statement for the best name match."""
    fetch = fetch or intake.fetch_url
    if not name:
        return {}
    try:
        search_url = ('https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json'
                      f'&language=en&type=item&search={quote(name)}')
        payload = _safe_fetch(search_url, fetch)
        if not payload:
            return {}
        entity_id = (json.loads(payload).get('search') or [{}])[0].get('id')
        if not entity_id:
            return {}
        entity_url = f'https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json'
        payload = _safe_fetch(entity_url, fetch)
        if not payload:
            return {}
        claims = json.loads(payload).get('entities', {}).get(entity_id, {}).get('claims', {})
        industry = None
        industry_claims = claims.get('P452')
        if industry_claims:
            value = _claim_value(industry_claims[0])
            industry_entity = value.get('id') if isinstance(value, dict) else None
            if industry_entity:
                industry = _resolve_entity_label(industry_entity, fetch)
        employees = _most_recent_dated_quantity(claims.get('P1128'))
        return {'industry': industry, 'employee_count': employees}
    except Exception:
        return {}


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
# optional 'industry' (free text) and 'employee_count' (raw int or None).
def _jsonld_signal(company, fetch=None):
    return fetch_company_jsonld(company.get('website'), fetch)


def _wikidata_signal(company, fetch=None):
    return fetch_wikidata(company.get('name'), fetch)


def _osm_signal(company, fetch=None):
    return fetch_osm(company.get('name'), fetch)


SECTOR_SIGNALS = (_jsonld_signal, _wikidata_signal, _osm_signal)
SIZE_SIGNALS = (_jsonld_signal, _wikidata_signal)

# Flag vocabulary for decisions 20-21 and the partially-populated-pair rule.
FLAG_SECTOR_AMBIGUOUS = 'sector-ambiguous'
FLAG_SECTOR_CONFLICT = 'sector-source-conflict'
FLAG_SIZE_INCONSISTENT = 'size-inconsistent'


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

def external_sectors(company, signals=SECTOR_SIGNALS, fetch=None):
    """Independent confident matches from distinct sources. Returns a tuple
    (codes, flag) where flag names the review reason when the result was
    refused: FLAG_SECTOR_CONFLICT when two or more distinct confident
    matches arrived without distinct-activity evidence (decisions 20-21),
    FLAG_SECTOR_AMBIGUOUS when a signal matched several sections at once
    (decision 20), or None when there was simply no usable signal."""
    found, ambiguous = set(), False
    for signal in signals:
        industry = signal(company, fetch).get('industry')
        if not industry:
            continue
        matched = sectors.match_sectors(industry)
        if not matched:
            if sectors.all_matched_sections(industry):
                ambiguous = True  # signal matched several sections: refused
            continue
        found.add(tuple(matched))
    if len(found) == 1:
        return sorted(found.pop()), None
    if found:
        # Two or more confident classifications of possibly the same
        # activity: confidence alone never resolves it, no source priority
        # exists, so refuse and flag (decisions 20-21).
        return None, FLAG_SECTOR_CONFLICT
    return None, FLAG_SECTOR_AMBIGUOUS if ambiguous else None


def sectors_cascade(company, signals=SECTOR_SIGNALS, fetch=None):
    """sectors is eligible whenever it is empty. Promotion from job
    aggregation is tried first (no network); the external-fetch pipeline is
    the fallback. Returns (codes_or_None, review_flag_or_None): an ambiguous
    promotion refusal (multiple matches without distinct-activity evidence)
    is itself a review event, so it stops the cascade with a flag rather
    than falling through to external fetch and masking the conflict."""
    if company.get('sectors'):
        return None, None
    promoted = promote_aggregated_sectors(company)
    if promoted:
        return promoted, None
    if promoted is None:
        return None, FLAG_SECTOR_CONFLICT
    return external_sectors(company, signals, fetch)


def size_cascade(company, signals=SIZE_SIGNALS, fetch=None):
    """size_range/size_class is eligible whenever either is empty. There is
    no zero-network tier for size, so this goes straight to external fetch,
    and obeys the partially-populated-pair consistency rule: a freshly
    fetched count that contradicts an already-populated field fills nothing
    and raises a review flag, since silently leaving a half-filled pair with
    no pending indication violates Section 3."""
    size_range, size_class = company.get('size_range'), company.get('size_class')
    if size_range and size_class:
        return None, None
    count = None
    for signal in signals:
        count = signal(company, fetch).get('employee_count')
        if count:
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

def plan_backfill(root, sector_signals=SECTOR_SIGNALS, size_signals=SIZE_SIGNALS, fetch=None):
    """Read-only planning phase: run both cascades over every employer and
    collect (company, changes) pairs. All network I/O happens here, so the
    caller must NOT hold the vault write lock while running this (a cold
    pass over many companies can take minutes; holding the lock that long
    deadlocks every other write in the app)."""
    vault.backfill_company_kind(root)
    plan = []
    scanned = 0
    for company in vault.list_companies(root):
        if company.get('kind', 'employer') != 'employer':
            continue
        scanned += 1
        changes = {}
        new_sectors, sector_flag = sectors_cascade(company, sector_signals, fetch)
        if new_sectors:
            changes['sectors'] = new_sectors
            changes['review_flags'] = _clear_flags(
                changes.get('review_flags', company.get('review_flags')),
                (FLAG_SECTOR_AMBIGUOUS, FLAG_SECTOR_CONFLICT))
        elif sector_flag:
            changes['review_flags'] = _merge_flags(
                changes.get('review_flags', company.get('review_flags')), sector_flag)
        size_changes, size_flag = size_cascade(company, size_signals, fetch)
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


def backfill(root, sector_signals=SECTOR_SIGNALS, size_signals=SIZE_SIGNALS, fetch=None):
    """Explicit, owner-triggered backfill (decision 27). Scoped to
    kind == 'employer'; sectors and size run as independent per-field
    cascades over the same company list, never as a single combined pass.
    Every ambiguity refusal, source conflict, and size inconsistency the
    cascades surface is persisted on review_flags, and a flag is removed
    once its field resolves. Runs the one-time kind backfill first, so a
    company record that predates the kind field is never skipped merely
    because it has not been migrated yet."""
    plan, _scanned = plan_backfill(root, sector_signals, size_signals, fetch)
    return apply_backfill(root, plan)
