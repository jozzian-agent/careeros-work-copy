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


#: The size evidence a company's own postings carry, and the record of
#: which posting carried it. Named here because the Section 1 field-group
#: matrix keeps size away from non-employer kinds, so `regenerate_company`
#: has to remove this pair for them exactly like it removes `sectors`.
SIZE_EVIDENCE_KEYS = ('employee_count', 'employee_count_evidence')


def _posting_headcount(jobs):
    """The employee count the company's own postings state, as evidence
    for `size_class` (owner decision 2026-10-16), plus the record of which
    posting stated it and when.

    A posting's headcount used to be read once, at intake, and then
    nothing: the job kept the raw `employee_count` it was extracted into,
    and no company ever saw it again. The capability's zero-network
    promotion tier (`org_intake.enrich.promote_aggregated_size`) reads
    exactly `enrichment['employee_count']`, so aggregating it here is what
    turns one posting's number into standing evidence that any later
    cascade run can derive a class from -- the same route the aggregated
    sectors already take. Only the class is ever derived from it; the
    retired numeric scales (`size_range`, the legacy `size` string) stay
    unwritten, which is what the 2026-10-15 decision settled.

    Which count, when several postings state different ones: the one on
    the most recently posted job, and failing any dated job, the first
    posting that states a count at all. That is the rule
    [enrichment evidence](../docs/decisions/enrichment-evidence.md)
    already settled for Wikidata statements ("prefer the latest usable
    date on a non-deprecated statement; otherwise use the first"), and a
    posting's date is the same kind of signal: the newer number is the one
    more likely to still be true. A count the record cannot read as a
    plausible positive headcount is absent evidence, not a zero.
    """
    stated = []
    for job in jobs:
        count = job.get('employee_count')
        if type(count) is not int or count < 1:
            continue
        try:
            posted = date.fromisoformat(str(job.get('posted_date'))).isoformat()
        except ValueError:
            posted = None
        stated.append({'count': count, 'job_id': job.get('id'), 'posted_date': posted})
    if not stated:
        return {'employee_count': None, 'employee_count_evidence': None}
    dated = [entry for entry in stated if entry['posted_date']]
    # max() keeps the first of equal dates, so two postings sharing the
    # newest date resolve by vault order rather than arbitrarily.
    best = max(dated, key=lambda entry: entry['posted_date']) if dated else stated[0]
    return {'employee_count': best['count'], 'employee_count_evidence': dict(best)}


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
        **_posting_headcount(jobs),
    )


def _shared_owners(root):
    """The owners whose records a shared record may be built from, or
    None when ownership does not apply to this vault at all.

    None means there is not one stored account, which is a pre-M1 vault
    or a test fixture: there is no tester in it to protect, so everything
    in it may write. Otherwise it is the ids of the admins, and an
    ownerless record may write alongside them (see
    `may_write_shared_company`, the one caller -- the derived-data rule
    needs no account list at all).
    """
    from careeros import users

    accounts = users.list_users(root)
    return None if not accounts else {user['id'] for user in accounts
                                      if users.is_admin(user)}


def contributes_to_shared(root, record):
    """Whether this one record's facts may be DERIVED INTO shared company
    data: the rollup below, and the contact-email promotion in
    `vault.save_job`.

    Owner decision 2026-10-27 (privacy audit finding 3): shared data is
    derived only from PUBLIC POSTINGS, which is a record no user owns --
    the ones the feed pool and the API add, and the pre-M2 records the
    migration has not handed to anybody. Never from a job a user owns,
    and the admin is not an exception.

    Why the admin is not an exception, which is what changed. Everything
    this rule lets through lands on a record every user reads, and some
    of it names the posting it came from: `_posting_headcount` publishes
    `{'count', 'job_id', 'posted_date'}`, and the rest of the rollup
    publishes a company's posting count, its locations, its keywords and
    its seniority range. An admin's job is as private as a tester's (D3
    scopes every read by owner, the admin included), so admitting it
    published the id and the posting date of a record no other user may
    read, plus aggregates only its holder should have. "Admin" is a
    permission to curate the shared half on purpose, not a statement
    that their own board is public.

    Keyed on the record's owner and never on the session, so it answers
    the same on the request thread and on the AI queue, where there is no
    session to read. It needs no account list either, which is why the
    pre-M1 / fixture special case is gone: a vault with no accounts holds
    only ownerless records, so every one of them is a public posting and
    reads as one here.

    This is NOT the rule for whether a record's resolution may bring a
    shared company into EXISTENCE or teach one an identifier; that is
    `may_write_shared_company` below, and the two are deliberately
    different rules.
    """
    from careeros import vault

    return not (record or {}).get(vault.OWNER_FIELD)


