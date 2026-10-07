"""Experience library, detail and shared add/edit form."""
from flask import abort, current_app
from markupsafe import Markup
from careeros import vault
from careeros.web.markdown import render_markdown
from careeros.web.ui import page

EMPTY_STATE = 'No positions yet — add your first one'

def root():
    return current_app.config['VAULT_PATH']

def get(identifier):
    data = vault.load_experience(root(), identifier)
    if data is None:
        abort(404)
    return data

def company_label(exp, companies_by_id):
    """Once company_id is set, the display label always resolves live from
    the linked company record; the cached free-text company field is used
    only while company_id is still null, so a company rename never needs a
    rewrite pass across every linked experience."""
    if exp.get('company_id') and exp['company_id'] in companies_by_id:
        return companies_by_id[exp['company_id']].get('name') or exp.get('company', '')
    return exp.get('company', '')

def _companies_by_id():
    return {c['id']: c for c in vault.list_companies(root())}

def build_page():
    companies_by_id = _companies_by_id()
    entries = vault.list_experiences(root())
    labels = {exp['id']: company_label(exp, companies_by_id) for exp in entries}
    return page('Experiences', 'experiences', 'experiences.html', entries=entries, empty=EMPTY_STATE,
                companies=companies_by_id, labels=labels, tag_labels=vault.tag_label_map(root()))

def detail(identifier):
    data = get(identifier)
    companies_by_id = _companies_by_id()
    return page(data['title'], 'experiences', 'detail.html', exp=data,
                label=company_label(data, companies_by_id), companies=companies_by_id,
                tag_labels=vault.tag_label_map(root()),
                markdown=Markup(render_markdown(data.get('detail', ''))))

def form(identifier=None):
    data = get(identifier) if identifier else {}
    return page('Edit position' if identifier else 'Add position', 'experiences', 'experience_form.html',
                exp=data, companies=vault.list_companies(root()), tags=vault.load_tags(root()))
