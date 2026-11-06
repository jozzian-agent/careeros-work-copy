#!/bin/bash
# Backfill empty descriptions on the production vault from one uploaded
# prod-export generation (CAREER-131).
#
# WHAT IT DOES
#   The 752 jobs generation 2026-11-03 imported have EMPTY descriptions:
#   that generation was exported before descriptions.yaml existed, so
#   there was no posting text to import (deploy/import_prod_generation.sh,
#   "DESCRIPTIONS, HONESTLY"). The text was never lost -- the frozen ATS
#   snapshots live on the LAN host and every export since resolves them
#   into descriptions.yaml. This script is the VPS-side step that puts
#   that text onto the jobs that are still empty:
#
#     1. proves the upload finished (COMPLETE names the generation), that
#        the bytes are the ones the exporter vouched for (MANIFEST sha256
#        with sha256sum -c), and -- unlike the import wrapper -- that the
#        generation CARRIES descriptions.yaml AND that the manifest
#        vouches for it. A generation without the file has nothing to
#        give and is refused, not silently "applied" as a no-op.
#     2. takes the data lock, so a backup or a promotion cannot
#        interleave with the fill;
#     3. on an apply, refuses unless a vault backup younger than
#        IMPORT_BACKUP_MAX_AGE exists, and prints the exact command that
#        makes one;
#     4. runs scripts/backfill_descriptions.py out of the promoted
#        release, as the vault's own account, against
#        /srv/careeros/prod/vault. All fill rules live in that script,
#        tested in tests/test_backfill_descriptions.py:
#        * fill ONLY jobs whose stored description is empty/whitespace;
#        * NEVER overwrite an existing description;
#        * NEVER touch a record that has an owner;
#        * match by source_id against the generation's pool.yaml;
#        * stamp field_provenance.description = feed;
#        * idempotent: a second run fills nothing.
#
#   The generation is an input, not a release: it stays in incoming/
#   after a successful run (promote_incoming.sh skips prod-export
#   generations by their manifest header).
#
# WHO RUNS IT, AND WHAT IT MAY READ
#   Same posture as import_prod_generation.sh: root invokes, the fill
#   itself runs as IMPORT_USER (careeros-prod) via runuser, so the
#   process that writes the vault is the account that owns it. The
#   generation is readable through the group membership and 2775
#   incoming/ that push-to-prod.md already sets up.
#
# WHAT IT MUST NEVER TOUCH
#   * Any record with an owner, and any description that is already
#     non-empty: enforced by backfill_descriptions.py, which only fills
#     empty ones.
#   * The generation itself: read-only. Nothing is moved or deleted.
#   * Code, releases, /etc, backups. Writes nothing anywhere except,
#     through the fill script, job descriptions in the vault.
#
# ARGUMENTS
#   $1  generation name (e.g. 2026-11-04T090000Z). Required. It must be
#       a prod-export generation that carries descriptions.yaml; any
#       export made after 2026-11-03 does.
#   Then, in any order:
#   --dry-run  validate, take the lock, print the fill report with its
#       sample, write nothing. No backup needed.
#
# ENVIRONMENT
#   The import wrapper's variables, unchanged in name and meaning, so one
#   host setup serves both scripts:
#   IMPORT_INCOMING        where uploads land   (/srv/careeros/prod/incoming)
#   IMPORT_VAULT           the production vault (/srv/careeros/prod/vault)
#   IMPORT_BACKUP_DIR      deploy.sh's vault archives, vault-*.tar.gz
#                                        (/srv/careeros/prod/backups)
#   IMPORT_BACKUP_MAX_AGE  seconds a backup may be old and still count
#                                                                   (3600)
#   IMPORT_RELEASE         the promoted release whose code and venv run
#                          the fill         (/srv/careeros/prod/app/current)
#   IMPORT_PYTHON          interpreter with PyYAML + the release's deps
#                                        ($IMPORT_RELEASE/.venv/bin/python)
#   IMPORT_USER            account the fill runs as; an EMPTY value (set
#                          but empty) runs it as the invoking user, which
#                          is what a test on a host with no careeros-prod
#                          account needs  (careeros-prod)
#   DEPLOY_DATA_LOCK       promotion/backup lock
#                                        (/run/careeros/careeros-data.lock)
#
# FAILURE
#   Non-zero exit and one `ALERT careeros-backfill <generation>:` line
#   naming what was refused. The vault is either untouched or, when the
#   fill script itself died mid-run, in the state its own record-by-
#   record writes left it -- which is what the backup gate exists for.
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
shift || true
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "usage: $(basename "$0") <generation> [--dry-run]" >&2; exit 2 ;;
  esac
done

