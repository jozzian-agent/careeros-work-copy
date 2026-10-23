#!/bin/bash
# First-time setup of a fresh Ubuntu VM for Career OS. Run by the owner,
# as root, once per machine:
#
#   sudo bash ~/deploy/setup-vps.sh
#
# IDEMPOTENT BY CONSTRUCTION. Every step reads the current state before
# it changes anything, so a second run reports what is already there and
# does nothing else. That is what makes it safe to re-run after a partial
# failure, and what makes it safe to read: there is no step that is only
# correct the first time.
#
# WHAT IT NEVER OVERWRITES
#   * /etc/careeros/{prod,stg}.env -- created with placeholder comments
#     when absent, left exactly as found when present. These hold the
#     owner's LLM keys and the smoke tester's password.
#   * /root/.ssh/careeros-{prod,stg}_deploy -- generated when absent,
#     left alone when present. Regenerating one would silently break
#     deploys until the new public key was added on GitHub.
#   * /etc/caddy/Caddyfile -- installed only while it is still the stock
#     default, so it cannot clobber the password hash or a hostname the
#     owner edited in.
#   * The vaults. Nothing here creates, moves or reads a record.
#
# WHAT IT DOES NOT DO
#   * Start either app service. They have no configuration yet: the env
#     files are placeholders and no release is deployed. The timers are
#     enabled, so the first staging deploy happens on its own within a
#     few minutes, or immediately with
#     `systemctl start careeros-deploy@stg`.
#   * Disable SSH password login. Doing that from a script is how a
#     person gets locked out of their own box. deploy/README.md has it as
#     a checklist step with the second-terminal check first.
#   * Touch any firewall rule other than the three ports named below.
#
# ARGUMENTS
#   --dry-run   print what each step would do and change nothing.
#
# ENVIRONMENT (for a rehearsal on a throwaway VM; defaults are the real
# layout)
#   CAREEROS_SETUP_ROOT       /srv/careeros
#   CAREEROS_SETUP_ENV_DIR    /etc/careeros
#   CAREEROS_SETUP_SSH_DIR    /root/.ssh
#   CAREEROS_SETUP_UNIT_DIR   /etc/systemd/system
#   CAREEROS_SETUP_CADDYFILE  /etc/caddy/Caddyfile
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

ROOT="${CAREEROS_SETUP_ROOT:-/srv/careeros}"
ENV_DIR="${CAREEROS_SETUP_ENV_DIR:-/etc/careeros}"
SSH_DIR="${CAREEROS_SETUP_SSH_DIR:-/root/.ssh}"
UNIT_DIR="${CAREEROS_SETUP_UNIT_DIR:-/etc/systemd/system}"
CADDYFILE="${CAREEROS_SETUP_CADDYFILE:-/etc/caddy/Caddyfile}"

ENVIRONMENTS=(prod stg)
UNITS=(careeros-prod.service careeros-stg.service careeros-deploy@.service)
TIMERS=(careeros-deploy-stg.timer careeros-deploy-prod.timer)
PORTS=(22 80 443)

DRY_RUN=no
[[ ${1:-} == --dry-run ]] && DRY_RUN=yes

step() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
skip() { printf '   already done: %s\n' "$*"; }
fail() { printf '\n!! %s\n' "$*" >&2; exit 1; }

