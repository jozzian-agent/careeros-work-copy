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
it for a job. (Removed again 2026-10-19 by B5, with the filter that read
it; see the M2 section below.)

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

2026-10-17 (M1, accounts and required login): every endpoint listed below
now requires a session. An API call without one is answered
`401 {"error": "login required"}` and nothing else: no record, no route
name and no reason. A page request without one is redirected to
`/login`. Three routes are outside the gate: `GET /login`, `POST /login`
and `GET /api/health`. No existing contract changed otherwise: an
authenticated call gets exactly the response it got before. See the gate
and the login endpoints under Minimal contents.

2026-10-17 (CAREER-36, async AI): the four AI entry points stopped
answering with a record and now answer `202 {"status": "queued"}`, and the
job record gained the four `ai_` fields the front end polls instead. The
page contracts below are unchanged in shape: the fields are record
fields, so they arrive on `job` and on each board entry the way every
other record field does. See AI readings under Minimal contents.

2026-10-14 (owner round, notes): notes stop being one free-text field per
record and become a list of titled notes. The two detail contracts gained
`notes`, the Job detail contract lost `markdown` (nothing renders notes as
HTML anymore), and notes have their own write endpoints plus one
vault-wide read. See the Notes section under Minimal contents.

2026-10-28 (CAREER-71, size-class labels): `size_classes` changed shape in
all three contracts that carry it (Board, Companies, Company detail). It
was the bare code list and is now `[code, label]` pairs in the same order,
the shape `function_options` already used. The reason is one class: the
pages derived their display text by title-casing the code, which reads
"Xl" for the class the taxonomy labels "Very large" (owner decision D3,
2026-10-17). The labels come from `careeros/data/taxonomy/company_size.yaml`
through `vault.SIZE_CLASS_LABELS` and are retyped nowhere. Two readers of
a class outside those keys moved with it: the Company detail
`classification.size.value` answers a stored class as its label, and each
`sizes` row of `GET /api/taxonomy` gained a `label`. No code changed and
no record was migrated — this is what a class is SHOWN as.

## Appears in

The existing Jobs, Search, Companies and Experiences flows. Page views extend
existing routes because their default record responses are already consumed by
scripts and Jinja JavaScript. No new product concept, dependency or stored field
is introduced. Separate taxonomy and form routes mirror existing HTML routes;
record endpoints cannot supply their choices and derived labels alone.

## Minimal contents

| Method | Path | Page | Change |
|---|---|---|---|
| GET | `/api/jobs?view=board` | My Jobs, board and list | Extended collection |
| GET | `/api/jobs?view=universe` | All jobs | The board shape, over the universe (B2) |
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
| GET | `/api/health` | None | New, M1, unauthenticated |
| GET, POST | `/login` | Log in | New, M1, unauthenticated |
| POST | `/logout` | The logout affordance in the app chrome | New, M1 |

### The gate (M1)

Every row above except the last three needs a session. Without one:

- A path under `/api/` is answered `401 {"error": "login required"}`. The
  body is that object and nothing else, on every endpoint, so no response
  can leak a record before the caller has signed in.
- Any other path is answered `302` to `/login`, including a path that does
  not exist, so status codes cannot be read to find out which routes the
  app has.

The session is a Flask signed cookie holding one key, `user_id`. Role, name
and whether the account is disabled are read off the user record on every
request, so the cookie carries nothing a client could usefully forge, and
disabling an account ends its live session on that account's next request.
The cookie is `HttpOnly`, `SameSite=Lax` and lives 30 days, and the signing
key is persisted in the vault ([schemas](../schemas.md)), so a session
survives a server restart. `Secure` is deliberately not forced, because the
instance is not always reached over HTTPS.

`GET /api/health` answers `{"ok": true}` and nothing else. It is the one
unauthenticated read, and it reads no record.

`GET /login` is the login page: the built React page when the front end is
built, otherwise the same form rendered from the shared shell, since the one
page reachable without a session cannot be the one page that needs a build.
A signed-in person asking for it is redirected to the board.

### The split (M2)

Since 2026-10-18 (CAREER-39, owner decisions D3/D4) a session does not
only let a request in, it decides what the request can see.

- **Jobs and experiences are private.** Every list above answers with
  the session user's own records. Every per-record path answers for
  somebody else's record exactly as it answers for a record that is not
  there: the same status, the same body, including the admin asking for a
  tester's. There is no 403 on this half, on purpose, because a 403
  would itself say the record exists.
