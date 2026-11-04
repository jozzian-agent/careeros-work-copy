#!/bin/bash
# Import one uploaded prod-export generation into the production vault.
#
# WHAT IT DOES
#   The VPS-side third step of the hand-push path (push-to-prod.md):
#   export on the LAN, upload with deploy/push_to_prod.sh, import here.
#   Given a generation name in incoming/, it
#
#     1. proves the upload finished (COMPLETE names the generation) and
#        that the bytes are the ones the exporter vouched for (MANIFEST
#        sha256, verified with sha256sum -c);
#     2. takes the data lock, so a backup or a promotion cannot
#        interleave with the import;
#     3. on an apply, refuses unless a vault backup younger than
#        IMPORT_BACKUP_MAX_AGE exists, and prints the exact command that
#        makes one;
#     4. runs the EXISTING scripts/import_pool_to_vault.py out of the
#        promoted release, as the vault's own account, against
#        /srv/careeros/prod/vault. No import logic lives in this file:
#        the creation rules (ownerless, in_pipeline: false, never
#        overwrite, never delete, skip on url/source_id, values+salary
#        from the classification half) are that script's, tested in
#        tests/test_pool_import.py.
#
#   The generation is an input, not a release: it stays in incoming/
#   after a successful import (promote_incoming.sh skips it by its
#   manifest header, so it can never be promoted or destroyed by a
#   promotion). Removing an imported generation is an owner decision.
#
# WHO RUNS IT, AND WHAT IT MAY READ
#   Root, like promote_incoming.sh: the backup directory is root-only
#   and dropping to the vault account needs it. The import itself runs
#   as IMPORT_USER (careeros-prod, the vault's owner) via runuser, so
#   the process that writes the vault is the account that owns it and
#   nothing runs the release code as root. careeros-prod reads the
#   careeros-push-owned generation through the group membership and the
#   2775 incoming/ directory that push-to-prod.md already has the owner
#   set up once -- no new privilege is introduced here.
#
# WHAT IT MUST NEVER TOUCH
#   * Any record with an owner, and any record that already exists:
#     enforced by import_pool_to_vault.py, which only creates.
#   * The generation itself: read-only. Nothing is moved or deleted.
#   * Code, releases, /etc, backups. It reads the backup directory to
#     find the newest archive and writes nothing anywhere except, through
#     the import script, the vault.
#
# DESCRIPTIONS, HONESTLY
#   An export generation carries pool.yaml + classification.yaml and no
#   ATS snapshots (sync and export both exclude them), so every imported
#   job lands with an empty description and the report counts them under
#   "descriptions missing". Title, url, location, company, coded values
#   (family top-3 included, as `ranked` inside the value record) and
#   salary all arrive; the posting text does not. This is the export
#   format's shape, not a failure of this step.
#
# ARGUMENTS
#   $1  generation name (e.g. 2026-11-03T165340Z). Required.
#   $2  --dry-run  optional: validate, take the lock, print the import
#       report with its 5-row sample, write nothing. No backup needed.
#
# ENVIRONMENT
#   IMPORT_INCOMING        where uploads land   (/srv/careeros/prod/incoming)
#   IMPORT_VAULT           the production vault (/srv/careeros/prod/vault)
#   IMPORT_BACKUP_DIR      deploy.sh's vault archives, vault-*.tar.gz
#                                        (/srv/careeros/prod/backups)
#   IMPORT_BACKUP_MAX_AGE  seconds a backup may be old and still count
#                                                                   (3600)
#   IMPORT_RELEASE         the promoted release whose code and venv run
#                          the import       (/srv/careeros/prod/app/current)
#   IMPORT_PYTHON          interpreter with PyYAML + the release's deps
#                                        ($IMPORT_RELEASE/.venv/bin/python)
#   IMPORT_USER            account the import runs as; an EMPTY value
#                          (set but empty) runs it as the invoking user,
#                          which is what a test on a host with no
#                          careeros-prod account needs  (careeros-prod)
#   DEPLOY_DATA_LOCK       promotion/backup lock
#                                        (/run/careeros/careeros-data.lock)
#
# FAILURE
#   Non-zero exit and one `ALERT careeros-import <generation>:` line
#   naming what was refused. The vault is either untouched or, when the
#   import script itself died mid-run, in the state its own
#   record-by-record writes left it -- which is what the backup gate
#   exists for.
set -euo pipefail

