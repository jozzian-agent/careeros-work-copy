#!/bin/bash
# Pull prod's encrypted backups down to the LAN (Amendment 2, the off-VPS
# copy).
#
# WHAT IT DOES
#   Runs on the LAN. Pulls completed encrypted archives out of the VPS
#   backup directory over a SEPARATE, read-only SSH credential, lands them
#   in a LAN destination, and verifies each file against the manifest the
#   VPS wrote beside it (`<archive>.sha256`). A file that does not match is
#   renamed `.unverified` and the run fails, so the next run fetches it
#   again instead of silently trusting it. An archive whose `.sha256` never
#   arrived also fails the run, naming it: an unverifiable copy is not an
#   off-VPS copy, and counting it as "pending" is how a backup nobody can
#   check looked like a successful pull.
#
#   For every archive it DID verify, it writes a receipt back to the VPS --
#   `<archive>.pulled` under `/var/backups/careeros/.receipts/` -- which is
#   what lets deploy/backup_prod.sh prune without guessing whether a second
#   copy exists. That is the only thing this script ever writes on the VPS,
#   and it can write nothing else (see THE SSH SIDE below).
#
#   A receipt names the archive AND carries its sha256, and is written only
#   after the manifest has been shown to vouch for THAT archive's own
#   basename. A manifest naming some other file is a failed run with no
#   receipt: otherwise "verified" would mean "a file called something else
#   checked out", and prod would prune an archive on the strength of it.
#
#   Freshness is checked on EVERY run, not only when nothing new arrived:
#   a run that pulls today's owner-data archive while the newest full copy
#   is five weeks old exits non-zero and names which class is stale.
#
#   The direction matters: the VPS never reaches into the LAN, so the LAN
#   pulls. That is also why this needs its own credential rather than the
#   push key -- the push key is write-only and confined to `incoming/`, and
#   a key that can both write prod data and read prod backups is one
#   compromise away from both.
#
# WHAT IT MUST NEVER TOUCH
#   * The archives on the VPS. No deletion, no rename, no
#     `--remove-source-files`: the VPS's own retention is
#     deploy/backup_prod.sh's job, and a LAN job that could delete prod
#     backups would put both copies in one failure domain. The receipt it
#     writes is a new file in a directory that holds nothing else.
#   * The LAN vault, this repo, or any archive it did not just pull.
#     Existing destination files are never overwritten (`--ignore-existing`);
#     an archive is immutable once written.
#   * Plaintext. It never decrypts; the recovery key is not on this host.
#
# ARGUMENTS
#   none, or --check-stale: create nothing, pull nothing, and exit non-zero
#   if the newest LOCAL full copy is older than PULL_MAX_FULL_AGE_DAYS or
#   the newest local owner-data copy older than PULL_MAX_OWNER_AGE_DAYS, or
#   if either namespace holds no copy at all. The mirror image of
#   `backup_prod.sh --check-stale`, asking the other half of the question:
#   that one says a backup was made, this one says a backup left the VPS.
#   Put it on its own daily cron line whose output somebody reads.
#
#   The same freshness check runs at the end of EVERY normal pull, whether
#   or not anything new arrived. "Something arrived" is not the question;
#   "is a recent, verified copy of both classes on the LAN" is.
#
# ENVIRONMENT
#   PULL_DEST         LAN destination directory  (/srv/nas/careeros-backups)
#   PULL_TARGET       rsync source         (careeros-backup@app.career-os.ch)
#   PULL_SSH_KEY      private key for the read-only pull
#                                    (/root/.ssh/careeros-backup/id_ed25519)
#   PULL_RECEIPT_SSH_KEY  private key for the receipt write; a DIFFERENT
#                     key, because one authorized_keys line carries one
#                     forced command and the pull key's is read-only
#                               (/root/.ssh/careeros-backup/receipt_ed25519)
#   PULL_KNOWN_HOSTS  pinned VPS host key file
#                                    (/root/.ssh/careeros-backup/known_hosts)
#   PULL_SSH_PORT     port                                            (22)
#   PULL_MAX_FULL_AGE_DAYS   staleness limit for the newest local full  (8)
#   PULL_MAX_OWNER_AGE_DAYS  staleness limit for owner-data             (2)
#
#   PULL_DEST should be a versioned NAS share whose snapshots the VPS and
#   app credentials cannot delete (Amendment 2 prefers that over a second
#   Proxmox disk: an independent failure domain, not a second copy in the
#   same one).
#
#   Archives keep their VPS timestamps (`rsync -a`), so "the newest local
#   full is 9 days old" means the backup is 9 days old, not the download.
#
# THE SSH SIDE (owner work, Part 3 -- this script creates no keys)
#   On the VPS, a dedicated unprivileged account whose
#   ~/.ssh/authorized_keys holds TWO lines, one per key, because a forced
#   command belongs to a key and reading and writing need different ones:
#
#     restrict,command="/usr/bin/rrsync -ro /var/backups/careeros",\
#     from="203.0.113.7" ssh-ed25519 AAAA...PUBLIC... careeros-backup-pull@lan
#
#     restrict,command="/usr/bin/rrsync -wo /var/backups/careeros/.receipts",\
#     from="203.0.113.7" ssh-ed25519 AAAA...RECEIPT... careeros-backup-receipt@lan
#
#   `rrsync -ro` refuses rsync's writing modes; `rrsync -wo` refuses its
#   reading modes; both confine every path they are handed to their own
#   directory. So the first key can read ciphertext and nothing else, and
#   the second can create receipt files and nothing else -- not an archive,
#   not a manifest, nothing outside `.receipts/`. Neither can decrypt or
#   delete. `restrict` turns off forwarding, PTY and agent; `from=` pins
#   the LAN egress (203.0.113.7 is a documentation address).
#
#   The read account needs group read on /var/backups/careeros, which
#   backup_prod.sh keeps at 0750 with archives at 0640 for exactly this
#   purpose, and write access to `.receipts/` alone -- group write on that
#   one directory, which backup_prod.sh keeps at 0770. Both private keys
#   live on this host 0600 in a 0700 directory.
#
#   Note what group-write on a directory the backup account OWNS means for
#   the transfer: this account can create files in `.receipts/` and cannot
#   chown, chmod or set times on the directory itself. So the receipt push
#   sends plain FILES with `--no-perms --no-owner --no-group --no-times`
#   and never the directory -- an `rsync -a` of the directory would try to
#   apply its metadata and exit 23.
#
# FAILURE
#   Non-zero exit and one `ALERT careeros-backup-pull:` line.
set -euo pipefail

