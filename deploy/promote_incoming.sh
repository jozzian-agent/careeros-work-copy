#!/bin/bash
# Promote one uploaded pipeline generation on the VPS (Amendment 1).
#
# WHAT IT DOES
#   Runs on the prod VPS, locally, as the prod account -- never over the
#   uploader's SSH key. That separation is the point: the LAN key can only
#   write into `incoming/`, so the thing that decides what prod serves is a
#   local step the uploader cannot reach (Amendment 1, "upload/promotion
#   separation").
#
#   For one generation it: takes exclusive control of it, refuses it unless
#   the uploader finished it, MOVES it next to the live generations on the
#   same filesystem, puts it in its final ownership and modes, and only
#   then validates -- the manifest against the bytes on disk, no symlinks,
#   no special files, no unlisted extras, no path pointing outside the
#   tree, the mandatory files parsing to a real document whose OWN records
#   are counted, floored and checked for being records at all, the manifest
#   header's counts matching those parsed counts -- then looks once more
#   (checksums again, nothing stamped meaningfully later than the COMPLETE
#   marker, and no process still holding a file in the tree open) and swaps
#   the `current` pointer by renaming a temporary symlink over it. A reader
#   either sees the whole old generation or the whole new one; there is no
#   instant in which it sees half of either.
#
# WHY IT MOVES BEFORE IT VALIDATES
#   Validating in `incoming/` and promoting afterwards is a
#   time-of-check/time-of-use hole: `incoming/` is the one directory the
#   uploader's key can write, so bytes that passed sha256sum could be
#   rewritten in the window between the check and the move, and what got
#   promoted would be bytes nothing ever vouched for. The move closes it.
#   `mv` of a finished generation is a rename on one filesystem, it costs
#   nothing, and the uploader's rrsync confinement cannot reach
#   `generations/` -- so every check runs on bytes the uploader can no
#   longer NAME. A generation that fails validation after the move is
#   deleted: it was never pointed at, no reader could have been inside it,
#   and leaving it would let the next run promote it by name.
#
# THE RESIDUAL WINDOW, HONESTLY
#   A rename revokes names, not file descriptors. An rsync receiver that
#   still has a payload file open for writing when the move happens keeps
#   writing into the moved file through that fd, and no check this script
#   can run will revoke it -- there is no userspace way to close another
#   process's descriptor. The same is true of the `chown`: it only runs
#   when this script is root, and a file's open fds survive it either way.
#   So the move is a strong boundary against a NEW write (nothing can open
#   the path again) and no boundary at all against an OLD one.
#
#   A descriptor cannot be revoked, but its holder can be SEEN. Three
#   things run immediately before the swap, and together they close the
#   window in practice:
#
#     1. the generation is checksummed again, so any writer that changed
#        the bytes at any point after validation is caught;
#     2. no payload file may be stamped more than 120s after the COMPLETE
#        marker that travelled with it -- a file written after the upload
#        finished. The tolerance is there because rsync preserves the
#        SOURCE's mtimes, so legitimate payload files are older than the
#        marker and only NTP skew between the LAN host and this one can
#        make them look slightly newer. Two minutes of skew is a clock, two
#        hundred is a writer;
#     3. no process may hold any file under the generation open (`fuser`,
#        or `lsof +D` where fuser is absent; with neither installed this
#        script refuses to promote, because a quiescence check that cannot
#        run is not one that passed). That is the one that actually catches
#        the open-fd case: a transfer which started before the move is
#        still running, and a running holder is visible in /proc even
#        though its descriptor is untouchable. The generation is destroyed
#        and the holding PIDs are named in the alert.
#
#   What is left after that is theoretical rather than practical: an
#   attacker who already has code execution as the uploading account could
#   fork a holder that has exited by the time the check runs while its
#   descriptor lives on somewhere (passed over a unix socket, kept by a
#   process outside this tree's view). Out of scope: that account's key is
#   confined to `rrsync -wo incoming/` and gets no shell, so there is
#   nothing there to run code with, and an attacker who HAS a shell on the
#   VPS does not need this window for anything.
#
#   The structural answer, which is the one that holds without any of the
#   above, is the COMPLETE marker: it is pushed as its own transfer after
#   the payload rsync has exited, so a generation this script will look at
#   is one whose uploading process has already closed every fd it had. A
#   generation whose upload is still running has no marker and is refused
#   outright.
#
#   The generation that was current is kept, and its clock restarts at the
#   swap, so requests already reading it have DEPLOY_DRAIN_SECONDS to
#   finish before anything is removed.
#
# WHAT IT MUST NEVER TOUCH
#   * The prod vault. Owner-edited records are prod-authoritative (owner
#     decision 1) and are not in this tree at all: a promoted generation
#     holds pipeline output only, so promotion can never overwrite or
#     delete an application, a status, a note or a CV. Applying the
#     shared vault files a generation carries is a separate owner-run step
#     (decision 6), not this script's business.
#   * Code, releases, `/etc`, backups, the uploader's key.
#   * A generation that is being uploaded, or one that is current.
#
# ARGUMENTS
#   $1  generation name (e.g. 2026-10-22T193005Z). Optional: with no
#       argument the newest COMPLETE generation in incoming is promoted.
#
# ENVIRONMENT
#   DEPLOY_INCOMING        where the LAN uploads  (/srv/careeros/prod/incoming)
#   DEPLOY_ROOT            fixed root holding `generations/` and the
#                          `current` pointer     (/srv/careeros/prod/pipeline)
#   DEPLOY_LOCK            deploy.sh's lock          (/run/careeros/deploy.lock)
#   DEPLOY_DATA_LOCK       promotion/backup lock
#                                        (/run/careeros/careeros-data.lock)
#   DEPLOY_DRAIN_SECONDS   how long the generation that was current is
#                          kept after the swap                       (900)
#   DEPLOY_OWNER           user:group for the promoted tree; applied only
#                          when this runs as root           (careeros-prod)
#   PROMOTE_PYTHON         a python that can `import yaml`, used to parse
#                          and COUNT the two mandatory files. The release
#                          venv's interpreter is the safe choice on a VPS
#                          where the system python has no PyYAML:
#                          /srv/careeros/prod/app/.venv/bin/python
#                                                              (python3)
#   PROMOTE_MIN_POOL_ROWS       floor for the pool postings counted out
#                               of the payload                        (50)
#   PROMOTE_MIN_CLASSIFIED_ROWS floor for the classified postings      (50)
#   PROMOTE_MIN_TENANTS         floor for the tenant RECORDS summed out of
#                               the generation's parsed tenants.yaml
#                               files -- the entries of each file's
#                               `tenants:` list, not its `count:` header
#                                                                   (1000)
#                          The three default to the SYNC_MIN_* floors the
#                          LAN side applies, so the VPS re-checks the same
#                          numbers rather than trusting that it did. Every
#                          one of them is enforced against a number read
#                          out of the PAYLOAD, never out of the manifest
#                          header -- the header is the uploader's claim and
#                          only has to agree with the payload.
#   PROMOTE_EXPECTED_SOURCE when set, the manifest's `source:` host must
#                          equal it; unset, `source:` only has to be
#                          non-empty                               (unset)
#
# THE TWO LOCKS, AND WHY THERE ARE TWO
#   DEPLOY_LOCK is the shared convention with deploy.sh: both take it with
#   `flock -n`, so whoever has it runs and the other refuses rather than
#   queues. A release and a promotion must never interleave.
#   DEPLOY_DATA_LOCK is held across the swap and is the same lock
#   deploy/backup_prod.sh holds for the whole of its run, so a backup can
#   never catch a half-swapped pointer and a promotion can never land
#   between a backup's publish and its prune. A promotion that collides
#   with a running backup refuses and waits for the next cron tick --
#   `flock -n`, not a queue. It has to be a second
#   lock: deploy.sh calls deploy/pre_deploy_backup.sh while it already
#   holds DEPLOY_LOCK, and a backup waiting on the deploy lock would
#   deadlock the release it was protecting.
#
# STALE-SYNC ALERTING comes free from the pointer: the day a promoted
#   generation belongs to is the first ten characters of
#   `readlink current`, so "nothing has synced for more than 36 hours" is
#   readable on the VPS without logging one line of personal content.
#
# FAILURE
#   Non-zero exit and one `ALERT careeros-promote <generation>:` line. The
#   `current` pointer is left exactly where it was; prod keeps serving. If
#   the generation had already been moved out of `incoming/`, the moved
#   copy is removed, so a rejected generation cannot be promoted later by
#   name and cannot fill the disk.
set -euo pipefail