IMPORT_INCOMING="${IMPORT_INCOMING:-/srv/careeros/prod/incoming}"
IMPORT_VAULT="${IMPORT_VAULT:-/srv/careeros/prod/vault}"
IMPORT_BACKUP_DIR="${IMPORT_BACKUP_DIR:-/srv/careeros/prod/backups}"
IMPORT_BACKUP_MAX_AGE="${IMPORT_BACKUP_MAX_AGE:-3600}"
IMPORT_RELEASE="${IMPORT_RELEASE:-/srv/careeros/prod/app/current}"
IMPORT_PYTHON="${IMPORT_PYTHON:-$IMPORT_RELEASE/.venv/bin/python}"
IMPORT_USER="${IMPORT_USER-careeros-prod}"
DEPLOY_DATA_LOCK="${DEPLOY_DATA_LOCK:-/run/careeros/careeros-data.lock}"

GEN="${1:-}"
DRY_RUN=0
case "${2:-}" in
  '') ;;
  --dry-run) DRY_RUN=1 ;;
  *) echo "usage: $(basename "$0") <generation> [--dry-run]" >&2; exit 2 ;;
esac

alert() {
  echo "ALERT careeros-import ${GEN:-?}: $*"
  exit 1
}

[[ $GEN =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z$ ]] \
  || alert "'$GEN' is not a generation name (YYYY-MM-DDTHHMMSSZ)"

SRC="$IMPORT_INCOMING/$GEN"
[[ -d $SRC && ! -L $SRC ]] || alert "no generation directory at $SRC"

# --- 1. the upload finished, and the bytes are the vouched-for ones -------
[[ -f $SRC/COMPLETE && ! -L $SRC/COMPLETE ]] \
  || alert "incomplete generation: no COMPLETE marker, the upload is still running or died"
[[ $(cat "$SRC/COMPLETE") == "$GEN" ]] \
  || alert "the COMPLETE marker does not name this generation"
[[ -f $SRC/MANIFEST && ! -L $SRC/MANIFEST ]] || alert "no MANIFEST in the generation"
# The header is what tells an export generation from a pipeline one, the
# same line promote_incoming.sh reads to skip these. Importing a pipeline
# generation would mean importing bytes in a layout this path never
# validated for vault writes.
[[ $(head -1 "$SRC/MANIFEST") == '# careeros prod-export manifest' ]] \
  || alert "$GEN is not a prod-export generation (its MANIFEST header says otherwise); a pipeline generation is promote_incoming.sh's business, not this script's"
for required in pool.yaml classification.yaml; do
  [[ -f $SRC/$required && ! -L $SRC/$required ]] \
    || alert "the generation carries no $required"
done
# sha256sum -c over the manifest body: every file the exporter listed,
# checked against the digest the exporter computed. -c reads the
# `<digest>  <name>` shape the MANIFEST already holds.
SUMS=$(mktemp -t careeros-import-sums-XXXXXX)
trap 'rm -f "$SUMS"' EXIT
awk 'body; /^--$/ {body=1}' "$SRC/MANIFEST" >"$SUMS"
[[ -s $SUMS ]] || alert "the manifest lists no file"
( cd "$SRC" && sha256sum --quiet -c "$SUMS" ) >/dev/null \
  || alert "checksum mismatch: the generation's bytes are not the ones its MANIFEST vouches for"

# --- 2. the data lock ------------------------------------------------------
mkdir -p "$(dirname "$DEPLOY_DATA_LOCK")"
: >>"$DEPLOY_DATA_LOCK" 2>/dev/null || alert "cannot open the data lock $DEPLOY_DATA_LOCK"
exec 9>>"$DEPLOY_DATA_LOCK"
flock -n 9 || alert "a backup or a promotion holds $DEPLOY_DATA_LOCK; try again when it is done"

# --- 3. the interpreter and the vault have to be there ---------------------
[[ -x $IMPORT_PYTHON ]] || alert "no interpreter at $IMPORT_PYTHON (is the release carrying this code promoted? see docs/runbooks/push-to-prod.md)"
[[ -f $IMPORT_RELEASE/scripts/import_pool_to_vault.py ]] \
  || alert "the release at $IMPORT_RELEASE carries no import script; the promoted release predates the import step"
[[ -d $IMPORT_VAULT/jobs ]] \
  || alert "$IMPORT_VAULT does not look like a CareerOS vault (missing jobs/); refusing to import into a guess"

