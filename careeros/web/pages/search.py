"""Editable criteria from the selected vault."""
from flask import current_app
from careeros import vault
from careeros.web.ui import page

EMPTY_STATE = 'No criteria yet — define your next role.'

def build_page():
    data = vault.load_search(current_app.config['VAULT_PATH'])
    return page('Search', 'search', 'search.html', data=data, empty=EMPTY_STATE,
                sections=[('roles', 'Roles'), ('must_haves', 'Must-haves'), ('nice_to_haves', 'Nice-to-haves'), ('avoid', 'Avoid')])
