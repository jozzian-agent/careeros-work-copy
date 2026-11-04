#!/bin/bash
# Push one staged prod-export generation from the LAN host to the VPS (owner decision 2026-11-04).
#
# WHAT IT DOES
#   push_to_prod.sh DATE [--dry-run]
#
#   Finds the staged export for DATE (data/prod-export/<DATE>/, the shape
#   scripts/export_jobs_for_prod.py writes: pool.yaml, classification.yaml,
#   MANIFEST), re-running the export if the directory is missing. Re-verifies
#   the MANIFEST checksums LOCALLY and refuses to continue on any mismatch.
#   Uploads over the dedicated push key with rsync into
#   /srv/careeros/prod/incoming/<generation>/ on the VPS, following the
#   generation naming (YYYY-MM-DDTHHMMSSZ) and COMPLETE-marker convention of
#   deploy/sync_vault_to_prod.sh: the marker is a SEPARATE transfer written
#   LAST, so a half-finished upload never looks complete to promote_incoming.sh.
#
# WHAT IT NEVER DOES
#   * No --delete, ever, on any transfer: it cannot remove anything remote.
#   * No overwrite: every remote file must be a pure creation (rsync
#     itemized `+++++++++`); anything else means the generation name is
#     taken or half-populated and the push is refused before transferring.
#   * Writes nothing outside data/prod-export/ on this host (plus one line
#     in data/prod-export/push-receipts.log after a successful push).
#   * Touches no secret value: the SSH key is referenced by PATH only and
#     never printed; no credential appears in any output.
#   * Promotes nothing. Promotion/import is a VPS-local step the owner runs.
#
# ENVIRONMENT (paths and names, never secrets)
#   SYNC_HOST          the VPS hostname. NO DEFAULT: from this variable or
#                      from a one-line file /etc/careeros/push-host that the
#                      owner writes once. Unset+missing file is a usage error.
#   SYNC_USER          the restricted receiving account        (careeros-push)
#   SYNC_SSH_KEY       private push key, path only   (/root/.ssh/careeros-push/id_ed25519)
#   SYNC_KNOWN_HOSTS   pinned host key file, StrictHostKeyChecking=yes
#                                   (/root/.ssh/careeros-push/known_hosts)
#   SYNC_SSH_PORT                                          (22)
#   EXPORT_ROOT        where staged exports live    (<repo>/data/prod-export)
#   CAREEROS_VAULT     vault to check ownership against; needed ONLY when
#                      the export must be (re-)run. Unset is an error in
#                      that case, never a guess.
#   PUSH_PYTHON        python for the export step (repo .venv or python3)
#
# EXIT
#   0 on success (or a clean --dry-run). Non-zero on any failure, with one
#   `ALERT careeros-push-to-prod <date>:` line saying what refused.
#
# DRY RUN
#   --dry-run does everything locally (find/re-run export, checksum verify)
#   plus rsync --dry-run against the real target, prints the file names,
#   sizes and the generation name it WOULD use, and writes nothing remotely
#   and no receipt.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(dirname "$HERE")

alert() {
  echo "ALERT careeros-push-to-prod ${DAY:-?}: $*" >&2
  exit 1
}

