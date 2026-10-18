# Brief: Jobs page fixes and layout, plus handover for the next session

For the agent working on CareerOS. Written 2026-10-18 by the owner with a reviewing session, from testing the implemented board. Part A is ready to build. Part B holds the owner's notes for the next session. Propose your plan for Part A briefly, then build, and report with screenshots of each check.

Related briefs, still valid unless this one says otherwise:
- careeros-detail-pages-brief.md
- careeros-jobs-board-brief.md
- careeros-vision-and-mvp.md

## Design

- Canvas: https://claude.ai/artifact/7PBPPwtEXZEmQdeNXd4b8S
- Approved artboards for this brief:
  - "Jobs board": the approved layout
  - "Page title A: no box"
  - "Ended lane A: grey, full board height"
  - "Ended lane A while dragging"
- Design system: CareerOS, https://claude.ai/artifact/5j1CSeRurNtisC3QGYfbDt. Update it in the same change where noted.

# Part A: build now

## 1. One "selected" style for every toggle and choice

Board and List currently look like primary buttons when selected. Only "Add a job" is a primary action on this page. A selected view or filter is a state, not an action.

- **Every selected toggle uses one style,** the one the Function filter has when active: light blue ground, blue border, default text. This covers:
  - Board and List
  - Needs attention, when on
  - Hide closed postings, when on
  - the Sector and Size filters on Companies
  - the Tiles and List pair on Companies (see B4)
  - every later toggle
- **Unselected toggles keep the neutral chip style.**
- **Board and List form one pair,** with aria-pressed on each, 16px to the right of "Add a job".
- **Design system rule,** in Buttons and FilterBar: primary blue is only for the one main action on a screen, never for a selected state.

## 2. Bug: filter popovers are see-through

In List view the Function dropdown shows the table through it, and the table header draws on top of its search field. The same happens with Location and More filters.

- **Fix the root cause once, for every popover and dropdown.** Look for two causes: a transparent background, likely from a theme token remap, and the stacking order.
- **Popovers use the card background and the floating shadow.** They sit above the board, the table and any sticky header.
- **Check the other layered controls too:** the status dropdown on cards and the "How did it end?" chooser.

## 3. Page header without the white box, on every list page

Today the title sits in a white band, indented further than the content below it.

- **Remove the band.** The title is an H1 (28px bold) on the page ground, on the same left edge as everything below it.
- **Apply it to every list page:** Jobs, Companies, Experiences, Notes, Taxonomy and Search. Detail pages already work this way.
- **The Jobs page, top to bottom,** as on the "Jobs board" artboard:
  1. "My Jobs"
  2. "Add a job" (primary), then the Board and List pair
  3. The filter bar: search, Function, Location, More filters, a divider, Needs attention, Hide closed postings, and the count on the right ("16 open · 25 ended", or "N of M jobs" when filtered)
  4. The closed-postings banner, when it applies
  5. The board or the list
- **Pages without a main action** show the title row and their filters only.

## 4. Collapsed Ended lane: grey, full board height

The lane works well. It looks unfinished for four reasons:
- it is a floating white card
- its counts wrap onto two lines
- it does not line up with the column headers
- it covers part of the Offer column

Build it as "Ended lane A":

- **Ground.** The design system's secondary ground (#e9e9e9), no border, 16px rounding, running the full height of the board.
- **Width.** 168px.
- **Header.** "Ended" and the count, on the same baseline as the column titles, with a grey underline instead of the blue one.
- **Counts.** Won, Rejected and Stopped, one row each, label left, number right.
- **Show.** A white "Show" button, then "Drop a job here to end it" in small subtle text.
- **Layout.** The columns end before the lane and never slide under it. The lane stays pinned to the right edge while the columns scroll.
- **While a card is dragged over it.** Light blue ground, dashed blue outline, "Drop to end".
- **Update KanbanBoard** in the design system.

## 5. Job card, as on the "Jobs board" artboard

- **Top row.** "Needs your input" on the left when it applies. On the right, the compact status select from the design system: bordered, 32px high, about 112px wide. Not the large grey pill used today.
- **Then:** the title (at most 2 lines), the company link, and one line with location and "Added 14 Oct".
- **No sector or size tags on cards.** Today they run past the card edge.
- **No separate "Posted" line on the card.**
- **The closed chip as the last row.** "Posting closed" in neutral style. For New and Interested jobs whose posting closed more than 7 days ago, a warning chip instead: "Closed N days ago".
- **Location shows each part once.** "Switzerland, Zug, Zug, Switzerland" becomes "Zug". The country is left out when it is Switzerland.

## 6. Data bugs found while testing

- **Raw HTML in a title.** "Lead Business & Technology Engineering (w/m/d), <br/>80-100% Zürich / hybrid". Strip markup from extracted text everywhere it is stored, and clean the existing records.
- **An internal code in a company name.** "CHE003 Thomson Reuters Enterprise Centre GmbH" looks like a Workday tenant code leaking into the name. Find where it comes from, and fix the stored name.
- **A page heading taken as a title.** Finders' job is titled "Job Offers". Treat generic headings such as "Job Offers" or "Careers" as no title, and flag the job as needing input.

