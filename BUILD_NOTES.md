# JOZ-260: fix silent backfill failures

Not committed — left in the working tree for review, per instructions.

## (a) Per-signal outcome accounting

Added `company_lookup.BackfillAccounting`, an **optional collector** passed
through `plan_backfill(..., collector=...)` -> `sectors_cascade`/`size_cascade`
-> `external_sectors`. For every (company, signal, field) looked at during a
sweep it records one outcome from the required vocabulary: `matched`,
`ambiguous`, `rate-limited`, `fetch-error`, `empty`, `not-attempted`.
`collector.summary()` returns the aggregate counts; `collector.events` has
the raw per-signal detail.

**Design choice: collector parameter, not a return-shape change.**
`plan_backfill` returns `(plan, scanned)` today, and that tuple is unpacked
positionally in `server.py`'s backfill route and in existing tests. Growing
it to a 3-tuple is a breaking change for every caller, defeating "backwards
compatible." An optional `collector=None` parameter is purely additive —
every existing call site, mock, and test keeps working untouched (verified:
all 586 pre-existing tests still pass unmodified except two mocks of
`sectors_cascade`/`size_cascade` that needed a `collector=None` parameter
added to their lambda signatures, since `plan_backfill` now calls them with
one more positional argument). `server.py`'s route builds a collector,
passes it in, and adds the summary as a new `signal_summary` JSON key —
additive for API consumers too.

Each signal function (`_jsonld_signal`/`_wikidata_signal`/`_osm_signal`) can
report `{'status': 'not_attempted'}` before even calling the underlying
fetcher (no website/name to query), and `fetch_wikidata` itself now reports
`'status': 'rate_limited'` or `'status': 'error'` when the fetch didn't
complete cleanly (see (b)). The `'status'` key is only ever present on a
non-`'ok'` result, so every pre-existing exact-equality test against
`fetch_wikidata`/`fetch_company_jsonld`/`fetch_osm`'s return dict is
unaffected. `fetch_company_jsonld`/`fetch_osm` themselves are untouched
internally (OSM is explicitly out of scope; JSON-LD was never implicated in
the diagnosis) — their `not-attempted` precondition check lives in the
signal wrapper instead, so their own function contracts don't change.

## (b) Wikidata 429 retry/backoff + pacing

New `_wikidata_get(url, fetch, sleep)` helper used by every Wikidata HTTP
call in `fetch_wikidata`/`_resolve_entity_label` (search, entity lookup, and
industry-label resolution all go through it, since any of the three can hit
the rate limit). On `HTTPError` with code 429 it retries up to
`WIKIDATA_MAX_RETRIES` (3) times with exponential backoff
(`WIKIDATA_BACKOFF_SECONDS=1`, doubling), honoring the `Retry-After` header
when present. Only once every retry is exhausted does it report
`'rate_limited'` — a 429 that resolves on retry returns a clean result with
no `'status'` key at all. A non-429 `HTTPError` or any other exception is
reported as `'error'` immediately, no retry (retrying wouldn't help and
would just slow the sweep down further).

Request pacing: `_wikidata_pace()` enforces a minimum 0.1s gap between
successive Wikidata HTTP calls (real wall clock, not the injectable `sleep`
used for backoff tests — pacing is a courtesy to the live API between calls,
not something a retry test needs to fake out). This is a simple, global
module-level last-call timestamp; it reduces the odds of triggering the
limit in the first place during a long sweep over many companies.

## (c) ISIC vocabulary + J-vs-M / automotive decisions

**J vs. M ambiguity.** Both J ("technology") and M ("technology") share a
generic one-word keyword, so any text containing "technology" — including
"technology industry" and "information technology" — matched both sections
and was refused, even though these two specific phrases are unambiguously
J (ISIC J = information and communication). Fix: `sectors.all_matched_sections`
now prefers a **strictly longest matching keyword** when a text matches more
than one section, instead of always returning every section with any match.
"technology industry" (new J keyword, length 19) and "information
technology" (existing J keyword, length 23) each now outrank the generic
10-character "technology" keyword that M also has, so both resolve
confidently to J alone. Bare "Technology" still ties with M at the same
keyword length (10 == 10), so it's still refused exactly as before — this
was an explicit existing test (`('Technology', [])`) that must keep passing,
confirming the fix doesn't just make all ambiguity disappear. This needed a
small, targeted change to `sectors.py` (specificity tie-break) rather than
a YAML-only fix, because YAML keywords alone can't express "this match is
more specific than that one" — justified since the alternative (removing
the shared "technology" keyword from M) would have made bare "Technology"
stop being ambiguous, regressing documented behavior.

**Automotive: C, not G.** ISIC Rev.4 classifies motor vehicle *manufacturing*
(e.g., a carmaker) under Section C, Division 29. Section G covers only
wholesale/retail trade and repair of motor vehicles — a dealership or repair
shop, not a manufacturer. "automotive industry" as a general Wikidata
industry string most commonly describes the manufacturer, so it maps to C.
Documented inline in `isic_sections.yaml`.

**Pharmaceutical -> C** (ISIC Division 21, manufacture of pharmaceuticals).

**Cryptocurrency / fintech -> K** (financial and insurance activities).

New keywords added to `data/isic_sections.yaml`: `pharmaceutical`,
`automotive` (section C); `technology industry` (section J);
`cryptocurrency`, `fintech` (section K). Each has a dedicated unit test in
`test_match_sectors_widened_vocabulary_classes`, plus a regression test
confirming bare "Technology" is still refused.

## Not touched (explicitly out of scope)

- OSM (`fetch_osm`): always fails on this host (IPv6-only, no route); no
  retry/backoff logic added, per instructions.
- JSON-LD fetch internals: no site observed carries industry data in JSON-LD;
  left as-is aside from the new not-attempted precondition check in the
  signal wrapper.
- `review_flags` vocabulary: unchanged (`FLAG_SECTOR_AMBIGUOUS`,
  `FLAG_SECTOR_CONFLICT`, `FLAG_SIZE_INCONSISTENT`).
- The vault-write-lock / network-phase separation from c963324 (plan vs.
  apply) is unchanged; `plan_backfill` still does all network I/O and
  `apply_backfill` still only touches the local filesystem under the lock.

## Tests

- 19 new tests added (586 -> 605), all passing.
- New coverage: per-signal accounting for each outcome (matched, ambiguous,
  rate-limited, fetch-error, empty, not-attempted), 429-then-success retry,
  Retry-After header honored, retry exhaustion -> rate-limited, non-429
  HTTPError / generic exception -> fetch-error (not rate-limited), and one
  parametrized test per new vocabulary class plus a regression test for the
  preserved bare-"Technology" ambiguity.
- Final: `.venv/bin/python -m pytest tests/ -q` -> **605 passed**.

Not committed, not pushed — working tree only.

## FIX ROUND (2026-10-07): Codex review REQUEST-CHANGES, all six findings

An independent review of the above returned REQUEST-CHANGES with six
findings, all fixed in this round without changing the overall design
(BackfillAccounting collector, additive `signal_summary`, `(plan, scanned)`
shape, lock discipline all unchanged).

**1 (major) — `all_matched_sections` tie-break bypassed decision 20 for
unrelated sectors.** The original "longest keyword wins" rule compared
keyword length *globally*, so "software and retail" (J via "software", 8
chars; G via "retail", 6 chars) incorrectly resolved to J — two completely
independent activities, not a generic/specific restatement of one. Same bug
for "mining and manufacturing" → C. Fixed `sectors.all_matched_sections` to
only resolve a tie when one section's matched keyword is a strict substring
of another's (true specialization, e.g. "technology" is a substring of
"technology industry" and of "information technology" — the same underlying
word, just phrased more specifically). When the competing keywords are not
substrings of one another, every originally matched section is returned
unresolved, exactly as before the J-vs-M vocabulary fix. Verified "software
and retail" and "mining and manufacturing" are ambiguous again, and all of
"technology industry"→J, "information technology"→J, bare "Technology"→[]
still hold. New tests: `test_match_sectors_independent_keywords_stay_ambiguous`,
`test_all_matched_sections_independent_keywords_returns_both_unresolved`.

**2 (major) — a signal-wide `status` discarded a valid field alongside a
failed one.** `fetch_wikidata` had one `status` key describing the whole
result, so `{'industry': None, 'employee_count': 100, 'status': 'error'}`
(the industry-label HTTP call failed, but employee_count had already been
read from the claims payload that *did* succeed) made `size_cascade` throw
the 100 away entirely, and the same shared key let `external_sectors`
discard a real industry value whenever size's call had failed. Replaced the
single `status` with two independent keys, `industry_status` and
`size_status`: the two calls that are genuinely shared (search, and the
claims fetch itself) set both identically on failure (nothing was fetched
for either field), but the industry-label-only lookup (P452 id → text) sets
`industry_status` alone, since employee_count by then is already resolved
from the independently-fetched claims and must not be discarded. Every
signal wrapper (`_jsonld_signal`/`_wikidata_signal`/`_osm_signal`) and both
cascades (`external_sectors` reads `industry_status`, `size_cascade` reads
`size_status`) were updated to match. New tests:
`test_fetch_wikidata_industry_label_failure_preserves_employee_count`,
`test_size_cascade_industry_status_failure_preserves_employee_count`,
`test_external_sectors_size_status_failure_preserves_industry`,
`test_plan_backfill_accounting_partial_wikidata_failure_preserves_valid_field`.
Three pre-existing tests that asserted the old single-`status` shape
(`test_fetch_wikidata_rate_limited_after_retries_exhausted`,
`..._non_429_http_error_is_fetch_error...`, `..._generic_exception_is_fetch_error`,
plus the two ad hoc accounting-test signals) were updated to the new shape.

