"""CI gate: `server.*` keys hold plain `{var}` placeholders; all keys stay valid.

`frontend/src/i18n/en.json` is read by two different runtimes. React reads
it through react-intl, which speaks full ICU MessageFormat, and the server
reads the `server.*` namespace through `careeros.i18n`, which substitutes
with Python `str.format` and knows a placeholder name and nothing more.
The namespace rule splits the grammar accordingly:

  * `server.*` keys — Flask pages and mail bodies. STRICT: plain `{var}`
    placeholders only, no ICU.
  * every other key — client strings. ICU is allowed: plural, select,
    selectordinal, number, date, apostrophe quoting.

All keys, in both namespaces, must still be basically valid:

  * balanced braces. An unbalanced brace is a typo in either grammar and
    breaks react-intl's compile just as surely as it breaks `str.format`.
  * no empty values, and no key with leading or trailing whitespace.

What additionally fails in a `server.*` value:

  * an ICU construct, meaning a comma inside a placeholder. That one rule
    catches every form of it: `{n, plural, ...}`, `{gender, select, ...}`,
    `{n, selectordinal, ...}`, `{n, number}` and `{d, date, short}` all
    carry a comma, and none of them is a legal `str.format` field name.
  * nested braces inside a placeholder, which is the body of an ICU
    construct even when its comma is missing.
  * a doubled brace. Python reads `{{` as one literal brace and ICU does
    not, so a value carrying one cannot mean the same thing on both
    sides. A server string that needs a literal brace needs different
    wording.
  * a placeholder name that is not a legal Python identifier, because
    `str.format` is what resolves it.

An ICU construct in a `server.*` value is not a cosmetic problem:
`str.format` would raise on it, so a plural written into a mail body
would surface as a failed send rather than as a clumsy sentence. The
rule and its reasoning live in `frontend/src/i18n/README.md`.

The same placeholder name twice in one value is fine, and so is a value
with no placeholder at all.

The second gate is the sync rule: the catalog and the code that reads it
must name the same keys, in both directions.

  * every key in the catalog is used somewhere. A dead key is a string
    nobody reads, and the next translator would pay to translate it.
  * every key the code asks for is in the catalog. A key that is not
    there renders as its own id on the page, which react-intl reports to
    the browser console and nothing else notices.

Both directions are answered by scanning text, not by parsing JavaScript
or Python, and the limits of that are worth saying out loud:

  * a client key counts as used when its own quoted spelling appears
    anywhere in a `.js` or `.jsx` file under `frontend/src` (the `i18n`
    directory itself excluded, since the catalog quotes every key).
    A key quoted in a comment therefore counts as used, and so would one
    quoted in dead code. The rule catches the case it is for -- a key
    nobody renders any more -- and it cannot be fooled into failing a
    key that IS rendered.
  * an id the code asks for is read out of a react-intl consumption
    position, meaning `id="..."` or `id: '...'`, and only literals that
    look like a catalog key (they carry a dot and no whitespace) are
    treated as one. That is what keeps `id="login-email"`, a DOM id, out
    of it. The cost is that an id built at runtime is invisible here,
    which is why every id in this front end is written as a literal.
  * a `server.*` key counts as used when `tr('key'` or `tr("key"`
    appears in a `.py` file anywhere under `careeros/`. The same
    comment caveat applies.

The sync rule compares a catalog against the tree that reads it, so it
needs both. `--root` names that tree (default: the repository this script
lives in) and `--catalog` defaults to that tree's own catalog. A
`--catalog` given on its own is a file from somewhere else, so only the
validity rules above run over it.

Usage:
  python scripts/check_i18n.py
  python scripts/check_i18n.py --catalog path/to/other.json
  python scripts/check_i18n.py --root path/to/tree
"""
import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO_ROOT))

from careeros import i18n  # noqa: E402

#: Where the two runtimes live inside a tree, relative to its root.
CLIENT_SOURCE_DIR = Path('frontend') / 'src'
SERVER_SOURCE_DIR = Path('careeros')

#: The catalog quotes every key it holds, so scanning it for "is this key
#: used" would answer yes every time. Its whole directory is skipped, named
#: relative to whichever client source directory is being scanned.
CLIENT_SKIP_DIRNAME = 'i18n'

CLIENT_SOURCE_GLOBS = ('*.js', '*.jsx')