PULL_DEST="${PULL_DEST:-/srv/nas/careeros-backups}"
PULL_TARGET="${PULL_TARGET:-careeros-backup@app.career-os.ch}"
PULL_SSH_KEY="${PULL_SSH_KEY:-/root/.ssh/careeros-backup/id_ed25519}"
PULL_RECEIPT_SSH_KEY="${PULL_RECEIPT_SSH_KEY:-/root/.ssh/careeros-backup/receipt_ed25519}"
PULL_KNOWN_HOSTS="${PULL_KNOWN_HOSTS:-/root/.ssh/careeros-backup/known_hosts}"
PULL_SSH_PORT="${PULL_SSH_PORT:-22}"
PULL_MAX_FULL_AGE_DAYS="${PULL_MAX_FULL_AGE_DAYS:-8}"
PULL_MAX_OWNER_AGE_DAYS="${PULL_MAX_OWNER_AGE_DAYS:-2}"

MODE="${1:-}"
WORK=""

alert() {
  echo "ALERT careeros-backup-pull: $*"
  exit 1
}

cleanup() { [[ -n $WORK && -d $WORK ]] && rm -rf "$WORK"; return 0; }
trap cleanup EXIT

#: Every transfer, in both directions: this script can create nothing but
#: directories and regular files, here or on the VPS. `-a` implies `-l`,
#: which would recreate a symlink the VPS side offered, and `--safe-links`
#: would still allow one pointing inside the tree.
RSYNC_SAFE=(-a --no-links --no-devices --no-specials)

newest_in() {   # newest_in <namespace>: the newest local archive, or nothing
  local dir="$PULL_DEST/$1"
  [[ -d $dir ]] || return 0
  find "$dir" -maxdepth 1 -type f -name '*.tar.zst.age' -printf '%T@ %p\n' \
    | LC_ALL=C sort -n | tail -1 | cut -d' ' -f2-
}

#: Which classes freshness() found stale, for the alert to name. A run
#: that says "the off-VPS copy is stale" without saying which half is
#: stale sends the owner looking in the wrong place.
STALE_CLASSES=""

freshness() {   # freshness: 0 if both namespaces hold a recent VERIFIED copy
  local now stale=0 pair ns limit newest days
  now=$(date -u +%s)
  STALE_CLASSES=""
  for pair in "full:$PULL_MAX_FULL_AGE_DAYS" "owner-data:$PULL_MAX_OWNER_AGE_DAYS"; do
    ns="${pair%%:*}"; limit="${pair##*:}"
    newest=$(newest_in "$ns")
    if [[ -z $newest ]]; then
      echo "-- STALE $ns: no copy at all in $PULL_DEST/$ns"
      stale=1
      STALE_CLASSES+="${STALE_CLASSES:+, }$ns"
      continue
    fi
    days=$(( (now - $(stat -c '%Y' "$newest")) / 86400 ))
    if (( days > limit )); then
      echo "-- STALE $ns: the newest copy is ${days}d old, over the ${limit}d limit ($(basename "$newest"))"
      stale=1
      STALE_CLASSES+="${STALE_CLASSES:+, }$ns"
    else
      echo "-- $ns: newest copy ${days}d old ($(basename "$newest"))"
    fi
  done
  return "$stale"
}

