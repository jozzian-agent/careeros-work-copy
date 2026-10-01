"""Interviews placeholder page."""

from careeros.web.theme import page_shell

EMPTY_STATE = 'Interview preparation lands in a later chunk — upcoming conversations, practice, and follow-up notes.'


def build_page() -> str:
    """Return the complete styled page without reading vault data."""
    body = f"<section class='card empty-state'><h1>Interviews</h1><p class='muted'>{EMPTY_STATE}</p></section>"
    return page_shell('Interviews', 'interviews', body)
