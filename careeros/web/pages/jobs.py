"""Posting board and job detail.

M2 (CAREER-39): every job read here is scoped to one user. The `owner`
argument is a `vault.Owner` and comes from the session, so the board, the
detail page and the classification sub-page all answer with that user's
own jobs and nothing else (decision D3).
"""
from datetime import date
import re

from flask import abort, current_app
from careeros import history, users, vault, watcher
from org_intake import classify as sectors
from careeros.web.ui import page

# The section is My Jobs since M2 (decision D10), so its empty state
# names it that way rather than saying "no jobs yet" about a page the
# owner now reads as theirs.
EMPTY_STATE = 'My Jobs is empty — paste a posting link to get started.'

# How long a closed posting sits on a job the owner has not applied to
# before the board asks about it (D7).
CLOSED_REVIEW_DAYS = 7

# The statuses the closed-posting question applies to: every open status
# before Applied. A job in Applied or later keeps the neutral chip,
# because a closed posting does not end an application. Read off the one
# status ladder rather than typed out again here.
BEFORE_APPLIED = vault.OPEN_STATUSES[:vault.OPEN_STATUSES.index('applied')]

# The statuses that count as having applied, for "Your search so far".
# Won counts too: a job can be dropped straight onto the Won lane from
# Interested, and you cannot win a job you never applied to.
APPLIED_OR_LATER = tuple(vault.OPEN_STATUSES[vault.OPEN_STATUSES.index('applied'):]) + ('won',)

def needs_attention(job):
    """M1 audit batch B: a job needs owner action when the company link is
    unresolved or ingest got stuck, mirroring company_link_state/ingest_state
    as already stored on the entry dict (no separate recompute in JS).

    2026-10-18 adds the third case the owner found: a posting whose
    heading was its careers page and not a role, so the job carries a
    provisional title and nothing but the owner can give it the real one.
    That is recorded as a `field_status_reason` for `title`, and the
    vault keeps such a reason only while the field is still
    not_evidenced, so the ask disappears by itself the moment anything
    fills it (careeros/intake._extract, careeros/vault._save_record).

    This is also what the board card's one "Needs your input" chip reads,
    so the chip and the "Needs attention" filter cannot disagree about
    which jobs they mean.
    """
    return (job.get('company_link_state') == 'needs_review'
            or job.get('ingest_state') in ('fetch_failed', 'extract_failed')
            or 'title' in (job.get('field_status_reason') or {}))

def days_closed(job, today):
    """Whole days since this job posting was found gone, or None when the
    record does not say. A record can carry the flag without a date (a
    posting gone before the date was stored), and a week cannot be
    measured from a date that is not there."""
    try:
        found = date.fromisoformat(str(job.get('closed_at')))
    except (TypeError, ValueError):
        return None
    return (today - found).days


def closed_review(entries, today):
    """The jobs the closed-postings banner and its review popup ask about:
    the owner has not applied, the posting has been gone for more than a
    week, and they have not already kept the job.

    This is also the set whose card shows the warning chip rather than the
    neutral one, so the front end reads one list for both and the chip can
    never disagree with the banner. `days_closed` rides along because the
    threshold is decided here: a card that says "Closed 8 days ago" and a
    banner that says "over a week" have to be counting the same days.
    """
    rows = []
    for job in entries:
        if (job.get('status') not in BEFORE_APPLIED or not job.get('closed')
                or job.get('closed_reviewed_at')):
            continue
        days = days_closed(job, today)
        if days is None or days <= CLOSED_REVIEW_DAYS:
            continue
        rows.append({'id': job.get('id'), 'closed_at': job.get('closed_at'), 'days_closed': days})
    return rows


