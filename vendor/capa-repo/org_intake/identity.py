"""Organisation identity resolution ladder.

Ported from careeros/company_resolve.py. Resolves a loose organisation
reference (a posting URL, a free-text employer name, or both) to one known
record, reusing an existing one whenever the evidence supports it and
creating a fresh one when it does not. Rungs 1-2 (resolve_rungs_1_2) are
pure local identifier lookups keyed by ATS tenant or domain: no network
I/O, safe to call before any fetch. Rungs 3-5 (resolve_rungs_3_5) run once
posting text is available: name matching (exact, then fuzzy) and the
tenant-vs-employer cross-check.

Identifiers are additive and deduped on (type, value), so repeated calls
for the same tenant/domain never grow the list with a redundant entry
(rule 2). This module performs store reads/writes but never a network
call; sector/size enrichment (which does reach the network) lives in
enrich.py and is never duplicated here.

Dependency injection: `store` is any object satisfying store.py's
protocol (list_organisations/load_organisation/save_organisation); this
module never imports a product's storage layer. Tenant-sharing evidence
(rule 6/behavior note M6) is passed in as `tenant_employer_names`, a
precomputed list of employer name strings already seen under the posting's
(provider, tenant) pair - this module never scans job/posting records
itself (the contract's settled "Tenant-sharing evidence" open question).
"""
import difflib
import re
import uuid

from org_intake import ats, url as url_mod

IDENTIFIER_TYPES = ('domain', 'ats_tenant', 'wikidata', 'name_variant')

# Below this ratio, a name is not even offered as a fuzzy candidate; at or
# above 1.0 it would already have matched as an exact name (handled first,
# separately, so a true exact match is never also reported as "fuzzy").
FUZZY_CUTOFF = 0.6
FUZZY_CANDIDATE_LIMIT = 5


def _normalize_name(name):
    """Case/punctuation-insensitive form, used for both the exact-match
    check and as the basis for the fuzzy ratio: collapse everything but
    letters/digits to single spaces so "Acme, Inc." and "ACME INC" compare
    equal, and "Acme" vs "Acme GmbH" compare as a partial (fuzzy) match."""
    return re.sub(r'[^a-z0-9]+', ' ', (name or '').casefold()).strip()


def ats_tenant_value(ats_match):
    return f"{ats_match['provider']}:{ats_match['tenant']}"


def _identifiers(record):
    return record.get('identifiers') or []


def _name_variants(record):
    """Normalized-name -> display label, for the record's own name plus
    every name_variant identifier on file (including ones taught by an
    owner's review decision, see apply_review)."""
    variants = {}
    own = _normalize_name(record.get('name'))
    if own:
        variants[own] = record.get('name')
    for identifier in _identifiers(record):
        if identifier.get('type') == 'name_variant':
            normalized = _normalize_name(identifier.get('value'))
            if normalized:
                variants[normalized] = identifier.get('value')
    return variants


def find_by_identifier(records, type_, value):
    if not value:
        return None
    return next((record for record in records
                 if any(identifier.get('type') == type_ and identifier.get('value') == value
                        for identifier in _identifiers(record))), None)


def find_all_by_exact_name(records, name, exclude_id=None):
    """Every record whose name/name_variant matches exactly, in list
    order - used where more than one match must be treated as ambiguous
    (rule 5) rather than first-wins."""
    target = _normalize_name(name)
    if not target:
        return []
    return [record for record in records
            if not (exclude_id and record.get('id') == exclude_id) and target in _name_variants(record)]


def find_by_exact_name(records, name, exclude_id=None):
    """Case/punct-insensitive match against a record's name or any of its
    name_variant identifiers. Returns the first match only; a caller that
    must detect more than one exact match (rule 5) uses
    find_all_by_exact_name instead."""
    matches = find_all_by_exact_name(records, name, exclude_id)
    return matches[0] if matches else None


