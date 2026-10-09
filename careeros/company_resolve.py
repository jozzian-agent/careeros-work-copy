"""Company resolution ladder (JOZ-266, spec SPEC-journey1.md §3 step 4).

Resolves a job's company from identifiers already on file plus, once the
posting is fetched, the employer name extracted from its text. Rungs 1-2
(resolve_rungs_1_2) are pure local identifier lookups: no network I/O
(global rule 5), safe to call synchronously at stub creation before any
fetch. Rungs 3-5 (resolve_rungs_3_5) run after fetch/extraction and only
ever consult data already in the vault: name matching (exact and fuzzy)
and the staffing/shared-tenant flags.

Identifiers and sources are additive and deduped -- (type, value) for an
identifier, normalized url for a source -- so repeated ingest of the same
posting, or the same tenant/domain under a second posting, never grows
either list with a redundant entry.

This module performs vault reads/writes (local file I/O) but never a
network call; company_lookup.py's external-fetch cascade is reused as-is
for sector/size enrichment and is never duplicated or modified here.
"""
import difflib
import re
import uuid

from careeros import url_normalize, vault

# m11: the canonical tenant feed/listing URL recorded as a company's
# ats_feed source, so repeated postings under the same tenant dedupe to one
# source instead of growing one entry per posting (posting URLs themselves
# stay on the job record, never here). A provider missing from this map
# falls back to the triggering posting URL (see _ats_feed_url).
_ATS_FEED_URL = {
    'greenhouse': 'https://boards.greenhouse.io/{tenant}',
    'lever': 'https://jobs.lever.co/{tenant}',
    'ashby': 'https://jobs.ashbyhq.com/{tenant}',
    'smartrecruiters': 'https://jobs.smartrecruiters.com/{tenant}',
    'recruitee': 'https://{tenant}.recruitee.com',
    'teamtailor': 'https://{tenant}.teamtailor.com/jobs',
    'personio': 'https://{tenant}.jobs.personio.de',
    'workday': 'https://{tenant}.myworkdayjobs.com',
    'refline': 'https://m.refline.ch/{tenant}',
    'join': 'https://{tenant}.join.com/jobs',
}


def _ats_feed_url(ats_match, fallback_url):
    template = _ATS_FEED_URL.get(ats_match.provider)
    return template.format(tenant=ats_match.tenant) if template else fallback_url

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


def _domain_of(url):
    from careeros import intake
    try:
        return intake.domain(url)
    except Exception:
        return ''


def ats_tenant_value(ats_match):
    return f'{ats_match.provider}:{ats_match.tenant}'


def _identifiers(company):
    return company.get('identifiers') or []


def _name_variants(company):
    """Normalized-name -> display label, for the company's own name plus
    every name_variant identifier on file (including ones taught by the
    owner's review decisions, see apply_review)."""
    variants = {}
    own = _normalize_name(company.get('name'))
    if own:
        variants[own] = company.get('name')
    for identifier in _identifiers(company):
        if identifier.get('type') == 'name_variant':
            normalized = _normalize_name(identifier.get('value'))
            if normalized:
                variants[normalized] = identifier.get('value')
    return variants


def find_by_identifier(companies, type_, value):
    if not value:
        return None
    return next((company for company in companies
                 if any(identifier.get('type') == type_ and identifier.get('value') == value
                        for identifier in _identifiers(company))), None)


def find_all_by_exact_name(companies, name, exclude_id=None):
    """Every company whose name/name_variant matches exactly, in list
    order -- used where more than one match must be treated as ambiguous
    (Decision-20) rather than first-wins."""
    target = _normalize_name(name)
    if not target:
        return []
    return [company for company in companies
            if not (exclude_id and company.get('id') == exclude_id) and target in _name_variants(company)]


def find_by_exact_name(companies, name, exclude_id=None):
    """Case/punct-insensitive match against a company's name or any of its
    name_variant identifiers -- rung-1-style confident per spec §3 step 4.
    Returns the first match only; a caller that must detect more than one
    exact match (Decision-20) uses find_all_by_exact_name instead."""
    matches = find_all_by_exact_name(companies, name, exclude_id)
    return matches[0] if matches else None