def statuses_held(job):
    """Every status this job is recorded as having held: the one it is in
    now, plus both sides of every status move in its history.

    Both sides, because a move records where the job came from as well as
    where it went, so one event is evidence of two statuses. The current
    status is counted too: a job can be written straight into a status
    without a move ever being recorded.
    """
    held = {job.get('status') or 'new'}
    for event in job.get('history') or []:
        if isinstance(event, dict) and event.get('event') == 'status_changed':
            held.update(part.strip() for part in str(event.get('detail') or '').split('->') if part.strip())
    return held


def search_so_far(entries):
    """The counts the Ended lane heads with (D7).

    Every count is over history rather than over where a job sits now, so
    an ended job still counts for the interview it got. The most common
    reason to stop is left out entirely while no stopped job carries one:
    a line reading "Most common reason to stop: none" would be a fact
    about the field rather than about the search. Ties go to the earlier
    reason in the suggestion list, so the same records always report the
    same answer.
    """
    held = [statuses_held(job) for job in entries]
    applied = set(APPLIED_OR_LATER)
    stats = dict(
        applied_to=sum(bool(statuses & applied) for statuses in held),
        interviews=sum('interviewing' in statuses for statuses in held),
        offers=sum('offer' in statuses for statuses in held),
    )
    counts = {}
    for job in entries:
        reason = job.get('end_reason')
        if job.get('status') == 'stopped' and reason:
            counts[reason] = counts.get(reason, 0) + 1
    if counts:
        order = {reason: index for index, reason in enumerate(vault.STOPPED_REASONS)}
        top = max(counts, key=lambda reason: (counts[reason], -order.get(reason, len(order))))
        stats['top_stopped_reason'] = {'reason': top, 'count': counts[top]}
    return stats


def page_context(root, owner=None):
    return board_context(vault.list_jobs(root, owner), vault.visible_companies(root, owner),
                         vault.function_label_map(root))

def board_context(entries, companies, function_labels, today=None):
    """Build the board context without I/O or mutating input records."""
    today = today or date.today()
    function_options = sorted(((fid, info['label']) for fid, info in function_labels.items()),
                              key=lambda pair: pair[1].casefold())
    entries = [job | {'needs_attention': needs_attention(job)} for job in entries]
    return dict(
        entries=entries,
        companies={c['id']: c for c in companies if 'id' in c},
        statuses=vault.STATUSES,
        # The words every surface shows for a status, and which of them
        # end a job, both from the one vocabulary in the vault: the board
        # columns are the open statuses in order and the Ended lane holds
        # the rest, so neither list is computed in JS.
        status_labels=vault.STATUS_LABELS,
        ended_statuses=vault.ENDED_STATUSES,
        # The split the filter bar reads as "N open · M ended".
        counts=dict(open=sum(vault.is_open_job(job) for job in entries),
                    ended=sum(not vault.is_open_job(job) for job in entries)),
        # The suggestions the ending popup offers, per ended status, and
        # the title the free text beside them is saved under as a note.
        end_reasons={status: list(reasons) for status, reasons in vault.END_REASONS.items()},
        end_note_title=vault.END_NOTE_TITLE,
        closed_review=closed_review(entries, today),
        search_so_far=search_so_far(entries),
        empty=EMPTY_STATE,
        function_options=function_options,
        # The one company-size scale, for the board's Company size facet.
        # Sent here rather than hard-coded in JS so the board and the
        # Companies directory read the same vocabulary from the same place
        # (owner decision 2026-10-15: classes, never a numeric range).
        size_classes=vault.SIZE_CLASSES,
    )

def company_summaries(companies, isic_sections):
    """One board-card-sized summary per company, keyed by id: a display
    name, an industry label (the company's FIRST ISIC sector, human-
    labeled, None when it has no sectors or an unknown code), and its raw
    size_class (micro/small/medium/large, may be None). Pure and
    testable without I/O so the board route's shape can be pinned without
    a vault fixture."""
    isic_labels = {section['code']: section['label'] for section in isic_sections}
    summaries = {}
    for key, company in companies.items():
        sector_codes = company.get('sectors') or []
        industry = isic_labels.get(sector_codes[0]) if sector_codes else None
        summaries[key] = {'name': company.get('name'), 'industry': industry, 'size_class': company.get('size_class')}
    return summaries

