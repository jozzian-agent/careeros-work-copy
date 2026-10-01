# Vault schemas — Chunk 3

Select a vault with `--vault PATH` or `CAREEROS_VAULT`; the explicit flag wins.
Only `sample/vault/` contains synthetic development records.
Missing directories and files are valid empty states; reads never create files.
Writes use safe YAML and atomic file replacement. The local Flask app serializes
writes within its process; run one server process per vault.

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
| status | new, interested, applied, interviewing, offer, rejected, closed, withdrawn |
| posted_date | ISO date or null |
| added | ISO date, server-local today on creation |
| salary_info | Boolean, public disclosure present |
| salary_note | String, public posting salary hint, otherwise empty |
| location | String, best-effort location hint |
| remote_ok | Boolean or null when unknown |
| notes | Safe Markdown string, same subset as experience detail |
| enriched | Boolean, false on intake; true after successful enrichment fetch and extraction |
| employment_type | String from JSON-LD employmentType; arrays joined with commas |
| valid_through | String from JSON-LD validThrough (date or timestamp), otherwise empty |
| custom | Mapping with string keys |
| status_changed | ISO date, set/overwritten when an existing job changes status |

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
| size | String or null, e.g. 50-200 |
| locations | List of strings |
| sector | String or null |
| notes | Safe Markdown string |
| custom | Mapping with string keys |

GET `/api/companies` lists profiles by name. GET/PUT `/api/companies/<id>`
reads or partially updates a profile with the same 400/404 conventions. The UI
edits profile fields except ID and server-managed name_source and links its jobs. Open-job counts exclude
rejected, closed, and withdrawn jobs (offers still count as open).

Both collections use max existing numeric ID plus one, ID-suffixed slugs, and
atomic saves, like experiences. Missing directories are empty; corrupt,
empty, and non-mapping YAML is skipped via the shared reader. Renaming preserves
IDs and removes the old filename. Deleting the highest job permits ID reuse.
Sample public salary disclosures are synthetic; experience salary remains null.


### Chunk 3.5 extraction and enrichment

JSON-LD JobPosting (including arrays and @graph) takes precedence over social
metadata and title heuristics. Known ATS slugs are employer-name fallbacks;
jobs.ch is never an employer fallback. Unknown employers produce a null company
link and a null company in the intake response rather than an empty profile.
Company website hints undergo structural HTTP(S) validation and are not fetched.

POST `/api/jobs/<id>/enrich` checks the URL, fetches and extracts before acquiring
the write lock. Under the lock it reloads the current job, reconciles companies,
and saves. Deletion during fetch returns 404; a changed posting URL returns 409.
It fills empty metadata, preserving nonempty titles, status, notes and custom
fields. Only the first enrichment may fill salary_info/salary_note; when enriched
is already true, both salary fields remain untouched, including false/empty owner
values. All nonempty titles are treated as owner-set. Empty responses or
fetch/extraction failures return 422 without writes. Success sets enriched=true.
Employer names dedupe case-insensitively. Only companies with name_source=auto
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
return 404. Any linked job (including closed jobs) blocks deletion with 409,
`count`, and `error: "Still linked to N jobs"`. Jobs are never cascade-deleted.
Job and company detail pages require confirmation before deletion.

JSON-LD JobPosting.jobLocation PostalAddress addressLocality, addressRegion,
and addressCountry (text or a named country object) supply the job location
string and the company locations list, deduplicated in source order.
Existing text-location heuristics remain the fallback. hiringOrganization.url
(or sameAs) supplies website; industry supplies sector when it is text.
numberOfEmployees, either a number/numeric string or QuantitativeValue.value,
maps to size: 1–10, 11–50, 51–200, 201–1000, and above 1000 map to
`1-10`, `11-50`, `51-200`, `201-1000`, and `1000+`, respectively.
Absent or invalid hints remain empty.

Intake and enrichment fill sector, size, and locations only when the selected
company's field is empty/missing, regardless of name_source. Nonempty owner
values always win. Company selection and name/website provenance rules remain
unchanged; hiringOrganization.address does not replace the job's location.
