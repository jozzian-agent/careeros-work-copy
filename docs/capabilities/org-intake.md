---
type: Convention
title: Organisation intake
description: Contract for the capability that resolves a loose organisation reference to a known, classified record.
timestamp: 2026-10-11
status: approved
---

# Organisation intake

## Purpose

Given a loose reference to an organisation - a posting URL, a free-text
employer name, or both - resolve it to one known record, reusing an
existing one whenever the evidence supports it and creating a fresh one
when it does not, then classify that record by standard industry section
and EU employee-count size class. Every step prefers the cheapest signal
that can answer confidently over an expensive or fuzzy one, and refuses
to guess past what its own confidence rules allow: anything short of
confident is reported as an open question for the caller, never resolved
silently.

## Behavior

1. Loose input is never rejected. A URL with no recognizable ATS, no
   matching domain, or an employer name with nothing on file still
   produces a definite outcome (pending / linked / needs-review / a
   fresh record) and never raises. *Reason:* every job needs a usable
   outcome at every call, including the no-signal-yet case at stub
   creation. File: `careeros/company_resolve.py`
   `resolve_rungs_1_2` (local-only lookup, returns `None` cleanly on a
   miss) and `resolve_and_link` (always returns a result dict).

2. Identity is tracked only through four identifier types - domain,
   ats_tenant, wikidata, name_variant (`vault.IDENTIFIER_TYPES`) -
   matched by exact `(type, value)`. A persisted identifier always wins
   over a fresh name guess. *Reason:* once a link is established once,
   it must not be re-derived, and possibly re-litigated, on every later
   call. File: `careeros/vault.py` `IDENTIFIER_TYPES`;
   `careeros/company_resolve.py` `find_by_identifier`, `add_identifier`,
   and `resolve_and_link`'s `existing=` precedence.
   *Caveat:* `wikidata` is a legal identifier type but no code path
   today ever writes one - a contract promise, not current behavior.

3. The ladder climbs cheap/local to expensive/name-based: rungs 1–2 are
   pure local identifier lookups keyed by ATS tenant or domain, no
   network I/O; rungs 3–5 add name matching (exact, then fuzzy) and a
   tenant-vs-employer cross-check once posting text is available.
   *Reason:* a free, structural match should never wait on a fuzzy
   name comparison. File: `careeros/company_resolve.py`
   `resolve_rungs_1_2` and `resolve_rungs_3_5`.

4. A name match only ever links confidently on an exact
   (case/punctuation-insensitive) match against a record's name or any
   of its name_variant identifiers; anything short of exact is reported
   as a scored fuzzy candidate, never auto-linked. *Reason:* a fuzzy
   score is evidence for a human to weigh, not grounds to link
   automatically. File: `careeros/company_resolve.py`
   `find_by_exact_name`, `find_all_by_exact_name`, `fuzzy_candidates`.

5. More than one record carrying the identical exact name is itself an
   ambiguity, never a first-wins pick. *Reason:* silently picking the
   first of two identically-named records would pick wrong half the
   time with no evidence either way. File:
   `careeros/company_resolve.py` `resolve_rungs_3_5`'s
   `ambiguous_exact` branch.

6. A unique ATS-tenant link must still agree with the posting's own
   employer text (exactly or fuzzily) before it counts as confirmed;
   disagreement with no better candidate elsewhere is reported as
   `employer_differs_from_tenant`, disagreement that matches a
   different record is reported as `shared_tenant`. *Reason:* one ATS
   tenant can host more than one employer (e.g. a staffing agency), so
   tenant membership alone is never sufficient evidence. File:
   `careeros/company_resolve.py` `resolve_rungs_3_5`'s
   `tenant_rooted` branch.

7. Classification runs against one fixed external taxonomy - UN ISIC
   Rev.4, 21 sections - by keyword matching on free-text industry
   strings; a string whose keywords match more than one section is
   refused outright rather than guessed. *Reason:* standards over ad
   hoc labels, and a matcher that cannot tell which of two sections
   applies should say so, not pick one. File: `careeros/sectors.py`
   `all_matched_sections`, `match_sectors`; `careeros/data/isic_sections.yaml`.

8. Size is classified on one scale: EU Recommendation 2003/361/EC
   employee-count thresholds (micro ≤10, small ≤50, medium ≤250,
   large >250), with a parallel numeric range bucket derived from the
   same raw count so the two fields can never desync. *Reason:* two
   independently-derived size fields could silently disagree; deriving
   both from one count at once rules that out by construction. File:
   `careeros/sectors.py` `SIZE_CLASS_THRESHOLDS`, `derive_size`.

9. Sector/size enrichment runs a cascade from cheap/structured to
   expensive/fuzzy: a zero-network promotion from already-aggregated
   data first, then the organisation's own website (JSON-LD), then
   Wikidata, then OSM (sector only), with an LLM world-knowledge
   fallback gated behind an explicit flag and only ever tried once
   every structured signal came back empty. *Reason:* the LLM signal
   is neither free nor independently verifiable, so it is a last
   resort, gated in code rather than by prompt wording alone. File:
   `careeros/company_lookup.py` `SECTOR_SIGNALS`/`SIZE_SIGNALS`,
   `sectors_cascade`, `external_sectors`.

