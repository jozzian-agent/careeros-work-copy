# FIXES

The follow-up round that answers the reviewer's notes on the stability
batch, and carries two owner decisions, is the **last** section of this
file. Corrections it made to the write-up below are marked where they
belong, so this file does not read as if the batch were still accurate
where it was not.

## Stability batch

CAREER-29 to CAREER-33, built 2026-10-16. No surface changed, so nothing
here needs a sketch or a click-test except as noted. Every change is
uncommitted in the working tree, including the submodule edit.

Worked in the order the brief set (5, 2, 1, 4, 3), smallest blast radius
first; written up in ticket order below.

### Gates

| Suite | Command | Result |
|---|---|---|
| Product | `.venv/bin/python -m pytest tests/ -q` | 1250 passed |
| Capability | `cd vendor/capa-repo && ../../.venv/bin/python -m pytest tests -q` | 240 passed |
| Browser | `cd frontend && npx playwright test` | 299 passed |

Baselines before this batch: 1230 / 236 / 290. The two pytest suites must
run separately and each from its own root — `tests/test_enrich.py` exists
in both trees, and a run that collects both aborts with
`import file mismatch` before a single test executes. That is now written
down in README.md, because the obvious thing to type (`pytest` at the
repo root) collects nothing at all, and an abort is easy to mistake for a
pass when it scrolls past.

New test functions, counted as functions rather than parametrised cases:
8 product, 4 capability, 1 spec file (9 routes). The product suite's count
rises by 20 rather than 8 because two of those are table-driven.

Each **behaviour** test was seen failing once against the unchanged code;
where that needed the code temporarily reverted, the revert is described
under the item. The exceptions, stated plainly: two of the 8 are
vocabulary pins (`test_the_seed_is_the_pinned_vocabulary`, and the ISCO
level pin the follow-up round renamed to
`test_an_entry_carries_an_isco_unit_group_unless_it_has_no_esco_parent`),
which guard a data
file against an unnoticed edit rather than guarding behaviour, so there
is no code to break to see them fail — the same character as
`test_the_ending_suggestions_are_the_owner_words`, which they are modelled
on.

---

### CAREER-29 — seed the job-function facet, widen the ESCO seed

**The premise had already moved.** The live vault has had a `tags.yaml`
since 2026-10-15 with all 28 function ids seeded, and one job (JOB-046)
carries a function. So the missing seed path was not missing:
`vault.seed_function_facet` and
[docs/runbooks/seed-function-facet.md](docs/runbooks/seed-function-facet.md)
shipped in `d1b21e9`, and the facet was run against the live vault. What
was left was the vocabulary itself and its pinning.

**Widened the seed from 28 to 31 entries**, every gap found by reading
the owner's own 42 stored postings rather than by guessing at a market:

| Added | Postings that had no home |
|---|---|
| `ict-consultant` | "M365 Digital Workplace Consultant", "AI Tech Consultant" |
| `business-development-manager` | "Ökosystem & Strategie Manager", "Engagierte Persönlichkeit für Produktportfolioentwicklung", "Crew Product Lead" |
| `innovation-manager` | "Innovation Management Professional", "Digitalisierungs- und Innovationsprojektleiter" |

**Five** existing entries gained keywords for the same reason: `product
owner` / `head of product` (product manager), `entwickler` (software
developer), `channel manager` (sales manager), `security expert`
(security manager), `trade control` (compliance officer). (This section
said "four" and then listed five; the count was the error, not the list.)
Keywords matter because the whole seed is handed to the extraction prompt
(`ingest._function_options_text`), so an id with no lexical anchor for a
posting the owner actually stores is an id the model will not reach for.
`security expert` did not survive the follow-up round below: it was the
one keyword here that pointed a posting at the wrong ISCO unit group.

**ISCO level: settled on the four-digit unit group**, which is what the
file already used; the brief left the choice open between that and a
three-digit minor group. Recorded in the file header with the reason: a
coarser roll-up is a prefix of the unit group, so recording the finest
level keeps every roll-up available, and draft choice 22 derives ISCO
from the validated ESCO concept anyway. There is a test for it.

**Vocabulary pinned the way the stopped reasons are pinned.** The old
test asserted "at least 20 ids, and these 10 are among them", which a
deletion walks straight through. `tests/test_function_facet.py` now holds
the full id tuple in seed-file order (`FUNCTION_IDS`, 31 ids here and 40
after the follow-up round), mirroring
`tests/test_board_d7.py::test_the_ending_suggestions_are_the_owner_words`,
plus a table-driven test with one line per posting shape the owner stores.

Files: `careeros/data/esco_occupations.yaml`, `tests/test_function_facet.py`.

**Deliverable for the parent — seeding the live vault.** Full sequence,
with the backup and the before/after counts, is
[the runbook](docs/runbooks/seed-function-facet.md); the one command at
its heart, run from the repository root with `VAULT` set to the live
vault's path (updated to the call the follow-up round left behind — it
returns added **and** updated ids now):