DEPLOY_INCOMING="${DEPLOY_INCOMING:-/srv/careeros/prod/incoming}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/srv/careeros/prod/pipeline}"
DEPLOY_LOCK="${DEPLOY_LOCK:-/run/careeros/deploy.lock}"
DEPLOY_DATA_LOCK="${DEPLOY_DATA_LOCK:-/run/careeros/careeros-data.lock}"
DEPLOY_DRAIN_SECONDS="${DEPLOY_DRAIN_SECONDS:-900}"
#   An empty DEPLOY_OWNER (set, but empty) leaves ownership alone, which is
#   what a rehearsal or a test run on a host with no careeros-prod account
#   needs. Unset is the production default.
DEPLOY_OWNER="${DEPLOY_OWNER-careeros-prod}"
PROMOTE_PYTHON="${PROMOTE_PYTHON:-python3}"
PROMOTE_MIN_POOL_ROWS="${PROMOTE_MIN_POOL_ROWS:-50}"
PROMOTE_MIN_CLASSIFIED_ROWS="${PROMOTE_MIN_CLASSIFIED_ROWS:-50}"
PROMOTE_MIN_TENANTS="${PROMOTE_MIN_TENANTS:-1000}"

GEN="${1:-}"
WORK=""
#: The generation's final directory, once it has been moved there and
#: while it is still unvalidated. A failure from here on removes it: it was
#: never pointed at, so nothing can have been reading it. Cleared again at
#: the swap, after which this directory is what prod serves.
MOVED=""