#: A quoted string that could be a catalog key: it carries a dot and no
#: whitespace. Deliberately loose for the used-keys scan, where a false
#: "used" is harmless, and the one filter that keeps a DOM id such as
#: `login-email` out of the asked-for-ids scan.
KEY_SHAPED = re.compile(r'''['"]([^'"\s]*\.[^'"\s]*)['"]''')

#: A react-intl consumption position: `id="board.title"`, `id: 'board.title'`.
#: The lookbehind is what stops `data-testid="a.b"` matching.
CLIENT_ID = re.compile(r'''(?<![\w-])id\s*[=:]\s*['"]([^'"\s]+)['"]''')

#: `careeros.i18n.tr` is the one way a server string is read.
SERVER_TR = re.compile(r'''\btr\(\s*['"]([^'"]+)['"]''')

#: Said once here and quoted into each ICU problem, because the message a
#: contributor reads in CI has to explain why the rule exists, not only
#: that it was broken.
ICU_REASON = ('an ICU construct (plural, select, selectordinal, or a number or '
              'date skeleton), which the server cannot parse')

#: A value can be a whole sentence, and a placeholder body in a broken one
#: can be most of it. Enough to recognise, short enough to read.
_SHOWN = 40


def _shown(body):
    return body if len(body) <= _SHOWN else f'{body[:_SHOWN]}...'


def basic_problems(value):
    """The rules every value follows, ICU or not: braces balance.

    A stack walk rather than a counter, so the failure message can name
    the position of the brace that broke — a counter knows the string
    ended wrong but not where it went wrong.
    """
    stack = []
    for index, char in enumerate(value):
        if char == '{':
            stack.append(index)
        elif char == '}':
            if not stack:
                return [f'unbalanced closing brace at position {index}']
            stack.pop()
    if stack:
        return [f'unbalanced opening brace at position {stack[0]}']
    return []


def server_value_problems(value):
    """Every rule a `server.*` value breaks, in reading order.

    One pass over the string rather than a regular expression: the thing
    being checked is nesting and balance, which a regular expression
    cannot see, and the position of the brace that broke is what makes
    the failure message useful.
    """
    found = []
    index = 0
    while index < len(value):
        char = value[index]
        nxt = value[index + 1:index + 2]
        if char in '{}' and nxt == char:
            found.append(f'doubled brace {char}{char} at position {index}: Python reads it as '
                         'one literal brace and ICU does not, so reword to avoid the brace')
            index += 2
            continue
        if char == '}':
            found.append(f'unbalanced closing brace at position {index}')
            return found
        if char != '{':
            index += 1
            continue
        close = value.find('}', index + 1)
        if close < 0:
            found.append(f'unbalanced opening brace at position {index}')
            return found
        body = value[index + 1:close]
        if ',' in body:
            found.append(f'{{{_shown(body)}}} is not a plain placeholder: it is {ICU_REASON}. '
                         f'Move the string out of the {i18n.SERVER_PREFIX}* namespace if it is '
                         'a client string, or reword it')
        elif '{' in body:
            found.append(f'{{{_shown(body)}}} nests a brace inside a placeholder: '
                         f'it is the body of {ICU_REASON}')
        elif not body.isidentifier():
            found.append(f'placeholder name {body!r} is not a legal Python identifier, '
                         'and str.format is what resolves it on the server')
        index = close + 1
    return found


def _source_text(directory, globs, skip=None):
    """Every file under `directory` matching `globs`, as (path, text) pairs.

    A missing directory reads as no files rather than as an error: a tree
    that holds only one of the two runtimes is a legitimate thing to check
    (and is what the unit tests point this at).
    """
    if not directory.is_dir():
        return
    for glob in globs:
        for path in sorted(directory.rglob(glob)):
            if skip is not None and skip in path.parents:
                continue
            yield path, path.read_text(encoding='utf-8', errors='replace')


def used_client_keys(src_dir):
    """Every key-shaped quoted literal in the client sources under `src_dir`.

    A set, not a per-file map: the question this answers is only whether a
    catalog key is spelled anywhere in the code at all. See the module
    docstring for what this scan cannot see.
    """
    skip = src_dir / CLIENT_SKIP_DIRNAME
    found = set()
    for _path, text in _source_text(src_dir, CLIENT_SOURCE_GLOBS, skip=skip):
        found.update(KEY_SHAPED.findall(text))
    return found


