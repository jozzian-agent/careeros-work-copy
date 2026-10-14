---
type: Surface
title: "Detail pages"
description: "Describe the shared Job/Experience/Company/Classification detail-page skeleton."
timestamp: 2026-10-14
---

# Detail pages

Surface: `/jobs/<id>`, `/experiences/<id>`, `/companies/<id>`,
`/companies/<id>/taxonomy` (React rewrite of `job_detail.html`,
`detail.html`, `company_detail.html`, `company_taxonomy.html`).
Status: implemented 2026-10-12 (JOZ-280). Owner click-test pending.

2026-10-14 (detail-pages realignment): `/companies/<id>/taxonomy` is
removed, page and JSON endpoint both. Everything below about that
sub-page is history. The job and company detail JSON contracts the pages
read are in [JSON page contracts](json-api.md).

2026-10-14 (package 2, requirement groups): the Requirements section
renders the grouped shape package 1 built it for. A job stores
`requirement_groups` ([schemas](../schemas.md)) as of this round; a job
written before it keeps its flat lists and keeps rendering through the
package-1 adapter, until the owner presses Re-extract on that job, which
is the only thing that migrates a record (owner decision: nothing
migrates on read and nothing re-runs in bulk). Languages get their first
stored home and, with it, an editor in Edit job. The extraction popup
gains one row for the groups, labeled Requirements.

2026-10-14 (detail-pages realignment, package 1): the Job page is rebuilt
to the approved canvas and no longer follows the shared section order
below. Top to bottom it is now:

1. `DetailHeader`: back link, the JOB label with the "Needs your input"
   chip beside it (shown only when the card below is, and linking to it),
   title, company link, then location, added date and the posting link.
   Edit job and Delete are both gray secondary.
2. Status (`StatusSelect`) and Fit, where Fit reads "Not calculated yet":
   scoring is not built, so there is no control.
3. The one needs-input card, when the backend's `needs_input` says there
   is something to ask: either which company this job is at (candidates
   as radio rows, "Link to this company", "None of these, create new",
   both through `POST /api/jobs/<id>/resolve-review`) or that the posting
   could not be read ("Try again", through
   `POST /api/jobs/<id>/extract`, plus "Paste the posting text" while the
   posting itself was never fetched, which is the only state the paste
   endpoint accepts). A failed extraction raises the card even when the
   posting text is stored: retrying is the only way its details ever
   arrive, and the text is corrected in Edit job.
4. Summary, labeled "AI-generated" when a model wrote it.
5. Requirements, labeled "AI-extracted": one block per group the posting
   asked for, in the owner's order (Education, Experience, Skills,
   Languages, Certifications), each line carrying its level. Skills,
   Languages and Certifications read as tags, the two prose groups as
   must-have and nice-to-have rows. A stored skill the Skills group does
   not already carry joins that group as a must-have tag, so a skill the
   list holds is never invisible. A job with no grouped requirements yet
   shows its flat must-have and nice-to-have lines with its extracted
   skills as must-have tags, which is the package-1 shape.
6. Responsibilities, labeled "AI-extracted".
7. One extraction row: when the posting was last read, which fields were
   not found in it, "How this was extracted", and "Re-extract". The popup
   repeats when the posting was read and then lists every covered field
   with its result (Found, Not found in posting, Failed, Pending) and its
   source (Page data, AI, You). A field that was not found links to the
   surface that can set it. This popup replaced the permanent Extraction
   card and its eight status badges. Re-extract reads the stored posting
   text again, which is how a job gets its requirement groups; it is
   disabled, with a reason, while no posting text has arrived.
8. Original posting, collapsed, one card, the posting's own paragraphs,
   ending with the posting's own link ("Open the posting at its source").
9. Details, collapsed: source, posted date and "Check if still online"
   with its result line.
10. Classification, collapsed: the sector, marked "From the company" when
    it is inherited from the linked company, the function and the tags,
    each reading "Not found in posting" when the posting named none.
    "Edit classification" sits inside it and opens the shared popup.
11. Notes: one row per note, with a dashed "Add a note" box when there
    are none. See [Notes](notes.md) for the section, the note window and
    the vault-wide page.
12. History, collapsed: the visible events only, with local dates.

