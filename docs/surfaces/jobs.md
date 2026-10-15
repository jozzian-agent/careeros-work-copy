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
4. Filter bar: Fit, Function, Location, More filters (Industry, Company
   size), Needs attention (toggle with a count); active filters show as
   removable Tag chips with Clear all and a result count. Superseded by
   JOZ-279 below; this item originally named a single Function `SelectList`.
5. Intake by posting link, via the add-job popup opened by the plus
   button (no inline field on the board itself as of JOZ-279); duplicate
   warning dialog with Open existing / Promote to pipeline / Add anyway /
   Cancel (Cancel creates nothing) for the subset of duplicates not
   already handled inside the popup.
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
| intake form (url input + Add) | Modal (AddJobPopup) + TextField + Button color="red"→themed blue; see JOZ-279 below |
| duplicate-warning dialog | Modal + Button row |
| function select | Popover + Checkbox list (FilterBar/FilterPopoverPanel); see JOZ-279 below |
| needs-attention toggle | Chip-style button with a count badge (FilterBar); see JOZ-279 below |
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
│ Jobs                       [+] [Board] [List]               │  PageHeader
├────────────────────────────────────────────────────────────┤
│ Fit▾ Function▾ Location▾ More filters▾ │ Needs attention(1) │  filters
│                                              N of M jobs    │
│ Active filters: [Fit: Lucky ×] [Clear all]                 │
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
Empty: "Nothing here yet — add a posting URL above." (copy is backend-owned
via `board.empty`; "above" now means the plus button's popup, not an inline
field — see JOZ-279 below)
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

## JOZ-279 rebuild

Fills in the filter row and the add-job popup that JOZ-278 left as a
SelectList/toggle and a title-only shell, respectively. Component-level
detail lives in `frontend/BUILD_NOTES.md`'s "Filter bar and add-job popup
rebuild (JOZ-279)" section; this is the surface-level summary.

- **Filter bar.** Chip order is Fit, Function, Location, More filters, a
  divider, then Needs attention — each of the first three opens a Popover,
  and More filters opens its own side panel, with at most one of those four
  open at a time. Needs attention has no popup of its own; it is a plain
  pressed/unpressed toggle chip. Industry and Company size live inside
  More filters.
  Checking an option filters the board immediately; there is no separate
  "apply" draft state, Apply/Clear/Show N jobs just close or reset the
  panel that is already live.
- **Active filters.** Every checked option across every group renders as a
  removable Tag below the chip row ("Group: value"), plus a Clear all text
  button and a result count ("N jobs" with nothing active, "N of M jobs"
  once something is).
- **Needs attention count.** The toggle now carries the same count badge
  style as the other chips, computed from the existing `needs_attention`
  field — no backend change.
- **Company size filters on the company's class (2026-10-15).** The facet
  reads each job's `company_size_class` over the `size_classes` vocabulary
  the board payload now carries, which is the one size scale the
  [Companies list](companies.md) uses too (owner decision: classes, never
  a numeric range). It used to bucket each job's own raw `employee_count`
  in JS with a copy of the backend's thresholds, which disagreed with the
  card's own size badge for every posting that stated no headcount but
  whose company is classified anyway. Labels are the plain class words
  (Micro, Small, Medium, Large), and only classes some job's company is
  actually in are offered.
- **FilterBar serves both pages.** The chip groups, the word the result
  count counts and the needs-toggle label are props, so the Companies list
  drives the same component with its own filters; a group marked `inMore`
  renders inside the More filters panel, which the Companies page has
  none of.
- **Add-job popup.** Replaces the JOZ-278 shell with the full flow: a
  posting-link `TextField`, Cancel/Add job, and the five README states
  (ready, reading, not a link, already on your board, couldn't read). For a
  posting that was saved but could not be read, Try again retries extraction
  for that saved record rather than resubmitting to intake; this covers both
  a 201 whose ingest_state came back failed and a 503 (extraction could not
  even start), so an ordinary retry never risks a duplicate record and a
  forced retry does not resubmit intake either. Wired to the same
  `POST /api/jobs/intake` endpoint the old inline field used.
- **Inline "Posting URL" field removed.** Now that the popup has the same
  capability, the pre-existing field and Add button below the board are
  gone (fewest-elements); intake lives only behind the plus button.

## States

Board/list, empty board and no attention matches follow the sketch above.
Duplicate intake opens a choice dialog for the subset of duplicates not
already resolved inside the add-job popup (JOZ-279); pending, failed and
company-review chips identify unfinished work. Mutation failures revert and
show a toast.

## Open questions

The recorded navigation follow-up and Jinja cutover await the later audit.

## JOZ-280: job card links now depend on the React flag

Card titles have always linked to `/jobs/<id>`. Before JOZ-280 that always
served the Jinja job detail page, flag or no flag. After JOZ-280 it serves
the React Job detail page when `CAREEROS_REACT_UI=1` and the build exists,
and otherwise 404s — the Jinja detail page is removed outright rather than
kept as a flag-off fallback (an intentional difference from this board's
own dual-mode `/jobs`; see [Detail pages](detail-pages.md)). The board
itself is unaffected either way.
