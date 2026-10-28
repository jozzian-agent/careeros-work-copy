#!/bin/bash
# Prod backups on the VPS: compressed, public-key encrypted, pruned by age
# and count (Amendment 2, replacing "keep the last 14" vault backups).
#
# WHAT IT DOES
#   One mode per failure mode, chosen by a flag:
#
#   --full         The prod-synced subset: the generation prod is serving.
#                  Sunday's job. Keeps 5 (~1 month at one a week).
#                  Skippable while prod has no pipeline generation yet:
#                  BACKUP_FULL_ENABLED=0, below.
#   --owner-data   The prod-authoritative slice -- the prod vault, which is
#                  where applications, statuses, notes and CVs live once
#                  editing begins in prod (owner decision 1). Daily job.
#                  Keeps 30.
#   --check-stale  Creates nothing. Exits non-zero if the newest full
#                  backup is older than BACKUP_STALE_FULL_DAYS or the
#                  newest owner-data backup older than
#                  BACKUP_STALE_OWNER_DAYS. This is the alarm that makes a
#                  backup job which silently stopped running visible.
#
#   Every archive is `tar | zstd | age -R` in ONE stream: no plaintext and
#   no unencrypted compressed file is ever written to disk, not even
#   briefly, and the VPS holds only the encryption (public) key. It can
#   create backups and can never open them (owner decision 3; the recovery
#   key is offline with the owner).
#
#   Each archive gets a manifest beside it, `<archive>.sha256`, in
#   `sha256sum -c` format, which is what deploy/pull_backups_lan.sh
#   verifies the pulled copy against.
#
# WHAT IT MUST NEVER TOUCH
#   * The data it reads. Sources are opened read-only; nothing is moved,
#     rotated or deleted inside the vault or a generation.
#   * The live pointer. It holds DEPLOY_DATA_LOCK from before it creates
#     anything until it exits, so a promotion cannot swap `current`
#     underneath it and a second backup of the same namespace cannot
#     interleave its publish and prune with this one's -- but it never
#     writes the pointer itself.
#   * Plaintext. If `age` or the recipient file is missing the script FAILS
#     and writes nothing. There is no "unencrypted fallback" path here on
#     purpose: a fallback is how an unencrypted copy of somebody's job
#     history ends up on a rented VPS.
#   * An archive that has not been verified. Pruning happens only after a
#     new archive is created, read back and checksummed.
#
# HOW FAR THE VERIFICATION HONESTLY GOES
#   A decrypt-check is impossible here BY DESIGN -- the private key is not
#   on this machine. So what this script verifies is: tar, zstd and age all
#   exited 0 (the pipeline's whole status, not just the last stage); the
#   archive is at least BACKUP_MIN_BYTES; and the bytes on disk read back
#   to the sha256 recorded in the manifest. The zstd frame also carries its
#   own content checksum, so a truncated or bit-rotted archive is detectable
#   at restore time.
#   What this CANNOT tell you: that the recipient key is one the owner
#   still holds the private half of, or that the plaintext inside is
#   restorable. Only a real restore proves that. Amendment 2 therefore
#   requires a full isolated restore -- decryption, ownership, permissions,
#   app startup -- once before go-live and quarterly after.
#
# THE CONFIRMED OFF-VPS COPY
#   NOTHING ON THIS BOX CONNECTS OUT. The VPS holds no credential for the
#   LAN and no address for it, so it cannot go and look for the second
#   copy. What it can do is read a local file the LAN left behind: after
#   deploy/pull_backups_lan.sh has pulled an archive and checked its
#   sha256 on the LAN, that script -- connecting IN, from the LAN, over a
#   write-confined key that can create nothing else -- leaves
#   `<archive>.pulled` in BACKUP_RECEIPT_DIR. By the time this script
#   reads it, a receipt is an ordinary local file. So retention here is:
#
#     * count-based pruning deletes only RECEIPTED archives. An archive
#       nobody has confirmed off this box is kept, however far down the
#       ranking it falls.
#     * the max-age backstop deletes an UNRECEIPTED archive only when a
#       NEWER archive in the same namespace is receipted -- that is, only
#       when something more recent is confirmed to exist off this box.
#       Otherwise it is kept and one ALERT line says so. The backstop
#       exists because a directory that only grows is its own outage, but
#       an age limit that deletes the last confirmed-nowhere copy of
#       somebody's job history because a LAN pull has been dead for two
#       months is not a backstop, it is the outage.
#     * if NONE of the newest BACKUP_RECEIPT_ALERT_NEWEST archives in the
#       namespace is receipted, one non-fatal ALERT line says the off-VPS
#       copy is unconfirmed. The newest archive is never receipted -- it
#       was written seconds ago -- which is why the test is "none of the
#       newest N" and not "the newest one".
#
#   A receipt is a claim by the LAN host, not proof the bytes are readable;
#   only the restore test proves that. It is, however, a claim the VPS
#   cannot forge for itself, which is the property that matters here.
#
#   What the VPS does check about a receipt: that it names the archive it
#   is filed under AND records the sha256 the archive on this disk actually
#   hashes to. A receipt whose hash disagrees is about some other bytes --
#   a stale receipt left behind by a reused name, or a LAN host that
#   verified something else -- and the archive counts as unreceipted. The
#   hash is recomputed, not read out of the `.sha256` manifest: the
#   manifest and the receipt would otherwise be two copies of the same
#   claim, and the thing being tested is whether the receipt is about the
#   bytes that are here now.
#
# ARGUMENTS
#   exactly one of --full | --owner-data | --check-stale
#
# ENVIRONMENT
#   BACKUP_DIR               where archives land      (/var/backups/careeros)
#   BACKUP_FULL_SOURCE       the served generation
#                                      (/srv/careeros/prod/pipeline/current)
#   BACKUP_OWNER_SOURCE      the prod vault      (/srv/careeros/prod/vault)
#   BACKUP_AGE_RECIPIENTS    age recipient file, PUBLIC keys only
#                                   (/etc/careeros/backup-recipients.txt)
#   BACKUP_NAMESPACE         subdirectory and name prefix; defaults to the
#                            mode. deploy/pre_deploy_backup.sh sets
#                            `pre-deploy` and `pre-deploy-owner-data`
#                                                             (per mode)
#   BACKUP_FULL_ENABLED      1 or 0. 0 turns the whole full class off:
#                            `--full` creates nothing and exits 0, and
#                            `--check-stale` stops asking about it.
#                            For the window before the pipeline is
#                            deployed, where BACKUP_FULL_SOURCE does not
#                            exist yet and the stale alarm would be a
#                            permanent one nobody can clear. owner-data
#                            is unaffected and still alarms. Set it back
#                            to 1 the day the pipeline lands: left at 0
#                            it narrows backup coverage to the vault and
#                            says so only in one line per run. Any other
#                            value is an error, so a typo cannot turn a
#                            backup class off by accident.          (1)
#   BACKUP_KEEP              archives to keep    (5 / 30 / 14 per namespace)
#   BACKUP_MAX_AGE_DAYS      age at which an archive is pruned, provided a
#                            newer one survives AND either it or something
#                            newer is receipted off the VPS
#                                               (40 / 35 / 90 per namespace)
#   BACKUP_ZSTD_LEVEL        compression level                        (19)
#   BACKUP_MIN_BYTES         size below which an archive is not believed (512)
#   BACKUP_STALE_FULL_DAYS   --check-stale threshold for full           (8)
#   BACKUP_STALE_OWNER_DAYS  --check-stale threshold for owner-data     (2)
#   BACKUP_RECEIPT_DIR       where the LAN pull writes its receipts
#                                              (`$BACKUP_DIR/.receipts`)
#   BACKUP_RECEIPT_GROUP     the group of the restricted account the LAN
#                            pull logs in as, which this script group-owns
#                            the receipts directory to when it is root.
#                            NO DEFAULT: that account is one the owner
#                            created and named (deploy/RUNBOOK.md, "The
#                            off-VPS copy"), and a guessed group name here
#                            would chgrp to nothing and say it had. Unset
#                            leaves the directory's group alone and says
#                            so in one line.                     (unset)
#   BACKUP_RECEIPT_ALERT_NEWEST  how many of the newest archives have to
#                            be unreceipted before the unconfirmed-copy
#                            alert fires                                (2)
#   DEPLOY_DATA_LOCK         shared with promote_incoming.sh
#                                        (/run/careeros/careeros-data.lock)
#
# OWNER WORK (never this script's, never in git)
#   Generating the age key pair, keeping the private half offline, and
#   placing the public recipients at BACKUP_AGE_RECIPIENTS (root-owned,
#   0644 is fine -- it is a public key). The recipient file may hold
#   several recipients; all of them can open the archive, so add a second
#   one only deliberately.
#
# FAILURE
#   Non-zero exit and one `ALERT careeros-prod-backup <namespace>:` line.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/careeros}"
BACKUP_FULL_SOURCE="${BACKUP_FULL_SOURCE:-/srv/careeros/prod/pipeline/current}"
BACKUP_OWNER_SOURCE="${BACKUP_OWNER_SOURCE:-/srv/careeros/prod/vault}"
BACKUP_AGE_RECIPIENTS="${BACKUP_AGE_RECIPIENTS:-/etc/careeros/backup-recipients.txt}"
BACKUP_FULL_ENABLED="${BACKUP_FULL_ENABLED:-1}"
BACKUP_ZSTD_LEVEL="${BACKUP_ZSTD_LEVEL:-19}"
BACKUP_MIN_BYTES="${BACKUP_MIN_BYTES:-512}"
BACKUP_STALE_FULL_DAYS="${BACKUP_STALE_FULL_DAYS:-8}"
BACKUP_STALE_OWNER_DAYS="${BACKUP_STALE_OWNER_DAYS:-2}"
BACKUP_RECEIPT_DIR="${BACKUP_RECEIPT_DIR:-$BACKUP_DIR/.receipts}"
BACKUP_RECEIPT_ALERT_NEWEST="${BACKUP_RECEIPT_ALERT_NEWEST:-2}"
BACKUP_RECEIPT_GROUP="${BACKUP_RECEIPT_GROUP:-}"
DEPLOY_DATA_LOCK="${DEPLOY_DATA_LOCK:-/run/careeros/careeros-data.lock}"

