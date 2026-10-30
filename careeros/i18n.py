"""The server side of the one string catalog: read it, substitute into it.

WHAT THIS MODULE IS FOR. User-visible English lives in
`frontend/src/i18n/en.json`, one flat JSON object of dot-namespaced keys.
React will read that file through react-intl, and this module is how the
Python side reads the very same file, so a string has one home rather
than one per language the app is written in.

Nothing in the web app calls anything here yet. This is the library and
its tests; the Flask wiring, and the move of the existing strings into
the catalog, are later PRs.

PLACEHOLDERS ONLY, AND WHY. `tr` substitutes with `str.format`, so a
value may carry `{var}` placeholders and nothing else. An ICU
MessageFormat construct, meaning a plural, a select, or a number or date
skeleton, is forbidden in the catalog because `str.format` cannot parse
one: it would raise in the middle of a page render instead of reading as
a bad translation. `scripts/check_i18n.py` is the gate that keeps such a
value out of the file, and CI runs it on every pull request.
`frontend/src/i18n/README.md` states the rule for both sides.

THE TWO FAILURES ARE DELIBERATELY DIFFERENT SHAPES, because they are
different facts:

- A key that is not in the catalog is a typo in our own code. It logs a
  warning and returns the key, so a mistyped key in a mail body sends a
  mail with an ugly string in it rather than failing the send.
- A key whose placeholders do not match the variables given is a caller
  that cannot be rendered at all. It raises `CatalogError`, naming the
  key. The raw pattern is never returned instead, because a page
  showing `Hello {name}` to a person is a defect that hides itself.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from types import MappingProxyType

_logger = logging.getLogger(__name__)

#: The catalog the front end owns, addressed from this file and never
#: from the working directory: gunicorn, pytest and a cron job all run
#: from somewhere different, and the file is in the same place for all
#: three.
CATALOG_PATH = Path(__file__).resolve().parents[1] / 'frontend' / 'src' / 'i18n' / 'en.json'


class CatalogError(ValueError):
    """A value could not be rendered with the variables it was given.

    Carries the key, because the pattern and the missing variable are
    both useless without knowing which string asked for them.
    """


#: One parsed catalog per path per process. The catalog ships with the
#: application and does not change per owner or per request, so re-reading
#: it per call would buy nothing. Keyed by path rather than held as a
#: single value so a test can load a fixture catalog without evicting, or
#: inheriting, the real one.
_cache = {}


def _read(path):
    """Parse one catalog file into a read-only mapping.

    Read-only because the cache hands the same object to every caller,
    and a caller that edited it would be editing the catalog for the
    whole process.
    """
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'{path}: a string catalog must be a JSON object')
    for key, value in data.items():
        if not isinstance(value, str):
            raise ValueError(f'{path}: key {key!r} holds {type(value).__name__}, '
                             'and every catalog value must be a string')
    return MappingProxyType(data)


def load_catalog(path=None):
    """The catalog as a mapping of key to pattern, parsed once per path.

    `path` is for tests and for the check script. Left out, it reads the
    one real catalog at `CATALOG_PATH`.
    """
    resolved = str(Path(path) if path is not None else CATALOG_PATH)
    if resolved not in _cache:
        _cache[resolved] = _read(resolved)
    return _cache[resolved]


def clear_cache():
    """Forget every parsed catalog. For a test that edits a file in place."""
    _cache.clear()


def tr(key, **variables):
    """The string for `key`, with `{var}` placeholders substituted.

    A missing key logs a warning and comes back as the key itself. A
    pattern that cannot be filled with these variables raises
    `CatalogError`.
    """
    pattern = load_catalog().get(key)
    if pattern is None:
        _logger.warning('i18n: no catalog entry for key %r, using the key itself', key)
        return key
    try:
        return pattern.format(**variables)
    except (KeyError, ValueError, IndexError) as error:
        given = ', '.join(sorted(variables)) or 'none'
        raise CatalogError(
            f'i18n key {key!r} could not be rendered: {type(error).__name__}: {error}. '
            f'Variables given: {given}') from error