def build_page():
    root = current_app.config['VAULT_PATH']
    context = page_context(root, users.owner(users.session_user(root)))
    return page('My Jobs', 'jobs', 'jobs.html', **context)

def show_remote_chip(job):
    """Show the remote label only when the location does not already include it.

    Word-boundary match so town names merely containing the letters
    (e.g. Remotedorf) still get the chip.
    """
    return bool(job.get("remote_ok")) and not re.search(r"\bremote\b", (job.get("location") or "").casefold())


FIT_PLACEHOLDER = 'Not calculated yet'

# A summary this short is a legitimate one-liner even when the posting
# happens to open with the same words; below it there is nothing to
# suppress and no confident way to tell a copy from a coincidence.
SUMMARY_COPY_MIN = 40


def normalize_space(text):
    """Collapse every run of whitespace to one space and trim."""
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def summary_is_copy(summary, description):
    """True when the stored summary is just the opening of the posting
    rather than a summary of it.

    Extraction sometimes stores the first paragraph verbatim; rendering
    that above the same text as an AI-made summary is a lie about both the
    work and the content. Whitespace-insensitive so a reflowed copy still
    counts.
    """
    text, source = normalize_space(summary), normalize_space(description)
    if len(text) < SUMMARY_COPY_MIN or not source:
        return False
    return source.startswith(text)


def sector_display(record, isic_labels):
    """Owner-facing sector for a job or company record, or None.

    Prefers the legacy free-text sector the extractor writes, and falls
    back to the first ISIC section the record is classified under (human
    label, bare code when the code is unknown), so a record classified
    only by code does not read as unclassified.
    """
    record = record or {}
    legacy = (record.get('sector') or '').strip()
    if legacy:
        return legacy
    codes = record.get('sectors') or []
    return isic_labels.get(codes[0], codes[0]) if codes else None


def classification_sector(job, company, isic_labels):
    """Sector for the job detail page, with where it came from.

    The job's own sector wins; a job with none inherits the linked
    company's, labeled as such. Before this the page read only the job
    field and showed nothing for the common case of a posting that never
    named a sector but whose company is classified.
    """
    for record, source in ((job, 'job'), (company, 'company')):
        value = sector_display(record, isic_labels)
        if value:
            return {'value': value, 'source': source}
    return {'value': None, 'source': None}


def job_needs_input(job):
    """The ONE thing the page asks the owner for, or None.

    At most one ask is rendered, so precedence is decided here rather
    than by section order in the UI: an unresolved company link blocks
    the record's identity, which matters more than a posting whose text
    never arrived. Review candidates pass through as stored, however many
    there are.

    The link state alone decides the company ask. A needs_review record
    whose review block is missing is still a record whose company is
    unresolved, so it must raise the company ask with a null review (the
    page then offers creating a company) rather than fall through to a
    read failure, which is not what the owner has to decide.

    Stored posting text settles a failed fetch and not a failed
    extraction. Text that arrived is all a fetch was ever for, so there is
    nothing left to ask. An extraction that failed read that same text and
    still produced no details, and nothing moves that on again by itself,
    so the ask stands however much text is stored.
    """
    if job.get('company_link_state') == 'needs_review':
        return {'kind': 'company', 'review': job.get('company_review')}
    description = (job.get('description') or '').strip()
    state = job.get('ingest_state')
    if state == 'extract_failed' or (state == 'fetch_failed' and not description):
        return {'kind': 'read_failed',
                'error_reason': (job.get('ingest_error') or {}).get('reason')}
    return None


def detail_context(root, identifier, llm_pending=False, owner=None):
    job = vault.load_job(root, identifier, owner)
    if job is None:
        abort(404)
    return job_context(job, vault.load_company(root, job.get('company_id')),
                       vault.function_label_map(root), llm_pending,
                       isic_sections=sectors.load_isic_sections())

