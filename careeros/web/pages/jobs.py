"""Posting board and job detail."""
import re

from flask import abort, current_app
from careeros import history, vault, watcher
from org_intake import classify as sectors
from careeros.web.ui import page

EMPTY_STATE = 'No jobs yet — paste a posting link to get started.'

def needs_attention(job):
    """M1 audit batch B: a job needs owner action when the company link is
    unresolved or ingest got stuck, mirroring company_link_state/ingest_state
    as already stored on the entry dict (no separate recompute in JS)."""
    return (job.get('company_link_state') == 'needs_review'
            or job.get('ingest_state') in ('fetch_failed', 'extract_failed'))

def page_context(root):
    return board_context(vault.list_jobs(root), vault.list_companies(root),
                         vault.function_label_map(root))

def board_context(entries, companies, function_labels):
    """Build the board context without I/O or mutating input records."""
    function_options = sorted(((fid, info['label']) for fid, info in function_labels.items()),
                              key=lambda pair: pair[1].casefold())
    entries = [job | {'needs_attention': needs_attention(job)} for job in entries]
    return dict(
        entries=entries,
        companies={c['id']: c for c in companies if 'id' in c},
        statuses=vault.STATUSES,
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
    context = page_context(root)
    return page('Jobs', 'jobs', 'jobs.html', **context)

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


def detail_context(root, identifier, llm_pending=False):
    job = vault.load_job(root, identifier)
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

def taxonomy_context(root, identifier):
    """Taxonomy sub-page (approved wireframe 2026-10-07): function (ESCO),
    the company's ISIC sectors read-only, and controlled-vocabulary tags.
    No provenance display per the owner's decision."""
    job = vault.load_job(root, identifier)
    if job is None:
        abort(404)
    return classification_context(
        job, vault.load_company(root, job.get('company_id')),
        vault.function_label_map(root), sectors.load_isic_sections(),
        vault.tag_label_map(root), vault.load_tags(root))

def classification_context(job, company, function_labels, isic_sections, tag_labels, tag_registry):
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
    )

def taxonomy(identifier):
    root = current_app.config['VAULT_PATH']
    context = taxonomy_context(root, identifier)
    return page(f"Classification · {context['job'].get('title', 'Job')}", 'jobs', 'job_taxonomy.html', **context)
