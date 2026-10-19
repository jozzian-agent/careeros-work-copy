---
type: Decision
title: "JOZ-273 — Gestalt integration mode: decision note"
description: "Record the approved full React integration of Gestalt."
timestamp: 2026-10-11
status: approved 2026-10-10
---

# JOZ-273 — Gestalt integration mode: decision note

Status: DECIDED. Owner decision 2026-10-10: option C, full React front end
on Gestalt. Recorded in PROJECT.md (Expensive decisions).

Consequences of C:

- Flask becomes a JSON API; the 11 Jinja templates are rewritten as React
  pages using real Gestalt components (blue/purple theme per PROJECT.md).
- A JS build toolchain (npm, bundler) enters the repo for the first time.
- JOZ-274 (cards) and JOZ-275 (buttons/messages) fold into the rewrite as
  Gestalt components (Card, Button, Toast) instead of CSS-only passes.
- The Playwright/JS-harness tests need porting page by page. (The UI smoke
  script this line also named, `scripts/verify.py`, was retired 2026-10-16
  rather than ported: see PROJECT.md.)
- Batches A–D remain the source of truth for behavior; the rewrite must
  preserve every owner-approved interaction.

## The situation

The app is server-rendered Jinja with plain CSS and vanilla JS. There is no
build step, no npm, no React anywhere. Styling already lives in one place
(`careeros/web/theme.py` + `ui.py`) as a small CSS-variable token layer
(`--bg-page`, `--accent-indigo`, `--status-success`, ...) plus component
classes (`.card`, `.chip`, `.toast`, `dialog`).

Gestalt (gestalt.pinterest.systems) ships as React components + a design
token package. Its tokens are plain CSS variables and can be used without
React; its components cannot.

## What exists today (registry seed)

| Component | Class/markup in use | Count across templates |
|---|---|---|
| Card | `.card` (+ `.wide`, `.ai-summary`) | 32 |
| Button | `<button>` + `.primary` / `.danger` | ~20 |
| Chip | `.chip` (+ `.chip-local`, `.company-review-chip`) | 29 |
| Toast/message | `.toast` (+ `.toast.error`) | 1 helper |
| Input/label | `label input`, `label textarea` | many |
| Dialog | native `<dialog>` styled once | 2 |
| Layout | `.grid`, `.row`, `.stack`, `.spaced` | 75+ |

Ad-hoc variants that the migrations (JOZ-274/275) must absorb:
`.position` (job-card variant of `.card`), `.empty-state`, `.salary-badge`,
`.retry-ingest`, `.ingest-failed`, `.external`.

## Options

### A) Gestalt tokens + patterns, no React — RECOMMENDED

Adopt Gestalt's design token values (colors, spacing, radii, typography
scale) mapped onto the existing CSS variables, and copy Gestalt's component
*patterns* (card, button, chip, toast states) into the existing CSS
classes. One registry doc lists every component class; new UI picks from
it first.

- Cost: smallest. No new dependency, no build step, no runtime JS added.
  One token-mapping pass in theme.py + registry doc.
- Risk: "visual parity" is pattern-level, not pixel-level; Gestalt updates
  must be ported by hand (we rarely want them anyway).
- Fit: matches AGENTS.md reuse ladder — extends the existing token layer
  (step 3) instead of adding a stack (step 7).
- JOZ-274/275 become pure CSS/markup consolidation passes.

### B) React islands with real Gestalt components

Keep Jinja pages but mount React on interactive spots (edit mode, dialogs,
toasts) using actual Gestalt components.

- Cost: high. npm + bundler into a repo with zero JS build today; two
  rendering models on one page; every migration touches both stacks.
- Risk: mixed-stack complexity contradicts the one-principle (more
  elements, not fewer); Gestalt's React components assume their own layout
  system.
- Fit: only if we expect the interactive surface to grow a lot.

### C) Full React front end on Gestalt

Rewrite all 11 templates as a React SPA against a JSON API.

- Cost: largest by far; every page, every test, every UI smoke-script step
  rewritten. Weeks, not a batch.
- Risk: throws away working, tested, owner-approved surfaces (batches A–D).
- Fit: none at current scale. Park unless the product direction changes.

## Recommendation

Option A. It is the only option that removes elements rather than adding
them, it builds on the token layer that already exists, and it unblocks
JOZ-274/275 immediately as CSS-only passes.

## If A is chosen, the registry section will name these first

card, button, message/toast, input — plus chip, dialog, layout
primitives, each with its allowed variants and the rule: new UI picks from
the registry first; additions need a recorded reason.

## Badge usage

