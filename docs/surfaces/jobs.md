---
type: Surface
title: "My Jobs"
description: "Describe the approved React My Jobs board and its acceptance state."
timestamp: 2026-10-15
---

# My Jobs

Surface: /jobs (React rewrite of jobs.html + job_cards.html).
Status: Approved 2026-10-10 (owner: "Go" on plan defaults + sketch).

2026-10-18 (CAREER-39 M2, owner decision D10): the surface is called **My
Jobs** in the navigation, in the page title, in the detail page's back
link and in its empty state, because the board holds the signed-in user's
own postings and nobody else's (decision D3). The route stays `/jobs` and
so do the slugs and data attributes: those are not words a person reads.
The board is scoped server-side, by `vault.Owner` on
`jobs.page_context`; the payload shape did not change, so nothing in the
behaviour contract below moves. The empty state is now "My Jobs is empty
— paste a posting link to get started.
Owner click-test: Passed 2026-10-11 on live LAN server with the real vault
("works all"). One gap found: navigation to the other pages is missing
from the React Jobs page; tracked as M0 follow-up below.

2026-10-19 (B2, CAREER-89): the section gained a second tab, **All
jobs**, which is the same payload and the same components over every job
that is not private to another user. See "All jobs, the second tab"
below; My Jobs itself is unchanged.

2026-10-12 (JOZ-278, design-brief rebuild): the board's card and status
controls were rebuilt against the handoff brief, on top of the above. See
"JOZ-278 rebuild" below for what changed; it supersedes the component
mapping and card anatomy further down where the two disagree, and
`frontend/BUILD_NOTES.md`'s "Jobs board rebuild (JOZ-278)" section has the
full implementation rationale this doc only summarizes.

## Purpose

Track jobs on the React board and list while preserving approved interactions.

## Appears in

My Jobs → add a posting, review a card, change status or open job detail.

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
│ My Jobs                    [+] [Board] [List]               │  PageHeader
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
  The filter bar's Fit facet stayed at that milestone: removing a working
  control was a separate decision from removing a chip that stood for
  nothing. With no job carrying a fit, every job grouped under the
  facet's unrated option, so the facet filtered nothing in practice. The
  D7 board brief removed it on 2026-10-15 (see Open questions below).
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

## D7 statuses and the closed posting (2026-10-15)

Owner decision D7 and the [board brief](../briefs/2026-10-15-jobs-board-d7.md)
reworked the status list and made a closed posting a flag. Both halves are
built: the vocabulary, the flag and the payload below, and the board layout
the brief draws, against the canvas the owner approved on 2026-10-15
(claude.ai artifact 7PBPPwtEXZEmQdeNXd4b8S). Where the canvas and the
design system disagreed, the canvas won and the design system was changed
in the same round; see
[design-system.md](../decisions/design-system.md) "Jobs board D7".

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

### The board layout

What the page renders, top to bottom. Component-level detail lives in
`frontend/BUILD_NOTES.md` "Jobs board D7 frontend"; this is the surface
summary.

- **Header.** The title, then "Add a job" as the one primary button (it
  opens the same popup the plus button used to), with the Board and List
  switch beside it.
- **Filter bar.** Function, Location, More filters, a divider, then the
  "Needs attention" and "Hide closed postings" toggles, and the count on
  the right. The count reads "N open and M ended" from the payload split
  while no filter is on, and "N of M jobs" once one is, because a count
  has to describe what is shown. There is no Fit facet: fit is not
  calculated, so the board offers no filter for it. "Hide closed postings"
  is off on every load and hides a flagged job wherever it sits.
- **Closed-postings banner.** One row per the payload's `closed_review`,
  shown while at least one of those jobs has not been dismissed. "Review"
  opens the popup; "Not now" hides the banner for the jobs it is asking
  about today, remembered per job id in localStorage, so a job that
  crosses the week later brings it back.
- **Five open columns**, 320px each, in payload order: New, Interested,
  Applied, Interviewing, Offer. Each column is a labelled group naming its
  status and count. An empty one invites a drop.
- **The Ended lane**, sitting outside the scrolling row at the end of the
  board so it is always a drop target (an earlier sticky attempt painted
  over the More filters popup and was dropped; see BUILD_NOTES.md).
  Collapsed on every load: a narrow strip with the total, the three
  counts, "Show" and "Drop a job here to end it". Expanded it is one
  320px column, not three, with "Your search so far" on top and Won,
  Rejected and Stopped as groups, each showing its latest three jobs by
  the day the status changed, then "Show all N". An empty group says
  "Nothing won yet" and so on. An ended card is compact: the status
  select, the title, the company and the reason, or the link that adds
  one, which is offered only for an outcome that has suggestions (Won has
  none).
