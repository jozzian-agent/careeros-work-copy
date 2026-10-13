"""Experience library, detail and shared add/edit form."""
from flask import abort, current_app
from markupsafe import Markup
from careeros import vault
from careeros.web.markdown import render_markdown
from careeros.web.ui import page

EMPTY_STATE = 'No positions yet — add your first one'

def get(root, identifier):
    data = vault.load_experience(root, identifier)
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

def _companies_by_id(root):
    return {c['id']: c for c in vault.list_companies(root)}

def page_context(root):
    return library_context(vault.list_experiences(root), _companies_by_id(root),
                           vault.tag_label_map(root))

def library_context(entries, companies_by_id, tag_labels):
    labels = {exp['id']: company_label(exp, companies_by_id) for exp in entries}
    return dict(
        entries=entries,
        empty=EMPTY_STATE,
        companies=companies_by_id,
        labels=labels,
        tag_labels=tag_labels,
    )

def detail_context(root, identifier):
    return experience_context(get(root, identifier), _companies_by_id(root),
                              vault.tag_label_map(root))

def experience_context(data, companies_by_id, tag_labels):
    return dict(
        exp=data,
        label=company_label(data, companies_by_id),
        companies=companies_by_id,
        tag_labels=tag_labels,
        markdown=Markup(render_markdown(data.get('detail', ''))),
    )

def form_context(root, identifier=None):
    data = get(root, identifier) if identifier else {}
    return editor_context(data, vault.list_companies(root), vault.load_tags(root))

def editor_context(data, companies, tags):
    return dict(exp=data, companies=companies, tags=tags)

def form(identifier=None):
    root = current_app.config['VAULT_PATH']
    context = form_context(root, identifier)
    return page('Edit position' if identifier else 'Add position', 'experiences', 'experience_form.html', **context)
