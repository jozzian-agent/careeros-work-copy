"""The server side of the one string catalog: read it, substitute into it.

WHAT THIS MODULE IS FOR. User-visible English lives in
`frontend/src/i18n/en.json`, one flat JSON object of dot-namespaced keys.
React reads that file through react-intl, and this module is how the
Python side reads the very same file, so a string has one home rather
than one per language the app is written in.

Nothing in the web app calls anything here yet. This is the library and
its tests; the Flask wiring, and the move of the existing strings into
the catalog, are later PRs.

THE NAMESPACE RULE. The catalog has two kinds of keys:

- `server.*` — strings the server renders: the Flask pages and the body
  of a mail. These are the only keys this module loads or returns.
- everything else — client strings, which React renders through
  react-intl and which may use full ICU MessageFormat (plural, select,
  number, date). The server refuses to touch them, because `tr`
  substitutes with `str.format` and cannot parse an ICU construct; a
  client string rendered server-side would raise in the middle of a
  page render instead of reading as a bad translation.

A `server.*` value may carry plain `{var}` placeholders and nothing
else. `scripts/check_i18n.py` is the gate that holds the namespace to
its grammar, and CI runs it on every pull request.
`frontend/src/i18n/README.md` states the rule for both sides.

THE FAILURES ARE DELIBERATELY DIFFERENT SHAPES, because they are
different facts:

- A key outside the `server.*` namespace is a server-side caller
  reaching for a client string. It raises `CatalogError`, naming the
  key: there is no rendering of it that could ever be right.
- A `server.*` key that is not in the catalog is a typo in our own
  code. It logs a warning and returns the key, so a mistyped key in a
  mail body sends a mail with an ugly string in it rather than failing
  the send.
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

#: The only namespace this module loads. Everything else in the catalog
#: belongs to the client and may use ICU, which `str.format` cannot parse.
SERVER_PREFIX = 'server.'


class CatalogError(ValueError):
    """A value could not be rendered, or was not ours to render.

    Carries the key, because the pattern, the missing variable and the
    wrong namespace are all useless without knowing which string asked.
    """


#: One parsed catalog per path per process. The catalog ships with the
#: application and does not change per owner or per request, so re-reading
#: it per call would buy nothing. Keyed by path rather than held as a
#: single value so a test can load a fixture catalog without evicting, or
#: inheriting, the real one.
_cache = {}
_raw_cache = {}


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


def load_raw_catalog(path=None):
    """Every key of the catalog, server and client alike, parsed once.

    For the check script, which has to see the whole file to gate both
    namespaces. Server code uses `load_catalog`.
    """
    resolved = str(Path(path) if path is not None else CATALOG_PATH)
    if resolved not in _raw_cache:
        _raw_cache[resolved] = _read(resolved)
    return _raw_cache[resolved]


def load_catalog(path=None):
    """The `server.*` keys only, as a mapping of key to pattern.

    Keys outside the namespace are not loaded at all: a server-side
    caller cannot reach a client string even by accident. `path` is for
    tests and for the check script; left out, it reads the one real
    catalog at `CATALOG_PATH`.
    """
    resolved = str(Path(path) if path is not None else CATALOG_PATH)
    if resolved not in _cache:
        raw = load_raw_catalog(resolved)
        _cache[resolved] = MappingProxyType(
            {key: value for key, value in raw.items() if key.startswith(SERVER_PREFIX)})
    return _cache[resolved]


def clear_cache():
    """Forget every parsed catalog. For a test that edits a file in place."""
    _cache.clear()
    _raw_cache.clear()


def tr(key, **variables):
    """The string for a `server.*` key, with `{var}` placeholders filled.

    A key outside the namespace raises `CatalogError`: it is a client
    string, and the server has no grammar for it. A `server.*` key that
    is missing from the catalog logs a warning and comes back as the key
    itself. A pattern that cannot be filled with these variables raises
    `CatalogError`.
    """
    if not isinstance(key, str) or not key.startswith(SERVER_PREFIX):
        raise CatalogError(
            f'i18n key {key!r} is not in the {SERVER_PREFIX}* namespace: the server renders '
            'server.* keys only, because every other key may use ICU and str.format '
            'cannot parse it')
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