- **Companies and the tag vocabulary are shared.** Every user reads
  them. Changing one is the admin's: a PUT or DELETE on a company, a
  company note write, `/enrich`, `/retry`, `backfill-sector-size`, and
  any payload that would register a new tag value (`proposed_tags`, or
  the legacy skills-only experience payload) answer
  `403 {"error": "Only the admin can change companies and vocabulary."}`.
  The check runs after the record lookup, so a company that does not
  exist still answers 404 and a tester cannot map the vault by comparing
  the two.
- **`owner_id` is never accepted from a client.** The job PUT and both
  experience write paths strip it, so a record's owner is set once by
  the path that creates it and never moves.
- **One read is wider than the owner's own records: the All jobs tab**
  (B2, 2026-10-19). `GET /api/jobs?view=universe` answers with every job
  that is not private to another user -- the records carrying no
  `owner_id` plus the caller's own -- in the `view=board` shape, each
  entry carrying `on_my_board`. Another user's job is absent, for the
  admin too, and every per-job route answers for one of them exactly as
  it answers for a job that never existed; `POST /api/jobs/<id>/promote`
  reads through the same scope
  (`vault.load_universe_job` / `Owner.sees_in_universe`). The open-jobs
  `counts` on `GET /api/companies?view=page` are over the same set, so a
  company's number is the universe's open jobs and not the caller's board
  (B3).
- **Every board read is also narrower than the caller's own records: it
  is their BOARD** (CAREER-72/74, [schemas](../schemas.md)). A job
  carrying `in_pipeline: false` is universe-only -- the ATS pool import
  writes 704 of them, all ownerless -- so it is absent from
  `GET /api/jobs`, from `GET /api/jobs?view=board` and from the company
  profile's own job section, for every caller including the admin, who
  owns an ownerless record by inheritance. It is present on
  `GET /api/jobs?view=universe` with `on_my_board: false`, which is what
  offers "Add to my jobs"; the `closed_review` and `search_so_far` keys
  of either payload count board entries only, because both are about one
  person's own search. `GET /api/jobs/<id>` is unchanged and still reads
  the caller's own record whether or not it is on a board.
- **`POST /api/jobs/<id>/promote` is "Add to my jobs".** For a posting
  the caller does not own it answers `201` with a NEW job record of
  theirs, copied from the posting, landing in `new` and stamped with
  their `owner_id`; the posting it came from is left exactly as it was,
  so ownership never moves (D4). For a record that is already theirs it
  answers `200` with the record, flipping `in_pipeline` when that is
  false. A second call therefore adds nothing: the caller's own
  duplicate check finds the record they already have. The companion
  decision and what the copy carries are in [My Jobs](jobs.md).
- **`GET /api/companies/<id>?view=page` lost a key.** `needs_input` is
  gone (B5, 2026-10-19), and the directory entry's `needs_attention`
  with it: no company surface asks for "Needs your input" any more. A
  classification field with no value sends `{"value": null, "source":
  null}` and the page reads it as Unknown.
- **A private record's save writes nothing shared.** A job belonging to
  a tester does not promote its contact address onto the company, does
  not enter the company's rollup, and does not fill the company's
  website, size, sector or sources on intake, re-resolve or enrichment.
  One rule decides it, `enrich.contributes_to_shared`, keyed on the
  record's owner rather than on the session so the AI queue answers the
  same. `POST /api/experiences/<id>/link-company` with `create` is
  403 for the same reason; linking to a company that already exists, and
  unlinking, stay open to everybody.
- **A tester's posting resolves to a company that exists, or to none.**
  The resolution ladder never creates a company for a tester, by any
  route: intake, `POST /api/jobs/<id>/resolve`, the `create` half of
  `POST /api/jobs/<id>/resolve-review` (403) and the `create` half of
  `POST /api/experiences/<id>/link-company` (403). A posting whose
  company is not in the vault answers `company_id: null` with
  `company_link_state: "pending"`, and the job keeps the employer name
  as its own free text.