- **The closed row on a card.** A closed posting shows the neutral
  "Posting closed" chip, except for the jobs in `closed_review`, which
  show a warning chip reading "Closed N days ago" with the day count the
  payload sent. The card never counts days itself, so the chip and the
  banner cannot disagree.

### Ending a job

- Dropping a card on the collapsed lane opens the chooser, "How did it
  end?", anchored to the strip. Dropping on a group of the expanded lane
  picks that outcome without asking. The status select offers the same
  three statuses under a divider and runs the same flow, which is the
  keyboard and screen-reader route.
- Won always asks first and nothing happens to any other job. Rejected
  and Stopped move at once, with a floating message carrying "Add a
  reason" and "Undo".
- The reason popup offers that status's suggestions, picked or not, plus
  free text saved as a dated note under `end_note_title`. Skip writes
  nothing. A failed save keeps the popup open with the endpoint's own
  message.
- Dragging an ended job back to an open column is an ordinary move, with
  its own Undo. The reason it was given stays on the record.

### Closed postings review

Each row shows the job, its company and "closed N days ago", with Keep and
Stop. Keep is a PUT of `closed_reviewed_at`, which takes the row out of the
list and turns the warning chip neutral; the flag is left alone, because
the posting is still gone. Stop is one PUT carrying both the status and the
reason "Posting closed". Both land on the board straight away and come back
if the write fails. "Done" closes the popup.

### Phone, below 720px

One column at a time, chosen from a chip row that scrolls sideways with
Ended as the last chip, where the lane renders already open. Nothing is
draggable, so every move goes through the status select and the empty
column stops inviting a gesture that is not there. The banner shortens to
"N closed postings to review". Popups open as full-width sheets, through
Gestalt's own mobile adaptation.

## The page as built, 2026-10-18

Approved with the "Jobs board", "Page title A: no box", "Ended lane A:
grey, full board height" and "Ended lane A while dragging" artboards.
This section replaces "The board layout" above wherever the two
disagree. The design-system entries are in
`docs/decisions/design-system.md`, "Jobs page, 2026-10-18".

### Top to bottom

1. **"My Jobs"**, as the page's H1, on the page ground. There is no white
   title band: the title, the toolbar and the board share one left edge.
2. **"Add a job"**, the one filled blue button on the page, then the
   Board and List pair 16px to its right. A selected view is a state, so
   it carries the same wash-blue ground and blue border every selected
   toggle in the app carries, never the blue fill.
3. **The filter bar.** Function, Location, More filters, a divider, then
   the "Needs attention" and "Hide closed postings" toggles, and the
   count on the right. Unchanged from the D7 section above, except that a
   toggle that is on now looks the same as the chosen view.
4. **The closed-postings banner**, when it applies. Unchanged.
5. **The board or the list.**

A page with no main action, such as Companies, shows the title row and
its filters only.

### Filter popovers

Every popover and dropdown on the page draws the card ground with the
floating shadow and sits above the board, the table and anything sticky.
In List view the Function, Location and More filters panels used to show
the table through them and let the table's header draw over their search
field. They were never transparent: Gestalt renders a popover inline with
no z-index of its own, and Gestalt's own table element carries
`isolation: isolate`, which makes it a stacking context painted in the
same pass and later in tree order. Every overlay now mounts in a Gestalt
Layer, which is appended after the application root, so tree order puts
all of them above whatever the page draws. The card status dropdown and
the "How did it end?" chooser follow the same rule.

### The Ended lane

Grey (the secondary ground), no border, 16px rounding, 168px wide, and
the full height of the board. "Ended" and the total sit on the column
titles' own baseline under a grey rule rather than the columns' blue one.
Won, Rejected and Stopped are one row each, the label on the left and the
number on the right. Then a white "Show" button, then "Drop a job here to
end it".

It is pinned to the right edge while the columns scroll, and the columns
end before it: scrolled fully right, the last column clears it with the
board's own gap. Dragging a card over it turns it wash blue with a dashed
blue outline and the words "Drop to end".

The expanded lane is unchanged and still out of scope.

### The job card

- **Top row.** "Needs your input" on the left when the job is waiting on
  the owner, and the compact status select on the right: bordered, 32px
  high, 112px wide, white, with a chevron.
