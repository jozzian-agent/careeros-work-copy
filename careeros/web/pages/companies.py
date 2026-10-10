"""Company directory and editable profiles."""
from flask import abort, current_app
from careeros import sectors, vault
from careeros.web.pages.jobs import needs_attention
from careeros.web.ui import page

EMPTY_STATE = 'No companies yet — add a job to start your directory.'

def build_page():
    root = current_app.config['VAULT_PATH']
    jobs = vault.list_jobs(root)
    entries = vault.list_companies(root)
    counts = {c.get('id'): sum(j.get('company_id') == c.get('id') and j.get('status') not in ('rejected', 'closed', 'withdrawn') for j in jobs) for c in entries}
    isic_sections = sectors.load_isic_sections()
    isic_labels = {section['code']: section['label'] for section in isic_sections}
    # Human sector labels per company, read-time only: the card and filter
    # controls must show ISIC labels, never the bare section codes stored
    # on the record (Section 3's display requirement).
    sector_labels = {c.get('id'): [isic_labels.get(code, code) for code in c.get('sectors', [])]
                     for c in entries}
    return page('Companies', 'companies', 'companies.html', entries=entries, counts=counts, empty=EMPTY_STATE,
                isic_sections=isic_sections, sector_labels=sector_labels, size_classes=vault.SIZE_CLASSES)

def detail(identifier):
    root = current_app.config['VAULT_PATH']
    company = vault.load_company(root, identifier)
    if company is None:
        abort(404)
    isic_labels = {s['code']: s['label'] for s in sectors.load_isic_sections()}
    # Same read-time label mapping as the directory card (build_page):
    # the detail page shows human labels, never bare section codes.
    sector_labels = [isic_labels.get(code, code) for code in company.get('sectors', [])]
    # job_cards.html is shared with the board; every entry it renders must
    # carry needs_attention so data-needs is truthful here too (audit B).
    job_entries = [j for j in vault.list_jobs(root) if j.get('company_id') == identifier]
    for job in job_entries:
        job['needs_attention'] = needs_attention(job)
    return page(company.get('name', 'Company'), 'companies', 'company_detail.html', company=company,
                sector_labels=sector_labels,
                entries=job_entries,
                experiences=[e for e in vault.list_experiences(root) if e.get('company_id') == identifier],
                companies={identifier: company}, isic_sections=sectors.load_isic_sections(),
                size_classes=vault.SIZE_CLASSES, kinds=vault.KINDS)

def taxonomy(identifier):
    """Taxonomy sub-page (approved wireframe 2026-10-07): kind, ISIC
    sectors, EU size class, and review flags in one focused editor. No
    provenance display per the owner's decision."""
    root = current_app.config['VAULT_PATH']
    company = vault.load_company(root, identifier)
    if company is None:
        abort(404)
    return page(f"Classification · {company.get('name', 'Company')}", 'companies',
                'company_taxonomy.html', company=company,
                isic_sections=sectors.load_isic_sections(),
                size_classes=vault.SIZE_CLASSES, kinds=vault.KINDS)
