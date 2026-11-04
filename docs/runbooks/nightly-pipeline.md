# Nightly pipeline: fetch at 19:00, classify overnight

The one place that says what runs every night, when, how long it takes,
where the outputs land, and how to run any of it by hand. Added for
CAREER-57's follow-up (owner decision 2026-10-18: "B now, A as the
scheduled next step"). Hardened 2026-10-21 after two nights of OOM
kills; what changed is in "Memory, disk and the log" below.

## The schedule

| When (host clock, UTC) | What | Where it runs | Expected duration |
|---|---|---|---|
| 19:00 UTC (20:00 Swiss in winter, 21:00 in summer) | `scripts/nightly_pipeline.sh` — fetch all six ATS providers, export the pool, classify it with the local LLM | Hermes cron job `careeros-nightly-pipeline` on 192.168.1.203 (this host) | ~10 h on the current pool (see "Measured durations" below) |
| on completion, next morning | Telegram message with the one-line result and any failures (the cron job delivers the script's stdout when it exits, so a 19:00 UTC start that finishes around 05:00 UTC delivers around 05:00 UTC) | delivered by the cron job | instant |

There is exactly **one** scheduled job for this pipeline. It is a
`no_agent` cron job: the scheduler runs the script and delivers its
stdout verbatim — no LLM tokens are spent on the run itself (the
classification LLM calls go to the owner's own hardware, which is also
free).

## What the script does, in order

1. **Open the day's log** (`data/nightly/nightly_<date>.log`) and write
   the header into it, before anything that can fail. A run that dies in
   its first second still leaves the day's file saying so.
2. **Check the disk** on the data filesystem. Under 3 G free it prints a
   loud `WARNING` and **continues** — a full disk is the owner's call,
   and a night skipped over a warning is a night of postings lost.
3. **Compress** the posting snapshots nothing has touched for 30 days:
   `run_ats_fetch.py --provider personio compress --all-providers
   --older-than 30 --apply`. First because it frees the disk the rest of
   the night writes to, and it runs even on a night that then aborts.
   Lossless and verified per file; see "Memory, disk and the log".
4. **Preflight:** pings the local LLM host (`http://192.168.1.10:11434`,
   the "ideaai" box, model `qwen3:30b-a3b`). If it is down, the fetch,
   the export and the classification are **all three skipped** — a fetch
   with no classification half-done is worse than nothing done — and the
   run still writes its log and its Telegram line.
5. **Fetch**, one provider at a time: personio, greenhouse, lever, ashby,
   recruitee, smartrecruiters — each through
   `scripts/run_ats_fetch.py --provider <p> fetch`, up to 3 attempts with
   60/120 s backoff. One global rate limit of one request a second and
   robots.txt respected (both are built into the runner). A provider
   failing does not stop the others, the export or the classification;
   failures are collected into the one `fails:` line.
6. **Export** the multi-provider golden-set pool for the day:
   `run_ats_fetch.py --provider personio export --all-providers --day <date>`
   → `data/ats/exports/golden_set_pool_<date>.yaml`.
   The export drops demo-tenant rows and open applications (CAREER-133,
   `export.hygiene_skip`) and tallies every drop in the file's own
   `skipped_reasons`; see `docs/audits/pool-in-area-and-hygiene.md` for
   the in-area rule and the measured junk.
7. **Classify** the pool through the local LLM layer:
   `run_classification.py --pool <today's pool> --layer llm --previous <latest run_*.yaml>
   --out data/classification/run_<date>.yaml`.
   The rules layer runs first inside the same command (it is free and
   deterministic); the LLM only answers the fields rules left open.
   Since CAREER-138 the job family is one of those fields on EVERY
   posting — the rules layer no longer decides it — and `--previous`
   (the latest run file that is not tonight's own output) keeps the cost
   down: postings whose family a previous run already settled are
   carried into tonight's run file unchanged, and the model only sees
   the new postings and the ones whose family is still unknown. A night
   with nothing new and nothing unknown makes zero model calls and still
   writes the run file. The first night after CAREER-138 was the one-off
   re-run of every still-unknown family (2026-11-03: 797 model calls,
   ~4.8 h — see "Measured durations"); every later night classifies only
   what is new.
   `CLASSIFY_LLM_NATIVE=1` is exported by the script and is **required** —
   see `local-llm-optimisation.md` for why (10x speed difference).
8. **Sync to prod**, only with `SYNC_TO_PROD=1` and only after a night
   with no failures: `deploy/sync_vault_to_prod.sh <date>`, which pushes
   the pipeline-owned subset into an incoming generation on the VPS
   ([deploy runbook](deploy-runbook.md)). Off by default, so a LAN-only
   install never runs it. The day is passed as an argument because the
   night can cross midnight UTC. A sync failure adds `sync` to the
   `fails:` line and the exit code and changes nothing this script wrote.

Every step is idempotent: re-running any of them the same day overwrites
only derived files, never immutable snapshots (fetch writes a new
snapshot only when a posting's content hash changed).

## Memory, disk and the log (CAREER-93, 2026-10-21)

The 2026-10-20 run was killed mid-fetch and took the owner's Telegram bot
with it: this VM has 3 GiB, `hermes-gateway` holds ~1.3 GiB of it, and
the kernel's OOM killer picks the biggest process in the slice rather
than the one that is growing. Three things answer that, and the first is
the only real fix.

1. **The fetch loop is flat in memory.** It used to hold every tenant's
   mapped postings until the last tenant was done, so memory grew with
   the tenant count — greenhouse (2 319 tenants) and ashby (3 019) were
   holding hours of postings. Each tenant is now folded into the store
   the moment it is fetched and only its numbers are kept
   (`scripts/run_ats_fetch.py`, `_tenant_summary`). Measured over a
   synthetic Personio feed, 40 postings a tenant: **44.6 MiB peak RSS at
   25 tenants, 45.7 MiB at 400** (before the change: 49 MiB and
   242.7 MiB — linear).
   One consequence worth knowing: a run that dies half way has now
   folded the tenants it got through, instead of nothing. That is safe
   and idempotent — the retry fetches them again under a new run id,
   snapshots are content-addressed, and a posting that was seen again
   cannot close — but a killed run is no longer all-or-nothing.
   **What sets the peak now is the biggest single tenant, not the run.**
   The real lever fetch (83 tenants, 10 130 postings, on a copy of the
   store) peaked at **779 MiB**, against **915 MiB** for the same fetch
   on the old loop — a small gap, because lever has only 83 tenants and
   its peak is one tenant's state file rather than the accumulation; the
   accumulation is what grew with greenhouse's 2 319 and ashby's 3 019.
   ~640 MiB of the 779 is one file:
   loading `state/boxlunch.yaml` (15.7 MB, 4 674 postings) through
   PyYAML costs that much on its own. The biggest state file per
   provider today is lever 15.7 MB, greenhouse 8.5 MB, smartrecruiters
   3.2 MB, ashby 2.9 MB, recruitee 1.1 MB. That fits under the cap and
   not by a wide margin; the open questions below say what would buy
   room.
2. **Every python leg runs in its own systemd scope with a memory cap**
   (`MemoryMax=2000M`, `MemoryHigh` off, `MemorySwapMax=0`). A runaway
   leg is dealt with inside its own scope and can never be answered by
   killing the gateway. If `systemd-run` cannot give a scope (a
   container, a test), the leg runs plainly and the log says
   `WARNING: systemd-run gave no scope` rather than looking capped.
   **History:** the caps were sized 2026-10-12 for a 3 GiB VM
   (`MemoryMax=1200M`, `MemoryHigh=900M`). Measured 2026-10-21,
   `MemoryHigh` is throttling, not a limit: a leg held there with no
   swap *stalls* rather than dying (over 3 minutes and still going,
   where `MemoryMax` alone kills it in under a second). The VM was
   upgraded to 8 GiB on 2026-10-22 (worst measured leg: 779 MiB), so
   `MemoryHigh` was dropped — a runaway leg now dies at `MemoryMax`
   instead of stalling — and the hard cap gained headroom. Set
   `NIGHTLY_MEMORY_HIGH=900M` to restore the old throttling behaviour.
3. **The snapshots stop growing without bound.** Nothing prunes
   `data/ats` by design — the snapshots are the golden set's evidence —
   so step 3 compresses instead of deleting. `compress` is a dry run
   unless given `--apply`, it replaces a file only after reading its
   `.zst` copy back byte for byte, and every reader goes through
   `store.stored_path`, so a packed snapshot and a plain one are the same
   snapshot to the pool export, the classification and the next fetch.
   Measured 2026-10-21 on one lever tenant's 58 snapshots: 1.2 MB →
   0.3 MB (4.1x). The whole of `data/ats` plus `data/personio` is
   236 507 posting snapshots and 3.76 GB, so the first night that packs
   month-old files will free most of it.

### Environment overrides

The defaults are what cron runs; each of these is read at the top of the
script and is there for a by-hand run or a test.

| Variable | Default | What for |
|---|---|---|
| `NIGHTLY_PYTHON` | `.venv/bin/python` | the interpreter every leg runs under |
| `NIGHTLY_DATA` | `data` | where the log, the pool and the classification land |
| `NIGHTLY_PROVIDERS` | the six | run one provider's fetch only |
| `NIGHTLY_OLLAMA` | `http://192.168.1.10:11434` | the LLM host the preflight pings |
| `NIGHTLY_ATTEMPTS` / `NIGHTLY_BACKOFF` | `3` / `60` | fetch retries and the backoff step in seconds |
| `NIGHTLY_MEMORY_MAX` / `NIGHTLY_MEMORY_HIGH` / `NIGHTLY_MEMORY_SWAP_MAX` | `2000M` / off / `0` | the per-leg cap; set `MEMORY_HIGH=900M` to re-enable throttling |
| `NIGHTLY_DISK_FLOOR_MB` | `3072` | the free-space watermark that warns |
| `NIGHTLY_COMPRESS_AFTER` | `30` | days before a posting snapshot is packed |
| `SYNC_TO_PROD` | `0` | `1` chains the prod sync onto a clean night (step 8); the sync's own variables are in the [deploy runbook](deploy-runbook.md) |

## Outputs

| File | What it is |
|---|---|
| `data/nightly/nightly_<date>.log` | full verbose log of every step, created before the first one |
| `data/ats/exports/golden_set_pool_<date>.yaml` | the day's sampling pool |
| `data/classification/run_<date>.yaml` | every posting's classification, per-field evidence, confidence, and per-call latency/token metrics |
| Telegram (this owner) | one summary line + the model-calls/review stats |

Nothing in this pipeline writes to the vault. The vault is the owner's;
staging output stays in this repo's `data/`.

Putting a day's pool INTO a vault is a separate, owner-gated step and is
not scheduled: `scripts/import_pool_to_vault.py`, which reads the two
files above and writes the postings as universe jobs
([runbook](import-pool.md)). It is deliberately not a cron line — it
holds the vault write lock for the length of the import and the owner
takes a vault backup before running it.

## Measured durations

2026-11-03 night (pool of 797 postings, log `data/nightly/nightly_2026-11-03.log`,
run 19:00 → 04:57 the next day, host clock = UTC, ~10 h total):

- Fetch legs: personio 43 min, greenhouse 97 min, lever 6 min, ashby
  78 min, recruitee 8 min, smartrecruiters 47 min; export 29 min.
- Classification: 797 model calls, 0 failed, mean 23.3 s per call,
  4 h 48 min total — `CLASSIFY_LLM_NATIVE=1`, `qwen3:30b-a3b` on the
  local LLM host (192.168.1.10). This night was the one-off CAREER-138
  re-run of every still-unknown family; a night with `--previous`
  carrying settled families classifies only what is new.
- The 2026-10-18 measurements this section used to quote (mean 19.0 s
  per call on a 204-posting pool, ≈65 min classification) were on the
  same host and still describe a single call, but the pool is ~4x
  larger now and a full classify night is hours, not minutes.

Re-measure after any model or prompt change:
`scripts/run_classification.py --pool <pool> --layer llm --limit 10 --dry-run`

## Running it by hand

```bash
cd /root/work/careeros-dashboard
scripts/nightly_pipeline.sh            # the whole thing, same as cron
NIGHTLY_PROVIDERS=lever scripts/nightly_pipeline.sh   # one provider's fetch
# what the snapshots would compress to, writing nothing:
.venv/bin/python scripts/run_ats_fetch.py --provider personio compress \
    --all-providers --older-than 30
# or just one leg:
CLASSIFY_LLM_NATIVE=1 .venv/bin/python scripts/run_classification.py \
    --pool data/ats/exports/golden_set_pool_$(date +%F).yaml \
    --layer llm --out /tmp/manual_run.yaml
```

## The family suggestion queue (CAREER-131)

When no job family fits a posting at all, the model answers `unknown` and
proposes a short role name (since CAREER-138 it picks the CLOSEST family
whenever one reasonably fits, and proposes only when none does). The
proposals are collected in the run files (review reason
`llm_family_suggested`, counted in the run summary's `needs review`
line). The owner's loop:

```bash
cd /root/work/careeros-dashboard
# 1. what has been proposed, counted by distinct postings
.venv/bin/python scripts/family_suggestions.py list
# 2. approve one: it becomes a family in esco_occupations.yaml AND
#    occupation_families.yaml, and the pinned counts in the tests move
.venv/bin/python scripts/family_suggestions.py approve "Robotics Technician" \
    --code robotics-technician --label-de "Robotertechniker" --isco3 742
# 3. re-run ONLY the postings whose family was unknown (carries the
#    settled ones from the previous run, no second model call for them)
CLASSIFY_LLM_NATIVE=1 .venv/bin/python scripts/run_classification.py \
    --pool data/ats/exports/golden_set_pool_$(date +%F).yaml \
    --layer llm --previous data/classification/run_$(date +%F).yaml \
    --out data/classification/rerun_$(date +%F).yaml
```

`isco3` must be a CH-ISCO-19 minor group the taxonomy knows; `--isco4`
only when the code is already in the shipped ISCO-08 list (otherwise
confirm it later via the CAREER-29 route). An approved family starts as
`proposed` with no ESCO citation, exactly like the v2 additions.

## Failure modes and what to do

| Symptom | Cause | Fix |
|---|---|---|
| `FAILED: llm-unreachable` | the local LLM box is off/asleep | start Ollama on 192.168.1.10; re-run the script by hand |
| `Killed` in the log, or a leg that never returns | a leg hit its memory cap (see above) | read the run's own last tenant line; since 2026-10-22 `MemoryHigh` is off by default so a runaway leg dies rather than stalls — if you set `NIGHTLY_MEMORY_HIGH` and see a stall, unset it |
| `WARNING: only <N>M free` | `data/ats` is filling the root disk | run the compression step by hand with a smaller `--older-than`; it is lossless |
| `fetch <provider> FAILED` | provider API changed or tenant list stale | check `data/nightly/nightly_<date>.log`; a weekly `discover` pass may be needed (not scheduled yet — see below) |
| classify run shows `model calls: N (M failed)` | Ollama timeout or malformed answers | the run still completes; failed fields land in `needs_review` rather than silently missing. Check `local-llm-optimisation.md` |
| Telegram summary says FAILED but log looks fine | partial: one leg failed | re-run only that leg by hand; everything is idempotent |

## What is deliberately NOT scheduled

- **Weekly `discover`** (finding new tenants per provider, incl. Common
  Crawl): documented in `run_ats_fetch.py`'s header as a weekly shape,
  but not installed — tenant lists change slowly and the owner has not
  asked for it. Add it as its own cron line when feeds start missing
  companies.
- **`map`** (ATS platform-map rebuild): manual, feeds a decision, not a
  daily fact.
- Any cron on the vault itself: out of scope, the vault is written only
  by the dashboard's own flows.

## Open questions

- ~~**A stalled leg has no wall-clock limit.**~~ **Answered 2026-10-22:**
  `MemoryHigh` was dropped (the host gained RAM: 3 → 8 GiB), so a
  runaway leg now dies at `MemoryMax=2000M` instead of throttling into
  a stall. A `timeout` around each leg remains unadded — with the stall
  mode gone the only way a leg lingers is by legitimately working, and
  killing that would be worse.
- **The next memory bottleneck is PyYAML, and it is cheap to fix.**
  One tenant's state file dominates the peak (see above), and this venv
  already has libyaml: loading `state/boxlunch.yaml` with
  `yaml.CSafeLoader` takes **4.5 s and 436 MiB** against **20.6 s and
  630 MiB** for the pure-python loader. Switching `store.read_yaml` /
  `store.write_yaml` to the C loader and dumper is a two-line change
  that would cut both the peak and the run time, and it was outside this
  brief, so it is the owner's to accept. Sharding posting state below
  the tenant is the bigger, later answer.
- **Nothing packs the raw FEED snapshots.** They are already gzipped,
  which is why the compression step leaves them alone, but zstd would
  still beat gzip on them. Worth measuring only if the disk gets tight
  again after the first month of packing.
- **Whether 30 days is the right cutoff** is a guess, not a measurement:
  nothing has needed to read a snapshot older than the day's own run
  yet. Shorten it if the disk needs it; the step is lossless either way.

## The cron job (record)

Hermes cron job **`careeros-nightly-pipeline`, id `488ba0fa1330`**,
`no_agent: true`, script `~/.hermes/scripts/careeros_nightly.sh` (a
one-line wrapper that execs `scripts/nightly_pipeline.sh`), schedule
`0 19 * * *` (fires 19:00 UTC per `cron list`; see the DST record
below), delivery to the owner's Telegram. Created 2026-10-18.

**DST — record corrected 2026-11-04.** The intended fix (2026-10-22)
was `hermes config set timezone Europe/Zurich` plus schedule
`0 19 * * *`, so the pipeline would fire at 19:00 Swiss wall-clock
year-round. What the scheduler actually does today (raw `cron list`
output, 2026-11-04): schedule `0 19 * * *`,
`next_run_at: 2026-11-04T19:00:00+00:00` — it fires at **19:00 UTC**,
which is 20:00 Swiss in winter (CET) and 21:00 in summer (CEST). The
config line `timezone: Europe/Zurich` is set but is not taking effect
on this job; the most likely cause is the gateway caching the timezone
at startup — the config change only applies after a gateway restart —
and the measured 2026-11-03 run started at 19:00 host
time with the host clock on UTC, matching the +00:00 next-run. Until
either the gateway is restarted on the Zurich timezone or the schedule
is deliberately kept on UTC, treat **19:00 UTC** as the real fire time.
Historical caveat: before the 2026-10-22 fix, a fixed-UTC `0 17 * * *`
fired one hour early in winter (CET), which was judged cosmetic.
