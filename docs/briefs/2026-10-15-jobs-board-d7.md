# Brief: rework the Jobs board for the new status list (D7)

For the agent working on CareerOS. Written 2026-10-15 by the owner with a reviewing session. Paste into the tracker. Propose your plan and wait for my reply before building.

## Intent anchor

The board shows the jobs I am still pursuing, in the order they move, without the 25 ended jobs in the way. Ending a job is one drag, and the board helps me notice postings that have closed.

## Design

- Canvas, approved by the owner 2026-10-15: https://claude.ai/artifact/7PBPPwtEXZEmQdeNXd4b8S. The board artboards are in the bottom rows.
- Design system: CareerOS, https://claude.ai/artifact/5j1CSeRurNtisC3QGYfbDt

| Artboard | Shows |
|---|---|
| Jobs board | Default: five open columns, the collapsed Ended lane and the closed-postings banner |
| Jobs board: Ended expanded | The Ended lane open, with "Your search so far" and the three groups |
| End a job: how did it end | Dropping a card on the collapsed lane opens the chooser |
| End a job: Won asks first | The confirmation for Won |
| End a job: moved, optional reason (Stopped) | The undo message and the optional reason popup |
| End a job: optional reason (Rejected) | The reason popup for Rejected |
| Closed postings review | The review popup behind the banner |
| Jobs board on a phone, and its Ended view | One column at a time |

Where the canvas differs from the design system, the canvas wins, and you update the design system in the same change (see the last section).

## Statuses (owner decision D7)

- **Statuses, in this order:** New, Interested, Applied, Interviewing, Offer, Won, Rejected, Stopped.
- **Won** means I got the job. **Stopped** means I quit pursuing it without a rejection, and it replaces Withdrawn.
- **Closed is no longer a status.** It becomes a flag on the job, set when the posting is gone. A closed posting is a fact about the posting, not my decision.
- **Open** means not Won, not Rejected, not Stopped. Use this one definition everywhere: the board, the company list counts and filters.

### Migration, one time

- Withdrawn becomes Stopped.
- Every job with status Closed gets the closed flag. Its status goes back to the last status before Closed, read from history. If history has none, it becomes New. Nothing is ended on my behalf. Jobs that land in New or Interested are then picked up by the closed-posting suggestion below.
- The closed date comes from the "posting gone" history event. Without one, use the migration date.
- Report how many jobs moved where before and after, and keep a backup of the vault taken just before.

## Task

### Board layout

1. **Header.** Title "Jobs", and "Add a job" as the one primary button (the existing add popup).
2. **Filter bar** (FilterBar), in this order:
   - search, Function, Location, More filters
   - a divider
   - Needs attention, then "Hide closed postings", a toggle chip, off by default
   - the count "16 open · 25 ended" on the right

   There is no Fit filter, because Fit is not calculated yet.
3. **Closed-postings banner** (Message, info, inline). Shown when at least one job in New or Interested has had a closed posting for more than 7 days, and that job has not been kept. Text: "N jobs you have not applied to have had a closed posting for over a week." Actions:
   - "Review" opens the review popup.
   - "Not now" hides the banner until another job crosses the threshold.
4. **Open columns** (KanbanBoard), 320px each, in this order: New, Interested, Applied, Interviewing, Offer. An empty column shows a dashed box: "No jobs here yet. Drag a job here."
5. **Ended lane**, to the right of Offer.
   - **Collapsed by default, on every load.** A narrow strip shows "Ended", the total, the Won, Rejected and Stopped counts, a "Show" button and "Drop a job here to end it". It stays pinned to the right edge while the columns scroll sideways, so it is always a drop target.
   - **Expanded**, it is one 320px column, not three columns, with "Hide" in its header. Inside, top to bottom:
     - "Your search so far"
     - Won, Rejected and Stopped as groups, each showing its latest 3 jobs, then "Show all N"
     - an empty group says "Nothing won yet", "Nothing rejected yet" or "Nothing stopped yet"
   - **Ended cards are compact:** title, company, and the reason when there is one. Without one, an "Add a reason" link.

### Job card

The JobCard from the design system, with one addition:

- **Top row.** "Needs your input" on the left when it applies, and the status select on the right. The Fit chip is not shown on cards until fit is calculated.
- **Then:** title (two lines at most), company link, location and added date.
- **Closed flag, a new last row.**
  - Shown as a neutral chip, "Posting closed".
  - For a job in New or Interested whose posting closed more than 7 days ago, it becomes a warning chip instead: warning-weak ground, alert icon in warning text color, "Closed 9 days ago".
  - A job in Applied or later keeps the neutral chip, because a closed posting does not end an application.
- **The status select** lists the open statuses, a divider, then Won, Rejected and Stopped. Choosing an ended status runs the same flow as dropping on the lane.

### Ending a job