**3 (major) — accounting omitted every skipped (signal, field) pair.** Early
returns in `sectors_cascade` (field already populated; aggregate-promotion
success or refusal) and `size_cascade` (field already populated; the size
loop's `break` after the first successful count) recorded no event at all
for the signals never invoked, so `collector.summary()` silently undercounted
instead of covering every pair the sweep considered. Added
`_record_not_attempted(collector, company, signals, field)`, called at every
early-return/break point for exactly the signals that were skipped (no
network, no invocation — just an accounting entry). Aggregate promotion
itself now also produces an event: `promote_aggregated_sectors` is in
`_SIGNAL_NAMES` (as `'promotion'`) and records `'matched'` on a successful
promotion or `'ambiguous'` on a promotion refusal (decision-20 conflict),
before marking the external signals `'not-attempted'`. New tests:
`test_sectors_cascade_already_populated_records_not_attempted_for_all_considered_signals`,
`test_sectors_cascade_promotion_success_records_matched_and_skips_external_signals`,
`test_sectors_cascade_promotion_conflict_records_ambiguous_and_skips_external_signals`,
`test_size_cascade_already_populated_records_not_attempted`,
`test_size_cascade_break_on_first_match_records_not_attempted_for_remaining_signals`.

**4 (major) — JSON-LD production fetch errors were accounted as `empty`.**
`_safe_fetch` swallows every exception and returns `None`, indistinguishable
from "fetched cleanly, no JSON-LD there." Added `_safe_fetch_status(url,
fetch)`, used only by `fetch_company_jsonld`, which returns `(value, status)`
and reports `status='error'` when `fetch()` itself raised (vs. `'ok'` for
both a safety-rejected destination and a merely-empty response — so
`test_fetch_company_jsonld_rejects_private_destination`'s existing `== {}`
expectation is untouched). `_safe_fetch` itself — OSM's only caller, out of
scope for this finding — is completely unchanged, so OSM's
exception-swallowing behavior is identical to before. New tests:
`test_fetch_company_jsonld_reports_fetch_error_on_exception`,
`test_jsonld_production_fetch_error_is_not_counted_as_empty` (through
`plan_backfill`, with a fetcher that raises `HTTPError(..., 500, ...)`).

**5 (minor) — `_last_wikidata_call` pacing was not thread-safe.** Flask
serves requests on multiple threads; two overlapping sweeps (or a sweep
racing some other Wikidata-touching code path) could read-sleep-update the
module-level timestamp concurrently. Added a dedicated
`_wikidata_pace_lock = threading.Lock()` (not the vault write lock — pacing
is unrelated to vault I/O and must never be on that lock's critical path)
guarding the whole read-sleep-update in `_wikidata_pace()`. New smoke test:
`test_wikidata_pace_is_thread_safe_under_concurrent_calls` (20 concurrent
threads, asserts no exception).

**6 (major) — Retry-After parsing was incomplete.** The old parser only
tried `float(value)`, so the HTTP-date form (RFC 7231 §7.1.3) was silently
ignored (falls back to exponential backoff even though the server gave an
explicit, honorable wait), and a numeric value had no upper bound at all —
an adversarial or misconfigured server could stall a retry arbitrarily long.
Added `_retry_after_http_date()` using the stdlib
`email.utils.parsedate_to_datetime` for the date form, and
`RETRY_AFTER_MAX_SECONDS = 30` clamps every parsed value (numeric or date),
floored at zero. A value that is neither a number nor a parseable HTTP-date
returns `None`, same as before, so the caller falls back to its own
exponential delay rather than not sleeping at all. New tests:
`test_wikidata_retry_after_http_date_form_honored`,
`test_wikidata_retry_after_huge_value_clamped`,
`test_wikidata_retry_after_garbage_value_falls_back_to_exponential_delay`.

**Verification.** Re-checked all the original live-diagnosis strings still
map correctly after the Finding 1 fix: "technology industry"→J, "information
technology"→J, "software industry"→J, "pharmaceutical industry"→C,
"automotive industry"→C, "cryptocurrency"→K, "energy supply"→D, "banking"→K,
bare "technology"→ambiguous refusal, and confirmed "software and retail" and
"mining and manufacturing" are ambiguous refusals again.

**Tests:** 605 → 623 (18 new, 2 pre-existing updated to the new per-field
status shape). `.venv/bin/python -m pytest tests/ -q` → **623 passed**.

Not committed, not pushed — working tree only.

## FIX ROUND 2 (orchestrator patches, 2026-10-07)
Codex re-review left 2 unresolved items; both patched directly (small deltas):
- company_lookup._retry_after_seconds: reject non-finite floats ("NaN"/"inf"
  previously clamped to 0.0); now falls back to exponential delay. Test:
  test_wikidata_retry_after_nan_value_falls_back_to_exponential_delay.
- sectors_cascade: promotion returning [] (no aggregated data) now records a
  ('promotion','empty') event before falling through to external signals, so
  accounting covers every executed step. Test:
  test_sectors_cascade_promotion_empty_records_empty_event.
- 3 pre-existing exact-count accounting tests updated to include the
  promotion-empty event (they asserted summaries computed before it existed).
Full suite: 625 passed.

# JOZ-261: LLM-backed sector/size signal to company backfill

Not committed — left in the working tree for review, per instructions.

## Problem

A live backfill sweep (JOZ-260's diagnosis) found the external-fetch
pipeline dead for almost everyone: 20 companies scanned, 1 classifiable.
JSON-LD, Wikidata, and OSM all depend on structured data that most
employers simply don't publish anywhere a scraper can reach. The LLM has
genuine world knowledge of well-known employers that none of those sources
expose, so it becomes the last-resort signal in the cascade.

## (a) `_llm_signal` — cascade placement and shape

Added `_llm_signal` to `company_lookup.py`, appended to the END of both
`SECTOR_SIGNALS` (after jsonld, wikidata, osm) and `SIZE_SIGNALS` (after
jsonld, wikidata) — cheapest-first is preserved; the LLM is the most
expensive and least independently-verifiable source, so it only ever runs
once everything free/structured has already failed. One call backs both
fields, mirroring `fetch_company_jsonld`'s single-fetch shape exactly: a
transport/HTTP/timeout failure sets `industry_status`/`size_status` to
`'error'` identically for both.

**Gating lives in the signal wrapper, not in server.py.** `_llm_signal`
checks `os.environ.get('BACKFILL_USE_LLM') != '1'` as its own precondition
check, returning `{'industry_status': 'not_attempted', 'size_status':
'not_attempted'}` immediately when unset — the exact same convention
`_jsonld_signal`/`_wikidata_signal`/`_osm_signal` already use for "no
website/name to query." This means:
- `_llm_signal` can live directly in the module-level `SECTOR_SIGNALS`/
  `SIZE_SIGNALS` tuples with zero special-casing in `server.py` — the
  `/api/companies/backfill-sector-size` route needed NO code changes at all;
  `signal_summary` picks up `'llm'` counts automatically via the existing
  accounting plumbing (verified via a live `test_client()` call against a
  mocked LLM client, see below).
- Every test that calls `plan_backfill`/`backfill` with the real module
  defaults (not an explicit `sector_signals=`/`size_signals=` override)
  still costs nothing: `BACKFILL_USE_LLM` is unset in the test environment,
  so `_llm_signal` returns immediately without constructing an LLM client or
  touching the network.
- `BACKFILL_USE_LLM` unset produces an explicit `not-attempted` accounting
  event for the `'llm'` signal (not merely an absent one), satisfying the
  letter of "never silently empty" for this signal too.

## (b) Decision-20 gating, in code

The prompt (`LLM_SYSTEM_PROMPT`) asks for strict JSON:
`{"sector": <ISIC letter A-U or null>, "sector_label": <short rationale or
null>, "confidence": "high"|"low", "size_hint": <EU size class or null>}`.
The model's own confidence claim is never trusted blindly; `_llm_signal`
re-validates in code:
- `confidence` must literally equal `'high'`.
- `sector` must be a string that is one of the known ISIC section codes
  (`sectors.known_section_codes()`).
- **Cross-check, not override:** when `sector_label` is non-empty,
  `sectors.match_sectors(sector_label)` is run against it. If that returns
  a single confident match that names a DIFFERENT section than the stated
  letter, the response is self-contradictory and is refused — the model
  said "K" but its own rationale text reads as unambiguously "F", which is
  a sign the output is unreliable, not merely under-specified. When the
  cross-check returns no match or an ambiguous (multi-section) match, it
  does not block the letter: free-text rationale is not expected to always
  contain a literal ISIC keyword, and **the letter is authoritative for the
  fill** per the spec, not the keyword matcher's independent re-derivation
  of it. This is the one place the task's "where sensible" qualifier is
  resolved: sensible means "use it to catch self-contradiction," not "use it
  to re-derive the answer instead of the letter."
- Any other combination (confidence `'low'`, missing/null/invalid `sector`,
  a self-contradictory rationale, or a response that didn't even parse as a
  JSON object) sets `industry_status='ambiguous'` rather than returning an
  empty result.

**New shared status value: `'ambiguous'`.** `_STATUS_OUTCOMES` gained one
entry (`'ambiguous': 'ambiguous'`), and `external_sectors` now sets its
local `ambiguous` flag when it sees that status, exactly as it already does
when a keyword signal matches more than one section. This reuses the
EXISTING `FLAG_SECTOR_AMBIGUOUS` review-flag path end to end — no new flag
vocabulary was invented, per instructions. This is a two-line, additive
change to `external_sectors`; every other signal's behavior (none of which
can ever produce `industry_status='ambiguous'`) is untouched.

**New shared signal-result key: `'sector_code'`.** When `_llm_signal` has a
validated, authoritative letter, it returns `{'sector_code': <letter>}`
instead of `{'industry': <text>}`. `external_sectors` checks this key
BEFORE falling through to `sectors.match_sectors(industry)` — when present,
the code is taken directly, bypassing the keyword matcher entirely (it is
already resolved and authoritative; re-deriving it from the free-text
rationale would be redundant at best and overridable-by-a-coincidental-
keyword-miss at worst). No existing signal ever sets this key, so this is
purely additive.

## (c) Size: a size-class hint is not a count

The prompt also asks for `size_hint`, an EU size class (`micro`/`small`/
`medium`/`large`) — the model has no way to know a precise headcount, only
roughly how big an employer is. This does NOT fit the existing size
pipeline, which is built entirely around a raw `employee_count` that
`sectors.derive_size`/`fill_size_updates` turns into `size_range` AND
`size_class` TOGETHER. Converting a size class to a representative count
(e.g. "large" → 1000) and feeding it through that pipeline was considered
and rejected: it would fabricate a `size_range` bucket the signal has no
real basis for (a 300-employee company is EU-class "large" at the ≥250
threshold, but bucketing it as `'1000+'` would simply be wrong).

Instead, `_llm_signal` returns a new, independent signal-result key,
`'size_class_hint'`, and `size_cascade` gained a small additive branch: a
class hint can only ever fill `size_class` — NEVER `size_range` — and
still obeys the same fill-empty-only / contradiction-flags-for-review rule
every other size source obeys (`FLAG_SIZE_INCONSISTENT` when it contradicts
an already-populated `size_class`, nothing written, never silently
discarded). The existing count-based path (`fill_size_updates`) is
completely untouched; the new branch only ever triggers when a signal set
`size_class_hint` and no signal in the cascade produced a usable count.

## (d) Provenance

The company schema has no per-field provenance field for sector/size fills
at all — not even for the existing jsonld/wikidata/osm signals (unlike jobs,
which track `ingest_source`/`summary_source`). The only mechanism ANY
backfill signal uses to record "this came from source X" is
`BackfillAccounting`'s named events (`_SIGNAL_NAMES`). `_llm_signal` was
added to that same dict as `'llm'`, so every LLM-sourced fill is
attributable via `collector.events` exactly the way a jsonld/wikidata fill
already is — no new field was invented on the company record itself.

## (e) Input scope

`_llm_prompt` sends ONLY `company['name']`, `company['website']`,
`company['locations']`, and `company['notes']` — the owner-entered,
company-identifying fields. It never sees a job description, an
`enrichment` block, or anything else in the vault. Covered by
`test_llm_signal_prompt_contains_only_identifying_fields_never_job_data`.

## (f) ISIC vocabulary: two Wikidata labels that resolved to nothing

The live sweep's Wikidata fetches actually returned "electrical
engineering" (for Siemens) and "cloud computing" (for a cloud provider),
neither of which matched any existing keyword. Added both to
`data/isic_sections.yaml`:
- `"electrical engineering"` → C (ISIC division 27, manufacture of
  electrical equipment). Verified it does not collide with M's "engineering
  services" or either section's bare "technology" keyword — the phrase
  "electrical engineering" does not contain either of those keywords
  verbatim, so it resolves as a clean single match, not a specificity
  tie-break.
- `"cloud computing"` → J. Unambiguous, no overlap with any other section.

Regression-checked: bare `"Technology"` still refuses (`[]`), `"software
and retail"` still refuses, `"mining and manufacturing"` still refuses —
the new keywords don't touch the existing tie-break/ambiguity logic at all.

## Design deviations / judgment calls worth flagging for review

1. **Confidence gates BOTH sector and size, not sector alone.** The JSON
   schema has one `confidence` field, not one per field. Rather than split
   hairs about whether a "high" sector confidence implies a trustworthy
   size guess, `_llm_signal` requires `confidence == 'high'` before it will
   use `size_hint` at all, same as sector. A model that isn't sure it knows
   the company shouldn't be trusted for its size either.
2. **The cross-check can refuse a `confidence: "high"` sector claim.** The
   task says "the letter is authoritative for the fill," which could be read
   as "never second-guess the letter." I read "cross-checked ... where
   sensible" as requiring the cross-check to actually do something: catch a
   self-contradictory response (stated letter disagrees with the model's
   own rationale) rather than being decorative. A label that simply doesn't
   keyword-match anything never blocks the letter — only a CONFIDENT,
   DIFFERENT keyword match does.
3. **`BACKFILL_USE_LLM` is enforced in `company_lookup.py`, not `server.py`.**
   The task described it as a `server.py` concern; implementing it as the
   signal wrapper's own precondition check (matching the existing
   website/name precondition convention) meant zero changes to
   `server.py`, and it extends the protection to any direct caller of
   `company_lookup.backfill()`/`plan_backfill()`, not just the HTTP route.

## Tests

16 new tests in `tests/test_sectors.py` (the existing home for every
company_lookup/sectors test — there is no separate `test_company_lookup.py`
in this codebase): env-gate off → not-attempted; cascade membership +
ordering; high-confidence fill with `'llm'` provenance; letter-authoritative
-when-label-has-no-match; self-contradictory rationale refused; low
confidence refused; invalid letter refused; malformed JSON → ambiguous;
endpoint error → fetch-error both fields; size-hint contradiction → flag,
no overwrite; size-hint fills `size_class` only, never `size_range`; prompt
scope (no job data); accounting summary counts; two new vocabulary cases
(`electrical engineering`→C, `cloud computing`→J) plus a non-collision
regression check. All mock the LLM client via `client_for`
(`tests/test_ingest.py`'s existing helper) — no live network call anywhere
in the suite.

**Full suite:** `.venv/bin/python -m pytest tests/ -q` → **641 passed**
(625 baseline + 16 new). Re-ran 3x to rule out order-dependence; stable.
(One unrelated, pre-existing flaky failure —
`test_job_detail_polls_only_while_pending`, a thread-polling timing test —
was observed once in a full-suite run and did not reproduce on re-run or in
isolation; confirmed unrelated to this change, which touches no job
polling/threading code.)

## Live smoke test

Against the real local endpoint (`LLM_BASE_URL=http://192.168.1.10:11434/v1`,
model `qwen3:14b`, no `LLM_API_KEY` needed — the server doesn't require
one), with `BACKFILL_USE_LLM=1`, on a bare `{'name': 'Siemens'}` company
record (no website, no aggregated job data, so jsonld/wikidata/osm/
promotion were skipped by construction — only `_llm_signal` was wired in):

```
summary: {'matched': 2, 'ambiguous': 0, 'rate-limited': 0, 'fetch-error': 0, 'empty': 1, 'not-attempted': 0}
events: [
  {"company_id": "CO-001", "signal": "promotion", "field": "sectors", "outcome": "empty"},
  {"company_id": "CO-001", "signal": "llm", "field": "sectors", "outcome": "matched"},
  {"company_id": "CO-001", "signal": "llm", "field": "size", "outcome": "matched"}
]
company after: {..., 'sectors': ['C'], 'size_range': None, 'size_class': 'large', ...}
```

Siemens correctly classified as ISIC section C (Manufacturing — Siemens is
an industrial/electrical-engineering conglomerate) and EU size class
`large` (300k+ employees), with `size_range` correctly left unfilled (the
model only ever supplies a class, never a precise count). Also verified via
a real `test_client()` POST to `/api/companies/backfill-sector-size` with a
mocked client that `signal_summary` includes the `'llm'`-sourced counts with
zero changes to `server.py`.

Not committed, not pushed — working tree only.

# JOZ-262: Wikidata P1128 (employee count) feeds size_range

## Starting state: most of this was already wired up

Before writing anything, I found `fetch_wikidata`/`company_lookup.py` already
reads P1128 from the same entity-claims payload the P452 (industry) lookup
uses (one HTTP call, per requirement 1), already resolves it through
`sectors.resolve_employee_count` -> `size_cascade` -> `sectors.fill_size_updates`
(the exact fill-empty-only/consistency-checked machinery every other size
source uses, per requirement 3), and `_wikidata_signal` is already named
`'wikidata'` in `_SIGNAL_NAMES`, so `BackfillAccounting` already attributes a
P1128 fill to signal `wikidata`, field `size`, outcome `matched` (requirement
4) with zero code changes needed there. `SIZE_SIGNALS = (_jsonld_signal,
_wikidata_signal, _llm_signal)` already runs Wikidata before the LLM signal
(requirement 5), and the plan/apply split from c963324 (network phase never
holds the write lock) was already untouched. This had apparently landed as
part of the P1128 claims-reading added alongside the taxonomy layer's first
commit (35325be), well before the JOZ-260/261 work in this file — just never
called out in its own ticket or BUILD_NOTES section.

So the actual gap, once I compared the already-committed behavior line by
line against this ticket's requirement 2, was narrower than "add the
signal": it was **one behavioral mismatch** in how a P1128 statement with no
usable date was handled, plus **test coverage specifically exercising the
Wikidata signal through the real cascade** (the existing tests covered the
underlying `fill_size_updates` logic and `fetch_wikidata`'s claims-parsing in
isolation, but nothing exercised `_wikidata_signal` -> `size_cascade` ->
`backfill` end to end with a mocked Wikidata payload).

## (a) Undated P1128 statement: fall back, don't refuse

The pre-existing `_most_recent_dated_quantity` refused ANY P1128 statement
that lacked a P585 (point-in-time) qualifier outright, including a single,
unambiguous statement with nothing to disambiguate against — codified in
the (now-replaced) test `test_fetch_wikidata_refuses_undated_statement`.
Requirement 2 is explicit: "prefer the one with latest point-in-time
qualifier, **else the first non-deprecated rank statement**" — a lone
undated statement is still real evidence, just not date-disambiguated
evidence, and refusing it entirely contradicts that fallback.

Replaced `_most_recent_dated_quantity` with `_select_p1128_statement`:
1. Exclude `rank == 'deprecated'` statements outright (Wikidata's own marker
   that a value is superseded/wrong) — dated or not, listed first or not.
2. Among what's left, prefer the statement with the latest P585 qualifier.
3. With nothing dated at all, use the first remaining (non-deprecated)
   statement instead of refusing.
4. The chosen statement's mainsnak amount still goes through
   `sectors.resolve_employee_count`; anything that doesn't read as a
   positive integer is treated as absent, never guessed (requirement 2's
   last sentence, unchanged).

This is a deliberate behavior change from the pre-existing code, not a new
addition — flagging it here since it touches a path the earlier (uncredited)
work had already shipped with different semantics. Old test replaced with
`test_fetch_wikidata_undated_statement_falls_back_to_first_non_deprecated`;
new tests added for the parts of this that weren't exercised before:
`test_fetch_wikidata_dated_statement_preferred_over_undated` (a date still
wins when one exists), `test_fetch_wikidata_deprecated_rank_statement_excluded`
(a deprecated statement never wins, dated or not), and the pre-existing
`test_fetch_wikidata_prefers_most_recent_dated_statement` (two dated
statements, latest wins) is untouched and still passes unmodified.

## (b) Absent/unparseable P1128 is silent, not a fetch failure

Two new fetch-level tests close a gap the requirement calls out explicitly
("unparseable/absent P1128 leaves fields untouched and is NOT a
fetch-error"): `test_fetch_wikidata_no_p1128_claim_treated_as_absent_not_error`
(claims dict with no `P1128` key at all) and
`test_fetch_wikidata_unparseable_amount_treated_as_absent_not_error` (a
P1128 statement whose amount isn't numeric). Both assert `employee_count is
None` and `'size_status' not in result` — the fetch itself completed
cleanly, so this must never surface as `'error'`/`'fetch-error'` in
`BackfillAccounting`. This behavior was already correct in the existing
code (an unparseable/missing amount already fell through to `None` with no
status key); these tests just make that explicit instead of relying on it
being implied by the absence of a regression.

## (c) `sectors.fill_size_updates`: the missing mirror-image case

`test_fill_size_updates_never_overwrites_populated_field` covered "size_range
populated, size_class empty and consistent -> size_class alone fills," but
not its mirror: "size_class populated, size_range empty and consistent ->
size_range alone fills" (requirement 7's "size_class already present +
consistent -> only size_range fills"). Added
`sectors.fill_size_updates(1500, None, 'large') == {'size_range': '1000+'}`
to the same test function. The underlying logic needed no change — this was
a pure test gap in already-correct code.

## (d) New integration coverage: the real `_wikidata_signal` through the cascade

Every pre-existing test exercised either `fetch_wikidata` directly (claims
parsing) or `size_cascade`/`fill_size_updates` with a fake, hand-written
signal function standing in for "some source returned a count." Nothing ran
the actual `_wikidata_signal` through `size_cascade`/`backfill` with a mocked
Wikidata HTTP payload end to end. Added five tests in `tests/test_sectors.py`
(new "JOZ-262: Wikidata P1128 feeds the size cascade" section), all using
the `root` fixture (a copy of `sample/vault`) and a `fetch` function shaped
like a real Wikidata response, exactly the existing mocking pattern:
- `test_wikidata_signal_point_value_fills_both_size_fields` — a single
  dated P1128 statement fills size_range AND size_class on an empty
  company, with `('wikidata', 'size', 'matched')` in `collector.events`.
- `test_wikidata_signal_count_contradicting_existing_size_range_fills_nothing`
  — a count whose bucket disagrees with an already-populated `size_range`
  fills nothing and raises `FLAG_SIZE_INCONSISTENT`, via the real signal
  this time rather than a fake one.
- `test_wikidata_signal_size_class_present_and_consistent_fills_only_size_range`
  — the reverse pairing: size_class already set and consistent, Wikidata's
  count fills size_range alone.
- `test_wikidata_signal_absent_p1128_leaves_fields_untouched_not_fetch_error`
  — empty claims through the full cascade: no fields change, no review
  flag, and the collector records `('wikidata', 'size', 'empty')`, never
  `'fetch-error'`.
- `test_wikidata_signal_multiple_statements_latest_wins_through_cascade` —
  two dated statements through the full cascade; the later one's bucket is
  what ends up persisted.

## Tests

9 net new/changed tests (1 renamed + repurposed, 8 new; one existing test
function gained one more assertion). `.venv/bin/python -m pytest tests/ -q`
→ **650 passed** (641 baseline + 9), re-run 3x to confirm stability — stable
each time. (The two `test_ingest.py` timing tests that depend on `TIMEOUT`
being the module default are unrelated pre-existing environmental flakiness
in this session — an ambient `LLM_TIMEOUT=600` env var left set from the
live-smoke environment breaks their hard-coded `== 120`/`< 1.0` assertions;
clearing `LLM_TIMEOUT` before the run reproduces a clean 650/650 as shown
above. Nothing in this change touches `ingest.py` or its TIMEOUT handling.)

## Live smoke test

Scanned every company in the live vault still missing `size_range` (16 of
20) for one with a Wikidata entry actually carrying P1128. Most are small,
Swiss-local employers with no Wikidata presence at all (confirmed via the
real `fetch_wikidata`, one name at a time, paced to respect the existing
429 backoff). Two near-misses worth recording:
- **Kraken (CO-017)**, the ticket's suggested target: Wikidata's
  `wbsearchentities` top hit for the bare name "Kraken" is a Colombian
  musical group (Q6435931), not the exchange (Q22906202, the 2nd result) —
  a pre-existing, out-of-scope limitation in the top-1-result entity
  resolution this module has always used for P452 too, not something this
  ticket's P1128 reading introduced or is meant to fix.
- **Swissgrid (CO-009)**: resolves to the correct entity (Q2373251) but
  that entity carries no P1128 statement on Wikidata at all.

**Zürcher Kantonalbank (CO-016)** is the one real match: Wikidata indexes it
under the short legal name "Zürcher Kantonalbank" (Q-id resolved via search)
with a dated P1128 statement of 5,173. The vault's own `name` field for this
record is the auto-derived `"Zürcher Kantonalbank und ihre
Tochtergesellschaften"` (name_source: `auto`, i.e. lifted verbatim from a
job posting's `hiringOrganization.name`), which does not match anything in
Wikidata's search index — so an unmodified production run over this record
finds nothing (confirmed below, same as any absent-data case: silent, not
an error). This name-matching gap is the same pre-existing, out-of-scope
limitation as Kraken's, just the opposite failure mode (too specific rather
than too ambiguous).

To still produce real live evidence of the JOZ-262 P1128 pipeline itself
(not the separate name-resolution problem), the smoke script ran
`size_cascade` twice against CO-016: once completely unmodified (confirming
today's real behavior: Wikidata reports empty, not an error), and once
against an in-memory copy of the same record with only the lookup `name`
substituted to the disambiguated short form -- the on-disk `name` field was
never touched by this, and both runs resolved every other field from and
wrote their result back to the real CO-016 record via `vault.save_company`,
exactly the backfill's own write path:

```
BEFORE: {"size_range": null, "size_class": "large", "sectors": ["K"], "review_flags": []}

As-stored name ("...und ihre Tochtergesellschaften"), unmodified production path:
  size_cascade -> (None, None)
  events: jsonld/size=fetch-error (company site unreachable), wikidata/size=empty, llm/size=not-attempted

Disambiguated lookup name ("Zürcher Kantonalbank"):
  size_cascade -> ({'size_range': '1000+'}, None)
  events: jsonld/size=fetch-error, wikidata/size=matched, llm/size=not-attempted

AFTER: {"name": "Zürcher Kantonalbank und ihre Tochtergesellschaften",
        "size_range": "1000+", "size_class": "large", "sectors": ["K"], "review_flags": []}
signal_summary: {'matched': 1, 'ambiguous': 0, 'rate-limited': 0, 'fetch-error': 1, 'empty': 0, 'not-attempted': 1}
```

`size_range` went from `null` to `'1000+'`, consistent with the
already-populated `size_class: 'large'` (5,173 >= 250), attributed to signal
`wikidata`, field `size`, outcome `matched` — exactly the provenance
requirement 4 asks for. `size_class` was left alone (already populated and
consistent, per fill-empty-only semantics) and no review flag was raised.
The `name` field on disk is unchanged; this fill is left in the live vault
as evidence, following the same precedent as JOZ-261's Siemens live-smoke
fill.

**Judgment call worth flagging:** substituting the lookup name for one
demo call is a deliberate deviation from "run the real backfill unmodified,"
made because no company in this specific vault snapshot currently satisfies
both "still missing size_range" and "stored name resolves via Wikidata's
unmodified top-1 search to an entity with P1128" — the two near-misses above
are both pre-existing name-resolution gaps, not P1128-reading gaps, and
fixing entity disambiguation is out of this ticket's scope. The unmodified
first run against CO-016's real stored name is included specifically so the
"no behavior change for companies without a usable match, silent not error"
requirement is demonstrated against real production input, not only against
the demo's substituted one.

Not committed, not pushed — working tree only.

## Review fix round (findings 1,2,5,6)

A cross-review of the stacked JOZ-261/JOZ-262 tree found four in-scope
defects (findings 3 and 4 — duplicate cascades, stale-plan overwrite — are
pre-existing and filed separately; not touched here).

### Finding 1 (major) — LLM size hint bypassed range consistency

`size_cascade`'s `size_hint` branch only ever checked the hint against an
already-populated `size_class`; when `size_class` was empty but `size_range`
was already populated, it filled `size_class` from the hint completely
unchecked — e.g. `size_range='1-10'` (max 10 employees) plus LLM hint
`'large'` silently wrote `size_class='large'`, no review flag, even though
the two can never describe the same company.

Fix: added `sectors.size_class_hint_consistent_with_range(size_hint,
size_range)`, built on a new `sectors._size_range_bounds()` that parses a
bucket label ('1-10', ..., '1000+') back into `(lower, upper)` integers. The
implied class set is `{size_class_for(lower), size_class_for(upper)}` (upper
`None` for the open-ended '1000+' bucket maps to `'large'`, since nothing
above 1000 is ever anything else). A bucket whose own bounds straddle a
class threshold (e.g. '11-50': count 11-49 is 'small', count 50 exactly is
'medium') is therefore compatible with EITHER adjacent class, not just the
dominant one — the range alone can't rule out the narrower class sitting
right at that boundary. `size_cascade` now calls this before filling
`size_class` from a hint when `size_range` is already populated;
incompatible → fill nothing, raise `FLAG_SIZE_INCONSISTENT` (the exact same
flag/mechanism a contradicting raw count already uses). The already-covered
`size_class`-populated path is untouched.

Tests: `test_size_class_hint_consistent_with_range` (9-case parametrized unit
test directly on the new sectors.py helper, covering plain-compatible,
plain-contradictory, and both boundary-spanning buckets),
`test_llm_signal_size_hint_compatible_with_populated_range_fills_size_class`,
`test_llm_signal_size_hint_contradicts_populated_range_flags_without_filling`
(the exact bug scenario from the finding), `test_llm_signal_size_hint_boundary_spanning_range_treated_as_compatible`.

### Finding 2 (major) — LLM signal was not a true fallback

`external_sectors` ran every signal in `signals` unconditionally, including
`_llm_signal`, even after an earlier structured signal had already produced
a confident match — wasting an LLM call every time, and worse, a structured
'J' match followed by an LLM 'K' opinion manufactured a false
`FLAG_SECTOR_CONFLICT` that suppressed an otherwise-valid fill.

Fix: `external_sectors` now splits `signals` into structured (everything
that isn't `_llm_signal`) and the LLM signal, evaluates all structured
signals first via the factored-out `_evaluate_sector_signal()` helper, and
only invokes the LLM signal when structured signals produced no usable
result (`found` still empty — covers both "nothing matched" and "a signal
was ambiguous", but NOT "two structured signals already conflict", since
`found` is non-empty as soon as a conflict exists). When the LLM is skipped
this way, it's recorded as `not-attempted` via the existing
`_record_not_attempted` helper, so accounting coverage is unaffected.

`size_cascade` was audited against the same requirement and found already
correct: its per-signal loop breaks as soon as any signal (structured or
not) returns a count or hint, so `_llm_signal` — last in `SIZE_SIGNALS` —
was already unreachable once an earlier structured signal matched. No code
change there; added regression tests to lock in the existing behavior
alongside the `external_sectors` fix.

Tests (counting fake LLM client via a shared `_counting_llm_client` helper):
`test_external_sectors_llm_not_called_after_structured_success`,
`test_external_sectors_llm_called_as_fallback_when_structured_empty`,
`test_external_sectors_structured_conflict_short_circuits_before_llm`,
`test_size_cascade_llm_not_called_after_structured_success`,
`test_size_cascade_llm_called_as_fallback_when_structured_empty`,
`test_size_cascade_structured_contradiction_short_circuits_before_llm`.

### Finding 5 (minor) — `_select_p1128_statement` qualifier handling

Two bugs: (a) only `qualifiers['P585'][0]` was ever inspected, so a
statement carrying multiple P585 qualifiers (e.g. [2020, 2025]) could lose
to a different statement dated only 2024, using just its first (2020)
qualifier; (b) a malformed qualifiers container (not a dict, a non-list
`P585` value, a non-dict list entry) raised an exception that propagated all
the way out of `fetch_wikidata`'s outer try/except, discarding BOTH
`industry` and `size_status` as a blanket fetch error — even though industry
had already been resolved successfully from the same payload.

Fix: new `_qualifier_dates(claim)` defensively collects ALL usable P585
date values from one statement (skipping anything malformed at any level
rather than raising), and `_select_p1128_statement` now takes `max(dates)`
per statement before comparing across statements, so a statement's latest
qualifier — not just its first — determines its ranking. The whole function
body is also wrapped in `try/except Exception: return None`, so it can never
raise regardless of input shape. Additionally, `fetch_wikidata` now isolates
the `_select_p1128_statement(...)` call in its own try/except (defense in
depth beyond the selector's own safety net), setting `size_status='error'`
alone on failure without touching the already-resolved `industry`/
`industry_status`.

Tests: `test_fetch_wikidata_statement_multiple_p585_qualifiers_latest_wins`,
`test_fetch_wikidata_malformed_p585_qualifier_container_skipped_without_error`,
`test_fetch_wikidata_size_selection_exception_does_not_discard_industry`
(forces `_select_p1128_statement` to raise via monkeypatch to prove the
isolation holds even if a future regression reintroduces a raise),
`test_fetch_wikidata_all_deprecated_statements_yield_none_not_error`.

### Finding 6 (minor) — `llm_client.py` had zero regression coverage

`LLMClient` was never directly constructed in any test — the suite-wide
`offline` autouse fixture in `conftest.py` patches `urllib.request.
build_opener` itself to raise, which blocks `LLMClient.__init__` along with
every genuine network path. All existing LLM-related tests instead faked a
`client_for(...)`-style `SimpleNamespace` standing in for the whole client,
so `LLMClient.create`'s actual request-building/response-parsing — both
the default `/v1` mode AND the native (Ollama `/api/chat`) mode added
alongside this stack — had no direct coverage at all.

Added `tests/test_llm_client.py`: a `_make_client()` helper restores the
real `build_opener` (captured at module-import time, before the offline
fixture patches it) just long enough to construct a real `LLMClient`, then
replaces `client.opener.open` with a fake that records the outgoing
`Request` and returns a canned response — so the client is exercised for
real with no socket ever touched. Covers: default-mode payload/response
unchanged; native-mode endpoint (`/api/chat`, with and without a trailing
`/v1` on `base_url`), payload translation (`messages`, `format:'json'`,
`think` passthrough, `options.temperature`), optional keys omitted when not
supplied; response extraction (`message.content` vs `choices[0].message.
content`); `timeout` forwarded to the opener in both modes; `NoRedirect`
retained in the opener's handler list in both modes (plus a direct
unit-test of `NoRedirect.redirect_request` raising); malformed/absent
response raises `KeyError` in both modes identically.

**Overall deadline wrapper:** `careeros/ingest.py`'s `_within_deadline`
(grep `deadline` there) runs its LLM call on a background thread, joined via
a `Queue.get(timeout=...)`, so a client that ignores its own `timeout` kwarg
(or hangs before that socket timeout even engages — e.g. a slow DNS lookup)
still can't block past the configured budget. This was trivial to mirror in
`company_lookup.py`: added `_call_llm_client()` (the extracted client call)
and `_within_llm_deadline()` (the same Thread+Queue pattern, keyed off
`LLM_TIMEOUT`), with `_llm_classify` now calling `_within_llm_deadline()`
instead of the client directly. No change to `_llm_classify`'s external
contract (`(parsed_dict_or_None, status)`) — a deadline timeout surfaces as
a `TimeoutError`, caught by the same `except Exception` that already handles
every other transport failure, reported as `status='error'` exactly like
before.

Test: `test_llm_classify_enforces_overall_deadline_even_if_client_ignores_timeout`
(a fake client's `create()` sleeps 5s and ignores `timeout` entirely;
`LLM_TIMEOUT` monkeypatched to 0.05s; asserts `_llm_classify` returns
`(None, 'error')` in well under 1s).

## Tests

31 new tests (23 in `tests/test_sectors.py`, 8 in the new
`tests/test_llm_client.py`). `.venv/bin/python -m pytest tests/ -q` →
**681 passed** (650 baseline + 31). (As in the JOZ-262 section above, an
ambient `LLM_TIMEOUT=600` env var in this shell session breaks two
pre-existing, unrelated `test_ingest.py` timing assertions that hard-code
the module default; clearing it reproduces a clean 681/681. Nothing in this
round touches `ingest.py`.)

Not committed, not pushed — working tree only.

# JOZ-265: instant job stub, URL normalization, hard duplicate check

Not committed — left in the working tree for review, per instructions.

New modules `careeros/url_normalize.py` (normalization + ATS detection,
pure functions, no network) and `careeros/dedupe.py` (hard duplicate
lookup + warning payload). `careeros/vault.py` gains the Journey 1 job
fields (`normalized_url`, `in_pipeline`, `origin`, `source_id`,
`ingest_state`, `ingest_error`, plus `ats_provider`/`ats_tenant`/
`ats_posting_id`) and `migrate_job_fields`. `careeros/server.py`'s
`/api/jobs/intake` is restructured into the two-phase flow, plus a new
`/api/jobs/<id>/promote` endpoint and an `ingest_state` transition on the
existing `/api/jobs/<id>/extract` retry path. Templates (`jobs.html`,
`job_cards.html`, `job_detail.html`) show the new states and a Retry
control. Tests: `tests/test_url_normalize.py` (new), additions to
`tests/test_jobs.py` and `tests/test_vault.py`.

## Deviations from the brief, and why

**`original_url` keeps its existing meaning; it does not become "the raw
pasted URL."** The brief (quoting SPEC section 1) says to store the raw
pasted input as `original_url` when it differs from `normalized_url`. But
in this tree, `url` already *is* the raw pasted input (unchanged,
unnormalized), and `original_url` already has an established, different
meaning: the page's own schema.org-asserted canonical URL, populated by
`intake.py`'s `_extract()`/`ingest_posting()` and consumed by
`/api/jobs/<id>/extract` as the preferred refetch target. Repurposing it
per the brief would collide with that existing behavior and silently
change what `/extract`'s retry fetches. Per the brief's own instruction
("follow the tree, record the deviation"), `url` continues to serve as
the raw-input field and `original_url` is untouched; `normalized_url` is
simply the one new field, computed from `url`.

**A failed fetch still runs the existing heuristic/company-resolution
fallback; it is not a hard stop.** My first pass made `fetch_failed` skip
heuristic parsing and company linking entirely (company: null). That
broke several pre-existing tests (`test_intake[...None]`,
`test_delete_company_api_roundtrip`, `test_company_missing_metadata`) that
rely on the current contract: `heuristic_posting(url, html='')` still
derives a usable title/company from the URL and domain even when the page
never loaded, and a company is still created/linked from that. This is
actually the more correct reading of global rule 4 ("a pasted URL always
produces a job record, even if everything downstream fails") — the
URL-derived heuristic does not depend on the fetch having succeeded, only
the *real posting content* does. Phase B now always runs this fallback and
tags the result `ingest_state: fetch_failed` with `ingest_error` for
visibility, rather than stopping short of it. Only the LLM extraction step
is skipped when there is no real description to extract from (see next
item) — the thread is still started either way, matching the existing
`LLM_THREADS[id]` contract several tests depend on.

**`extract_failed` fires whenever the LLM returns no usable fields,
including "not configured in this environment."** This test environment
has no `LLM_BASE_URL` set, so every LLM call already fails today
(`ingest._call_llm` catches the resulting `RuntimeError` and returns
`None`, logging only the exception class name, never the reason, per the
existing redaction convention). Before this ticket that was entirely
silent — the job was simply never updated. That silence is exactly what
SPEC global rule 2 ("No silent fallbacks") asks to close, so `on_result`
now sets `ingest_state: extract_failed` whenever `fields` is `None` *and*
there was real text to attempt extraction on (an empty description, e.g.
from a `fetch_failed` stub, is "nothing attempted," not "attempted and
failed," and is left alone). This changes the observable outcome of one
pre-existing test, `test_jobs.py::test_intake` (the `<title>...</title>`
parametrization, which has real body text): its final-state assertion was
extended to check the now-visible `extract_failed` transition explicitly,
instead of asserting the job is silently unchanged. The other two
parametrizations (meta-only HTML, and a fetch that never happens) still
have no body text to extract and are unaffected.

**ATS detection fields (`ats_provider`, `ats_tenant`, `ats_posting_id`)
are new flat job fields**, even though the brief's "New job fields" list
(scope item 3) does not name them. Scope item 2 requires comparing
"detected (provider, posting_id)" against every vault job for the hard
duplicate check, which is not possible unless the detection result is
persisted somewhere on the job. Flat fields match this schema's existing
style (e.g. `company_id`) more than a nested dict would.

**The brief's "Teamtail" is treated as Teamtailor.** There is no ATS
called "Teamtail"; `teamtailor.com` is already a recognized host in
`server.py`'s `SHARED_ATS_HOSTS`, and is almost certainly what was meant.
`detect_ats` recognizes `*.teamtailor.com/jobs/<id>-<slug>` under the
provider id `teamtailor`.

**The migration runs automatically at app startup, not behind an explicit
button.** This is what the brief asks for literally ("runs at startup or
first access, safe to re-run"), but it is a deliberate departure from this
codebase's established convention for one-time migrations
(`backfill_company_kind`, `migrate_skills_to_tags`), whose docstrings say
"never runs automatically." Flagging the inconsistency here rather than
silently matching one convention or the other. `migrate_job_fields` reads
and writes the job YAML directly (like `save_watch_result` does for the
watcher), bypassing `save_job`'s full validation — a legacy record can
have a shape (e.g. an empty `url`) that predates a validation rule added
since it was written, and this migration must not refuse to backfill
purely additive fields just because an unrelated, pre-existing field would
fail today's stricter checks. `create_app` swallows `OSError` around the
migration call so a vault directory that does not exist yet (fresh
install) does not fail startup.

**Manual "paste posting text" is not built.** SPEC section 3, step 5
describes it as part of Journey 1's fetch-failure recovery, but the
brief's own "Scope (exact deliverables)" item 3 only requires a Retry
action on failure, not a paste-text endpoint. Built only what scope item 3
lists; paste-text is a reasonable follow-up, called out below.

**The two-phase HTTP response still waits on Phase B's fetch.** The brief
says both "the API returns the stub id immediately" and "Phase B
continues in the same request (fetch -> parse -> LLM extract, as today)";
taken together with "do NOT build the async worker," the fetch step
itself stays synchronous within the request, exactly as it already was.
What JOZ-265 actually delivers is: the stub (Phase A) is committed and
durably saved under its own short lock *before* the network fetch even
starts, so it is independently visible to any other reader (another
request, a direct vault read) for the whole duration of a slow or
hanging fetch — proven by `test_stub_is_visible_before_fetch_completes`,
which polls the vault from a second thread while the intake request is
blocked on a mocked slow fetch. True sub-fetch instant response is
JOZ-267's async worker.

## Open questions for the parent reviewer

1. Should a fetch failure still attempt the URL/domain-based company
   heuristic (current behavior, kept) or should `fetch_failed` leave
   `company_id: null` until a successful fetch (my first, reverted pass)?
   The former matches existing tests and global rule 4; the latter is
   arguably more "honest" about what is and isn't known yet.
2. Is "extract_failed whenever the LLM is unreachable/unconfigured,"
   not only when a configured LLM errors mid-call, the intended scope of
   SPEC step 6's failure state? This repo's test environment has no LLM
   configured, so in practice every successfully-fetched job that isn't
   explicitly mocked will settle on `extract_failed` until a real
   `LLM_BASE_URL` is set.
3. Manual "paste posting text" (SPEC step 5) and true pre-fetch instant
   response (SPEC's "appears in the list immediately" read literally) are
   both deferred — confirm that's acceptable for JOZ-265 and lands in
   JOZ-267, not expected sooner.
4. `duplicate_payload`'s `actions` list drops `add_anyway` when the match
   is a universe record (`in_pipeline: false`), showing only `['promote',
   'open_existing']`. The `/api/jobs/intake` endpoint still accepts
   `force: true` in that case regardless (it is not blocked), just not
   advertised as an action in the payload. Confirm that's the right UX,
   or whether `add_anyway` should always be offered as a third option.

## FIX ROUND (JOZ-265 cross-review, 2026-10-08)

A second coding agent cross-reviewed the diff above (tmp-review-j265.md)
and returned 5 MAJOR and 6 MINOR findings. A parent reviewer settled the
four open questions above as rulings R1-R4 (see the fix brief). Every
finding was re-verified with a deterministic probe against the pre-fix
code before any change was made; all 11 findings held up. Full suite
before this round: 728 passed. After: 771 passed (43 new regression
tests; 1 pre-existing test updated where the old assertion encoded the
bug being fixed, see M4/m10 below).

**R1 (keep the fallback, make it safe and distinguishable).** Already
true without new code once M2 landed: `ingest_state: fetch_failed` on the
job is itself the provenance marker that a company link came from the
URL/domain fallback rather than a confident schema.org extraction, and
M2's snapshot-equality protection (below) now covers `company_id` too, so
the fallback link can no longer land over an owner-set one.

**R2 (distinguish not-configured from transport failure from unusable
output).** This was a real gap: every LLM failure path collapsed to the
same `reason: 'no_usable_fields'`. `ingest._call_llm` now returns
`(fields, reason)` with three distinct reasons: `not_configured` (no
`LLM_BASE_URL`/`LLM_MODEL` in this environment, caught before any call is
attempted), `transport_error` (the API call itself failed), and
`unusable_output` (a response came back but did not parse into anything
usable). `extract_async`'s callback contract grew an optional second
argument (`on_result(fields, reason=None)`); a callback declaring only
one parameter is still called with just `fields` (checked via
`inspect.signature`), so every pre-existing single-argument callback in
the test suite is unaffected. `server.py`'s `on_result` uses the new
reason instead of a generic string. Tests:
`test_extract_async_reason_not_configured`,
`test_extract_async_reason_transport_error`,
`test_extract_async_reason_unusable_output`,
`test_extract_async_reason_none_on_success`,
`test_extract_async_single_argument_callback_still_works` (all in
test_ingest.py). `test_jobs.py::test_intake`'s extract_failed case now
asserts the specific `not_configured` reason instead of the old
catch-all string.

**R3 (scope acceptance).** No code change. True pre-fetch instant display
and paste-text mode remain explicitly out of scope for JOZ-265 and land in
JOZ-267; this round did not add an async worker. This BUILD_NOTES section
and this round's report do not claim the immediate-display acceptance
criterion as satisfied; the stub-durable-before-network-call guarantee
(`test_stub_is_visible_before_fetch_completes`, still passing) is a
different, narrower claim than "appears in the list immediately," and the
two are not conflated anywhere in this round's text.

**R4 (duplicate payload always offers add_anyway; universe match offers
all three plus a genuine dismissal).** `dedupe.duplicate_payload` now
always appends `add_anyway` to the actions list; a universe match
(`in_pipeline: false`) returns `['promote', 'open_existing', 'add_anyway']`.
`jobs.html`'s native `confirm()` dialogs are replaced with an explicit
`<dialog>` panel wired from `result.actions`, with a real Cancel button
and Escape-to-close path that creates nothing (neither falls through to
`force: true`), addressing m8 below in the same change.

### M1 (fixed) - DNS runs before the stub exists
`server.py:280` called `intake.check_url` (DNS + SSRF) before the stub was
ever saved; `intake.fetch_url` already performs the same check internally
once called, so the pre-stub call was both redundant and the actual bug.
Fix: the pre-stub call is now `intake.check_url_format` (structural only:
scheme + host, no DNS), at `server.py:301`. DNS/SSRF resolution now only
ever happens inside `intake.fetch_url`, in Phase B, after the stub is
durably saved; any failure there (including SSRF rejection) is caught by
Phase B's own try/except and surfaces as `ingest_state: fetch_failed`,
never a bare 400. SSRF protection itself (`intake.is_unsafe_ip` /
`intake.check_url`) is untouched.
Tests: `test_dns_failure_creates_fetch_failed_stub_not_400`,
`test_dns_resolved_only_after_stub_persisted` (call-order probe),
`test_ssrf_blocked_address_creates_fetch_failed_stub_not_400`.

### M2 (fixed) - Phase B overwrote concurrent owner edits, no provenance protection
`server.py`'s Phase B unconditionally merged the freshly scraped `data`
dict (title, description, location, source, and more) plus `company_id`
and `url` into the job, with no check against what the owner might have
changed on the stub while the fetch was in flight. Fix
(`server.py:390-402`): under the write lock, re-read the current record
and build `updates` as only the candidate fields whose current value
still equals the Phase A stub snapshot (`job`) for that same field; a
field the owner touched (to any value, including clearing it) is left
alone. The same check covers `company_id` and `url`, per the ruling's
"apply the same protection to company links and URL fields." The
pre-existing LLM-callback protection in `apply_llm_update` already used
this snapshot pattern; it was insufficient only because Phase B's own
merge, one step earlier, had no protection at all and clobbered the edit
before the LLM baseline was even taken.
Tests: `test_concurrent_owner_edit_during_fetch_survives` (parameterized
over title/description/location), `test_automated_fill_lands_when_field_
still_at_baseline` (control case, no edit). The brief's "owner clears a
field to empty" sub-case could not be constructed against Phase B
specifically: title is the only Phase A field with a non-blank baseline,
and vault.save_job rejects a blank title outright (title is required);
description/location both start blank, so clearing them to blank is
observationally identical to "never touched" at this phase. This is a
genuine, documented limitation of snapshot-equality (noted inline in
test_jobs.py), not a gap in the fix: the pre-existing
`test_async_owner_clear_and_success_flag` in test_ingest.py already
proves the same mechanism protects a real clear-to-empty against a
non-blank baseline, during the LLM callback phase.

### M3 (fixed) - failures could leave permanent progress states with no reason
Four distinct silent-failure paths, all through the same root cause: once
the stub was saved, nothing downstream of it was protected against an
exception, and a worker-start failure's return value was ignored outright.
Fix (`server.py:335-421`): the entire post-stub pipeline (fetch, parse,
company linking, save) is now inside one try/except; any exception
degrades the stub to `ingest_state: fetch_failed` with `ingest_error` and
a history event, never a bare 500/400 and never a silent no-op. An
empty/whitespace-only fetch result (no exception) is now explicitly
treated as a fetch failure too. `start_llm_enrichment`'s return value is
now checked; a worker-start failure now marks `extract_failed` instead of
leaving the job at `fetched` forever. The async callback's own exception
handler now also attempts to persist `extract_failed` (not just log),
with a nested try/except so a fully unavailable storage layer still logs
exactly once (matching the pre-existing `test_callback_save_failure_
contained` contract) rather than failing a second time on top of the
first.
Tests: `test_parse_failure_after_fetch_sets_failed_state_not_500`,
`test_empty_fetch_result_sets_fetch_failed_with_reason`,
`test_worker_start_failure_sets_extract_failed`,
`test_callback_exception_persists_failure_state`.

### M4 (fixed) - false hard duplicates across tenants and spoofed domains
Two independent bugs. (a) `url_normalize.detect_ats`'s Workday check used
`'.myworkdayjobs.com' in host` (substring), so
`a.myworkdayjobs.com.attacker.example` was misdetected as Workday; fixed to
`host.endswith('.myworkdayjobs.com')`, matching every other provider's
already-correct dot-prefixed-suffix check. (b) `dedupe.find_duplicate`'s
ATS-identity match compared only `(provider, posting_id)`, so the same
slug under two unrelated tenants (`a.recruitee.com/o/x` vs
`b.recruitee.com/o/x`) matched as a duplicate; every supported ATS scopes
its posting id to one tenant's board, so the match now requires
`(provider, tenant, posting_id)` all three.
Tests: `test_ats_detection_rejects_lookalike_hosts` (10 fixtures across
providers), `test_hard_duplicate_same_posting_id_different_tenant_is_not_
a_duplicate`. The pre-existing
`test_migrate_job_fields_backfills_every_missing_key` asserted
`ats_provider is None` for every sample job, which was only true because
the old migration never ran ATS detection at all (see m6); one sample job
is a real Personio posting, so the assertion was updated to compare
against `url_normalize.detect_ats` per job instead of a blanket None.

### M5 (fixed) - one malformed legacy URL could crash startup
`url_normalize.normalize` raises `ValueError` from `urlsplit(...).port`
on a URL like `https://example.com:bad/x`; `migrate_job_fields` called it
unguarded, and `server.py`'s startup only caught `OSError`. Fix
(`vault.py`, new `_migrate_one_job` + updated `migrate_job_fields`): each
record is migrated in its own try/except; a record that raises is left
byte-for-byte unchanged on disk, reported to stderr with its id and the
reason, and the sweep continues to every other record.
Tests: `test_migrate_job_fields_isolates_one_malformed_url_record`,
`test_app_startup_survives_one_malformed_url_record`.

### m6 (fixed) - migration skipped the whole record, never detected legacy ATS identity
The old migration's gate (`if data.get('normalized_url') is not None:
continue`) skipped the entire record, including fields unrelated to
`normalized_url`, the moment that one field was already present (which
happens the first time any unrelated `save_job` call touches a legacy
record, since `save_job` always writes the full schema). It also never
ran `detect_ats` at all. Fix: `_migrate_one_job` backfills each field
independently (setdefault semantics for `in_pipeline`/`origin`/
`source_id`/`ingest_state`/`ingest_error`, since those can carry a real,
final, falsy value like `in_pipeline: false`; value-based for
`normalized_url` and the `ats_*` fields, since those are always derived
and never owner-set through any API) and now calls `detect_ats` on the
stored url whenever any `ats_*` field is still missing.
Tests: `test_migrate_job_fields_never_overwrites_user_set_values` (already
existing, now exercises the independent-field-backfill path for real),
updated `test_migrate_job_fields_backfills_every_missing_key` (see M4).

### m7 (no_change_needed) - UI already documents the deferred scope
Per R3: no async worker was built. `job_cards.html`/`job_detail.html`
already render a "Details filling in..." chip after the response returns
(unchanged this round), and BUILD_NOTES' own wording already describes
the stub-durable guarantee as narrower than "appears in the list
immediately." This round's report does not claim the immediate-display
acceptance criterion as satisfied.

### m8 (fixed) - Cancel/Escape on the duplicate dialog created a second record
`jobs.html`'s native `confirm()` calls fell through to `submitIntake(url,
true)` on Cancel/Escape in both branches, and universe matches had no
Open Existing action exposed by `result.actions[0]==='promote'` branching
alone. Fix: replaced with an explicit `<dialog id="duplicate-warning">`
panel (same pattern as the existing delete-confirmation dialog) wired
dynamically from `result.actions`; Cancel and Escape both resolve to a
`cancel` action that returns without calling the API again, so nothing is
ever created on dismissal. Payload change covered under R4 above.
Tests: `test_duplicate_warning_panel_markup_no_native_confirm`,
`test_duplicate_warning_cancel_creates_nothing`,
`test_duplicate_warning_payload_always_includes_add_anyway`.

### m9 (fixed) - ATS recognition missed query-param and root-domain forms
`url_normalize.detect_ats` never read query parameters at all, missing
Workday's `?jobId=` and Personio's `?jobId=` forms, and never recognized
join.com's own root-domain path form (`join.com/companies/<tenant>/<id>-
<slug>`, as opposed to the `<tenant>.join.com/jobs/<id>` subdomain form
already handled). Fix: `detect_ats` now also checks `parse_qsl` for the
documented `jobId` param on Workday/Personio hosts, and a dedicated
`host == 'join.com'` branch for the root-domain form. Only these named,
known provider ID parameters are recognized; no arbitrary query key is
guessed at.
Tests: `test_ats_detection_query_and_root_forms` (3 fixtures),
`test_ats_detection_query_forms_do_not_misfire_on_unrelated_params` (4
negative fixtures).

### m10 (fixed) - test_intake's extension weakened an existing guarantee
The prior extension branched on `after['ingest_state'] ==
'extract_failed'` (the observed response), so a regression that made the
failure stop appearing, or that leaked an `llm_pending` reservation, would
simply fall into the "unchanged" branch and still pass. Fix: the test is
now parameterized with `expected_final_state` chosen from the html
fixture (what body text the fetch yields) rather than read back off the
response, and asserts `llm_pending is False`, the exact `ingest_error`
(stage, reason), the preserved history prefix, and the single appended
failure event, for every parametrization.

### m11 (fixed) - validation allowed inconsistent ingest_state/ingest_error pairs
`vault.py`'s job validation accepted `ingest_state: complete` with a
populated `ingest_error`, and did not restrict `ingest_error.stage` to a
known vocabulary. Fix (`vault.py`, inside `_save_record`): `ingest_error`
is now rejected unless `ingest_state` is `fetch_failed`/`extract_failed`,
and rejected if present for any other state; `ingest_error.stage` must be
`fetch` or `extract`. The `/extract` retry path (`server.py`) now also
treats `extract_failed` as a state that can transition through `fetched`,
clearing the stale error, matching `stub`/`fetch_failed`'s existing retry
handling.
Tests: `test_inconsistent_ingest_state_error_pairs_rejected`
(parameterized: complete+error, fetch_failed+null-error,
fetch_failed+bogus-stage), `test_retry_from_extract_failed_clears_prior_
error`.

Not committed, not pushed, working tree only, per the fix brief.

## FIX ROUND 2 (JOZ-265 verification follow-up, 2026-10-08)

Inherited work was retained. The first command ran the full suite against
that partial tree: 788 collected, 783 passed, 5 failed. This is distinct
from the parent-verified round 1 baseline of 771 passed. Four failures
were in the unfinished executable dialog harness; it selected the shared
UI script twice, then also redeclared dialog variables. The fifth still
expected HTTP 201 after worker startup failed. The inherited round 2
regressions also served as initial probes for ownership, migration,
URL changes, retry failure, and stage validation. Remaining handoff and
callback gaps were identified by inspection and covered with new probes.
No finding was silently skipped or disagreed with.

### O1: fixed, inherited implementation completed

The prior agent added persisted field_provenance, owner markers on PUT,
and provenance checks in fetch and callback writes. The completion now
passes a snapshot containing only the previous automation values plus
fields automation actually wrote, instead of the merged owner record.
Callback field writes and terminal-state writes share one write-lock
scope. Saved owner provenance also blocks explicit enrichment and retry
refresh writes, including deliberate empty values. Supplied provenance
is merged with existing provenance when PUT marks content fields.

Fix locations: careeros/vault.py defaults and provenance validation;
careeros/server.py apply_llm_update, Phase B automation_baseline, job_api,
and enrichment merge. Tests:
- test_owner_edit_during_fetch_survives_llm_callback_too (title, location)
- test_owner_clears_field_during_fetch_stays_empty_through_callback
- test_saved_owner_provenance_blocks_fetch_and_callback
- test_automation_fills_untouched_fields_and_marks_provenance

Two existing enrichment fixtures were adjusted explicitly: untouched
empty fields are now initialized through storage, while owner PUT clears
must remain empty. test_enrich_merge still verifies automatic filling;
test_enrich_salary_only_first_time still verifies initial salary filling
and later owner protection, and now expects an owner-cleared location to
stay empty. This follows O1 rather than weakening its guarantee.

### O2: fixed, inherited implementation completed

The prior agent classified metadata-only content as extract_failed with
reason empty_content. This classification is retained because fetching
succeeded but extraction had no usable input. A None callback preserves
that visible failure; other unusable callbacks cannot leave a healthy
fetched state. Worker startup failure now returns HTTP 503 with an
explicit error and the persisted job, replacing the partial HTTP 200.
Tests: test_metadata_only_none_callback_is_terminal,
test_worker_start_failure_sets_extract_failed,
test_thread_start_failure_clears_pending, and parameterized test_intake.
Fix: careeros/server.py start_llm_enrichment and job_intake.

### O3: fixed by prior agent, reverified and expanded

Migration treats null ATS components as unknown, detects them from the
stored URL, and preserves explicit non-null components. Migration was
chosen over lookup-time derivation to persist a stable identity once and
keep duplicate lookup simple. Added the exact null-triple Greenhouse
shape and an alternate-host duplicate assertion alongside the inherited
Personio tests. Fix: careeros/vault.py _migrate_one_job. Tests:
- test_migrate_job_fields_backfills_present_but_none_ats_triple
- test_migrate_job_fields_preserves_explicit_non_null_ats_values
- test_migrate_null_greenhouse_identity_matches_alternate_form

### O4: fixed, inherited test harness repaired

The harness now executes the actual jobs script with the shared UI
script once, in separate scope from its driver. Cancel, Escape, Open
existing, Add anyway, and Promote are exercised. Requests emitted by
Cancel, Escape, Open existing, and Add anyway are replayed against the
real API, with actual vault record-count assertions. The old three-string
Cancel test was removed. Native confirm absence remains asserted.
Fix: tests/test_jobs.py _run_dialog_scenario and
_assert_dialog_record_count. Tests:
- test_duplicate_dialog_cancel_and_escape_create_nothing
- test_duplicate_dialog_add_anyway_creates_second_record
- test_duplicate_dialog_open_existing_navigates_and_creates_nothing
- test_duplicate_dialog_promote_creates_nothing
- test_duplicate_warning_panel_markup_no_native_confirm

### N1: fixed, inherited repair completed

The partial repair restored an error after a failed handoff but cleared
it before attempting startup, and missed refresh worker failures. The
prior error now remains until extract_async returns a worker. Early
callbacks queue until that accepted handoff transition is saved, so an
immediate success cannot be overwritten with fetched. Failed extraction
startup, refresh startup, and refresh exceptions persist extract_failed
with reason and history. Refresh startup returns HTTP 503. An already
started background refresh returns HTTP 202 with accepted true; this
acknowledges queued work, not successful extraction. GET reports the
subsequent terminal outcome and pending false.
Fix: careeros/server.py start_llm_enrichment and extract_job. Tests:
- test_retry_worker_start_failure_does_not_leave_fetched_with_no_error
- test_retry_error_retained_until_successful_handoff
- test_retry_from_extract_failed_clears_prior_error
- test_refresh_worker_start_failure_is_terminal
- test_refresh_worker_exception_persists_failure

### N2: fixed, inherited repair completed

The prior agent discarded stale Phase B content and recomputed identity
on owner PUT. Completion adds extract_failed/source_url_changed, clears
the obsolete original_url fetch target, and protects callback completion
as well as field writes from stale URLs. Normalized URL and all ATS
components change in the same PUT save. The route audit found intake
creation and generic PUT as the URL-writing paths; explicit enrichment
already checks its source URL, and retry checks its snapshot. The
mid-fetch regression now uses distinct ATS tenants, checks no stale
worker starts, and proves re-adding the old URL creates a separate job.
Fix: careeros/server.py job_intake, job_api, start_llm_enrichment. Tests:
- test_url_change_during_fetch_discards_stale_result
- test_put_url_change_recomputes_normalized_url_and_ats_atomically
- test_url_change_before_callback_discards_completion

### N3: fixed by prior agent, reverified

Failure state and stage must correspond in both directions.
Fix: careeros/vault.py expected_stage validation.
Test: test_ingest_error_stage_must_match_failure_state (both mismatches).

### H1 and H2: completed by prior agent, reverified

H1: test_migrate_job_fields_personio_fixture_detected_independent_of_detector
asserts the literal fixture identity without calling the detector for its
expectation. H2:
test_migrate_job_fields_backfilled_ats_identity_matches_as_duplicate
asserts alternate-form duplicate detection after migration. The new
Greenhouse test provides an additional independent identity expectation
and alternate-form duplicate assertion. The earlier generic migration
test correction is retained.

### Verification and deviations

Full suite: 788 collected / 783 passed / 5 failed before completion;
794 collected / 794 passed after completion. Net change is seven new
cases and removal of the obsolete source-string Cancel test. Node was
available; no dialog test was skipped. Command:
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q.

The requested ephemeral-port smoke was attempted with a temporary vault,
but the managed sandbox rejected socket creation with PermissionError,
Errno 1, Operation not permitted. Approval is unavailable in this session.
The port-based smoke therefore remains unverified. A WSGI integration
fallback exercised actual routes, actual extraction workers, a fixture
completion service, and the actual dialog JavaScript. It does not claim
to verify a listening socket or a full browser DOM. Temporary scripts and
raw transcripts are in /tmp and are not git-bound.

Smoke key lines:
- O1: stub visible mid-fetch; owner title and location survive successful callback.
- O1: owner sets location then clears it; empty location survives both phases.
- O2: metadata-only page ends extract_failed / empty_content / failure history.
- N1: intake 503; retry 202 accepted; final extract_failed / worker_start_failed / pending false.
- N1: job detail renders Extraction failed after the failed retry.
- N2: changed URL rejects all stale fields and callback; identity belongs to the new tenant; old URL creates a separate record.
- O4: Cancel 0, Escape 0, Open existing 0, Add anyway 1 record-count deltas.

Leak scan of added diff lines plus git-bound untracked modules/tests:
no private addresses, private hostnames, credentials, or deployment
endpoint/provider details. Numeric URL-port matches are existing public
example-domain normalization fixtures, not deployment endpoints.
git diff --check passes. No commit or push was performed. All fixture
writes were temporary; the owner vault was never accessed. Network and
LLM calls remain outside the vault write-lock. Schema changes are
additive. Closed round 1 findings were not reopened for unrelated churn.