```bash
.venv/bin/python - <<'PY'
import os
from careeros import vault
root = os.environ['VAULT']
with vault.WriteLock(root):
    result = vault.seed_function_facet(root)
print('added', len(result.added), 'ids:', result.added)
print('updated', len(result.updated), 'ids:', result.updated)
PY
```

**Superseded by the follow-up round below**, in two ways worth naming
here because this section got both of them wrong:

- The expected output was `added 3 ids` and the vocabulary is now wider,
  so the run adds 12 ids and updates 7. The [runbook](docs/runbooks/seed-function-facet.md)
  carries the real output of a run against a copy of the live
  `tags.yaml`.
- This section claimed the keyword additions reach "the prompt, which is
  built from the seed file's own options at call time, so no vault write
  is needed for them". **That is false.** The prompt is built from the
  *vault's* own facet (`vault.function_facet_options`, called in
  `server.py` at both extraction sites), never from the seed file, so a
  keyword that reaches no vault reaches no reading. Since the seed also
  skipped every id already present, those five keyword additions reached
  nothing at all. Fixed below.

**Not done, flagged:** 30 of the 31 entries are still local extensions
with `esco_uri: null` and their `isco` cleared on the way into the vault
(decision 25). Confirming an entry against the live ESCO portal is owner
work and was already an open question in the runbook; this batch added
three more unconfirmed entries to that list rather than resolving it.
(Resolved for the 10 concepts the golden set needs, in the follow-up
round below; 25 of the now-40 entries are still unverified.)

---

### CAREER-30 — visible drops

The function-id drop was already visible (`d1b21e9`: a log line, and a
`field_status_reason` when no id survived). This generalises the rule to
every drop site found on the way into a record.

**Sites found and what each one now does.** Values are never logged, only
field names and payload keys: a dropped value is as likely to be a
private IP or a personal address as a typo.

| Site | Before | Now |
|---|---|---|
| Unknown function id (`server.accept_function_ids`) | log + reason | unchanged |
| **Redaction emptying a value** (`ingest.redact`) | silent | logs at the one place that does the emptying, so every call site emits a line; the 9 of 14 call sites that pass a field path name it (`Redacted seniority ...`), the rest log a generic `Redacted an extracted value`. Takes an optional collector so a write can also put a reason on the record |
| **A redacted field on the extraction write** (`server.apply_llm_update`) | silent | `field_status_reason` saying the reading answered and the answer could not be stored, for any emptied field `field_status` reports and the write left without a value |
| **A payload key the record does not store** (`vault._save_record` for jobs and companies, `vault.validate_experience` for experiences) | silent | logs kind, record id and the dropped keys |
| **An unusable extracted `contact_email`** (`server.apply_llm_update`) | silent | logs the job id and that the address was not usable |

`function_drop_status` became the general `drop_status`, with the
function-id wording as its one caller-specific reason; the redaction
reason is the second caller. A reason is only ever recorded for a field
in `ingest.STATUS_FIELDS` — the vault drops a reason the moment its field
moves off `not_evidenced`, and a field no status rule ever moves would
keep its reason for good.

**Consciously not done:** `description` and `summary` are not in
`STATUS_FIELDS`, so a redacted description gets the log line and no row
on the record. Adding either as a per-field status row changes the
extraction popup, which is surface work needing an approved sketch, so it
is out of this batch. It matters: the description is the field the
[residue audit](docs/audits/redaction-residue.md) is about.

Files: `careeros/ingest.py`, `careeros/server.py`, `careeros/vault.py`,
`docs/flows/add-job-by-link.md`, `tests/test_ingest.py`,
`tests/test_put_provenance.py`.