alert() {
  echo "ALERT careeros-promote ${GEN:-?}: $*"
  if [[ -n $MOVED && -d $MOVED ]]; then
    rm -rf "$MOVED"
    echo "-- rejected generation removed from $MOVED; the current pointer was never touched"
  fi
  exit 1
}

cleanup() { [[ -n $WORK && -d $WORK ]] && rm -rf "$WORK"; return 0; }
trap cleanup EXIT

[[ -d $DEPLOY_INCOMING ]] || alert "no incoming directory at $DEPLOY_INCOMING"

# --- 1. which generation --------------------------------------------------
if [[ -z $GEN ]]; then
  GEN=$(cd "$DEPLOY_INCOMING" && \
        find . -mindepth 2 -maxdepth 2 -name COMPLETE -printf '%h\n' 2>/dev/null \
        | sed 's|^\./||' | LC_ALL=C sort | tail -1)
  [[ -n $GEN ]] || alert "no COMPLETE generation waiting in $DEPLOY_INCOMING"
fi
[[ $GEN =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z$ ]] \
  || alert "'$GEN' is not a generation name (YYYY-MM-DDTHHMMSSZ)"

SRC="$DEPLOY_INCOMING/$GEN"
[[ -d $SRC && ! -L $SRC ]] || alert "$SRC is not a directory"

