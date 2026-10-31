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
  pages using real Gestalt components (the theme they were rewritten under
  was superseded by the 2026-10-26 handover, which makes the brand
  Matchacado green; see "Tokens, the bridge and the restyle, 2026-10-29"
  below).
- A JS build toolchain (npm, bundler) enters the repo for the first time.
- JOZ-274 (cards) and JOZ-275 (buttons/messages) fold into the rewrite as
  Gestalt components (Card, Button, Toast) instead of CSS-only passes.
- The Playwright/JS-harness tests need porting page by page. (The UI smoke
  script this line also named, `scripts/verify.py`, was retired 2026-10-16
  rather than ported: see PROJECT.md.)
- Batches A–D remain the source of truth for behavior; the rewrite must
  preserve every owner-approved interaction.

## The situation at the time of the decision (2026-10-10)

Historical: this describes the app *before* the decision. The repo today is
the React SPA the decision produced (`frontend/`, npm build, Gestalt
components); the Jinja templates and their component classes named here are
gone from the front end.

The app was server-rendered Jinja with plain CSS and vanilla JS. There was
no build step, no npm, no React anywhere. Styling lived in one place
(`careeros/web/theme.py` + `ui.py`) as a small CSS-variable token layer
plus component classes (`.card`, `.chip`, `.toast`, `dialog`).

Gestalt (gestalt.pinterest.systems) ships as React components + a design
token package. Its tokens are plain CSS variables and can be used without
React; its components cannot.

The pre-decision options comparison and the inventory of Jinja component
classes that used to stand here were removed by CAREER-119: the decision
is recorded above, the planned component-registry doc never materialised
(the fewest-elements rule below is what governs component choice instead),
and keeping the superseded argument made the note contradict the repo it
describes.

## The decision as the repo is today (updated 2026-10-31, CAREER-119)

- **Full React front end on Gestalt** (option C, owner decision
  2026-10-10). Flask is a JSON API; the pages are React components in
  `frontend/src` built on Gestalt, with a design package imported under
  `docs/design/` (CAREER-120).
- **Brand tokens live in `frontend/src/design/tokens.css`**: Matchacado
  green `#008753` (`--color-brand-primary`) on ground `#f6fdf5`
  (`--color-background-page`), light theme only at launch; the dark block
  still carries the old palette deliberately (see "Unchanged, deliberately"
  below). The Gestalt bridge (`frontend/src/design/theme.css`) binds the
  **informational** colour to the brand (owner ruling, 2026-10-26
  handover); warning and error are *not* brand colours — they keep their
  own wash and text tokens, bound through
  `--color-background-box-{warning,error}-weak` and
  `--color-icon-{warning,error}` so banners read from this theme rather
  than from Gestalt's stock palette by coincidence.