Sections 8 to 10 and 12 are collapsed by default (owner round,
2026-10-14), all four through `SectionCard`'s `collapsible` variant: one
`Accordion.Expandable` per section, so opening one never closes another,
with one wording rule for the toggle ("Show the <title>" / "Hide the
<title>"). The always-open variant is unchanged.

While the posting is being read, a strip sits under Status and Fit and
the sections with nothing in them yet say "Being read from the posting."
The strip is gone once reading is done.

Edit job now carries every machine-made field the page labels (summary,
both requirement lists, responsibilities, skills as removable tags), so
no AI label points at a field the owner cannot correct. The two
requirement fields are always there, because the extraction popup sends
the owner here for a requirement the posting did not yield, and they
write per reported field rather than by one flag:

- The grouped field is written when the page renders the groups, and for
  a job that stores no requirements at all, since the groups are the
  shape anything new goes into. It is left alone for a job still
  rendering its flat lists, because regrouping a job is what Re-extract
  is for, and the fallback group would otherwise bury every prose line
  of that job under Skills behind the owner.
- The flat block is written when the page renders it, and for a job that
  has no block at all, so the Description row that says "Not found in
  posting" leads to a control that writes it. A block written here
  records `method: 'user'`.

Languages are their own removable tags beside the two fields, since a
language is a word rather than a sentence and the Languages group is
where one is stored, so that editor appears exactly when the popup
writes the groups. A requirement line keeps the group it already had,
matched on its text; a line the owner has just written or reworded lands
in Skills, the same fallback group the extractor uses, which is one
control per level instead of one per group. The per-section
Edit button beside the AI label is gone; there is one editing surface.
Notes are not one of its fields: as of the owner round a note is its own
record with its own window, so Edit job and Edit company both lost their
notes field and the `focus` prop that only existed to land on it.

The Company page is rebuilt in the same round:

1. `DetailHeader`: back link, the COMPANY label with the same "Needs your
   input" chip, title, "sector · size", then the locations and the
   website as an external link on one line. Edit company and Delete are
   both gray secondary.
2. The one needs-input card, when the backend's `needs_input` says the
   sector or the size is empty and automation has run out of ideas: it
   names the field and the sources that were tried, "Set it yourself"
   opens Edit classification and "Try again" calls
   `POST /api/companies/<id>/retry`, whose outcome renders below it.
3. Jobs: each linked job's title as a link, with its status.
4. Experiences: the same row, with present or past.
5. Classification, collapsed: the sector and the size, each with where
   the value came from ("Set by you", "Found by AI", "Found on Wikidata",
   and so on), and "Edit classification" inside it.
6. Notes, the same section as the Job page's.

The Company page has no History section: a company record stores no
history, so the owner round's "collapse History on both pages" applies
only to the Job page. Giving companies a history is a feature, not a
collapse, and is not in this round.

There is no Details section: it repeated the title as a Name row and the
website that is now in the header. Edit classification is one component
with a job and a company variant, which is what replaced the retired
`/companies/<id>/taxonomy` page.

## Purpose

One shared skeleton for every record detail page, so a friend always knows
what they are looking at and how to get back, edit or delete it.

## Appears in

Jobs board → a job card's title → Job detail. Experiences list → a
position → Experience detail. Companies directory → a company → Company
detail → Edit classification → Company Classification.

## Minimal contents

- `DetailHeader`: back link to the list, a small-caps type label (JOB /
  EXPERIENCE / COMPANY, with the "Needs your input" chip inline when that
  page has one ask), title, subtitle, location and dates, Edit and Delete
  actions, both gray secondary.
- `SectionCard`s, each page rendering only the sections it has data for.
  The Job and Company pages follow the 2026-10-14 orders above; the
  Experience page keeps the original skeleton order (summary, content,
  details, notes).
- The Job page additionally has Status and Fit under the header:
  `StatusSelect`, reused from the board, and the read-only `FitChip`
  placeholder. The Fit dropdown that briefly lived here is gone; nothing
  ever read the value it wrote.

## Routing

No Jinja coexistence for these four routes (owner decision), unlike the
Jobs board's own `/jobs` list route: they are mounted only when
`CAREEROS_REACT_UI=1` and the build exists, with the prior Jinja routes,
views and templates removed rather than kept as a flag-off fallback. See
`frontend/BUILD_NOTES.md`'s "Routing: no Jinja fallback for detail pages"
for the detail, including the one wiring bug (a route lambda not accepting
Flask's `<identifier>` kwarg) this exposed and the regression tests added
for it (`tests/test_react_ui_flag.py`).

`/jobs/<id>/taxonomy` (job classification) is not part of this cutover and
stays a separate, unconditionally-Jinja page: job classification is edited
from the Job detail page via the Edit classification popup instead of a
navigated-to sub-page, so nothing links to the old page anymore, but it is
not removed either. Its JSON endpoint is what the popup reads.

## Edit and delete

Four edit popups (Edit job, Edit position, Edit company, Edit
classification) and one delete confirmation template. The first set was
designed in Phase A of JOZ-280 (not in the original design brief) and
owner-approved before that build: wireframes lived at
`frontend/wireframes/joz280/` (gitignored review artifacts, not shipped).
Edit classification is the 2026-10-14 round's one popup for both job and
company classification, replacing JOZ-280's job-only Edit criteria popup
and the retired Company Classification page. All write through existing
endpoints; no backend endpoint or schema change. See
`frontend/BUILD_NOTES.md`'s component registries for exactly which Gestalt
components and endpoints each popup uses.

## States

Loading and load-error states per page (plain text, a Retry on load
failure). Ingest failure/pending states and their Retry are shown on the
Job page. A company delete blocked by still-linked records (409) renders
inline in the delete `ModalAlert` rather than closing it. Empty related-item
lists (a company with no jobs or experiences) show the dashed empty state.

## Verification

2026-10-14 (package 2, grouped requirements):

- `.venv/bin/python -m pytest tests/ -q` (1106, was 1052: 31 tests
  written in the new `tests/test_requirement_groups.py` for the
  vocabulary, the prompt, the parser, the rule-based fallback, the stored
  field and its validation, the additive migration and the re-extract
  endpoint; parametrized, they run as 54 cases).
- `cd frontend && npx playwright test` (224, was 210): `job-detail.spec.js`
  is 68 (was 54), covering the grouped render and its level tags, the
  legacy flat-list fallback, the AI label following the recorded source,
  the extraction popup's Requirements row, the Re-extract button (enabled,
  disabled without posting text, and its error) and the languages editor.
- `cd frontend && npm run build`.
- Owner click-test on the live instance: pending.

2026-10-14 (package 1, the two rebuilt pages, after the owner round):

- `.venv/bin/python -m pytest tests/ -q` (1052, was 1033: 18 in the new
  `tests/test_notes.py` for the note shape, the migration, the CRUD
  endpoints and the vault-wide roll-up, plus one for the `/notes` page
  route in `tests/test_react_ui_flag.py`).
- `cd frontend && npx playwright test` (210, was 193): `job-detail.spec.js`
  (54), `company-detail.spec.js` (22), the new `notes.spec.js` (8) and the
  shared `detail-pages.spec.js` (7: Delete gray and the back arrow blue
  on both pages, the 390px layout, the retired classification route).
- `cd frontend && npm run build`.
- Owner click-test on the live instance: pending.

Earlier, 2026-10-14 after the review fix round and before the owner
round: pytest 1033 (was 1030), Playwright 193 (was 174).

Earlier, at the JOZ-280 cutover: pytest 909 (was 919 — see BUILD_NOTES for
the accounting of converted vs. removed tests), Playwright 106 (was 78).

## Open questions

- Live-polling for in-progress enrichment (the old page's 4s interval) is
  not carried over; the page shows the loaded snapshot, polls while a
  field is pending, and offers Retry.
- Three fields the extraction popup reports on (company, seniority,
  employment type) have no owner-editing surface anywhere, so their rows
  name the result without linking to a setter. Whether they get one is a
  product decision, not a gap in this package.
- A job's `skills` list and the Skills requirement group overlap: the
  extraction fills both, and each has its own editor, so the two drift.
  The owner decided to keep the list (2026-10-14), so the Requirements
  section renders the group plus any stored skill the group does not
  carry, and nothing the record holds goes unshown.
- Edit job shows the grouped requirements as two lists by level, not as
  five lists by group, so the owner cannot move a line from one group to
  another there. Re-extracting the job is what regroups it today.
- Re-extract with no model reachable stores the rule-based groups and the
  queued reading then comes back with nothing. A job that was already
  read keeps that reading: its state does not change, the fields the
  earlier reading settled keep what they settled on, and the attempt
  shows up as its own history line ("Reading the posting again found
  nothing new") with one sentence in the extraction popup. A job whose
  reading never succeeded keeps the ordinary failure path and its card,
  because there is no earlier reading to protect.

The company-review resolution UI (picking a candidate or creating a
company for a `needs_review` job), flagged as a known gap at the JOZ-280
cutover, is implemented: it is the Job page's needs-input card.