def fuzzy_candidates(companies, name, exclude_id=None, cutoff=FUZZY_CUTOFF, limit=FUZZY_CANDIDATE_LIMIT):
    """Candidates whose best-matching name/name_variant scores at or above
    cutoff but short of an exact match (an exact match is never reported
    here; it is handled earlier by find_by_exact_name). Sorted by score,
    highest first."""
    target = _normalize_name(name)
    if not target:
        return []
    scored = []
    for company in companies:
        if exclude_id and company.get('id') == exclude_id:
            continue
        best_score, best_label = 0.0, None
        for normalized, label in _name_variants(company).items():
            score = difflib.SequenceMatcher(None, target, normalized).ratio()
            if score > best_score:
                best_score, best_label = score, label
        if cutoff <= best_score < 1.0:
            scored.append({'company_id': company['id'], 'name': company.get('name'),
                           'score': round(best_score, 3), 'basis': best_label})
    scored.sort(key=lambda candidate: -candidate['score'])
    return scored[:limit]


def _has_identifier(company, type_, value):
    return any(identifier.get('type') == type_ and identifier.get('value') == value
               for identifier in _identifiers(company))


def add_identifier(root, company, type_, value, provenance):
    """Append one identifier, deduped on (type, value); a no-op write is
    skipped entirely so repeated ingest never grows the list. Returns the
    (possibly unchanged) company record."""
    if type_ not in vault.IDENTIFIER_TYPES or not value or _has_identifier(company, type_, value):
        return company
    if type_ == 'ats_tenant':
        owner = find_by_identifier(vault.list_companies(root), type_, value)
        if owner and owner['id'] != company['id']:
            return company
    identifiers = _identifiers(company) + [{'type': type_, 'value': value, 'provenance': provenance}]
    return vault.save_company(root, {'identifiers': identifiers}, company['id'])


def add_source(root, company, kind, url, ats_provider=None):
    """Append one source, deduped by normalized url; last_polled stays null
    (Journey 2 polls, Journey 1 only records, per spec §5)."""
    if not url:
        return company
    normalized = url_normalize.normalize(url)
    sources = company.get('sources') or []
    if any(url_normalize.normalize(source.get('url') or '') == normalized for source in sources):
        return company
    new_source = {'id': f'SRC-{len(sources) + 1}', 'kind': kind, 'url': url,
                  'ats_provider': ats_provider, 'active': True, 'last_polled': None}
    return vault.save_company(root, {'sources': sources + [new_source]}, company['id'])


def resolve_rungs_1_2(root, url):
    """Rungs 1-2: pure local identifier lookups, no network I/O (global
    rule 5). Rung 2 (domain) only ever applies to a non-ATS posting URL: an
    ATS-hosted URL's domain belongs to the ATS provider, not the employer,
    so it is never looked up as a company identifier.

    Returns (company_or_None, reason_or_None, ats_match_or_None). The ATS
    match is returned even on a miss, so a caller can still record a fresh
    ats_tenant identifier/source once a company becomes known later (rung
    3 name match, or rung 4 creation).
    """
    ats_match = url_normalize.detect_ats(url)
    companies = vault.list_companies(root)
    if ats_match is not None:
        company = find_by_identifier(companies, 'ats_tenant', ats_tenant_value(ats_match))
        return (company, 'ats_tenant', ats_match) if company else (None, None, ats_match)
    domain = _domain_of(url)
    company = find_by_identifier(companies, 'domain', domain)
    return (company, 'domain', None) if company else (None, None, None)


