"""Editable criteria from the selected vault."""
from careeros import vault

EMPTY_STATE = 'No criteria yet — define your next role.'

def page_context(root, owner):
    """The Search page for one signed-in user.

    `owner` is required: criteria belong to one user (2026-10-27 privacy
    audit, finding 4) and this page is the only reader of them besides
    the API route itself.
    """
    return criteria_context(vault.load_search(root, owner))

def criteria_context(data):
    return dict(
        data=data,
        empty=EMPTY_STATE,
        sections=[('roles', 'Roles'), ('must_haves', 'Must-haves'), ('nice_to_haves', 'Nice-to-haves'), ('avoid', 'Avoid')],
    )