def fuzzy_candidates(records, name, exclude_id=None, cutoff=FUZZY_CUTOFF, limit=FUZZY_CANDIDATE_LIMIT):
    """Candidates whose best-matching name/name_variant scores at or above
    cutoff but short of an exact match (an exact match is never reported
    here; it is handled earlier by find_by_exact_name). Sorted by score,
    highest first (rule 4: never auto-linked, always a scored candidate)."""
    target = _normalize_name(name)
    if not target:
        return []
    scored = []
    for record in records:
        if exclude_id and record.get('id') == exclude_id:
            continue
        best_score, best_label = 0.0, None
        for normalized, label in _name_variants(record).items():
            score = difflib.SequenceMatcher(None, target, normalized).ratio()
            if score > best_score:
                best_score, best_label = score, label
        if cutoff <= best_score < 1.0:
            scored.append({'record_id': record['id'], 'name': record.get('name'),
                           'score': round(best_score, 3), 'basis': best_label})
    scored.sort(key=lambda candidate: -candidate['score'])
    return scored[:limit]


def _has_identifier(record, type_, value):
    return any(identifier.get('type') == type_ and identifier.get('value') == value
               for identifier in _identifiers(record))


def add_identifier(store, record, type_, value, provenance):
    """Append one identifier, deduped on (type, value); a no-op write is
    skipped entirely so repeated calls never grow the list (rule 2). An
    ats_tenant identifier already owned by a different record is never
    taken over (one ATS tenant can host more than one employer; rule 6).
    Returns the (possibly unchanged) record."""
    if type_ not in IDENTIFIER_TYPES or not value or _has_identifier(record, type_, value):
        return record
    if type_ == 'ats_tenant':
        owner = find_by_identifier(store.list_organisations(), type_, value)
        if owner and owner['id'] != record['id']:
            return record
    identifiers = _identifiers(record) + [{'type': type_, 'value': value, 'provenance': provenance}]
    return store.save_organisation({'identifiers': identifiers}, record['id'])


def resolve_rungs_1_2(store, url):
    """Rungs 1-2: pure local identifier lookups, no network I/O. Rung 2
    (domain) only ever applies to a non-ATS posting URL: an ATS-hosted
    URL's domain belongs to the ATS provider, not the employer, so it is
    never looked up as an organisation identifier.

    Returns (record_or_None, reason_or_None, ats_match_or_None). The ATS
    match is returned even on a miss, so a caller can still record a fresh
    ats_tenant identifier once a record becomes known later."""
    ats_match = ats.detect_ats(url)
    records = store.list_organisations()
    if ats_match is not None:
        record = find_by_identifier(records, 'ats_tenant', ats_tenant_value(ats_match))
        return (record, 'ats_tenant', ats_match) if record else (None, None, ats_match)
    domain = url_mod.domain(url)
    record = find_by_identifier(records, 'domain', domain)
    return (record, 'domain', None) if record else (None, None, None)


def _tenant_has_other_evidenced_employer(record, tenant_employer_names):
    """Has any employer name already observed under this (provider,
    tenant) pair evidenced a DIFFERENT employer than this record? Only
    real observed-posting text counts (passed in by the caller, per the
    contract's settled tenant-sharing-evidence answer); a tenant with no
    other evidence on file is never flagged just because some unrelated
    record happens to exist elsewhere in the store."""
    if not tenant_employer_names:
        return False
    variants = set(_name_variants(record))
    for name in tenant_employer_names:
        normalized = _normalize_name(name) if name else ''
        if normalized and normalized not in variants and not fuzzy_candidates([record], name):
            return True
    return False


