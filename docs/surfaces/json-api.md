---
type: Surface
title: "M1 JSON page contracts"
description: "Describe JSON representations for existing dashboard pages."
timestamp: 2026-10-11
---

# M1 JSON page contracts

## Purpose

Provide the existing dashboard data to the approved React migration while
keeping Jinja and existing record clients working. Backend implementation of
the owner brief, 2026-10-10; this does not accept a React page or its design gate.

## Appears in

The existing Jobs, Search, Companies and Experiences flows. Page views extend
existing routes because their default record responses are already consumed by
scripts and Jinja JavaScript. No new product concept, dependency or stored field
is introduced. Separate taxonomy and form routes mirror existing HTML routes;
record endpoints cannot supply their choices and derived labels alone.

## Minimal contents

| Method | Path | Page | Change |
|---|---|---|---|
| GET | `/api/jobs?view=board` | Jobs and job cards | Extended collection |
| GET | `/api/jobs/<id>?view=page` | Job detail | Extended detail |
| GET | `/api/search?view=page` | Search | Extended with page metadata |
| GET, POST | `/api/search` | Search criteria | Already covered |
| GET | `/api/companies?view=page` | Companies | Extended collection |
| GET | `/api/companies/<id>?view=page` | Company detail | Extended detail |
| GET | `/api/jobs/<id>/taxonomy` | Job classification | New |
| GET | `/api/companies/<id>/taxonomy` | Company classification | New |
| GET | `/api/experiences?view=page` | Experiences | Extended collection |
| GET | `/api/experiences/<id>?view=page` | Experience detail (`detail.html`) | Extended detail |
| GET | `/api/experiences/new` | Add experience | New |
| GET | `/api/experiences/<id>/edit` | Edit experience | New |

All existing default record responses and write methods retain their contracts.
`view` selects GET representations only; writes still return records. JSON
converts template tuples to arrays and rendered Markdown to strings.

- Board: `statuses`, `entries`, `companies`, `function_options`, `empty`.
  Entries retain record fields and add `needs_attention`, `company_name` and
  `pending`. Companies maps IDs to names. Pending means not enriched, matching
  the existing card attribute; it is distinct from active detail enrichment.
- Job detail: `job`, `company`, `statuses`, `function_labels`, `markdown`,
  `has_description`, `show_remote_chip`, `watch_eligible`, `watch_reason`,
  `llm_pending`. The record includes source description, summary provenance,
  company review, history, ingest failure and retry information.
- Search: `data`, `sections`, `empty`. The original GET/POST already covers
  roles, must-haves, nice-to-haves, avoid, notes and updated date. There is no
  matches list in the current template or criteria model, so none is invented.
- Companies: `entries`, `counts`, `sector_labels`, `isic_sections`,
  `size_classes`, `empty`. Entries retain kind, locations, sectors, size,
  enrichment states and review flags.
- Company detail: `company`, `entries`, `experiences`, `companies`,
  `sector_labels`, `isic_sections`, `size_classes`, `kinds`. Existing raw GET
  already covers notes, flags, enrichment states, identifiers, sources,
  provenance and stored classification. The page view adds linked records,
  attention flags, resolved labels and taxonomy choices.
- Job taxonomy: `job`, `company`, `function_options`, `function_labels`,
  `isic_labels`, `tags`, `tag_labels`, `tag_registry`.
- Company taxonomy: `company`, `isic_sections`, `size_classes`, `kinds`.
- Experiences: `entries`, `companies`, `labels`, `tag_labels`, `empty`.
  Existing raw collection/detail already covers company ID and frozen company
  label, dates, location, summary, highlights, detail, skills, tags, people led,
  custom fields and salary. Page contexts add live company labels and tag labels.
- Experience detail: `exp`, `label`, `companies`, `tag_labels`, `markdown`.
- Experience forms: `exp`, `companies`, `tags`. The add form uses an empty
  `exp`; edit uses the stored record including its company link.

Pure assembly functions in the four existing page modules receive explicit
record snapshots. Shared read-only loaders supply them to HTML and JSON.
The board JSON representation projects company names from the shared context.
No template changed. The reuse ladder stops at extending existing builders and
routes; a serializer framework and new dependencies are unnecessary. Revisit
only if a later page contract needs behavior the current builders cannot express.

## States

Empty collections return empty entry arrays and their existing empty message.
Missing Search criteria is JSON null, or `data: null` in its page view.
Missing detail, taxonomy and edit records return JSON errors with status 404;
HTML missing-record pages keep their existing response. Linked company names
resolve from current company records; an unlinked board job has a null
`company_name`. Ingest failures, needs-review flags and enrichment state remain
available without triggering work. Reads never start enrichment or save data.

## Verification

- `.venv/bin/python -m pytest tests/test_api_*.py -q` pins exact nested JSON
  keys/types in five endpoint-group files and checks values, empty states,
  missing records and existing mutation contracts.
- `.venv/bin/python -m pytest -q` runs the existing HTML and API regression suite.
- On 2026-10-10, all 11 HTML page variants rendered byte-for-byte identically
  to the original handlers at the task's starting commit, using a temporary
  fixture vault. Templates and the browser verification script are unchanged.
- A separate agent reviewed the plan and implementation. Browser acceptance
  of React pages remains in their respective cutover milestones.

Verification result, 2026-10-10: the full command above passed 916 tests
(896 existing plus 20 new). The separate review found no blockers; the required
leak scan and `git diff --check` were clean. Changes remain uncommitted.

## Open questions

None for this backend scope. Matching jobs on Search would be a separate
feature decision; the brief's reference to a matches list does not describe
current behavior.
