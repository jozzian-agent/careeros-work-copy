#!/bin/bash
# Push one night's pipeline-owned data from the LAN to prod (Amendment 1).
#
# WHAT IT DOES
#   Called with the day the nightly ran for, it stages an allowlisted copy
#   of that night's pipeline output, writes a checksum manifest beside it,
#   and rsyncs the tree into `incoming/<generation>/` on the prod VPS over
#   a dedicated, write-confined SSH key. The upload ends with a `COMPLETE`
#   marker pushed as its own transfer, which is the only thing that tells
#   the VPS side a generation is whole.
#
#   It does NOT promote anything. Promotion is a separate, VPS-local step
#   (deploy/promote_incoming.sh) run by the prod account, never by this
#   uploader. Prod keeps serving the last promoted generation until that
#   step succeeds, so a failed or half-finished sync costs nothing but a
#   stale generation and an alert.
#
#   Authority is split (owner decision 1, 2026-10-22): pipeline output is
#   LAN-authoritative and flows one way; owner-edited records are
#   prod-authoritative and this script cannot see, mirror or delete them.
#
# WHAT IT MUST NEVER TOUCH
#   * The session-signing key (`secret_key`), user/account records,
#     environment files, logs, backups, `state/`, ATS snapshots. None of
#     them is in the allowlist, and the allowlist is the only thing that
#     is ever staged -- there is no exclusion list to get wrong.
#   * Prod-owned paths. The uploader writes under one confined incoming
#     directory and nowhere else: not the live pointer, not an active
#     generation, not the prod vault, not code, not /etc. `--delete` is
#     passed only against the fresh incoming generation directory, which
#     is disposable by construction, and never against a prod-owned path.
#   * Staging. Exactly one target, prod. Staging is seeded from
#     `sample/vault/` and never holds live data.
#   * Anything in this repo. The staging copy lives in a private temp
#     directory and is removed on exit; `data/` is only ever read.
#
# ARGUMENTS
#   $1  DAY, the pipeline run day as YYYY-MM-DD. REQUIRED and never
#       recomputed here: the nightly can cross midnight UTC, so the only
#       correct day is the one the nightly itself used (Amendment 1,
#       "chaining, not clock").
#
# ENVIRONMENT (every default is a path or a hostname, never a secret)
#   SYNC_DATA          data directory to read            (repo `data`)
#   SYNC_VAULT         vault root for the pipeline-owned vault files;
#                      falls back to CAREEROS_VAULT, and when both are
#                      unset no vault file is staged at all   (unset)
#   SYNC_VAULT_FILES   allowlist inside the vault    (`companies tags.yaml`)
#   SYNC_PROVIDERS     providers whose tenants/runs ship          (the six)
#   SYNC_TARGET        rsync target             (careeros-sync@app.career-os.ch)
#   SYNC_SSH_KEY       private key for this push only
#                                      (/root/.ssh/careeros-sync/id_ed25519)
#   SYNC_KNOWN_HOSTS   pinned VPS host key file
#                                      (/root/.ssh/careeros-sync/known_hosts)
#   SYNC_SSH_PORT      port                                            (22)
#   SYNC_MIN_POOL_ROWS       floor for the day's pool postings         (50)
#   SYNC_MIN_CLASSIFIED_ROWS floor for the day's classified postings   (50)
#   SYNC_MIN_TENANTS         floor for the summed tenant count       (1000)
#   SYNC_MAX_DELETE          deletions inside the incoming generation
#                            above which the sync aborts instead of
#                            propagating                               (50)
#   SYNC_PIPELINE_LOCK       the nightly pipeline's lock, taken SHARED here
#                            so a running pipeline and this reading of its
#                            output cannot interleave
#                                     (`$SYNC_DATA/nightly/.pipeline.lock`)
#   SYNC_SELF_LOCK           this script's own lock, taken EXCLUSIVE and
#                            non-blocking so two syncs cannot build two
#                            generations out of one tree
#                                         (`$SYNC_DATA/nightly/.sync.lock`)
#   SYNC_LOCK_TIMEOUT        seconds to wait for the pipeline lock before
#                            aborting with an alert                   (300)
#
# THE TWO LOCKS, AND THE ORDER THEY ARE TAKEN IN
#   SYNC_PIPELINE_LOCK first, SHARED, with a timeout: the nightly holds it
#   exclusive while it writes, so either a run is going (and this waits) or
#   none is (and one starting now waits for this). Then SYNC_SELF_LOCK,
#   EXCLUSIVE and non-blocking: a second sync refuses instead of queueing,
#   because two syncs reading one finished tree would each mint their own
#   generation name from the clock and two started in the same second would
#   mint the SAME one and overwrite each other's upload.
#
#   Always pipeline-then-sync, never the other way round. Two processes
#   that take two locks in opposite orders deadlock; one order, written
#   down, is the whole fix. Nothing else in this repo takes the sync lock.
#
#   EVERYTHING that reads the source tree happens inside both -- the
#   completion verdict included. The verdict used to be read before the
#   lock, which meant a pipeline re-run could change it in the window
#   between "this night finished clean" and the staging copy, and the data
#   that got pushed would be the data of a run whose verdict was never
#   looked at.
#
# WHAT THE TRANSFER FLAGS GUARANTEE
#   `--no-links --no-devices --no-specials` on every transfer: this sync
#   can create nothing but directories and regular files on the far side.
#   `-a` implies `-l`, which would happily recreate a symlink on the VPS,
#   and `--safe-links` is not enough -- it only drops links that point
#   outside the tree, so a link to a path that exists inside the
#   generation would still be created. The staging step already refuses to
#   copy a non-regular file, and promotion rejects a tree that holds one;
#   these flags are the layer in between, on the wire.
#
#   The vault allowlist defaults to the shared, non-owner slice --
#   `companies/` and `tags.yaml`, which decision D3 keeps as one shared
#   universe and which `migrate_record_owner.py` deliberately never
#   assigns to anybody. `jobs/` is NOT in it: universe postings and the
#   owner's own records live in the same directory and are told apart only
#   by the `owner_id` field inside each file, so shipping the directory
#   would ship owner data. Splitting it needs a content-aware export that
#   does not exist yet; until then prod's universe jobs come from the
#   owner-run seed import (decision 6). `search.yaml` is excluded for the
#   same reason: it indexes owner records too.
#
# THE SSH SIDE (owner work, Part 3 of the deploy runbook -- this script
# creates no keys and holds no credential)
#   On the VPS, the receiving account's ~/.ssh/authorized_keys gets ONE
#   line, write-only and confined to the incoming directory:
#
#     restrict,command="/usr/bin/rrsync -wo /srv/careeros/prod/incoming",\
#     from="203.0.113.7" ssh-ed25519 AAAA...PUBLIC... careeros-sync@lan
#
#   `restrict` turns off forwarding, PTY and agent; `from=` pins the LAN's
#   public egress address (203.0.113.7 is a documentation address --
#   substitute the real one, and drop the clause if the egress is dynamic).
#
#   What `rrsync -wo` is, precisely: it refuses rsync's reading modes and
#   confines every path it is handed to that one directory LEXICALLY. It is
#   not a chroot and not a jail -- there is no kernel boundary here. Three
#   layers do the work, and only together:
#     1. rrsync's path confinement: nothing outside `incoming/` is nameable.
#     2. `--no-links --no-devices --no-specials` on every transfer: nothing
#        but directories and regular files can be created at the far end,
#        so no symlink can be planted to be followed later.
#     3. promotion's own `find ! -type f ! -type d` rejection, on the VPS,
#        after the tree is out of this key's reach: a generation holding a
#        symlink or a special file is deleted rather than served.
#   The private half lives on this host as 0600 in a 0700 directory,
#   unreadable by app users; this script refuses to run if it is looser.
#   Rotation: generate a new pair, add the new line, run this script once
#   by hand, then remove the old line. Revocation: delete the line.
#
# FAILURE
#   Any failure exits non-zero and prints one `ALERT careeros-sync <day>:`
#   line on stdout. When the nightly chains this script, that line lands in
#   the night's log and `sync` joins the `fails:` line (scripts/nightly_pipeline.sh).
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(dirname "$HERE")

