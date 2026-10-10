"""Editable criteria from the selected vault."""
from flask import current_app
from careeros import vault
from careeros.web.ui import page

EMPTY_STATE = 'No criteria yet — define your next role.'

def page_context(root):
    return criteria_context(vault.load_search(root))

def criteria_context(data):
    return dict(
        data=data,
        empty=EMPTY_STATE,
        sections=[('roles', 'Roles'), ('must_haves', 'Must-haves'), ('nice_to_haves', 'Nice-to-haves'), ('avoid', 'Avoid')],
    )

def build_page():
    root = current_app.config['VAULT_PATH']
    context = page_context(root)
    return page('Search', 'search', 'search.html', **context)
