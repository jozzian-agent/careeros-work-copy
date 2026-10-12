---
type: Surface
title: "Detail pages"
description: "Describe the shared Job/Experience/Company/Classification detail-page skeleton."
timestamp: 2026-10-12
---

# Detail pages

Surface: `/jobs/<id>`, `/experiences/<id>`, `/companies/<id>`,
`/companies/<id>/taxonomy` (React rewrite of `job_detail.html`,
`detail.html`, `company_detail.html`, `company_taxonomy.html`).
Status: implemented 2026-10-12 (JOZ-280). Owner click-test pending.

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
ticket (not in the original handoff) and owner-approved before the build:
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
