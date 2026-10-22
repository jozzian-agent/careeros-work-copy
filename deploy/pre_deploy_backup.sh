#!/bin/bash
# The backup a release takes before it starts (Amendment 2, pre-deploy).
#
# WHAT IT DOES
#   Two calls into deploy/backup_prod.sh, both in a pre-deploy namespace
#   that keeps 14 instead of 5:
#
#     --owner-data  into `pre-deploy-owner-data`  -- the prod vault
#     --full        into `pre-deploy`             -- the served generation
#
#   Owner data first, because it is the half that cannot be rebuilt: the
#   pipeline can produce another generation any night, but an application,
#   a status, a note or a CV exists only in prod once editing begins there
#   (owner decision 1).
#
#   WHY BOTH, and why this used to be wrong: migrations run automatically
#   at every app startup (careeros/server.py, create_app), which means they
#   have already rewritten records by the time the health check decides
#   whether to roll back. Rolling the code back does not roll a migration
#   back. What those migrations rewrite is the VAULT -- `migrate_record_owner.py`
#   stamps ownership onto owner records -- and a pre-deploy backup that
#   held only the pipeline generation covered exactly the half a release
#   cannot damage while leaving the half it can damage unbacked. The
#   Sunday/daily jobs are not a substitute: the daily owner-data backup can
#   be up to 24 hours old, and a release is a thing that happens between
#   them.
#
#   Two calls rather than a new combined mode in backup_prod.sh: it is the
#   smaller element. A combined mode would need a second source, a second
#   tar leg in the one encrypt stream and its own retention rule, to
#   produce an archive that mixes two subsets with different restore
#   procedures. Two namespaces also keep "14" meaning what it says -- 14
#   releases' worth of each -- and keep the two archives from colliding on
#   a name, which they would if both landed in one namespace in the same
#   second.
#
#   INTENDED CALLER: a deploy script, immediately before it installs a new
#   release. There is NO deploy.sh in this repo yet -- it is still a brief
#   in the deploy runbook (Part 2) -- and this script does not invent one.
#   When one is written, it calls this first and treats a non-zero exit as
#   a reason not to deploy. It must call it BEFORE it takes DEPLOY_LOCK, or
#   while holding only that lock: backup_prod.sh waits on
#   DEPLOY_DATA_LOCK, never on the deploy lock, precisely so this call
#   cannot deadlock the release it protects.
#
#   Either call failing fails the whole thing, with backup_prod.sh's own
#   ALERT line, and the second is not attempted after the first fails: a
#   release that cannot back up both halves is a release that must not
#   start.
#
# WHAT IT MUST NEVER TOUCH
#   Whatever backup_prod.sh must never touch -- it adds no file access of
#   its own. It does not restart, deploy or roll back anything, and it
#   fails closed through backup_prod.sh (no age key, no backup, no deploy).
#
# ARGUMENTS
#   none. Any argument is refused rather than passed on, so a stray
#   `--owner-data` cannot turn a pre-deploy backup into something else.
#
# ENVIRONMENT
#   Everything backup_prod.sh reads. BACKUP_NAMESPACE is the prefix for
#   both calls (default `pre-deploy`; the owner-data one appends
#   `-owner-data`) and the retention is set here, both still overridable by
#   the caller's environment, which is what the rehearsal VM does.
#
# FAILURE
#   Non-zero exit, and backup_prod.sh's own `ALERT careeros-backup
#   pre-deploy...:` line.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if (( $# > 0 )); then
  echo "ALERT careeros-backup pre-deploy: $(basename "$0") takes no arguments (got '$*')"
  exit 1
fi

NS="${BACKUP_NAMESPACE:-pre-deploy}"
export BACKUP_KEEP="${BACKUP_KEEP:-14}"

BACKUP_NAMESPACE="$NS-owner-data" "$HERE/backup_prod.sh" --owner-data \
  || exit 1
BACKUP_NAMESPACE="$NS" "$HERE/backup_prod.sh" --full \
  || exit 1
echo "-- pre-deploy backup ok: the prod vault and the served generation are both archived"
