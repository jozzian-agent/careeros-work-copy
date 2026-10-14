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
   could not be read ("Paste the posting text", "Try again").
4. Summary, labeled "AI-generated" when a model wrote it.
5. Requirements, labeled "AI-extracted": must-have and nice-to-have
   lines, with extracted skills as must-have tags.
6. Responsibilities, labeled "AI-extracted".
7. One extraction row: when the posting was last read, which fields were
   not found in it, and "How this was extracted", which opens a popup
   listing every covered field with its result (Found, Not found in
   posting, Failed, Pending) and its source (Page data, AI, You). A field
   that was not found links to the surface that can set it. This popup
   replaced the permanent Extraction card and its eight status badges.
8. Original posting, collapsed, one card, the posting's own paragraphs.
9. Details, collapsed: source, posted date and "Check if still online"
   with its result line.
10. Classification: the sector, marked "From the company" when it is
    inherited from the linked company, the function and the tags, each
    reading "Not found in posting" when the posting named none. "Edit
    classification" opens the shared popup.
11. Notes, with a dashed "Add a note" box when there are none, which
    opens Edit job at the notes field.
12. History: the visible events only, with local dates.

While the posting is being read, a strip sits under Status and Fit and
the sections with nothing in them yet say "Being read from the posting."
The strip is gone once reading is done.

Edit job now carries every machine-made field the page labels (summary,
both requirement lists, responsibilities, skills as removable tags), so
no AI label points at a field the owner cannot correct. The per-section
Edit button beside the AI label is gone; there is one editing surface.

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
5. Classification: the sector and the size, each with where the value
   came from ("Set by you", "Found by AI", "Found on Wikidata", and so
   on), and "Edit classification".
6. Notes, with the same dashed "Add a note" box, which opens Edit company
   at the notes field.

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
  EXPERIENCE / COMPANY / COMPANY CLASSIFICATION, with the job's fit chip or
  "Needs your input" inline for jobs), title, subtitle, location/dates,
  Edit and Delete actions. Company Classification has neither action; it
  saves inline with its own Save changes/Cancel row instead.
- `SectionCard`s in order: summary, content, classification, details,
  notes, related items, history — each page only renders the sections it
  has data for.
- The job page additionally has Status and Fit dropdowns under the header
  (`StatusSelect`, reused from the board; `FitSelect`, new — the job
  record's `fit` field had no writer anywhere before this ticket).

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
from the Job detail page via the Edit criteria popup instead of a
navigated-to sub-page, so nothing links to the old page anymore, but it is
not removed either.

## Edit and delete

Four edit popups (Edit job, Edit position, Edit company, Edit criteria)
and one delete confirmation template, all designed in Phase A of this
ticket (not in the original design brief) and owner-approved before the build:
wireframes lived at `frontend/wireframes/joz280/` (gitignored review
artifacts, not shipped). All write through existing endpoints; no backend
endpoint or schema change. See `frontend/BUILD_NOTES.md`'s component
registry for exactly which Gestalt components and endpoints each popup
uses, and its "Known gap" note for the one piece of existing Jinja
functionality (resolving a `needs_review` company match from the job page)
not yet ported to React.

## States

Loading and load-error states per page (plain text, a Retry on load
failure). Ingest failure/pending states and their Retry are shown on the
Job page. A company delete blocked by still-linked records (409) renders
inline in the delete `ModalAlert` rather than closing it. Empty related-item
lists (a company with no jobs or experiences) show the dashed empty state.

## Verification

- `.venv/bin/python -m pytest -q` (909, was 919 — see BUILD_NOTES for the
  accounting of converted vs. removed tests).
- `cd frontend && npx playwright test` (106, was 78): `job-detail.spec.js`,
  `experience-detail.spec.js`, `company-detail.spec.js`,
  `company-classification.spec.js`.
- `cd frontend && npm run build`.
- Owner click-test on the live instance: pending.

## Open questions

- The company-review resolution UI (picking a candidate / creating a
  company for a `needs_review` job) is not yet ported; flagged in
  BUILD_NOTES as a follow-up, not silently dropped.
- Live-polling for in-progress enrichment (the old page's 4s interval) is
  not carried over; the page shows the loaded snapshot and offers Retry.