**Test evidence.** 5 new product test functions. The brief's own case
("feed an unknown tag id through the API, assert the drop is visible on
the record and in logs") was already covered by
`tests/test_function_facet.py::test_a_dropped_function_id_leaves_a_trace_on_the_job_and_in_the_log`,
which still passes. New:

- `test_ingest.py::test_a_redacted_field_leaves_a_reason_on_the_record_and_a_log_line`
  — also asserts the removed content appears in neither the log nor the
  reason. Seen failing with the log/collector lines stubbed out
  (`KeyError: 'seniority'`).
- `test_ingest.py::test_a_redacted_field_the_record_already_has_a_value_for_records_no_reason`
  — a reason explains an empty field, and that field is not empty.
- `test_ingest.py::test_an_unusable_extracted_contact_email_is_logged_when_dropped`
  — the job id is in the message and the address is not.
- `test_put_provenance.py::test_a_dropped_payload_key_is_logged_rather_than_dropped_in_silence`
  — seen failing with the vault log line disabled.
- `test_put_provenance.py::test_a_write_of_only_stored_keys_logs_nothing`
  — the guard against a log line on every ordinary write.

**Noise check before shipping the vault log line:** instrumented
`_save_record` across the whole product suite. 8 dropped-key events in
1230 tests, all of them either a test's own deliberate junk key or the
retired `fit`. It does not fire on ordinary operation.

---

### CAREER-31 — redaction-residue audit

Read-only, as instructed: nothing was written to the live vault and no
posting was fetched. Full table, per-record evidence and the commands are
in [docs/audits/redaction-residue.md](docs/audits/redaction-residue.md).

**The headline is that the brief's premise does not survive the records.**
8 of **44** records have an empty `description` or `summary` (6 and 7, 5
of them both), and **not one can be attributed to the redaction defect**
(the denominator read 42 here and in the audit until the follow-up round
re-counted; JOB-048 and JOB-049 were already in the vault and neither is
affected, so every per-record finding stands):

- **JOB-003** was never read at all — no `enriched` or `llm_enriched`
  event in its history. Nothing was lost; nothing was ever extracted.
- **JOB-034** failed to fetch on 2026-10-13, two days *after* the fix,
  and says so on the record (`ingest_state: fetch_failed`,
  `ingest_error`, two `description_refresh_failed` events, a LinkedIn
  login wall). Its summary is non-empty and owner-written.
- **JOB-020** and **JOB-021** were read before the fix, but their stored
  descriptions are 16 and 79 characters of page chrome and bare title, so
  a reading of that text yields an empty summary either way.
- **JOB-004, 005, 006, 007** were enriched 2026-10-02, pre-fix, by the
  scrape pass only. Empty descriptions afterwards, consistent with the
  redaction defect and equally consistent with a fetch that returned
  nothing. All three of `field_status`, `field_status_reason` and
  `field_provenance` are empty on them, so nothing stored tells the two
  apart.

That last point is the actual finding, and it is why CAREER-30 was worth
doing properly: a field emptied by redaction was indistinguishable from a
field the posting never supported. From now on it says which.

**Re-read path, per record.** `re-extract` reads the stored text and
fetches nothing, so it restores **nothing** for all six empty-description
records — it is the wrong tool for every record in this audit. `POST
/api/jobs/<id>/extract` re-fetches and is the only path that can restore
a description. Worth running: JOB-004, JOB-005, JOB-006 (and JOB-003 as a
first reading). Not worth running: JOB-021 (JS-rendered, expect the shell
again), JOB-020 (not a posting, a careers landing page). Cannot work:
JOB-007 (`posting_gone` 2026-10-07), JOB-034 (fetch already fails twice
over) — paste the posting text for those two instead.

The exact commands, the backup first, and the verification loop are at
the end of the audit. The parent runs them; this batch ran none of them.

**Note for the audit's own filing:** the audit names no absolute vault
path, because `tests/test_jobs.py::test_host_path_not_introduced` is a
product rule that only `careeros/server.py` may hold the host vault path.
The first draft failed that test, which is the rule working.

---

### CAREER-32 — retire scripts/verify.py

**Deleted** `scripts/verify.py` (gone from disk, not just dereferenced)
and updated every reference: `README.md` (which recommended it while
admitting it was stale), `PROJECT.md`'s open question, and two mentions
in `docs/decisions/design-system.md` rewritten as history.

**The diff against the Playwright suite, check by check.** The script had
three parts.

1. **It ran `pytest` itself.** Dropped: the gate runs the suites directly,
   and both are in README.md now.
2. **~40 `curl` checks against a real Flask server** (page routes return
   `CareerOS`, 404s, `/api/search` round trip, experiences CRUD, jobs
   list and invalid-status 400, companies GET/PUT, intake rejecting
   `file://`, the delete-while-linked 409 and the delete cascade).
   Dropped as duplicates: every one is covered by the product suite
   against the same sample vault through the Flask test client
   (`tests/test_api_search.py`, `test_api_experiences.py`,
   `test_api_jobs.py`, `test_api_companies.py`, `test_jobs.py`,
   `test_company_kind.py`). What the script added over those is a real
   socket and the WSGI layer, which is behaviour Flask guarantees.
3. **~60 browser assertions.** Nearly all of them drove the Jinja app and
   cannot be ported because the surfaces are gone: `#toast`, `#job-sort`,
   `#status`, `#notes`, `.jobs-table`, `input[name="sectors"]`, the
   Board/List switch, `confirm()` dialogs, the "Enrich pending" button
   removed in the M1 audit, and `.kanban-column` counted as 8 when the D7
   board has five columns and an Ended lane. The React equivalents are
   already covered by the 21 existing spec files.

**Folded in, because nothing else held them:** the script's two
app-wide browser guards — no uncaught script error, and no request to any
origin but the app's own. Now `frontend/tests/page-health.spec.js`, over
nine routes (`/`, `/jobs`, `/jobs/JOB-001`, `/companies`,
`/companies/CO-001`, `/experiences`, `/experiences/EXP-001`, `/notes`,
`/taxonomy`) instead of one run of one page set. The second guard earns
its place on its own: the front end is offline-by-default, and a stray
CDN import would otherwise pass every existing spec.

Both guards were seen failing: an injected `addInitScript` that threw and
fetched `https://cdn.example/probe.js` turned all 9 green tests red, once
for the error array and once for the external array, then was removed.

**Consciously dropped, and recorded as an open question in PROJECT.md:**
the real-backend browser check. The Playwright suite drives the **Vite
dev server** — `frontend/playwright.config.js` starts `npm run dev` as
its `webServer` — with every API response mocked
(`frontend/tests/helpers.js`); the pytest suites drive the real handlers
with no browser. So the gap after this deletion is wider than "no real
backend": the bundle Flask actually serves (`frontend/dist`, from
`npm run build`) is loaded by no automated check either, so a break that
only shows up in a production build is invisible too. The owner
click-test is what covers both. Whether that is worth a second Playwright
project serving `frontend/dist` from Flask over the sample vault is the
owner's call, not a thing to build inside this batch. Also dropped: the
screenshot run, and the sample-vault snapshot-and-restore dance the
script needed because it wrote to `sample/vault` (the test suites use tmp
copies, so the need is gone).

