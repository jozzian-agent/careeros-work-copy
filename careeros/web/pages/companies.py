"""Company directory and editable profiles."""
from flask import abort
from careeros import vault
from org_intake import classify as sectors
from careeros.web.pages.jobs import needs_attention

EMPTY_STATE = 'No companies yet — add a job to start your directory.'

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
        entries=job_entries,
        experiences=[e for e in experiences if e.get('company_id') == identifier],
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
