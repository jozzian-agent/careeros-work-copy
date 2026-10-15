---
type: Flow
title: "CareerOS — Journey Specs (handoff to coding agent)"
description: "Describe adding a job by link and the constraints on later journeys."
timestamp: 2026-10-15
---

# CareerOS — Journey Specs (handoff to coding agent)

Status: draft v1. Scope for this handoff: **Journey 1 is built now.** Journeys 2 and 3 are written as *constraints on Journey 1*, not as work items.

---

## 0. How to read this

- Journeys describe what the user does and what they must see. They are the source of truth; feature lists derive from them.
- Where a journey says "visible", it means visible in the UI, not just stored in the vault.
- Anything not specified here must be raised as a question, not decided silently.
- Existing shipped behaviour (company enrichment cascade, Decision-20, signal accounting, watcher, write-lock) is reused as-is unless a section says otherwise.

## 1. Global rules (apply to every journey)

1. **Human edits always win.** Any field the user has entered or edited is never overwritten by an automated step (ingest, extraction, enrichment, backfill, watcher). Each field carries provenance (`user` / `wikidata` / `jsonld` / `llm` / `scrape`); automated writes only fill fields that are empty and not `user`-provenanced. This also closes the stale-plan race for the new async steps: apply per field at write time, under the write-lock, re-reading current state, never apply a precomputed whole-record plan.
2. **No silent fallbacks.** Every failure, skip, or ambiguity is a visible state with a reason and, where possible, a retry or manual action. "Unknown" must be distinguishable from "not tried", "tried and found nothing", and "conflict, needs review".
3. **Confident matches only (Decision-20).** Ambiguous or contradictory results fill nothing and raise a review flag.
4. **Never reject user input.** A pasted URL always produces a job record, even if everything downstream fails.
5. **Done means live.** Each journey is accepted by running it on a clickable instance, not by tests passing. Section 8 lists the live checks.
6. **No journey-1 code may assume a human triggered it.** The ingest entry point takes an `origin` (`manual` | `discovered`) so Journey 2 can reuse it.

## 2. Concepts

| Concept | Meaning |
|---|---|
| **Company** | One record per real organisation. Never split by country. Country lives on the job's `location`. |
| **Identifier** | A way to recognise a company: primary domain, ATS tenant (`provider:slug`, e.g. `greenhouse:acme`), Wikidata ID, name variant. A company has many. |
| **Source** | A place jobs are listed for a company: a careers page or an ATS feed. A company can have several (global + regional). Journey 2 polls sources. |
| **Job** | One posting, identified by normalized URL (and ATS posting ID where available). |
| **Universe** | All known jobs for all companies. Jobs discovered by sources land here. |
| **Pipeline** | The subset of jobs the user has promoted, carrying their status, notes and history. |

**MVP storage rule:** keep a single `jobs/` store. Add `in_pipeline: bool` and `origin: manual | discovered`. Manually added jobs are `in_pipeline: true`; discovered jobs are `false`. This keeps the Universe/Pipeline split cheap now and mappable to "shared universe DB + per-user pipeline entry" when hosted.

## 3. Journey 1 — Add a job by URL

### Intent
I find a job while browsing, paste the URL, and it shows up in my list immediately, linked to the right company, with details filling in as they become available. I triage it (new → interested → applied → …).

### Trigger
User submits a URL in the add-job input.

### Preconditions
None. Works for any URL, including ones that cannot be fetched.

### Steps and system behaviour

**Step 1 — Normalize URL.** Lowercase host, strip fragments and tracking params (utm_*, gclid, etc.), normalize trailing slash, keep ATS posting IDs. Store as `normalized_url`; keep the raw input as `original_url` if different.

**Step 2 — Hard duplicate check (instant, no network).** Compare `normalized_url` and ATS posting ID against all jobs (pipeline and universe).
- Match found → do **not** create yet. Show a warning: "This looks like a job you already have", with the existing record shown side by side with what was pasted, the basis of the match ("same URL" / "same ATS posting ID"), and two actions: **Open existing** / **Add anyway**.
- If the existing match is in the universe but not in the pipeline, the primary action is **Promote to my pipeline** (not "duplicate"), since this is the normal Journey-2 case.
- Never auto-merge, never silently drop.

**Step 3 — Create the stub instantly.** Job record with `status: new`, `ingest_state: stub`, `in_pipeline: true`, `origin: manual`, history event `created`. It appears in the list immediately. This must not wait on the network or the LLM.

