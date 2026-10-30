---
type: Convention
title: String catalog
description: State the namespace rule every value in the English string catalog follows, why the server forbids ICU in server.* keys, and the sync rule that keeps the catalog and the code naming the same keys.
timestamp: 2026-10-30
---

# String catalog

`en.json` beside this file is the one catalog of user-visible English
strings. JSON cannot carry a comment, so the rules that govern every
value in it live here.

## Who reads the catalog

Both sides of the app read the same file:

- React, through react-intl. `src/main.jsx` imports `en.json` and wraps
  the app in `IntlProvider` with `locale` and `defaultLocale` both `en`.
  The catalog is imported, not fetched: every string is needed by the
  first paint, so a fetch would buy a flash of untranslated interface and
  a second failure mode in exchange for nothing.
- The server, through `careeros/i18n.py`, for the Flask pages and for
  the body of a mail.

A surface reads a string with `<FormattedMessage id="..." />` where a
React node will do, and with `useIntl().formatMessage({ id: '...' })`
where a plain string is needed — a `label`, a `text`, an `aria-label`, a
`title`, a `placeholder`, the message text handed to a toast.

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

Two consequences of full ICU on the client side are worth knowing before
writing a value:

- An apostrophe is ICU's escape character, so a literal one is written
  doubled: `"It''s saved"` renders as `It's saved`.
- A plural's `#` is formatted as a number, grouping separators included,
  while a plain `{count}` is not. Where a value must match a string the
  code used to build by hand, `{count}` inside the plural branches is
  the one that keeps `1000` from becoming `1,000`.

## The sync rule

Every key in the catalog is read by the code, and every key the code
asks for is in the catalog. Both directions are enforced, because each
one fails invisibly on its own: a dead key is a string nobody renders
and the next translator pays to translate, and a key the catalog lacks
renders as its own id on the page while only the browser console says
so.

That means **ids are written as literals**, never built: no template
string, no id assembled from a slug or a loop variable, no lookup table
of ids. Where a list of labels used to sit at module scope, it moves
inside the component and spells each id out — see `src/Nav.jsx` for the
nav tabs and `src/pages/CompaniesList.jsx` for the facets and columns.
A computed id is invisible to the check, which is the whole reason the
rule exists.

`scripts/check_i18n.py` enforces this, and CI runs it on every pull
request:

- strict placeholder rule for `server.*` values;
- basic validity for ALL values: balanced braces, no empty values, no
  key with leading or trailing whitespace;
- every key is used — a client key by its quoted spelling appearing
  under `frontend/src`, a `server.*` key by a `tr('key')` call under
  `careeros/`;
- every id the code asks react-intl for is a key in the catalog.

Run it the same way locally:

```
python scripts/check_i18n.py
```

The script's own docstring says what its text scan can and cannot see.

## Moving a string between sides

If a string that was client-only turns out to be needed by the server
too, move it (or add a sibling) under `server.*` and strip its ICU; the
client can render a plain-placeholder string fine. The other direction
means the server caller has to give up the string.

## Keys

Dot-namespaced, first segment naming the surface. The surfaces that own
keys today:

- `shell.*` — the app header: the nav tabs, the nav landmark label and
  Log out.
- `login.*` — the login page.
- `board.*` — My Jobs: the title, the action and view row, the list
  view's columns and sort options, the duplicate dialog, and the board's
  own toasts.
- `allJobs.*` — the All jobs tab.
- `companies.*` — the Companies directory, both views.
- `experiences.*` — the Experiences list.
- `common.*` — the exception to surface-first naming: a string two
  surfaces render identically, in the same role. `common.retry` is the
  button every list page's load error offers; `common.jobs.*` are the
  four strings My Jobs and All jobs both show. One key rather than two
  copies, because a second spelling of one word is a second thing to
  keep right. A key goes here only when the surfaces really share the
  element — not merely when the English happens to coincide, which is
  why "Location" is a `board.*` column and a `companies.*` field.

There are no `server.*` keys yet: the Flask pages and the mail bodies
still carry their English inline, and move to the catalog in their own
change.

Not every string the app renders is here. Out of the catalog on purpose:

- anything the API sends. A status word, a taxonomy label, a size class
  and the empty-state sentence each page receives in its payload are the
  server's words, not the catalog's, and translating them is the
  server's job.
- the `CareerOS` wordmark, which is the product's name.
- the detail pages, Notes, Search criteria and Taxonomy, and the shared
  components under `src/components/`. They keep their English inline
  until their own change moves it, which is why `FilterBar`'s
  `countNoun` ("jobs", "companies") is still a literal prop: extracting
  half of "4 of 12 jobs" would put a bare noun in the catalog and leave
  the sentence that needs it in the code.

## Open questions

- Which locale beyond `en` lands first, and whether a missing key in a
  translated catalog falls back to English or to the key itself. The
  server side returns the key today, which is a safe default for one
  locale and probably the wrong one for several.
- Whether the count sentences `FilterBar` and `MoreFiltersPanel` build
  from `countNoun` become one ICU message per surface or one message
  with a plural, which is a decision for the change that extracts those
  components.
