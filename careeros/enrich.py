"""Product company aggregation and vault persistence for capability results."""
from collections import Counter
from datetime import date

# Unknown seniority labels do not imply a rank and are excluded.
SENIORITY = ('intern', 'entry', 'junior', 'mid', 'senior', 'lead', 'staff',
             'principal', 'manager', 'director', 'executive')
ALIASES = {'internship': 'intern', 'entry-level': 'entry', 'entry level': 'entry',
           'mid-level': 'mid', 'mid level': 'mid', 'associate': 'junior'}


def _texts(value):
    values = [value] if isinstance(value, str) else value
    return [v.strip() for v in values if isinstance(v, str) and v.strip()] if isinstance(values, list) else []


def enrich_company(jobs):
    """Aggregate postings without mutating inputs or performing any IO.

    Keywords count once per posting, case-insensitively, with lexical ties.
    Missing or malformed legacy values are ignored. Empty bounds/dates are null.
    """
    jobs = list(jobs)
    sectors, locations, ranks, dates = set(), set(), set(), []
    keywords = Counter()
    for job in jobs:
        for key in ('sector', 'sectors', 'industry', 'industries'):
            sectors.update(_texts(job.get(key)))
        locations.update(_texts(job.get('location')))
        keywords.update({word.casefold() for word in _texts(job.get('keywords'))})
        level = job.get('seniority')
        if isinstance(level, str):
            level = level.strip().casefold()
            level = ALIASES.get(level, level)
            if level in SENIORITY:
                ranks.add(SENIORITY.index(level))
        try:
            dates.append(date.fromisoformat(str(job.get('posted_date'))).isoformat())
        except ValueError:
            pass
    return dict(
        sectors=sorted(sectors), locations_seen=sorted(locations),
        remote_friendly=any(job.get('remote_ok') is True for job in jobs),
        seniority_range={'min': SENIORITY[min(ranks)] if ranks else None,
                         'max': SENIORITY[max(ranks)] if ranks else None},
        hiring_activity={'count': len(jobs), 'most_recent_posted_date': max(dates, default=None)},
        top_keywords=sorted(keywords, key=lambda word: (-keywords[word], word))[:10],
    )


def regenerate_company(root, identifier):
    """Merge derived facts through vault helpers; caller holds any write lock.

    Sector aggregation is gated on kind == 'employer' (Section 1's behavior
    matrix): sector/size are not concepts that apply cleanly to an
    institution or an aggregate placeholder. Because block starts from a
    *copy of the existing* enrichment before merging derived values in, a
    company that was an employer at some earlier regeneration (so
    enrichment.sectors got populated) and is later re-kinded away keeps
    showing that stale data forever unless the gate actively deletes both
    the top-level sectors field and the nested enrichment.sectors key,
    rather than merely omitting sectors from what gets newly derived.
    """
    from careeros import vault
    company = vault.load_company(root, identifier)
    if company is None:
        return None
    derived = enrich_company(job for job in vault.list_jobs(root)
                             if job.get('company_id') == identifier)
    previous = company.get('enrichment')
    block = dict(previous) if isinstance(previous, dict) else {}
    updates = {}
    if company.get('kind', 'employer') == 'employer':
        for key, value in derived.items():
            if isinstance(value, dict) and isinstance(block.get(key), dict):
                value = block[key] | value
            block[key] = value
    else:
        for key, value in derived.items():
            if key == 'sectors':
                continue
            if isinstance(value, dict) and isinstance(block.get(key), dict):
                value = block[key] | value
            block[key] = value
        block.pop('sectors', None)
        # Section 1's matrix gives institutions and aggregates no sector and
        # no size, so a company re-kinded away from employer must lose both,
        # not just sectors: clear the top-level sectors list and every size
        # representation (legacy string plus the derived pair), same
        # active-deletion rule the sectors note above describes.
        if company.get('sectors'):
            updates['sectors'] = []
        for key in ('size', 'size_range', 'size_class'):
            if company.get(key) is not None:
                updates[key] = None
    return vault.save_company(root, {'enrichment': block} | updates, identifier)


from org_intake import enrich as org_enrich
from org_intake import fetch as org_fetch
from careeros.llm_client import TIMEOUT as LLM_TIMEOUT, get_llm_client, get_llm_model
from types import SimpleNamespace
import os
from careeros import ingest