DAY="${1:-}"

SYNC_DATA="${SYNC_DATA:-$REPO/data}"
SYNC_DATA="${SYNC_DATA%/}"
SYNC_VAULT="${SYNC_VAULT:-${CAREEROS_VAULT:-}}"
SYNC_VAULT_FILES="${SYNC_VAULT_FILES:-companies tags.yaml}"
SYNC_PROVIDERS="${SYNC_PROVIDERS:-personio greenhouse lever ashby recruitee smartrecruiters}"
SYNC_TARGET="${SYNC_TARGET:-careeros-sync@app.career-os.ch}"
SYNC_SSH_KEY="${SYNC_SSH_KEY:-/root/.ssh/careeros-sync/id_ed25519}"
SYNC_KNOWN_HOSTS="${SYNC_KNOWN_HOSTS:-/root/.ssh/careeros-sync/known_hosts}"
SYNC_SSH_PORT="${SYNC_SSH_PORT:-22}"
SYNC_MIN_POOL_ROWS="${SYNC_MIN_POOL_ROWS:-50}"
SYNC_MIN_CLASSIFIED_ROWS="${SYNC_MIN_CLASSIFIED_ROWS:-50}"
SYNC_MIN_TENANTS="${SYNC_MIN_TENANTS:-1000}"
SYNC_MAX_DELETE="${SYNC_MAX_DELETE:-50}"
SYNC_PIPELINE_LOCK="${SYNC_PIPELINE_LOCK:-$SYNC_DATA/nightly/.pipeline.lock}"
SYNC_SELF_LOCK="${SYNC_SELF_LOCK:-$SYNC_DATA/nightly/.sync.lock}"
SYNC_LOCK_TIMEOUT="${SYNC_LOCK_TIMEOUT:-300}"