**Step 4 — Company resolution (ladder).** Run what is possible without the page first, then finish after fetch:
1. URL's ATS tenant matches a known company identifier → auto-link.
2. URL's domain matches a known company identifier → auto-link.
3. After fetch: extracted company name matches an existing company only fuzzily (e.g. "Acme" vs "Acme GmbH") → **do not auto-link.** Set `company_link_state: needs_review` and show "Is this Acme GmbH?" with candidates and a "none of these / create new" option.
4. Nothing matches → create a new company with the identifiers found (domain, ATS tenant), then trigger the existing enrichment cascade (promotion text from this job → Wikidata → JSON-LD → optional LLM) under Decision-20.
5. Flags (never guessed):
   - **Staffing/recruiter posting:** the employer named in the posting differs from the owner of the ATS tenant → `company_link_state: needs_review`, reason `employer_differs_from_tenant`.
   - **Shared tenant:** one tenant observed hosting multiple distinct employers → same treatment.

While unresolved, the job shows "Company: pending" or "Company: needs your input", never blank.

**Step 5 — Fetch the page.** On success, store the raw text in `description`, set `ingest_state: fetched`, record history. On failure (network error, login wall, JS-only page, blocked, LinkedIn-style gating) set `ingest_state: fetch_failed` with `ingest_error {stage, reason, at}`. The job stays in the list. The UI offers **Retry fetch** and **Paste posting text manually**; pasting text moves the job on to extraction.

**Step 6 — Extraction (queued, local LLM).** Runs asynchronously; the UI must not block on it. Per-field progress is visible via `field_status` (`pending` / `done` / `failed` / `not_evidenced`). Rules:
- Emit `null` / `not_evidenced` rather than a guess when the text does not support a field. (Known failure: a thin careers-page posting produced `employment_type: internship` on a Senior PM role.)
- Set `posting_quality: thin | ok | rich` from the text and show it. Thin postings display a notice that extraction will be limited.
- Extraction applies per field, respecting global rule 1.
- LLM failure → `ingest_state: extract_failed`, visible, with **Retry**.
- A function id the reading returns that the vault's `function` facet does not carry cannot be stored, so it is dropped (decision 23). The drop is never silent: the count and the ids are logged, and when no id survives, `field_status.function` stays `not_evidenced` with a `field_status_reason` naming the ids, which is what tells an unseeded registry apart from a posting that said nothing about the role. Seeding the facet is [its own runbook](../runbooks/seed-function-facet.md).

**Step 7 — Soft duplicate check (after company + title known).** Compare company + title + location (normalized). Possible match → non-blocking warning on the job: "Possible duplicate of JOB-0xx" with the compared fields and a confidence reason; actions **Open other** / **Not a duplicate** / **Mark as duplicate (close this one)**. Never auto-merge.

**Step 8 — Start the watcher.** Existing behaviour: history event `watch_started`.

### States
Job ingest: see §4.1. Company link: `linked` | `pending` | `needs_review`. Duplicate: `none` | `possible` | `dismissed`.

### Failure paths (all must be visible, none may delete the job)
- Fetch fails → stub stays, manual paste available.
- Extraction fails → fetched job stays, retry available.
- Company ambiguous → job stays, "needs your input".
- Company enrichment finds nothing → company shows per-field `exhausted` (see §4.2), not a blank.
- Duplicate suspected → warning, user decides.

### End state (visible)
Job is in the list with a status the user can triage. Company is linked (or visibly pending/needs input). Fields that were extracted show their values; fields that were not evidenced show why. A new company shows its sector/size, or an honest flagged/exhausted state.

### Out of scope for Journey 1
Careers-page polling, discovery, fit scoring, user profile, retry schedules for exhausted companies, hosted multi-user.

## 4. State machines

### 4.1 Job ingest

```
(stub) --fetch ok--> (fetched) --extract ok--> (complete)
  |                      |
  |--fetch fail--> (fetch_failed) --retry / manual paste--> (fetched)
                         \
 (fetched) --extract fail--> (extract_failed) --retry--> (fetched → complete)
```

Rules:
- Every transition appends a history event (`fetched`, `fetch_failed`, `llm_enriched`, `extract_failed`, ...) with timestamp.
- Failed states are terminal only until user retries. No automatic infinite retry; the existing watcher cadence is separate.
- `complete` means extraction ran, not that every field is filled. Per-field truth lives in `field_status`.

### 4.2 Company field enrichment (per field: sector, size)

States: `never_tried` → `filled` | `flagged` | `exhausted`.

- `filled`: confident value, with provenance.
- `flagged`: ambiguous/contradictory signal, nothing written, review flag raised (existing Decision-20 behaviour).
- `exhausted`: all signals tried, nothing found. Stores `last_attempted` and the per-signal results (existing signal accounting).
- Manual entry sets `filled` with provenance `user` and is never overwritten (global rule 1).
- Journey 1 only needs to **set** these states and display them. Retry triggers (new job text, website changed, manual re-enrich) are a later journey; do not build a scheduler for them now.
- UI must show the state, not just the value: "Sector: not tried yet" vs "Sector: nothing found (Wikidata, website, LLM)" vs "Sector: needs review".

## 5. Data deltas (additions only; existing model unchanged)