# --- 2. locks -------------------------------------------------------------
mkdir -p "$(dirname "$DEPLOY_LOCK")" "$(dirname "$DEPLOY_DATA_LOCK")"
# Probed before `exec`, because a redirection `exec` cannot open ends the
# shell outright and the owner would get an exit code with no alert line.
: >>"$DEPLOY_LOCK" 2>/dev/null || alert "cannot open the deploy lock $DEPLOY_LOCK"
: >>"$DEPLOY_DATA_LOCK" 2>/dev/null || alert "cannot open the data lock $DEPLOY_DATA_LOCK"
exec 8>>"$DEPLOY_LOCK"
flock -n 8 || alert "a release holds $DEPLOY_LOCK; promotion waits for the next run rather than interleaving with a deploy"
exec 9>>"$DEPLOY_DATA_LOCK"
flock -n 9 || alert "another promotion or a backup holds $DEPLOY_DATA_LOCK"

# --- 3. the uploader has to have finished ---------------------------------
# Only the separately-pushed marker says so. rsync gives no ordering
# guarantee inside one transfer, so "the manifest is there" is not enough.
[[ -f $SRC/COMPLETE && ! -L $SRC/COMPLETE ]] \
  || alert "incomplete generation: no COMPLETE marker, the upload is still running or died"
[[ -f $SRC/MANIFEST && ! -L $SRC/MANIFEST ]] || alert "no MANIFEST in the generation"

# --- 4. out of the uploader's reach, THEN validated -----------------------
# Everything in this section has to happen before the move, because after
# it there is no `incoming` copy left to compare against.
mkdir -p "$DEPLOY_ROOT/generations"
# Same filesystem or nothing: a copy across devices is not a rename, and a
# rename is the whole reason the swap cannot be seen half done.
[[ $(stat -c '%d' "$SRC") == $(stat -c '%d' "$DEPLOY_ROOT/generations") ]] \
  || alert "$DEPLOY_INCOMING and $DEPLOY_ROOT are on different filesystems; an atomic promotion is impossible until they share one"
[[ -e "$DEPLOY_ROOT/generations/$GEN" ]] \
  && alert "generation $GEN is already promoted; refusing to replace a live generation"

previous=""
[[ -L "$DEPLOY_ROOT/current" ]] && previous=$(basename "$(readlink "$DEPLOY_ROOT/current")")

DEST="$DEPLOY_ROOT/generations/$GEN"
mv "$SRC" "$DEST" || alert "cannot move the generation to $DEST"
MOVED="$DEST"

# Ownership and modes FIRST, before a single check reads the tree, so that
# what validation looks at is the tree in its final shape rather than the
# uploader's. Neither touches an mtime (both move ctime only), which is
# what lets the pre-swap check below compare mtimes against COMPLETE.
find "$DEST" -type d -exec chmod 750 {} +
find "$DEST" -type f -exec chmod 640 {} +
if [[ $(id -u) == 0 && -n $DEPLOY_OWNER ]]; then
  chown -R "$DEPLOY_OWNER" "$DEST" \
    || alert "cannot give the generation to $DEPLOY_OWNER"
fi
echo "-- moved to $DEST, where the uploader cannot name it; validating there"

# --- 5. validate, on bytes the uploader can no longer name ----------------
odd=$(find "$DEST" ! -type f ! -type d -print -quit)
[[ -z $odd ]] || alert "refusing a generation that holds a symlink or special file: $odd"

header_gen=$(sed -n 's/^generation: //p' "$DEST/MANIFEST" | head -1)
header_day=$(sed -n 's/^day: //p' "$DEST/MANIFEST" | head -1)
header_source=$(sed -n 's/^source: //p' "$DEST/MANIFEST" | head -1)
[[ $header_gen == "$GEN" ]] \
  || alert "the manifest names generation '$header_gen', the directory is '$GEN'"
[[ $GEN == "$header_day"T* ]] \
  || alert "the manifest's day '$header_day' does not match the generation name"
[[ $(cat "$DEST/COMPLETE") == "$GEN" ]] \
  || alert "the COMPLETE marker does not name this generation"