**Deleted in the follow-up round:** `careeros/web/screenshot.py` was left
in place here, unreferenced by any code once `verify.py` went, on the
argument that AGENTS.md's component gate needs specimen screenshots. The
owner decided otherwise the same day: the module is gone.

---

### CAREER-33 — stop writing size_range

**The product half was already done** (M0-7, 2026-10-15):
`vault._drop_retired_size_range` strips a `size_range` from every company
payload at the one write gate. So no live record was gaining a range. The
erosion the brief names was upstream of that gate and at one site beside
it.

**Capability (`vendor/capa-repo/org_intake`, edited in place — the pin
must move; the parent handles the pin).** Contract rule 8 derived the
numeric bucket beside the class, atomically, so the pair could not
desync. There is no pair to keep in step once one scale is retired, and a
derivation that keeps handing back the retired one invites the next
caller to persist it:

- `classify.derive_size` returns `{'size_class': ...}` and nothing else.
- `classify.fill_size_updates` proposes only the class.
- `enrich.size_cascade` drops the dead `size_range` write filter.
- **Reads kept intact**, which is most of what touches the field:
  `size_range_bucket`, `_size_range_bounds`,
  `range_consistent_with_size_range`,
  `size_class_hint_consistent_with_range`, and the cascade's own
  consistency check and protection gate still read a stored range,
  because a record written before the decision carries one and evidence
  that contradicts it is a conflict to flag.

**One real bug fell out of that and is fixed.** With the class the only
field anything fills, "nothing to fill" stopped meaning "the evidence
contradicts the record": a count that *agrees* with an already-stored
class now also fills nothing. The cascade read an empty fill as a
conflict, so every company whose stored class a signal merely confirmed
would have been flagged `FLAG_SIZE_INCONSISTENT`. Caught by
`tests/test_sectors.py::test_wikidata_signal_count_consistent_with_a_stored_class_changes_nothing`,
which went red on the first pass. Fixed by asking the question directly:
new `classify.count_conflicts_with_stored_size`, which
`fill_size_updates` and the cascade both use, so the two can never drift
apart again.

**Product side.**

- `careeros/server.py` `run_company_cascade`: the `size_range` strip is
  gone — nothing proposes one now — and the comment says why rather than
  leaving a filter nobody can date.
- `careeros/server.py` phase B: `derive_size` for a new company writes
  the class alone, because that is all it returns.
- **`careeros/intake.py` `_extract` stops bucketing a posting's headcount
  into a `size` string, and `fill_company_metadata` stops filling the
  legacy `size` field from it.** This one is a judgement call worth the
  owner's eye: it is the legacy `size` field, not `size_range`, so it was
  arguably outside the brief. But the bucket was derived from the very
  same `employee_count` the class is derived from, and the two writes
  landed in the same `changes` dict, so a company enriched from a posting
  with a headcount ended up carrying `size: '51-200'` *and*
  `size_class: 'medium'` — the two coexisting scales the 2026-10-15
  decision retired, rebuilt from one signal under the old field's name.
  Reads of a stored legacy `size` are untouched
  (`careeros/web/pages/companies.py`), so an older record still shows
  what it carries. Reversing this is a small revert if the owner wants
  the legacy field writable.

**Test evidence.** 4 new capability test functions, 1 new product test:

- `tests/test_sectors.py::test_retry_company_leaves_an_owner_approved_size_class_untouched`
  — the brief's own case, through `POST /api/companies/<id>/retry` end to
  end: a company with `size_class: large` and a signal reporting 1500
  employees keeps its class, stores no range, raises no flag, and reports
  `applied_fields: []`. Seen failing with the capability hunks reverted
  (`assert ['size_range'] == []`), which is the point: the old code
  reported having filled a value no write persists.