#: Every transfer runs with these. See "WHAT THE TRANSFER FLAGS GUARANTEE"
#: in the header: with them this script cannot create a symlink, a device
#: node or a socket on the VPS, whatever is in the staged tree.
RSYNC_SAFE=(-a --no-links --no-devices --no-specials)

STAGE=""
alert() {   # alert <reason...>: the one line the owner reads, then out
  echo "ALERT careeros-sync ${DAY:-?}: $*"
  exit 1
}

cleanup() { [[ -n $STAGE && -d $STAGE ]] && rm -rf "$STAGE"; return 0; }
trap cleanup EXIT

[[ $DAY =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
  || alert "usage: $(basename "$0") <YYYY-MM-DD>; the nightly's day is an argument, never a date this script computes"

# --- 1. the locks, before anything is read -------------------------------
# Nothing above this line has looked at `data/`, and nothing below reads it
# outside these two locks. See "THE TWO LOCKS" in the header: pipeline
# first and shared, then this script's own, exclusive and non-blocking.
#
# The pipeline lock covers the verdict as well as the counts and the copy.
# A tree that is still being written is how a count check passes on a file
# that is half-written a second later -- and a verdict read outside the
# lock is how a clean night's verdict gets paired with a re-run's data.
mkdir -p "$(dirname "$SYNC_PIPELINE_LOCK")" "$(dirname "$SYNC_SELF_LOCK")"
: >>"$SYNC_PIPELINE_LOCK" 2>/dev/null \
  || alert "cannot open the pipeline lock $SYNC_PIPELINE_LOCK"
: >>"$SYNC_SELF_LOCK" 2>/dev/null \
  || alert "cannot open the sync lock $SYNC_SELF_LOCK"
exec 7>>"$SYNC_PIPELINE_LOCK"
flock -s -w "$SYNC_LOCK_TIMEOUT" 7 \
  || alert "a nightly pipeline run still holds $SYNC_PIPELINE_LOCK after ${SYNC_LOCK_TIMEOUT}s; nothing is pushed rather than reading a tree that is still being written"
exec 6>>"$SYNC_SELF_LOCK"
flock -n 6 \
  || alert "another sync is running (it holds $SYNC_SELF_LOCK); refusing to build a second generation out of the same tree"

# --- 1b. the night has to have finished, and finished here ----------------
# The nightly's own day log is the completion manifest: it carries the host
# and the day in its first line and a verdict line per run in it. Read here
# and not earlier, so the verdict and the bytes it vouches for are read
# under one lock.
MANIFEST="$SYNC_DATA/nightly/nightly_$DAY.log"
[[ -f $MANIFEST ]] || alert "no nightly completion manifest at $MANIFEST"
grep -q "^== nightly pipeline $DAY (host $(hostname)" "$MANIFEST" \
  || alert "$MANIFEST does not name this host and day -- refusing to push another host's run"

# The LAST verdict, not any verdict. The day's log is appended to, so a
# night that was re-run after a clean one holds two `== nightly finished`
# lines, and "is there a clean one anywhere in the file" would read a
# broken re-run as a success and push whatever it left behind. The verdict
# that describes the data on disk right now is the final one.
# (`|| true`: no match is an answer here, not a pipeline failure to die on.)
verdict=$(grep -E '^== nightly finished, fails:' "$MANIFEST" | tail -1 || true)
[[ -n $verdict ]] \
  || alert "$MANIFEST holds no nightly verdict line; the night did not get far enough to have one"
[[ $verdict == '== nightly finished, fails: none ==' ]] \
  || alert "the night of $DAY did not finish clean (last verdict: '$verdict'); nothing is pushed"

# --- 2. mandatory files, and counts that are not degenerate ---------------
POOL="$SYNC_DATA/ats/exports/golden_set_pool_$DAY.yaml"
CLASSIFIED="$SYNC_DATA/classification/run_$DAY.yaml"

provider_dir() {   # provider_dir <provider>: personio predates data/ats/
  [[ $1 == personio ]] && { echo "$SYNC_DATA/personio"; return; }
  echo "$SYNC_DATA/ats/$1"
}

missing=()
[[ -s $POOL ]] || missing+=("$POOL")
[[ -s $CLASSIFIED ]] || missing+=("$CLASSIFIED")
for p in $SYNC_PROVIDERS; do
  for f in tenants.yaml runs.yaml; do
    [[ -s "$(provider_dir "$p")/$f" ]] || missing+=("$(provider_dir "$p")/$f")
  done
done
(( ${#missing[@]} == 0 )) || alert "mandatory file(s) missing or empty: ${missing[*]}"

summary_postings() {   # summary_postings <yaml>: the `summary: postings:` count
  local n
  n=$(grep -m1 -E '^  postings: [0-9]+$' "$1" | tr -dc '0-9')
  echo "${n:-0}"
}

pool_rows=$(summary_postings "$POOL")
classified_rows=$(summary_postings "$CLASSIFIED")
tenants=0
for p in $SYNC_PROVIDERS; do
  n=$(grep -m1 -E '^count: [0-9]+$' "$(provider_dir "$p")/tenants.yaml" | tr -dc '0-9')
  tenants=$(( tenants + ${n:-0} ))
done

(( pool_rows >= SYNC_MIN_POOL_ROWS )) \
  || alert "degenerate pool: $pool_rows posting(s) under the ${SYNC_MIN_POOL_ROWS} floor"
(( classified_rows >= SYNC_MIN_CLASSIFIED_ROWS )) \
  || alert "degenerate classification run: $classified_rows posting(s) under the ${SYNC_MIN_CLASSIFIED_ROWS} floor"
(( tenants >= SYNC_MIN_TENANTS )) \
  || alert "degenerate tenant pool: $tenants tenant(s) under the ${SYNC_MIN_TENANTS} floor"

echo "-- source ok: $pool_rows pooled, $classified_rows classified, $tenants tenants"

# --- 3. the credential has to be a credential -----------------------------
[[ -f $SYNC_SSH_KEY ]] || alert "no push key at $SYNC_SSH_KEY (owner work: see this script's header)"
key_mode=$(stat -c '%a' "$SYNC_SSH_KEY")
dir_mode=$(stat -c '%a' "$(dirname "$SYNC_SSH_KEY")")
[[ $key_mode == 600 ]] || alert "$SYNC_SSH_KEY is mode $key_mode, must be 600"
[[ $dir_mode == 700 ]] || alert "$(dirname "$SYNC_SSH_KEY") is mode $dir_mode, must be 700"
[[ -s $SYNC_KNOWN_HOSTS ]] \
  || alert "no pinned host key at $SYNC_KNOWN_HOSTS -- StrictHostKeyChecking=yes would fail anyway"

# --- 4. stage the allowlist, so what is hashed is exactly what is sent ----
# A private copy is the stable snapshot the amendment asks for: the nightly
# is finished, but the owner's own work is not, and rsyncing a live tree
# could send half of a file somebody is editing. 16 MB makes this cheap.
STAGE=$(mktemp -d -t careeros-sync-XXXXXX)
PAYLOAD="$STAGE/payload"
mkdir -p "$PAYLOAD"

stage_item() {   # stage_item <abs src> <relative dest>: copy into the payload
  local src=$1 dest="$PAYLOAD/$2"
  mkdir -p "$(dirname "$dest")"
  cp -a "$src" "$dest"
}

stage_item "$SYNC_DATA/ats/exports" "data/ats/exports"
stage_item "$SYNC_DATA/classification" "data/classification"
for p in $SYNC_PROVIDERS; do
  src=$(provider_dir "$p")
  for f in tenants.yaml runs.yaml; do
    stage_item "$src/$f" "data/${src#"$SYNC_DATA/"}/$f"
  done
done

vault_staged=0
if [[ -n $SYNC_VAULT ]]; then
  [[ -d $SYNC_VAULT ]] || alert "SYNC_VAULT=$SYNC_VAULT is not a directory"
  for f in $SYNC_VAULT_FILES; do
    case $f in
      */*|..|.) alert "SYNC_VAULT_FILES entry '$f' is not a plain name in the vault root" ;;
      secret_key|users|search.yaml|jobs|experiences|interviews|documents)
        alert "SYNC_VAULT_FILES entry '$f' is owner-owned or a credential and may never be synced" ;;
    esac
    [[ -e "$SYNC_VAULT/$f" ]] || alert "vault allowlist entry missing: $SYNC_VAULT/$f"
    stage_item "$SYNC_VAULT/$f" "vault/$f"
    vault_staged=$(( vault_staged + 1 ))
  done
  echo "-- vault: $vault_staged allowlisted item(s) from $SYNC_VAULT"
else
  echo "-- vault: SYNC_VAULT and CAREEROS_VAULT unset, no vault file staged"
fi

# No symlink, no device, no socket leaves here: the VPS side rejects them
# anyway, and finding one now is a bug on this side worth hearing about.
odd=$(find "$PAYLOAD" ! -type f ! -type d -print -quit)
[[ -z $odd ]] || alert "staged tree holds a non-regular file: $odd"
chmod -R u=rwX,go=rX "$PAYLOAD"

# The counts again, on the copy this time. Cheap (two greps) and it closes
# the only window the lock cannot: a count read before the copy describes
# the file that was there then, and what gets uploaded is the copy. If the
# two disagree, something rewrote the tree mid-copy and the generation is
# not one night's output.
staged_pool=$(summary_postings "$PAYLOAD/data/ats/exports/golden_set_pool_$DAY.yaml")
staged_classified=$(summary_postings "$PAYLOAD/data/classification/run_$DAY.yaml")
(( staged_pool == pool_rows && staged_classified == classified_rows )) \
  || alert "the staged copy does not match what was counted (pool $pool_rows -> $staged_pool, classified $classified_rows -> $staged_classified); the tree changed while it was being copied"

# Nothing after this reads `data/`, so the pipeline is free to run again.
# The sync lock (fd 6) is NOT dropped here: it is held to the end of the
# process, because what it protects is the generation name and the upload,
# not the read.
exec 7>&-

# --- 5. the manifest: the generation's identity and its checksums ---------
# Only the time part of the generation name is read from the clock. The day
# is the argument, so a run that starts after midnight still files under
# the night it belongs to.
GEN="${DAY}T$(date -u +%H%M%SZ)"
{
  echo "# careeros pipeline generation manifest"
  echo "generation: $GEN"
  echo "day: $DAY"
  echo "source: $(hostname)"
  echo "pool_postings: $pool_rows"
  echo "classified_postings: $classified_rows"
  echo "tenants: $tenants"
  echo "vault_items: $vault_staged"
  echo "--"
} >"$PAYLOAD/MANIFEST"
( cd "$PAYLOAD" && find . -type f ! -name MANIFEST -printf '%P\n' | LC_ALL=C sort \
    | xargs -r sha256sum >>"$PAYLOAD/MANIFEST" )
echo "-- generation $GEN staged, $(( $(wc -l <"$PAYLOAD/MANIFEST") - 9 )) file(s)"

# --- 6. upload ------------------------------------------------------------
ssh_cmd="ssh"
for opt in -i "$SYNC_SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
           -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$SYNC_KNOWN_HOSTS" \
           -o PasswordAuthentication=no -o PubkeyAuthentication=yes \
           -o ClearAllForwardings=yes -o RequestTTY=no -p "$SYNC_SSH_PORT"; do
  ssh_cmd+=" $(printf '%q' "$opt")"
done

# `--delete` is scoped to the incoming generation directory and nothing
# else; a generation name is unique, so the only thing it can ever remove
# is the debris of an interrupted push to the SAME name. Anything above
# the threshold means the name is not what this script thinks it is.
#
# A dry run that FAILS is not a dry run that found nothing. It used to be
# read as one -- stderr discarded, `|| true`, and `grep -c` on an empty
# stream answering 0 -- so a refused connection, a wrong host key or an
# rrsync that denied the path all came out as "zero deletions" and the
# destructive transfer ran next with nobody having inspected anything.
dry_rc=0
rsync -ni --delete --dry-run "${RSYNC_SAFE[@]}" -e "$ssh_cmd" \
      "$PAYLOAD/" "$SYNC_TARGET:$GEN/" >"$STAGE/dryrun.out" 2>"$STAGE/dryrun.err" \
  || dry_rc=$?
if (( dry_rc != 0 )); then
  alert "the deletion dry run failed (rsync exit $dry_rc: $(tr '\n' ' ' <"$STAGE/dryrun.err")) -- refusing to transfer without knowing what it would delete"
fi
deletions=$(grep -c '^\*deleting' "$STAGE/dryrun.out" || true)
if (( deletions > SYNC_MAX_DELETE )); then
  alert "the dry run would delete $deletions file(s) inside incoming/$GEN, over the ${SYNC_MAX_DELETE} threshold -- aborting instead of propagating"
fi

# `--max-delete` is the same threshold again, enforced by rsync itself
# during the real transfer: the dry run describes the far side as it was a
# moment ago, and this is what covers the moment in between. Over it,
# rsync stops rather than finishing the deletions.
rsync "${RSYNC_SAFE[@]}" --delete --max-delete="$SYNC_MAX_DELETE" \
      --no-owner --no-group --chmod=D750,F640 \
      -e "$ssh_cmd" "$PAYLOAD/" "$SYNC_TARGET:$GEN/" \
  || alert "rsync of generation $GEN failed; prod keeps serving its last promoted generation"

# The marker is a second, tiny transfer with no --delete: rsync gives no
# ordering guarantee inside one run, so a COMPLETE that travelled with the
# payload could land before the data it vouches for.
mkdir -p "$STAGE/marker"
echo "$GEN" >"$STAGE/marker/COMPLETE"
chmod 640 "$STAGE/marker/COMPLETE"
rsync "${RSYNC_SAFE[@]}" --no-owner --no-group --chmod=F640 \
      -e "$ssh_cmd" "$STAGE/marker/COMPLETE" "$SYNC_TARGET:$GEN/COMPLETE" \
  || alert "generation $GEN uploaded but its COMPLETE marker did not; the VPS will not promote a generation it cannot see finished"

echo "-- sync ok: generation $GEN is complete in incoming on $SYNC_TARGET"
echo "-- promotion is the VPS's own step: deploy/promote_incoming.sh $GEN"