Owner decision 2026-10-13: colored badges are reserved for two cases.
The first is an owner-action signal, such as the "Needs your input"
recommendation badge on a job's company link. The second is a
provenance marker on a detail page, such as the "AI-generated" info
badge on the job detail page.

A quiet chip must never alarm: it uses subtle text, a transparent or
secondary-base background, and a container-level border at most, never a
colored badge type. It is what a machine-state notice uses, such as
extraction failed or details filling in.

Board cards carried neutral information tags for industry, size,
function and salary until 2026-10-18. They do not any more: see "Jobs
page, 2026-10-18" below. The rule the removal leaves is that a board
card states what identifies the posting and what the owner has to act
on, and nothing a filter above the board or the detail page already
says.

## Detail-page updates

Owner decision 2026-10-14, approved with the detail-pages canvas: the
entries below are adopted for the Job and Company detail pages. They
change existing components rather than adding a second way to do the
same thing.

| Entry | What it is | Rule |
|---|---|---|
| Dashed AI label (`AiLabel.jsx`) | `AI-generated` for text a model composed, `AI-extracted` for text it lifted out of the posting | A dashed outline and subtle text, no fill and no colour of its own. A provenance marker is not an owner action, so it must not read like the violet "Needs your input" signal. Replaces `SectionCard`'s plain `label` badge. |
| Level tag (`LevelTag.jsx`) | One requirement or skill, filled for a must-have and outlined for a nice-to-have | Colour never carries the must/nice difference: both levels use the same neutral container colours and brand blue is never used for either, because blue is this system's primary-action colour. The fill carries it visually, and a visually hidden "Must-have:" / "Nice to have:" prefix carries it for everyone else. |
| `SectionCard` variant `needs-input` | The one ask a detail page makes of its owner | Violet wash with a violet border, exactly one action set, rendered only when there is something to ask. A page never shows two at once; which ask wins is decided in the backend context, not by section order. |
| `SectionCard` padding | 24px | Was 16px. |
| Detail-page content column | 960px (`DETAIL_MAX_WIDTH`) | Was 880px. One constant, shared by the Job, Company and Experience pages. |
| `DetailHeader` Delete | Gray secondary, same weight as Edit | `color="red"` maps to the brand fill in this theme (see `frontend/src/design/theme.css`), so the page's most destructive action rendered as its primary one. |
| `FitChip` read-only variant | "Not calculated yet" in neutral colours | Fit scoring is not built. The page says so rather than showing a control that stands for a feature that does not exist, and it stays out of violet because nothing is being asked of the owner. The violet "Needs your input" variant is still what the board shows for a missing owner rating. |
| Dashed empty state | `SectionCard`'s `EmptyState`, now with one optional action inside the box | Reused for the Notes section ("Add a note"), not re-invented per section. |

### Recorded token override

`--color-icon-brand-primary` is rebound to `--color-brand-primary` in
`frontend/src/design/theme.css`. Gestalt's brand icon token is still
Pinterest red, so the detail pages' back-link arrow (an `Icon`
`color="brandPrimary"`) rendered red beside its blue link text. The brand
here is blue.

## Jobs board D7

Approved 2026-10-15 with the board canvas (claude.ai artifact
7PBPPwtEXZEmQdeNXd4b8S), by prose: the entries below were built from the
design brief the canvas approved, and the artifact itself was never opened
by the agent, so conformance to the canvas is confirmed at the owner
click-test, not here. Where that canvas and this document disagreed,
the canvas won and the entries below are the change. They alter the
components the board already had rather than adding a second way to do
the same thing.

