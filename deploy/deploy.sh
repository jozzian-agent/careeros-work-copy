#!/bin/bash
# One deploy of one environment, run on the VPS as root.
#
#   deploy.sh stg                 deploy the latest origin/main
#   deploy.sh prod                deploy the newest tag matching v*
#   deploy.sh prod --rollback     go back one release and stay there
#
# Normally nothing runs this by hand: careeros-deploy@.service does, on
# the two timers (stg every 2 minutes, prod every 5). See
# deploy/RUNBOOK.md for the owner-facing version of everything below.
#
# WHAT A RUN DOES, IN ORDER
#   1. Refuses unless it is root, names a known environment, and can take
#      the deploy lock. One run at a time across both environments.
#   2. Stops if a rollback is pinned, or if the ref it would deploy is
#      the one `current` already points at, or the one that failed last
#      time. A no-op run costs a fetch and a second.
#   3. prod only: archives the vault to backups/vault-<timestamp>.tar.gz,
#      verifies the archive, prunes to the newest 14. A backup that does
#      not work ends the run before anything is touched.
#   4. Builds the release: clean checkout of the ref into
#      releases/<ref>, a fresh venv, requirements.txt.
#   5. Proves the release imports before it can become `current`. A
#      release whose dependencies did not install never gets the symlink.
#   6. Flips `current` atomically, restarts the service, polls
#      /api/health for up to 60s, then runs tests/smoke.sh against the
#      local port. Either one failing rolls back to the previous release,
#      restarts, re-polls, records the bad ref, and exits non-zero.
#   7. Prunes to the newest 2 releases, never touching the two the
#      symlinks point at.
#
# WHAT IT NEVER DOES
#   * Run migrations. They run at app startup (careeros/server.py,
#     create_app), so the release that starts is the one that migrates,
#     and a rollback restarts an older app against the same vault.
#   * Print a secret. It reads no env file and holds no password: the
#     smoke test reads its own credentials out of /etc/careeros/<env>.env
#     itself, so nothing from that file is ever a variable in this
#     process or an argument to anything it starts.
#   * Write outside /srv/careeros/<env>, /run/careeros and the journal.
#
# ENVIRONMENT (all optional; the defaults are what the timers run)
#   CAREEROS_DEPLOY_ROOT        /srv/careeros
#   CAREEROS_DEPLOY_ENV_DIR     /etc/careeros
#   CAREEROS_DEPLOY_REPO        git@github.com:jozzian/careeros.git
#   CAREEROS_DEPLOY_SSH_DIR     /root/.ssh
#   CAREEROS_DEPLOY_PYTHON      python3   (the system 3.14 on this box)
#   CAREEROS_DEPLOY_SYSTEMCTL   systemctl
#   CAREEROS_DEPLOY_USER        careeros-<env>   who owns a release
#   CAREEROS_DEPLOY_SERVICE     careeros-<env>   the unit to restart
#   CAREEROS_DEPLOY_HEALTH_WAIT 60      seconds to wait for /api/health
#   CAREEROS_DEPLOY_KEEP        2       releases kept
#   CAREEROS_DEPLOY_BACKUP_KEEP 14      prod vault archives kept
#   CAREEROS_DEPLOY_LOCK        /run/careeros/deploy.lock
#   CAREEROS_DEPLOY_LOCK_HELD   set by careeros-deploy@.service, which
#                               already holds the lock
set -euo pipefail

ROOT="${CAREEROS_DEPLOY_ROOT:-/srv/careeros}"
ENV_DIR="${CAREEROS_DEPLOY_ENV_DIR:-/etc/careeros}"
REPO="${CAREEROS_DEPLOY_REPO:-git@github.com:jozzian/careeros.git}"
SSH_DIR="${CAREEROS_DEPLOY_SSH_DIR:-/root/.ssh}"
# The system python3, which on this box is 3.14 (setup-vps.sh checks the
# version and proves requirements.txt installs under it before anything
# else happens). Never a version-suffixed binary: the first draft of this
# script hardcoded one, and no such binary exists on the real machine, so
# every deploy would have failed at the venv.
PYTHON="${CAREEROS_DEPLOY_PYTHON:-python3}"
SYSTEMCTL="${CAREEROS_DEPLOY_SYSTEMCTL:-systemctl}"
HEALTH_WAIT="${CAREEROS_DEPLOY_HEALTH_WAIT:-60}"
KEEP="${CAREEROS_DEPLOY_KEEP:-2}"
BACKUP_KEEP="${CAREEROS_DEPLOY_BACKUP_KEEP:-14}"
LOCK="${CAREEROS_DEPLOY_LOCK:-/run/careeros/deploy.lock}"