MODE="${1:-}"
NS=""
PARTIAL=""

alert() {
  echo "ALERT careeros-prod-backup ${NS:-${MODE:-?}}: $*"
  exit 1
}

cleanup() { [[ -n $PARTIAL && -e $PARTIAL ]] && rm -f "$PARTIAL"; return 0; }
trap cleanup EXIT

# 1 or 0 and nothing else. A switch that turns a backup class off is one
# a typo must not be able to flip: `BACKUP_FULL_ENABLED=false` read as
# "not 1, so off" is how a class stops being backed up quietly.
case $BACKUP_FULL_ENABLED in
  0|1) ;;
  *) alert "BACKUP_FULL_ENABLED must be 1 or 0, not '$BACKUP_FULL_ENABLED'" ;;
esac

newest_in() {   # newest_in <namespace>: the newest archive, or nothing
  local dir="$BACKUP_DIR/$1"
  [[ -d $dir ]] || return 0
  find "$dir" -maxdepth 1 -type f -name '*.tar.zst.age' -printf '%T@ %p\n' \
    | LC_ALL=C sort -n | tail -1 | cut -d' ' -f2-
}

# --- --check-stale: the alarm, and nothing else ---------------------------
if [[ $MODE == --check-stale ]]; then
  NS=check-stale
  now=$(date -u +%s)
  stale=0
  # owner-data always; full only while the class is on. A disabled class
  # produces no archive, so asking whether its newest one is recent is a
  # question with one permanent answer -- an alarm that is always ringing
  # is an alarm nobody reads, including when owner-data starts ringing too.
  pairs=("owner-data:$BACKUP_STALE_OWNER_DAYS")
  if [[ $BACKUP_FULL_ENABLED == 1 ]]; then
    pairs=("full:$BACKUP_STALE_FULL_DAYS" "${pairs[@]}")
  else
    echo "-- full: the full class is disabled (BACKUP_FULL_ENABLED=0), so its staleness is not checked; backup coverage is the vault only until it is set back to 1"
  fi
  for pair in "${pairs[@]}"; do
    ns="${pair%%:*}"; limit="${pair##*:}"
    newest=$(newest_in "$ns")
    if [[ -z $newest ]]; then
      echo "ALERT careeros-prod-backup $ns: no backup at all in $BACKUP_DIR/$ns"
      stale=1
      continue
    fi
    days=$(( (now - $(stat -c '%Y' "$newest")) / 86400 ))
    if (( days > limit )); then
      echo "ALERT careeros-prod-backup $ns: newest backup is ${days}d old, over the ${limit}d limit ($(basename "$newest"))"
      stale=1
    else
      echo "-- $ns: newest backup ${days}d old ($(basename "$newest"))"
    fi
  done
  exit "$stale"
