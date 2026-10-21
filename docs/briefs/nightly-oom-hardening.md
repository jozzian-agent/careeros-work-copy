# Task brief: nightly pipeline OOM hardening

Date: 2026-10-21. Author: Hermes (orchestrator). Builder: Claude Code.

## Problem (verified from logs)

The nightly fetch pipeline OOMs on large providers and, worse, the kernel OOM
killer kills `hermes-gateway` (the largest process in the slice) instead of the
runaway script — taking down the user's Telegram bot mid-conversation.

Evidence:
- `data/nightly/nightly_2026-10-20.log` line ~3975: greenhouse fetch reached
  tenant 2294/2319 then `nightly_pipeline.sh: line 42: 1348870 Killed
  .venv/bin/python scripts/run_ats_fetch.py --provider "$p" fetch`.
- Journal: `hermes-gateway.service: Failed with result 'oom-kill'` on Oct 12
  and Oct 20 05:00. VM has 3 GiB RAM; gateway RSS ~1.3 GiB.
- No `nightly_2026-10-21.log` at all: the pipeline died with the OOM and no
  log file was created for the run that never completed.
- Root disk at 75% (6.4G free); `data/ats` snapshots are 6.1G and
  never-pruned by design.

## Root cause in code

`scripts/run_ats_fetch.py::cmd_fetch` accumulates every tenant's full result
dict — including all mapped postings — in a `results` dict for the whole run,
and only calls `store.record_run(...)` after the final tenant. For greenhouse
(2319 tenants) and ashby (3019) this holds hours' worth of postings + snapshot
data in RAM. Memory grows linearly with tenant count.

## Required changes (all three, in one round)

### 1. Flat-memory fetch loop (the real fix)

In `cmd_fetch`, stop retaining per-tenant results for the whole run. Fold each
tenant into the store incrementally:
- Call `store.record_run` (or an equivalent incremental path via
  `careeros/feeds/store.py`) per tenant or per small batch (e.g. 50 tenants),
  immediately after fetching it, so the mapped postings can be released.
- The final per-run summary (`_print_run`, `store.record_run` return values,
  runs.json entry) must be assembled from small per-tenant summaries only —
  never from retained posting lists.
- Preserve semantics exactly: "a failed fetch never closes anything"
  (non-ok `fetch_status` tenants skipped), run ids, snapshot writes,
  closure/misses accounting, the `failures` map, and the printed run report.
- If `record_run` batching changes run-record shape, keep `runs.json` entries
  backward-compatible (same keys; `_print_run` output unchanged).

Acceptance: run the fetch against a fixture/copy of a small provider (lever,
83 tenants) and show peak RSS stays flat vs tenant count (e.g. via
`/usr/bin/time -v` or a sampling wrapper). Add/adjust tests under `tests/`
covering incremental fold: ok tenant folds immediately; failed tenant is not
counted; summary matches old whole-run behavior on a fixture.

### 2. systemd-run memory caps in nightly_pipeline.sh (defense in depth)

Wrap each long-running python invocation (fetch, classify, geocode, report —
at minimum fetch) with:

    systemd-run --scope --quiet -p MemoryMax=1200M -p MemoryHigh=900M <cmd>

`systemd-run --scope -p MemoryMax=...` is verified working on this host.
Rationale: a runaway process now gets OOM-killed *inside its own scope* and
can never kill hermes-gateway. If `systemd-run` is unavailable (e.g. tests),
fall back to running the command directly. Keep the 1200M/900M values as
variables at the top of the script so they're tunable.

### 3. Pipeline resilience + visible logs

In `scripts/nightly_pipeline.sh`:
- Create the nightly log file at pipeline start (before any provider), so a
  total failure still leaves `nightly_<date>.log` with an error line.
- One provider's fetch failing must not abort the remaining providers, the
  export, or classify/report steps. Track failures and print a final
  `== nightly finished, fails: ... ==` line (the Oct 19 log already shows this
  pattern — keep it) listing every failed stage.
- Add a disk watermark check at pipeline start: if free space on the data
  filesystem < 3G, print a loud WARNING line into the log and continue (do
  not abort).
- Add snapshot compression: a new step (script or subcommand, your choice —
  follow repo conventions) that zstd-compresses posting snapshot JSON files in
  `data/ats` older than 30 days, and make the snapshot reader
  (`store.write_posting_snapshot` / whatever loads snapshots) transparently
  read `.zst`. Verify no reader path breaks on both compressed and
  uncompressed snapshots. If transparent read proves invasive, stop and leave
  an honest note in the brief's follow-ups instead of half-building it.

## Constraints

- Repo conventions in AGENTS.md / PROJECT.md apply: minimum new elements,
  tests beside code, no scope creep beyond the three items.
- Do not run the full nightly pipeline as a test (hours of network traffic).
  Use fixtures, `--provider lever` against a temp copy of data, or unit tests.
- Do not touch `data/ats` production snapshots except through the
  compression step's own dry-run flag; include a `--dry-run` for it.
- Commit when green with a clear message. Do NOT push.

## Verification gates (builder must run and report)

1. Full test suite green.
2. Lever-sized fetch on a data copy: peak RSS reported, run summary identical
   in shape to previous runs.
