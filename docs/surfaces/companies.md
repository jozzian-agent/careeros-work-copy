---
type: Surface
title: "Companies list"
description: "Describe the Companies list surface."
timestamp: 2026-10-13
---

# Companies list

Surface: `/companies` (React rewrite of `companies.html`).
Status: implemented 2026-10-13 (JOZ-283). Owner click-test pending.

## Purpose

Browse every company in the shared directory, filtered by sector or size,
and reach any one of them.

## Appears in

Nav → Companies. A card → Company detail.

## Minimal contents

A page header (Companies) and, when the directory is not empty, a Sector
filter and a Size filter (each "All ..." by default) above a card grid:
company name, a muted `sector labels · size` line (the raw size range
when known, else the title-cased size class, else "Size unknown"), and an
"N open jobs" chip.

Filtering is client-side, same semantics as the Jinja page's inline
script: the sector filter matches ANY of the company's sectors; the size
filter matches `size_class` exactly. A filter combination with no matches
shows an empty grid with no separate message, matching the Jinja page's
own behavior (it only ever hid non-matching cards, it never rendered a
"no results" state).

## Routing

No Jinja coexistence (same no-coexist decision as the JOZ-280 detail
pages; see [Detail pages](detail-pages.md)): `/companies` exists only when
`CAREEROS_REACT_UI=1`, with the Jinja `companies.html` template and its
view removed rather than kept as a flag-off fallback
(`tests/test_react_ui_flag.py`).

## States

Loading and load-error states (plain text, a Retry on load failure). An
empty directory shows the empty message with no filter controls. This is
a deliberate change, not Jinja parity: the Jinja page's filter controls
sat outside its entries loop, so an empty directory still showed the
(uselessly empty) Sector and Size selects above the `{% else %}` empty
message. Hiding them here is a conscious improvement, since filters with
nothing to filter serve no purpose.

## Verification

- `.venv/bin/python -m pytest -q`.
- `cd frontend && npx playwright test tests/companies-list.spec.js`.
- `cd frontend && npm run build`.
- Owner click-test on the live instance: pending.

## Open questions

None beyond the ones already open for the Companies surface generally
(see PROJECT.md's inventory).