def resolve_rungs_3_5(root, *, url, employer_name, linked_company=None, linked_reason=None):
    """Rungs 3-5, called after fetch/extraction once the posting's employer
    name is known (employer_named_in_posting; may be None/empty, which is
    "not evidenced", never a guess). `linked_company`/`linked_reason` are
    whatever resolve_rungs_1_2 already found; this never repeats that
    lookup, it only layers the employer-name cross-check (rung 5) on top of
    an existing ATS-tenant link, or runs name matching from scratch when
    nothing linked locally yet (rungs 3-4).

    Returns a dict: company (record, or None), link_state
    ('linked' | 'needs_review' | 'pending' | 'new_company'), link_reason,
    candidates (a list for needs_review, else None). link_state
    'new_company' is a signal to the caller: rung 4 applies, nothing on
    file matches even fuzzily, and a fresh company should be created.
    """
    companies = vault.list_companies(root)
    # A job already sitting in needs_review under one of the tenant-rooted
    # reasons is still fundamentally an ats_tenant link, just already
    # flagged -- re-resolving it (M1's existing= anchoring feeds a job's
    # OWN stored reason back in here) must use the SAME tenant-aware
    # treatment, not fall through to the generic "weak basis" branch below
    # (which would, among other things, forget the tenant match entirely).
    tenant_rooted = linked_reason in ('ats_tenant', 'shared_tenant', 'employer_differs_from_tenant')

    if linked_company is not None:
        if linked_reason == 'manual':
            return dict(company=linked_company, link_state='linked', link_reason=linked_reason, candidates=None)
        if not employer_name:
            # M6: even when THIS posting's own employer text is null (e.g.
            # Phase B's fallback_name kept the resolution out of the
            # stub-time-only null/null shortcut, but still had nothing
            # real to offer), a tenant already known -- from a different,
            # real stored posting -- to host more than one employer must
            # never be silently auto-confirmed just because this one
            # posting happens to say nothing.
            if tenant_rooted and _tenant_has_other_evidenced_employer(
                    root, url_normalize.detect_ats(url), linked_company):
                return dict(company=linked_company, link_state='needs_review',
                           link_reason='shared_tenant', candidates=None)
            return dict(company=linked_company, link_state='linked', link_reason=linked_reason, candidates=None)
        if tenant_rooted:
            # Rung 5: the posting's employer must agree with the tenant's
            # owner (exactly or fuzzily) or this is a staffing/shared-tenant
            # case, never silently assumed either way. A confirming match
            # always upgrades the reason back to the honest 'ats_tenant',
            # even if this job had previously been flagged.
            if (find_by_exact_name([linked_company], employer_name)
                    or fuzzy_candidates([linked_company], employer_name)):
                return dict(company=linked_company, link_state='linked',
                           link_reason='ats_tenant', candidates=None)
            other = find_by_exact_name(companies, employer_name, exclude_id=linked_company['id'])
            if other is not None:
                return dict(company=linked_company, link_state='needs_review', link_reason='shared_tenant',
                           candidates=[{'company_id': other['id'], 'name': other.get('name'),
                                       'score': 1.0, 'basis': employer_name}])
            return dict(company=linked_company, link_state='needs_review',
                       link_reason='employer_differs_from_tenant', candidates=None)
        # M2/M4: any other basis this company was reached through (a plain
        # domain identifier, a prior exact-name match, or a rung-4 guess
        # that was never real evidence at all) is weaker than a unique ATS
        # tenant id -- a provisional automation link must never suppress
        # the fuzzy check. Only an exact match reconfirms silently (with
        # the reason upgraded to reflect that real evidence now exists);
        # anything less goes to review with whatever candidates the
        # evidence actually supports, never a silent keep and never a
        # silent relink.
        exact = find_by_exact_name([linked_company], employer_name)
        if exact is not None:
            return dict(company=linked_company, link_state='linked', link_reason='name_exact', candidates=None)
        other = find_by_exact_name(companies, employer_name, exclude_id=linked_company['id'])
        current_candidates = fuzzy_candidates([linked_company], employer_name, cutoff=0)
        for candidate in current_candidates:
            candidate['current'] = True
        candidates = current_candidates + fuzzy_candidates(
            companies, employer_name, exclude_id=linked_company['id'])
        # An exact alternative challenges the provisional link; it is not fuzzy.
        if other is not None:
            candidates = [{'company_id': other['id'], 'name': other.get('name'), 'score': 1.0,
                          'basis': employer_name}] + [c for c in candidates if c['company_id'] != other['id']]
        return dict(company=linked_company, link_state='needs_review',
                   link_reason='ambiguous_exact' if other else 'fuzzy_name',
                   candidates=(sorted(candidates[:FUZZY_CANDIDATE_LIMIT],
                                      key=lambda c: -c['score']) or None))

    if employer_name:
        exact_matches = find_all_by_exact_name(companies, employer_name)
        if len(exact_matches) > 1:
            # Decision-20: more than one company carries the exact same
            # name/variant -- never first-wins, always a review question.
            return dict(company=None, link_state='needs_review', link_reason='ambiguous_exact',
                       candidates=[{'company_id': c['id'], 'name': c.get('name'), 'score': 1.0,
                                   'basis': employer_name} for c in exact_matches])
        if exact_matches:
            return dict(company=exact_matches[0], link_state='linked', link_reason='name_exact', candidates=None)
        fuzzy = fuzzy_candidates(companies, employer_name)
        if fuzzy:
            return dict(company=None, link_state='needs_review', link_reason='fuzzy_name', candidates=fuzzy)
        return dict(company=None, link_state='new_company', link_reason='new_company', candidates=None)

    return dict(company=None, link_state='pending', link_reason=None, candidates=None)


def _record_link_evidence(root, company, url, ats_match, domain):
    """Record whatever rung-1/2-shaped evidence this URL carries onto a
    confidently linked company, regardless of which rung actually produced
    the link (e.g. a rung-3 name match still teaches the tenant/domain for
    next time)."""
    if ats_match is not None:
        company = add_identifier(root, company, 'ats_tenant', ats_tenant_value(ats_match), 'scrape')
        company = add_source(root, company, 'ats_feed', _ats_feed_url(ats_match, url), ats_match.provider)
    elif domain:
        company = add_identifier(root, company, 'domain', domain, 'scrape')
        company = add_source(root, company, 'careers_page', url)
    return company