def resolve_rungs_3_5(store, *, url, employer_name, linked_record=None, linked_reason=None,
                       tenant_employer_names=None):
    """Rungs 3-5, called once the posting's employer name is known
    (employer_name; may be None/empty, which is "not evidenced", never a
    guess). `linked_record`/`linked_reason` are whatever resolve_rungs_1_2
    already found; this never repeats that lookup, it only layers the
    employer-name cross-check (rung 5) on top of an existing ATS-tenant
    link, or runs name matching from scratch when nothing linked locally
    yet (rungs 3-4).

    Returns a dict: record (or None), link_state
    ('linked' | 'needs_review' | 'pending' | 'new_record'), link_reason,
    candidates (a list for needs_review, else None). link_state
    'new_record' signals: rung 4 applies, nothing on file matches even
    fuzzily, and a fresh record should be created.
    """
    records = store.list_organisations()
    # A posting already sitting in needs_review under one of the
    # tenant-rooted reasons is still fundamentally an ats_tenant link, just
    # already flagged - re-resolving it must use the SAME tenant-aware
    # treatment, not fall through to the generic "weak basis" branch below.
    tenant_rooted = linked_reason in ('ats_tenant', 'shared_tenant', 'employer_differs_from_tenant')

    if linked_record is not None:
        if linked_reason == 'manual':
            return dict(record=linked_record, link_state='linked', link_reason=linked_reason, candidates=None)
        if not employer_name:
            # Even when THIS posting's own employer text is null, a tenant
            # already known - from different, real evidence - to host more
            # than one employer must never be silently auto-confirmed just
            # because this one posting happens to say nothing.
            if tenant_rooted and _tenant_has_other_evidenced_employer(linked_record, tenant_employer_names):
                return dict(record=linked_record, link_state='needs_review',
                           link_reason='shared_tenant', candidates=None)
            return dict(record=linked_record, link_state='linked', link_reason=linked_reason, candidates=None)
        if tenant_rooted:
            # Rung 5: the posting's employer must agree with the tenant's
            # owner (exactly or fuzzily) or this is a staffing/shared-tenant
            # case, never silently assumed either way. A confirming match
            # always upgrades the reason back to the honest 'ats_tenant'.
            if (find_by_exact_name([linked_record], employer_name)
                    or fuzzy_candidates([linked_record], employer_name)):
                return dict(record=linked_record, link_state='linked',
                           link_reason='ats_tenant', candidates=None)
            other = find_by_exact_name(records, employer_name, exclude_id=linked_record['id'])
            if other is not None:
                return dict(record=linked_record, link_state='needs_review', link_reason='shared_tenant',
                           candidates=[{'record_id': other['id'], 'name': other.get('name'),
                                       'score': 1.0, 'basis': employer_name}])
            return dict(record=linked_record, link_state='needs_review',
                       link_reason='employer_differs_from_tenant', candidates=None)
        # Any other basis this record was reached through (a plain domain
        # identifier, a prior exact-name match, or a rung-4 guess that was
        # never real evidence at all) is weaker than a unique ATS tenant id
        # - a provisional link must never suppress the fuzzy check. Only an
        # exact match reconfirms silently; anything less goes to review
        # with whatever candidates the evidence actually supports.
        exact = find_by_exact_name([linked_record], employer_name)
        if exact is not None:
            return dict(record=linked_record, link_state='linked', link_reason='name_exact', candidates=None)
        other = find_by_exact_name(records, employer_name, exclude_id=linked_record['id'])
        current_candidates = fuzzy_candidates([linked_record], employer_name, cutoff=0)
        for candidate in current_candidates:
            candidate['current'] = True
        candidates = current_candidates + fuzzy_candidates(
            records, employer_name, exclude_id=linked_record['id'])
        if other is not None:
            candidates = [{'record_id': other['id'], 'name': other.get('name'), 'score': 1.0,
                          'basis': employer_name}] + [c for c in candidates if c['record_id'] != other['id']]
        return dict(record=linked_record, link_state='needs_review',
                   link_reason='ambiguous_exact' if other else 'fuzzy_name',
                   candidates=(sorted(candidates[:FUZZY_CANDIDATE_LIMIT],
                                      key=lambda c: -c['score']) or None))

    if employer_name:
        exact_matches = find_all_by_exact_name(records, employer_name)
        if len(exact_matches) > 1:
            # Rule 5: more than one record carries the identical exact
            # name - never first-wins, always a review question.
            return dict(record=None, link_state='needs_review', link_reason='ambiguous_exact',
                       candidates=[{'record_id': r['id'], 'name': r.get('name'), 'score': 1.0,
                                   'basis': employer_name} for r in exact_matches])
        if exact_matches:
            return dict(record=exact_matches[0], link_state='linked', link_reason='name_exact', candidates=None)
        fuzzy = fuzzy_candidates(records, employer_name)
        if fuzzy:
            return dict(record=None, link_state='needs_review', link_reason='fuzzy_name', candidates=fuzzy)
        return dict(record=None, link_state='new_record', link_reason='new_record', candidates=None)

    return dict(record=None, link_state='pending', link_reason=None, candidates=None)


