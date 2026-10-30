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

Usage:
  python scripts/check_i18n.py
  python scripts/check_i18n.py --catalog path/to/other.json
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careeros import i18n  # noqa: E402

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
                        help='catalog to check (default: frontend/src/i18n/en.json)')
    args = parser.parse_args(argv)

    path = Path(args.catalog) if args.catalog else i18n.CATALOG_PATH
    try:
        catalog = i18n.load_raw_catalog(path)
    except (OSError, ValueError) as error:
        print(f'{path}: unreadable string catalog: {error}', file=sys.stderr)
        return 1

    found = problems(catalog)
    if found:
        print(f'{path}: {len(found)} problem(s):', file=sys.stderr)
        for key, message in found:
            print(f'  {key}: {message}', file=sys.stderr)
        print(f'{i18n.SERVER_PREFIX}* values may carry plain {{var}} placeholders only; '
              'all values must balance their braces. '
              'See frontend/src/i18n/README.md.', file=sys.stderr)
        return 1

    server_keys = sum(1 for key in catalog if key.startswith(i18n.SERVER_PREFIX))
    print(f'{path}: {len(catalog)} key(s) checked ({server_keys} {i18n.SERVER_PREFIX}*), OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
