#!/bin/bash
# First-time setup of this VPS for Career OS. Run by the owner, as root,
# once per machine:
#
#   sudo deploy/setup-vps.sh --check     # read the plan, change nothing
#   sudo deploy/setup-vps.sh             # do it
#
# It runs as root and uses no `sudo` of its own, so there is nothing in
# here that could prompt for a password halfway through. To check that
# your account can become root without a prompt, run `sudo -n true`
# BEFORE this script: it exits 0 when sudo needs no password. (`sudo -v`
# prompts even where real commands do not, so it answers a different
# question.)
#
# WHAT THIS MACHINE IS (verified on the box, 2026-10-23)
#   Ubuntu 26.04.1 LTS, amd64, system python3 = 3.14.4.
#   2 vCPU, 1.9 GB RAM, 37.6 GB disk, no swap when it arrived.
#   Staging and production both run here, behind one Caddy.
#   Login is the `ubuntu` account with an SSH key; password login is
#   already off.
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
#     owner's LLM keys and the tester's password.
#   * /root/.ssh/careeros-{prod,stg}_deploy -- generated when absent,
#     left alone when present. Regenerating one would silently break
#     deploys until the new public key was added on GitHub.
#   * /etc/caddy/Caddyfile -- installed only while it is still the stock
#     default, so it cannot clobber the password hash or a hostname the
#     owner edited in.
#   * The vaults. Nothing here creates, moves or reads a record.
#   * SSH. Not sshd_config, not authorized_keys, not the sshd service,
#     nothing. This box is key-only already, and a script that edits SSH
#     while the owner is logged in over SSH is how a person loses access
#     to their own machine. If it is ever worth changing, it is worth
#     doing by hand with a second terminal open. ufw keeps 22 open.
#
# WHAT IT DOES NOT START
#   * careeros-prod.service and careeros-deploy-prod.timer are INSTALLED
#     and nothing more: not enabled, not started. Production begins when
#     the owner says so (deploy/RUNBOOK.md, "Production, the first time").
#   * careeros-stg.service is installed and not started: there is no
#     release yet to run.
#   * careeros-deploy-stg.timer is installed and NOT started here. It is
#     a RUNBOOK step (step 7), turned on only after the env file is
#     filled in and the first deploy has been watched by hand -- so a
#     timer never fires before the config exists.
#   The last thing this script prints is exactly that state, with the
#   commands to change it.
#
# ARGUMENTS
#   --check   print what each step would do and change nothing.
#
# ENVIRONMENT (the defaults are the real layout; the overrides exist so
# tests/test_deploy_config.py can run --check against a fake root)
#   CAREEROS_SETUP_ROOT       /srv/careeros
#   CAREEROS_SETUP_ENV_DIR    /etc/careeros
#   CAREEROS_DEPLOY_SSH_DIR   /root/.ssh
#   CAREEROS_SETUP_UNIT_DIR   /etc/systemd/system
#   CAREEROS_SETUP_CADDYFILE  /etc/caddy/Caddyfile
#   CAREEROS_SETUP_SWAPFILE   /swapfile
#   CAREEROS_SETUP_SWAP_MB    2048
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=$(dirname "$HERE")

ROOT="${CAREEROS_SETUP_ROOT:-/srv/careeros}"
ENV_DIR="${CAREEROS_SETUP_ENV_DIR:-/etc/careeros}"
# The same variable deploy.sh reads, so the two scripts cannot disagree
# about where this environment's deploy key is.
SSH_DIR="${CAREEROS_DEPLOY_SSH_DIR:-/root/.ssh}"
UNIT_DIR="${CAREEROS_SETUP_UNIT_DIR:-/etc/systemd/system}"
CADDYFILE="${CAREEROS_SETUP_CADDYFILE:-/etc/caddy/Caddyfile}"
SWAPFILE="${CAREEROS_SETUP_SWAPFILE:-/swapfile}"
SWAP_MB="${CAREEROS_SETUP_SWAP_MB:-2048}"