- **Dropping a card on the collapsed lane** opens a chooser at the drop point: "How did it end?" Won, Rejected, Stopped.
- **Dropping on a group of the expanded lane** picks that outcome directly.
- **Won always asks first:** "Mark as won? [title] at [company] moves to Won. Your other jobs stay as they are." Buttons "Cancel" and "Mark as won". Nothing happens to other open jobs.
- **Rejected and Stopped move at once.** A floating message reads "Moved to Stopped", with "Add a reason", "Undo" and dismiss.
- **Dragging an ended job back** to any open column is allowed, with "Moved to Applied" and Undo.
- **History records each move** in plain words, such as "Status changed from Applied to Stopped".

### Reasons, always optional

- **Opened from "Add a reason"** in the message, or on an ended card.
- **Suggestions, pick one or none:**
  - Stopped: Not interested anymore, Salary or conditions, Location or commute, Took another offer, Posting closed, No response.
  - Rejected: No reason given, After interview, Experience did not match, Position filled.
- **Plus a free text field,** "Anything else?", saved as a dated note on the job.
- **Skip saves nothing.** A job never waits for a reason.
- **History includes the reason,** for example "Stopped: Salary or conditions".

### Closed postings review

- **The popup lists each job from the banner** with company and "closed N days ago", plus "Keep" and "Stop".
- **Stop** moves the job to Stopped with the reason "Posting closed", which can be changed later.
- **Keep** turns the warning chip back to the neutral "Posting closed", and the job is not suggested again.
- **"Done"** closes the popup.

### Your search so far

| Line | Counts |
|---|---|
| Applied to | Jobs whose history ever reached Applied or later, including ended ones |
| Interviews | Jobs that ever reached Interviewing |
| Offers | Jobs that ever reached Offer |
| Most common reason to stop | The most frequent suggestion among Stopped jobs, with its count. Hidden while no Stopped job has a reason. |

### Phone

- **Below 720px wide,** the board shows one column at a time.
- **A status row of chips** scrolls sideways, with Ended as the last chip.
- **No dragging on phones.** Cards move with the status select, which runs the same ending flow.
- **The banner shortens** to "N closed postings to review".
- **Popups open as full-width sheets.**

## Reuses

- **Design system components.** KanbanBoard, JobCard, FilterBar, Message, Badge, StatusSelect, EmptyStates, Buttons.
- **Gestalt.** Modal, Popover, Dropdown.
- **Existing code.** The drag library already in use, the watcher's "posting gone" event, and the history event registry from the detail pages brief.

## Adds

- The Ended lane.
- The ending chooser.
- The reason popup.
- The closed flag and its two chip states.
- The closed-postings banner and review.
- "Your search so far".
- The phone layout.

Each traces to D7 or to the owner decisions of 2026-10-15.

## Removes

- The Rejected, Closed and Withdrawn columns.
- The Closed and Withdrawn statuses.
- The Fit chip on cards and the Fit filter, until fit exists.

## Design system updates (same change)

- **KanbanBoard.** New column list, the Ended lane (collapsed and expanded), and the pinned lane while scrolling. Change the empty text to "No jobs here yet. Drag a job here."
- **JobCard.** Add the closed row and its two chip states. Note that the Fit chip is hidden until fit is calculated.
- **StatusSelect.** The D7 list, with a divider before Won, Rejected and Stopped.
- **FilterBar.** No Fit chip until fit exists. Add the "Hide closed postings" toggle after Needs attention.
- **Message.** Add these rows:
  - "Moved to Stopped [Add a reason] [Undo]"
  - "N jobs you have not applied to have had a closed posting for over a week. [Review] [Not now]"
  - "Moved to Won"

## Outcome

Check these on a running instance with the real vault, and report each one.

1. Migration report shows no job left in Withdrawn or Closed, and the board shows five open columns plus the Ended lane.
2. The Ended lane is collapsed after every reload and stays visible at the right edge when the columns scroll.
3. Dropping a card on the collapsed lane opens the chooser. Stopped moves it at once and shows Undo. Undo puts it back.
4. Won asks first, and Cancel leaves the job where it was. Other open jobs are untouched after Mark as won.
5. "Add a reason" saves a suggestion and a note. Skip saves nothing. The ended card shows the reason.
6. A job in Interested whose posting closed 8 days ago shows the warning chip and appears in the banner. One in Applied with a closed posting shows the neutral chip and no banner.
7. Keep in the review popup turns the chip neutral, and the job does not come back. Stop moves it to Stopped with "Posting closed".
8. "Hide closed postings" hides flagged jobs in every column and is off after reload.
9. "Your search so far" numbers match a hand count from history for at least three jobs.
10. At 390px wide, one column shows at a time, the status row scrolls, and a job can be ended through the status select.
11. A screen reader announces each column name and count, and the ending chooser can be used with the keyboard alone.

## Deferred

- When a job is Won, an optional prompt to stop the other open jobs. Never automatic.
- Sorting and searching inside the Ended lane.
- Remembering whether the Ended lane was open.
- Fuller statistics: rates, time to offer, monthly view, reasons over time.

Dropped: bulk moves.
