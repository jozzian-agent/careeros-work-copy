"""Company directory and editable profiles."""
from flask import abort
from careeros import vault
from org_intake import classify as sectors
from careeros.web.pages.jobs import needs_attention, sector_display

EMPTY_STATE = 'No companies yet — add a job to start your directory.'

# enrichment.field_states keys for the two owner-facing classification
# fields. Sector state is recorded under the plural ISIC field name, so
# the page cannot just reuse its own field names here.
FIELD_STATE_KEYS = {'sector': 'sectors', 'size': 'size'}

# A classification field is owner-set when any of the stored keys behind
# it is: size lives in three (the legacy string plus the derived EU pair),
# sector in two (the legacy string plus the ISIC list).
FIELD_PROVENANCE_KEYS = {'sector': ('sector', 'sectors'),
                         'size': ('size', 'size_range', 'size_class')}

# Enrichment outcomes that mean the signal actually produced the value.
FILLED_OUTCOMES = ('matched', 'filled')

# An outcome meaning the signal never ran, so it is not a source the card
# can claim to have tried.
NOT_ATTEMPTED = 'not-attempted'

def page_context(root):
    return directory_context(vault.list_jobs(root), vault.list_companies(root),
                             sectors.load_isic_sections())

def directory_context(jobs, entries, isic_sections):
    counts = {c.get('id'): sum(j.get('company_id') == c.get('id') and j.get('status') not in ('rejected', 'closed', 'withdrawn') for j in jobs) for c in entries}
    isic_labels = {section['code']: section['label'] for section in isic_sections}
    # Human sector labels per company, read-time only: the card and filter
    # controls must show ISIC labels, never the bare section codes stored
    # on the record (Section 3's display requirement).
    sector_labels = {c.get('id'): [isic_labels.get(code, code) for code in c.get('sectors', [])]
                     for c in entries}
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


def field_state(company, field):
    """The stored enrichment lifecycle state for one field, or None when
    the cascade has never recorded one."""
    states = (company.get('enrichment') or {}).get('field_states') or {}
    return (states.get(FIELD_STATE_KEYS[field]) or {}).get('state')


def signals_tried(company, field):
    """Source names that actually ran for one field, in the order they
    ran, each named once. A signal recorded as not-attempted did not run,
    so the card must not claim it as tried."""
    names = []
    for event in field_events(company, field):
        name = event.get('signal')
        if name and event.get('outcome') != NOT_ATTEMPTED and name not in names:
            names.append(name)
    return names


def field_flagged(company, field):
    """Whether a review flag stands against this field. Every flag in the
    enrichment vocabulary is named '<field>-<problem>'."""
    return any(isinstance(flag, str) and flag.startswith(f'{field}-')
               for flag in company.get('review_flags') or [])


def field_value(company, field, isic_labels):
    """Owner-facing value for one classification field, or None.

    Size prefers the raw range the source reported over the derived EU
    class, matching what the directory card and header already show.
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


def company_needs_input(company, isic_labels):
    """The ONE classification field the page asks the owner for, or None.

    Asking is only honest once automation has run out of ideas: the field
    is empty AND either every signal was tried and found nothing
    (exhausted) or a signal found something the record cannot act on (a
    review flag). A flag alone used to be enough, which asked the owner to
    re-enter a value the record already had -- a stale flag left behind by
    an earlier ambiguity kept the card up forever.
    """
    for field in ('sector', 'size'):
        if field_value(company, field, isic_labels):
            continue
        if field_state(company, field) == 'exhausted' or field_flagged(company, field):
            return {'field': field, 'tried': signals_tried(company, field)}
    return None


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


def detail_context(root, identifier):
    company = vault.load_company(root, identifier)
    if company is None:
        abort(404)
    return company_context(company, vault.list_jobs(root), vault.list_experiences(root),
                           sectors.load_isic_sections())

def company_context(company, jobs, experiences, isic_sections):
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
        classification={field: {'value': field_value(company, field, isic_labels),
                                'source': field_source(company, field)}
                        for field in ('sector', 'size')},
        needs_input=company_needs_input(company, isic_labels),
        companies={identifier: company},
        isic_sections=isic_sections,
        size_classes=vault.SIZE_CLASSES,
        kinds=vault.KINDS,
    )

def taxonomy_context(root, identifier):
    """Taxonomy sub-page (approved wireframe 2026-10-07): kind, ISIC
    sectors, EU size class, and review flags in one focused editor. No
    provenance display per the owner's decision."""
    company = vault.load_company(root, identifier)
    if company is None:
        abort(404)
    return classification_context(company, sectors.load_isic_sections())

def classification_context(company, isic_sections):
    return dict(
        company=company,
        isic_sections=isic_sections,
        size_classes=vault.SIZE_CLASSES,
        kinds=vault.KINDS,
    )
