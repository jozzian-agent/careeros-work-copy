#!/bin/bash
# The nightly pipeline: snapshot compression -> ATS fetch -> pool export ->
# local-LLM classification -> (optional) prod sync.
#
# The last leg is off unless SYNC_TO_PROD=1: it pushes the night's
# pipeline-owned output to the prod VPS (deploy/sync_vault_to_prod.sh,
# docs/runbooks/deploy-runbook.md). A LAN-only install never runs it.
#
# Runs at 19:00 Swiss time via the Hermes cron job that wraps this script
# (~/.hermes/scripts/careeros_nightly.sh). Since 2026-10-22 the Hermes cron
# timezone is explicitly Europe/Zurich and the schedule is "0 19 * * *", so
# DST shifts the UTC fire time, not the Swiss wall time. Every step is
# idempotent and safe to re-run; details, decisions and measured durations
# live in docs/runbooks/nightly-pipeline.md.
#
# Contract: verbose progress goes to the log file, ONLY a short summary goes
# to stdout, because stdout is delivered verbatim to Telegram by the cron
# runner. Empty stdout would mean silent.
#
# ONE RUN AT A TIME. The script takes an exclusive flock on
# `$DATA/nightly/.pipeline.lock` and refuses (never queues) if another run
# holds it: two runs would fetch into the same snapshots and export over the
# same day's pool. deploy/sync_vault_to_prod.sh takes that same lock SHARED
# while it counts and stages, so a push can never read a half-written tree.
#
# NOTHING HERE MAY TAKE THE HOST DOWN WITH IT (CAREER-93). On 2026-10-12 and
# 2026-10-20 the kernel answered a runaway fetch by killing the owner's
# Telegram bot, which was the biggest process in the slice (the VM had 3 GiB
# then; it was upgraded to 8 GiB on 2026-10-22 and the caps were re-sized:
# worst measured leg 779 MiB, so MemoryMax=2G keeps a runaway leg contained
# while leaving generous headroom, and MemoryHigh was dropped -- it stalled
# legs rather than ending them, an open question the runbook carried).
# Every python leg therefore runs in its own systemd scope with a memory cap,
# so a leg that runs away is dealt with inside its own scope and nothing else
# on the host is touched.
# The cap is the second line of defence; the first is that the fetch loop no
# longer grows with the tenant count (scripts/run_ats_fetch.py,
# `_tenant_summary`).
set -uo pipefail
# Resolve the repo from this script's own location, not a hardcoded path.
# A hardcoded `cd /root/work/careeros-dashboard` only works on the host that
# literally keeps the repo there; CI runners and any other checkout fail
# before a single stage runs. NIGHTLY_REPO overrides for odd layouts.
REPO="${NIGHTLY_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO" || { echo "nightly: repo missing"; exit 1; }

DAY=$(date +%F)

# Everything a test or a by-hand run needs to point somewhere else. The
# defaults are what cron runs; see the runbook's "Running it by hand".
PY="${NIGHTLY_PYTHON:-.venv/bin/python}"
DATA="${NIGHTLY_DATA:-data}"
PROVIDERS="${NIGHTLY_PROVIDERS:-personio greenhouse lever ashby recruitee smartrecruiters}"
OLLAMA="${NIGHTLY_OLLAMA:-http://192.168.1.10:11434}"
ATTEMPTS="${NIGHTLY_ATTEMPTS:-3}"
BACKOFF="${NIGHTLY_BACKOFF:-60}"          # seconds, times the attempt number
# Hard: the kernel ends the leg here, inside its own scope. Sized 2026-10-22
# for the 8 GiB VM (worst measured leg: 779 MiB, lever).
MEM_MAX="${NIGHTLY_MEMORY_MAX:-2000M}"
# Soft cap OFF by default since 2026-10-22: measured 2026-10-21, a leg held at
# MemoryHigh STALLS rather than dying (over 3 minutes and still going, where
# MemoryMax alone ends it in under a second). With 8 GiB on the host there is
# no longer a reason to trade a stalled leg for host safety -- a runaway leg
# now simply dies at MemoryMax. Set NIGHTLY_MEMORY_HIGH=900M (or any value)
# to re-enable the old behaviour.
MEM_HIGH="${NIGHTLY_MEMORY_HIGH:-}"
# No swap for a capped leg: with swap allowed, a leg over MemoryHigh is pushed
# into the host's 1 GiB of swap and crawls, which starves everything else on
# the box -- the opposite of what the cap is for.
MEM_SWAP="${NIGHTLY_MEMORY_SWAP_MAX:-0}"
DISK_FLOOR_MB="${NIGHTLY_DISK_FLOOR_MB:-3072}"   # warn (never abort) below this much free
COMPRESS_AFTER="${NIGHTLY_COMPRESS_AFTER:-30}"   # days before a snapshot is packed
# One run at a time, and one reader at a time. Held exclusive for the whole
# pipeline; deploy/sync_vault_to_prod.sh takes the same file SHARED while it
# counts and copies, so a sync can never read a tree this script is still
# writing. Released before the sync leg below -- the pipeline is finished by
# then, and a sync waiting on a lock its own parent holds would simply time
# out. Default path is derived from $DATA, so a test or by-hand run that
# points $DATA elsewhere gets its own lock, as does the sync.
LOCK="${NIGHTLY_LOCK:-$DATA/nightly/.pipeline.lock}"