DAY="${1:-}"
[[ $DAY =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
  || { echo "usage: push_to_prod.sh YYYY-MM-DD [--dry-run]" >&2; exit 2; }
shift
DRY=0
[[ ${1:-} == "--dry-run" ]] && DRY=1

SYNC_USER="${SYNC_USER:-careeros-push}"
SYNC_SSH_KEY="${SYNC_SSH_KEY:-/root/.ssh/careeros-push/id_ed25519}"
SYNC_KNOWN_HOSTS="${SYNC_KNOWN_HOSTS:-/root/.ssh/careeros-push/known_hosts}"
SYNC_SSH_PORT="${SYNC_SSH_PORT:-22}"
EXPORT_ROOT="${EXPORT_ROOT:-$REPO/data/prod-export}"
EXPORT_DIR="$EXPORT_ROOT/$DAY"
PUSH_PYTHON="${PUSH_PYTHON:-$REPO/.venv/bin/python}"
[[ -x $PUSH_PYTHON ]] || PUSH_PYTHON=python3

# The host is never hard-coded: owner-set variable or owner-written file.
SYNC_HOST="${SYNC_HOST:-}"
if [[ -z $SYNC_HOST && -r /etc/careeros/push-host ]]; then
  SYNC_HOST=$(head -1 /etc/careeros/push-host | tr -d '[:space:]')
fi
[[ -n $SYNC_HOST ]] \
  || alert "SYNC_HOST is unset and /etc/careeros/push-host is missing; set one (owner decision: no invented hostnames)"

# --- 1. find or re-run the staged export -----------------------------------
if [[ ! -d $EXPORT_DIR ]]; then
  echo "-- no staged export at $EXPORT_DIR; running the export step for $DAY"
  [[ -n ${CAREEROS_VAULT:-} ]] \
    || alert "CAREEROS_VAULT is unset and the export must run; point it at the vault to check ownership against"
  pool="$REPO/data/ats/exports/golden_set_pool_$DAY.yaml"
  run="$REPO/data/classification/run_$DAY.yaml"
  [[ -f $pool ]] || alert "no pool export for $DAY at $pool"
  [[ -f $run ]] || alert "no classification run for $DAY at $run"
  PYTHONPATH="$REPO:$REPO/vendor/capa-repo" "$PUSH_PYTHON" \
    "$REPO/scripts/export_jobs_for_prod.py" \
    --pool "$pool" --classification "$run" \
    --vault "$CAREEROS_VAULT" --out "$EXPORT_DIR" \
    || alert "the export step failed; nothing was sent"
fi

for f in pool.yaml classification.yaml MANIFEST; do
  [[ -f $EXPORT_DIR/$f ]] || alert "$EXPORT_DIR/$f is missing; the staged export is incomplete"
done

# --- 2. re-verify the MANIFEST locally, byte for byte ----------------------
manifest_ok=0
while read -r digest name; do
  [[ -f $EXPORT_DIR/$name ]] || alert "MANIFEST lists $name but the file is not in the staged export"
  actual=$(sha256sum "$EXPORT_DIR/$name" | cut -d' ' -f1)
  [[ $actual == "$digest" ]] \
    || alert "checksum mismatch for $name (manifest ${digest:0:12}…, actual ${actual:0:12}…); refusing to send a tree that changed after it was staged"
  manifest_ok=$(( manifest_ok + 1 ))
done < <(sed -n '/^--$/,$p' "$EXPORT_DIR/MANIFEST" | tail -n +2)
(( manifest_ok >= 2 )) || alert "MANIFEST carries $manifest_ok checksum line(s); expected pool.yaml and classification.yaml"
echo "-- manifest ok: $manifest_ok file(s) verified against their sha256"

postings=$(sed -n 's/^postings: //p' "$EXPORT_DIR/MANIFEST" | head -1)
[[ -n $postings ]] || alert "MANIFEST has no postings: line"

# --- 3. generation name + SSH command (key by path, never by value) --------
GEN="${DAY}T$(date -u +%H%M%SZ)"
[[ $GEN =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z$ ]] \
  || alert "generated name '$GEN' is not a generation name"

[[ -f $SYNC_SSH_KEY ]] || alert "no push key at $SYNC_SSH_KEY"
key_mode=$(stat -c '%a' "$SYNC_SSH_KEY")
dir_mode=$(stat -c '%a' "$(dirname "$SYNC_SSH_KEY")")
[[ $key_mode == 600 ]] || alert "$SYNC_SSH_KEY is mode $key_mode, must be 600"
[[ $dir_mode == 700 ]] || alert "$(dirname "$SYNC_SSH_KEY") is mode $dir_mode, must be 700"
[[ -s $SYNC_KNOWN_HOSTS ]] \
  || alert "no pinned host key at $SYNC_KNOWN_HOSTS (owner pins it once; see docs/runbooks/push-to-prod.md, 'Host-key pinning')"

ssh_cmd="ssh"
for opt in -i "$SYNC_SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
           -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$SYNC_KNOWN_HOSTS" \
           -o PasswordAuthentication=no -o PubkeyAuthentication=yes \
           -o ClearAllForwardings=yes -o RequestTTY=no -p "$SYNC_SSH_PORT"; do
  ssh_cmd+=" $(printf '%q' "$opt")"
done

RSYNC_SAFE=(-a --no-links --no-devices --no-specials)
TARGET="$SYNC_USER@$SYNC_HOST"

echo "-- generation $GEN -> $TARGET:/srv/careeros/prod/incoming/$GEN/"
echo "   $postings postings, $(du -sb "$EXPORT_DIR" | cut -f1) bytes staged:"
(cd "$EXPORT_DIR" && find . -type f -printf '   %p %s bytes\n' | sort)

# --- 4. pre-flight dry run: the target must be EMPTY -----------------------
# A dry run that FAILS is not a dry run that found nothing (the lesson
# sync_vault_to_prod.sh carries in its comments): any non-zero exit stops
# the push. rrsync -wo cannot list, but the receiver's file list still shows
# what EXISTS at the target: a pure creation itemizes as `+++++++++`.
# Anything else (an update line, a deletion line) means the generation name
# is taken or half-populated, and this script refuses instead of overwriting.
pre=$(mktemp -d -t push-to-prod-XXXXXX)
trap 'rm -rf "$pre"' EXIT
rc=0
rsync -ni --dry-run "${RSYNC_SAFE[@]}" -e "$ssh_cmd" \
      "$EXPORT_DIR/" "$TARGET:$GEN/" >"$pre/dry.out" 2>"$pre/dry.err" || rc=$?
(( rc == 0 )) \
  || alert "the pre-flight dry run failed (rsync exit $rc: $(tr '\n' ' ' <"$pre/dry.err" | head -c 300))"
foreign=$(grep -v '^\(>f+++\|cd+++\|\.d+++\)' "$pre/dry.out" | grep -c '[^[:space:]]' || true)
deletes=$(grep -c '^\*deleting' "$pre/dry.out" || true)
(( deletes == 0 )) || alert "the dry run shows $deletes deletion(s) at the target; this script never deletes -- something is very wrong"
(( foreign == 0 )) \
  || alert "the target generation $GEN is not empty ($foreign item(s) would be updated, not created); refusing to overwrite an existing generation -- re-run later for a fresh name, and inspect/remove the old one on the VPS as root"

if (( DRY == 1 )); then
  echo "-- dry run: nothing sent, no receipt written"
  echo "-- a real run would create incoming/$GEN/ with the files above and write COMPLETE last"
  exit 0
fi

# --- 5. the real transfer: no --delete, no overwrite -----------------------
# D770/F640 (not sync_vault_to_prod.sh's D750/F640) so careeros-prod can
# read and `mv` the generation out of incoming WITHOUT root, provided it
# is in the careeros-push group and incoming/ is group-writable (see
# docs/runbooks/push-to-prod.md, "Permissions"). promote_incoming.sh
# re-chmods 750/640 after the move regardless, so root-run promotion is
# unaffected.
rsync "${RSYNC_SAFE[@]}" --stats --no-owner --no-group --chmod=D770,F640 \
      -e "$ssh_cmd" "$EXPORT_DIR/" "$TARGET:$GEN/" >"$pre/send.out" \
  || alert "rsync of generation $GEN failed; nothing is promotable until COMPLETE lands, and it has not"
sent_bytes=$(sed -n 's/^Total transferred file size: \([0-9,]*\) bytes$/\1/p' "$pre/send.out" | tr -d ',')
echo "-- payload sent: ${sent_bytes:-unknown} bytes"

# --- 6. COMPLETE, LAST, as its own transfer --------------------------------
# rsync gives no ordering guarantee inside one run, so the marker never
# travels with the payload (same rule as sync_vault_to_prod.sh).
echo "$GEN" >"$pre/COMPLETE"
chmod 640 "$pre/COMPLETE"
rsync "${RSYNC_SAFE[@]}" --no-owner --no-group --chmod=F640 \
      -e "$ssh_cmd" "$pre/COMPLETE" "$TARGET:$GEN/COMPLETE" \
  || alert "generation $GEN uploaded but its COMPLETE marker did not; the VPS will not promote it -- re-push (a fresh generation) or place the marker by hand on the VPS as root"

# --- 7. receipt (local only) -------------------------------------------------
mkdir -p "$EXPORT_ROOT"
echo "$(date -u +%FT%TZ) $DAY gen=$GEN host=$SYNC_HOST postings=$postings bytes=${sent_bytes:-?}" \
  >>"$EXPORT_ROOT/push-receipts.log"

echo "-- push ok: generation $GEN is complete in incoming on $TARGET"
echo "-- next step (owner, on the VPS): import/promote $GEN -- see docs/runbooks/push-to-prod.md"
