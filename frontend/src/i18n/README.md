---
type: Convention
title: String catalog
description: State the namespace rule every value in the English string catalog follows, and why the server forbids ICU in server.* keys.
timestamp: 2026-10-30
---

# String catalog

`en.json` beside this file is the one catalog of user-visible English
strings. JSON cannot carry a comment, so the rules that govern every
value in it live here.

## Who reads the catalog

Both sides of the app read the same file:

- React, through react-intl (wired by a later PR, not by this one).
- The server, through `careeros/i18n.py`, for the Flask pages and for
  the body of a mail.

## The namespace rule

The namespace a key lives in decides which grammar its value may use:

- **`server.*`** — strings the server renders: Flask pages and mail
  bodies. Values may contain plain `{var}` placeholders and NOTHING
  else. ICU MessageFormat constructs are forbidden here:
  - plurals, meaning `{n, plural, one {...} other {...}}`
  - selects, meaning `{gender, select, ...}` and `selectordinal`
  - number and date skeletons, meaning `{n, number}` or `{d, date, short}`
  - apostrophe quoting, which ICU uses to escape a literal brace
  Every `{var}` name must be a legal Python identifier.
- **Every other key** — client strings, rendered by React through
  react-intl. Full ICU is allowed: plural, select, number, date.

The reason for the split is the server grammar: `careeros.i18n.tr`
substitutes with Python `str.format`, which knows a placeholder name
and nothing more. It cannot parse an ICU construct, so a plural in a
`server.*` value would not read as a bad translation, it would read as
a raised exception in the middle of a page render or a mail send.
Conversely, `careeros/i18n.py` refuses to load or return ANY key
outside `server.*` — a server-side caller cannot reach a client string
even by accident, so ICU in a client key is safe.

`scripts/check_i18n.py` enforces this, and CI runs it on every pull
request:

- strict placeholder rule for `server.*` values;
- basic validity for ALL values: balanced braces, no empty values, no
  key with leading or trailing whitespace.

Run it the same way locally:

```
python scripts/check_i18n.py
```

## Moving a string between sides

If a string that was client-only turns out to be needed by the server
too, move it (or add a sibling) under `server.*` and strip its ICU; the
client can render a plain-placeholder string fine. The other direction
means the server caller has to give up the string.

## Keys

Dot-namespaced, first segment naming the surface. The two entries
today are the examples that make the CI check meaningful from day one:

- `server.mail.greeting` — a `server.*` key with a `{var}` placeholder.
- `shell.logOut` — a client key with no placeholder.

Real strings move in later PRs.

## Open questions

- Which locale beyond `en` lands first, and whether a missing key in a
  translated catalog falls back to English or to the key itself. The
  server side returns the key today, which is a safe default for one
  locale and probably the wrong one for several.