def _tenant_has_other_evidenced_employer(root, ats_match, company):
    """M6: has ANY job actually posted under this exact provider+tenant
    ever evidenced a different employer? Registry membership alone is not
    sharing evidence (decision text); only employer_named_in_posting text
    observed on a real posting counts, so a tenant with zero other postings
    on file is never flagged just because some unrelated company happens to
    exist elsewhere in the vault."""
    if ats_match is None:
        return False
    variants = set(_name_variants(company))
    for job in vault.list_jobs(root):
        if job.get('ats_provider') == ats_match.provider and job.get('ats_tenant') == ats_match.tenant:
            name = job.get('employer_named_in_posting')
            normalized = _normalize_name(name) if name else ''
            if normalized and normalized not in variants and not fuzzy_candidates([company], name):
                return True
    return False


def _create_company(root, name, url, ats_match, domain):
    company = vault.save_company(root, {'name': name, 'name_source': 'auto'})
    return _record_link_evidence(root, company, url, ats_match, domain)


def _job_fields(company, state, reason, candidates):
    review = None
    if state == 'needs_review':
        # M5: a revision token so /resolve-review can reject a stale
        # concurrent submission (one made against a review that has since
        # been resolved or replaced) instead of silently first-winning.
        review = {'candidates': candidates or [], 'at': vault.timestamp(), 'token': uuid.uuid4().hex}
    return dict(company_id=company['id'] if company else None,
               company_link_state=state, company_link_reason=reason, company_review=review)


def resolve_and_link(root, *, url, employer_name=None, fallback_name=None, legacy_hint=None, existing=None):
    """Full ladder entry point.

    existing, when given, is an (company_id, company_link_reason) pair
    describing a link the job ALREADY carries (M1/M2/M3): it takes
    priority over rungs 1-2's own identifier lookup (and over
    legacy_hint), since a job's existing link -- however it was
    established -- must never be silently abandoned for a fresh rungs-1-2
    guess just because this call's own URL lookup doesn't happen to carry
    a matching identifier (e.g. a concurrent owner edit, or a company
    linked by a mechanism that predates this URL's own identifiers).
    Ignored when its company_id is falsy or no longer resolves.

    legacy_hint, when given, is an optional (company, reason) pair the
    caller already found through some pre-identifiers matching mechanism
    of its own (e.g. this project's pre-JOZ-266 name/website matching). It
    is consulted only once rungs 1-2's own identifier lookup finds
    nothing (and existing did not apply), so a persisted identifier always
    wins over it; any link made through it is immediately taught into a
    real identifier (see _record_link_evidence), so later resolutions no
    longer need it.

    Called with employer_name=None and fallback_name=None at stub creation
    time: only rungs 1-2 run (pure, no network), and the result is never a
    review state or a new company -- rungs 3-5 need the posting text
    first, so a miss here is simply 'pending'.

    Called again after fetch/extraction, with employer_name set to
    employer_named_in_posting (the strict, never-guessed signal rungs 3
    and 5 are specified against) and fallback_name set to whatever looser
    company-name signal the job's own `company` field already uses
    (including its pre-existing slug/domain-derived guess, for a posting
    with no real employer signal at all). employer_name alone ever drives
    fuzzy matching or a review flag, so a guess can never manufacture a
    review question or a false staffing/shared-tenant flag; fallback_name
    is consulted only once employer_name has nothing to offer (rungs 1-3
    all miss), and only for an exact-name match or rung-4 creation --
    preserving this project's pre-ladder behavior of always ending up
    linked to *some* company whenever any name signal at all is
    available, now additionally recorded with identifiers/sources.

    All I/O here is local vault reads/writes; no network call is ever made
    (global rule 5).

    Returns a dict ready to merge into the job's save_job fields:
    company_id, company_link_state, company_link_reason, company_review.
    """
    linked_company, linked_reason, ats_match = None, None, None
    if existing and existing[0]:
        linked_company = vault.load_company(root, existing[0])
        linked_reason = existing[1] if linked_company is not None else None
    if linked_company is not None:
        ats_match = url_normalize.detect_ats(url)
    else:
        linked_company, linked_reason, ats_match = resolve_rungs_1_2(root, url)
        if linked_company is None and legacy_hint is not None:
            linked_company, linked_reason = legacy_hint
    domain = None if ats_match is not None else _domain_of(url)

    if employer_name is None and fallback_name is None:
        if linked_company is not None:
            if (linked_reason == 'ats_tenant'
                    and _tenant_has_other_evidenced_employer(root, ats_match, linked_company)):
                return _job_fields(linked_company, 'needs_review', 'shared_tenant', None)
            linked_company = _record_link_evidence(root, linked_company, url, ats_match, domain)
            return _job_fields(linked_company, 'linked', linked_reason, None)
        return _job_fields(None, 'pending', None, None)

    result = resolve_rungs_3_5(root, url=url, employer_name=employer_name,
                               linked_company=linked_company, linked_reason=linked_reason)
    company, state, reason, candidates = (result['company'], result['link_state'],
                                          result['link_reason'], result['candidates'])

    if state == 'pending' and fallback_name:
        exact = find_by_exact_name(vault.list_companies(root), fallback_name)
        if exact is not None:
            company, state, reason = exact, 'linked', 'name_exact'
        else:
            state, reason = 'new_company', 'new_company'

    if state == 'new_company':
        company = _create_company(root, employer_name or fallback_name, url, ats_match, domain)
        state, reason = 'linked', 'new_company'
    elif state == 'linked' and company is not None:
        company = _record_link_evidence(root, company, url, ats_match, domain)
    return _job_fields(company, state, reason, candidates)


