"""Experience library, detail and shared add/edit form.

M2 (CAREER-39): an experience belongs to one user (decision D3), so
every read here takes the session user's `vault.Owner` and somebody
else's position answers 404, the same as one that is not there.
"""
from flask import abort, current_app
from markupsafe import Markup
from careeros import users, vault
from careeros.web.markdown import render_markdown
from careeros.web.ui import page

EMPTY_STATE = 'No positions yet — add your first one'

def get(root, identifier, owner=None):
    data = vault.load_experience(root, identifier, owner)
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

def _companies_by_id(root, owner=None):
    # The reader's own view of the shared half: a position linked to a
    # company the admin retired still resolves its label for the user
    # who owns that position (M2 soft retire).
    return {c['id']: c for c in vault.visible_companies(root, owner)}

def page_context(root, owner=None):
    return library_context(vault.list_experiences(root, owner), _companies_by_id(root, owner),
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

def detail_context(root, identifier, owner=None):
    return experience_context(get(root, identifier, owner), _companies_by_id(root, owner),
                              vault.tag_label_map(root))

def experience_context(data, companies_by_id, tag_labels):
    return dict(
        exp=data,
        label=company_label(data, companies_by_id),
        companies=companies_by_id,
        tag_labels=tag_labels,
        markdown=Markup(render_markdown(data.get('detail', ''))),
    )

def form_context(root, identifier=None, owner=None, can_edit_shared=True):
    data = get(root, identifier, owner) if identifier else {}
    return editor_context(data, vault.visible_companies(root, owner), vault.load_tags(root),
                          can_edit_shared)

def editor_context(data, companies, tags, can_edit_shared=True):
    # can_edit_shared (M2, D3): whether this user may add a value to the
    # shared tag vocabulary. The form offers the propose-a-new-tag
    # control only when they may; picking a registered tag is a write to
    # the position itself and stays open to everybody.
    return dict(exp=data, companies=companies, tags=tags, can_edit_shared=can_edit_shared)

def form(identifier=None):
    root = current_app.config['VAULT_PATH']
    user = users.session_user(root)
    context = form_context(root, identifier, users.owner(user), users.is_admin(user))
    return page('Edit position' if identifier else 'Add position', 'experiences', 'experience_form.html', **context)
