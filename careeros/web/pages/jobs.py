"""Posting board and job detail.

M2 (CAREER-39): every job read here is scoped to one user. The `owner`
argument is a `vault.Owner` and comes from the session, so the board, the
detail page and the classification sub-page all answer with that user's
own jobs and nothing else (decision D3).
"""
from datetime import date
import re

from flask import abort, current_app
from careeros import history, taxonomy, users, vault, watcher
from org_intake import classify as sectors
from careeros.web.ui import page

# The section is My Jobs since M2 (decision D10), so its empty state
# names it that way rather than saying "no jobs yet" about a page the
# owner now reads as theirs.
EMPTY_STATE = 'My Jobs is empty — paste a posting link to get started.'

# B2 (CAREER-89): the All jobs tab's own empty state. It names where a
# job comes from rather than telling the reader to paste one, because the
# tab holds the records the API and the feeds add as well as their own.
UNIVERSE_EMPTY_STATE = 'No jobs here yet — add one by link on My Jobs.'

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

def pending_company_ask(job):
    """Whether a pending company link is something the owner can actually
    settle, which is the one case the page asks them about (owner ruling
    2026-11-01).

    A pending link means the resolution ladder finished without a company
    and without an ambiguity to review, so there is no review block and
    nothing on the page said so: the subtitle link needs a resolved
    company record and the needs_review ask does not cover this state.

    All three conditions are needed. Without an extracted employer name
    there is nothing to ask about, because the owner would be naming a
    company the posting never named. And a job whose extraction has not
    finished may yet resolve itself, so the ask waits for `complete`
    rather than interrupting a reading that is still queued or running,
    or doubling up on a reading that failed.
    """
    return (job.get('company_link_state') == 'pending'
            and bool((job.get('employer_named_in_posting') or '').strip())
            and job.get('ingest_state') == 'complete')


