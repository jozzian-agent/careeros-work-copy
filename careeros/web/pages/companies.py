"""Company directory and editable profiles."""
from flask import abort, current_app, request
from markupsafe import Markup
from careeros import sectors, vault
from careeros.web.ui import page
from careeros.web.markdown import render_markdown

EMPTY_STATE = 'No companies yet — add a job to start your directory.'

def build_page():
    root = current_app.config['VAULT_PATH']
    jobs = vault.list_jobs(root)
    all_entries = vault.list_companies(root)
    show_all = request.args.get('show_all') == '1'
    # Aggregate placeholders (e.g. "Early Career") are hidden by default,
    # per Section 1's behavior matrix, with a "Show all" toggle to reveal them.
    entries = all_entries if show_all else [c for c in all_entries if c.get('kind') != 'aggregate']
    counts = {c.get('id'): sum(j.get('company_id') == c.get('id') and j.get('status') not in ('rejected', 'closed', 'withdrawn') for j in jobs) for c in entries}
    isic_sections = sectors.load_isic_sections()
    isic_labels = {section['code']: section['label'] for section in isic_sections}
    # Human sector labels per company, read-time only: the card and filter
    # controls must show ISIC labels, never the bare section codes stored
    # on the record (Section 3's display requirement).
    sector_labels = {c.get('id'): [isic_labels.get(code, code) for code in c.get('sectors', [])]
                     for c in entries}
    return page('Companies', 'companies', 'companies.html', entries=entries, counts=counts, empty=EMPTY_STATE,
                show_all=show_all, hidden_count=len(all_entries) - len(entries),
                isic_sections=isic_sections, sector_labels=sector_labels, size_classes=vault.SIZE_CLASSES)

def detail(identifier):
    root = current_app.config['VAULT_PATH']
    company = vault.load_company(root, identifier)
    if company is None:
        abort(404)
    return page(company.get('name', 'Company'), 'companies', 'company_detail.html', company=company,
                entries=[j for j in vault.list_jobs(root) if j.get('company_id') == identifier],
                experiences=[e for e in vault.list_experiences(root) if e.get('company_id') == identifier],
                companies={identifier: company}, isic_sections=sectors.load_isic_sections(),
                size_classes=vault.SIZE_CLASSES, kinds=vault.KINDS,
                markdown=Markup(render_markdown(company.get('notes', ''))))
