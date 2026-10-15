---
type: Surface
title: "M1 JSON page contracts"
description: "Describe JSON representations for existing dashboard pages."
timestamp: 2026-10-14
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

2026-10-15 (Companies list rework): two additive keys, no field removed.
The board gains `size_classes`, the one company-size scale, so the board's
Company size facet reads the same vocabulary the Companies page already
reads instead of bucketing employee counts in JS. Each company in the
Companies collection gains `needs_attention`, true when any review flag
stands against the record, derived server-side the way the board derives
it for a job.

2026-10-14 (detail-pages realignment, backend round B1 to B6): the Job
detail and Company detail `view=page` contracts gained the canvas keys
listed below, and the company taxonomy endpoint is gone along with its
page (the job taxonomy endpoint is untouched). The two detail contracts
are spelled out key by key below, because the canvas brief named keys
(`notes_html`, `details`, `posting_text`) these contracts never had: the
notes HTML is `markdown` and the posting text and detail fields are read
from the raw record.

2026-10-14 (package 2, requirement groups): the job record gained
`requirement_groups`, a list of `{group, level, text}` over a fixed
five-group vocabulary ([schemas](../schemas.md)), and one write endpoint,
`POST /api/jobs/<id>/re-extract`, which reads the stored posting text
again. The Job detail contract is unchanged in shape: the groups are a
record field, so they arrive on `job` the way the flat
`description_structured` block always has, and everything downstream of
the page context reads them from there.

2026-10-14 (owner round, notes): notes stop being one free-text field per
record and become a list of titled notes. The two detail contracts gained
`notes`, the Job detail contract lost `markdown` (nothing renders notes as
HTML anymore), and notes have their own write endpoints plus one
vault-wide read. See the Notes section under Minimal contents.

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
| GET | `/api/notes` | Notes | New |
| POST | `/api/jobs/<id>/re-extract` | Job detail | New |
| POST | `/api/jobs/<id>/notes`, `/api/companies/<id>/notes` | Job and Company detail | New |
| PATCH, DELETE | `/api/jobs/<id>/notes/<note_id>`, `/api/companies/<id>/notes/<note_id>` | Job and Company detail | New |

All existing default record responses and write methods retain their contracts.
`view` selects GET representations only; writes still return records. JSON
converts template tuples to arrays and rendered Markdown to strings.

- Board: `statuses`, `size_classes`, `entries`, `companies`,
  `function_options`, `empty`. `size_classes` is the company-size scale
  (micro, small, medium, large), the same key the Companies contracts
  carry, so both pages filter over one vocabulary.
  Entries retain record fields and add `needs_attention`, `company_name`,
  `company_industry`, `company_size_class` and `pending`. Companies maps IDs
  to `{name, industry, size_class}`: `industry` is the company's first ISIC
  sector, human-labeled (`None` with no sectors or an unknown code);
  `size_class` is the raw micro/small/medium/large value (`None` when unset).
  Pending means not enriched, matching the existing card attribute; it is
  distinct from active detail enrichment.