fi

# --- mode, namespace, retention ------------------------------------------
case $MODE in
  --full)       NS=full;       SRC="$BACKUP_FULL_SOURCE";  keep=5;  max_age=40 ;;
  --owner-data) NS=owner-data; SRC="$BACKUP_OWNER_SOURCE"; keep=30; max_age=35 ;;
  *) alert "usage: $(basename "$0") --full | --owner-data | --check-stale (got '${MODE:-nothing}')" ;;
esac
# Before the lock and before anything is created: with the class off,
# this run is a no-op that says so, not a failure. It covers the
# pre-deploy full namespace too -- same source, same missing generation.
if [[ $MODE == --full && $BACKUP_FULL_ENABLED != 1 ]]; then
  echo "-- full: the full class is disabled (BACKUP_FULL_ENABLED=0); nothing was created. Set it back to 1 once $BACKUP_FULL_SOURCE exists, or prod's served generation is in no backup at all"
  exit 0
fi
NS="${BACKUP_NAMESPACE:-$NS}"
# The pre-deploy namespaces hold the same two subsets kept against a
# different failure mode (a bad release, and the additive migrations that
# run at startup before the health check), so they get their own retention.
# `pre-deploy` is the --full subset and `pre-deploy-owner-data` the vault
# one; deploy/pre_deploy_backup.sh takes both before every release.
[[ $NS == pre-deploy* ]] && { keep=14; max_age=90; }
keep="${BACKUP_KEEP:-$keep}"
max_age="${BACKUP_MAX_AGE_DAYS:-$max_age}"

