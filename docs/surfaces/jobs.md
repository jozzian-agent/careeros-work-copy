---
type: Surface
title: "Jobs"
description: "Describe the approved React Jobs board and its acceptance state."
timestamp: 2026-10-15
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

- **Fit chip. Removed 2026-10-15 (owner decision Q14).** The card used to
  show a read-only fit chip: one of three rated states (`no_fit`,
  `lucky`, `excellent`, icon plus label on a brand-coloured background)
  or, when the job had no fit yet, a "Needs your input" chip. Nothing
  writes a job's fit, because fit scoring is not built, so every card
  showed the unrated state and asked the owner for a rating they have no
  way to give. The card now says nothing about fit until the scoring
  milestone lands. The Job detail page keeps its own honest placeholder
  ("Not calculated yet", backend-owned via `fit_placeholder`), which is
  the one place that answers the question without pretending the feature
  exists.
  The filter bar's Fit facet stays: it still renders, and removing a
  working control is a separate decision from removing a chip that stood
  for nothing. With no job carrying a fit, every job groups under the
  facet's unrated option, so the facet filters nothing in practice. It is
  listed here as an open question rather than quietly dropped.
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

## D7 statuses and the closed posting (backend, 2026-10-15)

Owner decision D7 and the [board brief](../briefs/2026-10-15-jobs-board-d7.md)
reworked the status list and made a closed posting a flag. This is the
backend half, which is built. **The board layout the brief draws -- five
open columns, the Ended lane, the ending chooser, the reason popup, the
closed-postings banner and its review popup, "Your search so far" and the
phone layout -- is the frontend chunk and is not built yet.** The React
board still renders one column per status, so it shows eight columns
until that chunk lands.

### Statuses

New, Interested, Applied, Interviewing, Offer, Won, Rejected, Stopped, in
that order (`vault.STATUSES`, with `vault.STATUS_LABELS` for the words).
Stopped replaces Withdrawn. Closed is not a status: a posting that is gone
is a fact about the posting, so it is the `closed` flag below.

Open means not ended. `vault.ENDED_STATUSES` is Won, Rejected and Stopped,
and `vault.OPEN_STATUSES` is derived from it, so the board split, the
status select and the [Companies list](companies.md) open-jobs count all
read one definition. A stored status outside the eight is refused by
`vault.save_job`; a vault written before D7 is moved onto the list by
[its runbook](../runbooks/migrate-board-d7.md), once.

### The closed flag

A job record carries `closed` (boolean), `closed_at` (the day the posting
was found gone), `closed_reviewed_at` (the day the owner kept the job
anyway) and `end_reason` (one of the suggestions, or null).

- The watcher sets `closed` and `closed_at` when it finds a posting gone,
  and leaves the status alone: ending a job is the owner's decision.
- `closed_at` keeps the day the posting was FIRST missed, which is the day
  the week below is counted from.
- The flag is never cleared by the product. Nothing clears it if a posting
  comes back online, which is an open question below.

### What the board payload carries

`GET /api/jobs?view=board` adds to the keys it already had:

- `status_labels`, `ended_statuses`: the words, and which statuses belong
  in the Ended lane.
- `counts`: the split the filter bar shows, as "N open · M ended".
- `end_reasons`: the suggestions per ended status, and `end_note_title`
  the title the free text beside them is saved under as a note.
- `closed_review`: the banner and review-popup list. One row per job the
  owner has not applied to (a status before Applied), whose posting has
  been gone for more than 7 days, and which they have not kept, as
  `{id, closed_at, days_closed}`. This is the same set whose card shows
  the warning chip rather than the neutral one, so the chip and the banner
  cannot disagree, and `days_closed` is counted here so the card wording
  and the threshold count the same days. A closed job with no `closed_at`
  is left out: without the date there is no week to measure.
- `search_so_far`: `applied_to`, `interviews` and `offers`, counted over
  each job's history (both sides of every recorded move, plus its current
  status) so an ended job still counts for the interview it got, plus
  `top_stopped_reason` as `{reason, count}`. That last key is absent while
  no stopped job carries a reason.

Every entry keeps the whole job record, so `status`, `closed`,
`closed_at`, `end_reason` and `closed_reviewed_at` ride along with it.

### Moving a job, and the reason

The existing `PUT /api/jobs/<id>` takes every D7 status, and the ending
flow needs no endpoint of its own:

- A move records history in plain words, "Status changed from Applied to
  Stopped".
- `end_reason` on the same or a later PUT records "Stopped: Salary or
  conditions". Saving the same reason again records nothing.
- The free text beside a reason is an ordinary dated note
  (`POST /api/jobs/<id>/notes`), under the `end_note_title` title, not a
  second note store and not a field.
- The Keep action is a PUT of `closed_reviewed_at`, which takes the job
  out of `closed_review` and leaves its flag alone.
- Won needs no backend behaviour: the confirmation is the front end's, and
  nothing happens to any other job.
- "Hide closed postings" is a filter over the payload, so there is nothing
  behind it here.

## States

Board/list, empty board and no attention matches follow the sketch above.
Duplicate intake opens a choice dialog for the subset of duplicates not
already resolved inside the add-job popup (JOZ-279); pending, failed and
company-review chips identify unfinished work. Mutation failures revert and
show a toast.

## Open questions

The recorded navigation follow-up and Jinja cutover await the later audit.

- "Your search so far" reads history, which the vault caps at 50 entries per
  job. A very long-lived job could age out of its own applied/interviewing
  evidence and under-count. No live job is near the cap yet; revisit if the
  numbers ever disagree with a hand count.
- Clearing a stored ending reason takes `end_reason: null` on the job PUT;
  the empty string is rejected like any other off-vocabulary value.

- Does the filter bar keep its Fit facet while no job carries a fit? The
  chip and its popover still work, and the facet is left in place rather
  than removed on an agent's judgement (M0-4 was scoped to the card), but
  it currently groups every job under one option. The D7 brief answers it
  for the reworked bar (no Fit filter until fit exists); the facet is on
  the board until the frontend chunk lands.
- Nothing clears a job's `closed` flag if the posting comes back online.
  The watcher sets it, and the Keep action only quiets the warning. D7
  does not say what should happen, so nothing was built for it.
- An ended job keeps the reason it was given when it is dragged back to an
  open column. The record keeps what the owner said rather than being
  rewritten behind them, and only a stopped job's reason is counted in
  "Your search so far", but no surface shows a reason on an open card.

## JOZ-280: job card links now depend on the React flag

Card titles have always linked to `/jobs/<id>`. Before JOZ-280 that always
served the Jinja job detail page, flag or no flag. After JOZ-280 it serves
the React Job detail page when `CAREEROS_REACT_UI=1` and the build exists,
and otherwise 404s — the Jinja detail page is removed outright rather than
kept as a flag-off fallback (an intentional difference from this board's
own dual-mode `/jobs`; see [Detail pages](detail-pages.md)). The board
itself is unaffected either way.
