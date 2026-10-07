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