LOG_DIR="$DATA/nightly"
LOG="$LOG_DIR/nightly_$DAY.log"
mkdir -p "$LOG_DIR" "$DATA/classification"

# The log file exists before anything can fail, so a run that dies in its
# first second still leaves the day's file saying so. The 2026-10-20 OOM left
# no nightly_2026-10-21.log at all, which is how a dead pipeline looked
# exactly like a pipeline that never ran.
echo "== nightly pipeline $DAY (host $(hostname), pid $$) ==" >>"$LOG" 2>&1

# Refuse, never queue: a second run while the first is still going would
# fetch into the same snapshots and export over the same day's pool. The
# log and the Telegram line both say so -- an empty stdout would read as
# silence, which is the one thing this script must never be.
if ! { : >>"$LOCK"; } 2>/dev/null; then
  echo "== nightly ABORTED: cannot open the lock $LOCK ==" >>"$LOG" 2>&1
  echo "CareerOS nightly $DAY: cannot open the lock $LOCK; nothing ran (log: $LOG)"
  exit 1
fi
exec 7>>"$LOCK"
if ! flock -n 7; then
  echo "== nightly ABORTED: another run holds $LOCK ==" >>"$LOG" 2>&1
  echo "CareerOS nightly $DAY: another run still holds $LOCK; this one did nothing (log: $LOG)"
  exit 1
fi

# Required, not optional: Ollama's OpenAI-compat /v1 endpoint silently drops
# think=False and qwen3:30b-a3b then spends ~100s "thinking" per posting.
# The native /api/chat path with think:false is ~10x faster and answers in
# the same JSON shape. See docs/runbooks/local-llm-optimisation.md.
export CLASSIFY_LLM_NATIVE=1

fails=""

# One home for the cap, and probed ONCE: a systemd-run that refuses for its own
# reasons (no systemd in a container, a test) must not read as every leg failing.
CAP_ARGS=(--scope --quiet -p "MemoryMax=$MEM_MAX" -p "MemorySwapMax=$MEM_SWAP")
[[ -n $MEM_HIGH ]] && CAP_ARGS+=(-p "MemoryHigh=$MEM_HIGH")
CAP=""
if systemd-run "${CAP_ARGS[@]}" -- true >/dev/null 2>&1; then
  CAP=yes
fi

capped() {   # capped <cmd...>: run it under the memory cap, or plainly
  if [[ -n $CAP ]]; then
    systemd-run "${CAP_ARGS[@]}" -- "$@"
  else
    "$@"
  fi
}

stage() {    # stage <name> <cmd...>: one capped step, timed, failure recorded
  local name=$1; shift
  local t0=$SECONDS
  if capped "$@"; then
    echo "-- $name ok in $((SECONDS - t0))s"
  else
    echo "-- $name FAILED in $((SECONDS - t0))s"
    fails="$fails $name"
  fi
}