- **Gestalt is pinned at exactly `177.0.12`** (`frontend/package.json` +
  `package-lock.json`, installed with `npm ci`), and a hashed class
  (`.Il7`, Gestalt's primary-button fill) ties `theme.css` to that version.
  A version bump cannot pass silently: `frontend/tests/theme.spec.js`
  asserts rendered colours and computed contrast ratios, so a class or
  palette that moved under the theme fails the suite loudly.
- **Fewest-elements rule** (owner directive): one `Button` (Gestalt's), one
  `Message` (`frontend/src/components/Message.jsx`), and `JobCard` as the
  one card on the jobs pages — one component per class, applied everywhere,
  never per-page variants. The planned shared pieces (SegmentedControl,
  CollectionPage, the Dialog pattern, CompanyTile, the fixed-height card
  rule) are tracked in CAREER-118 and specified under `docs/design/`.
- **The Flask-rendered pages carry the same palette** (CAREER-115):
  `careeros/web/theme.py` holds a copy of the light `:root` block of
  `tokens.css`, and `tests/test_light_theme.py` pins the token-to-token
  mapping, so neither file can move without the other failing the suite.

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
| Level tag (`LevelTag.jsx`) | One requirement or skill, filled for a must-have and outlined for a nice-to-have | Colour never carries the must/nice difference: both levels use the same neutral container colours (`--color-background-secondary-base`, transparent, `--color-border-container`) and the brand colour is never used for either, because the brand is this system's primary-action colour. No teal and no blue appears here at all. The fill carries the difference visually, and a visually hidden "Must-have:" / "Nice to have:" prefix carries it for everyone else. |
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
`color="brandPrimary"`) rendered red beside its link text. The brand here
is Matchacado green (`#008753`); it was blue until the 2026-10-26
handover, and the rebinding is what makes the arrow follow it either way.

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

### Buttons: the one filled brand element on a screen

The brand fill is the fill of the one main action on a screen, and never
of a selected state. A selected view, a selected filter and a selected
toggle are states, not actions.

On the Jobs page that one action is "Add a job". Board and List used to
be `ButtonToggle`, whose selected state this theme binds to the brand
fill (`--color-background-button-selected-default`), so choosing a view
looked like the page's main action and there were three filled brand
buttons above the board.

Since the rewrite to a `FilterChip` pair, nothing in the app reads
`--color-background-button-selected-default` and nothing may: a view
switch is a state and takes the one selected style below (2026-10-29
brief, A3). The binding is kept so that a `ButtonToggle` added later for
something that *is* an action lands on the brand rather than on Gestalt's
near-black `--color-background-selected-base`.

An overlay with its own main action keeps one of its own: the Apply
button of a filter popover and the "Show N jobs" button of the More
filters panel are each the one main action of that panel. A chip's count
pill is not an action and is not covered by the rule; it is aria-hidden
decoration inside the chip it belongs to.

### FilterBar: the one selected style

| Entry | What it is | Rule |
|---|---|---|
| `FilterChip` selected | The brand wash (`--color-brand-wash`) with a 2px brand border (`--color-brand-primary`) and the default text colour | One style for every selected toggle in the app: the Board and List pair, Needs attention, Hide closed postings, the Sector, Size and Open jobs filters on Companies, and every later toggle. It is the style the Function filter already had when active. Hover does not move it: a selected chip is already showing the state a hover would announce. |
| `FilterChip` unselected | The neutral chip: `--color-background-secondary-base` ground, no visible border, darkening to `--color-background-secondary-weak` on hover | The border is present and transparent in this state, so selecting a chip never changes its size and the row never reflows. The brief (2026-10-29, B2) names the hover "fill-secondary-hover"; the ported token set has no such name and `--color-background-secondary-weak` is its one darker partner to the base, so the hover binds to that rather than to a token invented for it. |
| `FilterChip` metrics (2026-10-29, B2) | 32px high, 14px bold label, pill radius | Was 40px. The two view pairs keep the 44px they are given explicitly, which is the height of the primary button beside them (artboard 2026-10-18); 32px is the chip's own default and therefore the filter row's height. The ground and the border moved out of the component's inline style into `components/FilterChip.css`, because a hover cannot be written inline and an inline declaration would outrank the rule meant to change it. |
| Board and List pair | Two `FilterChip`s in a `role="group"` labelled "View", each carrying its own `aria-pressed`, 16px to the right of "Add a job" | One pair rather than two independent buttons, because exactly one of them is true. |
| Tiles and List pair (Companies, 2026-10-19) | The same pair, same group label, same 44px height, as the first row under the title | Companies has no main action, so the pair is the whole of that row; it still never carries the primary fill, because a chosen view is a state (B4). |
| Filter bar divider | Rendered only when the bar has at least one toggle | Companies' bar has none since B5, and the All jobs tab has one; a rule with nothing after it is a line that means nothing. |

### Page header: no white band

| Entry | What it is | Rule |
|---|---|---|
| `PageLayout.jsx` | The frame every list page sits in: an H1 on the page ground, the header rows under it, then `main` | Replaces Gestalt's `PageHeader` on Jobs, Companies, Experiences, Notes, Taxonomy and Search. `PageHeader` draws a white band with its own horizontal padding, so the title sat in a box and further in from the left than the content under it. The left edge is a property of this one component, which is what keeps the title, the toolbar and the content sharing it. |
| Header stack metrics | 24px top, 32px sides, 16px bottom, 16px between rows | From the artboard. `main` is 32px sides and 32px bottom with no top padding of its own, because the stack's bottom padding is the gap between them. |
| Page title | `Heading size="600" accessibilityLevel={1}`: 28px bold, 31px line height | Gestalt maps size 600 to an h2 by default, and this is the page's one top-level heading. |

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
| Lane header | "Ended" and the count on the column titles' own baseline, under a 2px grey rule | The same wrapper a `KanbanBoard` column header uses, so the two titles and their rules land on one line. The rule is grey where a column's is the brand colour, because the lane is not one of the statuses being worked. |
| Lane counts | Won, Rejected and Stopped, one row each, label left and number right | They used to wrap onto two lines each in a 72px strip. |
| Lane actions | A white `Show` button, then "Drop a job here to end it" in 12px subtle text | |
| Lane position | The last cell of the board's outer flex row, a sibling of the scrolling columns area, with `align-self: stretch` | It reserves its own width and the scroller takes what is left, so the columns end before the lane and never slide under it, and `align-self: stretch` still gives the lane the board's full height, which is the height the scroller's columns define. A sticky item inside the scroller passed the height check but painted over the Interview column at 1280px, and an earlier sticky attempt covered the More filters panel; plain flex layout needs no positioning and no z-index. |
| Lane drag-over | The brand-wash ground (`--color-brand-wash`), a 2px dashed brand outline (`--color-brand-primary`), and "Drop to end" | The same dashed outline a column shows. Dashed, not solid: it is the drop-target language the board already speaks, and the 2026-10-29 brief (B4) fixes the colour and the width, both of which already held. |
| `KanbanBoard` row | A plain flex row rather than Gestalt's `Flex`, inside a scrolling box that is itself one cell of the board's outer flex row | `Flex` wraps every child in a block div of its own to space them, and a wrapped child cannot be stretched to the row's height. The outer row holds two cells: the scrolling columns area, which grows, and the lane, which does not. |

### Job card

| Entry | What it is | Rule |
|---|---|---|
| `JobCard` top row | 32px tall: the "Needs your input" chip on the left when the job is waiting on the owner, the status select on the right | The row keeps its height with no chip in it, so the select sits on one line across a column of cards. |
| "Needs your input" chip | Violet wash with a violet ring, 24px, 12px bold text | It reads the payload's own `needs_attention`, which is what the filter bar's "Needs attention" chip counts, so the chip and the filter cannot disagree. It replaces the violet `Badge` that used to sit beside the company link on a board card; the list view still shows that badge, having no top row. |
| `StatusSelect` control | A native button: 112px wide, 32px high, 8px radius, a hairline border, a white ground, 12px bold text, and a chevron | Was a Gestalt `Button color="gray" size="sm"`, which drew a large grey pill with no room for a chevron and read as a filled chip rather than as a select. The dropdown it opens is unchanged. Grown to 44px at phone widths, where a finger is the pointer. |
| `JobCard` company link | 14px bold, ink-black and underlined (`--color-text-link`, `#000000`) | Since the 2026-10-26 handover the underline is what says "this is a link", not the colour. |
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

## Tokens, the bridge and the restyle, 2026-10-29

The 2026-10-26 handover replaced the blue/purple theme with the Matchacado
green brand on a light ground (`frontend/src/design/tokens.css`). This
section records the second half of that change: the Gestalt bridge
(`frontend/src/design/theme.css`) that makes Gestalt's own component
tokens read the brand, and the restyle of the components the brief names.
Nothing here is a new component, a new layout or a new behaviour. There is
no "brand blue" anywhere in this system: the brand is green, and so is the
informational colour, by owner ruling.

### The brand is the informational colour

`Badge type="info"`, `BannerSlim type="info"` and `BannerCallout
type="info"` are brand green, not Gestalt's skycicle blue. The
closed-postings banner on the Jobs board is the visible check, and
`frontend/tests/theme.spec.js` asserts its rendered ground, its icon, all
eight info tokens, and that no element on the page is painted in any of
Gestalt's three info blues.

### Recorded token overrides

Every row is a redeclaration in `frontend/src/design/theme.css`. The three
from earlier sections (`--color-icon-brand-primary`, the popover trio) are
still in force and are not repeated here.

| Override | Bound to | Reason |
|---|---|---|
| `--color-background-info-{base,strong,weak}` | `--color-brand-primary` / `-strong` / `--color-brand-wash` | The informational colour is the brand (owner ruling, 2026-10-26 handover). |
| `--color-background-box-info-{base,weak}` | the same three | **Gestalt already aliases these to the names above, and the alias does not hold at runtime.** `DesignTokensProvider` republishes every token as a resolved literal on `:root`, which bypasses it — the same trap recorded for the popover ground. `BannerSlim type="info"` reads `--color-background-box-info-weak` for its ground (`MESSAGING_TYPE_ATTRIBUTES` maps `info` to `Box color="infoWeak"`), so until this binding landed the closed-postings banner was still Gestalt's `#d7edff`. |
| `--color-background-badge-info-{default,hover}` | `--color-brand-primary` / `-strong` | Same alias, same bypass: every `Badge type="info"` ("AI-generated", the function chips) was still Gestalt's `#0074e8`. |
| `--color-background-box-{warning,error}-weak` | `--color-background-warning-weak` / `--color-background-error-weak` | A warning banner uses the warning wash and an error banner the error wash. Gestalt's stock light values happen to equal the handover's, so the pairing looked right already; binding it makes the agreement this theme's rather than a coincidence of two palettes. |
| `--color-icon-{warning,error}` | `--color-text-warning` / `--color-text-error` | The icon in such a banner is the same colour as its text, for the same reason. |
| `--color-background-button-primary-{default,hover,active}`, scoped to `[role="alertdialog"]` | `--color-text-error` (`#cc0000`), `--color-background-danger-hover` (`#a30000`) ×2 | The one red fill left in the app. Rebinding the primary-button tokens to the brand is what makes every `Button color="red"` green, which is wanted everywhere except on a button that really does destroy a record. Gestalt builds a `ModalAlert`'s primary action as `Button color="red"` and renders the alert as `role="alertdialog"`, so the role **is** the destructive case: the tokens are redeclared on the dialog element, no component grew a prop and no call site changed. A custom property declared on an element beats one inherited from `:root` whatever the root's `!important`, so none of these needs `!important`. |
| `--color-text-{inverse,default}`, scoped to `[role="alertdialog"] .Il7` | `--color-background-card` | The label on that red fill is the surface colour, measured at 5.25:1. Both names are bound because Gestalt picks between them in JS — see the `.Il7` note in `frontend/BUILD_NOTES.md`. |

`--color-background-button-selected-default` stays bound to the brand and
stays unread: see "Buttons: the one filled brand element on a screen".

### Links

Links are ink-black (`--color-text-link`, `#000000`) and underlined
everywhere, in `#root` and in the `Layer` portals alike. The underline is
what carries "this is a link", not the colour, which is why it is always
on rather than on hover.

Buttons and chips are excluded. A Gestalt `ButtonLink` is an `<a>` wearing
a button's chrome — the Experiences page's "Add position" is one — so the
anchor-wide rule drew an underline through the label of a filled pill. The
rule now skips `.USg`, the class Gestalt 177.0.12 puts on button chrome
and on nothing else, and Gestalt's own `text-decoration: none` on the same
anchor takes over. Chips need no exclusion: every chip in the app is a
`<button>` or a `<div>`, never an anchor. Nav items are `TapAreaLink`s and
really are links, so they keep the underline.

### Line heights

Each line height belongs to a font **size**, not to a heading level, and
the scale is no longer one formula. The pairs, from the 2026-10-26
handover:

| Font size | Line height | Gestalt scale |
|---|---|---|
| 12px | 16px | text-100 / heading-100 |
| 14px | 20px | text-200 / heading-200 |
| 16px | 22px | text-300 / heading-300 |
| 20px | 24px | heading-400 |
| 28px | 31px | heading-600 |
| 36px | 40px | heading-700 |

Gestalt classic ships no line height for `Text` or `Heading` at all, so
the whole scale is declared in `design/theme.css` against Gestalt's own
typography classes, plus a generic fallback for leaves outside them. Two
constraints hold it in place, both of them learned the hard way:

- **Leaf elements only.** Declaring a line height on the structural
  wrappers too perturbs layout enough that Chromium stops starting a
  native drag on the job cards — no `dragstart` fires and the board's
  drag-and-drop silently dies. `tests/jobs-board.spec.js` is what caught
  it.
- **Portals too.** Gestalt's `Layer` mounts its children in a plain `div`
  appended to `document.body`, so a `#root`-only rule leaves `Toast` text
  with no line height at all.

### Messages and popups

| Entry | What it is | Rule |
|---|---|---|
| `Message.jsx` (`FloatingMessage`) | A `BannerSlim` inside a bordered, shadowed `Box` | The border is `--color-border-container` (Gestalt's `borderStyle="sm"`) and the shadow `--elevation-floating`. No blue in any state: `info` is the brand wash, `warning` the warning wash with warning text and icon, `error` the error wash with error text and icon. |
| Popovers and overlays | The card surface (`--color-background-card`) | `--color-background-popover-primary`, `--color-border-popover-primary` and `--color-background-elevation-floating` are bound to it directly, for the alias reason above. Recorded in "Overlays: every popover in a Layer". |
| `DeleteConfirmModal.jsx` | A `ModalAlert`, the app's one delete confirmation | Its confirm is the only red fill in the app (table above); its "Keep" secondary stays the gray it was. |

### Unchanged, deliberately

The dark token block in `tokens.css` is untouched: launch is light-only
and a dark rework is its own decision, so the dark set still carries the
old names (`color-brand-wash-blue`, `-teal`, `color-brand-accent`) and the
old values. `tests/theme.spec.js` asserts them, so the day dark mode is
reworked it is a visible change rather than a drift.
