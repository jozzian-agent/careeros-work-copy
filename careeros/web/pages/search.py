"""Editable criteria from the selected vault."""
from careeros import vault

EMPTY_STATE = 'No criteria yet — define your next role.'

def page_context(root):
    return criteria_context(vault.load_search(root))

def criteria_context(data):
    return dict(
        data=data,
        empty=EMPTY_STATE,
        sections=[('roles', 'Roles'), ('must_haves', 'Must-haves'), ('nice_to_haves', 'Nice-to-haves'), ('avoid', 'Avoid')],
    )