def _record_link_evidence(store, record, ats_match, domain):
    """Record whatever rung-1/2-shaped evidence this URL carries onto a
    confidently linked record, regardless of which rung actually produced
    the link (e.g. a rung-3 name match still teaches the tenant/domain for
    next time)."""
    # R5: source registration (ats_feed/careers_page) is a product concern, not this capability's - this only ever teaches an identifier, never a source-list entry.
    if ats_match is not None:
        record = add_identifier(store, record, 'ats_tenant', ats_tenant_value(ats_match), 'scrape')
    elif domain:
        record = add_identifier(store, record, 'domain', domain, 'scrape')
    return record


def _create_record(store, name, ats_match, domain):
    record = store.save_organisation({'name': name, 'name_source': 'auto'})
    return _record_link_evidence(store, record, ats_match, domain)


def _result_fields(record, state, reason, candidates):
    review = None
    if state == 'needs_review':
        # A one-time revision token so a stale concurrent resolution is
        # rejected rather than silently first-winning (States section).
        review = {'candidates': candidates or [], 'token': uuid.uuid4().hex}
    return dict(record_id=record['id'] if record else None,
               link_state=state, link_reason=reason, review=review)


def resolve_identity(store, *, url, employer_name=None, fallback_name=None, existing=None,
                      legacy_hint=None, tenant_employer_names=None):
    """Full ladder entry point.

    resolve_identity(store, url="https://boards.greenhouse.io/northwind/jobs/9981")
    => {"record_id": None, "link_state": "pending", "link_reason": None, "review": None}

    `existing`, when given, is an (record_id, link_reason) pair describing
    a link the caller already carries: it takes priority over rungs 1-2's
    own identifier lookup (and over legacy_hint), since an existing link -
    however it was established - must never be silently abandoned for a
    fresh rungs-1-2 guess just because this call's URL does not happen to
    carry a matching identifier. Ignored when its record_id is falsy or no
    longer resolves.

    `legacy_hint`, when given, is an optional (record, reason) pair the
    caller already found through some matching mechanism of its own. It is
    consulted only once rungs 1-2's own identifier lookup finds nothing
    (and existing did not apply), so a persisted identifier always wins
    over it; any link made through it is immediately taught into a real
    identifier (see _record_link_evidence).

    Called with employer_name=None and fallback_name=None (e.g. at stub
    creation, before any fetch): only rungs 1-2 run (pure, no network),
    and the result is never a review state or a new record - rungs 3-5
    need the posting text first, so a miss here is simply 'pending'
    (rule 1).

    Called again once employer_name is known (the strict, never-guessed
    signal rungs 3 and 5 are specified against) and optionally
    fallback_name (a looser name signal, consulted only once employer_name
    has nothing to offer, and only for an exact-name match or rung-4
    creation - never for fuzzy matching or a review flag).

    All I/O here is store reads/writes; no network call is ever made
    (rule 3).

    Returns a dict: record_id, link_state, link_reason, review.
    """
    linked_record, linked_reason, ats_match = None, None, None
    if existing and existing[0]:
        linked_record = store.load_organisation(existing[0])
        linked_reason = existing[1] if linked_record is not None else None
    if linked_record is not None:
        ats_match = ats.detect_ats(url)
    else:
        linked_record, linked_reason, ats_match = resolve_rungs_1_2(store, url)
        if linked_record is None and legacy_hint is not None:
            linked_record, linked_reason = legacy_hint
    domain = None if ats_match is not None else url_mod.domain(url)

    if employer_name is None and fallback_name is None:
        if linked_record is not None:
            if (linked_reason == 'ats_tenant'
                    and _tenant_has_other_evidenced_employer(linked_record, tenant_employer_names)):
                return _result_fields(linked_record, 'needs_review', 'shared_tenant', None)
            linked_record = _record_link_evidence(store, linked_record, ats_match, domain)
            return _result_fields(linked_record, 'linked', linked_reason, None)
        return _result_fields(None, 'pending', None, None)

    result = resolve_rungs_3_5(store, url=url, employer_name=employer_name, linked_record=linked_record,
                               linked_reason=linked_reason, tenant_employer_names=tenant_employer_names)
    record, state, reason, candidates = (result['record'], result['link_state'],
                                         result['link_reason'], result['candidates'])

    if state == 'pending' and fallback_name:
        exact_matches = find_all_by_exact_name(store.list_organisations(), fallback_name)
        if len(exact_matches) > 1:
            # Rule 5 applies here too: more than one record carrying the
            # identical exact name is itself an ambiguity, never a
            # first-wins pick, even when the signal is only the looser
            # fallback_name rather than the strict employer_name.
            return _result_fields(None, 'needs_review', 'ambiguous_exact_name_match',
                                  [{'record_id': r['id'], 'name': r.get('name'), 'score': 1.0,
                                    'basis': fallback_name} for r in exact_matches])
        if exact_matches:
            record, state, reason = exact_matches[0], 'linked', 'name_exact'
        else:
            state, reason = 'new_record', 'new_record'

    if state == 'new_record':
        record = _create_record(store, employer_name or fallback_name, ats_match, domain)
        state, reason = 'linked', 'new_company'
    elif state == 'linked' and record is not None:
        record = _record_link_evidence(store, record, ats_match, domain)
    return _result_fields(record, state, reason, candidates)


