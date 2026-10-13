---
type: Surface
title: "Preferences"
description: "Describe the approved single edit mode for search preferences."
timestamp: 2026-10-11
---

# Preferences

## Purpose

Edit all criteria together, saving once or discarding the whole edit.

## Appears in

Search → Edit criteria → edit lists and notes → Done or Cancel.

## Routing

2026-10-13 (JOZ-283): Search is now `SearchCriteria.jsx`, mounted at `/`.
The Jinja `search.html` template, its view and its `/search` route are
removed, with no Jinja fallback (same no-coexist decision as the JOZ-280
detail pages; see [Detail pages](detail-pages.md)). The redundant second
URL the Jinja page also answered to (`/search`) is retired rather than
carried over: the nav's Search tab, and the app's own wordmark link, now
point at `/`. The page exists only when `CAREEROS_REACT_UI=1`; with the
flag off, `/` 404s (`tests/test_react_ui_flag.py`).

## Minimal contents

Visual contract: [approved mockup](batch-d-mockup.html), fixed spacing version. Existing app dark
theme controls and tokens are reused. No broader design-system migration.

Owner verdict (verbatim): "ok, apart from spacing on this i guess it is fine".
Spacing was fixed in the approved mockup afterward.

From the build brief:

> ONE right-aligned bar above the grid: a single "Edit criteria" primary button.
> While edit mode is ON, it is replaced by "Done" + "Cancel" (same bar position).
> Edit mode ON: every criteria card shows its add-input row (input flexes to
> near-full card width, Add button right) and each list item gets a × remove
> button. Notes swaps its read paragraph for a full-width textarea (label above).

The implementation (`SearchCriteria.jsx`, JOZ-283) stacks one `SectionCard`
per criteria section plus a Notes `SectionCard` in a single column, not the
two-column grid an earlier sketch of this bar described; the sketch is
removed here since it no longer matches what was built.

List rows use 6px vertical padding, subtle dividers except on the last item,
12px before ×, and 12px above add rows with an 8px gap.

## States

- No criteria: existing Create criteria path stays unchanged.
- Read: no per-card edit or remove controls. Empty lists say No items yet;
  empty notes say No notes yet. There is no filtering/no-match state.
- Editing: a working copy holds adds, removals and notes; nothing is sent yet.
- Done: one full-object POST; Done and Cancel are disabled for its
  duration; the read view only switches over once the save succeeds (no
  optimistic update).
- Cancel: restore the entry backup without a POST.
- Save failure: keep the edits, stay in edit mode, and show an error
  banner with the server's message so the owner can retry.

Approved 2026-10-10 (owner click-test, mockup)

Deferred: nothing.

## Open questions

None about the sketch. Live implementation acceptance remains an owner check.


Live acceptance checks: edit multiple criteria, Cancel to restore, then Done and reload; check mobile spacing.

Verification: `.venv/bin/python -m pytest tests/ -q`,
`cd frontend && npx playwright test tests/search-criteria.spec.js`. Owner
implementation click-test remains pending; the approved mockup is not
implementation acceptance.