- `vendor/.../test_classify.py::test_derive_size_never_hands_back_the_retired_numeric_scale`
  and `::test_count_conflicts_with_stored_size_separates_agreement_from_contradiction`.
- `vendor/.../test_enrich.py::test_rule11_a_count_agreeing_with_a_stored_class_neither_writes_nor_flags`
  and `::test_rule11_a_count_contradicting_a_stored_class_still_flags` —
  the two halves of the bug above.
Existing expectations were updated rather than deleted, each with the
reason beside it: every product and capability assertion that named
`size_range` in a derivation or cascade result now names the class alone,
`tests/test_sectors.py::test_extract_retains_the_raw_employee_count_and_derives_no_bucket`
(renamed from `..._retains_both_size_bucket_and_raw_employee_count`) and
`tests/test_jobs.py::test_company_size_extraction` now pin the raw count
and the absence of a bucket, and
`tests/test_jobs.py::test_company_metadata_fill_only` expects the legacy
`size` to stay `None` where it used to expect `'51-200'`. The removal of
the bucket from `_extract` also meant removing `'size'` from the phase-B
metadata split in `careeros/server.py` (a `KeyError` the first full run
caught, in 119 tests at once).

Docs: `docs/capabilities/org-intake.md` (rules 8 and 11, the pinned
`classify_size` example, and a note that the pin must move),
`docs/surfaces/companies.md`, `docs/schemas.md` (the company `size` row
and the JSON-LD `numberOfEmployees` mapping, which still described the
bucket ladder), PROJECT.md's Size fixed list.

---

### What the parent needs to do

1. **Move the submodule pin.** `vendor/capa-repo` is edited in place
   (`org_intake/classify.py`, `org_intake/enrich.py`, and its own three
   test files). Nothing is committed in either repo.
2. **Seed the function facet** in the live vault. The command is above,
   but read the [runbook](docs/runbooks/seed-function-facet.md) for the
   current numbers: the follow-up round widened the vocabulary to 40
   entries and made a re-run update what it used to skip, so the run
   adds 12 ids and updates 7.
3. **Run the re-reads** the audit lists, after the backup it names.
4. ~~**Decide two flagged calls**~~ — both decided by the owner on
   2026-10-16 and implemented in the follow-up round: the legacy company
   `size` field stays unwritten (and the headcount behind it is now
   stored as size evidence instead of dropped), and
   `careeros/web/screenshot.py` is deleted.

### What this batch could not verify

- **Whether the pre-fix redaction caused any of the 8 empty fields.** It
  cannot be answered from the vault, and the only thing that would answer
  it — a log from 2026-10-02 — was never written, which is the defect
  CAREER-30 fixes. Running the re-read makes the question moot for the
  three records that can be refetched.
- **That the built front end works against the real backend.** No
  automated check covers it, before this batch or after, and the browser
  suite does not even load the built bundle (it drives the Vite dev
  server); see the PROJECT.md open question. The owner click-test is the
  only cover.
- **The ESCO URIs and ISCO codes** of the 30 unconfirmed seed entries,
  including the 3 added here. No network call was made to the ESCO
  portal. They reach no vault while `esco_uri` is null. (The follow-up
  round verified 10 against the live ESCO API — every concept the golden
  set uses — leaving 25 of the now-40 entries unverified.)
- **Whether the widened seed actually raises how many jobs carry a
  function.** That needs the re-read in CAREER-31 and a count afterwards,
  both the owner's action. The baseline: **3 of the 44 stored jobs carry
  a function** (JOB-046, JOB-048, JOB-049, all `ict-product-manager`),
  counted from the live vault on 2026-10-16. This section said "1 of 42",
  which was the state when the facet was first seeded and two records ago.

---

## Follow-up round — reviewer notes and two owner decisions

Built 2026-10-16, on top of the uncommitted batch above and still
uncommitted: nothing is committed, nothing is pushed, nothing of the
batch is reverted. The reviewer accepted the batch with notes; this
answers every one of them, plus two owner decisions taken the same day.
No surface changed here either.

### Gates

| Suite | Command | Result | Baseline |
|---|---|---|---|
| Product | `.venv/bin/python -m pytest tests/ -q` | **1286 passed** | 1250 |
| Capability | `cd vendor/capa-repo && ../../.venv/bin/python -m pytest tests -q` | **240 passed** | 240 |
| Browser | `cd frontend && npx playwright test` | **299 passed** | 299 |

15 new product test functions (8 in `tests/test_function_facet.py`, 5 in
`tests/test_enrich.py`, 2 in `tests/test_sectors.py`); the suite count
rises by 36 because three of them are table-driven. No capability code
was touched, so that suite is unchanged at 240 and the pin still has to
move for the batch's own reason.