- **Then** the title (at most two lines), the company as a link, and one
  line with a pin, the location, and "Added 14 Oct".
- **Last row**, when it applies: the closed chip, neutral as "Posting
  closed" or, for a New or Interested job whose posting has been gone
  more than a week, the warning chip reading "Closed N days ago".
- **No sector, size, salary or function tags**, and no separate "Posted"
  line. Four tags on a 320px card ran past its edge, and each of them is
  either a filter above the board or a line on the detail page.
- **The location shows each part once**, and leaves Switzerland out while
  anything else is left: a stored "Switzerland, Zug, Zug, Switzerland"
  reads "Zug". Display only; the stored value is never touched.

"Needs your input" on a card reads the payload's own `needs_attention`,
which is the same flag the "Needs attention" filter counts, so the chip
and the filter always mean the same jobs. Three things set it: an
unresolved company link, an ingest that got stuck, and a posting whose
heading was its careers page rather than a role, so the job has only a
provisional title (see "Stored text" below).

### Stored text

Three defects the owner found by reading their own board, all fixed at
the point extracted text is stored, with
`scripts/clean_stored_text.py` as the same rules over records written
before that:

- **No stored field holds markup.** A posting that states its own title
  with HTML in it ("...(w/m/d),&lt;br/&gt;80-100%...") or an entity escape
  in it ("Smith &amp;amp; Co") is stored as the plain text it means.
  Nothing renders a stored field as HTML, so markup in one is a defect
  and not formatting.