log() { printf '%s deploy[%s]: %s\n' "$(date -Is)" "${ENVIRONMENT:-?}" "$*"; }
fail() { log "FAILED: $*"; exit 1; }

usage() {
  printf 'usage: %s <stg|prod> [--rollback]\n' "${0##*/}" >&2
  exit 64
}

# --- arguments -------------------------------------------------------------

ENVIRONMENT=""
ROLLBACK_ONLY=no
while [[ $# -gt 0 ]]; do
  case $1 in
    stg|prod) [[ -z $ENVIRONMENT ]] || usage; ENVIRONMENT=$1 ;;
    --rollback) ROLLBACK_ONLY=yes ;;
    -h|--help) usage ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage ;;
  esac
  shift
done
[[ -n $ENVIRONMENT ]] || usage

# Everything about this environment, in one place, derived from its name
# so the two environments cannot drift apart. The ports are the ones the
# systemd units pass to the app on ExecStart and the Caddyfile proxies to.
if [[ $ENVIRONMENT == prod ]]; then
  PORT=8001
else
  PORT=8002
fi
SERVICE="${CAREEROS_DEPLOY_SERVICE:-careeros-$ENVIRONMENT}"
SERVICE_USER="${CAREEROS_DEPLOY_USER:-careeros-$ENVIRONMENT}"
ENV_FILE="$ENV_DIR/$ENVIRONMENT.env"
DEPLOY_KEY="$SSH_DIR/careeros-${ENVIRONMENT}_deploy"

ENV_ROOT="$ROOT/$ENVIRONMENT"
APP="$ENV_ROOT/app"
RELEASES="$APP/releases"
CURRENT="$APP/current"
PREVIOUS="$APP/previous"
PIN="$APP/rollback.pin"
FAILED_REF="$APP/failed.ref"
VAULT="$ENV_ROOT/vault"
BACKUPS="$ENV_ROOT/backups"
MIRROR="$APP/repo.git"
HEALTH_PATH='/api/health'

# --- preconditions ---------------------------------------------------------

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'must run as root: it writes release trees and restarts a service'
[[ -d $ENV_ROOT ]] || fail "$ENV_ROOT does not exist -- run setup-vps.sh first"

# One run at a time, across both environments, by hand as much as on the
# timer: two runs would fight over the same release tree. Refuses rather
# than queueing -- a queued run fires a stale deploy minutes after the
# timer that asked for it.
#
# careeros-deploy@.service already holds this same lock and says so, so a
# run started from there does not try to take a lock it is inside of.
#
# It is the same path deploy/promote_incoming.sh calls DEPLOY_LOCK, which
# is deliberate: a data promotion and a release are exactly the two
# things that must not run at once.
if [[ -z ${CAREEROS_DEPLOY_LOCK_HELD:-} ]]; then
  install -d -m 0700 "$(dirname "$LOCK")"
  exec 9>"$LOCK"
  flock -n 9 || { log "another deploy run holds $LOCK -- not queueing behind it"; exit 1; }
  export CAREEROS_DEPLOY_LOCK_HELD=1
fi

# git talks to GitHub with this environment's own read-only deploy key
# and nothing else: IdentitiesOnly stops it falling back to any other key
# in root's agent or ~/.ssh, so a staging deploy cannot use production's
# key even by accident. StrictHostKeyChecking=yes because setup-vps.sh
# already recorded GitHub's host key and printed its fingerprint for the
# owner to compare -- an unknown host key here means something changed,
# which is a stop and not a prompt.
export GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o BatchMode=yes"
export GIT_TERMINAL_PROMPT=0

# --- the release pointers --------------------------------------------------

current_release() { [[ -L $CURRENT ]] && readlink -f "$CURRENT" || true; }
previous_release() { [[ -L $PREVIOUS ]] && readlink -f "$PREVIOUS" || true; }