{
  if [[ -n $CAP ]]; then
    echo "-- memory cap per python leg: MemoryMax=$MEM_MAX MemoryHigh=${MEM_HIGH:-off} MemorySwapMax=$MEM_SWAP"
  else
    echo "-- WARNING: systemd-run gave no scope; python legs run uncapped"
  fi

  # A watermark, not a gate: a full disk is the owner's call to make, and a
  # night skipped for a warning is a night of postings lost.
  free_mb=$(df -Pm "$DATA" | awk 'NR==2 {print $4}')
  if [[ -n ${free_mb:-} ]] && (( free_mb < DISK_FLOOR_MB )); then
    echo "WARNING: only ${free_mb}M free on the $DATA filesystem, under the ${DISK_FLOOR_MB}M floor - the snapshots will fill it; continuing anyway"
  else
    echo "-- disk: ${free_mb:-?}M free on the $DATA filesystem"
  fi

  # Housekeeping first: it frees the disk the rest of the night writes to,
  # and it is the one step that is worth running even on a night that
  # aborts. Compression changes how a snapshot is stored, never what it
  # says (careeros/feeds/store.py).
  echo "-- compress posting snapshots older than $COMPRESS_AFTER day(s)"
  stage compress "$PY" scripts/run_ats_fetch.py --provider personio compress \
    --all-providers --older-than "$COMPRESS_AFTER" --apply

  if ! curl -s --max-time 10 "$OLLAMA/api/tags" >/dev/null; then
    # Nothing half-runs: a fetch with no classification is worse than
    # nothing fetched, so the three legs below are skipped as one.
    echo "FATAL: local LLM host $OLLAMA unreachable - classification would fail for hours; skipping fetch, export and classify so nothing half-runs."
    fails="$fails llm-unreachable"
  else
    # Per-provider fetch with retry+backoff: 2026-10-19 smartrecruiters died in
    # 1s (transient endpoint blip) and cost the day 10 tenants' worth of postings.
    # Fetches are idempotent (frozen snapshots), so a retry is always safe.
    # One provider's failure stops that provider and nothing else.
    for p in $PROVIDERS; do
      t0=$SECONDS
      attempt=1
      # Owner granted the robots.txt exception for smartrecruiters on 2026-10-22
      # (their robots.txt allows only LinkedIn's crawler on the path their own
      # docs publish as public and unauthenticated; reasoning in
      # data/ats/TRIAL_REPORT.md). Without it the provider fails every night
      # and burns three pointless retries -- a policy block does not change
      # in 60s.
      fetch_extra=()
      if [[ "$p" == "smartrecruiters" ]]; then
        fetch_extra=(--robots-exception smartrecruiters)
      fi
      while true; do
        capped "$PY" scripts/run_ats_fetch.py --provider "$p" fetch "${fetch_extra[@]}"
        rc=$?
        if (( rc == 0 )); then
          echo "-- fetch $p ok (attempt $attempt) in $((SECONDS - t0))s"
          break
        fi
        if (( rc == 2 )); then
          # robots.txt policy refusal: retrying cannot change the answer.
          echo "-- fetch $p REFUSED by robots.txt (exit 2) - not retryable"
          fails="$fails fetch:$p"
          break
        fi
        if (( attempt >= ATTEMPTS )); then
          echo "-- fetch $p FAILED after $attempt attempt(s) in $((SECONDS - t0))s"
          fails="$fails fetch:$p"
          break
        fi
        backoff=$(( attempt * BACKOFF ))
        echo "-- fetch $p attempt $attempt failed; retrying in ${backoff}s"
        (( backoff > 0 )) && sleep "$backoff"
        attempt=$(( attempt + 1 ))
      done
    done

    echo "-- export pool (--all-providers)"
    stage export "$PY" scripts/run_ats_fetch.py --provider personio export \
      --all-providers --day "$DAY"

    POOL="$DATA/ats/exports/golden_set_pool_$DAY.yaml"
    if [[ -f $POOL ]]; then
      rows=$(grep -c '^- id:\|  - id:' "$POOL" || true)
      echo "-- classify llm layer over $POOL ($rows row(s))"
      stage classify "$PY" scripts/run_classification.py --pool "$POOL" --layer llm \
        --out "$DATA/classification/run_$DAY.yaml"
    else
      echo "-- POOL MISSING: $POOL - classify skipped"
      fails="$fails pool-missing"
    fi
  fi

  echo "== nightly finished, fails:${fails:- none} =="

  # Amendment 1: chaining, not clock. The prod sync fires on pipeline
  # completion with $DAY passed in, because the nightly can cross midnight
  # UTC and a `date +%F` inside the sync would then push the wrong day.
  # Off by default (SYNC_TO_PROD=1 in the cron wrapper's environment turns
  # it on), so a LAN-only install is unaffected.
  #
  # It runs AFTER the finished line on purpose: that line, in this file, is
  # the completion manifest the sync requires before it pushes anything,
  # and a night with any failure pushes nothing -- prod keeps serving its
  # last promoted generation, which is better than a partial one. A sync
  # failure adds `sync` to the fails line the owner reads on stdout and to
  # the exit code, and changes nothing this script wrote: the sync only
  # reads `data/`, and promotion on the VPS is a separate step.
  #
  # The pipeline lock is dropped first, for two reasons: nothing below
  # writes `data/`, and the sync takes that same lock shared to read it.
  # Holding it here would make the sync wait SYNC_LOCK_TIMEOUT on its own
  # parent and then alert.
  exec 7>&-
  if [[ ${SYNC_TO_PROD:-0} == 1 ]]; then
    if [[ -n $fails ]]; then
      echo "-- sync skipped: the night ended with fails:$fails"
    else
      t0=$SECONDS
      # Not under `capped`: this is rsync and ssh, not a python leg.
      if deploy/sync_vault_to_prod.sh "$DAY"; then
        echo "-- sync ok in $((SECONDS - t0))s"
      else
        fails="$fails sync"
        echo "== sync FAILED in $((SECONDS - t0))s, fails:$fails =="
      fi
    fi
  fi
} >>"$LOG" 2>&1

# --- stdout: the Telegram summary, kept short -------------------------------
echo "CareerOS nightly $DAY: $( [[ -z $fails ]] && echo 'all steps ok' || echo "FAILED:$fails" ) (log: $LOG)"
if [[ -f $DATA/classification/run_$DAY.yaml ]]; then
  grep -E 'model calls:|needs review:' "$LOG" | tail -2
fi
[[ -z $fails ]] || exit 1
