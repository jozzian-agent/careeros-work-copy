"""Company directory and editable profiles.

M2 (CAREER-39): a company record is shared universe, readable by every
user and editable by the admin alone (decision D3). What is private is
what hangs off it here: the open-jobs count on a directory card and the
linked jobs and positions on a profile are read through the session
user's own `vault.Owner`, so one user's board never shows in another's
company page. CAREER-41 adds the notes to the private half: every
signed-in user may add a note to a company, and a company note is
visible to its author alone (the admin included), so `visible_companies`
answers each record with only this reader's own notes.
"""
from flask import abort
from careeros import vault
from org_intake import classify as sectors
from careeros.web.pages.jobs import needs_attention, sector_display

EMPTY_STATE = 'No companies yet — add a job to start your directory.'

# B3 (CAREER-90): why an API-added company was reported missing, recorded
# here because this is the read path it was said to be missing from.
# `vault.visible_companies` has always answered with every company in the
# vault whatever its source, so nothing was filtering one out. What was
# missing was its open jobs: the count below was the reading user's own
# board, so a company whose postings nobody on this board holds read "No
# open jobs" and the tile looked like an empty stub. The count is the
# universe's open jobs now (rule 3), and `docs/surfaces/companies.md`
# carries the confirmation in full.

# enrichment.field_states keys for the two owner-facing classification
# fields. Sector state is recorded under the plural ISIC field name, so
# the page cannot just reuse its own field names here.
FIELD_STATE_KEYS = {'sector': 'sectors', 'size': 'size'}

# B5 (CAREER-92, owner decision 2026-10-19): no company surface asks for
# "Needs your input" any more. The directory's own `needs_attention` mark
# and the profile's one-field `needs_input` ask are gone with the chip,
# the card and the filter that read them, and with them the three helpers
# that only existed to decide when to ask (`field_state`, `field_flagged`,
# `signals_tried`). A missing sector or size reads "Unknown" in the
# Classification section, beside the two things that fix it: Edit
# classification and the existing retry. The Jobs board keeps its own
# chip, which is about a job and not about a company.

# A classification field is owner-set when any of the stored keys behind
# it is: size lives in three (the legacy string plus the derived EU pair),
# sector in two (the legacy string plus the ISIC list).
FIELD_PROVENANCE_KEYS = {'sector': ('sector', 'sectors'),
                         'size': ('size', 'size_range', 'size_class')}

# Enrichment outcomes that mean the signal actually produced the value.
FILLED_OUTCOMES = ('matched', 'filled')

def page_context(root, owner=None):
    # visible_companies, not list_companies: a company the admin retired
    # is gone from their directory, and still on the card list of a user
    # whose own record links it (M2 soft retire).
    #
    # list_universe_jobs, not list_jobs: the open-jobs count is the
    # universe's (B3, see the note at the top of this module).
    return directory_context(vault.list_universe_jobs(root, owner),
                             vault.visible_companies(root, owner),
                             sectors.load_isic_sections())

def directory_context(jobs, entries, isic_sections):
    # Open-jobs count per company, over vault.is_open_job: the one place
    # that says which statuses still count as open, shared with every
    # filter built on this number. B3 (CAREER-90): `jobs` is every job
    # this reader may see in the universe -- their own plus the ownerless
    # ones -- so the number is "open jobs here", not "open jobs here that
    # I happen to hold". Another user's private posting is not counted,
    # because a count is a leak like any other (D3).
    counts = {c.get('id'): sum(j.get('company_id') == c.get('id') and vault.is_open_job(j) for j in jobs)
              for c in entries}
    isic_labels = {section['code']: section['label'] for section in isic_sections}
    # Human sector labels per company, read-time only: the card and filter
    # controls must show ISIC labels, never the bare section codes stored
    # on the record (Section 3's display requirement).
    sector_labels = {c.get('id'): [isic_labels.get(code, code) for code in c.get('sectors', [])]
                     for c in entries}
    # No can_edit_shared here, unlike the profile below: the directory
    # offers no company write at all, so there is nothing on it to hide
    # from a tester and no reason to send the flag.
    return dict(
        entries=entries,
        counts=counts,
        empty=EMPTY_STATE,
        isic_sections=isic_sections,
        sector_labels=sector_labels,
        size_classes=vault.SIZE_CLASSES,
    )

def field_events(company, field):
    """The enrichment events recorded for one classification field."""
    states = (company.get('enrichment') or {}).get('field_states') or {}
    state = states.get(FIELD_STATE_KEYS[field]) or {}
    return [event for event in state.get('events') or [] if isinstance(event, dict)]