# --- 4. apply: a recent backup, or the exact command that makes one --------
if (( DRY_RUN == 0 )); then
  # `|| true`: a backup directory that does not exist is an ANSWER here
  # ("no backup"), not a pipeline failure to die on -- under
  # `set -o pipefail` a failing find would end the script before the
  # alert that names the missing backup ever printed.
  newest=$( { find "$IMPORT_BACKUP_DIR" -maxdepth 1 -type f -name 'vault-*.tar.gz' \
                -printf '%T@ %p\n' 2>/dev/null || true; } \
            | LC_ALL=C sort -rn | head -1 | cut -d' ' -f2-)
  if [[ -z $newest ]]; then
    alert "no vault backup in $IMPORT_BACKUP_DIR; refusing to apply. Make one first:
  sudo tar -czf $IMPORT_BACKUP_DIR/vault-\$(date -u +%Y%m%dT%H%M%SZ).tar.gz -C $(dirname "$IMPORT_VAULT") $(basename "$IMPORT_VAULT")"
  fi
  age=$(( $(date +%s) - $(stat -c '%Y' "$newest") ))
  if (( age > IMPORT_BACKUP_MAX_AGE )); then
    alert "the newest vault backup ($(basename "$newest")) is $(( age / 60 )) minute(s) old, over the $(( IMPORT_BACKUP_MAX_AGE / 60 ))-minute limit; refusing to apply. Make a fresh one first:
  sudo tar -czf $IMPORT_BACKUP_DIR/vault-\$(date -u +%Y%m%dT%H%M%SZ).tar.gz -C $(dirname "$IMPORT_VAULT") $(basename "$IMPORT_VAULT")"
  fi
  echo "-- backup ok: $(basename "$newest") ($(( age / 60 )) minute(s) old)"
fi

# --- 5. the import itself ---------------------------------------------------
# The existing script, unmodified in behaviour: --vault is the production
# vault, --stores is deliberately NOT passed, because an export
# generation carries no snapshots (see DESCRIPTIONS above) and the
# default lookup finding nothing is the honest path -- every row counts
# as "descriptions missing" in the report instead of silently borrowing
# some other tree's text.
cmd=("$IMPORT_PYTHON" "$IMPORT_RELEASE/scripts/import_pool_to_vault.py"
     --pool "$SRC/pool.yaml" --classification "$SRC/classification.yaml"
     --vault "$IMPORT_VAULT")
# `if` and not `(( DRY_RUN )) && ...`: under `set -e` an AND-list whose
# left side is false exits the script -- the whole wrapper would die
# silently on every APPLY run.
if (( DRY_RUN )); then cmd+=(--dry-run); fi

echo "-- import generation $GEN into $IMPORT_VAULT (mode: $( (( DRY_RUN )) && echo dry-run || echo APPLY ))"
# `if ... rc=$?` and not a bare call: under `set -e` a failing command
# would end the script before the alert line -- the one thing the owner
# reads -- ever prints. `cd $IMPORT_RELEASE` first: the import script
# resolves its default `data/ats` store roots relative to the working
# directory, and the release root is the one place that path means
# something (it holds no snapshots either way, but a cwd that is the
# vault's parent would be a different wrong guess).
if [[ $(id -u) == 0 && -n $IMPORT_USER ]]; then
  if runuser -u "$IMPORT_USER" -- bash -c 'cd "$0" && exec "$@"' "$IMPORT_RELEASE" "${cmd[@]}"; then rc=0; else rc=$?; fi
else
  [[ $(id -u) == 0 ]] \
    || echo "-- note: running as $(id -un), so the import runs as this user rather than $IMPORT_USER (test mode)"
  if (cd "$IMPORT_RELEASE" && exec "${cmd[@]}"); then rc=0; else rc=$?; fi
fi

# A failed import is the import script's own report and warnings; this
# line is only the wrapper's verdict.
(( rc == 0 )) || alert "the import script exited $rc; the vault may hold a partial import -- restore from the backup named above if in doubt (docs/runbooks/push-to-prod.md, Rollback)"

if (( DRY_RUN )); then
  echo "-- dry run ok: nothing was written"
else
  echo "-- import ok: $GEN is in $IMPORT_VAULT"
  echo "   verify with: sudo grep -rl '^in_pipeline: false' $IMPORT_VAULT/jobs | wc -l"
  echo "   (counts every universe-only job; compare against the report's 'imported:' line)"
fi
