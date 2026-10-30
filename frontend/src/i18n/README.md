---
type: Convention
title: String catalog
description: State the rules every value in the English string catalog follows, and why the server side forbids ICU.
timestamp: 2026-10-30
---

# String catalog

`en.json` beside this file is the one catalog of user-visible English
strings. JSON cannot carry a comment, so the constraint that governs
every value in it lives here.

## Who reads the catalog

Both sides of the app read the same file:

- React, through react-intl (wired by a later PR, not by this one).
- The server, through `careeros/i18n.py`, for the Flask pages and for
  the body of a mail.

## The rule: placeholders only

A value may contain `{var}` placeholders and nothing else. ICU
MessageFormat constructs are FORBIDDEN in every key:

- plurals, meaning `{n, plural, one {...} other {...}}`
- selects, meaning `{gender, select, ...}` and `selectordinal`
- number and date skeletons, meaning `{n, number}` or `{d, date, short}`
- apostrophe quoting, which ICU uses to escape a literal brace

The reason is the server: `careeros.i18n.tr` substitutes with Python
`str.format`, which knows a placeholder name and nothing more. It cannot
parse an ICU construct, so a plural in a value would not read as a bad
translation, it would read as a raised exception in the middle of a page
render or a mail send.

Every `{var}` name must also be a legal Python identifier, because
`str.format` is what resolves it.

`scripts/check_i18n.py` enforces all of this, and CI runs it on every
pull request. Run it the same way locally:

```
python scripts/check_i18n.py
```

## Client-only keys

React may use full ICU in a key that is marked client-only. There are
none today, and the catalog has no way to mark one, because a mechanism
with no user would be a thing to maintain for nothing. If a plural is
ever genuinely needed on the client, the key has to be excluded from the
server-loaded set explicitly, and the check script and this document are
the two places that change in the same PR.

## Keys

Dot-namespaced, first segment naming the surface, for example
`shell.logOut`. `shell.logOut` is the single entry today: it is an
example placeholder for the PR that moves the existing strings across,
and keeping one real entry is what makes the CI check meaningful from
day one.

## Open questions

- Which locale beyond `en` lands first, and whether a missing key in a
  translated catalog falls back to English or to the key itself. The
  server side returns the key today, which is a safe default for one
  locale and probably the wrong one for several.