# --- --check-stale: the alarm, and nothing else ---------------------------
# No credential is needed and none is checked: this reads the LAN side only.
if [[ $MODE == --check-stale ]]; then
  [[ -d $PULL_DEST ]] || alert "the LAN destination $PULL_DEST does not exist"
  freshness || alert "the off-VPS copy is stale; prod's backups are not leaving the VPS"
  echo "-- check-stale ok: a recent off-VPS copy of both namespaces is on the LAN"
  exit 0
fi
[[ -z $MODE ]] || alert "usage: $(basename "$0") [--check-stale] (got '$MODE')"

[[ -f $PULL_SSH_KEY ]] || alert "no pull key at $PULL_SSH_KEY (owner work: see this script's header)"
[[ -f $PULL_RECEIPT_SSH_KEY ]] \
  || alert "no receipt key at $PULL_RECEIPT_SSH_KEY (owner work: the second authorized_keys line, rrsync -wo into .receipts/ -- see this script's header). Without it prod cannot tell a pulled archive from an unconfirmed one and will not prune by count"
for key in "$PULL_SSH_KEY" "$PULL_RECEIPT_SSH_KEY"; do
  key_mode=$(stat -c '%a' "$key")
  dir_mode=$(stat -c '%a' "$(dirname "$key")")
  [[ $key_mode == 600 ]] || alert "$key is mode $key_mode, must be 600"
  [[ $dir_mode == 700 ]] || alert "$(dirname "$key") is mode $dir_mode, must be 700"
done
[[ -s $PULL_KNOWN_HOSTS ]] || alert "no pinned host key at $PULL_KNOWN_HOSTS"
[[ -d $PULL_DEST ]] || alert "the LAN destination $PULL_DEST does not exist"

ssh_for() {   # ssh_for <key>: the hardened -e string for one credential
  local built="ssh" opt
  for opt in -i "$1" -o IdentitiesOnly=yes -o BatchMode=yes \
             -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$PULL_KNOWN_HOSTS" \
             -o PasswordAuthentication=no -o PubkeyAuthentication=yes \
             -o ClearAllForwardings=yes -o RequestTTY=no -p "$PULL_SSH_PORT"; do
    built+=" $(printf '%q' "$opt")"
  done
  echo "$built"
}
ssh_cmd=$(ssh_for "$PULL_SSH_KEY")
receipt_ssh_cmd=$(ssh_for "$PULL_RECEIPT_SSH_KEY")

WORK=$(mktemp -d -t careeros-pull-XXXXXX)
RECEIPTS="$WORK/receipts"
mkdir -p "$RECEIPTS"

# What is already here, so "nothing new arrived" is a fact and not a guess.
find "$PULL_DEST" -type f -name '*.tar.zst.age' | LC_ALL=C sort >"$WORK/before"

# No --delete in either direction, and --ignore-existing so a verified
# archive is never re-downloaded or overwritten. `.partial` is what
# backup_prod.sh writes while a stream is still running; `.receipts/` is
# this script's own writing coming back at it.
rsync "${RSYNC_SAFE[@]}" --ignore-existing --no-owner --no-group --chmod=D750,F640 \
      --exclude='*.partial' --exclude='.receipts/' \
      -e "$ssh_cmd" "$PULL_TARGET:." "$PULL_DEST/" \
  || alert "rsync from $PULL_TARGET failed; nothing on the VPS was changed"

find "$PULL_DEST" -type f -name '*.tar.zst.age' | LC_ALL=C sort >"$WORK/after"
arrived=$(comm -13 "$WORK/before" "$WORK/after" | grep -c . || true)