3. `systemd-run` wrapper demonstrated on one command (can be `true`).
4. Compression step dry-run on `data/ats`: lists candidate files, changes
   nothing; then a real run limited to a single test tenant directory, with
   read-back verification of one compressed snapshot.
5. Pipeline log file created even when the first stage fails (simulate with a
   bogus provider).

## Follow-ups

Written by the builder, 2026-10-21. All three required changes are in and
every gate below ran; these are the deviations, the findings and what is
deliberately left open.

**Deviations from the brief, each deliberate.**

- **The compression step is a dry run by DEFAULT and takes `--apply`**,
  rather than carrying a `--dry-run` flag. Repo convention (the brief's
  own Constraints): `scripts/migrate_*.py` and `flag_size_review.py` all
  write nothing unless given `--apply`. Gate 4's dry run is therefore
  the plain command with no flag.
- **It is a subcommand, not a script**: `run_ats_fetch.py compress`,
  beside `export`, because it needs the same `--root` / `--provider` /
  `--all-providers` wiring the runner already has. One new element
  instead of a script with its own command line.
- **It packs posting snapshots only.** The raw FEED snapshots are
  already gzipped (`.xml.gz`, `.json.gz`) and are 3% of the bulk —
  11 MB against 325 MB for lever. zstd would still beat gzip on them;
  worth measuring only if the disk gets tight again.
- **`zstandard==0.25.0` is a new dependency.** Neither the `zstd` CLI
  nor any zstd module was on the host, so "zstd-compress" could not be
  done with what was installed. The wheel is in `.wheelhouse` as well,
  so the offline install still works. It is imported lazily, so a
  checkout whose venv predates it keeps working on plain snapshots.
- **`--all-providers` covers `data/personio` too**, not only
  `data/ats/*`, because it is the same kind of staging store and holds
  16 028 of the 236 507 packable snapshots.
- **One adjacent fix, flagged rather than built quietly.** The old
  script's "ideaai unreachable" abort did `exit 1` from inside the block
  that is redirected to the log, so the Telegram summary was EMPTY on
  exactly the night it mattered — the runbook's own failure table says
  the owner should see `ABORTED - ideaai unreachable`. The preflight now
  skips fetch, export and classify as one (the same "nothing
  half-runs" rule) and falls through to the summary line, so stdout says
  `FAILED: llm-unreachable`. The runbook's table is updated to match.

**Findings the owner should decide on.**

- **`MemoryHigh` is throttling, not a limit, and it turns a kill into a
  stall.** Measured on this host: a leg held at `MemoryHigh` with swap
  allowed is pushed into the host's 1 GiB of swap and crawls; with
  `MemorySwapMax=0` it still stalls rather than dying — over 3 minutes
  and still going, where `MemoryMax` alone ends it in under a second.
  `MemorySwapMax=0` was therefore added to the scope (a third tunable),
  and `MemoryHigh` is kept at the briefed 900M because a throttled leg
  cannot push the gateway out of memory, which is what the cap is for.
  **Open:** nothing puts a wall-clock limit on a stalled leg. Either wrap
  each leg in `timeout`, or run with `NIGHTLY_MEMORY_HIGH=` (empty) so a
  runaway dies at `MemoryMax`. A cap is not a timeout; one line in the
  script either way, and it is the owner's call.
- **A killed run is no longer all-or-nothing.** Folding each tenant as it
  is fetched means a run that dies half way has recorded the tenants it
  got through. That is safe and idempotent — the retry re-fetches them
  under a new run id, snapshots are content-addressed, and a posting seen
  again cannot close — but `runs.yaml` gets no entry for the dead run, so
  "what did last night actually fetch?" is answered by the log and the
  per-tenant state rather than by one run entry.
- **The peak is now set by the biggest single tenant, and PyYAML is
  why.** With the loop flat, the real lever fetch (83 tenants, 10 130
  postings, on a copy of the store) peaks at **779 MiB** — against
  **915 MiB** for the same fetch on the old loop, which is already over
  the briefed `MemoryHigh=900M`. ~640 MiB of the 779 is one file: `state/boxlunch.yaml`, 15.7 MB and 4 674
  postings, parsed by the pure-python YAML loader. That is inside
  `MemoryMax=1200M` but only 86% of `MemoryHigh=900M`, so a tenant that
  grows another sixth would start being throttled. The cheap answer is
  already installed: loading that same file with `yaml.CSafeLoader`
  takes **4.5 s and 436 MiB** against **20.6 s and 630 MiB**. Switching
  `store.read_yaml` / `store.write_yaml` to the C loader and dumper is a
  two-line change that cuts both the peak and the run time, and it is
  outside this brief, so it is left for the owner to accept or cut.
  Biggest state file per provider today: lever 15.7 MB, greenhouse
  8.5 MB, smartrecruiters 3.2 MB, ashby 2.9 MB, recruitee 1.1 MB.
- **The 30-day cutoff is a guess, not a measurement.** Nothing has yet
  needed to read a snapshot older than its own day's run. On today's
  store nothing is 30 days old (the oldest is 2026-10-17), so the first
  night that frees anything is 2026-11-16. Shorten `--older-than` if the
  disk needs it sooner; the step is lossless either way.
- **Nothing prunes, still.** `data/ats` is 6.1 G and compression buys
  roughly 4x on the 3.76 G of posting snapshots. It does not change the
  slope, only the intercept.