10. A field fills only on one confident result; two independent
    confident results that cannot be shown to describe genuinely
    distinct activities refuse to fill and raise a review flag instead
    of picking one. *Reason:* no source has priority over another, so
    an unresolved conflict must surface, not silently resolve. File:
    `careeros/company_lookup.py` `external_sectors`,
    `promote_aggregated_sectors`.

11. Size never overwrites an already-populated field, and a freshly
    fetched value that contradicts one already on file fills nothing
    and raises a review flag instead of guessing which is right.
    *Reason:* a half-filled, internally inconsistent pair must never
    be written silently. File: `careeros/sectors.py`
    `fill_size_updates`; `careeros/company_lookup.py` `size_cascade`.

12. Every external signal reports its own outcome - matched, ambiguous,
    rate-limited, fetch-error, empty, or not-attempted - so a sweep's
    silence is never confused with a fetch that quietly failed.
    *Reason:* a prior defect saw a backfill swallow the difference
    between "no usable data" and "Wikidata rate-limited us". File:
    `careeros/company_lookup.py` `BackfillAccounting`,
    `_STATUS_OUTCOMES`, `_record_outcome`.

13. A re-run never repeats work a field already has. The identity
    ladder's own re-run replays from stored fields with no network
    call at all, short-circuiting entirely once an owner has hand-set
    the link. The enrichment cascades skip any field that is already
    populated or owner-provenanced. *Reason:* re-running must be safe
    to call often and cheap when there is nothing left to do. File:
    `careeros/company_resolve.py` `rerun`; `careeros/company_lookup.py`
    `size_cascade` and `sectors_cascade`'s early-populated-field
    returns.

14. Every identifier and every record name carries its own provenance
    (`scrape` vs `user`; `name_source` `auto` vs `owner`), and an
    owner-set link decision is never silently overwritten by a later
    re-run. *Reason:* human edits always win - a re-run must not
    undo an owner's correction just because it disagrees. File:
    `careeros/company_resolve.py` `add_identifier`, `apply_review`,
    `rerun`.

15. Per-field enrichment state is a lifecycle the contract promises in
    full (`never-tried` / `filled` / `flagged` / `exhausted`) but the
    code only partly builds today. *Caveat:* `company_lookup.py`'s own
    cascades return a bare `(result, flag)` pair with no state label
    at all; `filled`/`flagged`/`exhausted` are assembled only once, in
    the product's `server.py`, and nothing anywhere writes a
    `never-tried` label yet. File: `careeros/company_lookup.py`
    `sectors_cascade`, `size_cascade`; `careeros/server.py`
    `run_company_cascade`'s per-field state block.

## Not included

- **Storage.** The capability never reads or writes a file itself; a
  store object (list/load/save for its own records) is passed in. The
  product supplies the implementation (today, `careeros/vault.py`).
- **Fetching and parsing posting content.** The capability never
  fetches a job posting page or parses the posting itself; it is
  always handed an already-extracted employer-name string. The
  product owns the posting fetch/parse pipeline (today,
  `careeros/intake.py`'s `Posting` parser and `_extract`/
  `ingest_posting`), and the full set of extraction/summarization
  concerns around it (`careeros/ingest.py`).
- **The posting identifier.** ATS detection returns provider and
  tenant only. The product parses any posting-id out of the URL
  itself.
- **The model client.** An LLM client and model name are passed in by
  the product for the world-knowledge fallback signal; the capability
  never constructs one (today, `careeros/llm_client.py`).
