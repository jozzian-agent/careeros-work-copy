# Vault schemas — Chunk 1

Select a vault with `--vault PATH` or `CAREEROS_VAULT`; the explicit flag wins.
Only `sample/vault/` contains the invented Neri Quill persona used during development.
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