**Seen failing first.** The behaviour tests were run against the
unchanged code by reverting `careeros/vault.py` and `careeros/enrich.py`
to `HEAD` and restoring them afterwards:

- the three re-seed tests failed (`ValueError: too many values to
  unpack`, then the skipped update);
- all ten posting-headcount cases failed (`KeyError: 'employee_count'`
  on the aggregate, and `assert 'size-inconsistent' in []` on the
  conflict path);
- `test_re_running_the_seed_leaves_a_vault_only_confirmation_alone`
  passed before the change, and is named as what it is: a guard that the
  new update path does not overreach, not a behaviour that was missing.

The vocabulary tests are pins against a data file, the same character as
`test_the_ending_suggestions_are_the_owner_words`. They were still seen
red before the file changed: with `careeros/data/esco_occupations.yaml`
reverted, 28 of the 55 cases in `tests/test_function_facet.py` fail.
`test_a_label_with_no_esco_concept_is_not_absorbed_into_a_wrong_unit_group`
is the one that fails specifically against **the batch's own** keyword
list, which is where `security expert` was added.

---

### A. Function vocabulary (CAREER-29 follow-up)

**A1 — the 10 verified URIs are in the seed, and a re-run is no longer a
no-op. DONE.** Every URI in
`/root/careeros-golden-set/function-vocabulary-2026-10-16.json` was
re-fetched from
`https://ec.europa.eu/esco/api/resource/occupation?uri=<uri>&language=en`
rather than trusted: all 10 answered, each one's `preferredLabel.en`
matching the json's label and its `code` beginning with the json's ISCO
(`1330.7`, `2511.9`, `1221.3.2.1`, `1330.6`, `1223.1`, `1221.3.2`,
`1221.2`, `2421.2`, `2511.7`, `2512.3`). All 5 labels the json calls
fabricated returned **404**, confirming the split. The four digits before
the first dot are what each entry records as `isco`, which is choice 22's
"derived from the validated concept" made literal; the file header says
so, and `tests/test_function_facet.py::ESCO_BACKED` pins the pair.

The seed skip is fixed, which is what made this worth doing before any
run: `vault.seed_function_facet` now **updates** an entry already in a
vault — `esco_uri`, `isco` and the local-extension marker together,
because the three are one statement about which concept the entry is —
and merges in new keywords, adding and never removing. It returns a
`FunctionSeedResult(added, updated)` named tuple instead of a bare list,
so a run says what it confirmed as well as what it created. Labels are
still never touched, and a second run in a row writes no file.

The same no-op hid a second thing, which the batch's own write-up got
wrong: the extraction prompt is built from the **vault's** facet
(`vault.function_facet_options`, called at both extraction sites in
`server.py`), never from the seed file. So the batch's five keyword
additions reached no reading at all. They do now. The flip side is
written into the runbook: a keyword *removed* from the seed file stays in
a vault that already stored it, and taking one out is a hand edit.

**A2 — every golden-set label is expressible. DONE.** Four new
ESCO-backed entries for concepts the seed had no home for: `product
manager` (1223), `banking products manager` (1221) — the two the brief
named — plus `business consultant` (2421) and `ICT business analysis
manager` (2511), which the golden set also uses and which are their own
ESCO concepts rather than the `management-consultant` and
`ict-business-analyst` entries already present (`business consultant`
moved off the former's keyword list onto the concept that owns it).
`test_every_golden_set_label_is_expressible` checks all 15 function
labels in the golden set; the 2 `unclassifiable` rows are a careers
landing page and a job-board page, which is not a function and gets no
id on purpose.

**A3 — the two absorptions are fixed and the five owner labels are local
extensions. DONE.** New `local: true` entries, carrying `isco: null` and
`esco_uri: null`: `embedded-systems-security-engineer`,
`chief-product-officer`, `digital-transformation-manager`,
`innovation-officer`, `digital-marketing-manager`. They seed as
`source: local-extension`, and `_seed_is_esco_backed` refuses to treat
one as ESCO-backed even if a URI were filled in beside the marker.

- **`embedded systems security engineer`** (golden 2529): `security
  expert` is off `ict-security-manager` (1330) and on the new entry,
  beside `product security`, `solution security`, `embedded security`,
  `produktsicherheit`, `ot security`, `iot security`. The test that
  asserted the 1330 absorption as correct
  (`test_a_posting_the_owner_stores_has_an_id_to_land_in[Product &
  Solution Security Expert...]`) now expects the local extension, and a
  second test asserts `ict-security-manager` no longer claims that title
  by any keyword at all.
- **`chief product officer`** (golden 1223): its own entry, with `chief
  product officer`, `cpo`, `vp product`, `head of product`. The blanket
  keyword was **reviewed, not removed**, and `head of product` now
  anchors both entries. The reason, from the golden set itself: four rows
  contain "Head of Product" and they split two and two — CISTEC and the
  no-company row are the top product role (1223), while Proton's "Head of
  Product (Mail)" is one product line and LinkedIn's "Head of Product
  Orchestration" one product area, both 1330. (The brief said 2 of 3; the
  CSV says 2 of 4.) Keywords are prompt context and not a matcher
  (choice 11 defers the matcher), so a genuinely ambiguous phrase
  anchoring both candidates is what lets the posting's own text decide;
  giving one id sole ownership would decide those rows by seed order.
  The file header states this rule, and the test table has a row for each
  reading.