- Job detail: `job`, `company`, `statuses`, `function_labels`, `notes`,
  `has_description`, `show_remote_chip`, `watch_eligible`, `watch_reason`,
  `llm_pending`, `history`, `classification`, `needs_input`, `reading`,
  `summary_effective`, `fit`, `fit_placeholder`. There is no posting-text
  or details key of its own: the posting stays on the raw record
  (`job.description`, `job.description_structured`, plus its title,
  location, employment type, salary and the rest), `notes` is the owner's
  notes as the migrated list (see Notes below), and `has_description` says
  whether any posting text arrived. The `markdown` key, which rendered the
  single legacy notes string to HTML, is gone: a note body is the plain
  text the owner typed and the page renders it as text. The record also carries summary
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
    or `{kind: 'read_failed', error_reason}` when reading the posting
    failed and only the owner can move it on: `extract_failed` whatever
    text is stored, since the text was read and still produced no details,
    and `fetch_failed` only while no text arrived at all, since stored
    text is all the fetch was ever for. The company ask always wins.
  - `reading`: true while the posting is still on its way in: the
    extractor running in this process (`llm_pending`), or an
    `ingest_state` that has not reached a result yet (`stub` or
    `fetched`, which is where a record parks when intake is interrupted).
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
  enrichment states and review flags, and add `needs_attention`: true when
  the record carries any review flag, which is what the directory's
  "Needs your input" filter asks for (broader than the detail contract's
  one-field `needs_input`). `counts` is the number of OPEN jobs linked to
  each company — open meaning any status but rejected, closed and
  withdrawn (`vault.ENDED_STATUSES`, the one definition both the count and
  the page's Open jobs filter read).
- Company detail: `company`, `entries`, `experiences`, `companies`,
  `sector_labels`, `isic_sections`, `size_classes`, `kinds`,
  `classification`, `needs_input`, `notes`, `jobs`. Existing raw GET
  already covers website, locations, flags, enrichment states,
  identifiers, sources, provenance and stored classification, all read
  from `company`. The page view adds linked records, attention flags,
  resolved labels, taxonomy choices and the notes list. The derived keys:
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
- Notes. A note is `{id, title, body, created, updated}`, stored as
  `note_list` on the job or company record it belongs to, which is the
  only thing that associates them: a note belongs to exactly one record.
  Ids are generated server-side (uuid4 hex) and never accepted from a
  client. A title is required and may not be blank; a body may be empty.
  `created` and `updated` are UTC timestamps, except on a note migrated
  out of the legacy free-text field, where both are null because that
  field never recorded a write-time.
  - `notes` on the two detail contracts is the migrated view: `note_list`
    when the record has one, otherwise the legacy `notes` string as a
    single note titled "Note" under the fixed id `legacy`. Reading never
    writes: the file keeps its legacy shape until the owner's first note
    write, which persists the migrated note and clears the legacy string
    in the same save, so a note never exists in two shapes at once.
  - `POST /api/jobs/<id>/notes` and `POST /api/companies/<id>/notes` take
    `{title, body}` and answer 201 with the created note. `PATCH
    .../notes/<note_id>` takes `{title?, body?}`, leaves a field the
    payload does not carry alone, stamps `updated`, and answers the note.
    `DELETE .../notes/<note_id>` answers `{deleted: <note_id>}`. A missing
    record or note is 404; a blank title is 400.
  - `GET /api/notes` is `{notes, empty}`: every note in the vault as
    `{id, title, body_preview, created, updated, job_id, job_title,
    company_id, company_name}`, newest `created` first, with the two keys
    of the other kind null. `body_preview` is the body's first non-empty
    line, shortened to 120 characters. Read-only aggregation; the Notes
    page it feeds links through to the record that holds a note.
  - The legacy `notes` string stays a writable field of `PUT
    /api/jobs/<id>` and `PUT /api/companies/<id>` for one release, since
    existing record clients and the enrichment merge rules read and
    preserve it. No frontend caller writes it anymore. Once a record has
    a non-empty `note_list`, a write to the legacy string is no longer
    surfaced anywhere, which is why the field is scheduled for removal
    rather than kept.
- Requirement groups. `requirement_groups` on a job is a list of
  `{group, level, text}` over the fixed vocabulary in
  [schemas](../schemas.md). An empty list means the job has no grouped
  requirements yet, which is where every job written before package 2
  starts; the page then renders its flat `description_structured` lists
  instead, so both shapes read correctly off one contract.
  - `POST /api/jobs/<id>/re-extract` reads the stored posting text again
    and answers 202 with the job plus `llm_pending`. It fetches nothing:
    the live posting may be gone, and the text to group is the stored
    one. It writes the rule-based groups (the flat lists under the Skills
    group) in the same breath, so the action lands a result with no model
    reachable, and queues the extraction that replaces them. A missing
    job is 404. A job with no stored posting text is 409, and so is a job
    whose reading is already running, each with its own `error`: there is
    one reservation per job, and a request that did not get it started no
    reading, so answering 202 would credit it with another run's result.
  - `PUT /api/jobs/<id>` takes the whole list, like any other field, and
    stamps owner provenance on it, after which no extraction overwrites
    it. That is the Languages editor's write path.
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