- **No company name holds an internal code.** Some employers prefix their
  own `hiringOrganization.name` with a site code ("CHE003 Thomson Reuters
  Enterprise Centre GmbH"). The code is dropped where a posting's
  employer name is read, so it reaches neither the job nor a company
  record created from it.
- **A careers page's name is not a job title.** "Job Offers", "Careers
  and jobs", "Stellenangebote" and the rest of that short list are page
  names. A posting whose heading is one of them keeps a provisional
  title, because a job in the vault has to have one, and the record says
  the posting evidenced no title, which is what makes the board ask the
  owner for it. The ask disappears by itself the moment anything fills
  the field.

### Not built, and why

The artboard draws a "Search jobs" field as the first control of the
filter bar. It is a static placeholder on the artboard, and no document
says what it searches, how it combines with the facets or whether it
applies to both views, so it is not built. It needs a sentence from the
owner first.

## All jobs, the second tab (B2, 2026-10-19)

Surface: `/all-jobs` (React only, like `/notes` and `/taxonomy`).
Owner decisions of 2026-10-19: the tab is called **All jobs** and sits
next to My Jobs in the nav; "universe" stays a backend word and appears
nowhere a person reads (PROJECT.md, Frame).

### What it holds

Every job record that is **not private to another user**. Concretely:

- every record with no `owner_id` — what the API adds and what the feed
  pool will add, and what a record written before the M2 split carries;
- plus the reading user's own records.

Another user's job is absent, and absent for the admin too: D3 is privacy
and not hierarchy, so a tester's postings are invisible here exactly as
they are on the board. Every per-job route answers for one of them with
the same not-found a job that never existed gets
(`vault.load_universe_job`, `tests/test_record_privacy.py`). The rule is
one function, `vault.Owner.sees_in_universe`, and it is applied
**server-side**: nothing about visibility is decided in the browser.

A consequence worth stating, because it is easy to read as a bug: for the
admin the tab is their board plus nothing, since an ownerless record is
already theirs by inheritance. It differs from My Jobs only once records
exist that no user owns — which, on the live vault today, is none: the
owner migration gave all 44 jobs to the admin.

### What it shows

The board's own parts, not a second set: the same payload
(`GET /api/jobs?view=universe`, the `view=board` shape plus one key), the
same `FilterBar` over the same facets (`frontend/src/jobFilters.js`), the
same `JobCard`, the same `PageLayout` title row.

- **One grid of cards**, not a kanban. A column per status would be a
  column of empty promises for the postings nobody has added yet.
- **A job on my board shows its status**, in the working status select,
  so a move from here is the same move as on the board.
- **A job that is not on my board offers "Add to my jobs"** in the place
  the select would be.
- **A card that is not mine says nothing about somebody else being
  asked**: no "Needs your input" chip, no ingest state and no Try again,
  because the retry is owner-scoped and would answer not-found. The
  posting's own facts — title, company, location, closed chip — read
  exactly as they do on the board.
- **Filters**: Function, Location, More filters (Industry, Company size),
  then "Hide closed postings", and the count on the right ("N open · M
  ended", "N of M jobs" once a filter is on). There is no "Needs
  attention" toggle here: the flag mostly describes records the reader
  does not hold, so it would offer to narrow to somebody else's asks.
- **No main action.** Pasting a link belongs on My Jobs, which is where
  the job a person adds lands, so this page is the title row and its
  filters (brief 2026-10-18, section 3).

### "Add to my jobs" is a copy, not a hand-over

`POST /api/jobs/<id>/promote`, the existing promote action under the
user's own word. What it does depends on whose record it is:

- **Already mine** (my own job, or an ownerless one the admin inherits):
  nothing is created. `in_pipeline` is flipped true for the Journey 2
  record shape nothing writes yet, and the record is answered as it
  stands.
- **Ownerless, and I am not the admin**: a new job record of my own,
  copied from the posting and landing in **New**, stamped with my
  `owner_id` (`vault.add_job_to_board`). 201 with my record.

**The conflict, and how it was resolved.** The brief's preference was
that promote re-stamp the ownerless record with the adding user's
`owner_id`. That contradicts M2 as PROJECT.md states it — "ownership is
stamped once and never moves" (D4), and "a record written before the
split is the admin's" — so re-stamping would take a job off the admin's
own board and would be exactly the ownership change both write paths
strip out of their payloads. Per the brief's own instruction, PROJECT.md
wins and the conflict is reported. The copy is not an invention either:
"the same posting added by two users is two private records" is already
the rule the duplicate check implements (D4), and this is that rule
applied to a posting the pool holds.

What travels onto the copy is everything the record says about the
posting. What does not: the status (New), `in_pipeline`, `added`, the
history, the notes (they belong to whoever wrote them), the AI reading
state, `end_reason` and `closed_reviewed_at`
(`vault.BOARD_COPY_EXCLUDED`). Two more rules ride along, both so the new
record is well formed: it gains a `normalized_url` when the source had
none, so it is comparable to any later paste of the same link; and a
company link it may not make (a retired company) is dropped to `pending`
with the employer name left as free text, rather than the add failing
with a company error.

A second click adds nothing: the adder's own duplicate check finds the
record they already have and answers 200 with it.

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

- Settled 2026-10-15: the Fit facet is gone. The D7 brief removes it
  until fit is calculated, so nothing on the board asks about fit any
  more, and `fit` on a job record has no reader here.
- Below 720px a popup is Gestalt's own mobile sheet, which names the
  dialog "Bottom sheet" rather than carrying the popup's own
  accessibilityModalLabel (Modal does not pass it to SheetMobile). Each
  popup still renders its heading inside, so the content is announced.
  Worth revisiting if a screen-reader pass on a phone finds it confusing.
- The ending chooser is anchored to the Ended strip rather than to the
  exact point the card was dropped on. A Popover needs an element to
  anchor to, and the strip is the element that was dropped on.
- An ended card shows "Add a reason" only for an outcome that has
  suggestions, so a won job is never asked why it ended. Free text alone
  for a won job therefore has no entry point.
- Nothing clears a job's `closed` flag if the posting comes back online.
  The watcher sets it, and the Keep action only quiets the warning. D7
  does not say what should happen, so nothing was built for it.
- An ended job keeps the reason it was given when it is dragged back to an
  open column, Undo included. The record keeps what the owner said rather
  than being rewritten behind them, and only a stopped job's reason is
  counted in "Your search so far", but no surface shows a reason on an
  open card.
- Closing one of the board popups (ending chooser, reason, review) does
  not return focus to the element that opened it. Keyboard operability
  inside the popups is tested; the focus return is a known gap, to be
  picked up in the Part 4 test audit.
- The Job detail page's status select shows the flat eight-status list
  (its payload carries no `ended_statuses`), so it can mark a job Won
  without the confirmation the board always asks for. Smallest fix is
  `ended_statuses` in the detail payload; left to the next backend chunk.

## JOZ-280: job card links now depend on the React flag

Card titles have always linked to `/jobs/<id>`. Before JOZ-280 that always
served the Jinja job detail page, flag or no flag. After JOZ-280 it serves
the React Job detail page when `CAREEROS_REACT_UI=1` and the build exists,
and otherwise 404s — the Jinja detail page is removed outright rather than
kept as a flag-off fallback (an intentional difference from this board's
own dual-mode `/jobs`; see [Detail pages](detail-pages.md)). The board
itself is unaffected either way.