| Entry | What it is | Rule |
|---|---|---|
| `KanbanBoard` column list | Five open columns, 320px each, in payload order | The columns are the open statuses, never the whole status list. Which statuses those are comes from the payload (`statuses` minus `ended_statuses`), so the board cannot disagree with the vault. |
| `KanbanBoard` empty column | "No jobs here yet. Drag a job here." | Was "No jobs here yet". The invitation is dropped in the phone layout, where nothing is draggable. |
| `KanbanBoard` labelled column | `role="group"` with "Status, N jobs", singular at one | A column is a region a screen reader can name, since the column IS the filter and the count is the information. |
| Ended lane (`EndedLane.jsx`) | A collapsible lane pinned to the right edge of the board | Collapsed on every load, and nothing remembers the choice, by owner decision. Rebuilt 2026-10-18: see "Jobs page, 2026-10-18" below for the grey full-height lane that replaced the floating white card. |
| `JobCard` closed row | "Posting closed" as the quiet chip, or a warning chip reading "Closed N days ago" | Which of the two shows is the payload's decision (`closed_review`), never the card's own date arithmetic, so the chip and the banner cannot disagree. |
| `JobCard` compact variant | The Ended lane's card: status select, title, company, reason | An ended job needs nothing said about its posting or its enrichment. It keeps the status select, because moving it back must have a keyboard route. |
| `JobCard` fit chip | Still hidden | Fit scoring is not built (owner decision M0-4, 2026-10-15). The chip returns with the scoring. |
| `StatusSelect` list | The eight D7 statuses, with a divider before Won, Rejected and Stopped | The divider is a labelled `Dropdown.Section` ("Ended"), so the grouping is announced and not only drawn. Picking one of the three runs the same ending flow a drop on the lane runs. Both new props are defaulted, so a caller whose payload cannot say which statuses end a job (the Job detail page) still gets the flat list. |
| `FilterBar` toggles | A list of plain toggle chips after the divider, not one fixed needs-attention pair | The board passes "Needs attention" and "Hide closed postings"; the Companies directory passes its own one. Clear all resets every toggle with the groups. |
| `FilterBar` Fit facet | Removed | No job carries a fit, so the facet grouped every job under one option. It returns with the scoring, like the card chip. |
| `FilterBar` count | An optional summary while no filter is on | The board shows the open and ended split there. Once a filter is on, the "N of M" form wins, because the count has to describe what is shown. |
| `Message` second action | One extra text action beside the primary one | For "Moved to Stopped [Add a reason] [Undo]". `BannerSlim` takes exactly one `primaryAction`, so the second action rides inside the message node rather than a second banner component existing for one row. |

### Recorded overrides

| Override | Reason |
|---|---|
| The warning closed chip uses `--color-background-warning-weak` and an alert icon, against "Badge usage" above (a machine-state notice must never alarm) | The canvas asks for it, and it is the one closed-posting case that wants the owner's attention: a posting gone for over a week on a job they never applied to. Every other closed posting keeps the quiet chip. |
| `StatusSelect.css` draws a rule above the Ended section of the status dropdown | `Dropdown.Section` adds space above itself and no divider, and the canvas asks for a divider. The selector is keyed to the dropdown's own id, so no other `Dropdown.Section` in the app is restyled. |


## Jobs page, 2026-10-18

Approved with the "Jobs board", "Page title A: no box", "Ended lane A:
grey, full board height" and "Ended lane A while dragging" artboards on
the board canvas (claude.ai artifact 7PBPPwtEXZEmQdeNXd4b8S). Every
entry changes a component the app already has. Where the brief and the
artboard disagreed, the brief won and the entry says so.

### Buttons: the one filled blue element on a screen

Primary blue is the fill of the one main action on a screen, and never
of a selected state. A selected view, a selected filter and a selected
toggle are states, not actions.

On the Jobs page that one action is "Add a job". Board and List used to
be `ButtonToggle`, whose selected state this theme binds to the brand
fill (`--color-background-button-selected-default`), so choosing a view
looked like the page's main action and there were three filled blue
buttons above the board.

An overlay with its own main action keeps one of its own: the Apply
button of a filter popover and the "Show N jobs" button of the More
filters panel are each the one main action of that panel. A chip's count
pill is not an action and is not covered by the rule; it is aria-hidden
decoration inside the chip it belongs to.

### FilterBar: the one selected style

| Entry | What it is | Rule |
|---|---|---|
| `FilterChip` selected | The wash-blue ground with a 2px brand-blue border and the default text colour | One style for every selected toggle in the app: the Board and List pair, Needs attention, Hide closed postings, the Sector, Size and Open jobs filters on Companies, and every later toggle. It is the style the Function filter already had when active. |
| `FilterChip` unselected | The neutral chip: secondary-base ground, no visible border | The border is present and transparent in this state, so selecting a chip never changes its size and the row never reflows. |
| Board and List pair | Two `FilterChip`s in a `role="group"` labelled "View", each carrying its own `aria-pressed`, 16px to the right of "Add a job" | One pair rather than two independent buttons, because exactly one of them is true. |
| Tiles and List pair (Companies, 2026-10-19) | The same pair, same group label, same 44px height, as the first row under the title | Companies has no main action, so the pair is the whole of that row; it still never carries the primary fill, because a chosen view is a state (B4). |
| Filter bar divider | Rendered only when the bar has at least one toggle | Companies' bar has none since B5, and the All jobs tab has one; a rule with nothing after it is a line that means nothing. |

### Page header: no white band

