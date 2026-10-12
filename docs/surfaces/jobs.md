---
type: Surface
title: "Jobs"
description: "Describe the approved React Jobs board and its acceptance state."
timestamp: 2026-10-12
---

# Jobs

Surface: /jobs (React rewrite of jobs.html + job_cards.html).
Status: Approved 2026-10-10 (owner: "Go" on plan defaults + sketch).
Owner click-test: Passed 2026-10-11 on live LAN server with the real vault
("works all"). One gap found: navigation to the other pages is missing
from the React Jobs page; tracked as M0 follow-up below.

2026-10-12 (JOZ-278, design-brief rebuild): the board's card and status
controls were rebuilt against the handoff brief, on top of the above. See
"JOZ-278 rebuild" below for what changed; it supersedes the component
mapping and card anatomy further down where the two disagree, and
`frontend/BUILD_NOTES.md`'s "Jobs board rebuild (JOZ-278)" section has the
full implementation rationale this doc only summarizes.

## Purpose

Track jobs on the React board and list while preserving approved interactions.

## Appears in

Jobs → add a posting, review a card, change status or open job detail.

## Minimal contents

### Behavior contract (batches A–D)

1. Board and List switch, remembered per browser (localStorage).
2. Columns are the filter; one status control per card (select + drag-drop
   both move a job; optimistic move, revert + toast on failure).
3. Needs attention toggle, remembered per browser.
4. Function filter (All functions + facet values).
5. Intake by posting URL; duplicate warning dialog with Open existing /
   Promote to pipeline / Add anyway / Cancel (Cancel creates nothing).
6. Ingest failure chips with Retry; enrichment pending states;
   "Details filling in…" for stub/fetched.
7. Company link, "Needs your input" review chip, "Company: pending" chip.
8. Salary disclosed chip; source chip; location/added meta line.
9. List view: sortable columns (Title, Company, Source, Status, Location,
   Posted, Added), aria-sort, mobile sort select.
10. Auto-refresh on tab regain (>30s) and back-forward cache restore.
11. Toasts for success/error of every mutation.

### Gestalt component mapping

| Today (Jinja/CSS) | Gestalt |
|---|---|
| page-header h1 + view toggle | PageHeader + two Buttons (aria-pressed) |
| intake form (url input + Add) | TextField + Button color="red"→themed blue |
| duplicate-warning dialog | Modal + Button row |
| function select | SelectList |
| needs-attention toggle | Button (pressed state) |
| kanban column + column-count chip | Box/Flex column + Tag |
| job card (.card) | Card |
| status select | SelectList (compact) |
| chips (.chip variants) | Tag (variants: needs-review purple, ingest-failed red, info gray) |
| retry-ingest button | Button size="sm" |
| list view table | Table + Table.SortableHeaderCell |
| toast | Toast (Gestalt) via shared helper |
| empty states | Text + Box |

Theme: blue/purple tokens (owner decision, PROJECT.md design system).
Gestalt default red accent replaced via custom theme tokens in
frontend/src/theme.js.

### Text layout

```
┌────────────────────────────────────────────────────────────┐
│ Jobs                            [Board] [List]             │  PageHeader
├────────────────────────────────────────────────────────────┤
│ Posting URL [________________________] [Add]               │  intake
├────────────────────────────────────────────────────────────┤
│ Function [All functions ▾]   [Needs attention]             │  filters
├───────────────┬───────────────┬───────────────┬────────────┤
│ New (3)       │ Picked (2)    │ Applied (1)   │ ...        │  columns
│ ┌───────────┐ │ ┌───────────┐ │               │            │
│ │ Title →   │ │ │ Title →   │ │               │            │
│ │ [status▾] │ │ │ [status▾] │ │               │            │
│ │ Company→  │ │ │ Company:  │ │               │            │
│ │ [rev chip]│ │ │ pending   │ │               │            │
│ │ Loc · Add │ │ │ Loc · Add │ │               │            │
│ │ (src)(sal)│ │ │ (src)     │ │               │            │
│ │ (filling…)│ │ │(fail)[Ret]│ │               │            │
│ └───────────┘ │ └───────────┘ │               │            │
└───────────────┴───────────────┴───────────────┴────────────┘
Empty: "Nothing here yet — add a posting URL above."
Needs-attention empty: "Nothing needs attention."
```

List view (unchanged columns/order):

```
Sort by [Choose order ▾]   (mobile only)
| Title↕ | Company↕ | Source↕ | Status↕ | Location↕ | Posted↕ | Added↕ |
```

### Deferred (listed per AGENTS.md)

- Responsive/mobile refinements beyond the existing mobile-sort select
  (Gestalt Box wrap defaults used in M0; revisit in polish round).
- Keyboard drag-drop alternative beyond the existing status select
  (select already provides full keyboard access).
- Any visual polish beyond token swap; that is the M6 registry round.
- Board column reorder/customization — never existed, not added.

### Adds / Removes

- Adds: frontend/ package (new element; required by owner decision C —
  no existing element can render Gestalt components).
- Removes at cutover: jobs.html, job_cards.html, their JS-harness tests,
  and the /jobs HTML route branch.

## JOZ-278 rebuild

Lands the design brief's card/status/drag anatomy on top of the R0 board
above. Component-level detail (exact props, geometry, token wiring) lives in
`frontend/BUILD_NOTES.md`'s "Jobs board rebuild (JOZ-278)" section; this is
the surface-level summary.

- **Fit chip.** Each card shows a read-only fit chip: one of three rated
  states (`no_fit`, `lucky`, `excellent` — icon + label, brand-coloured
  background) or, when the job has no fit yet, a "Needs your input" chip.
  The two never appear together. Fit is set elsewhere (job detail page,
  later calculated automatically); the board only displays it.
- **Status control.** Replaces the old `SelectList` with a compact button
  that opens a Dropdown (`StatusSelect.jsx`), reachable the same way by
  click or keyboard; it is also the keyboard/screen-reader route for moving
  a card, since drag-and-drop itself is not.
- **Drag-and-drop.** Hand-rolled native HTML5 drag-and-drop (not a library):
  it was already load-bearing on the pre-rebuild board, carries no new
  React-19 peer-dependency risk, and matches the handoff mockup's own
  reference implementation. A same-column drop is a pure client-side
  reorder (the board API has no concept of card position); a cross-column
  drop is the real status mutation, reachable identically from the status
  control.
- **Undo.** A successful move's success toast carries an Undo action.
  Undo, and a failed move's automatic revert, each restore only the one
  card's status and slot (not a whole-board snapshot), so a different
  card's move landing in between is never reverted by this one. If Undo's
  own write fails, the card is reconciled to the state the server actually
  kept (not left showing the stale pre-Undo column) and a persistent error
  is shown rather than a silent mismatch.
- **Toasts.** A success toast auto-hides after ~4s; an error toast persists
  until dismissed. Toasts stack rather than replace one another, so a
  success elsewhere can never clear a still-outstanding error.
- **Add-job popup.** The plus button next to Board/List opens a shell
  Modal: a heading and a footer Close button, nothing else. The real
  intake flow (posting-link field, duplicate/"not a link"/"couldn't read"
  states) is JOZ-279; the existing inline "Posting URL" field below the
  board stays the one working intake path until then.

## States

Board/list, empty board and no attention matches follow the sketch above.
Duplicate intake opens a choice dialog; pending, failed and company-review
chips identify unfinished work. Mutation failures revert and show a toast.

## Open questions

The recorded navigation follow-up and Jinja cutover await the later audit.