#: The python this box has. No version-suffixed binary exists on it and
#: nothing installs one: `python3` IS 3.14.4 here, and the check below
#: proves it rather than trusting it.
PYTHON=python3
PYTHON_MIN='3.14'

ENVIRONMENTS=(prod stg)
UNITS=(careeros-prod.service careeros-stg.service careeros-deploy@.service)
TIMERS=(careeros-deploy-stg.timer careeros-deploy-prod.timer)
#: Enabled and started by this script: NOTHING. Every unit and timer in
#: UNITS and TIMERS is installed and left alone -- see "WHAT IT DOES NOT
#: START". The staging deploy timer is a RUNBOOK step (deploy/RUNBOOK.md,
#: step 7) taken only after the env file is filled in and the first
#: deploy has been watched by hand, because a timer that fires before
#: the config exists makes the first deploy something the owner reads
#: about in a journal instead of watching happen.
PORTS=(22 80 443)

CHECK_ONLY=no
case ${1:-} in
  '') ;;
  --check) CHECK_ONLY=yes ;;
  *) printf 'usage: %s [--check]\n' "${0##*/}" >&2; exit 64 ;;
esac

step() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
skip() { printf '   already done: %s\n' "$*"; }
fail() { printf '\n!! %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

run() {   # run <command...>: honor --check for everything that changes state
  if [[ $CHECK_ONLY == yes ]]; then
    printf '   would run: %s\n' "$*"
    return 0
  fi
  "$@"
}

IS_ROOT=yes
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  IS_ROOT=no
  # A real run has to be root: it creates users, writes /etc and
  # restarts systemd units. --check writes nothing at all, so it is
  # allowed either way -- reading the plan should not need privilege, and
  # it is one fewer reason to run an unread script as root.
  [[ $CHECK_ONLY == yes ]] || fail "must run as root: try  sudo $0"
fi
[[ -d $HERE/systemd ]] || fail "cannot find $HERE/systemd -- copy the whole deploy/ folder, not just this script"

if [[ $CHECK_ONLY == yes ]]; then
  printf 'CHECK ONLY: nothing below will be changed.\n'
  [[ $IS_ROOT == yes ]] \
    || printf 'Not root, so anything under /root and /etc reads as absent.\n'
fi

# --- python ----------------------------------------------------------------
# First, because everything else is pointless if the interpreter this box
# has cannot run the app. Checked with the interpreter itself rather than
# by parsing a version string: `python3 --version` prints a string this
# script would then have to compare by hand, and sys.version_info is the
# comparison already done correctly.

step "Python (needs $PYTHON_MIN or newer)"
have "$PYTHON" || fail "no $PYTHON on this box, which should be impossible on Ubuntu 26.04"
PYTHON_FOUND=$("$PYTHON" --version 2>&1 || true)
if "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)'; then
  note "$PYTHON is $PYTHON_FOUND"
else
  fail "$PYTHON is $PYTHON_FOUND, older than $PYTHON_MIN.
   Every release venv is built with this interpreter (deploy/deploy.sh,
   CAREEROS_DEPLOY_PYTHON), so a box whose python3 is older than
   $PYTHON_MIN would build releases nobody has tested. Either update the
   system python3, or set CAREEROS_DEPLOY_PYTHON to a newer one that is
   really installed -- do NOT invent a binary name."
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
# No version-suffixed python package anywhere: python3-venv and
# python3-pip follow this release's own python3, which is the 3.14 the
# check above just confirmed. git, curl and tar are what deploy.sh runs.
ensure_packages python3-venv python3-pip git curl ca-certificates tar \
                ufw unattended-upgrades gpg debian-keyring debian-archive-keyring \
                apt-transport-https

step 'Caddy from the official repository'
# Guarded on the keyring and list files rather than on the package, so a
# half-finished earlier run is completed rather than skipped.
CADDY_KEYRING=/usr/share/keyrings/caddy-stable-archive-keyring.gpg
CADDY_LIST=/etc/apt/sources.list.d/caddy-stable.list
if [[ -s $CADDY_KEYRING ]]; then
  skip "$CADDY_KEYRING"
elif [[ $CHECK_ONLY == yes ]]; then
  note "would fetch https://dl.cloudsmith.io/public/caddy/stable/gpg.key into $CADDY_KEYRING"
else
  note 'fetching the Caddy signing key'
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o "$CADDY_KEYRING" \
    || fail 'could not fetch the Caddy signing key'
  chmod 0644 "$CADDY_KEYRING"
fi
if [[ -s $CADDY_LIST ]]; then
  skip "$CADDY_LIST"
elif [[ $CHECK_ONLY == yes ]]; then
  note "would write the cloudsmith deb line into $CADDY_LIST"
else
  note 'adding the Caddy apt source'
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' >"$CADDY_LIST" \
    || { rm -f "$CADDY_LIST"; fail 'could not fetch the Caddy apt source list'; }
  APT_UPDATED=no
fi
ensure_packages caddy

step 'unattended-upgrades'
# The package is installed above; this is the half that turns it on.
if [[ -f /etc/apt/apt.conf.d/20auto-upgrades ]]; then
  skip '/etc/apt/apt.conf.d/20auto-upgrades'
elif [[ $CHECK_ONLY == yes ]]; then
  note 'would write /etc/apt/apt.conf.d/20auto-upgrades'
else
  note 'enabling automatic security updates'
  cat >/etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
fi

# --- swap ------------------------------------------------------------------
# This box arrived with 1.9 GB of RAM and no swap, and runs two app
# processes plus a pip install during every deploy. Without swap the
# kernel's only answer to a spike is to kill something; with it, the
# deploy gets slow instead of dead. 2 GB on a 37.6 GB disk.
#
# swappiness 10: swap is there for the spike, not for routine paging of a
# process that fits in RAM.

step "Swap ($SWAP_MB MB at $SWAPFILE)"
swap_total_mb() { awk '/^SwapTotal:/ { print int($2 / 1024) }' /proc/meminfo; }
SWAP_NOW=$(swap_total_mb)
RECORD_SWAPFILE=yes
if (( SWAP_NOW >= 1024 )) && [[ ! -e $SWAPFILE ]]; then
  # Swap is already covered by something this script did not make: a
  # partition, or a file somewhere else. Nothing to create -- and
  # nothing to put in /etc/fstab either, because a line naming a file
  # that does not exist is a failed swap unit at every boot.
  skip "${SWAP_NOW} MB of swap is already active, and there is no $SWAPFILE to record"
  RECORD_SWAPFILE=no
elif (( SWAP_NOW >= 1024 )); then
  skip "${SWAP_NOW} MB of swap is already active"
elif [[ -e $SWAPFILE ]]; then
  # Present but not in use: a previous run that was interrupted between
  # mkswap and swapon, or a reboot with no fstab line. Do not re-create
  # it (that would discard a file this script cannot prove is unused);
  # turn it on and record it.
  note "$SWAPFILE exists but swap is only ${SWAP_NOW} MB -- enabling the existing file"
  run swapon "$SWAPFILE" || note "swapon $SWAPFILE failed; look at it by hand"
else
  note "creating $SWAPFILE"
  run fallocate -l "${SWAP_MB}M" "$SWAPFILE" \
    || run dd if=/dev/zero of="$SWAPFILE" bs=1M count="$SWAP_MB" status=none
  run chmod 600 "$SWAPFILE"
  run mkswap -q "$SWAPFILE"
  run swapon "$SWAPFILE"
fi
# One fstab line, matched on the path so a re-run never adds a second.
# Without it the swap file is forgotten at the next boot, which is the
# reboot where the box quietly goes back to having no swap at all.
if [[ $RECORD_SWAPFILE == no ]]; then
  : # nothing of ours to record
elif grep -qF "$SWAPFILE" /etc/fstab; then
  skip "$SWAPFILE is in /etc/fstab"
elif [[ $CHECK_ONLY == yes ]]; then
  note "would append '$SWAPFILE none swap sw 0 0' to /etc/fstab"
else
  note "recording $SWAPFILE in /etc/fstab"
  printf '%s none swap sw 0 0\n' "$SWAPFILE" >>/etc/fstab
fi
SYSCTL_FILE=/etc/sysctl.d/99-careeros.conf
if [[ -f $SYSCTL_FILE ]]; then
  skip "$SYSCTL_FILE"
elif [[ $CHECK_ONLY == yes ]]; then
  note "would write vm.swappiness=10 into $SYSCTL_FILE and apply it"
else
  note 'setting vm.swappiness=10'
  printf 'vm.swappiness=10\n' >"$SYSCTL_FILE"
  sysctl -q -p "$SYSCTL_FILE" || note "could not apply $SYSCTL_FILE now; it applies at the next boot"
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
    # own a vault and run one service. It holds no credential of any
    # kind -- the deploy key is root's (deploy/RUNBOOK.md, "Why the app
    # users hold no key").
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
  if [[ ! -d $path ]]; then
    note "creating $path ($mode, $own)"
    run install -d -m "$mode" -o "${own%%:*}" -g "${own##*:}" "$path"
    return 0
  fi
  skip "$path"
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
  ensure_dir "$ROOT/$environment/app" 755 root:root
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
if cmp -s "$HERE/deploy.sh" "$ROOT/deploy.sh"; then
  skip "$ROOT/deploy.sh is current"
else
  note "installing $ROOT/deploy.sh"
  run install -m 0755 -o root -g root "$HERE/deploy.sh" "$ROOT/deploy.sh"
fi

# --- the dependency guard --------------------------------------------------
# The one thing about this box that cannot be read off a fact sheet: does
# every pinned dependency actually build or have a wheel for python 3.14?
# A release venv is built during a deploy, by a timer, with nobody
# watching -- so the answer is found out HERE, once, loudly, with the
# offending package named, rather than in a journal entry at 03:00.
#
# A throwaway venv in a temporary directory, removed either way: nothing
# about this step survives it.

step 'Dependency check (requirements.txt in a throwaway venv)'
REQUIREMENTS="$REPO/requirements.txt"
if [[ ! -f $REQUIREMENTS ]]; then
  note "no $REQUIREMENTS here, so the dependencies were NOT checked."
  note 'That happens when only deploy/ was copied over. It is not fatal --'
  note 'the first deploy builds a venv from the release it checks out --'
  note 'but then pip is proving it in a journal rather than in front of you.'
elif [[ $CHECK_ONLY == yes ]]; then
  note "would create a throwaway venv and pip-install $REQUIREMENTS into it"
else
  SCRATCH=$(mktemp -d -t careeros-setup-venv-XXXXXX)
  # Removed whether this succeeds, fails or is interrupted.
  trap 'rm -rf "${SCRATCH:?}"' EXIT
  note "building $SCRATCH/venv with $PYTHON ($PYTHON_FOUND)"
  "$PYTHON" -m venv "$SCRATCH/venv" || fail "$PYTHON -m venv failed -- is python3-venv installed?"
  "$SCRATCH/venv/bin/python" -m pip install --quiet --disable-pip-version-check \
      --no-input -r "$REQUIREMENTS" >"$SCRATCH/pip.log" 2>&1 || {
    # pip names the package it could not build; that line is the whole
    # point of this step, so it is printed rather than summarised.
    printf '\n'
    sed 's/^/   pip: /' "$SCRATCH/pip.log" >&2 || true
    offender=$(grep -oE '(Getting requirements to build wheel|Building wheel for|Could not find a version that satisfies the requirement|ERROR: No matching distribution found for) [^ ]+' \
                 "$SCRATCH/pip.log" | tail -1 | awk '{print $NF}' || true)
    fail "requirements.txt does not install under $PYTHON_FOUND${offender:+ -- the last package pip was working on was $offender}.
   The pip output above says which it was and why. Nothing on this box is
   broken and this step changed nothing.
   If a package has no 3.14 wheel or build, the fix is a repository
   change: pin a version that does, and re-run this script. Do NOT work
   around it by installing another python -- deploy.sh builds every
   release venv with $PYTHON.
   If pip could not reach the index at all, that is a network problem and
   this script can be re-run as soon as it is fixed."
  }
  note "requirements.txt installs cleanly under $PYTHON_FOUND"
  rm -rf "${SCRATCH:?}"
  trap - EXIT
fi

# --- env files -------------------------------------------------------------

step 'Environment files'
# Root-owned, mode 0640, group = the service's group: the service can
# read it, nothing else on the box can. Created with nothing but
# placeholder comments, so a box that has been set up but not configured
# runs the app with no LLM -- which the app reports as `not_configured`
# rather than inventing anything. NEVER overwritten.
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
  if [[ $CHECK_ONLY == yes ]]; then
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
# one does and which file reads it, is .env.example in the repo.
#
# Mode 0640, root:$account. Keep it that way: the service reads it,
# nothing else may.
#
# The host and the port are NOT here. The app takes them as command-line
# flags and reads no variable for them, so careeros-$environment.service
# passes them on ExecStart. A line here would be read by nothing.

# --- the LLM ---
# One key per environment, each with its own spend limit. Never reuse the
# production key here or anywhere else. With none of these set, the app
# still runs: an extraction settles as 'not_configured', which is a
# visible failure and not an invented record.
# LLM_BASE_URL=https://openrouter.ai/api/v1
# LLM_MODEL=the-model-name
# LLM_API_KEY=paste-the-key-here

# --- the built front end ---
# Most pages are React-only. Uncomment once a release carries a
# frontend/dist build (see deploy/RUNBOOK.md, "Known gaps").
# CAREEROS_REACT_UI=1

# --- the smoke test (deploy/RUNBOOK.md, "The tester account") ---
# A dedicated tester account, never the owner's. The password is
# generated into a root-owned file and copied in here with sudoedit; it
# is never typed and never on a command line.
# SMOKE_EMAIL=the-tester-account-you-created
# SMOKE_PASSWORD=paste-the-generated-line-here
CONF
done

# --- deploy keys -----------------------------------------------------------

step 'Read-only deploy keys'
# One ed25519 pair per environment, no passphrase (nothing is there to
# type one at boot), generated here and never anywhere else. Root-owned,
# in root's own .ssh: the app users must never be able to read a
# repository credential (deploy/RUNBOOK.md, "Why the app users hold no
# key"). Only the PUBLIC half ever leaves this box, and it is printed at
# the end for the owner to paste into GitHub with write access OFF.
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
elif [[ $CHECK_ONLY == yes ]]; then
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

# Nothing is enabled or started by this script. Every unit and timer is
# a file on disk and a line in the printout below: the app services have
# no release to run yet, production is the owner's to open, and the
# staging deploy timer waits until the env file exists and the first
# deploy has been watched by hand (deploy/RUNBOOK.md, steps 5-7).

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
# they are deliberately not opened: two defences, not one. 22 stays open
# because this box is reached over SSH and nothing here touches SSH.
#
# The allow rules go in BEFORE enable. `ufw enable` on a box reached over
# SSH with no rule for 22 is how a person locks themselves out.
if ! have ufw; then
  note 'ufw is not installed yet (a real run installs it above), so there'
  note 'is nothing to read. A real run allows 22, 80 and 443 and enables it.'
elif [[ $IS_ROOT == no ]]; then
  note 'reading ufw status needs root, so this --check cannot say what the'
  note 'firewall holds. A real run allows 22, 80 and 443 and enables it.'
else
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
fi

# --- what the owner does next ----------------------------------------------

printf '\n'
printf '=========================================================================\n'
if [[ $CHECK_ONLY == yes ]]; then
  printf ' That was --check. NOTHING above was changed. Re-run without --check.\n'
else
  printf ' Setup finished. Three things are now the owner'\''s to do.\n'
fi
printf '=========================================================================\n'

printf '\n1. ADD THESE TWO DEPLOY KEYS on GitHub:\n'
printf '   github.com/jozzian/careeros -> Settings -> Deploy keys\n'
printf '   -> Add deploy key. Leave "Allow write access" OFF for both.\n'
printf '   They only ever pull, and they are read-only on GitHub'\''s side too.\n'
for environment in "${ENVIRONMENTS[@]}"; do
  key="$SSH_DIR/careeros-${environment}_deploy.pub"
  printf '\n   --- careeros-%s (title it that) ---\n' "$environment"
  if [[ -f $key ]]; then
    printf '   '
    cat "$key"
  else
    printf '   (not generated yet: this was a --check run)\n'
  fi
done

printf '\n   The host key this box will trust for github.com:\n'
if [[ -f $KNOWN_HOSTS ]]; then
  ssh-keygen -lf "$KNOWN_HOSTS" 2>/dev/null | sed 's/^/     /' || true
  printf '   Compare these against the fingerprints GitHub publishes at\n'
  printf '   docs.github.com -> "GitHub'\''s SSH key fingerprints" before the first deploy.\n'
else
  printf '     (none recorded yet: this was a --check run)\n'
fi

printf '\n2. FILL IN THE ENV FILES. They hold only placeholders right now:\n'
for environment in "${ENVIRONMENTS[@]}"; do
  printf '     sudoedit %s/%s.env\n' "$ENV_DIR" "$environment"
done
printf '   The variables, what each one does and which file reads it:\n'
printf '   .env.example in the repo. Staging first -- production can wait.\n'

printf '\n3. SET THE STAGING PASSWORD in Caddy:\n'
printf '     caddy hash-password            # prompts, prints a hash\n'
printf '     sudoedit %s        # replace PASTE_HASH_HERE\n' "$CADDYFILE"
printf '     caddy validate --config %s\n' "$CADDYFILE"
printf '     systemctl reload caddy\n'

# printf '%s\n' here, not printf '----\n': a format string that begins
# with a dash is read as an option, which is how this block once ended an
# otherwise successful run with "printf: --: invalid option" and exit 2.
RULE='-------------------------------------------------------------------------'
printf '\n%s\n' "$RULE"
if [[ $CHECK_ONLY == yes ]]; then
  printf ' WHAT A REAL RUN WOULD LEAVE RUNNING, EXACTLY\n'
  printf ' (this was --check, so nothing below is enabled or started yet)\n'
else
  printf ' WHAT IS RUNNING NOW, EXACTLY\n'
fi
printf '%s\n' "$RULE"
printf '   careeros-deploy-stg.timer     installed, NOT enabled, NOT started.\n'
printf '                                 Step 7 of deploy/RUNBOOK.md turns it\n'
printf '                                 on -- after the env file is filled in\n'
printf '                                 and the first deploy has been watched\n'
printf '                                 by hand.\n'
printf '   careeros-stg.service          installed, NOT started (no release yet).\n'
printf '   careeros-prod.service         installed, NOT enabled, NOT started.\n'
printf '   careeros-deploy-prod.timer    installed, NOT enabled, NOT started.\n'
printf '   careeros-deploy@.service      installed; the two timers call it.\n'
printf '\n   Staging, in order (deploy/RUNBOOK.md, steps 5-7). Editing an env\n'
printf '   file later needs systemctl restart careeros-stg to take effect:\n'
printf '     sudoedit /etc/careeros/stg.env\n'
printf '     systemctl start careeros-deploy@stg\n'
printf '     journalctl -u careeros-deploy@stg -n 50 --no-pager\n'
printf '     systemctl enable --now careeros-stg\n'
printf '     curl -s http://127.0.0.1:8002/api/health      # {"ok":true}\n'
printf '     systemctl enable --now careeros-deploy-stg.timer\n'
printf '\n   Production, once prod.env is filled in and a v* tag exists.\n'
printf '   In this order: enable (so it survives a reboot) WITHOUT --now,\n'
printf '   because a service with no release yet would only fail-loop; the\n'
printf '   deploy is what starts it; the timer goes on last.\n'
printf '     systemctl enable careeros-prod.service\n'
printf '     /srv/careeros/deploy.sh prod\n'
printf '     systemctl enable --now careeros-deploy-prod.timer\n'
printf '\n   The whole sequence, with expected output at every step:\n'
printf '   deploy/RUNBOOK.md\n'
printf '\n'