run() {   # run <command...>: honor --dry-run for everything that changes state
  if [[ $DRY_RUN == yes ]]; then
    printf '   would run: %s\n' "$*"
    return 0
  fi
  "$@"
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'must run as root'
[[ -d $HERE/systemd ]] || fail "cannot find $HERE/systemd -- copy the whole deploy/ folder, not just this script"

if [[ $DRY_RUN == yes ]]; then
  printf 'DRY RUN: nothing below will be changed.\n'
fi

# --- packages --------------------------------------------------------------
# One apt update for the whole run, and `apt-get install` only for what
# is actually missing, so a re-run on a configured box makes no network
# call and holds no lock.

APT_UPDATED=no
apt_update_once() {
  [[ $APT_UPDATED == yes ]] && return 0
  run env DEBIAN_FRONTEND=noninteractive apt-get update -qq
  APT_UPDATED=yes
}

ensure_packages() {   # ensure_packages <package...>
  local missing=()
  for package in "$@"; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'ok installed' \
      || missing+=("$package")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    skip "installed: $*"
    return 0
  fi
  note "installing: ${missing[*]}"
  apt_update_once
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"
}

step 'Base packages'
# python3.11 explicitly, because that is the version requirements.txt is
# pinned against and the one deploy.sh builds every release venv with.
# git, curl and tar are what deploy.sh itself runs.
ensure_packages python3.11 python3.11-venv python3-pip git curl ca-certificates tar \
                ufw unattended-upgrades gpg debian-keyring debian-archive-keyring \
                apt-transport-https

step 'Caddy from the official repository'
# The four commands are the ones docs/runbooks/deploy-runbook.md Part 4
# names, so the script and the runbook can be read against each other.
# Guarded on the keyring and list files rather than on the package, so a
# half-finished earlier run is completed rather than skipped.
CADDY_KEYRING=/usr/share/keyrings/caddy-stable-archive-keyring.gpg
CADDY_LIST=/etc/apt/sources.list.d/caddy-stable.list
if [[ -s $CADDY_KEYRING ]]; then
  skip "$CADDY_KEYRING"
else
  note 'fetching the Caddy signing key'
  if [[ $DRY_RUN == yes ]]; then
    note "would fetch https://dl.cloudsmith.io/public/caddy/stable/gpg.key into $CADDY_KEYRING"
  else
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
      | gpg --dearmor -o "$CADDY_KEYRING" \
      || fail 'could not fetch the Caddy signing key'
    chmod 0644 "$CADDY_KEYRING"
  fi
fi
if [[ -s $CADDY_LIST ]]; then
  skip "$CADDY_LIST"
else
  note 'adding the Caddy apt source'
  if [[ $DRY_RUN == yes ]]; then
    note "would write the cloudsmith deb line into $CADDY_LIST"
  else
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' >"$CADDY_LIST" \
      || { rm -f "$CADDY_LIST"; fail 'could not fetch the Caddy apt source list'; }
    APT_UPDATED=no
  fi
fi
ensure_packages caddy

step 'unattended-upgrades'
# The package is installed above; this is the half that turns it on.
if [[ -f /etc/apt/apt.conf.d/20auto-upgrades ]]; then
  skip '/etc/apt/apt.conf.d/20auto-upgrades'
else
  note 'enabling automatic security updates'
  if [[ $DRY_RUN == yes ]]; then
    note 'would write /etc/apt/apt.conf.d/20auto-upgrades'
  else
    cat >/etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
  fi
fi

# --- users and groups ------------------------------------------------------

step 'Service users and groups'
for environment in "${ENVIRONMENTS[@]}"; do
  account="careeros-$environment"
  if getent group "$account" >/dev/null; then
    skip "group $account"
  else
    note "creating group $account"
    run groupadd --system "$account"
  fi
  if getent passwd "$account" >/dev/null; then
    skip "user $account"
  else
    # System account, no login shell, no home of its own: it exists to
    # own a vault and run one service.
    note "creating user $account (nologin)"
    run useradd --system --gid "$account" --shell /usr/sbin/nologin \
                --home-dir "$ROOT/$environment" --no-create-home "$account"
  fi
done

# --- directories -----------------------------------------------------------

step 'Directories'
# The vault is 700 and owned by the service user: the records, the id
# counters and the session signing key are in there, and nothing else on
# the box has any business reading them. Everything above it is 755,
# because Caddy and the owner both have to be able to walk the path.
ensure_dir() {   # ensure_dir <path> <mode> <owner:group>
  local path=$1 mode=$2 own=$3
  if [[ -d $path ]]; then
    skip "$path"
  else
    note "creating $path ($mode, $own)"
    run install -d -m "$mode" -o "${own%%:*}" -g "${own##*:}" "$path"
    return 0
  fi
  # Already there: correct the mode and owner anyway. A vault that was
  # restored from a backup or copied in by hand can arrive 755 or
  # root-owned, and either one is a leak this script exists to prevent.
  local actual
  actual=$(stat -c '%a %U:%G' "$path")
  if [[ $actual != "$mode $own" ]]; then
    note "fixing $path: $actual -> $mode $own"
    run chmod "$mode" "$path"
    run chown "$own" "$path"
  fi
}

ensure_dir "$ROOT" 755 root:root
for environment in "${ENVIRONMENTS[@]}"; do
  account="careeros-$environment"
  ensure_dir "$ROOT/$environment" 755 root:root
  ensure_dir "$ROOT/$environment/app" 755 "root:root"
  ensure_dir "$ROOT/$environment/app/releases" 755 root:root
  ensure_dir "$ROOT/$environment/vault" 700 "$account:$account"
done
# Production keeps the pre-deploy vault archives. Root-only: an archive
# is the whole vault in one file.
ensure_dir "$ROOT/prod/backups" 700 root:root

step "deploy.sh at $ROOT/deploy.sh"
# One copy, run for both environments, which is the path
# careeros-deploy@.service names. Replaced on every run so a re-run after
# an update to this folder actually updates it.
if [[ $DRY_RUN == yes ]]; then
  note "would install $HERE/deploy.sh to $ROOT/deploy.sh"
elif cmp -s "$HERE/deploy.sh" "$ROOT/deploy.sh"; then
  skip "$ROOT/deploy.sh is current"
else
  note "installing $ROOT/deploy.sh"
  install -m 0755 -o root -g root "$HERE/deploy.sh" "$ROOT/deploy.sh"
fi

# --- env files -------------------------------------------------------------

step 'Environment files'
# Root-owned, mode 0640, group = the service's group: the service can
# read it, nothing else on the box can. Created with nothing but
# placeholder comments, so a box that has been set up but not configured
# fails loudly rather than running on a guess. NEVER overwritten.
ensure_dir "$ENV_DIR" 755 root:root
for environment in "${ENVIRONMENTS[@]}"; do
  account="careeros-$environment"
  path="$ENV_DIR/$environment.env"
  if [[ -e $path ]]; then
    skip "$path (left exactly as it is)"
    # The permissions are still checked, because this is the file the
    # LLM key and the tester's password live in.
    actual=$(stat -c '%a %U:%G' "$path")
    if [[ $actual != "640 root:$account" ]]; then
      note "fixing $path: $actual -> 640 root:$account"
      run chmod 0640 "$path"
      run chown "root:$account" "$path"
    fi
    continue
  fi
  note "creating $path with placeholders only"
  if [[ $DRY_RUN == yes ]]; then
    note "would write $path (0640 root:$account)"
    continue
  fi
  install -m 0640 -o root -g "$account" /dev/null "$path"
  cat >"$path" <<CONF
# Career OS $environment. Read by careeros-$environment.service
# (EnvironmentFile) and by tests/smoke.sh.
#
# Every line below is a comment. Fill in the ones this environment needs
# with 'sudoedit $path', which keeps the values off every command line
# and out of shell history. The full list of variables, with what each
# one does, is .env.example in the repo.
#
# Mode 0640, root:$account. Keep it that way: the service reads it,
# nothing else may.

# --- the LLM (deploy runbook Part 5) ---
# One key per environment, each with its own spend limit in OpenRouter.
# Never reuse the production key here or anywhere else.
# LLM_BASE_URL=https://openrouter.ai/api/v1
# LLM_MODEL=the-model-name
# LLM_API_KEY=paste-the-key-here

# Until there is a key: answer from canned replies and make no network
# call (LLM_MOCK=1), or refuse every call with one clean error
# (LLM_DISABLED=1). Pick one; LLM_DISABLED wins if both are set.
# LLM_MOCK=1

# --- the session cookie ---
# This environment is reached through Caddy over HTTPS, so the session
# cookie must never travel any other way.
SESSION_COOKIE_SECURE=1

# --- the built front end ---
# Most pages are React-only. Uncomment once a release carries a
# frontend/dist build (see deploy/README.md, "Known gaps").
# CAREEROS_REACT_UI=1

# --- the smoke test (deploy/README.md, "The smoke tester account") ---
# A dedicated tester account, never the owner's. The password is
# generated into a root-owned file and copied in here with sudoedit; it
# is never typed and never on a command line.
# SMOKE_EMAIL=smoke@career-os.ch
# SMOKE_PASSWORD=paste-the-generated-line-here
CONF
done

# --- deploy keys -----------------------------------------------------------

step 'Read-only deploy keys'
# One ed25519 pair per environment, no passphrase (nothing is there to
# type one at boot), generated here and never anywhere else. Only the
# PUBLIC half ever leaves this box, and it is printed at the end for the
# owner to paste into GitHub with write access OFF.
ensure_dir "$SSH_DIR" 700 root:root
for environment in "${ENVIRONMENTS[@]}"; do
  key="$SSH_DIR/careeros-${environment}_deploy"
  if [[ -f $key ]]; then
    skip "$key (not regenerated: the public half is already on GitHub)"
    continue
  fi
  note "generating $key"
  run ssh-keygen -q -t ed25519 -N '' -C "careeros-$environment deploy (read-only)" -f "$key"
done

step "GitHub's host key in $SSH_DIR/known_hosts"
# Recorded once, here, so deploy.sh can run with
# StrictHostKeyChecking=yes: an unknown host key during a deploy then
# stops the deploy instead of being accepted by a script with nobody
# watching. The fingerprint is printed at the end so the owner can
# compare it against the one GitHub publishes.
KNOWN_HOSTS="$SSH_DIR/known_hosts"
if [[ -f $KNOWN_HOSTS ]] && ssh-keygen -F github.com -f "$KNOWN_HOSTS" >/dev/null 2>&1; then
  skip 'github.com is already in known_hosts'
elif [[ $DRY_RUN == yes ]]; then
  note "would run ssh-keyscan -t rsa,ecdsa,ed25519 github.com >> $KNOWN_HOSTS"
else
  note 'recording github.com'
  umask 077
  ssh-keyscan -t rsa,ecdsa,ed25519 github.com >>"$KNOWN_HOSTS" 2>/dev/null \
    || fail "could not reach github.com to record its host key -- fix networking and re-run"
  chmod 0600 "$KNOWN_HOSTS"
fi

# --- systemd ---------------------------------------------------------------

step 'systemd units and timers'
installed_any=no
for unit in "${UNITS[@]}" "${TIMERS[@]}"; do
  source_file="$HERE/systemd/$unit"
  [[ -f $source_file ]] || fail "missing $source_file"
  if cmp -s "$source_file" "$UNIT_DIR/$unit"; then
    skip "$unit is current"
    continue
  fi
  note "installing $unit"
  run install -m 0644 -o root -g root "$source_file" "$UNIT_DIR/$unit"
  installed_any=yes
done
if [[ $installed_any == yes ]]; then
  run systemctl daemon-reload
fi

# Enabled, not started: an app service with a placeholder env file and no
# release to run would only fail-loop. The timers are what bring the
# first release in.
for unit in "${UNITS[@]}"; do
  [[ $unit == *@.service ]] && continue
  if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
    skip "$unit is enabled"
  else
    note "enabling $unit (not starting it)"
    run systemctl enable "$unit"
  fi
done
for timer in "${TIMERS[@]}"; do
  if systemctl is-enabled --quiet "$timer" 2>/dev/null; then
    skip "$timer is enabled"
  else
    note "enabling and starting $timer"
    run systemctl enable --now "$timer"
  fi
done

# --- Caddy -----------------------------------------------------------------

step "Caddyfile at $CADDYFILE"
# Installed ONLY over the stock default. Caddy's package ships a
# Caddyfile that serves its own welcome page; that one is safe to
# replace. Anything else is the owner's -- it holds the staging password
# hash, which this repo must never contain -- and is left alone.
if [[ ! -f $CADDYFILE ]]; then
  note "installing $CADDYFILE (none was there)"
  run install -m 0644 -o root -g root "$HERE/Caddyfile" "$CADDYFILE"
elif cmp -s "$HERE/Caddyfile" "$CADDYFILE"; then
  skip "$CADDYFILE is already this file"
elif grep -q 'PASTE_HASH_HERE' "$CADDYFILE"; then
  skip "$CADDYFILE is ours and still has the placeholder hash -- left alone so an edit in progress is not lost"
elif grep -qE 'The Caddy web server|caddyserver\.com/docs|# The Caddyfile is an easy way' "$CADDYFILE"; then
  note "replacing the stock default $CADDYFILE"
  run cp -a "$CADDYFILE" "$CADDYFILE.stock-default"
  run install -m 0644 -o root -g root "$HERE/Caddyfile" "$CADDYFILE"
else
  skip "$CADDYFILE is not the stock default -- NOT touched. Compare it against $HERE/Caddyfile yourself."
fi

# --- firewall --------------------------------------------------------------

step 'Firewall (ufw)'
# 22, 80, 443 and nothing else. Both app processes bind 127.0.0.1, so
# 8001 and 8002 are not reachable from outside whatever ufw says, and
# they are deliberately not opened: two defences, not one.
#
# The allow rules go in BEFORE enable. `ufw enable` on a box reached over
# SSH with no rule for 22 is how a person locks themselves out.
for port in "${PORTS[@]}"; do
  if ufw status | grep -qE "^$port(/tcp)?[[:space:]]+ALLOW"; then
    skip "ufw allows $port"
  else
    note "allowing $port/tcp"
    run ufw allow "$port/tcp"
  fi
done
if ufw status | head -1 | grep -q 'Status: active'; then
  skip 'ufw is active'
else
  note 'enabling ufw'
  run ufw --force enable
fi

# --- what the owner does next ----------------------------------------------

printf '\n'
printf '=========================================================================\n'
printf ' Setup finished. Four things are now the owner'\''s to do.\n'
printf '=========================================================================\n'

printf '\n1. ADD THESE TWO DEPLOY KEYS to github.com/jozzian/careeros\n'
printf '   Settings -> Deploy keys -> Add deploy key.\n'
printf '   Leave "Allow write access" OFF for both. They only ever pull.\n'
for environment in "${ENVIRONMENTS[@]}"; do
  key="$SSH_DIR/careeros-${environment}_deploy.pub"
  printf '\n   --- careeros-%s ---\n' "$environment"
  if [[ -f $key ]]; then
    printf '   '
    cat "$key"
  else
    printf '   (not generated: this was a dry run)\n'
  fi
done

printf '\n   The host key this box will trust for github.com:\n'
if [[ -f $KNOWN_HOSTS ]]; then
  ssh-keygen -lf "$KNOWN_HOSTS" 2>/dev/null | sed 's/^/     /' || true
  printf '   Compare these against the fingerprints GitHub publishes at\n'
  printf '   docs.github.com -> "GitHub'\''s SSH key fingerprints" before the first deploy.\n'
else
  printf '     (none recorded: this was a dry run)\n'
fi

printf '\n2. FILL IN THE ENV FILES. They hold only placeholders right now:\n'
for environment in "${ENVIRONMENTS[@]}"; do
  printf '     sudoedit %s/%s.env\n' "$ENV_DIR" "$environment"
done
printf '   The variables and what each one does: .env.example in the repo.\n'

printf '\n3. SET THE STAGING PASSWORD in Caddy:\n'
printf '     caddy hash-password            # prompts, prints a hash\n'
printf '     sudoedit %s        # replace PASTE_HASH_HERE\n' "$CADDYFILE"
printf '     caddy validate --config %s\n' "$CADDYFILE"
printf '     systemctl reload caddy\n'

printf '\n4. HARDEN SSH, with a second terminal already open and key login\n'
printf '   proven in it. This script deliberately did not do it for you.\n'
printf '   deploy/README.md has the exact steps.\n'

printf '\nThe services are enabled but NOT started: they have no release yet.\n'
printf 'The staging timer will deploy within a few minutes, or start one now:\n'
printf '     systemctl start careeros-deploy@stg\n'
printf '     journalctl -u careeros-deploy@stg -n 50 --no-pager\n'
printf '\n'