# --- one run at a time, from here to the exit ----------------------------
# DEPLOY_DATA_LOCK is taken BEFORE anything is created and kept until the
# process exits, which is both of the things this lock has to do:
#
#   * keep a promotion from moving `current` under a backup that is reading
#     through it (which is why it existed), and
#   * keep two backups of the same namespace out of each other's way. They
#     mint their archive name from the clock, so two runs in one second
#     agree on the name; it used to be released as soon as the archive was
#     written, which left publish, checksum and prune interleaving -- one
#     run renaming its partial while the other was deciding what to delete.
#
# `flock -w`, not `-n`: a queued backup is a backup, where a refused one is
# a night with no copy of anything. The promotion side is the one that
# refuses rather than queues (it runs every ten minutes anyway).
mkdir -p "$(dirname "$DEPLOY_DATA_LOCK")"
: >>"$DEPLOY_DATA_LOCK" 2>/dev/null || alert "cannot open the data lock $DEPLOY_DATA_LOCK"
exec 9>>"$DEPLOY_DATA_LOCK"
flock -w 120 9 || alert "another backup or a promotion still holds $DEPLOY_DATA_LOCK after 120s"

# --- fail closed: no age, no recipient, no backup ------------------------
command -v age >/dev/null 2>&1 \
  || alert "age is not installed; refusing to write an unencrypted backup"
command -v zstd >/dev/null 2>&1 || alert "zstd is not installed"
[[ -s $BACKUP_AGE_RECIPIENTS ]] \
  || alert "no age recipient file at $BACKUP_AGE_RECIPIENTS; refusing to write an unencrypted backup"
grep -qE '^(age1|ssh-)' "$BACKUP_AGE_RECIPIENTS" \
  || alert "$BACKUP_AGE_RECIPIENTS holds no recognisable age recipient"