**Job**
- `normalized_url`, `original_url` (already exists, keep semantics)
- `ingest_state`: stub | fetched | complete | fetch_failed | extract_failed
- `ingest_error`: {stage, reason, at}
- `field_status`: map of extracted field → pending | done | failed | not_evidenced
- `field_status_reason`: map of extracted field → text, saying why that field reads as it does when the status word alone would mislead. Only a field whose status is `not_evidenced` can carry one, and the vault drops the entry as soon as the field moves on, so a reason can never outlive the state it explains. Its first writer is the function-id drop below.
- `field_provenance`: map of field → user | llm | scrape | ...
- `posting_quality`: thin | ok | rich
- `company_link_state`: linked | pending | needs_review; `company_link_reason`
- `employer_named_in_posting`: text extracted from the posting (used for the staffing/shared-tenant check)
- `duplicate`: {state, of_job_id, basis, reason}
- `in_pipeline`: bool; `origin`: manual | discovered; `source_id`: nullable, set by Journey 2
- Reserved, nullable, not populated yet: `occupation_code` (ISCO), `skill_codes` (ESCO)

**Company**
- `identifiers`: list of {type: domain | ats_tenant | wikidata | name_variant, value, provenance}
- `sources`: list of {id, kind: careers_page | ats_feed, url, ats_provider, active, last_polled}. Created/populated by Journey 1 when seen, polled only by Journey 2.
- Per-field enrichment state as in §4.2.

No schema for user profile yet (Journey 3).

## 6. Journey 2 (future) — Watch companies, fill the Universe

Not built now. **Constraints on Journey 1:**
- Reuse the same ingest path with `origin: discovered`; do not fork a second pipeline.
- Discovered jobs get `in_pipeline: false`. They never appear in the user's list automatically; they appear in a **Job Universe** view.
- Dedupe by normalized URL / ATS posting ID, so re-polling never creates duplicates.
- Company `sources` (careers page, ATS feed) are the polling targets; ATS tenants must be parsed into identifiers/sources at ingest time in Journey 1.
- Large companies must stay manageable: Universe needs filtering (company, location, seniority, function) rather than a flat list. Design the list view in Journey 1 so filters can be added without rework.
- Open: whether LLM extraction runs for every discovered job or lazily (on view/promote). Journey 1 should make extraction callable per job so either works.

## 7. Journey 3 (future) — Fit scoring against my profile

Not built now. **Constraints on Journey 1:**
- Extraction should emit normalized, list-shaped output for function, skills, seniority (already an ordered scale) so a profile can be matched against it later.
- Reserve nullable `occupation_code` (ISCO) and `skill_codes` (ESCO); do not make the local model map to codes yet.
- Sector stays at company level (ISIC) and is inherited by jobs. Do not start populating job-level sector.
- Keep `posting_quality` and per-field provenance so fit scores can be weighted by how trustworthy the extraction was.

## 8. Live acceptance checks for Journey 1

Each is run on a clickable instance and judged by what is visible.

1. **Happy path, new company:** paste a real posting URL → stub appears instantly → fields fill in → company created → sector/size filled or honestly flagged/exhausted.
2. **Known company by domain:** paste a second job from an existing company → auto-linked, no new company, zero enrichment network calls.
3. **ATS tenant:** paste a Greenhouse/Lever/Personio-style URL for a known company → linked via tenant.
4. **Hard duplicate:** paste the same URL again (with a tracking param added) → warning with side-by-side and "Open existing / Add anyway".
5. **Soft duplicate:** same role via a different URL → non-blocking "possible duplicate" with reason.
6. **Fetch failure:** paste a login-walled URL → job still created, visible `fetch_failed`, paste-text option works and resumes extraction.
7. **Thin posting:** paste a marketing-style careers page → `posting_quality: thin` shown; no invented employment_type/seniority.
8. **Fuzzy company name:** posting for "Acme GmbH" with "Acme" on file → asks, does not auto-link.
9. **Staffing posting:** employer in text differs from tenant owner → review flag, not auto-linked.
10. **Slow LLM:** job is usable and triageable while extraction is still pending; per-field pending/done is visible.
11. **Human wins:** edit a field while extraction is running → the edit survives.

## 9. Open decisions (need the owner's call; do not guess)

1. Where does the "needs your input" queue live: inline on the job/company card, as its own page, or both?
2. Hosted version: are manual edits per-user overlays, or edits to the shared record? (Affects provenance design but not Journey 1.)
3. Initial list of ATS providers to recognise (suggest: Greenhouse, Lever, Personio, Workday, SmartRecruiters, Ashby, Recruitee).
4. Extraction for discovered jobs: eager or lazy (Journey 2).
5. Should a manually pasted company-correction ("this isn't Acme GmbH, it's Acme Inc.") teach the identifier table, so the same fuzzy case never asks twice?
