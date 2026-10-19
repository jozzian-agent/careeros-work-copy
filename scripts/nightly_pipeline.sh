#!/bin/bash
# The nightly pipeline: ATS fetch -> pool export -> local-LLM classification.
#
# Runs at 19:00 local (Swiss) time via the Hermes cron job that wraps this
# script (~/.hermes/scripts/careeros_nightly.sh). Every step is idempotent
# and safe to re-run; details, decisions and measured durations live in
# docs/runbooks/nightly-pipeline.md.
#
# Contract: verbose progress goes to the log file, ONLY a short summary goes
# to stdout, because stdout is delivered verbatim to Telegram by the cron
# runner. Empty stdout would mean silent.
set -uo pipefail
cd /root/work/careeros-dashboard || { echo "nightly: repo missing"; exit 1; }

DAY=$(date +%F)
LOG_DIR=data/nightly
mkdir -p "$LOG_DIR" data/classification
LOG="$LOG_DIR/nightly_$DAY.log"

# Required, not optional: Ollama's OpenAI-compat /v1 endpoint silently drops
# think=False and qwen3:30b-a3b then spends ~100s "thinking" per posting.
# The native /api/chat path with think:false is ~10x faster and answers in
# the same JSON shape. See docs/runbooks/local-llm-optimisation.md.
export CLASSIFY_LLM_NATIVE=1

PROVIDERS="personio greenhouse lever ashby recruitee smartrecruiters"
OLLAMA=http://192.168.1.10:11434
fails=""

{
  echo "== nightly pipeline $DAY (host $(hostname)) =="

  if ! curl -s --max-time 10 "$OLLAMA/api/tags" >/dev/null; then
    echo "FATAL: local LLM host $OLLAMA unreachable - classification would fail for hours; aborting before fetch so nothing half-runs."
    echo "nightly $DAY: ABORTED - ideaai ($OLLAMA) unreachable"
    exit 1
  fi

  # Per-provider fetch with retry+backoff: 2026-10-19 smartrecruiters died in
  # 1s (transient endpoint blip) and cost the day 10 tenants' worth of postings.
  # Fetches are idempotent (frozen snapshots), so a retry is always safe.
  for p in $PROVIDERS; do
    t0=$SECONDS
    attempt=1
    ok=0
    until .venv/bin/python scripts/run_ats_fetch.py --provider "$p" fetch; do
      if (( attempt >= 3 )); then
        echo "-- fetch $p FAILED after $attempt attempts in $((SECONDS - t0))s"
        fails="$fails fetch:$p"
        break
      fi
      backoff=$(( attempt * 60 ))
      echo "-- fetch $p attempt $attempt failed; retrying in ${backoff}s"
      sleep "$backoff"
      attempt=$(( attempt + 1 ))
    done
    if [[ -z ${fails##*fetch:$p*} ]]; then :; else ok=1; fi
    (( ok )) && echo "-- fetch $p ok (attempt $attempt) in $((SECONDS - t0))s"
  done

  echo "-- export pool (--all-providers)"
  if .venv/bin/python scripts/run_ats_fetch.py --provider personio export --all-providers --day "$DAY"; then
    echo "-- export ok"
  else
    echo "-- export FAILED"
    fails="$fails export"
  fi

  POOL="data/ats/exports/golden_set_pool_$DAY.yaml"
  if [[ -f $POOL ]]; then
    rows=$(grep -c '^- id:\|  - id:' "$POOL" || true)
    t0=$SECONDS
    echo "-- classify llm layer over $POOL"
    if .venv/bin/python scripts/run_classification.py --pool "$POOL" --layer llm \
         --out "data/classification/run_$DAY.yaml"; then
      echo "-- classify ok in $((SECONDS - t0))s"
    else
      echo "-- classify FAILED in $((SECONDS - t0))s"
      fails="$fails classify"
    fi
  else
    echo "-- POOL MISSING: $POOL - classify skipped"
    fails="$fails pool-missing"
  fi

  echo "== nightly finished, fails:${fails:- none} =="
} >>"$LOG" 2>&1

# --- stdout: the Telegram summary, kept short -------------------------------
echo "CareerOS nightly $DAY: $( [[ -z $fails ]] && echo 'all steps ok' || echo "FAILED:$fails" ) (log: $LOG)"
if [[ -f data/classification/run_$DAY.yaml ]]; then
  grep -E 'model calls:|needs review:' "$LOG" | tail -2
fi
[[ -z $fails ]] || exit 1