[[ -d $SRC ]] || alert "nothing to back up: $SRC is not a directory"
[[ -n $(find "$SRC/." -mindepth 1 -maxdepth 1 -print -quit) ]] \
  || alert "refusing to archive an empty source: $SRC"

DEST_DIR="$BACKUP_DIR/$NS"
mkdir -p "$DEST_DIR"
# 0750, not 0700: the LAN pull account reads this directory through its own
# read-only rrsync key, so it has to be group-readable. The archives are
# encrypted, which is what makes that safe -- group read gets a reader
# ciphertext and nothing else. Owner work: group-own BACKUP_DIR to the pull
# account (see deploy/pull_backups_lan.sh).
chmod 750 "$BACKUP_DIR" "$DEST_DIR"
# And the group itself, on the namespace directory this run just made.
# `chgrp -R /var/backups/careeros` is an owner step that runs once, which
# leaves every namespace directory created AFTER it -- full/, owner-data/,
# the pre-deploy pair -- carrying this process's primary group instead,
# and 0750 on a directory group-owned by root grants the pull account
# nothing. So the group is placed here, by the code that creates the
# directory, every run. The RUNBOOK's `chmod g+s` on BACKUP_DIR covers
# the same hole from the other side (anything else created under it);
# both land the same group, so neither contradicts the other.
#
# Attempted rather than gated on root: a chgrp succeeds for any member of
# the target group, which is how this runs under a non-root backup
# account that is one. A failure is one line and not a failed backup --
# an archive that exists but is readable by too few is worth more than no
# archive -- and it names what to do, because 0750 without the right
# group is a pull that silently reads nothing.
if [[ -n $BACKUP_RECEIPT_GROUP ]]; then
  chgrp "$BACKUP_RECEIPT_GROUP" "$DEST_DIR" 2>/dev/null \
    || echo "ALERT careeros-prod-backup $NS: cannot group-own $DEST_DIR to '$BACKUP_RECEIPT_GROUP' -- does that group exist, and is this account root or a member? The LAN pull cannot read this namespace until it is group-owned there. Not fatal: this backup itself is unaffected"
fi
# 2770 for the receipts, and only the receipts: the LAN pull account has to
# be able to CREATE a file in here, which is the one write its credential
# allows anywhere on this box. Nothing in this directory is a backup -- a
# receipt is a name, a host, a timestamp and a hash -- so a group-writable
# directory holding them costs nothing if that key is lost. Receipts for
# every namespace share it; archive names are namespace-prefixed.
#
# Group-WRITABLE is only half of it: the group has to be the one the LAN
# pull's inbound write arrives as, or 0770 grants the write to nobody who
# wants it. That needs root, so it happens here only when this script has
# it, and says so when it does not rather than leaving a document to
# promise something no code does. The setgid bit is what makes a receipt
# created in here inherit the group instead of that account's primary one.
#
# BACKUP_RECEIPT_GROUP has no default: the account is the owner's, with a
# name only they know. Unset is not an error -- the archives are written
# either way -- but it is said out loud, because until it is set the
# receipts cannot arrive and count-pruning stays off.
mkdir -p "$BACKUP_RECEIPT_DIR"
if [[ -z $BACKUP_RECEIPT_GROUP ]]; then
  chmod 770 "$BACKUP_RECEIPT_DIR"
  echo "-- BACKUP_RECEIPT_GROUP is not set, so $BACKUP_RECEIPT_DIR keeps group $(id -gn) and no setgid bit. Set it to the group of the restricted account the LAN pull logs in as, or the receipts cannot arrive and count-pruning stays off (deploy/RUNBOOK.md, 'The off-VPS copy')"
elif [[ $(id -u) == 0 ]]; then
  if chgrp "$BACKUP_RECEIPT_GROUP" "$BACKUP_RECEIPT_DIR" 2>/dev/null; then
    chmod 2770 "$BACKUP_RECEIPT_DIR"
  else
    chmod 770 "$BACKUP_RECEIPT_DIR"
    echo "ALERT careeros-prod-backup $NS: cannot group-own $BACKUP_RECEIPT_DIR to '$BACKUP_RECEIPT_GROUP' -- does that group exist? The LAN's receipt write will be refused and count-pruning will stop. Not fatal: this backup itself is unaffected"
  fi