def asked_client_ids(src_dir):
    """Every key-shaped id the client sources ask react-intl for.

    `(id, path)` pairs, because a failure here has to name the file that
    asks for the missing key -- "board.ttile is not in the catalog" is
    only half an answer.
    """
    found = []
    skip = src_dir / CLIENT_SKIP_DIRNAME
    for path, text in _source_text(src_dir, CLIENT_SOURCE_GLOBS, skip=skip):
        for candidate in CLIENT_ID.findall(text):
            if '.' in candidate:
                found.append((candidate, path))
    return found


def used_server_keys(py_dir):
    """Every key passed to `tr()` in the Python sources under `py_dir`."""
    found = set()
    for _path, text in _source_text(py_dir, ('*.py',)):
        found.update(SERVER_TR.findall(text))
    return found


def unused_problems(catalog, client_used, server_used):
    """Every catalog key nothing reads, as `(key, message)` pairs."""
    found = []
    for key in catalog:
        if key.startswith(i18n.SERVER_PREFIX):
            if key not in server_used:
                found.append((key, f'nothing reads this key: no tr({key!r}) call under '
                                   f'{SERVER_SOURCE_DIR}/. Delete the key, or use it'))
        elif key not in client_used:
            found.append((key, f'nothing reads this key: it is not quoted anywhere under '
                               f'{CLIENT_SOURCE_DIR}/. Delete the key, or use it'))
    return found


def missing_from_catalog(catalog, asked):
    """Every id the code asks for that the catalog does not hold."""
    return [(key, f'{path}: asks react-intl for this id, and the catalog has no such key')
            for key, path in asked if key not in catalog]


def sync_problems(catalog, root):
    """Both directions of the sync rule over one tree, in reading order."""
    src_dir = root / CLIENT_SOURCE_DIR
    found = unused_problems(catalog,
                            used_client_keys(src_dir),
                            used_server_keys(root / SERVER_SOURCE_DIR))
    found.extend(missing_from_catalog(catalog, asked_client_ids(src_dir)))
    return found


def problems(catalog):
    """Every problem in a whole catalog as `(key, message)` pairs.

    A key can break more than one rule and every break is reported, so one
    run names everything there is to fix rather than the first thing.
    """
    found = []
    for key, value in catalog.items():
        if not key:
            found.append(('(empty key)', 'the catalog has an empty key'))
        elif key != key.strip():
            found.append((repr(key), 'key has leading or trailing whitespace'))
        if not value:
            found.append((key, 'value is empty, and a key with no string is not a string'))
            continue
        if key.startswith(i18n.SERVER_PREFIX):
            found.extend((key, message) for message in server_value_problems(value))
        else:
            found.extend((key, message) for message in basic_problems(value))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--catalog',
                        help='catalog to check (default: the tree\'s own '
                             'frontend/src/i18n/en.json). Given on its own, only the '
                             'validity rules run: a catalog from elsewhere has no code '
                             'tree to be in sync with')
    parser.add_argument('--root',
                        help='tree whose code the sync rules read '
                             '(default: this script\'s own repository)')
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else REPO_ROOT
    path = Path(args.catalog) if args.catalog else root / CLIENT_SOURCE_DIR / 'i18n' / 'en.json'
    checks_sync = args.root is not None or args.catalog is None
    try:
        catalog = i18n.load_raw_catalog(path)
    except (OSError, ValueError) as error:
        print(f'{path}: unreadable string catalog: {error}', file=sys.stderr)
        return 1

    found = problems(catalog)
    if checks_sync:
        found.extend(sync_problems(catalog, root))
    if found:
        print(f'{path}: {len(found)} problem(s):', file=sys.stderr)
        for key, message in found:
            print(f'  {key}: {message}', file=sys.stderr)
        print(f'{i18n.SERVER_PREFIX}* values may carry plain {{var}} placeholders only; '
              'all values must balance their braces; and every key must be used by the '
              'code exactly as the code names it. '
              'See frontend/src/i18n/README.md.', file=sys.stderr)
        return 1

    server_keys = sum(1 for key in catalog if key.startswith(i18n.SERVER_PREFIX))
    sync = 'all used' if checks_sync else 'sync rules skipped (no tree for this catalog)'
    print(f'{path}: {len(catalog)} key(s) checked '
          f'({server_keys} {i18n.SERVER_PREFIX}*), {sync}, OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