point() {   # point <symlink> <target>: an atomic flip, never a gap
  # ln -sfn on an existing symlink is two steps (unlink, create), so a
  # reader between them sees no `current` at all. Creating the new link
  # beside it and renaming it over is one rename syscall, so a reader
  # sees either the old target or the new one.
  local link=$1 target=$2 staging="$1.$$"
  ln -sfn "$target" "$staging"
  mv -Tf "$staging" "$link"
}

restart_service() {
  log "restarting $SERVICE"
  "$SYSTEMCTL" restart "$SERVICE" || fail "systemctl restart $SERVICE failed"
}

poll_health() {   # 0 when /api/health answers 200 inside the window
  # /api/health is the app's own unauthenticated check (careeros/server.py,
  # health): it answers {"ok": true} and reads no record, so polling it
  # proves the process is up and serving without a session.
  local waited=0 code
  while [[ $waited -lt $HEALTH_WAIT ]]; do
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
             "http://127.0.0.1:$PORT$HEALTH_PATH" 2>/dev/null || echo 000)
    if [[ $code == 200 ]]; then
      log "$HEALTH_PATH answered 200 after ${waited}s"
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  log "$HEALTH_PATH did not answer 200 on port $PORT within ${HEALTH_WAIT}s (last status $code)"
  return 1
}

run_smoke() {   # 0 pass, 1 fail, 2 not configured
  local release=$1 script="$1/tests/smoke.sh"
  if [[ ! -x $script ]]; then
    log "no tests/smoke.sh in this release -- health check only"
    return 2
  fi
  # The script reads the credentials out of the env file itself. They are
  # never variables here and never arguments to it, so a password cannot
  # reach this process, its argv, or the journal.
  local status=0
  SMOKE_ENV_FILE="$ENV_FILE" "$script" "http://127.0.0.1:$PORT" || status=$?
  case $status in
    0) log 'smoke test passed' ;;
    2) log "smoke test skipped: no credentials in $ENV_FILE (see deploy/RUNBOOK.md)" ;;
    *) log "smoke test failed (exit $status)" ;;
  esac
  return $status
}

verify_live() {   # the health gate: 0 only when the running service is good
  local release=$1 status=0
  poll_health || return 1
  run_smoke "$release" || status=$?
  [[ $status -eq 0 || $status -eq 2 ]]
}

roll_back_to_previous() {   # after a failed deploy
  local previous
  previous=$(previous_release)
  if [[ -z $previous || ! -d $previous ]]; then
    fail 'nothing to roll back to: no previous release recorded'
  fi
  log "rolling back to ${previous##*/}"
  point "$CURRENT" "$previous"
  restart_service
  if poll_health; then
    log "rollback to ${previous##*/} is live"
  else
    log "ALERT careeros-deploy: the ROLLBACK to ${previous##*/} did not answer $HEALTH_PATH either -- $ENVIRONMENT is down and needs a person"
  fi
}

# --- the explicit rollback -------------------------------------------------

if [[ $ROLLBACK_ONLY == yes ]]; then
  previous=$(previous_release)
  [[ -n $previous && -d $previous ]] || fail 'nothing to roll back to: no previous release recorded'
  log "rolling back to ${previous##*/} and pinning"
  point "$CURRENT" "$previous"
  restart_service
  # Pinned whether or not it comes up: the point of the pin is that the
  # timer stops deploying until a person has looked, and an environment
  # that is down is the case where that matters most.
  date -Is >"$PIN"
  printf 'rolled back to %s\n' "${previous##*/}" >>"$PIN"
  log "wrote $PIN -- the timer will skip this environment until it is removed"
  poll_health || fail "rolled back to ${previous##*/} but $HEALTH_PATH did not answer"
  log "rollback complete and pinned; remove $PIN to let the timer deploy again"
  exit 0
fi

# --- the skips -------------------------------------------------------------

if [[ -e $PIN ]]; then
  log "a rollback is pinned ($PIN) -- deploying nothing. Remove it to resume."
  exit 0
fi

install -d -m 0755 "$RELEASES"
install -d -m 0755 "$BACKUPS"

# --- what to deploy --------------------------------------------------------