else
  chmod 770 "$BACKUP_RECEIPT_DIR"
  echo "-- not root, so $BACKUP_RECEIPT_DIR keeps group $(id -gn) and no setgid bit; the LAN's receipt write needs it group-owned by '$BACKUP_RECEIPT_GROUP' (owner work, or run this as root)"
fi

# --- the snapshot selection ----------------------------------------------
# Under the lock taken above, so a promotion cannot move `current` between
# resolving it and tar opening the tree behind it.
REAL_SRC=$(readlink -f "$SRC") || alert "cannot resolve $SRC"
[[ -d $REAL_SRC ]] || alert "$SRC does not resolve to a directory"

# The name comes from the clock, so it is only unique per second -- hence
# the lock above, and hence this check. The PARTIAL carries the pid as
# well: a partial that collides is two runs writing one file, and the
# rename that followed would publish whichever half finished second.
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE="$DEST_DIR/${NS}_${STAMP}.tar.zst.age"
PARTIAL="$ARCHIVE.partial.$$"
[[ -e $ARCHIVE ]] && alert "an archive for this second already exists: $ARCHIVE"
[[ -e $PARTIAL ]] && alert "a partial archive for this second and this pid already exists: $PARTIAL"

echo "-- $NS: archiving $REAL_SRC"
if tar -C "$REAL_SRC" --numeric-owner -cf - . \
     | zstd -q -T0 "-$BACKUP_ZSTD_LEVEL" -c \
     | age -R "$BACKUP_AGE_RECIPIENTS" -o "$PARTIAL"; then
  stages=("${PIPESTATUS[@]}")
else
  stages=("${PIPESTATUS[@]}")
  alert "archive pipeline failed (tar=${stages[0]} zstd=${stages[1]} age=${stages[2]}); nothing was kept"
fi

bytes=$(stat -c '%s' "$PARTIAL")
(( bytes >= BACKUP_MIN_BYTES )) \
  || alert "the archive is only ${bytes}B, under the ${BACKUP_MIN_BYTES}B floor -- not believed, not kept"

chmod 640 "$PARTIAL"
# Loudly, not `mv -f`: if the final name turned up while this run was
# compressing, something else wrote an archive this run knows nothing
# about, and overwriting it would destroy a copy and publish bytes whose
# manifest belongs to the other one. The lock above means this should be
# unreachable; it is here because "should be" is not a guarantee.
[[ -e $ARCHIVE ]] \
  && alert "$ARCHIVE appeared while this run was compressing -- another run won this second; refusing to overwrite it. This run's partial is discarded"
mv -T "$PARTIAL" "$ARCHIVE"
PARTIAL=""
( cd "$DEST_DIR" && sha256sum "$(basename "$ARCHIVE")" >"$(basename "$ARCHIVE").sha256" )
chmod 644 "$ARCHIVE.sha256"
( cd "$DEST_DIR" && sha256sum --quiet -c "$(basename "$ARCHIVE").sha256" ) >/dev/null \
  || alert "the archive does not read back to its own checksum: $ARCHIVE"
echo "-- $NS: $(basename "$ARCHIVE") ok, ${bytes}B, encrypted to $(grep -cE '^(age1|ssh-)' "$BACKUP_AGE_RECIPIENTS") recipient(s)"

# --- prune, last, and only now -------------------------------------------
# Count first: everything ranked below the keep count goes, PROVIDED the
# LAN has confirmed it off this box. Then age, but only where something
# newer is confirmed off the box, so a stretch with a dead LAN pull cannot
# delete the only copy of anything.
mapfile -t archives < <(find "$DEST_DIR" -maxdepth 1 -type f -name '*.tar.zst.age' \
                        -printf '%T@ %p\n' | LC_ALL=C sort -rn | cut -d' ' -f2-)