def needs_attention(job):
    """M1 audit batch B: a job needs owner action when the company link is
    unresolved or ingest got stuck, mirroring company_link_state/ingest_state
    as already stored on the entry dict (no separate recompute in JS).

    An unresolved link is either of the two the page asks about: the
    reviewable one, and the pending one `pending_company_ask` settles.

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
            or pending_company_ask(job)
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


def _contract_code(job):
    """The classified contract code of one stored job, or None.

    The classification pipeline stores contract under `values` (a value
    record); the board's Contract facet filters on the plain code, like
    `function` does. Read here rather than in the browser because the
    All jobs tab's entries are projected records with no `values` key --
    the code has to come off the stored record BEFORE that projection
    (see `universe_context`).
    """
    record = (job.get('values') or {}).get('contract') or {}
    value = record.get('value')
    return value if value and value != taxonomy.UNKNOWN else None


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


def page_context(root, owner=None, *, is_admin):
    # list_jobs is the board read: this user's own records that are on a
    # board. The universe-only half (the feed pool's `in_pipeline: false`
    # records, CAREER-72/74) is excluded there rather than here, because
    # every other board reader wants the same answer -- see vault.list_jobs.
    return board_context(vault.list_jobs(root, owner), vault.visible_companies(root, owner),
                         vault.function_label_map(root), is_admin=is_admin)


def universe_context(root, owner=None, *, is_admin):
    """The All jobs payload (B2, CAREER-89).

    The same shape the board reads, over every job that is not private to
    another user (`vault.list_universe_jobs`), plus the one key that tab
    needs: `on_my_board`, which decides whether a card shows its status
    or offers "Add to my jobs". One payload shape, so the tab reuses the
    board's own filter bar and cards instead of a second contract.

    `on_my_board` is the same ownership rule the board itself is scoped
    by, read here rather than in the browser: a client cannot be trusted
    to work out whose record it is holding, and the answer decides which
    action it offers.

    A job this reader does NOT own reaches the response as
    `vault.public_posting_projection` and not whole (owner decision
    2026-10-27, privacy audit finding 1). The tab used to answer with the
    complete record for every entry on it, so an ownerless job's notes,
    note authors, history, custom data, field provenance and workflow
    state were readable by every signed-in user -- and an ownerless
    record is the one the admin's own board inherits, so those were in
    practice the admin's. Their own jobs stay whole: the reader's half of
    this tab is the reader's own data, which is what the board shows them
    anyway.

    The projection happens here, before the board decorations below, so
    nothing downstream can decorate a field the reader may not see; the
    cost is that the posting-count split and the closed-postings day
    count read a projected record as a job with no status, which is the
    right answer for a posting nobody here holds (see `board_context`).
    """
    entries = []
    for job in vault.list_universe_jobs(root, owner):
        # Both halves of the rule, and the second one is what the pool
        # import added (CAREER-72/74): a record is on my board when I own
        # it AND it is a board entry at all. An ownerless pool posting is
        # the admin's by inheritance, so ownership alone would tell them
        # a posting they have never added is already theirs -- and would
        # offer them a status select in place of the one action that
        # actually puts it on their board.
        #
        # Read off the STORED record, before the projection below strips
        # the two fields it answers from.
        mine = owner is None or owner.owns(job)
        if not mine:
            # The Contract facet's code comes off the STORED record: the
            # projection below drops `values`, and a reader who does not
            # own a posting still gets to filter it by contract.
            contract = _contract_code(job)
            job = vault.public_posting_projection(job)
        else:
            contract = _contract_code(job)
        entries.append(job | {'on_my_board': mine and vault.on_board(job),
                              'contract': contract})
    context = board_context(entries, vault.visible_companies(root, owner),
                            vault.function_label_map(root), is_admin=is_admin)
    # The posting text stays out of the LIST payload (owner decision
    # 2026-11-05). A list entry is a card: no list surface renders the
    # description (grep of the frontend confirms AllJobs, JobsBoard,
    # JobCard, jobFilters, CompaniesList, CompanyDetail and every popup
    # read it off the detail payload only), and 800 imported postings
    # carry ~3 MB of text that every All jobs fetch would otherwise
    # ship. `has_description` is the one bit a card could need, computed
    # the same way the detail context computes it (job_context below),
    # so the two surfaces cannot disagree about what "has text" means.
    #
    # AFTER board_context, deliberately: the decorations (needs_attention
    # via company_link_state/ingest_state/field_status_reason, contract
    # via the classified values, closed_review, search_so_far) are all
    # computed off the unstripped entries first, so nothing here can
    # change an answer a decoration gave -- and the tests beside this
    # function pin that the decorations do not read the text anyway.
    # The detail view (view=page -> job_context) is untouched and still
    # returns the full text to a reader allowed to see the record.
    context['entries'] = [
        {k: v for k, v in entry.items()
         if k not in ('description', 'description_structured')}
        | {'has_description': bool((entry.get('description') or '').strip())}
        for entry in context['entries']
    ]
    return context | {'empty': UNIVERSE_EMPTY_STATE}

def board_context(entries, companies, function_labels, today=None, *, is_admin):
    """Build the board context without I/O or mutating input records.

    `is_admin` is whether this reader may write the shared half
    (`server.may_edit_shared`), and it decides one thing here: whether
    needs-attention exists for them at all.

    Owner ruling 2026-11-01: "needs your input should not be displayed
    to non-admins at all. Not on cards, not on the filter and so on."
    Every reason `needs_attention` fires is a company link or a reading
    that only the admin can move on, so for everybody else the flag is
    an alarm about work they cannot do. It is answered False here rather
    than hidden in the browser, because the payload is the authoritative
    answer and a client that ignores a flag is still a client holding
    it. `is_admin` rides along so the filter chip can be left out
    entirely rather than rendered with a count of zero.

    The parameter has no default on purpose. A caller that forgets it
    gets a TypeError, which is the fail-closed answer: the alternative
    is a default, and either default is wrong for half the callers.
    """
    today = today or date.today()
    function_options = sorted(((fid, info['label']) for fid, info in function_labels.items()),
                              key=lambda pair: pair[1].casefold())
    entries = [job | {'needs_attention': needs_attention(job) if is_admin else False,
                      # Set only when the caller has not computed it off
                      # the stored record already (universe_context has,
                      # because the projection drops `values`).
                      'contract': job.get('contract') if 'contract' in job
                      else _contract_code(job)}
               for job in entries]
    # The two payload keys that are about one person's own search rather
    # than about the postings in front of them. `entries` here may be the
    # All jobs tab's, which carries universe-only records (the feed pool,
    # CAREER-72/74): a posting nobody has added to a board has no closed
    # posting to ask about and never applied to anything, so counting one
    # would put 704 imported jobs into "Your search so far" and into the
    # closed-postings banner. My Jobs passes board entries only, so there
    # the filter changes nothing.
    #
    # A projected All jobs entry (`universe_context`, privacy audit
    # finding 1) carries neither `in_pipeline` nor `status`, so it reads
    # as a board entry here and then as a job with nothing applied to and
    # nothing to review: it adds nothing to either number. `counts` below
    # reads it as open for the same reason, which is the right answer --
    # a posting this reader does not hold has no ending of theirs.
    board_entries = vault.board(entries)
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
        closed_review=closed_review(board_entries, today),
        search_so_far=search_so_far(board_entries),
        # Whether needs-attention exists for this reader (owner ruling
        # 2026-11-01, see the docstring). The board reads it to leave the
        # "Needs attention" chip out of the filter bar altogether: a
        # count of zero would still render a chip, and a chip that can
        # never match anything is a control that lies.
        is_admin=bool(is_admin),
        empty=EMPTY_STATE,
        function_options=function_options,
        # The one company-size scale, for the board's Company size facet:
        # `[code, label]` pairs like function_options above. Sent here
        # rather than hard-coded in JS so the board and the Companies
        # directory read the same vocabulary from the same place (owner
        # decision 2026-10-15: classes, never a numeric range), and sent
        # WITH its words since CAREER-71, because the facet used to
        # title-case the code and so offered "Xl" for the class whose
        # label is "Very large".
        size_classes=vault.SIZE_CLASS_OPTIONS,
        # The contract vocabulary for the Contract facet (CAREER-134),
        # [code, label] pairs like size_classes, in the taxonomy's order.
        contract_options=vault.CONTRACT_OPTIONS,
    )

def company_summaries(companies, isic_sections):
    """One board-card-sized summary per company, keyed by id: a display
    name, an industry label (the company's FIRST NOGA sector, human-
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
    # The ONE principal of this request (2026-10-27 privacy audit,
    # finding 8). Reading the user record a second time here was a second
    # chance to get None, and `page_context(root, None)` is an unscoped
    # read of every job in the vault; `request_principal` refuses
    # instead, like the other two page handlers here.
    principal = users.request_principal(root)
    # The one principal, read once and asked both questions (finding 8):
    # whose records this is, and whether needs-attention exists for them.
    context = page_context(root, users.owner(principal), is_admin=users.is_admin(principal))
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
    back to the first NOGA section the record is classified under (human
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


def company_ask(review, company_request=None):
    """The company ask, in the one shape the card renders.

    `review` is the stored review block or None, which is what decides
    whether the card offers candidates to pick from. `request` is absent
    unless the owner has an open request for this job, so a payload
    written before requests existed and a job with no request are the
    same answer.
    """
    ask = {'kind': 'company', 'review': review}
    if company_request is not None:
        ask['request'] = {'name': company_request.get('name'), 'filed': True}
    return ask


def job_needs_input(job, company_request=None):
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

    A pending link `pending_company_ask` accepts raises that same
    null-review company ask, for the same reason: the company is
    unresolved, the posting named an employer, and the create form is
    exactly the choice left. needs_review keeps precedence over it, and
    the read failure under both can never apply to a pending ask, whose
    own condition is an extraction that completed.

    `company_request` is the owner's open request for this job, where
    they have one (`vault.active_company_request`). It rides along on the
    company ask as a `request` block, which is what turns the ask from
    something to answer into something already asked: the name they
    asked for, and the fact that it is filed. The ask itself stays, so
    the page keeps saying the company is unresolved, and the card offers
    no action because there is none left until the request is resolved. A
    request is only ever read onto the ask it belongs to -- a read
    failure is not a company question -- so the block cannot appear
    beside the wrong kind.

    Stored posting text settles a failed fetch and not a failed
    extraction. Text that arrived is all a fetch was ever for, so there is
    nothing left to ask. An extraction that failed read that same text and
    still produced no details, and nothing moves that on again by itself,
    so the ask stands however much text is stored.
    """
    if job.get('company_link_state') == 'needs_review':
        return company_ask(job.get('company_review'), company_request)
    if pending_company_ask(job):
        return company_ask(None, company_request)
    description = (job.get('description') or '').strip()
    state = job.get('ingest_state')
    if state == 'extract_failed' or (state == 'fetch_failed' and not description):
        return {'kind': 'read_failed',
                'error_reason': (job.get('ingest_error') or {}).get('reason')}
    return None


def detail_context(root, identifier, llm_pending=False, owner=None, can_edit_shared=True):
    job = vault.load_job(root, identifier, owner)
    if job is None:
        abort(404)
    # reader_company (CAREER-41): the linked company is shared facts, but
    # its notes are private to their authors -- without this filter the
    # job page would echo every company note to whoever holds the job.
    return job_context(job, vault.reader_company(vault.load_company(root, job.get('company_id')),
                                                 owner),
                       vault.function_label_map(root), llm_pending,
                       isic_sections=sectors.load_sections(),
                       company_request=vault.active_company_request(root, job['id'], owner),
                       can_edit_shared=can_edit_shared)

def job_context(job, company, function_labels, llm_pending=False, isic_sections=None,
                company_request=None, can_edit_shared=True):
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
        needs_input=job_needs_input(job, company_request),
        # M2 (D3): whether this user may write the shared companies
        # record. The company ask offers them the create form when they
        # may and filing a company request when they may not, rather
        # than a button that answers 403. Same flag and same name the
        # company profile and the classification popup already read.
        can_edit_shared=can_edit_shared,
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
    """The job's classification: function (ESCO), the company's NOGA
    sectors read-only, and controlled-vocabulary tags. No provenance
    display per the owner's decision.

    Read by `GET /api/jobs/<id>/taxonomy`, which the React Job detail
    page's Edit classification popup is the one caller of. The Jinja
    sub-page this context was written for (`job_taxonomy.html`) was
    orphaned by that popup and removed 2026-11-01; the context is not,
    because the popup reads exactly this shape."""
    job = vault.load_job(root, identifier, owner)
    if job is None:
        abort(404)
    return classification_context(
        job, vault.reader_company(vault.load_company(root, job.get('company_id')), owner),
        vault.function_label_map(root), sectors.load_sections(),
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
