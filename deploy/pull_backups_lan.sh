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
#   PULL_DEST         LAN destination directory
#                                     (/srv/nas/careeros-prod-backups)
#   PULL_USER         the restricted account on the VPS that this script
#                     logs in as. NO DEFAULT: the account is one the owner
#                     created and named, and a name invented in a script
#                     here would be a login nobody can use. Unset is a
#                     one-line usage error.                       (unset)
#   PULL_HOST         the VPS                       (app.career-os.ch)
#   PULL_TARGET       the rsync source, composed as PULL_USER@PULL_HOST;
#                     set it whole to override both
#   PULL_SSH_KEY      private key for the read-only pull
#                                      (/root/.ssh/careeros-pull/id_ed25519)
#   PULL_RECEIPT_SSH_KEY  private key for the receipt write; a DIFFERENT
#                     key, because one authorized_keys line carries one
#                     forced command and the pull key's is read-only
#                                 (/root/.ssh/careeros-pull/receipt_ed25519)
#   PULL_KNOWN_HOSTS  pinned VPS host key file
#                                      (/root/.ssh/careeros-pull/known_hosts)
#   PULL_SSH_PORT     port                                            (22)
#   PULL_MAX_FULL_AGE_DAYS   staleness limit for the newest local full  (8)
#   PULL_MAX_OWNER_AGE_DAYS  staleness limit for owner-data             (2)
#   BACKUP_FULL_ENABLED      1 or 0, and the SAME value the VPS's
#                            deploy/backup_prod.sh runs with -- hence the
#                            BACKUP_ prefix on a variable this script
#                            reads: it is one switch over one decision,
#                            not a LAN opinion about it. 0 means the VPS
#                            is not making full archives (no pipeline
#                            generation there yet), so this pull excludes
#                            the `full/` namespace and the freshness
#                            check stops asking about it; owner-data is
#                            pulled and checked exactly as before. Set
#                            both sides back to 1 the day the pipeline
#                            lands -- left at 0 the LAN stops noticing
#                            that half of prod is not arriving. Any other
#                            value is an error.                      (1)
#
#   PULL_DEST should be a versioned NAS share whose own versions the VPS
#   and the app credentials cannot delete: an independent failure domain,
#   not a second copy inside the same one (Amendment 2).
#
#   Archives keep their VPS timestamps (`rsync -a`), so "the newest local
#   full is 9 days old" means the backup is 9 days old, not the download.
#
# THE SSH SIDE (owner work -- this script creates no keys and names no
# account; deploy/RUNBOOK.md, "The off-VPS copy", has it as a checklist)
#   On the VPS, a dedicated unprivileged account -- whatever the owner
#   named it, which is the name PULL_USER carries -- whose
#   ~/.ssh/authorized_keys holds TWO lines, one per key, because a forced
#   command belongs to a key and reading and writing need different ones:
#
#     restrict,command="/usr/bin/rrsync -ro /var/backups/careeros",\
#     from="203.0.113.7" ssh-ed25519 AAAA...PULLKEY... pull from the LAN
#
#     restrict,command="/usr/bin/rrsync -wo /var/backups/careeros/.receipts",\
#     from="203.0.113.7" ssh-ed25519 AAAA...RECEIPTKEY... receipts from the LAN
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
#   chown, chmod or set times on the directory itself. So the receipt
#   transfer sends plain FILES with `--no-perms --no-owner --no-group
#   --no-times` and never the directory -- an `rsync -a` of the directory
#   would try to apply its metadata and exit 23.
#
#   Both connections are made BY THIS HOST, into the VPS. Nothing on the
#   VPS ever connects out, to the LAN or anywhere else: it has no
#   credential for this host and no address for it.
#
# FAILURE
#   Non-zero exit and one `ALERT careeros-prod-backup-pull:` line.
set -euo pipefail