# The source host is in the manifest header, which is not checksummed --
# it cannot be, it carries the checksums. So it is identity, not proof;
# PROMOTE_EXPECTED_SOURCE is what turns it into a stated expectation the
# VPS will refuse to deviate from.
[[ -n $header_source ]] || alert "the manifest names no source host"
if [[ -n ${PROMOTE_EXPECTED_SOURCE:-} ]]; then
  [[ $header_source == "$PROMOTE_EXPECTED_SOURCE" ]] \
    || alert "the manifest's source is '$header_source', not the expected '$PROMOTE_EXPECTED_SOURCE'"
fi

WORK=$(mktemp -d -t careeros-promote-XXXXXX)
awk 'body; /^--$/ {body=1}' "$DEST/MANIFEST" >"$WORK/sums"
[[ -s $WORK/sums ]] || alert "the manifest lists no file"

# Every listed path must be a plain relative path inside the tree, and
# every file in the tree must be listed: an extra file nothing vouches for
# is exactly what a hostile or interrupted upload leaves behind.
cut -c 67- "$WORK/sums" | LC_ALL=C sort >"$WORK/listed"
while read -r path; do
  case $path in
    /*|*..*|'') alert "the manifest lists an unsafe path: '$path'" ;;
  esac
done <"$WORK/listed"
( cd "$DEST" && find . -type f ! -name MANIFEST ! -name COMPLETE -printf '%P\n' ) \
  | LC_ALL=C sort >"$WORK/present"
if ! diff -q "$WORK/listed" "$WORK/present" >/dev/null; then
  alert "the tree and the manifest disagree: $(diff "$WORK/listed" "$WORK/present" | tr '\n' ' ')"
fi

( cd "$DEST" && sha256sum --quiet -c "$WORK/sums" ) >/dev/null \
  || alert "checksum mismatch: the uploaded bytes are not the ones the manifest vouches for"

# Schema: the two files the serving app reads for the day have to be in
# there, under the names the pipeline writes.
POOL_REL="data/ats/exports/golden_set_pool_$header_day.yaml"
CLASSIFIED_REL="data/classification/run_$header_day.yaml"
for required in "$POOL_REL" "$CLASSIFIED_REL"; do
  grep -qxF "$required" "$WORK/listed" \
    || alert "the generation is missing a mandatory file: $required"
done

# --- 5b. content, not just bytes -----------------------------------------
# A checksum proves the bytes arrived; it says nothing about whether they
# are usable. An empty file, or a truncated one that was already empty or
# broken when the manifest was written, checksums perfectly and would make
# prod serve a day with no jobs in it.
#
# `yaml.safe_load` returning something truthy is not validation either: the
# file `x` parses, to the string 'x', and passes. So every file counted here
# has to parse to a mapping or a sequence, and the floors are enforced
# against the number of records COUNTED IN THE PAYLOAD -- the length of the
# top-level `postings:` list the pipeline writes in both files the app reads
# (careeros classification run and golden-set pool export), and the
# `tenants:` list in each per-provider tenants.yaml.
#
# A LIST IS NOT A LIST OF RECORDS, either: `postings: [x, y]` is a two-entry
# list and would satisfy a floor of two. Every counted entry has to be a
# mapping carrying the one key everything downstream reads it by --
# scripts/import_pool_to_vault.py indexes both posting exports by `key` and
# drops a row that has none, and a tenant is nothing without its `tenant`.
#
# The manifest header's counts are then only a claim, which has to agree
# with that count or the generation is refused: a header that disagrees with
# the bytes it travelled with is a manifest lying about its payload, and an
# OMITTED header count is no longer a way past the floor -- nothing is
# enforced against the header any more. Each tenants.yaml's own `count:`
# line is the same kind of claim about the same kind of list, and gets the
# same treatment.
cat >"$WORK/yamlcount.py" <<'PYEOF'
"""Print the record count of one pipeline export, or exit with a reason.

argv[1] is the file, argv[2] the key its records live under, argv[3] the
one key every one of those records has to carry.

argv[1] has to parse to a mapping or a sequence -- a bare scalar is what
`yaml.safe_load` happily returns for a file holding one word, and treating
that as "valid YAML" is how a day with no jobs in it gets promoted. The
number printed here is read out of the document itself and is what the
floors are applied to.
"""
import sys

import yaml

path, records_key, record_key = sys.argv[1:4]

try:
    with open(path) as handle:
        document = yaml.safe_load(handle)
except Exception as error:                       # a parse error, or an unreadable file
    sys.exit(f'{type(error).__name__}: {error}')

if not document:
    sys.exit('it parses, but to an empty document')
if not isinstance(document, (dict, list)):
    sys.exit(f'it parses to a bare {type(document).__name__}, not a mapping or a '
             f'sequence of records -- a scalar is not a pipeline export')
if isinstance(document, list):
    records = document
elif records_key in document:
    records = document[records_key]
    if not isinstance(records, list):
        sys.exit(f"its '{records_key}:' key holds a {type(records).__name__}, "
                 'not a list of records')
else:
    sys.exit(f"it holds no '{records_key}:' key, so it is not one of the exports the "
             f"app reads (top-level keys: {', '.join(map(str, document)) or 'none'})")

# `[a, b]` is a list of two things and not a list of two records. Every
# entry has to be a mapping, and has to carry the key the rest of the
# system identifies it by, or the count is a count of nothing usable.
for index, record in enumerate(records):
    if not isinstance(record, dict):
        sys.exit(f"entry {index} of '{records_key}:' is a bare "
                 f'{type(record).__name__}, not a record')
    if record_key not in record:
        sys.exit(f"entry {index} of '{records_key}:' has no '{record_key}:' key, "
                 'which is what everything downstream reads it by')
print(len(records))
PYEOF

#: Set by count_records, because a function that alerts cannot return its
#: answer through a command substitution: `$(...)` is a subshell, and the
#: alert line -- the one thing the owner reads -- would be captured into the
#: assignment instead of printed.
RECORDS=0
count_records() {   # count_records <relative path> <records key> <record key>
  local out
  out=$("$PROMOTE_PYTHON" "$WORK/yamlcount.py" "$DEST/$1" "$2" "$3" 2>&1) \
    || alert "$1 is not a usable YAML document -- $out"
  [[ $out =~ ^[0-9]+$ ]] \
    || alert "$1: the record count did not come back as a number -- '$out'"
  RECORDS=$out
}

count_records "$POOL_REL" postings key;       pool_rows=$RECORDS
count_records "$CLASSIFIED_REL" postings key; classified_rows=$RECORDS

# Tenants have no single file to parse: the records live in the
# per-provider `tenants.yaml` files, so each is parsed and counted exactly
# like the two exports above and the floor is applied to the SUM. Counted
# out of the payload for the same reason -- those files are in the
# manifest, so they are bytes that have been vouched for.
#
# The `count:` line in each file is its writer's claim about its own list,
# which `count: 1000` over `tenants: []` showed is not a count: so where it
# is there, it has to agree with the records that are there, and where it is
# not, the parsed count stands on its own. Nothing is enforced against a
# header any more, here or in the manifest.
tenants=0
tenant_files=0
while read -r relative; do
  count_records "$relative" tenants tenant
  # `sed | head` and not `grep`: under `set -o pipefail` a grep that
  # matches nothing fails the pipeline, which fails the ASSIGNMENT, which
  # under `set -e` would kill the script with an exit code, no alert line
  # and a moved generation left behind for the next run to promote by name.
  claimed_tenants=$(sed -n 's/^count: \([0-9]\{1,\}\)$/\1/p' "$DEST/$relative" | head -1)
  if [[ -n $claimed_tenants ]]; then
    (( claimed_tenants == RECORDS )) \
      || alert "$relative says count: $claimed_tenants but its tenants list holds $RECORDS record(s) -- the file does not describe its own payload"
  fi
  tenants=$(( tenants + RECORDS ))
  tenant_files=$(( tenant_files + 1 ))
done < <(grep -E '(^|/)tenants\.yaml$' "$WORK/listed" || true)

floor() {   # floor <label> <counted value> <minimum>: refuse a degenerate day
  (( $2 >= $3 )) \
    || alert "degenerate $1: $2 under the $3 floor -- refusing to promote a night that lost its data"
}
floor pool_postings "$pool_rows" "$PROMOTE_MIN_POOL_ROWS"
floor classified_postings "$classified_rows" "$PROMOTE_MIN_CLASSIFIED_ROWS"
floor tenants "$tenants" "$PROMOTE_MIN_TENANTS"

header_claim() {   # header_claim <manifest key> <counted value>
  local claimed
  claimed=$(sed -n "s/^$1: //p" "$DEST/MANIFEST" | head -1)
  if [[ -z $claimed ]]; then
    echo "-- $1: the manifest header claims nothing; the payload's own count $2 stands"
    return 0
  fi
  [[ $claimed =~ ^[0-9]+$ ]] || alert "the manifest header's $1 is not a number: '$claimed'"
  (( claimed == $2 )) \
    || alert "the manifest header claims $1: $claimed, the payload holds $2 -- the manifest does not describe the bytes it travelled with"
}
header_claim pool_postings "$pool_rows"
header_claim classified_postings "$classified_rows"
header_claim tenants "$tenants"

echo "-- generation $GEN validated: $(wc -l <"$WORK/listed") file(s) from $header_source, day $header_day, $pool_rows pooled, $classified_rows classified, $tenants tenants in $tenant_files file(s)"

# --- 6. the last look, then the swap -------------------------------------
# Everything above ran on a tree the uploader can no longer NAME, which is
# not the same as a tree nobody can still WRITE: a rename does not revoke an
# already-open descriptor (see "THE RESIDUAL WINDOW, HONESTLY"). So the
# generation is read once more, here, with nothing but two builtins between
# this and the pointer move.
#
# Three checks, because they catch different writers: the checksums catch
# anything that changed the bytes; the mtime comparison catches a writer
# that changed them and restored the hash -- or one that rewrote a file the
# manifest's own line was never going to disagree with; and the quiescence
# check catches the one neither of those can, a transfer that started before
# the move and is still holding an fd this script cannot revoke.
( cd "$DEST" && sha256sum --quiet -c "$WORK/sums" ) >/dev/null \
  || alert "the generation changed between validation and the swap: it no longer matches its own checksums. Nothing was promoted"

# COMPLETE is the reference because it travels in the tree and is pushed
# last, after the payload transfer exited. rsync preserves the SOURCE's
# mtimes, so a legitimate payload file is OLDER than the marker; a file that
# looks a little newer is NTP skew between the LAN host and this one, and a
# file that looks minutes newer was written here, after the upload finished.
# Hence a tolerance rather than a bare `-newer`: a clock that disagrees by
# seconds must not reject a good night.
complete_mtime=$(stat -c '%Y' "$DEST/COMPLETE")
late=$(find "$DEST" -type f ! -name COMPLETE \
            -newermt "@$(( complete_mtime + 120 ))" -print -quit)
[[ -z $late ]] \
  || alert "the generation holds a file stamped more than 120s after its COMPLETE marker ($late); something wrote into it after the upload finished. Nothing was promoted"

# QUIESCENCE. A rename cannot revoke a descriptor, but it cannot hide its
# holder either: a process that still has a file in this tree open is in
# /proc, whatever it has the file open FOR. Either tool answers the
# question; with neither installed this refuses to promote, because a check
# that cannot run has not passed. The same rule applies to a scan that
# STARTS but cannot finish: an inspection error is not "no holders", and
# treating it as one would fail this check open.
#
# VISIBILITY CAVEAT, stated plainly: fuser and lsof answer from /proc, and
# a non-root user only sees its OWN processes there. Run as the prod
# account, this scan proves quiescence only against the prod account's own
# descriptors; seeing the uploader's requires root (or a /proc without
# hidepid). The runbook says so where it says who runs this script, and
# the note below repeats it at run time. It is a warning, not a refusal,
# because refusing would make the script unusable under its documented
# identity -- but an operator who cares about the cross-user window runs
# promotion as root.
if command -v fuser >/dev/null 2>&1; then
  #: fuser on the generation's FILES, not `-m $DEST`: on Linux `-m` means
  #: "everything open on that file system", which on a VPS where incoming/
  #: and the app share a disk is every process on the box.
  holders=""
  while IFS= read -r -d '' f; do
    # set -e would kill the script on a bare assignment whose command
    # substitution exits non-zero -- and exit 1 (no holder) is the COMMON
    # case. Capture the status through the || arm instead.
    if out=$(fuser "$f" 2>/dev/null); then rc=0; else rc=$?; fi
    case $rc in
      0) holders+="${out:+ $out}" ;;   # fuser lists holders, exit 0
      1) ;;                            # exit 1 = nobody holds it
      *) alert "fuser could not inspect $f (exit $rc); a quiescence scan that could not run has not passed. Nothing was promoted" ;;
    esac
  done < <(find "$DEST" -type f -print0)
elif command -v lsof >/dev/null 2>&1; then
  if holders=$(lsof -t +D "$DEST" 2>/dev/null); then rc=0; else rc=$?; fi
  # lsof: 0 = something listed, 1 = nothing listed. Anything else is an
  # inspection error, and an error is not an empty answer.
  [[ $rc -le 1 ]] \
    || alert "lsof could not inspect the generation (exit $rc); a quiescence scan that could not run has not passed. Nothing was promoted"
  holders=$(printf '%s' "$holders" | LC_ALL=C sort -un | tr '\n' ' ')
else
  alert "neither fuser nor lsof is installed, so this host cannot tell whether anything still holds the generation open; refusing to promote a tree whose quiescence cannot be established (apt install psmisc). Nothing was promoted"
fi
[[ $EUID -eq 0 ]] \
  || echo "-- note: running as $(id -un); the quiescence scan sees only this user's descriptors (run as root to also see the uploader's)"
[[ -z ${holders//[[:space:]]/} ]] \
  || alert "the generation is still open in another process (pid(s) ${holders% }); a transfer that started before the move keeps writing through a descriptor no rename can revoke. Nothing was promoted"

ln -s "generations/$GEN" "$DEPLOY_ROOT/.current.$$"
mv -T "$DEPLOY_ROOT/.current.$$" "$DEPLOY_ROOT/current"
# Past this line the moved directory is what prod serves, so a later
# failure must never delete it.
MOVED=""
echo "-- current -> generations/$GEN"

# --- 7. drain, then prune -------------------------------------------------
# The generation that was current has its clock restarted here, not at
# upload time: the readers that matter are the ones that were inside it
# when the pointer moved.
if [[ -n $previous && -d "$DEPLOY_ROOT/generations/$previous" ]]; then
  touch "$DEPLOY_ROOT/generations/$previous"
  echo "-- previous generation $previous kept for ${DEPLOY_DRAIN_SECONDS}s while readers drain"
fi
now=$(date -u +%s)
for dir in "$DEPLOY_ROOT"/generations/*; do
  [[ -d $dir ]] || continue
  name=$(basename "$dir")
  [[ $name == "$GEN" ]] && continue
  age=$(( now - $(stat -c '%Y' "$dir") ))
  if (( age >= DEPLOY_DRAIN_SECONDS )); then
    rm -rf "$dir"
    echo "-- pruned generation $name (${age}s since it stopped being current)"
  fi
done

echo "-- promote ok: prod serves generation $GEN"