# --- verify what is here, all of it --------------------------------------
# Not only what arrived in this run: a `.sha256` that was missing last time
# may be here now, and an archive that was never verified is not a copy.
checked=0
missing=()
mislabelled=()
bad=0
while IFS= read -r archive; do
  base=$(basename "$archive")
  if [[ ! -f "$archive.sha256" ]]; then
    missing+=("$base")
    continue
  fi
  # The manifest has to vouch for THIS file and nothing else, checked
  # before `sha256sum -c` rather than after. A manifest naming a different
  # archive is not a manifest for this one: `-c` would go and hash whatever
  # it names (or fail because that name is absent), and the receipt written
  # afterwards would say this archive had been verified when nothing had
  # looked at its bytes. One line, matching the basename, or nothing.
  # Both sha256sum formats: `hash  name` and binary mode's `hash *name`.
  listed=$(sed -n 's/^[0-9a-f]\{64\} [ *]\(.*\)$/\1/p' "$archive.sha256")
  if [[ $listed != "$base" ]]; then
    mislabelled+=("$base")
    echo "-- MANIFEST MISMATCH: $base.sha256 vouches for '${listed//$'\n'/, }', not for $base"
    continue
  fi
  if ( cd "$(dirname "$archive")" && sha256sum --quiet -c "$base.sha256" ) >/dev/null 2>&1; then
    checked=$(( checked + 1 ))
    # The receipt says one thing and says it without personal content: this
    # archive exists off the VPS, and these are the bytes that were checked
    # there. The hash is what makes it a claim about bytes rather than about
    # a filename -- backup_prod.sh re-hashes the archive it is about to
    # prune and compares.
    {
      echo "archive: $base"
      echo "verified_by: $(hostname)"
      echo "verified_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
      sed -n 's/^\([0-9a-f]\{64\}\) [ *].*$/sha256: \1/p' "$archive.sha256" | head -1
    } >"$RECEIPTS/$base.pulled"
  else
    mv "$archive" "$archive.unverified"
    echo "-- CHECKSUM FAILED: $base set aside as .unverified for the next run"
    bad=$(( bad + 1 ))
  fi
done < <(find "$PULL_DEST" -type f -name '*.tar.zst.age' | LC_ALL=C sort)

# --- the receipts, in one transfer ---------------------------------------
# One connection for all of them, and no --delete: a receipt is additive
# and idempotent, so re-sending one costs nothing and losing one only
# delays prod's pruning by a run.
#
# FILES, never the directory, and no metadata preservation. The receipt
# directory on the VPS is owned by the backup account and only
# GROUP-writable for this key, so a transfer that tries to apply the source
# directory's permissions, owner, group or mtime to it fails -- that is a
# chown/chmod/utimes on a directory this account does not own, and real
# rsync exits 23 on it. So: the individual `.pulled` paths as sources
# (rsync then creates no directory and sets nothing on one),
# `--no-perms --no-owner --no-group --no-times`, and `--chmod=F640` to say
# what the new files should be. Nothing here needs `-a`.
#
# This is also the shape `rrsync -wo` permits: one write-only destination
# directory, plain files landing in it, no recursion to confine.
if (( checked > 0 )); then
  chmod 640 "$RECEIPTS"/*.pulled
  rsync --no-links --no-devices --no-specials \
        --no-perms --no-owner --no-group --no-times --chmod=F640 \
        -e "$receipt_ssh_cmd" "$RECEIPTS"/*.pulled "$PULL_TARGET:." \
    || alert "$checked archive(s) verified on the LAN but their receipts did not reach $PULL_TARGET; prod will keep every archive until they do"
  echo "-- $checked receipt(s) written back to $PULL_TARGET (.receipts/)"
fi

echo "-- pull: $arrived new archive(s), $checked verified, in $PULL_DEST"
(( bad == 0 )) || alert "$bad archive(s) did not match their manifest"
(( ${#mislabelled[@]} == 0 )) \
  || alert "${#mislabelled[@]} archive(s) have a .sha256 manifest that names a different file: ${mislabelled[*]} -- no receipt was written for them, because nothing has verified their bytes"
(( ${#missing[@]} == 0 )) \
  || alert "${#missing[@]} archive(s) have no .sha256 manifest and cannot be verified: ${missing[*]} -- an unverifiable copy is not an off-VPS copy"

# Freshness, on EVERY run and not only on a run that pulled nothing. A pull
# that fetches today's owner-data archive while the newest full copy on the
# LAN is five weeks old is not a healthy pull: one of the two things prod
# cannot reproduce is not leaving the VPS, and "something arrived" was
# hiding it. Every archive still here has been verified by the time this
# runs -- a tampered one was renamed out of the way above, and an
# unverifiable one has already failed the run.
if ! freshness; then
  (( arrived == 0 )) \
    && alert "nothing new was pulled and the off-VPS copy is stale ($STALE_CLASSES); prod's backups are not reaching the LAN"
  alert "$arrived archive(s) arrived, but the off-VPS copy is stale ($STALE_CLASSES); that class of prod's backups is not reaching the LAN"
fi
echo "-- pull ok"