- **`digital transformation manager`, `innovation officer`, `digital
  marketing manager`** got the same treatment — entries, markers, ISCO
  unmapped. Their rows were *not* absorptions and the write-up does not
  claim they were: each one's golden ISCO reading (1330, 1223, 1221)
  equals the unit group of the ESCO entry its title already reached, so
  nothing landed in a wrong group. The one row where the groups differ is
  "Senior Manager, Global Trade Control (GTC), Digital Enablement"
  (golden: digital transformation manager, 1330, **40% confidence**,
  runner-up "import export manager") against `compliance-officer`
  (2619). Both anchors are now present (`trade control` and `digital
  enablement`) and both are pinned, because at that confidence the
  vocabulary's job is to offer the reading, not to pick it. Same for
  "Ökosystem & Strategie Manager" (golden: business consultant, **25%**),
  whose label is now expressible while `business-development-manager`
  keeps the row it was pinned to.

**A4 — the coverage baseline is re-stated. DONE.** The live vault holds
**44 job records**, of which **3 carry a function** (JOB-046, JOB-048,
JOB-049, all `ict-product-manager`), counted read-only on 2026-10-16.
"1 of 42" is corrected in FIXES.md (the batch's own "could not verify"
list) and the denominator in PROJECT.md's CAREER-31 bullet; the golden
set's own "42 jobs" stands where it refers to the 42 rows it labelled.

**A5 — the runbook says what a re-run does. DONE.**
[docs/runbooks/seed-function-facet.md](docs/runbooks/seed-function-facet.md)
now records 40 values (10 ESCO-backed, 30 local extensions, 5 of them
permanently unmapped), the update rules, the keyword-removal caveat, and
the real output of a run against a **copy** of the live vault's
`tags.yaml` (the live vault itself was only read, never seeded):

```
added 12 ids: [...]      # the golden set's concepts and local extensions
updated 7 ids: ['ict-product-manager', 'software-developer', 'ict-security-manager',
 'ict-project-manager', 'marketing-manager', 'sales-manager', 'compliance-officer']
```

Those 7 are exactly what the old skip would have dropped: 5 ESCO
identities and 2 keyword sets the prompt could not otherwise see.

Files: `careeros/data/esco_occupations.yaml`, `careeros/vault.py`,
`tests/test_function_facet.py`,
`docs/runbooks/seed-function-facet.md`, `PROJECT.md`.

---

### B. Owner decisions

**B1 — a posting's headcount is stored as company size evidence. DONE.**
The count already stayed on the job as the raw `employee_count`; what was
missing is that nothing carried it any further. `careeros.enrich.
enrich_company` now also returns `employee_count` and
`employee_count_evidence` (`{count, job_id, posted_date}`), which
`regenerate_company` merges into the company's `enrichment` block on
every job save — and `enrichment['employee_count']` is exactly what the
capability's zero-network promotion tier reads
(`org_intake.enrich.promote_aggregated_size`, rule 9/R4). Nothing in the
product had ever written that key, so that tier was dead code here: a
company whose only size signal was one of its own postings showed
nothing, which is the reviewer's note.

- **Which count**, when postings disagree: the most recently posted one;
  failing any dated posting, the first that states one. That is the rule
  [enrichment evidence](docs/decisions/enrichment-evidence.md) already
  settled for dated Wikidata statements, and it supersedes the draft
  proposal to refuse undated evidence. A value that does not read as a
  positive integer headcount is absent evidence, never a zero.
- **Evidence, not a write.** The aggregation never touches `size_class`
  itself. A later size run derives the class through the unchanged rules:
  fill-empty-only, an owner-provenanced or populated field is never
  overwritten, and a count that contradicts a stored class or a legacy
  range raises `FLAG_SIZE_INCONSISTENT` instead of writing.
- **No resurrection of the retired scales.** Neither `size_range` nor the
  legacy `size` string is written anywhere on this path; both are
  asserted null in the tests.
- **One gate found while building it**, because Section 1's field-group
  matrix gives a non-employer no size: `regenerate_company` must *delete*
  this evidence when a company is re-kinded away from `employer`, exactly
  as it already deletes the nested `enrichment.sectors` rollup. Skipping
  it from new derivation would have left the old value showing forever.
- **The pinned JSON contracts moved**, since the company `enrichment`
  block is part of them: `tests/test_api_companies.py`,
  `test_api_experiences.py`, `test_api_jobs.py`, `test_api_taxonomy.py`
  gained the two keys in nine pinned shapes. `vault.validate_enrichment`
  validates them (a positive integer or null; an object or null), with
  six new cases in `test_enrichment_validation`.