alert() {
  echo "ALERT careeros-backfill ${GEN:-?}: $*"
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
[[ $(head -1 "$SRC/MANIFEST") == '# careeros prod-export manifest' ]] \
  || alert "$GEN is not a prod-export generation (its MANIFEST header says otherwise); a pipeline generation is promote_incoming.sh's business, not this script's"
for required in pool.yaml descriptions.yaml; do
  [[ -f $SRC/$required && ! -L $SRC/$required ]] \
    || alert "the generation carries no $required$( [[ $required == descriptions.yaml ]] && echo '; a backfill without posting text has nothing to give -- export and upload a fresh generation first (docs/runbooks/push-to-prod.md)')"
done
SUMS=$(mktemp -t careeros-backfill-sums-XXXXXX)
trap 'rm -f "$SUMS"' EXIT
awk 'body; /^--$/ {body=1}' "$SRC/MANIFEST" >"$SUMS"
[[ -s $SUMS ]] || alert "the manifest lists no file"
( cd "$SRC" && sha256sum --quiet -c "$SUMS" ) >/dev/null \
  || alert "checksum mismatch: the generation's bytes are not the ones its MANIFEST vouches for"
# sha256sum -c verifies the files the MANIFEST LISTS, so an unlisted
# descriptions.yaml would sail through that gate: the posting text is the
# one payload this script exists to write, and text nothing vouches for
# is refused -- the same guard import_prod_generation.sh holds.
awk -v name=descriptions.yaml '$2 == name { found = 1 } END { exit !found }' "$SUMS" \
  || alert "descriptions.yaml has no MANIFEST checksum line; refusing to backfill with posting text the manifest does not vouch for"
awk -v name=pool.yaml '$2 == name { found = 1 } END { exit !found }' "$SUMS" \
  || alert "pool.yaml has no MANIFEST checksum line; refusing to match against a key set the manifest does not vouch for"

# --- 2. the data lock ------------------------------------------------------
mkdir -p "$(dirname "$DEPLOY_DATA_LOCK")"
: >>"$DEPLOY_DATA_LOCK" 2>/dev/null || alert "cannot open the data lock $DEPLOY_DATA_LOCK"
exec 9>>"$DEPLOY_DATA_LOCK"
flock -n 9 || alert "a backup or a promotion holds $DEPLOY_DATA_LOCK; try again when it is done"

# --- 3. the interpreter, the fill script and the vault have to be there ----
[[ -x $IMPORT_PYTHON ]] || alert "no interpreter at $IMPORT_PYTHON (is the release carrying this code promoted? see docs/runbooks/push-to-prod.md)"
[[ -f $IMPORT_RELEASE/scripts/backfill_descriptions.py ]] \
  || alert "the release at $IMPORT_RELEASE carries no backfill script; the promoted release predates CAREER-131 -- promote the release that carries it first"
[[ -d $IMPORT_VAULT/jobs ]] \
  || alert "$IMPORT_VAULT does not look like a CareerOS vault (missing jobs/); refusing to fill into a guess"

# --- 4. apply: a recent backup, or the exact command that makes one --------
if (( DRY_RUN == 0 )); then
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

# --- 5. the fill itself -----------------------------------------------------
# The existing script, unmodified in behaviour: dry run unless --apply.
cmd=("$IMPORT_PYTHON" "$IMPORT_RELEASE/scripts/backfill_descriptions.py"
     --vault "$IMPORT_VAULT"
     --descriptions "$SRC/descriptions.yaml" --pool "$SRC/pool.yaml")
# `if` and not `(( DRY_RUN )) && ...`: under `set -e` an AND-list whose
# left side is false exits the script -- the whole wrapper would die
# silently on every dry run.
if (( DRY_RUN == 0 )); then cmd+=(--apply); fi

echo "-- backfill descriptions into $IMPORT_VAULT from $GEN (mode: $( (( DRY_RUN )) && echo dry-run || echo APPLY ))"
if [[ $(id -u) == 0 && -n $IMPORT_USER ]]; then
  # SC2016 is the point: the single quotes keep $0 and $@ literal here so
  # the inner bash -c expands them from its own argv (the release path and
  # the fill command), not from this shell's environment.
  # shellcheck disable=SC2016
  if runuser -u "$IMPORT_USER" -- bash -c 'cd "$0" && exec "$@"' "$IMPORT_RELEASE" "${cmd[@]}"; then rc=0; else rc=$?; fi
else
  [[ $(id -u) == 0 ]] \
    || echo "-- note: running as $(id -un), so the fill runs as this user rather than $IMPORT_USER (test mode)"
  if (cd "$IMPORT_RELEASE" && exec "${cmd[@]}"); then rc=0; else rc=$?; fi
fi

# A failed fill is the fill script's own report and stderr; this line is
# only the wrapper's verdict.
(( rc == 0 )) || alert "the backfill script exited $rc; the vault may hold partial fills -- restore from the backup named above if in doubt (docs/runbooks/backfill-descriptions.md, Rollback)"

if (( DRY_RUN )); then
  echo "-- dry run ok: nothing was written"
else
  echo "-- backfill ok: empty descriptions from $GEN are filled in $IMPORT_VAULT"
  echo "   verify: re-run this script with --dry-run; the report should show"
  echo "   'would fill: 0' and every matched job under 'already had text'."
fi