| Entry | What it is | Rule |
|---|---|---|
| `PageLayout.jsx` | The frame every list page sits in: an H1 on the page ground, the header rows under it, then `main` | Replaces Gestalt's `PageHeader` on Jobs, Companies, Experiences, Notes, Taxonomy and Search. `PageHeader` draws a white band with its own horizontal padding, so the title sat in a box and further in from the left than the content under it. The left edge is a property of this one component, which is what keeps the title, the toolbar and the content sharing it. |
| Header stack metrics | 24px top, 32px sides, 16px bottom, 16px between rows | From the artboard. `main` is 32px sides and 32px bottom with no top padding of its own, because the stack's bottom padding is the gap between them. |
| Page title | `Heading size="600" accessibilityLevel={1}`: 28px bold, 36px line height | Gestalt maps size 600 to an h2 by default, and this is the page's one top-level heading. |

### Overlays: every popover in a Layer

| Entry | What it is | Rule |
|---|---|---|
| `FloatingPopover.jsx` | Gestalt's `Popover` inside a `Layer` | Every `Popover` in the app renders through here. Gestalt's `Popover` defaults to `disablePortal: true`, so a panel renders inline in the DOM of whatever opened it with no z-index of its own; `Layer` mounts it in a div appended after `#root`, so tree order puts it above everything the page draws. No explicit `zIndex`, so Layer-mounted overlays stack among themselves in mount order and nothing has to keep a scale of numbers in step. |
| `MoreFiltersPanel` | `OverlayPanel` inside a `Layer`, for the same reason | Gestalt renders `OverlayPanel` inline too. This one is opened from the filter bar, earlier in the page than the board, so while the Ended lane was still a sticky item of the board it painted over the panel and swallowed its footer button. |
| `Dropdown` | Unchanged | Gestalt already wraps `Dropdown` in a `Layer` itself, so the card's status select was never affected. |

### Ended lane: grey, full board height

| Entry | What it is | Rule |
|---|---|---|
| Collapsed lane | 168px wide, the secondary ground, no border, 16px rounding, the full height of the board | The brief's 168px, not the artboard's 120px: three count rows need it. No border, because the ground is what the lane is drawn with. |
| Lane header | "Ended" and the count on the column titles' own baseline, under a 2px grey rule | The same wrapper a `KanbanBoard` column header uses, so the two titles and their rules land on one line. The rule is grey where a column's is brand blue, because the lane is not one of the statuses being worked. |
| Lane counts | Won, Rejected and Stopped, one row each, label left and number right | They used to wrap onto two lines each in a 72px strip. |
| Lane actions | A white `Show` button, then "Drop a job here to end it" in 12px subtle text | |
| Lane position | The last cell of the board's outer flex row, a sibling of the scrolling columns area, with `align-self: stretch` | It reserves its own width and the scroller takes what is left, so the columns end before the lane and never slide under it, and `align-self: stretch` still gives the lane the board's full height, which is the height the scroller's columns define. A sticky item inside the scroller passed the height check but painted over the Interview column at 1280px, and an earlier sticky attempt covered the More filters panel; plain flex layout needs no positioning and no z-index. |
| Lane drag-over | The wash-blue ground, a 2px dashed brand-blue outline, and "Drop to end" | The same dashed outline a column shows. |
| `KanbanBoard` row | A plain flex row rather than Gestalt's `Flex`, inside a scrolling box that is itself one cell of the board's outer flex row | `Flex` wraps every child in a block div of its own to space them, and a wrapped child cannot be stretched to the row's height. The outer row holds two cells: the scrolling columns area, which grows, and the lane, which does not. |

### Job card

| Entry | What it is | Rule |
|---|---|---|
| `JobCard` top row | 32px tall: the "Needs your input" chip on the left when the job is waiting on the owner, the status select on the right | The row keeps its height with no chip in it, so the select sits on one line across a column of cards. |
| "Needs your input" chip | Violet wash with a violet ring, 24px, 12px bold text | It reads the payload's own `needs_attention`, which is what the filter bar's "Needs attention" chip counts, so the chip and the filter cannot disagree. It replaces the violet `Badge` that used to sit beside the company link on a board card; the list view still shows that badge, having no top row. |
| `StatusSelect` control | A native button: 112px wide, 32px high, 8px radius, a hairline border, a white ground, 12px bold text, and a chevron | Was a Gestalt `Button color="gray" size="sm"`, which drew a large grey pill with no room for a chevron and read as a filled chip rather than as a select. The dropdown it opens is unchanged. Grown to 44px at phone widths, where a finger is the pointer. |
| `JobCard` company link | 14px bold in link blue | |
| `JobCard` meta line | One line: a pin and the location, then "Added 14 Oct" | Day and short month, with the year only when it is not the current one (`src/dates.js` `shortDate`). The location shows each part once and leaves Switzerland out while anything else is left (`src/location.js` `displayLocation`); display only, the stored value is never touched. |
| `JobCard` badge row | Removed | The sector, size, salary and function badges wrapped past the edge of a 320px card, and each of them is a filter above the board or a line on the detail page. The separate "Posted" line went with them: the card says when the job entered the board, which is the date the owner reads it by. |
| `JobCard` ingest indicator | Kept | Not a badge: a failed read is a visible state with a Try again beside it, and the board has no other route to that retry. |

