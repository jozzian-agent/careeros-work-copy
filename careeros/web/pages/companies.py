"""Companies placeholder page."""

from careeros.web.theme import page_shell

EMPTY_STATE = 'Company profiles land in a later chunk — research, notes, and opportunities.'


def build_page() -> str:
    """Return the complete styled page without reading vault data."""
    body = f"<section class='card empty-state'><h1>Companies</h1><p class='muted'>{EMPTY_STATE}</p></section>"
    return page_shell('Companies', 'companies', body)
