---
type: Surface
title: "Vault schemas — Chunk 3"
description: "Describe vault records and their JSON API representation."
timestamp: 2026-10-14
---

# Vault schemas — Chunk 3

Select a vault with `--vault PATH` or `CAREEROS_VAULT`; the explicit flag wins.
Only `sample/vault/` contains synthetic development records.
Missing directories and files are valid empty states; reads never create files.
Writes use safe YAML and atomic file replacement. The local Flask app serializes
writes within its process; run one server process per vault.

The vault also holds one file that is not a record: `secret_key`, the key the
session cookie is signed with, created on first boot with mode 0600 and read
on every later one, so a session outlives the process
([users](#usersname-idyaml)). It is the one file a start writes whatever else
it does, and the vault directory is created for it if it is not there yet,
because every request reads the session: a server with no key could not serve
even the login page. It is written atomically, and a file found empty or
truncated is replaced with a warning rather than adopted, which signs out
everybody holding a cookie signed with the old one.

## `users/<name>-<id>.yaml`

| Field | Type | Meaning |
| --- | --- | --- |
| id | string, `USER-###` | Allocated as max existing numeric ID plus one |
| email | nonempty string | The address signed in with, stored and matched lowercase, unique across the area |
| name | nonempty string | What to call the person |
| role | fixed list | `admin` or `tester` (`careeros.users.ROLES`) |
| password_hash | nonempty string | A werkzeug `generate_password_hash` hash, never a plain password |
| created_at | ISO timestamp | Set on the first save and never rewritten |
| disabled | boolean | True turns the account off; it is refused on its next request |

Added in M1 (accounts and required login). A user record never holds a plain
password: a payload carrying a `password` key is refused rather than quietly
dropped, and a `password_hash` that does not look like a werkzeug hash is
refused too, so a plain password cannot be stored by mistake. The field list
above is also applied to the stored record and not only to the payload, so a
key added to a file by hand is dropped the next time that record is saved.
Nothing outside this area holds either value, and no log line carries one.

Accounts are managed from the command line, since the first admin cannot sign
in to create themselves and M1 has no web UI for user management:

```bash
python -m careeros.users --vault PATH create --email ... --name ... --role admin --password ...
python -m careeros.users --vault PATH list
python -m careeros.users --vault PATH reset-password --email ... --password ...
python -m careeros.users --vault PATH disable --email ...
python -m careeros.users --vault PATH enable --email ...
```

`--role` defaults to `tester`, so an admin is only ever created by asking for
one; asking while an admin already exists prints a warning rather than
complying quietly. `list` never prints a hash. The role is read off the record
on every request and is not carried in the cookie, so M1 stores it without yet
reading it anywhere: the gate asks whether there is a user, never which kind,
because the vault is still one shared world (the per-user split is M2).

## `search.yaml`

| Field | Type | Meaning |
| --- | --- | --- |
| updated | ISO date | Set to today's server-local date on save |
| roles | list of strings | Target titles |
| must_haves | list of strings | Hard requirements |
| nice_to_haves | list of strings | Preferences |
| avoid | list of strings | Deal-breakers |
| notes | string | Free-form text |

All lists and notes may be empty. POST `/api/search` replaces criteria and returns
the saved document. GET returns the current document, or JSON null when missing.

## `experiences/<company-title>-<id>.yaml`

| Field | Type | Meaning |
| --- | --- | --- |
| id | string, `EXP-###` | Allocated as max existing numeric ID plus one |
| company | nonempty string | Employer |
| title | nonempty string | Position |
| start | string, `YYYY-MM` | First month |
| end | string, `YYYY-MM` or `present` | Last month, not before start |
| location | string | Location or remote arrangement |
| summary | string | Suggested 2–4 sentence overview |
| highlights | list of strings | Achievement bullets |
| skills | list of strings | Skill chips |
| people_led | nonnegative integer or null | Team size; zero is displayed |
| salary | any YAML value or null | Private, tier-3, file-only; samples ALWAYS null |
| detail | string | Long-form safe Markdown subset |
| custom | mapping with string keys | Arbitrary safe-YAML values |

Quote year-month strings in hand-authored YAML. The safe Markdown subset supports
paragraphs, `-`/`*` unordered lists, **bold**, and *italic*. HTML is escaped; links,
images, and other Markdown syntax are not interpreted. Custom values render as
escaped text or JSON in a definition list. Custom form values accept JSON for
nested data, numbers, booleans, or null; otherwise they are strings. Quote a value
as a JSON string to keep numeric-looking text as text.

POST `/api/experiences` allocates an ID and creates a file. GET lists positions
sorted by start descending. GET `/api/experiences/<id>` reads one; PUT or POST
replaces its editable fields; DELETE removes it. Missing IDs return 404 and
invalid documents return 400. Compensation is ignored on creation and preserved
from the existing file on update, regardless of submitted values. Only non-null
compensation appears on the detail page with a private lock affordance.

Company and title are slugified for filenames; the ID suffix prevents same-title
collisions. Edits retain the ID and rename the file if needed. IDs are allocated
from files currently present (deleting the highest ID permits its reuse).

## Later host-side import

After acceptance, an independently authorized host-side importer can map position
records into this schema, allocate IDs, and write one YAML file per position.
It should preserve long-form detail and custom values and handle tier-3 salary
only in vault files. No importer is part of Chunk 1, and no real vault is read by
the sample workflow. Back up the destination vault before a future import.


## `jobs/<title>-<id>.yaml`

| Field | Type / meaning |
| --- | --- |
| id | Allocated `JOB-###` |
| company_id | Existing `CO-###` or null |
| title | Nonempty string |
| url | HTTP(S) pasted posting URL |
| original_url | Original HTTP(S) posting URL; ATS intake retains the pasted URL here and in url |
| source | ATS platform label (Personio, Greenhouse, Lever, Workable, Ashby, SmartRecruiters, BambooHR, Monday, jobs.ch); otherwise domain guess |
| status | new, interested, applied, interviewing, offer, won, rejected, stopped (`vault.STATUSES`, owner decision D7). Won, rejected and stopped end a job (`vault.ENDED_STATUSES`); every other status leaves it open. Closed and withdrawn are retired: a closed posting is the `closed` flag below, and stopped replaced withdrawn |
| posted_date | ISO date or null |
| added | ISO date, server-local today on creation |
| salary_info | Boolean, public disclosure present |
| salary_note | String, public posting salary hint, otherwise empty |
| location | String, best-effort location hint |
| remote_ok | Boolean or null when unknown |
| notes | String, the pre-note_list free-text notes field. Legacy: see note_list |
| note_list | List of `{id, title, body, created, updated}`, the owner's notes |
| enriched | Boolean, false on intake; true after successful enrichment fetch and extraction |
| employment_type | String from JSON-LD employmentType; arrays joined with commas |
| valid_through | String from JSON-LD validThrough (date or timestamp), otherwise empty |
| custom | Mapping with string keys |
| status_changed | ISO date, set/overwritten when an existing job changes status |
| closed | Boolean, true once the posting is no longer online. A fact about the posting, set by the watcher, never a status |
| closed_at | ISO date the posting was first found gone, or null |
| closed_reviewed_at | ISO date the owner kept a job whose posting closed, or null. Takes it out of the board's closed-postings review |
| end_reason | One of `vault.STOPPED_REASONS` / `vault.REJECTED_REASONS`, or null. Always optional; the free text the owner adds beside it is an ordinary note on the job, under `vault.END_NOTE_TITLE` |
| ai_status | Where this job's AI reading stands: `queued`, `running`, `done` or `failed` (`vault.AI_STATUSES`), written by the queue that runs the reading. Null, and absent on every record written before the field, means never tried |
| ai_error | The sentence a failed reading leaves behind, in words the owner can read. Null in every other status: whatever moves the status on takes the reason with it. Never an exception message, since a transport failure names the host it was talking to |
| ai_started | Timestamp the reading began, or null. A finished reading keeps it, so a record still says when it started |
| ai_finished | Timestamp the reading ended, done or failed, or null while one is owed |

Requirements are stored twice over, on purpose. `description_structured`
holds the flat shape every job written before package 2 has
(`{summary, requirements, nice_to_have, method}`, where `method` is
`llm`, `heuristic`, `raw` or `user`, the last one being a block the owner
wrote in Edit job), and `requirement_groups` holds the grouped shape:

| Field | Type / meaning |
| --- | --- |
| requirement_groups | List of `{group, level, text}`, one entry per qualification the posting asks for |
| requirement_groups[].group | One of `education`, `experience`, `skills`, `languages`, `certifications`. Fixed list; a requirement the extractor cannot place lands in `skills` |
| requirement_groups[].level | `must` when the posting requires it, `nice` when it only prefers it |
| requirement_groups[].text | The qualification in the posting's own words, nonempty |

The groups carry one entry per group and text, with a must-have winning
over a nice-to-have for the same line, and text with no padding on it:
`vault.validate_requirement_groups` holds that invariant for every
writer. An empty list with no `requirement_groups` entry in
`field_provenance` means the job has no grouped requirements yet, which
is where every job written before package 2 starts. An empty list that
is stamped `user` means the owner emptied it on purpose, and the two are
read differently: the first still shows the flat lists and is filled by
any write path, the second renders as a grouped job with nothing in it
and is filled by nothing but the owner, or by the reading the owner asks
for with Re-extract, which takes that stamp off the field so the answer
can land. Every write path fills the groups for a job added since the
package (the offline intake pass, the queued model pass, the
fill-the-empty-fields enrich, and the owner's own edit), so for a job
written before them the owner's per-job Re-extract action
(`POST /api/jobs/<id>/re-extract`) is the only thing the interface
offers, and no read ever migrates a record. Languages have no field of
their own; a language the posting asks for is an entry in the `languages`
group.

GET `/api/jobs` lists jobs newest-added first. GET/PUT/DELETE
`/api/jobs/<id>` reads, partially updates editable schema fields, or deletes a
job. Missing records return 404; invalid status, type, URL, company link, or date
returns 400. IDs cannot be edited. Updates preserve unspecified fields and
atomically replace YAML; status_changed is server-managed.

POST `/api/jobs/intake` accepts `{ "url": "https://employer.example/careers/role" }`
and returns `{ "job": {...}, "company": {...} }` with status 201. The module-level
`careeros.intake.fetch_url` hook uses plain GET, a custom User-Agent, a ten-second
timeout and a two-megabyte read cap. Tests replace this hook and never fetch.
Metadata/title and visible-text regexes supply tentative hints without an LLM;
failure still creates a URL-derived title. Company names dedupe case-insensitively.
The domain guess handles common multipart suffixes but is not a full public-suffix
resolver. JavaScript-only or protected postings usually need later enrichment.
No original company URL is invented from an ATS URL.

## `companies/<name>-<id>.yaml`

| Field | Type / meaning |
| --- | --- |
| id | Allocated `CO-###` |
| name | Nonempty string |
| name_source | `auto` for intake/enrichment-created companies; `owner` after every human PUT. Missing provenance is treated as `owner`. |
| website | HTTP(S) employer website from JSON-LD sameAs/url, or null |
| size | String or null, e.g. 50-200. Legacy and read-only: nothing writes one since 2026-10-16 (CAREER-33); `size_class` is the one size scale (PROJECT.md Fixed lists). Still read, and still writable by an owner PUT. |
| locations | List of strings |
| sector | String or null |
| notes | String, the pre-note_list free-text notes field. Legacy: see note_list |
| note_list | List of `{id, title, body, created, updated}`, the owner's notes |
| custom | Mapping with string keys |

GET `/api/companies` lists profiles by name. GET/PUT `/api/companies/<id>`
reads or partially updates a profile with the same 400/404 conventions. The UI
edits profile fields except ID and server-managed name_source and links its jobs. Open-job counts exclude
won, rejected and stopped jobs (offers still count as open).

Both collections use max existing numeric ID plus one, ID-suffixed slugs, and
atomic saves, like experiences. Missing directories are empty; corrupt,
empty, and non-mapping YAML is skipped via the shared reader. Renaming preserves
IDs and removes the old filename. Deleting the highest job permits ID reuse.
Sample public salary disclosures are synthetic; experience salary remains null.

Notes are a list, not a field. A note is `{id, title, body, created,
updated}` under `note_list`, and it belongs to the one job or company
record whose file it sits in. A record written before the list keeps its
text in the free-text `notes` string; reads surface that string as the
record's one note (title "Note", id `legacy`, null timestamps) without
touching the file, and the first write through the notes endpoints
persists it into `note_list` and clears the string in the same save. A
write that does not carry notes at all preserves whichever shape is
stored, as every other field is preserved. Endpoint contracts are in
[JSON page contracts](surfaces/json-api.md).


### Chunk 3.5 extraction and enrichment

JSON-LD JobPosting (including arrays and @graph) takes precedence over social
metadata and title heuristics. Known ATS slugs are employer-name fallbacks;
jobs.ch is never an employer fallback. Unknown employers produce a null company
link and a null company in the intake response rather than an empty profile.
Company website hints undergo structural HTTP(S) validation and are not fetched.

POST `/api/jobs/<id>/enrich` checks the URL on the request thread and queues
everything after it, so what follows is what the queued reading writes to the
record. What the caller gets back, and where it reads the outcome, is one home
over in [JSON page contracts](surfaces/json-api.md).

The reading fetches and extracts before acquiring the write lock. Under the lock
it reloads the current job, reconciles companies, and saves. A job deleted while
its posting was being read, and a posting URL changed under the reading, each end
the reading with ai_status failed and the reason saying which, and write nothing.
It fills empty metadata, preserving nonempty titles, status, notes and custom
fields. Only the first enrichment may fill salary_info/salary_note; when enriched
is already true, both salary fields remain untouched, including false/empty owner
values. All nonempty titles are treated as owner-set. A fetch that returns
nothing, and an extraction that fails, fill nothing and leave ai_status failed
with the reason. A posting the model could not be reached for still fills
whatever the offline rules read off it, and is still a failed reading: enriched
says the posting was read and the empty fields were filled, and ai_status says
whether the reader itself answered. Employer names dedupe case-insensitively. Only companies with name_source=auto
may be renamed when unshared or reconciled to an existing match. Owner or unknown
provenance preserves the linked company and name; website hints only fill an
empty website. Matching profiles also receive website hints only when empty.
Shared auto profiles remain intact; new extracted employers get name_source=auto.
Both posting URLs remain unchanged.

With multiple JSON-LD JobPosting nodes, the request URL (full URL or path) is
matched against url/mainEntityOfPage before falling back to the first node.
Salary hints support leading and trailing currencies, including CHF ranges and
USD ranges expressed in k.

Board/List preference is stored in browser localStorage. Status filters apply to
both views; bulk enrichment processes pending jobs in the current filter sequentially.

Mobile list view hides table headers and offers a Sort by selector using the same sorting function as desktop headers.


### Chunk 3.5b deletion and company metadata

DELETE `/api/companies/<id>` returns `{"deleted": "<id>"}`; unknown IDs
return 404. Any linked job (including ended ones) blocks deletion with 409,
`count`, and `error: "Still linked to N jobs"`. Jobs are never cascade-deleted.
Job and company detail pages require confirmation before deletion.

JSON-LD JobPosting.jobLocation PostalAddress addressLocality, addressRegion,
and addressCountry (text or a named country object) supply the job location
string and the company locations list, deduplicated in source order.
Existing text-location heuristics remain the fallback. hiringOrganization.url
(or sameAs) supplies website; industry supplies sector when it is text.
numberOfEmployees, either a number/numeric string or QuantitativeValue.value,
is kept as the raw `employee_count` and nothing else; a range string resolves
to its upper bound. Absent or invalid hints remain empty. That count is what
the company's `size_class` is derived from. It used to be bucketed into a
numeric range as well, which the company's legacy `size` field then stored
beside the class — one signal writing two scales, retired by owner decision
2026-10-15 and removed from this path 2026-10-16 (CAREER-33).

The count is stored, not dropped (owner decision 2026-10-16). It stays on the
job as `employee_count`, and the company aggregation
(`careeros.enrich.enrich_company`) carries it into
`enrichment.employee_count` with an `enrichment.employee_count_evidence`
record of `{count, job_id, posted_date}`, which is the zero-network tier of
the size cascade (`org_intake.enrich.promote_aggregated_size`). So a company
whose only size signal is one of its own postings gains evidence a later size
run derives the class from, under the unchanged rules: fill-empty-only, a
contradiction flags instead of writing, neither retired scale is written, and
a non-employer keeps none of it. Of several stated counts the most recently
posted wins, otherwise the first stated.

Intake and enrichment fill sector, size_class and locations only when the
selected company's field is empty/missing, regardless of name_source.
Nonempty owner values always win. Company selection and name/website provenance rules remain
unchanged; hiringOrganization.address does not replace the job's location.