PULL_DEST="${PULL_DEST:-/srv/nas/careeros-prod-backups}"
PULL_USER="${PULL_USER:-}"
PULL_HOST="${PULL_HOST:-app.career-os.ch}"
PULL_SSH_KEY="${PULL_SSH_KEY:-/root/.ssh/careeros-pull/id_ed25519}"
PULL_RECEIPT_SSH_KEY="${PULL_RECEIPT_SSH_KEY:-/root/.ssh/careeros-pull/receipt_ed25519}"
PULL_KNOWN_HOSTS="${PULL_KNOWN_HOSTS:-/root/.ssh/careeros-pull/known_hosts}"
PULL_SSH_PORT="${PULL_SSH_PORT:-22}"
PULL_MAX_FULL_AGE_DAYS="${PULL_MAX_FULL_AGE_DAYS:-8}"
PULL_MAX_OWNER_AGE_DAYS="${PULL_MAX_OWNER_AGE_DAYS:-2}"
BACKUP_FULL_ENABLED="${BACKUP_FULL_ENABLED:-1}"

MODE="${1:-}"
WORK=""

alert() {
  echo "ALERT careeros-prod-backup-pull: $*"
  exit 1
}

cleanup() { [[ -n $WORK && -d $WORK ]] && rm -rf "$WORK"; return 0; }
trap cleanup EXIT

#: Every transfer, in both directions: this script can create nothing but
#: directories and regular files, here or on the VPS. `-a` implies `-l`,
#: which would recreate a symlink the VPS side offered, and `--safe-links`
#: would still allow one pointing inside the tree.
RSYNC_SAFE=(-a --no-links --no-devices --no-specials)

# 1 or 0 and nothing else, the same rule backup_prod.sh applies to it.
# `BACKUP_FULL_ENABLED=flase` (a typo) read as "not 1, so off" is how the LAN
# quietly stops checking whether half of prod is arriving.
case $BACKUP_FULL_ENABLED in
  0|1) ;;
  *) alert "BACKUP_FULL_ENABLED must be 1 or 0, not '$BACKUP_FULL_ENABLED'" ;;
esac

#: Which namespaces this run pulls and checks. `full` only while the VPS
#: is making full archives: a class that is switched off there has no
#: newest copy anywhere, so a freshness check on it is a permanent alarm,
#: and an alarm that is always ringing hides the owner-data one that is
#: the whole point of this script.
PULL_EXCLUDE_FULL=()
CHECKED_CLASSES="both namespaces"
if [[ $BACKUP_FULL_ENABLED != 1 ]]; then
  PULL_EXCLUDE_FULL=(--exclude='full/')
  CHECKED_CLASSES="owner-data (full is switched off)"
fi

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
  local pairs=("owner-data:$PULL_MAX_OWNER_AGE_DAYS")
  now=$(date -u +%s)
  STALE_CLASSES=""
  if [[ $BACKUP_FULL_ENABLED == 1 ]]; then
    pairs=("full:$PULL_MAX_FULL_AGE_DAYS" "${pairs[@]}")
  else
    echo "-- full: the full class is disabled on the VPS (BACKUP_FULL_ENABLED=0), so it is neither pulled nor checked; the off-VPS copy is the vault only until it is set back to 1"
  fi
  for pair in "${pairs[@]}"; do
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
  echo "-- check-stale ok: a recent off-VPS copy of ${CHECKED_CLASSES} is on the LAN"
  exit 0
fi
[[ -z $MODE ]] || alert "usage: $(basename "$0") [--check-stale] (got '$MODE')"

# Who to log in as. There is no default on purpose: the account on the
# VPS is one the owner created with a name of their choosing, and a name
# guessed here would make every run fail with an ssh error instead of
# this one line. PULL_TARGET set whole still wins, for a host that is
# reached some other way.
PULL_TARGET="${PULL_TARGET:-${PULL_USER:+$PULL_USER@$PULL_HOST}}"
[[ -n $PULL_TARGET ]] \
  || alert "PULL_USER is not set: name the restricted backup account you created on the VPS (PULL_USER=<account> $(basename "$0")), or set PULL_TARGET whole. See this script's header, THE SSH SIDE"

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
      --exclude='*.partial' --exclude='.receipts/' "${PULL_EXCLUDE_FULL[@]}" \
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