def apply_review(store, *, url=None, link_reason=None, employer_name=None, record_id=None, create=None,
                  token=None, current_token=None):
    """An owner resolves a needs_review case: either picks an existing
    candidate (record_id) or creates a new record (create={'name': ...}).

    Writes the posting's extracted employer name as a user-provenanced
    name_variant identifier on the chosen record, so the same fuzzy case
    never asks twice: the next posting naming this same employer text will
    hit find_by_exact_name via that identifier and auto-link with reason
    name_exact.

    States section: a needs_review case carries a one-time review token
    so a stale concurrent resolution is rejected rather than silently
    first-winning. This module never persists that token itself (the
    per-posting review state lives in the caller's own posting record,
    not the organisation record this module owns); the caller instead
    supplies both `token` (the one the review decision was made against)
    and `current_token` (whatever is on file right now, e.g. from a
    later resolve_identity/rerun call). Omitting `current_token` (the
    default) skips the check entirely, preserving today's behavior for a
    caller that does not track tokens at all.

    Returns a dict: {'record': the (possibly newly created) record, or
    None on a stale-token refusal; 'rejected': bool; 'reason': a refusal
    reason string, or None}. The caller is responsible for linking its
    own posting/job record to the returned record and clearing the
    review state there.
    """
    if current_token is not None and token != current_token:
        return {'record': None, 'rejected': True, 'reason': 'stale_review_token'}
    if record_id:
        record = store.load_organisation(record_id)
        if record is None:
            raise ValueError('Record not found.')
    elif create:
        name = (create.get('name') or '').strip()
        if not name:
            raise ValueError('Provide a record name.')
        record = store.save_organisation({'name': name, 'name_source': 'owner'})
        # Preserve whatever URL-derived identifiers this posting already
        # discovered, so the create-new path never leaves the new record
        # without the identifiers a regular rung-4 creation would have
        # taught. A shared-tenant case never asserts exclusive tenant
        # ownership (the ats_tenant identifier is omitted).
        ats_match = ats.detect_ats(url or '')
        domain = None if ats_match is not None else url_mod.domain(url or '')
        if ats_match is not None:
            if link_reason not in ('shared_tenant', 'employer_differs_from_tenant'):
                record = add_identifier(store, record, 'ats_tenant', ats_tenant_value(ats_match), 'scrape')
        elif domain:
            record = add_identifier(store, record, 'domain', domain, 'scrape')
    else:
        raise ValueError('Provide record_id or create.')
    if employer_name:
        record = add_identifier(store, record, 'name_variant', employer_name, 'user')
    return {'record': record, 'rejected': False, 'reason': None}


def rerun(store, *, url, employer_name=None, fallback_name=None, record_id=None, link_reason=None,
          link_state=None, review=None, owner_set=False, tenant_employer_names=None):
    """Re-run the full ladder using a stored url/employer_name (no network
    I/O; a caller that needs fresh posting text refetches it itself first).

    Human edits always win (rule 14): a no-op, returning the current state
    unchanged, whenever `owner_set` is true - the caller's own record of
    whether ANY of its link-decision fields (record id, link state,
    reason) carries owner/user provenance, since an owner can set just the
    state or reason alone."""
    if owner_set:
        return dict(record_id=record_id, link_state=link_state, link_reason=link_reason, review=review)
    return resolve_identity(store, url=url, employer_name=employer_name, fallback_name=fallback_name,
                            existing=(record_id, link_reason), tenant_employer_names=tenant_employer_names)
