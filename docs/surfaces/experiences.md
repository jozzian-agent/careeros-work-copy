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
Add position → the Add position page at `/experiences/new`, below.

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
(`tests/test_react_ui_flag.py`). Since 2026-11-01 `/experiences/new`
follows the same rule: see the Add position section below.
`/experiences/<id>/edit` is gone altogether — nothing in the React app
ever linked to it, and the Experience detail page edits in a popup.

## States

Loading and load-error states (plain text, a Retry on load failure). An
empty library shows one card with the empty message and an Add position
button instead of the list.

# Add position

Surface: `/experiences/new` (React rewrite of `experience_form.html`).
Status: implemented 2026-11-01 to the owner-approved artboard of the same
day. Owner click-test pending.

## Purpose

Write one position the user held, in one pass, without leaving a dialog's
worth of room for a field set this long.

## Appears in

Experiences → Add position (the heading row's button, and the empty
state's). Back link → Experiences. Save → the new position's detail page.
Cancel → Experiences.

## Minimal contents

A back link, the H1, and three `SectionCard`s in a 920px column —
**Role** (Title\*, Company with its link status, Start\*, End, Location\*,
People led), **What you did** (Summary, Highlights one per line, Detail as
markdown) and **Tags** (one input per registry facet except `function`,
Experience type as its three choices, and the custom fields) — over a
sticky bar holding Save position and Cancel. No salary field: compensation
is vault-file-only, by owner decision.

## States

Loading and load-error (plain text, a Retry). The three starred fields
show "Enter a title.", "Enter a start date." and "Enter a location."
inline when empty on Save, and nothing is written. A typed company reads
"Linked to X" when it matches a record, "Not linked" when it does not, and
"Will create "X" on save" once the create is asked for; the create itself
runs after the position exists, through
`POST /api/experiences/<id>/link-company`, and a near match is confirmed
first. A company link that fails after the position was created says so
and offers the position rather than a second Save. Only an admin is
offered the propose-a-new-tag control (M2, D3).

## Writes

`POST /api/experiences` (the one path that creates a position, which
stamps the owner) and then, if a company has to be created,
`POST /api/experiences/<id>/link-company`. No endpoint was added or
changed.

## Verification

- `.venv/bin/python -m pytest -q`.
- `cd frontend && npx playwright test tests/experiences-list.spec.js tests/add-position.spec.js`.
- `cd frontend && npm run test:unit` (`src/positions.test.js`, the payload).
- `cd frontend && npm run build`.
- Owner click-test on the live instance: pending.

## Open questions

- **Editing a position is still a dialog.** The owner's follow-up is to
  move it onto this page; the field set is already the shared
  `components/PositionFields.jsx` and the payload the shared
  `src/positions.js`, and `EditPositionPopup.jsx` is deliberately left on
  its own copy until that change.
- **The back link says "Professional experiences" and every other
  reference says "Experiences".** The artboard's wording, kept as drawn;
  the nav tab, the H1 of the list page and the detail pages' own back link
  all read "Experiences". One of the two words has to go.
- Nothing else beyond the questions already open for the Experiences
  surface generally (see PROJECT.md's inventory).