- **Company resolution reads the caller's own jobs.** The employer
  names recorded against an ATS tenant, and the legacy fallback's own
  tenant sweep, are scoped to the caller (a tester's own jobs; the
  admin's plus the legacy ownerless ones). So another user's private
  posting cannot change which company this user's posting resolves to,
  cannot raise the `shared_tenant` review, and cannot have its ATS
  association published as an identifier on a shared company. The cost
  is that the same tenant may resolve differently for two users.
- **`POST /api/jobs/<id>/resolve-review` validates the selection before
  it writes.** A `company_id` that is retired or absent answers
  `400 {"error": "Company not found."}` with no side effect; before, the
  capability wrote a `name_variant` onto the company and only then
  failed the job save.
- **A retired company answers like one that never existed, on writes
  too.** `company_id` on a job PUT or an experience write is validated
  through `vault.linkable_company`: a retired id is refused with the
  same `400 {"error": "Company not found."}` a deleted id gets, for
  every caller. The exception is the link a record already carries,
  which keeps saving. A tester's review selection
  (`POST /api/jobs/<id>/resolve-review` with `company_id`) links their
  job and writes no `name_variant` onto the shared company; the admin's
  still does.
- **A record id says nothing about what the vault holds.** Ids are
  allocated from a monotonic per-kind counter, so the id of the next
  record is the same whether the last delete removed a company or left a
  tombstone -- which is what keeps the two delete outcomes below
  indistinguishable in every observable, not just in their response
  bodies.
- **`DELETE /api/companies/<id>` is a soft retire when another user's
  record links the company.** The caller's own links are a 409 reporting
  their own counts. Otherwise the delete succeeds with
  `{"deleted": "<id>"}` whether or not anybody else links it: a company
  nothing links to is removed, and one another user's record links gains
  the `retired` tombstone ([schemas](../schemas.md)). From the API the
  two are the same answer, which is the point -- the old refusal told an
  admin with no links of their own that somebody else had records there.
  A retired company then answers every company route exactly as an id
  that was never used, including a second delete, and is absent from the
  company list, the directory, the Notes page, the Taxonomy counts and
  the position form's picker. The user whose own job or experience links
  it reads and edits it unchanged.
- **Three page payloads gained one key**, `can_edit_shared` (boolean):
  `GET /api/companies/<id>?view=page`, `GET /api/jobs/<id>/taxonomy` and
  `GET /api/experiences/new` / `<id>/edit`. The front end reads it to
  leave out a control a tester's own write would refuse, rather than
  rendering a button that answers 403. The companies directory did not
  gain it: it offers no company write to hide.

`POST /login` takes `{email, password}` and answers:

| Outcome | JSON request | Form request |
|---|---|---|
| Accepted | `200 {"ok": true, "next": "/jobs"}` | `302` to `/jobs` |
| Refused | `401 {"error": "Wrong email or password."}` | `401`, the page with that message |

One message for every refusal, whichever half was wrong and whether or not
the account is disabled, so the endpoint cannot be used to find out who has
an account. `POST /logout` drops the session and answers `{"ok": true}` to a
JSON request or `302` to `/login` to a form post. Both are content
negotiated on the request body, so the React page and the no-build fallback
form share one endpoint each rather than needing one apiece.

Known limits, accepted for a test of five people and recorded in
`frontend/BUILD_NOTES.md`: no CSRF token beyond what `SameSite=Lax` plus
same-origin JSON gives, and no rate limiting on `POST /login`.

All existing default record responses and write methods retain their contracts.
`view` selects GET representations only; writes still return records. JSON
converts template tuples to arrays and rendered Markdown to strings.

- Board: `statuses`, `status_labels`, `ended_statuses`, `counts`,
  `end_reasons`, `end_note_title`, `closed_review`, `search_so_far`,
  `size_classes`, `entries`, `companies`, `function_options`, `empty`.
  `size_classes` is the company-size scale as `[code, label]` pairs,
  smallest first (micro/Micro, small/Small, medium/Medium, large/Large,
  xl/"Very large" — the taxonomy code list and its own labels, see
  PROJECT.md "Taxonomy"), the same key the Companies contracts
  carry, so both pages filter over one vocabulary and show it in one set
  of words. A page derives no label of its own: `xl` is the class that
  proves why (CAREER-71).
  The D7 keys (see [Jobs](jobs.md) for the rules behind them):
  `statuses` is the eight owner statuses in board order,
  `status_labels` the word for each one, and `ended_statuses` the three
  that end a job, so the columns and the Ended lane are not decided in
  JS. `counts` is the split, `{open, ended}`. `end_reasons` is
  `{stopped: [...], rejected: [...]}`, the suggestions the ending popup
  offers, and `end_note_title` the title the free text beside them is
  saved under through the notes endpoints. `closed_review` is the
  closed-postings banner list, one `{id, closed_at, days_closed}` per job
  before Applied whose posting has been gone for over 7 days and which has
  no `closed_reviewed_at`; it is also the set whose card shows the warning
  chip. `search_so_far` is `{applied_to, interviews, offers}` counted over
  each job's history, plus `top_stopped_reason` as `{reason, count}`,
  which is absent while no stopped job carries a reason.
  Entries retain record fields and add `needs_attention`, `company_name`,
  `company_industry`, `company_size_class` and `pending`, plus
  `on_my_board` on the `view=universe` answer only (B2). Companies maps IDs
  to `{name, industry, size_class}`: `industry` is the company's first ISIC
  sector, human-labeled (`None` with no sectors or an unknown code);
  `size_class` is the raw micro/small/medium/large/xl value (`None` when unset).
  Pending means not enriched, matching the existing card attribute; it is
  distinct from active detail enrichment.
- Job detail: `job`, `company`, `statuses`, `status_labels`, `function_labels`, `notes`,
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
    `ingest_state` that has not reached a result yet (`stub`, or
    `fetched` while the extraction worker that was handed the posting is
    still running). Neither survives a restart as an in-flight state: a
    `fetched` record is settled at startup (see the restart note below),
    and a `stub` is the fetch the owner can still retry.
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
  each company, where open means any status but won, rejected and stopped
  (`vault.ENDED_STATUSES`, the one definition the count, the page's Open
  jobs filter and the board's own split all read).
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
    and answers like every other AI reading, see AI readings below. It
    fetches nothing: the live posting may be gone, and the text to group
    is the stored one. It writes the rule-based groups (the flat lists
    under the Skills group) in the same breath, so the action lands a
    result with no model reachable, and queues the extraction that
    replaces them.
  - `PUT /api/jobs/<id>` takes the whole list, like any other field, and
    stamps owner provenance on it, after which no extraction overwrites
    it. That is the Languages editor's write path.
- AI readings. `POST /api/jobs/<id>/enrich`, `POST /api/jobs/<id>/extract`,
  `POST /api/jobs/<id>/re-extract` and `POST /api/companies/<id>/enrich`
  all answer `202 {"status": "queued"}` and nothing else (CAREER-36). The
  model host is CPU-only and takes minutes per call, so the work leaves
  the request thread: the request validates, enqueues and returns, and a
  proxy that gives up after 100 seconds has nothing left to cut short. So
  a caller never reads the read job out of one of these responses. It
  reads the outcome off the job record, which is where the queue writes
  it.
  - Validation is what still answers before the queue, and only
    validation. A missing job or company is 404. A job whose posting link
    this product will not fetch is 422 on `/enrich`. A job with no stored
    posting text is 409 on `/re-extract`, and so is a job whose reading
    is already running, each with its own `error`: that action reports
    what it did to the stored text, so answering 202 would credit it with
    another run's result. `/enrich` and `/extract` answer 202 in that
    same case, because there is one reading per job either way and the
    one already running is the one that owns the status the caller polls.
  - Where a reading stands is four fields on the job record,
    `ai_status`, `ai_error`, `ai_started` and `ai_finished`
    ([schemas](../schemas.md)), carried by every payload the front end
    polls: the jobs collection, the board, the job detail and the job
    taxonomy. `ai_status` reads queued, then running, then done or
    failed, and a job with no `ai_status` at all never tried. A failed
    reading always carries `ai_error`, one sentence in words the owner
    can read, which is what the chip shows and offers Retry beside. A
    model call that failed is a failed reading even where the offline
    rules filled fields in its place.
  - The company enrichment records no status. It is queued for the same
    shape and answers the same 202; the aggregation it writes is its own
    result, and nothing polls a company for a reading.
  - The queue lives in the server process, so a process that stops
    abandons whatever it held: a job left queued or running is marked
    failed with `ai_error` "interrupted by server restart" the next time
    the server starts. Nothing stays in flight forever. The extraction
    worker lives in that process too, so the same startup settles the
    ingest side with the same words: a job left at `ingest_state:
    fetched` becomes `extract_failed` with `ingest_error {stage:
    extract, reason: "interrupted by server restart", at}` and is
    retryable through `/extract` like any other failed reading
    (CAREER-45). A `stub` is left alone: nothing had taken it on yet.
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
  `{size_class, count}` in the size vocabulary's own order
  (micro/small/medium/large/xl) plus a trailing `unknown` bucket, always
  present even when no companies exist. One row per class in the
  vocabulary, so a class added to the taxonomy appears here on its own.

Pure assembly functions in the four existing page modules receive explicit
record snapshots. Shared read-only loaders supply them to HTML and JSON.
The board JSON representation projects company names from the shared context.
No template changed. The reuse ladder stops at extending existing builders and
routes; a serializer framework and new dependencies are unnecessary. Revisit
only if a later page contract needs behavior the current builders cannot express.

## States

No session is its own state, ahead of every state below: an API call is
401 and a page request is a redirect to `/login`, before any record is
read. An account that exists but is disabled is in that same state, so
turning an account off is what ends its session.

Somebody else's job or experience is deliberately not a state of its
own: it is the missing-record state, byte for byte (M2, decision D3).
A refused write to shared data is a state of its own, 403 with one
sentence, because the record is there and the caller may read it.

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