def job_context(job, company, function_labels, llm_pending=False, isic_sections=None):
    """Build detail data from an explicit record snapshot."""
    description = job.get('description') or ''
    isic_labels = {s['code']: s['label'] for s in isic_sections or []}
    summary = job.get('summary') or ''
    return dict(
        job=job,
        show_remote_chip=show_remote_chip(job),
        watch_eligible=watcher.eligible(job),
        watch_reason=watcher.NOT_WATCHED_REASON,
        company=company,
        statuses=vault.STATUSES,
        status_labels=vault.STATUS_LABELS,
        function_labels=function_labels,
        # The owner's notes, as the list the Notes section renders. The
        # `markdown` key this replaces rendered the single legacy notes
        # string to HTML; nothing renders notes as HTML now, and a note
        # body is the plain text the owner typed into the note popup.
        notes=vault.notes_view(job),
        has_description=bool(description.strip()),
        llm_pending=llm_pending,
        # Owner-facing history: labels and visibility come from the
        # registry, never from the raw event types on the record.
        history=history.resolve(job.get('history')),
        classification=dict(
            sector=classification_sector(job, company, isic_labels),
            function=job.get('function') or [],
            tags=job.get('tags') or [],
        ),
        needs_input=job_needs_input(job),
        # True while the posting is still on its way in: the extractor
        # running in this process, or a record parked in one of the two
        # intake states that has not reached a result yet. A stub whose
        # fetch never returned and a fetched posting whose extraction was
        # lost to a restart are both still arriving, so the page says so
        # instead of claiming the posting was never read.
        reading=bool(llm_pending) or job.get('ingest_state') in ('stub', 'fetched'),
        # None when the stored summary is a copy of the posting's opening:
        # the page then shows the posting itself rather than the same text
        # twice under an AI-made label.
        summary_effective=None if summary_is_copy(summary, description) else summary,
        # Fit scoring is not built. The page says so instead of showing an
        # empty control that looks like it is waiting for input.
        fit=None,
        fit_placeholder=FIT_PLACEHOLDER,
    )

def taxonomy_context(root, identifier, owner=None, can_edit_shared=True):
    """Taxonomy sub-page (approved wireframe 2026-10-07): function (ESCO),
    the company's ISIC sectors read-only, and controlled-vocabulary tags.
    No provenance display per the owner's decision."""
    job = vault.load_job(root, identifier, owner)
    if job is None:
        abort(404)
    return classification_context(
        job, vault.load_company(root, job.get('company_id')),
        vault.function_label_map(root), sectors.load_isic_sections(),
        vault.tag_label_map(root), vault.load_tags(root), can_edit_shared)

def classification_context(job, company, function_labels, isic_sections, tag_labels, tag_registry,
                           can_edit_shared=True):
    function_options = sorted(((fid, info['label']) for fid, info in function_labels.items()),
                              key=lambda pair: pair[1].casefold())
    isic_labels = {s['code']: s['label'] for s in isic_sections}
    return dict(
        job=job,
        company=company,
        function_options=function_options,
        function_labels=function_labels,
        isic_labels=isic_labels,
        tags=job.get('tags') or [],
        tag_labels=tag_labels,
        tag_registry=tag_registry,
        # M2 (D3): whether this user may add a value to the shared tag
        # vocabulary. The page offers the propose-a-new-tag control only
        # when they may, rather than leaving a button that answers 403.
        can_edit_shared=can_edit_shared,
    )

def taxonomy(identifier):
    root = current_app.config['VAULT_PATH']
    user = users.session_user(root)
    context = taxonomy_context(root, identifier, users.owner(user), users.is_admin(user))
    return page(f"Classification · {context['job'].get('title', 'Job')}", 'jobs', 'job_taxonomy.html', **context)
