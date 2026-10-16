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

`POST /api/companies/<identifier>/retry` is the owner-triggered sector and size
retry for one employer company (it replaced the former sweep-all Backfill
button). It runs the same cascade as the automatic new-company path, does the
network phase outside the write lock, and returns the saved company plus a
call-fresh `retry_applied` list naming the cascade fields this invocation
actually wrote. Clients decide whether the retry changed anything from
`retry_applied` alone, never from stored field states, which can carry an older
run's results.

| Field | Meaning |
| --- | --- |
| `sectors` | Sorted distinct nonempty values from `sector`, `sectors`, `industry`, and `industries` |
| `locations_seen` | Sorted distinct nonempty posting locations |
| `remote_friendly` | True if at least one posting has boolean `remote_ok: true` |
| `seniority_range` | `min` and `max` recognized seniority labels, or null bounds |
| `hiring_activity` | Posting `count` and `most_recent_posted_date`, or null date |
| `top_keywords` | At most ten normalized keywords ordered by posting frequency, then alphabetically |
| `employee_count` | The headcount the company's own postings state, or null. Size evidence, not a size field: this is the zero-network tier the size cascade reads (`org_intake.enrich.promote_aggregated_size`), so it can derive `size_class` from a posting instead of the number being read once at intake. Of several stated counts the most recently posted wins; failing any dated posting, the first stated. A value nothing can read as a positive headcount is absent evidence, not a zero. |
| `employee_count_evidence` | `{count, job_id, posted_date}` for the posting the count above came from, or null — which posting said so, and when |

All stored postings count, regardless of application status. Repeated keywords
within one posting count once. Keyword matching ignores case and surrounding
whitespace. Sector and location values retain their case after trimming.
Malformed legacy values are ignored when aggregating.

The size evidence obeys the existing derivation rules unchanged (owner decision
2026-10-16): fill-empty-only, so it never overwrites a stored `size_class`; a
count that contradicts a stored class or a legacy numeric range raises
`size-inconsistent` rather than writing; neither retired scale (`size_range`,
the legacy `size` string) is ever written from it. Section 1's field-group
matrix still gives a non-employer no size, so re-kinding a company away from
`employer` deletes both keys the same way it deletes the nested
`enrichment.sectors` rollup.

Seniority follows this explicit ordering: intern, entry, junior, mid, senior,
lead, staff, principal, manager, director, executive. This is a convention for
mixed posting labels, not an inference about reporting relationships. Internship,
entry-level, mid-level, and associate aliases are normalized. Unrecognized labels
are excluded from the bounds.

The vault validates known enrichment types on company writes. Future unknown
keys are tolerated. Regeneration replaces known derived values and retains owner
fields and unknown extensions. External file edits can be incorporated through
the refresh endpoint.
