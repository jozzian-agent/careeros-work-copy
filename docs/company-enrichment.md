---
type: Surface
title: "Company enrichment"
description: "Describe the company enrichment endpoint and stored output."
timestamp: 2026-10-11
---

# Company enrichment

Company YAML stores regenerable posting facts under `enrichment`. Owner fields,
including `sector`, `locations`, `notes`, and custom fields, remain independent.
Unknown enrichment keys are retained, including keys inside the two nested objects.

Job creation, updates, deletion, company reassignment, and watcher persistence
refresh affected companies synchronously. Reassignment refreshes both companies.
`POST /api/companies/<identifier>/enrich` also refreshes a company from stored
postings, including older postings. It returns the company or HTTP 404 if absent.
The endpoint uses the existing write lock. No fetching or text extraction occurs.

| Field | Meaning |
| --- | --- |
| `sectors` | Sorted distinct nonempty values from `sector`, `sectors`, `industry`, and `industries` |
| `locations_seen` | Sorted distinct nonempty posting locations |
| `remote_friendly` | True if at least one posting has boolean `remote_ok: true` |
| `seniority_range` | `min` and `max` recognized seniority labels, or null bounds |
| `hiring_activity` | Posting `count` and `most_recent_posted_date`, or null date |
| `top_keywords` | At most ten normalized keywords ordered by posting frequency, then alphabetically |

All stored postings count, regardless of application status. Repeated keywords
within one posting count once. Keyword matching ignores case and surrounding
whitespace. Sector and location values retain their case after trimming.
Malformed legacy values are ignored when aggregating.

Seniority follows this explicit ordering: intern, entry, junior, mid, senior,
lead, staff, principal, manager, director, executive. This is a convention for
mixed posting labels, not an inference about reporting relationships. Internship,
entry-level, mid-level, and associate aliases are normalized. Unrecognized labels
are excluded from the bounds.

The vault validates known enrichment types on company writes. Future unknown
keys are tolerated. Regeneration replaces known derived values and retains owner
fields and unknown extensions. External file edits can be incorporated through
the refresh endpoint.