if [[ ! -d $MIRROR ]]; then
  log "first run: mirroring $REPO"
  git clone --mirror --quiet "$REPO" "$MIRROR" \
    || fail "could not clone $REPO with $DEPLOY_KEY (is the deploy key added on GitHub, read-only?)"
else
  git --git-dir="$MIRROR" remote update --prune >/dev/null \
    || fail "could not fetch $REPO with $DEPLOY_KEY"
fi

if [[ $ENVIRONMENT == stg ]]; then
  # Staging follows main: the commit, not the branch name, so the release
  # directory names exactly what is in it.
  CHECKOUT=$(git --git-dir="$MIRROR" rev-parse --verify --quiet main) \
    || fail 'origin/main not found in the mirror'
  TARGET=${CHECKOUT:0:12}
else
  # Production follows the newest v* tag. Sorted by version, not by date:
  # v0.10.0 is newer than v0.9.0 whichever was pushed first.
  TARGET=$(git --git-dir="$MIRROR" tag --list 'v*' --sort=-version:refname | head -1)
  [[ -n $TARGET ]] || fail 'no tag matching v* in the mirror -- publish a release first'
  CHECKOUT=$TARGET
fi
log "newest deployable ref is $TARGET"

CURRENT_PATH=$(current_release)
if [[ -n $CURRENT_PATH && ${CURRENT_PATH##*/} == "$TARGET" ]]; then
  log "already running $TARGET -- nothing to do"
  exit 0
fi

if [[ -f $FAILED_REF ]] && [[ $(<"$FAILED_REF") == "$TARGET" ]]; then
  log "$TARGET failed its health check on an earlier run and was rolled back -- not retrying it."
  log "Fix it and push a new commit or tag, or delete $FAILED_REF to try this ref again."
  exit 0
fi

# --- prod: the vault backup, before anything is touched --------------------

backup_vault() {
  local stamp archive
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  archive="$BACKUPS/vault-$stamp.tar.gz"
  [[ -d $VAULT ]] || { log "no vault at $VAULT to back up"; return 1; }
  log "archiving the vault to ${archive##*/}"
  tar -czf "$archive.part" -C "$(dirname "$VAULT")" "$(basename "$VAULT")" \
    || { rm -f "$archive.part"; return 1; }
  # Read it back before it counts as a backup: a truncated archive that
  # nobody opened is worse than no archive, because it looks like one.
  tar -tzf "$archive.part" >/dev/null || { rm -f "$archive.part"; return 1; }
  mv -f "$archive.part" "$archive"
  chmod 0600 "$archive"
  # Prune only after a good archive exists, so a failed backup can never
  # be the run that deletes an old one. Newest first by mtime, same idiom
  # as deploy/backup_prod.sh's newest_in: `find -printf` rather than
  # `ls`, so a name is a name and not something the shell has to be
  # trusted to re-split.
  local stale
  mapfile -t stale < <(find "$BACKUPS" -maxdepth 1 -type f -name 'vault-*.tar.gz' \
                         -printf '%T@ %p\n' | LC_ALL=C sort -rn | cut -d' ' -f2- \
                       | tail -n +$((BACKUP_KEEP + 1)))
  if [[ ${#stale[@]} -gt 0 ]]; then
    log "pruning ${#stale[@]} vault archive(s) past the newest $BACKUP_KEEP"
    rm -f "${stale[@]}"
  fi
  log "vault backup ok: ${archive##*/} ($(du -h "$archive" | cut -f1))"
  return 0
}

if [[ $ENVIRONMENT == prod ]]; then
  backup_vault || fail 'the vault backup did not succeed -- deploying nothing'
fi

# --- build the release -----------------------------------------------------

RELEASE="$RELEASES/$TARGET"

build_release() {
  # A directory left behind by an interrupted run is never trusted: the
  # marker file is written first and removed last, so anything carrying
  # it is a half-built release and is rebuilt from scratch.
  if [[ -d $RELEASE ]]; then
    if [[ -e $RELEASE/.incomplete ]]; then
      log "an earlier run left $TARGET half-built -- rebuilding it"
      rm -rf "$RELEASE"
    else
      log "reusing the already-built release $TARGET"
      return 0
    fi
  fi
  log "checking out $CHECKOUT into releases/$TARGET"
  # Cloned from the local mirror rather than from GitHub again, so the
  # build does one fetch per run. --no-hardlinks keeps the release's
  # objects its own, so pruning the mirror later cannot gut a release
  # that is still live.
  #
  # One clone and one checkout is the whole source step. vendor/capa-repo
  # is an ordinary directory in this repository, so the checkout already
  # has it: no second credential, no second fetch, nothing to initialise.
  git clone --quiet --no-checkout --no-hardlinks "$MIRROR" "$RELEASE" \
    || fail "could not create releases/$TARGET"
  : >"$RELEASE/.incomplete"
  git -C "$RELEASE" checkout --quiet --detach "$CHECKOUT" \
    || fail "could not check out $CHECKOUT"

  log "creating the venv with $PYTHON and installing requirements.txt"
  "$PYTHON" -m venv "$RELEASE/.venv" || fail "$PYTHON -m venv failed"
  # requirements.txt only: the app's dependencies, not the test runner's
  # (requirements-dev.txt). A release serves; it does not run pytest.
  #
  # --only-binary=:all: is a deliberate refusal to compile. A future
  # dependency that ships no wheel for this python fails here, visibly,
  # with pip naming the package it could not get -- instead of trying to
  # build it on a 1.9 GB box that has no compiler toolchain since the apt
  # hardening, where the attempt would fail anyway behind a wall of
  # setuptools output. The whole pinned set installs from wheels on this
  # box's python 3.14.4, which the owner checked.
  "$RELEASE/.venv/bin/python" -m pip install --quiet --disable-pip-version-check \
      --no-input --only-binary=:all: -r "$RELEASE/requirements.txt" \
    || fail 'pip install -r requirements.txt failed'

  # vendor/capa-repo holds the `org_intake` capability as a plain
  # directory rather than a package on the index, so the release's venv
  # is told where it is -- the same one line README.md has a fresh clone
  # write by hand, and the same fact CI states as PYTHONPATH.
  local purelib
  purelib=$("$RELEASE/.venv/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  printf '%s\n' "$RELEASE/vendor/capa-repo" >"$purelib/org_intake_vendor.pth"

  # The release has to be able to import the app before it is allowed to
  # become `current`. This is the half of "flip only after health passes"
  # that can be checked without a running service: a release whose
  # dependencies did not land fails here and never gets the symlink, so
  # the only failures the rollback below has to cover are the ones that
  # need the app actually running.
  ( cd "$RELEASE" && ./.venv/bin/python -c 'import careeros.server' ) \
    || fail "releases/$TARGET cannot import careeros.server -- not activating it"

  chown -R "$SERVICE_USER:$SERVICE_USER" "$RELEASE"
  rm -f "$RELEASE/.incomplete"
  log "releases/$TARGET is built"
}

build_release

# --- activate --------------------------------------------------------------

if [[ -n $CURRENT_PATH && -d $CURRENT_PATH ]]; then
  point "$PREVIOUS" "$CURRENT_PATH"
  log "previous -> ${CURRENT_PATH##*/}"
fi
point "$CURRENT" "$RELEASE"
log "current -> $TARGET"
restart_service

if ! verify_live "$RELEASE"; then
  log "$TARGET did not come up healthy -- rolling back"
  printf '%s\n' "$TARGET" >"$FAILED_REF"
  roll_back_to_previous
  fail "$TARGET was rolled back"
fi
rm -f "$FAILED_REF"

# --- prune -----------------------------------------------------------------

# Compared by directory name, not by path: `readlink -f` resolves every
# symlink on the way down, so a /srv that is itself a link would make two
# spellings of the same release look like two releases -- and the one the
# symlinks point at is exactly the one that must never be pruned.
keep_names=("$TARGET")
previous=$(previous_release)
[[ -n $previous ]] && keep_names+=("${previous##*/}")
while IFS= read -r candidate; do
  [[ -n $candidate ]] || continue
  keep=no
  for name in "${keep_names[@]}"; do
    [[ ${candidate##*/} == "$name" ]] && keep=yes
  done
  [[ $keep == yes ]] && continue
  log "pruning release ${candidate##*/}"
  rm -rf "$candidate"
done < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
           | LC_ALL=C sort -rn | cut -d' ' -f2- | tail -n +$((KEEP + 1)))

log "deployed $TARGET on port $PORT"
