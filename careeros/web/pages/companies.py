"""Company directory and editable profiles."""
from flask import abort, current_app
from markupsafe import Markup
from careeros import vault
from careeros.web.ui import page
from careeros.web.markdown import render_markdown

EMPTY_STATE = 'No companies yet — add a job to start your directory.'

def build_page():
    root = current_app.config['VAULT_PATH']
    jobs = vault.list_jobs(root)
    entries = vault.list_companies(root)
    counts = {c.get('id'): sum(j.get('company_id') == c.get('id') and j.get('status') not in ('rejected', 'closed', 'withdrawn') for j in jobs) for c in entries}
    return page('Companies', 'companies', 'companies.html', entries=entries, counts=counts, empty=EMPTY_STATE)

def detail(identifier):
    root = current_app.config['VAULT_PATH']
    company = vault.load_company(root, identifier)
    if company is None:
        abort(404)
    return page(company.get('name', 'Company'), 'companies', 'company_detail.html', company=company, entries=[j for j in vault.list_jobs(root) if j.get('company_id') == identifier], companies={identifier:company}, markdown=Markup(render_markdown(company.get('notes', ''))))