def classification_options():
    """Supply gated, lazy product model access and the product deadline."""
    options = dict(deadline=LLM_TIMEOUT, warn=ingest.warn)
    if os.environ.get('BACKFILL_USE_LLM') == '1':
        def create(**kwargs):
            return get_llm_client().chat.completions.create(
                **{**kwargs, 'model': get_llm_model()}, think=False, timeout=LLM_TIMEOUT)
        options.update(llm_client=SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create))), llm_model='configured-at-call')
    return options


def company_events(collector):
    """Keep the existing persisted company accounting shape."""
    return [{('company_id' if k == 'record_id' else k): v
             for k, v in event.items() if k != 'reason'} for event in collector.events]


# The capability appends its own gated LLM fallback signal when
# classification_options() injects llm_client (org_intake.enrich.
# external_sectors, rule 9); the product must not add _llm_signal to the
# signal lists itself, or the LLM runs twice per field per record.
SECTOR_SIGNALS = org_enrich.SECTOR_SIGNALS
SIZE_SIGNALS = org_enrich.SIZE_SIGNALS


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

    fetch=None resolves to the capability's default_fetch at call time
    (not at def time), so tests and callers can inject a replacement
    fetcher through either seam.

    collector is an optional BackfillAccounting instance; passing one
    records a matched/ambiguous/rate-limited/fetch-error/empty/not-attempted
    outcome for every (company, signal) pair the sweep looks at, readable
    afterwards via collector.summary(). This keeps the (plan, scanned)
    return shape exactly as it was -- both server.py's route handler and
    existing tests unpack it positionally -- rather than growing it into a
    3-tuple every caller would have to be updated for."""
    from careeros import vault
    if fetch is None:
        fetch = org_fetch.default_fetch
    vault.backfill_company_kind(root)
    options = classification_options()
    plan = []
    scanned = 0
    for company in vault.list_companies(root):
        if company.get('kind', 'employer') != 'employer':
            continue
        scanned += 1
        changes = {}
        new_sectors, sector_flag = org_enrich.classify_sector(company, signals=sector_signals, fetch=fetch, collector=collector, **options)
        if isinstance(new_sectors, dict):
            changes['identifiers'] = new_sectors.get('identifiers', [])
            new_sectors = new_sectors.get('sectors')
        if new_sectors:
            changes['sectors'] = new_sectors
            changes['review_flags'] = _clear_flags(
                changes.get('review_flags', company.get('review_flags')),
                (org_enrich.FLAG_SECTOR_AMBIGUOUS, org_enrich.FLAG_SECTOR_CONFLICT))
        elif sector_flag:
            changes['review_flags'] = _merge_flags(
                changes.get('review_flags', company.get('review_flags')), sector_flag)
        size_changes, size_flag = org_enrich.classify_size(company, signals=size_signals, fetch=fetch, collector=collector, **options)
        if size_changes and 'identifiers' in size_changes:
            changes['identifiers'] = changes.get('identifiers', []) + size_changes['identifiers']
            size_changes = {k: v for k, v in size_changes.items() if k != 'identifiers'}
        if size_changes:
            changes.update(size_changes)
            changes['review_flags'] = _clear_flags(
                changes.get('review_flags', company.get('review_flags')),
                (org_enrich.FLAG_SIZE_INCONSISTENT,))
        elif size_flag:
            changes['review_flags'] = _merge_flags(
                changes.get('review_flags', company.get('review_flags')), size_flag)
        if changes:
            plan.append((company, changes))
    return plan, scanned


def apply_backfill(root, plan):
    """Fast persistence phase for a plan_backfill result; safe under the
    vault write lock because it only touches the local filesystem."""
    from careeros import vault
    updated = []
    for company, changes in plan:
        from org_intake.identity import add_identifier
        from careeros.org_store import VaultOrganisationStore
        changes = dict(changes)
        identifiers = changes.pop('identifiers', [])
        current = vault.load_company(root, company['id'])
        if current is None:
            continue
        for identifier in identifiers:
            current = add_identifier(VaultOrganisationStore(root), current, identifier['type'],
                                     identifier['value'], identifier['provenance'])
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
    because it has not been migrated yet.

    fetch=None defers to plan_backfill's call-time resolution of the
    capability's default_fetch (see its docstring)."""
    plan, _scanned = plan_backfill(root, sector_signals, size_signals, fetch, collector)
    return apply_backfill(root, plan)