Tests: `test_enrich.py::test_a_posting_headcount_becomes_company_size_evidence`,
`::test_an_undated_posting_headcount_is_evidence_when_no_dated_one_is`,
`::test_an_unreadable_posting_headcount_is_absent_evidence` (6 cases),
`::test_a_posting_headcount_leaves_the_retired_size_scales_alone`,
`::test_a_non_employer_keeps_no_posting_headcount_evidence`, and the two
end-to-end ones through `POST /api/companies/<id>/retry` in
`test_sectors.py` — one deriving `medium` from a posting's 120 employees
with no network call (the promotion tier reports `matched` and every
other signal `not-attempted`), one asserting that a count contradicting a
stored class flags instead of writing. `test_aggregation` and
`test_empty_and_legacy_values` gained the two keys, since they pin the
aggregate exactly.

Files: `careeros/enrich.py`, `careeros/vault.py`, `tests/test_enrich.py`,
`tests/test_sectors.py`, the four contract test files, `docs/schemas.md`,
`docs/company-enrichment.md`, `docs/surfaces/companies.md`, `PROJECT.md`.

**B2 — `careeros/web/screenshot.py` is deleted. DONE.** Gone from disk.
`verify.py` was its only importer and went with CAREER-32; a grep for
`screenshot`, `render_page_png`, `chromium_available` and `CHROMIUM_PATH`
across the repo now finds no reference to the module in any code, test or
doc. The two mentions in FIXES.md are rewritten (the "left in place,
flagged" note and the parent's open decision). AGENTS.md needed no edit:
its component gate asks for "a screenshot of the densest piece of the
surface" and never named this module, so what is retired is the helper,
not the gate.

---

### C. Review corrections

**C1 — `_drop_retired_size_range` docstring. DONE.** "The intake cascade
still derives the pair, because `org_intake.classify.derive_size` is a
shared capability … and a second consumer may want the range" stopped
being true in the same batch that wrote it: CAREER-33 made `derive_size`
answer with the class alone. The docstring now says nothing derives a
range any more, and says why the gate stays anyway — it guards the
payload rather than a producer, so a legacy translation, an owner PUT or
a signal nobody has written yet still crosses it.

**C2 — `docs/surfaces/companies.md`. DONE.** Both sentences in the
paragraph under the batch's new one were false. The posting bucket does
not "defer to a stored `size_class` when `fill_company_metadata` decides
whether to fill the legacy `size` field" — there is no bucket and that
fill is gone; and the legacy `size` field is not "still written when a
posting states a size", because nothing writes it. Replaced with what is
true, plus the B1 evidence path.

**C3 — Playwright drives the Vite dev server. DONE.** Corrected in
FIXES.md (CAREER-32) and PROJECT.md's open question:
`frontend/playwright.config.js` starts `npm run dev` as its `webServer`,
so the suite never loads `frontend/dist`. The gap note is kept and
widened rather than softened: it is not only that the backend is mocked,
it is that the bundle Flask actually serves is loaded by no automated
check, so a break that appears only in a production build is invisible
too. The owner click-test covers both. (README.md already described the
dev server correctly.)

**C4 — "four existing entries gained keywords" → five. DONE.** The
sentence listed five and counted four. Corrected in FIXES.md and
PROJECT.md; the seed file's own header says five.

**C5 — audit denominator 44, not 42. DONE.**
`docs/audits/redaction-residue.md` now opens on 44 job records and says
which two were missing (JOB-048, JOB-049, neither affected). Every
per-record finding was re-checked against the 44 read-only on 2026-10-16
and stands: 6 empty `description`, 7 empty `summary`, 8 distinct records,
the same ids as before.

---

### What the parent still needs to do

1. **Move the submodule pin** — unchanged from the batch above, and this
   round touched no capability code.
2. **Seed the function facet** in the live vault: the run adds 12 ids and
   updates 7, per the runbook. Nothing in this round was run against
   `/root/career-os`; it was read (record counts, function coverage) and
   its `tags.yaml` was copied out to prove the seed numbers.
3. **Run the re-reads** the audit lists, then re-count function coverage
   against the 3-of-44 baseline above.

### What this round could not verify

- **Whether the wider vocabulary raises function coverage.** Still the
  owner's re-read plus a count; the baseline is now recorded honestly.
- **The ESCO identity of the other 25 entries.** 10 were verified because
  the golden set uses them. The rest keep `esco_uri: null` and an `isco`
  that is the seed file's own reading, and seed as local extensions with
  the code cleared, so nothing claims a roll-up it has not earned. The
  runbook's open question says so.
- **That the local extensions are the right labels.** They are the
  owner's own words from the golden set; the ESCO API can only say that
  no concept carries those URIs, which it does.