## Outcome, checked on a running instance

1. On Board view, the only filled blue element above the board is "Add a job". Switching to List moves the selected style to List. Needs attention and Hide closed postings show the same style when on.
2. Every filter popover, in Board and List view, scrolled to the top and scrolled down, shows nothing through it and nothing on top of it.
3. No list page has the white title band. Title, toolbar and content share one left edge.
4. The Ended lane is grey, full height and aligned with the column headers. It covers no column at 1280px or 1920px wide. Dragging over it shows "Drop to end".
5. Cards match the artboard: compact status select, no sector or size tags, one clean location line.
6. No stored title contains markup. The Thomson Reuters company name has no code. "Job Offers" is no longer a title.

## Not in scope for Part A

The List view layout beyond the shared header and popovers, the expanded Ended lane, and the company detail page (except B5).

# Part B: handover for the next session

The owner's comments, 2026-10-18. Each item says what the owner wants, what to do, and what is still open. Items B2 to B5 can be planned in the next session. B1 waits for deployment.

## B1. A secure setup for the OpenRouter token, when deployed

**What the owner wants.** A best-practice way to manage the OpenRouter API token once the application runs deployed. The owner will not hand the token over in a chat.

**Until then.** Keep using the local model. Do not ask for the token, and do not add it anywhere.

**When deployment comes, propose a setup that meets these rules:**
- **The token never appears** in the repository, a chat, a log, an error message, the frontend or a test fixture.
- **Locally,** it lives in an environment file that is listed in .gitignore. The repository holds only an example file with an empty value.
- **On the server,** it lives in the hosting platform's secret store, or in an environment file readable only by the service account. It is never baked into an image or a build.
- **The app reads it at start.** When it is missing, the app fails with a clear message naming the variable, never with the token's value.
- **Use a key made only for CareerOS,** with a spending limit set at the provider if it offers one, so a leaked key has a capped cost. This adds to the app's own monthly cap from careeros-vision-and-mvp.md, section 8.3.
- **Rotation is written down:** how to replace the key, and how to revoke it if it leaks.
- **The secret scan** routine from the toolkit runs before every commit.

**Note for planning.** The vision document puts the hosted model in M1, before hosting in M3. This decision moves the switch to deployment time. The golden set and the quality measurement from M1 can still run on the local model now. Re-measure on the hosted model when it arrives. Update the milestone table accordingly.

## B2. Jobs added through the API are not visible

**What the owner sees.** Jobs logged into the universe through the API call do not show up anywhere after logging in. The board only shows jobs on the owner's own board.

**What the owner wants.** An additional tab in the top navigation, where all jobs in the universe can be seen, including those added through the API.

**What to do:**
- **Confirm why they are hidden.** The likely cause is that the board shows only jobs marked as being on the user's board, and API-added jobs are not.
- **Add a nav tab listing every job in the universe.** It uses the same filter bar and the same list or card components as My Jobs.
- **Each job not yet on my board offers "Add to my jobs".** This puts it in New on my board, and is the existing "promote" action under a user word.
- **Jobs already on my board show their status** instead of the button.

**Open, owner decides.** The tab's name. PROJECT.md says "universe" is a backend word, not a user word. Proposal: "All jobs", next to "My Jobs". Show the proposal and wait.

## B3. All companies in one list

**What the owner wants.** Every organisation in the universe, including those added through the API, in the same Companies list the owner already has.

**What to do:**
- **Confirm why API-added companies are missing.** Then make the Companies list show every company in the universe, whatever its source.
- **Keep the existing equal tiles, the open-jobs chips and the filters** from the companies brief.
- **The open-jobs count** uses the universe's jobs that are open, not only the jobs on my board. If the two should differ, ask.
- **Do not show where a company came from** in the list.

## B4. Companies: a list view next to the tiles

**What the owner wants.** The tile view stays, and a list view is added.

**What to do:**
- **Add a "Tiles" and "List" pair** above the companies, in the selected style from A1, placed like Board and List on the Jobs page.
- **The list shows one row per company,** with these columns:
  - Name, as a link
  - Sector
  - Size
  - Location
  - Open jobs, the same chip as on the tiles
- **The columns can be sorted** by Name and by Open jobs.
- **The filters apply to both views.**
- **Show the proposed columns before building,** as a short text layout.

## B5. No "Needs your input" on the company page

**What the owner wants.** "Needs your input" no longer appears on the company page.

**What to do:**
- **Remove the chip and the Needs your input card** from the company detail page and from company tiles and list rows. Remove a Needs attention filter for companies, if one exists.
- **A missing sector or size shows in the Classification section** as "Unknown", with "Set it yourself" (opens Edit classification) and a quiet "Try again" (the existing company retry).
- **The job page keeps "Needs your input"** as designed. This change is only about companies.

**This supersedes** the "Company: a field needs input" artboard on the canvas, and the company Needs your input card in careeros-detail-pages-brief.md.
