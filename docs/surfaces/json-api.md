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

2026-10-12 (JOZ-280): the job detail, company detail, experience detail and
company taxonomy JSON contracts below are now read by React pages instead of
Jinja (their Jinja routes/templates are removed as part of that ticket's
detail-page cutover; see [Detail pages](detail-pages.md)). The contracts
themselves — every field listed below — are unchanged; only the renderer
consuming them moved.

2026-10-13 (JOZ-283): the Search, Experiences and Companies `view=page`
contracts below are, likewise, now read by React pages instead of Jinja
(their Jinja routes/views/templates are removed, same no-coexist decision
as JOZ-280; see [Search](preferences.md), [Experiences list](experiences.md)
and [Companies list](companies.md)). No contract field changed.

2026-10-14 (detail-pages realignment, backend round B1 to B6): the Job
detail and Company detail `view=page` contracts gained the canvas keys
listed below, and the company taxonomy endpoint is gone along with its
page (the job taxonomy endpoint is untouched). The two detail contracts
are spelled out key by key below, because the canvas brief named keys
(`notes_html`, `details`, `posting_text`) these contracts never had: the
notes HTML is `markdown` and the posting text and detail fields are read
from the raw record.

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
| GET | `/api/experiences?view=page` | Experiences | Extended collection |
| GET | `/api/experiences/<id>?view=page` | Experience detail (`detail.html`) | Extended detail |
| GET | `/api/experiences/new` | Add experience | New |
| GET | `/api/experiences/<id>/edit` | Edit experience | New |
| GET | `/api/taxonomy` | Taxonomy | New |

All existing default record responses and write methods retain their contracts.
`view` selects GET representations only; writes still return records. JSON
converts template tuples to arrays and rendered Markdown to strings.

- Board: `statuses`, `entries`, `companies`, `function_options`, `empty`.
  Entries retain record fields and add `needs_attention`, `company_name`,
  `company_industry`, `company_size_class` and `pending`. Companies maps IDs
  to `{name, industry, size_class}`: `industry` is the company's first ISIC
  sector, human-labeled (`None` with no sectors or an unknown code);
  `size_class` is the raw micro/small/medium/large value (`None` when unset).
  Pending means not enriched, matching the existing card attribute; it is
  distinct from active detail enrichment.
- Job detail: `job`, `company`, `statuses`, `function_labels`, `markdown`,
  `has_description`, `show_remote_chip`, `watch_eligible`, `watch_reason`,
  `llm_pending`, `history`, `classification`, `needs_input`, `reading`,
  `summary_effective`, `fit`, `fit_placeholder`. There is no posting-text
  or details key of its own: the posting stays on the raw record
  (`job.description`, `job.description_structured`, plus its title,
  location, employment type, salary and the rest), `markdown` is the
  owner's notes (`job.notes`) rendered to HTML, and `has_description` says
  whether any posting text arrived. The record also carries summary
  provenance, company review, raw history, ingest failure and retry
  information. The derived keys:
  - `history`: `[{ts, label, detail}]` from `careeros.history.resolve`,
    which is the raw `job.history` with owner-facing labels, invisible and
    unknown event types dropped, and the two extraction events collapsed
    into one entry.
  - `classification`: `{sector: {value, source}, function, tags}`. Sector
    `source` is `job` for the posting's own sector, `company` when it is
    inherited from the linked company record, and null with the value when
    neither has one.
  - `needs_input`: the one thing the page asks for, or null. Either
    `{kind: 'company', review}` when `job.company_link_state` is
    `needs_review` (`review` is `job.company_review`, which may be null),
    or `{kind: 'read_failed', error_reason}` when the posting text never
    arrived. The company ask always wins.
  - `reading`: true while the posting is still being read (`llm_pending`,
    or `ingest_state` `fetching`).
  - `summary_effective`: `job.summary`, or null when that summary is just
    the opening of the description verbatim. The stored record is never
    changed.
  - `fit`: always null, with `fit_placeholder` as the words the page shows
    instead. Fit scoring is not built.
- Search: `data`, `sections`, `empty`. The original GET/POST already covers
  roles, must-haves, nice-to-haves, avoid, notes and updated date. There is no
  matches list in the current template or criteria model, so none is invented.
- Companies: `entries`, `counts`, `sector_labels`, `isic_sections`,
  `size_classes`, `empty`. Entries retain kind, locations, sectors, size,
  enrichment states and review flags.
- Company detail: `company`, `entries`, `experiences`, `companies`,
  `sector_labels`, `isic_sections`, `size_classes`, `kinds`,
  `classification`, `needs_input`, `jobs`. Existing raw GET already covers
  notes, website, locations, flags, enrichment states, identifiers,
  sources, provenance and stored classification, all read from
  `company`; there is no notes-HTML key, since the company page shows the
  notes as plain text. The page view adds linked records, attention flags,
  resolved labels and taxonomy choices. The derived keys:
  - `classification`: `{sector: {value, source}, size: {value, source}}`.
    `source` is `user` when the owner set the field, else the name of the
    last enrichment signal that produced the value (`wikidata`, `llm`,
    ...), else null.
  - `needs_input`: `{field, tried}` for the one empty classification field
    automation has run out of ideas on (its enrichment state is
    `exhausted`, or a review flag stands against it), else null. `tried`
    lists the signals that actually ran for that field, in order. A review
    flag on a field that does have a value does not raise it.
  - `jobs` and `experiences`: linked records as `[{id, title, status}]`
    (an experience's status is `present` or `past`). `entries` stays the
    full job records the shared board card renderer reads.
- Job taxonomy: `job`, `company`, `function_options`, `function_labels`,
  `isic_labels`, `tags`, `tag_labels`, `tag_registry`.
- Experiences: `entries`, `companies`, `labels`, `tag_labels`, `empty`.
  Existing raw collection/detail already covers company ID and frozen company
  label, dates, location, summary, highlights, detail, skills, tags, people led,
  custom fields and salary. Page contexts add live company labels and tag labels.
- Experience detail: `exp`, `label`, `companies`, `tag_labels`, `markdown`.
- Experience forms: `exp`, `companies`, `tags`. The add form uses an empty
  `exp`; edit uses the stored record including its company link.
- Taxonomy: `skills`, `industries`, `sizes`, `tag_labels`. `skills` merges two
  sources per experience — the legacy free-text `skills` field (kept as-is)
  and `tags` tokens on the skill facets (`skill/capability`, `skill/domain`),
  shown by registry label, falling back to the slug when unknown — each a
  `{skill, count}` row, deduplicated per experience, sorted by count desc
  then name. `industries` is `{code, label, count}` per ISIC section any
  company's `sectors` carries, deduplicated per company. `sizes` is
  `{size_class, count}` in canonical micro/small/medium/large order plus a
  trailing `unknown` bucket, always present even when no companies exist.

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