def apply_review(root, job, *, company_id=None, create=None):
    """Owner resolves a needs_review job: either picks an existing
    candidate (company_id) or creates a new company (create={'name': ...}).

    Writes the job's extracted employer name as a user-provenanced
    name_variant identifier on the chosen company (owner decision 3.A,
    2026-10-08), so the same fuzzy case never asks twice: the next posting
    naming this same employer text will hit find_by_exact_name via that
    identifier and auto-link with reason name_exact.

    Returns the (possibly newly created) company record; the caller is
    responsible for linking the job to it and clearing the review state.
    """
    if company_id:
        company = vault.load_company(root, company_id)
        if company is None:
            raise ValueError('Company not found.')
    elif create:
        name = (create.get('name') or '').strip()
        if not name:
            raise ValueError('Provide a company name.')
        company = vault.save_company(root, {'name': name, 'name_source': 'owner'})
        # M8: preserve whatever URL-derived identifiers/sources this job's
        # posting already discovered, so the create-new path never leaves
        # the new company without the identifiers a regular rung-4 creation
        # would have taught. Shared-tenant cases never assert exclusive
        # tenant ownership (the ats_tenant identifier is omitted; the
        # feed-level source is still recorded, since that claims no
        # ownership, just "we've seen postings here").
        url = job.get('url') or ''
        ats_match = url_normalize.detect_ats(url)
        domain = None if ats_match is not None else _domain_of(url)
        if ats_match is not None:
            if job.get('company_link_reason') not in ('shared_tenant', 'employer_differs_from_tenant'):
                company = add_identifier(root, company, 'ats_tenant', ats_tenant_value(ats_match), 'scrape')
            company = add_source(root, company, 'ats_feed', _ats_feed_url(ats_match, url), ats_match.provider)
        elif domain:
            company = add_identifier(root, company, 'domain', domain, 'scrape')
            company = add_source(root, company, 'careers_page', url)
    else:
        raise ValueError('Provide company_id or create.')
    employer_name = job.get('employer_named_in_posting')
    if employer_name:
        company = add_identifier(root, company, 'name_variant', employer_name, 'user')
    return company


def rerun(root, job):
    """Re-run the full ladder for an existing job using its stored url and
    employer_named_in_posting (no network I/O; use the /extract endpoint
    to refetch the posting itself first, if that is what is needed).

    Human edits always win (global rule 1): a no-op, returning the current
    state unchanged, whenever ANY of the owner's link-decision group
    (company_id, company_link_state, company_link_reason) carries owner
    provenance -- not only company_id, since an owner can PUT just the
    state or reason alone (M1)."""
    provenance = job.get('field_provenance', {}) or {}
    if any(provenance.get(key) == 'user' for key in ('company_id', 'company_link_state', 'company_link_reason')):
        return dict(company_id=job.get('company_id'), company_link_state=job.get('company_link_state'),
                   company_link_reason=job.get('company_link_reason'), company_review=job.get('company_review'))
    return resolve_and_link(root, url=job.get('url') or '', employer_name=job.get('employer_named_in_posting'),
                            fallback_name=job.get('company'),
                            existing=(job.get('company_id'), job.get('company_link_reason')))
