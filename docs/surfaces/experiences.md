---
type: Surface
title: "Experiences list"
description: "Describe the Experiences list surface."
timestamp: 2026-10-13
---

# Experiences list

Surface: `/experiences` (React rewrite of `experiences.html`).
Status: implemented 2026-10-13 (JOZ-283). Owner click-test pending.

## Purpose

Show every position the user has held, so they can review and reach each
one, or add another.

## Appears in

Nav → Experiences. A card's title or company name → Experience detail.
Add position → the existing `/experiences/new` form (unchanged, still
Jinja).

## Minimal contents

A page header (Experiences, with an Add position button) and one card per
position: title (links to the detail page), the company label (linked to
the company's detail page when it resolves to a real record, plain text
otherwise), a muted `start – end · location` line, skill chips, tag chips
(the registry label, or the tag's own key title-cased when the registry
has none, with a "local" marker and tooltip for a local-extension tag),
and a "Led N people" chip when set.

## Routing

No Jinja coexistence (same no-coexist decision as the JOZ-280 detail
pages; see [Detail pages](detail-pages.md)): `/experiences` exists only
when `CAREEROS_REACT_UI=1`, with the Jinja `experiences.html` template and
its view removed rather than kept as a flag-off fallback
(`tests/test_react_ui_flag.py`). `/experiences/new` and
`/experiences/<id>/edit` are unaffected and stay Jinja.

## States

Loading and load-error states (plain text, a Retry on load failure). An
empty library shows one card with the empty message and an Add position
button instead of the list.

## Verification

- `.venv/bin/python -m pytest -q`.
- `cd frontend && npx playwright test tests/experiences-list.spec.js`.
- `cd frontend && npm run build`.
- Owner click-test on the live instance: pending.

## Open questions

None beyond the ones already open for the Experiences surface generally
(see PROJECT.md's inventory).