def field_value(company, field, isic_labels):
    """Owner-facing value for one classification field, or None.

    Size still prefers the raw range the source reported over the derived
    EU class (legacy `size`, then `size_range`, then `size_class`). The
    directory card no longer does -- since the class-scale rework it reads
    `size_class` only -- so the two surfaces can disagree on a record that
    carries both, which is an open question in
    `docs/surfaces/companies.md`, not a settled match.
    """
    if field == 'sector':
        return sector_display(company, isic_labels)
    for key in ('size', 'size_range', 'size_class'):
        value = (company.get(key) or '').strip() if isinstance(company.get(key), str) else company.get(key)
        if value:
            return value
    return None


def field_source(company, field):
    """Where the stored value came from: 'user' when the owner set it,
    otherwise the last enrichment signal that actually produced it, or
    None when nothing on the record says."""
    provenance = company.get('field_provenance') or {}
    if any(provenance.get(key) == 'user' for key in FIELD_PROVENANCE_KEYS[field]):
        return 'user'
    filled = [event.get('signal') for event in field_events(company, field)
              if event.get('outcome') in FILLED_OUTCOMES and event.get('signal')]
    return filled[-1] if filled else None


def linked_jobs(jobs, identifier):
    return [{'id': job.get('id'), 'title': job.get('title'), 'status': job.get('status')}
            for job in jobs if job.get('company_id') == identifier]


def linked_experiences(experiences, identifier):
    """Linked positions in the same shape as the job list, so the page
    renders both with one component. An experience has no status field;
    its equivalent is whether the owner still holds the role."""
    return [{'id': exp.get('id'), 'title': exp.get('title'),
             'status': 'present' if exp.get('end') == 'present' else 'past'}
            for exp in experiences if exp.get('company_id') == identifier]


def detail_context(root, identifier, owner=None, can_edit_shared=True):
    company = vault.may_see_company(root, identifier, owner)
    if company is None:
        abort(404)
    # list_jobs, not list_universe_jobs: the profile's job section says My
    # Jobs and means it (B3), so it stays this reader's own board -- which
    # since CAREER-72/74 also means a universe-only pool posting at this
    # company is not listed here, while the directory card's open-jobs
    # chip does count it. The two numbers answer two different questions
    # and the directory note in this module's header says so.
    return company_context(company, vault.list_jobs(root, owner),
                           vault.list_experiences(root, owner),
                           sectors.load_isic_sections(), can_edit_shared)

def company_context(company, jobs, experiences, isic_sections, can_edit_shared=True):
    identifier = company['id']
    isic_labels = {s['code']: s['label'] for s in isic_sections}
    # Same read-time label mapping as the directory card (page_context):
    # the detail page shows human labels, never bare section codes.
    sector_labels = [isic_labels.get(code, code) for code in company.get('sectors', [])]
    # job_cards.html is shared with the board; every entry it renders must
    # carry needs_attention so data-needs is truthful here too (audit B).
    job_entries = [j | {'needs_attention': needs_attention(j)}
                   for j in jobs if j.get('company_id') == identifier]
    return dict(
        company=company,
        sector_labels=sector_labels,
        # entries stays the full job records: job_cards.html and the board
        # renderer read them. jobs is the canvas list (title plus status),
        # which is all the detail page itself needs.
        entries=job_entries,
        jobs=linked_jobs(jobs, identifier),
        experiences=linked_experiences(experiences, identifier),
        # The owner's notes, in the same shape and from the same reader
        # the Job page uses: one notes surface, not two.
        notes=vault.notes_view(company),
        # B5: a field with no value sends null and the page reads it as
        # "Unknown" beside the two things that fix it. There is no
        # `needs_input` key any more, and no judgement here about whether
        # the gap is worth asking about: an unknown sector is an unknown
        # sector whether or not a signal has been tried.
        classification={field: {'value': field_value(company, field, isic_labels),
                                'source': field_source(company, field)}
                        for field in ('sector', 'size')},
        companies={identifier: company},
        isic_sections=isic_sections,
        size_classes=vault.SIZE_CLASSES,
        kinds=vault.KINDS,
        # M2 (D3): the company itself is shared and the admin alone edits
        # it, so Edit company, Delete, Edit classification, Try again and
        # the notes controls are offered only when this is true. The
        # linked lists above are already this user's own records.
        can_edit_shared=can_edit_shared,
    )