def may_write_shared_company(root, record, owners=None):
    """Whether this one record's resolution may create a shared company,
    teach one an identifier, or record a source onto one.

    M2 (CAREER-39, decision D3), and the rule `contributes_to_shared`
    used to be before the 2026-10-27 decision split the two apart. A
    tester's job is readable by nobody else, so a tester's posting
    resolves to a company that already exists and never brings one into
    existence, teaches it nothing, and has no careers page or ATS feed
    recorded onto it. Until the M3 merge queue exists, the shipped
    decision is that a tester does not write a shared record.

    True for a record with no owner, which is the pre-M2 record the admin
    inherits (`vault.Owner`), and for one an admin owns. The admin IS an
    exception here and is not one above, which is the whole distinction:
    curating the shared half -- deciding that an employer exists under
    this name, with this domain, on this ATS tenant -- is the admin's
    job, and intake is the only path the product has for doing it. What
    they may not do is have their own private board silently aggregated
    into data every user reads.

    False for a stored owner that is not an admin's. A record whose owner
    names no stored account at all is also false, which is a shape
    nothing produces: the accounts command line creates, disables and
    enables an account and never deletes one, so an owner id on a record
    names a stored account unless somebody edited the YAML by hand. The
    strict reading is the safe one there, because the alternative would
    publish a record nobody can read.

    Keyed on the record's owner and never on the session, for the same
    reason: there is no session on the AI queue.
    """
    from careeros import vault

    if owners is None:
        owners = _shared_owners(root)
    if owners is None:
        return True
    owner = (record or {}).get(vault.OWNER_FIELD)
    return not owner or owner in owners


def record_owner_scope(root, record):
    """The ownership scope the owner of this record reads under.

    Company resolution reads jobs: the employer names recorded against
    an ATS tenant, and the legacy fallback's own sweep for a job on the
    same tenant. Owner decision 2026-10-18: those reads are the
    caller's own and nobody else's. A private posting must not change
    which company somebody else's posting resolves to, must not flip a
    link from `linked` to `needs_review`/`shared_tenant`, and must not
    have its ATS association published as an identifier on a shared
    company. Cross-user resolution consistency is the thing traded away
    for that, deliberately: the same tenant may resolve differently for
    two users, which is the same shape as the two of them disagreeing
    about whether a retired company exists.

    On the request thread the caller is the session. On the AI queue
    there is none, so the scope is reconstructed from the record being
    processed, which is what this answers.

    An ownerless record is the admin's (`vault.Owner`), so it reads
    under the admin's own scope: admin-owned plus the legacy ownerless
    records, the same set the rollup above aggregates. A vault with no
    admin, or no accounts at all, is unscoped, which is the pre-M1 and
    fixture case `contributes_to_shared` already treats that way.
    """
    from careeros import users, vault

    identifier = (record or {}).get(vault.OWNER_FIELD)
    user = users.load_user(root, identifier) if identifier else None
    if user is None:
        found = users.admins(root)
        user = found[0] if found else None
    return users.owner(user)


def shared_jobs(root):
    """The jobs a shared company record may be derived from.

    The rollup below puts a posting's id (in the headcount evidence), its
    location, its keywords, its seniority and the count of a company's
    postings onto a record every user reads. So it reads the shared half
    of the vault only, per `contributes_to_shared`.

    `vault.list_jobs` is the board read, so a universe-only record
    contributes nothing either (CAREER-72/74). The pool import writes 704
    ownerless postings in one go and nobody has looked at one of them;
    letting them rewrite the locations, keywords and posting counts of 89
    curated shared companies is the M3 merge-queue question and not an
    import's to settle. The moment a person adds one to their board it is
    a board entry and rolls up like any other posting, which is the same
    "evidence earns its way in" shape the tester gate above has.
    `vault.save_job` reads this rule back, so saving a universe-only
    record skips the regeneration it could not change.

    Owner decision 2026-10-27 (finding 3): the shared half is the
    PUBLIC POSTINGS and nothing else. An admin-owned job used to be in
    here, which published the id and posting date of a record no other
    user may read; see `contributes_to_shared`.
    """
    from careeros import vault

    return [job for job in vault.list_jobs(root) if contributes_to_shared(root, job)]


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

    The posting headcount this aggregation now carries
    (SIZE_EVIDENCE_KEYS, owner decision 2026-10-16) is size evidence, so
    it is gated and actively deleted the same way: the matrix gives a
    non-employer no size at all, and leaving evidence toward a class
    behind would be the nested-rollup leak above under a second name.

    M2 (decision D3), tightened by the owner decision of 2026-10-27: the
    postings it aggregates are the PUBLIC POSTINGS (`shared_jobs`),
    never any user's own -- the admin's included. A rollup over all of
    them would publish one user's private postings -- their count, their
    locations, their keywords, and the id and posting date of the job the
    headcount came from -- on a record every user reads.
    """
    from careeros import vault
    company = vault.load_company(root, identifier)
    if company is None:
        return None
    derived = enrich_company(job for job in shared_jobs(root)
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
            if key == 'sectors' or key in SIZE_EVIDENCE_KEYS:
                continue
            if isinstance(value, dict) and isinstance(block.get(key), dict):
                value = block[key] | value
            block[key] = value
        block.pop('sectors', None)
        for key in SIZE_EVIDENCE_KEYS:
            block.pop(key, None)
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
        # M2 soft retire: a company the admin retired is gone from their
        # world, so an admin-triggered sweep does not spend a network
        # call on it or write a fresh classification onto it.
        if company.get('kind', 'employer') != 'employer' or vault.is_retired(company):
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
            # Writable on purpose: the only caller of apply_backfill is
            # the admin-gated backfill endpoint (M2, decision D3).
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
