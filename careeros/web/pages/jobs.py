"""Jobs placeholder page."""

from careeros.web.theme import page_shell

EMPTY_STATE = 'Job board lands in a later chunk — paste-link intake, company profiles, status tracking.'


def build_page() -> str:
    """Return the complete styled page without reading vault data."""
    body = f"<section class='card empty-state'><h1>Jobs</h1><p class='muted'>{EMPTY_STATE}</p></section>"
    return page_shell('Jobs', 'jobs', body)