- **Clock, deadline, and failure logging.** Every network call the
  capability makes (company-website fetch, Wikidata retry/backoff, the
  LLM signal's timeout) takes a deadline/sleep and a `warn(error)`
  callback as parameters, rather than importing the product's own
  clock or logging helper.
- **Job records, deduplication, watching, re-summarization.** None of
  this is in scope (`careeros/dedupe.py`, `careeros/watcher.py`,
  `careeros/enrich.py`). The capability reads and writes only
  organisation-shaped records; any evidence that today comes from
  scanning job records directly stays product-supplied as a parameter.
  (`careeros/company_resolve.py`'s tenant-sharing check currently
  scans `vault.list_jobs` itself for this; that job scan stays with
  the product, which must pass the capability the evidence it needs
  instead.)
- **Function/skill taxonomy data** (ESCO) and any other job-shaped
  reference data: unrelated to organisation identity/classification,
  stays product.

## Interface

Entry points as they will look once storage, the model client, and the
clock/warn callback are parameters rather than imports. Plain data in,
plain data out - no product-specific names.

```
resolve_identity(store, *, url, employer_name=None, fallback_name=None,
                 existing=None, legacy_hint=None) -> dict

# stub time, before any fetch:
resolve_identity(store, url="https://boards.greenhouse.io/northwind/jobs/9981")
=> {"record_id": None, "link_state": "pending", "link_reason": None, "review": None}

# after fetch, exact name match on file:
resolve_identity(store,
                 url="https://jobs.lever.co/northwind/55",
                 employer_name="Northwind Logistics AG")
=> {"record_id": "ORG-104", "link_state": "linked",
    "link_reason": "name_exact", "review": None}

# after fetch, only a fuzzy match on file:
resolve_identity(store,
                 url="https://northwind-logistics.example/careers/55",
                 employer_name="Nordwind Logistik AG")
=> {"record_id": None, "link_state": "needs_review", "link_reason": "fuzzy_name",
    "review": {"token": "a1b2c3", "candidates": [
        {"record_id": "ORG-104", "name": "Northwind Logistics AG",
         "score": 0.78, "basis": "Northwind Logistics AG"}]}}
```

```
classify_sector(record, *, fetch=None, warn=None, deadline=None,
                collector=None) -> (codes_or_None, flag_or_None)

classify_sector({"name": "Helvetia Robotics GmbH",
                 "website": "https://helvetia-robotics.example", "sectors": []})
=> (["C"], None)
```

```
classify_size(record, *, fetch=None, warn=None, deadline=None,
              collector=None) -> (updates_or_None, flag_or_None)

classify_size({"name": "Helvetia Robotics GmbH",
               "size_range": None, "size_class": None})
=> ({"size_range": "11-50", "size_class": "small"}, None)
```

```
detect_ats(url) -> {"provider": str, "tenant": str} | None

detect_ats("https://boards.greenhouse.io/northwind/jobs/9981")
=> {"provider": "greenhouse", "tenant": "northwind"}
```

```
normalize_url(url) -> str

normalize_url("HTTPS://Example.com/jobs/?utm_source=x&b=1&a=2")
=> "https://example.com/jobs?a=2&b=1"
```

## States

**Link state** (per job the product resolves against a record):

- `pending` - no identity signal at all yet (no identifier match, no
  employer name evidenced). Moves to `linked`, `needs_review`, or a
  freshly created record once an employer name or a stronger
  identifier arrives.
- `linked` - confidently resolved to one record, via an identifier
  match, an exact name match, or a confirmed tenant/employer
  cross-check. Stays `linked` on a later re-run unless new evidence
  contradicts it, or an owner changes it by hand.
- `needs_review` - ambiguous, with a reason: `fuzzy_name` (best match
  below exact), `ambiguous_exact` (two or more records share the exact
  name), `shared_tenant` (an ATS tenant has evidenced more than one
  employer), `employer_differs_from_tenant` (the posting's employer
  disagrees with the tenant's own name, no better candidate exists).
  Carries a one-time review token so a stale concurrent resolution is
  rejected rather than silently first-winning. Moves to `linked` only
  through an explicit resolution or a later rung-5 cross-check that
  reconfirms the tenant's own name.
- new record - no local or name match at all, but a usable name signal
  exists. Immediately reported as `linked` (reason `new_company`) once
  a fresh record is created.

**Identifier** (on a record): typed `domain` / `ats_tenant` /
`wikidata` / `name_variant` values, additive-only, deduped on
`(type, value)`, each carrying its own provenance (`scrape` or
`user`). Never shrinks or rewrites except through explicit owner
action.

**Per-field enrichment state** (sector, size) - contract promise:

- `never-tried` - not yet attempted (promised, not yet built anywhere).
- `filled` - a new value was written, or every relevant sub-field was
  already populated.
- `flagged` - a signal produced a result but confidence/consistency
  rules refused to fill it (ambiguous, conflicting, or inconsistent
  with an existing value).
- `exhausted` - every signal ran; nothing usable came back and nothing
  to flag either.

A field's state only moves forward through an explicit cascade run; a
`flagged` state clears automatically the next run that resolves it.

## Consumers

- CareerOS (careeros-dashboard) - pinned at: to be set at 2.4.

## Open questions

Contract approved by the owner 2026-10-11. The open questions below
were answered at approval; only the two marked remain genuinely open.

- JSON-LD collector: answered - the capability gets its own minimal
  JSON-LD-only block scanner (extracted from the product's posting
  parser); it does not import `intake.Posting`.
- EU size labels: answered - the capability owns the size-class
  vocabulary as its own constant (one canonical scale, per the owner
  decision that EU classes win); the product does not pass labels in.
- Deadline: answered - the deadline parameter is a plain number of
  seconds; the internal background-thread timeout pattern moves with
  the capability.
- Tenant-sharing evidence: answered - the product passes a
  precomputed list of employer names already seen under that
  `(provider, tenant)` pair; the capability never scans job records.
- `wikidata` identifier type: answered - the type stays; the
  capability eventually populates it from the entity id its own
  Wikidata lookup already resolves.
- Open: exact package/module names for the moved code inside
  `capa-repo` (owner creates the repo at 2.4).
- Open: how the store adapter interface is shaped at extraction
  (2.3) - list/load/save minimum is agreed, the exact signatures are
  settled there.
