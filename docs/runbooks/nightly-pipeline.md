# Nightly pipeline: fetch at 19:00, classify overnight

The one place that says what runs every night, when, how long it takes,
where the outputs land, and how to run any of it by hand. Added for
CAREER-57's follow-up (owner decision 2026-10-18: "B now, A as the
scheduled next step").

## The schedule

| When (Swiss local) | What | Where it runs | Expected duration |
|---|---|---|---|
| 19:00 | `scripts/nightly_pipeline.sh` — fetch all six ATS providers, export the pool, classify it with the local LLM | Hermes cron job `careeros-nightly-pipeline` on 192.168.1.203 (this host) | ~40-90 min measured (see below) |
| ~19:05+ | Telegram message with the one-line result and any failures | delivered by the cron job | instant |

There is exactly **one** scheduled job for this pipeline. It is a
`no_agent` cron job: the scheduler runs the script and delivers its
stdout verbatim — no LLM tokens are spent on the run itself (the
classification LLM calls go to the owner's own hardware, which is also
free).

## What the script does, in order

1. **Preflight:** pings the local LLM host (`http://192.168.1.10:11434`,
   the "ideaai" box, model `qwen3:30b-a3b`). If it is down the whole run
   aborts **before** fetching — a fetch with no classification half-done
   is worse than nothing done.
2. **Fetch**, one provider at a time: personio, greenhouse, lever, ashby,
   recruitee, smartrecruiters — each through
   `scripts/run_ats_fetch.py --provider <p> fetch`. One global rate
   limit of one request a second and robots.txt respected (both are
   built into the runner). A provider failing does not stop the others;
   failures are collected and reported.
3. **Export** the multi-provider golden-set pool for the day:
   `run_ats_fetch.py --provider personio export --all-providers --day <date>`
   → `data/ats/exports/golden_set_pool_<date>.yaml`.
4. **Classify** the pool through the local LLM layer:
   `run_classification.py --pool <today's pool> --layer llm --out data/classification/run_<date>.yaml`.
   The rules layer runs first inside the same command (it is free and
   deterministic); the LLM only answers the fields rules left open.
   `CLASSIFY_LLM_NATIVE=1` is exported by the script and is **required** —
   see `local-llm-optimisation.md` for why (10x speed difference).

Every step is idempotent: re-running any of them the same day overwrites
only derived files, never immutable snapshots (fetch writes a new
snapshot only when a posting's content hash changed).

## Outputs

| File | What it is |
|---|---|
| `data/nightly/nightly_<date>.log` | full verbose log of every step |
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

## Measured durations (2026-10-18, ideaai: Lenovo IdeaPad Pro 5, CPU-only)

- One LLM classification call (realistic 395-token prompt, JSON out):
  **mean 19.0 s** over a 10-posting live run (min 15.5, max 27.0),
  mean 1 106 tokens per call. This is the `--layer llm` path with
  `CLASSIFY_LLM_NATIVE=1`; the same call through the OpenAI-compat
  endpoint without it takes ~106 s and often times out.
- The current pool is 204 postings → classification ≈ **65 minutes**,
  worst case (all at the 27 s max) ≈ 92 minutes. Comfortably inside the
  overnight window.
- Fetch duration depends on how many tenants are live; the 1 req/s
  politeness cap dominates. Personio's store alone is ~2 500 tenants, so
  if fetch time becomes a problem, `--sample` or `--max-tenants` are the
  knobs — do not raise the rate limit.

Re-measure after any model or prompt change:
`scripts/run_classification.py --pool <pool> --layer llm --limit 10 --dry-run`

## Running it by hand

```bash
cd /root/work/careeros-dashboard
scripts/nightly_pipeline.sh            # the whole thing, same as cron
# or just one leg:
CLASSIFY_LLM_NATIVE=1 .venv/bin/python scripts/run_classification.py \
    --pool data/ats/exports/golden_set_pool_$(date +%F).yaml \
    --layer llm --out /tmp/manual_run.yaml
```

## Failure modes and what to do

| Symptom | Cause | Fix |
|---|---|---|
| `ABORTED - ideaai unreachable` | the local LLM box is off/asleep | start Ollama on 192.168.1.10; re-run the script by hand |
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

## The cron job (record)

Hermes cron job **`careeros-nightly-pipeline`, id `488ba0fa1330`**,
`no_agent: true`, script `~/.hermes/scripts/careeros_nightly.sh` (a
one-line wrapper that execs `scripts/nightly_pipeline.sh`), schedule
`0 17 * * *`, delivery to the owner's Telegram. Created 2026-10-18.

**DST caveat (action needed twice a year):** the host clock is UTC and
the schedule is fixed UTC, so `0 17 * * *` = 19:00 CEST in summer but
**18:00 CET in winter** — one hour early after the clocks go back (late
October) until they go forward again (late March). The classification
finishes overnight either way, so this is cosmetic, not breaking. To hold
19:00 Swiss year-round, change the cron expr at each DST transition:
`0 17 * * *` (CEST, Mar-Oct) / `0 18 * * *` (CET, Oct-Mar).