### Recorded token overrides

| Override | Reason |
|---|---|
| `--color-background-popover-primary`, `--color-border-popover-primary` and `--color-background-elevation-floating` are rebound to `--color-background-card` in `frontend/src/design/theme.css` | Gestalt aliases the popover ground to `--color-background-default`, which this theme already binds to the card, but `DesignTokensProvider` re-emits every token as a resolved literal on `:root`, which bypasses the alias: light mode got Gestalt's stock white and dark mode its elevation-floating grey, which is this system's secondary ground and not its card. Binding the three directly makes a popover the card surface in both schemes. `--color-border-popover-primary` is Gestalt's name for the caret's fill, not a border, so it follows the ground. |

## All jobs and the company Unknown state, 2026-10-19

B2 and B5. No new component: both entries are an existing one used
somewhere new, or one removed.

| Entry | What it is | Rule |
|---|---|---|
| All jobs grid | The board's own `JobCard` in `repeat(auto-fill, minmax(320px, 1fr))`, 16px gap, inside the shared `PageLayout` | 320px is the board column's own width, so a card reads the same in either place. Not a `KanbanBoard`: a column per status would be a column of empty promises for the postings nobody has added yet. |
| `JobCard` add action | `Button size="sm" color="gray"` reading "Add to my jobs", in the slot the status select holds on a card of the reader's own | Gray, not the primary fill: the page has no main action, and adding one posting is not the page's purpose (A1). The accessible name carries the job title, so a grid of them is distinguishable. |
| `JobCard` off-board card | No "Needs your input" chip, no ingest indicator, no drag | Each of those is about a record this reader does not hold; the retry behind the indicator is owner-scoped and would answer not-found. |
| Company needs-input card | **Removed** | The violet `SectionCard variant="needs-input"` is no longer rendered on a company (B5). The variant itself stays: the Job page's one ask is still the card it was made for. |
| Company "Needs your input" chip | **Removed** | The header chip and its `#needs-your-input` anchor go with the card. `NeedsInputChip` keeps its one caller, the Job page. |
| Classification actions | "Set it yourself" (`color="gray" size="sm"`) and "Try again" (`color="transparent" size="sm"`), inside the collapsed Classification section, shown only while something reads Unknown | Transparent is the quiet the brief asks for: a retry is an offer, not the thing the owner came for. While both values are known the section shows the plain "Edit classification" instead -- two labels for one popup would be one element too many. |

## Log in and the logout affordance (M1)

Proposed 2026-10-17 with the accounts milestone. Two new visible
elements, both built only from components this app has already adopted,
so nothing below is custom and nothing is restyled for one surface. The
brief fixes the look in one sentence: the login form is plain fields and
one primary button, no new visual language.

| Entry | What it is | Rule |
|---|---|---|
| Log in page (`pages/Login.jsx`) | `Heading`, one `Text` line, two `TextField`s, one primary `Button` | Plain fields and one primary button. The `Button` is `type="submit"` inside a real `form`, so Enter in either field signs in. |
| Log in error | `BannerSlim type="error"` with the server's one message | The same banner every popup already shows a failed write in. One message for every refused attempt, so the page cannot be used to find out who has an account. |
| Log in page chrome | None | It is the one route outside the shared `Page` wrapper, so it shows no nav. Every link a nav could offer leads back here until there is a session. |
| Logout affordance (`Nav.jsx`) | One `Button size="sm" color="transparent"` in the app header | The chrome every page already renders, not a settings page and not a menu: a menu holding one action is a container earning nothing. Transparent, because signing out is not the thing a person came to the page to do. |

The password field shows Gestalt's own "Show password" control. That
comes with `TextField type="password"` rather than being an element this
page added, and it is kept rather than suppressed: a typed password
nobody can check is how a tester ends up locked out of an account the
admin just made for them.

The no-build rendering of the same page (served when `frontend/dist` is
absent, the way `/jobs` already falls back) uses no CSS of its own. The
shared control styles in `careeros/web/ui.py` already cover a label, an
input and a primary button, so the fallback is a second rendering of one
page rather than a second visual language.