drop() {
  rm -f "$1" "$1.sha256" "$BACKUP_RECEIPT_DIR/$(basename "$1").pulled"
  echo "-- pruned $(basename "$1") ($2)"
}
receipted() {   # receipted <archive>: has the LAN confirmed THESE bytes?
  local base receipt claimed actual
  base=$(basename "$1")
  receipt="$BACKUP_RECEIPT_DIR/$base.pulled"
  [[ -f $receipt ]] || return 1
  # The receipt has to be about this archive, and about the bytes that are
  # in it now. A name alone would make a receipt from a reused name, or one
  # written for a file the LAN never actually had, good enough to delete by.
  grep -qxF "archive: $base" "$receipt" || {
    echo "-- $base: its receipt does not name it; treating it as unreceipted"
    return 1
  }
  claimed=$(sed -n 's/^sha256: \([0-9a-f]\{64\}\)$/\1/p' "$receipt" | head -1)
  [[ -n $claimed ]] || {
    echo "-- $base: its receipt records no sha256; treating it as unreceipted"
    return 1
  }
  actual=$(sha256sum "$1" | cut -d' ' -f1)
  [[ $claimed == "$actual" ]] || {
    echo "-- $base: its receipt records ${claimed:0:12}... but the archive hashes to ${actual:0:12}...; the receipt is about other bytes, treating it as unreceipted"
    return 1
  }
}

# The alert first, because it reads the ranking before pruning changes it.
unconfirmed=0
for archive in "${archives[@]:0:BACKUP_RECEIPT_ALERT_NEWEST}"; do
  receipted "$archive" || unconfirmed=$(( unconfirmed + 1 ))
done
if (( ${#archives[@]} > 0 && unconfirmed >= BACKUP_RECEIPT_ALERT_NEWEST )); then
  echo "ALERT careeros-prod-backup $NS: none of the newest $unconfirmed archive(s) has a receipt in $BACKUP_RECEIPT_DIR -- the off-VPS copy is unconfirmed; check deploy/pull_backups_lan.sh on the LAN"
fi

rank=0
survivors=()
for archive in "${archives[@]}"; do
  rank=$(( rank + 1 ))
  if (( rank > keep )); then
    if receipted "$archive"; then
      drop "$archive" "rank $rank, over keep=$keep, off-VPS copy receipted"
      continue
    fi
    echo "-- kept $(basename "$archive"): rank $rank is over keep=$keep, but no off-VPS receipt yet; only max-age=${max_age}d can remove it"
  fi
  survivors+=("$archive")
done
now=$(date -u +%s)
kept=${#survivors[@]}
total=${#survivors[@]}

# newer_receipted <index>: is any SURVIVING archive newer than this one
# confirmed off the VPS? `survivors` is newest-first, so "newer" is every
# index below this one; a pruned entry is blanked rather than removed, so
# the indices keep meaning what they meant.
newer_receipted() {
  local probe
  for (( probe = $1 - 1; probe >= 0; probe-- )); do
    [[ -n ${survivors[probe]} ]] || continue
    receipted "${survivors[probe]}" && return 0
  done
  return 1
}

# Oldest first, and never the last one standing. The age backstop deletes
# an unreceipted archive only when something NEWER is confirmed off this
# box: without that, a LAN pull that has been dead for two months would
# have the age limit delete the only copies there are, one run at a time,
# which is the failure the backstop was supposed to be insurance against.
for (( index = total - 1; index >= 0; index-- )); do
  archive="${survivors[index]}"
  [[ -n $archive ]] || continue
  days=$(( (now - $(stat -c '%Y' "$archive")) / 86400 ))
  (( days > max_age && kept > 1 )) || continue
  if receipted "$archive"; then
    drop "$archive" "${days}d old, over max-age=${max_age}d, off-VPS copy receipted"
  elif newer_receipted "$index"; then
    drop "$archive" "${days}d old, over max-age=${max_age}d, unreceipted but a newer archive is confirmed off-VPS"
  else
    echo "ALERT careeros-prod-backup $NS: unreceipted archive $(basename "$archive") is past max-age=${max_age}d but nothing newer is confirmed off-VPS; keeping it -- fix the LAN pull (deploy/pull_backups_lan.sh)"
    continue
  fi
  survivors[index]=""
  kept=$(( kept - 1 ))
done
echo "-- $NS: $kept archive(s) retained (keep=$keep, max-age=${max_age}d, pruning either way needs a confirmed off-VPS copy)"
