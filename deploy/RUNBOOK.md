# deploy/RUNBOOK.md — putting Career OS on the VPS, step by step

This is written for someone who has never deployed anything. Every step
says **where** it runs, gives the **exact command**, says **what success
looks like**, and says **what to paste back** if it does not.

| Tag | Where you are |
| --- | --- |
| **[Mac]** | your own computer, in your clone of the repository |
| **[VPS]** | logged into the server over SSH (`ssh ubuntu@app.career-os.ch`) |
| **[GitHub]** | github.com in a browser |

Read **Known gaps** at the end before the first production deploy. Two of
the things in it are decisions only you can make.

Nothing in here needs the agent, and the agent never connects to the
server. Every command below is yours.

---

## What this box is

Checked on the machine itself, 2026-10-23:

- Ubuntu 26.04.1 LTS, amd64. System `python3` is **3.14.4**. There is no
  version-suffixed interpreter on the box at all — `python3` is it, and
  every release venv is built with it.
- 2 vCPU, 1.9 GB RAM, 37.6 GB disk, one disk, **no swap** when it
  arrived. `setup-vps.sh` adds a 2 GB swap file.
- Login is the `ubuntu` account with your SSH key. Password login is
  already off. **Nothing in `deploy/` touches SSH** — not `sshd_config`,
  not `authorized_keys`, not the service. That stays yours, by hand.
- `app.career-os.ch` and `staging.career-os.ch` already point here (A and
  AAAA). No DNS work.
- **Staging and production run on this one box**, side by side, behind
  one Caddy.

To check that your account can become root without a prompt:

```bash
sudo -n true && echo 'sudo needs no password'
```

Use `sudo -n true`, never `sudo -v`: on this box `sudo -v` prompts for a
password even though real commands do not, so it answers a different
question and looks like a failure when nothing is wrong.

## The layout it builds

```
/srv/careeros/
  deploy.sh                     one copy, run for both environments
  prod/
    app/
      repo.git                  bare mirror; the only thing that fetches
      releases/<tag>/           a clean checkout + its own .venv
      current -> releases/...   what the service runs
      previous -> releases/...  what a rollback goes back to
      rollback.pin              present = the timer deploys nothing
      failed.ref                a ref that failed health; never retried
    vault/                      mode 700, owned by careeros-prod
    backups/vault-<ts>.tar.gz   pre-deploy archives, newest 14
  stg/                          the same, minus backups/
/etc/careeros/{prod,stg}.env    root:careeros-<env>, mode 0640
/root/.ssh/careeros-{prod,stg}_deploy      root-only, one per environment
/swapfile                       2 GB
```

| | Staging | Production |
| --- | --- | --- |
| URL | staging.career-os.ch | app.career-os.ch |
| Deploys | latest `main`, every 2 min | newest `v*` tag, every 5 min |
| Port | 127.0.0.1:8002 | 127.0.0.1:8001 |
| Service | `careeros-stg` | `careeros-prod` |
| Vault | synthetic | live |
| On after setup | everything **off** | everything **off** |

---

# First session, in order

Seven steps. Do them in this order; each one checks the last.

## 1. [Mac] Get `deploy/` onto the VPS

Either way works. The clone is better if you will re-run setup after a
repository change; `scp` is better if you only want these files there.

```bash
# Option A, a clone on the VPS (needs the repo readable from there, so
# normally: clone on the Mac, then option B)
ssh ubuntu@app.career-os.ch 'git clone https://github.com/jozzian/careeros.git ~/careeros'

# Option B, copy the folder from your clone -- deploy/ AND
# requirements.txt next to it, because setup-vps.sh's python-3.14
# dependency check pip-installs the requirements.txt it finds beside
# deploy/ and skips itself (saying so) when there is none:
scp -r deploy ubuntu@app.career-os.ch:~/deploy
scp requirements.txt ubuntu@app.career-os.ch:~/requirements.txt
```

**Expected:** `scp` prints one line per file and exits silently, and
afterwards `ssh ubuntu@app.career-os.ch 'ls ~/deploy/setup-vps.sh ~/requirements.txt'`
prints both paths.

**Then read the scripts before running them.** They run as root, which
makes a mistake or a hidden instruction in them the single biggest risk in
this whole setup:

```bash
ssh ubuntu@app.career-os.ch
less ~/deploy/setup-vps.sh
less ~/deploy/deploy.sh
```

> **A note on option B:** `setup-vps.sh` also pip-installs
> `requirements.txt` into a throwaway venv to prove every dependency
> builds on python 3.14. Copying only `deploy/` leaves no
> `requirements.txt` beside it, so that check is skipped and says so.
> Nothing breaks; you just find out at the first deploy instead.

## 2. [VPS] `--check`: read the plan, change nothing

```bash
sudo ~/deploy/setup-vps.sh --check
```

**Expected:** a run of `==` sections, every changing line prefixed
`would run:`, ending with

```text
 That was --check. NOTHING above was changed. Re-run without --check.
```

and a `WHAT IS RUNNING NOW, EXACTLY` block. The first section must say
`python3 is Python 3.14.4`.

> ### STOP AND CHECK
> - Does the Python line say 3.14 or newer? If it says anything older,
>   **stop** — every release venv is built with that interpreter.
> - Read every `would run:` line. Anything you do not recognise is a
>   reason to stop and ask, not to continue.
> - It changes nothing, so you can run it as often as you like.

**If it fails:** paste back the whole output, including the `!!` line.

## 3. [VPS] The real run

```bash
sudo ~/deploy/setup-vps.sh
```

It installs python3-venv/pip, Caddy, ufw and unattended-upgrades; makes a
2 GB swap file; creates the two `nologin` service users and the directory
tree; creates the two env files with **placeholders only**; proves
`requirements.txt` installs under python 3.14; generates the two deploy
keys; records GitHub's host key; installs the units and timers; and opens
22, 80 and 443. It enables and starts **nothing** — the staging flow in
steps 5–7 turns things on in order, after the env file exists.

**Expected:** the same sections, now with `creating`/`installing` lines
instead of `would run:`, and at the end:

```text
   careeros-deploy-stg.timer     installed, NOT enabled, NOT started. ...
   careeros-stg.service          installed, NOT started (no release yet).
   careeros-prod.service         installed, NOT enabled, NOT started.
   careeros-deploy-prod.timer    installed, NOT enabled, NOT started.
```

Safe to re-run: it never overwrites an env file, a deploy key, a
`Caddyfile` you have edited, or an existing swap file, and a second run
reports `already done:` for everything.

**If it fails:** it stops at the first failure with a `!!` line. Paste
back that line and the last section above it, plus:

```bash
sudo systemctl status caddy --no-pager -l
```

## 4. [VPS → GitHub] The two deploy keys

The end of step 3 printed two public keys. Print them again any time:

```bash
sudo cat /root/.ssh/careeros-prod_deploy.pub
sudo cat /root/.ssh/careeros-stg_deploy.pub
```

On **GitHub**, in a browser:

1. Go to `github.com/jozzian/careeros` — your own repository, not the
   agent's work copy.
2. Click **Settings** (the tab on the repository, not your profile).
3. In the left menu, under *Security*, click **Deploy keys**.
4. Click **Add deploy key**.
5. *Title*: `careeros-prod`. *Key*: paste the whole `prod` line.
6. Leave **Allow write access** UNCHECKED.
7. Click **Add key**. Repeat for `careeros-stg`.

**Expected:** two keys listed, each showing "Read-only".

> ### STOP AND CHECK
> - Are both keys **read-only** on GitHub? A deploy key with write access
>   turns a compromise of the server into a compromise of your source.
> - Compare the `github.com` host-key fingerprints the script printed
>   against the ones GitHub publishes (docs.github.com → "GitHub's SSH
>   key fingerprints"). `deploy.sh` runs with `StrictHostKeyChecking=yes`,
>   so a wrong key stops a deploy instead of trusting it.

## 5. [VPS] Fill in the staging env file

```bash
sudoedit /etc/careeros/stg.env
```

`sudoedit` keeps every value off the command line and out of shell
history. The file arrives with commented placeholders; the full list of
variables, what each does and **which file reads it** is
[`.env.example`](../.env.example).

For staging, the useful minimum is the LLM:

```text
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=the-model-name
LLM_API_KEY=<the staging key>
```

One key per environment, each with its own spend limit, and never the
production key here. **You can also leave all three out**: the app runs,
and an extraction settles as `not_configured` — a visible failure with
nothing invented (Known gaps, 2).

There is no host or port line. The app takes both as command-line flags,
which `careeros-stg.service` passes; a `CAREEROS_PORT=` line here would
be read by nothing.

> **Editing an env file later — any of them, either environment — needs a
> service restart to take effect:** `sudo systemctl restart careeros-stg`
> (or `careeros-prod`). systemd reads `EnvironmentFile` only when the
> service starts, so a saved edit changes nothing on its own.

**Expected:** afterwards

```bash
ls -l /etc/careeros/
```

shows `-rw-r----- 1 root careeros-stg` for `stg.env`.

## 6. [VPS] The first staging deploy, and the click test

Nothing is running yet — this deploy is by hand, and you watch it:

```bash
sudo systemctl start careeros-deploy@stg
journalctl -u careeros-deploy@stg -n 80 --no-pager
```

**Expected:** every step is one timestamped line, ending with

```text
... deploy[stg]: deployed <commit> on port 8002
```

The first run clones, builds a venv and installs requirements, so it
takes a few minutes. Then start the service — `enable --now`, so it also
comes back after a reboot — and ask the app itself:

```bash
sudo systemctl enable --now careeros-stg
curl -s http://127.0.0.1:8002/api/health
```

**Expected:** `Created symlink .../multi-user.target.wants/careeros-stg.service ...`
followed by `{"ok":true}`

**If the deploy failed:** paste back

```bash
journalctl -u careeros-deploy@stg -n 200 --no-pager
journalctl -u careeros-stg -n 100 --no-pager
```

The most common first failure is the deploy key: `could not clone ... (is
the deploy key added on GitHub, read-only?)` means step 4 is incomplete.

### An account to sign in with

There is no signup page: every route is behind the login gate, so the
staging vault needs one account before you can click anything. The vault
is owned by `careeros-stg`, so create it as that user and the files land
with the right owner:

```bash
sudo -u careeros-stg env CAREEROS_VAULT=/srv/careeros/stg/vault \
  /srv/careeros/stg/app/current/.venv/bin/python -m careeros.users \
  create --email you@example.com --name 'Your Name' --role admin \
  --password 'the password you chose'
```

**Expected:** one line naming the id, the role and the address.

That password is an argument, so it is visible in `ps` while the command
runs and it lands in your shell history — acceptable for your own account
on a box only you log into, and `history -d` afterwards is cheap. For the
**tester** account, which a script signs in as repeatedly, use the
generate-into-a-file route instead: see **The tester account**.

### The staging password, then the browser

Staging is reachable by hostname, so Caddy asks for a password in front
of it. Set it on the server — the password never reaches a command line,
this repository, or a log:

```bash
caddy hash-password                                  # prompts, prints a hash
sudoedit /etc/caddy/Caddyfile                        # replace PASTE_HASH_HERE
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

**Expected:** `caddy validate` prints `Valid configuration`, and the
reload is silent. The browser user name is `me`, which is a basic-auth
name in Caddy and not an account in the app.

> ### STOP AND CHECK — the click test
> Open `https://staging.career-os.ch`. The first request to a new
> hostname can take a few seconds while Caddy gets its certificate.
> - The browser asks for a user name and password (`me`, yours).
> - You get the app's own login page behind it.
> - You can sign in and reach `/jobs`.
>
> If the certificate never arrives: `journalctl -u caddy -n 50
> --no-pager` — paste that back. Most often it is DNS or port 80.
>
> Known gap: most pages are React-only and answer 404 until a release
> carries a built front end. `/jobs` and the whole JSON API work either
> way. See Known gaps, 1.

## 7. [VPS] Turn the staging deploy timer on

Only now — the env file exists, a release is deployed and watched, and
the click test passed:

```bash
sudo systemctl enable --now careeros-deploy-stg.timer
systemctl list-timers 'careeros-*'
```

**Expected:** `Created symlink .../timers.target.wants/careeros-deploy-stg.timer ...`
and `careeros-deploy-stg.timer` listed with a next-run time about two
minutes out. From here, every push to `main` lands on staging on its own.

**Staging is now the place a release is proved. Stop here for today if
you like — production needs nothing from you yet.**

---

# Production, the first time

Only when staging has been clicked through and you have a `v*` tag.

## [VPS] 1. Fill in the production env file

```bash
sudoedit /etc/careeros/prod.env
```

Its own LLM key, with its own spend limit. Never the staging key.

## [VPS] 2. Enable the service, without starting it

```bash
sudo systemctl enable careeros-prod.service
```

**Expected:** `Created symlink ...`. Enable, not `enable --now`: there is
no release yet, and a service started without one would only fail-loop.
The deploy is what starts it.

## [GitHub] 3. Publish a tag

Releases → Draft a new release → new tag `v0.1.0` on `main` → Publish.
Production deploys the newest tag matching `v*`, by version order, so
`v0.10.0` is newer than `v0.9.0` whichever was pushed first.

## [VPS] 4. The first production deploy, by hand

```bash
sudo /srv/careeros/deploy.sh prod
```

**Expected,** in this order, one timestamped line each: the vault
archive, the checkout, the venv, `current -> v0.1.0`, the restart,
`/api/health answered 200`, the smoke test, `deployed v0.1.0 on port
8001`.

On a first run the smoke test says `smoke test skipped: no credentials` —
that is a loud skip, not a failure (see **The tester account**).

```bash
curl -s http://127.0.0.1:8001/api/health
```

**Expected:** `{"ok":true}`. Then open `https://app.career-os.ch` and
sign in.

## [VPS] 5. Turn the production timer on

```bash
sudo systemctl enable --now careeros-deploy-prod.timer
systemctl list-timers 'careeros-*'
```

**Expected:** both timers listed with a next-run time. From here, a
published tag is live within about five minutes.

## [VPS] 6. The tester account, so the smoke test stops skipping

Follow **The tester account** below: create it, put `SMOKE_EMAIL` and
`SMOKE_PASSWORD` into `prod.env`, then run the smoke test by hand once:

```bash
sudo SMOKE_ENV_FILE=/etc/careeros/prod.env \
  /srv/careeros/prod/app/current/tests/smoke.sh http://127.0.0.1:8001
```

**Expected:** `-- GET /api/health 200`, `-- login ok, session cookie
stored`, three `GET` lines, `-- smoke ok: ...`, exit 0. From now on every
deploy runs this itself, and a failure rolls the release back.

Do this last on purpose: until it passes by hand, an automatic smoke
failure would roll back a release that is actually fine.

> ### STOP AND CHECK
> - `readlink /srv/careeros/prod/app/current` names the tag you published.
> - `ls -lh /srv/careeros/prod/backups/` holds one archive, from minutes
>   ago.
> - Production answers on its own hostname, over HTTPS.
> - The smoke test passes by hand, or you have decided to leave it
>   skipping for now.

**If it fails:** paste back

```bash
sudo journalctl -u careeros-deploy@prod -n 200 --no-pager
sudo journalctl -u careeros-prod -n 100 --no-pager
```

---

# What a deploy run does

Every run, in order:

1. Refuses unless it is root, names a known environment, and can take the
   deploy lock — one run at a time across both environments.
2. Stops if a rollback is pinned, if the ref is the one `current` already
   points at, or if it is the ref that failed last time.
3. **prod only:** archives the vault to
   `backups/vault-<timestamp>.tar.gz`, reads the archive back, prunes to
   the newest 14. A backup that does not verify ends the run before
   anything is touched.
4. Builds the release: clean checkout into `releases/<ref>`, a fresh venv,
   `requirements.txt`. No second credential and nothing to initialise —
   `vendor/capa-repo` is an ordinary directory in the repository.
5. Proves the release can `import careeros.server` before it may become
   `current`.
6. Flips `current` atomically, restarts the service, polls
   `/api/health` for up to 60 s, then runs `tests/smoke.sh` against the
   local port. Either one failing rolls back on its own.
7. Prunes to the newest 2 releases, never the two the symlinks point at.

It runs no migrations: those run at app startup, so the release that
starts is the one that migrates, and a rollback restarts an older app
against the same vault.

## How the timers behave

```bash
systemctl list-timers 'careeros-*'
journalctl -u careeros-deploy@stg -n 50 --no-pager
journalctl -u careeros-deploy@prod --since '1 hour ago' --no-pager
```

- Staging every 2 minutes, production every 5, measured from the **end**
  of the last run, so a slow deploy is never queued behind itself.
- One run at a time **across both environments**: `careeros-deploy@.service`
  holds `flock` on `/run/careeros/deploy.lock`, and a run that cannot get
  the lock exits quietly rather than waiting.
- A run that finds nothing new ends in a second with `already running …`.
- `Persistent=true`, so a box that was off catches up once.

---

# Rollback

## Automatic, after a failed deploy

`current` goes back to `previous`, the service restarts, `/api/health` is
polled again, and the bad ref is written to `failed.ref` so the timer does
not redeploy it every few minutes. A newer commit or tag deploys normally
over it.

If even the rollback does not answer, the log carries one line saying so
and naming the environment as down:

```text
ALERT careeros-deploy: the ROLLBACK to <ref> did not answer /api/health either -- prod is down and needs a person
```

## By hand, and it stays rolled back

```bash
sudo /srv/careeros/deploy.sh prod --rollback
```

That flips `current` back, restarts, and writes
`/srv/careeros/prod/app/rollback.pin`. **While that file exists the timer
deploys nothing** — it logs that it is skipping, so `journalctl` shows why
nothing is happening.

To resume:

```bash
sudo rm /srv/careeros/prod/app/rollback.pin
sudo systemctl start careeros-deploy@prod      # or wait for the timer
```

To let a ref that failed its health check be retried as-is:

```bash
sudo rm /srv/careeros/prod/app/failed.ref
```

The other way back is to publish a new tag on the last good commit, which
takes the normal path.

## What a failed release leaves behind

- `releases/<ref>/` — the half-built or unhealthy tree, with a
  `.incomplete` marker if the build itself was interrupted. The next run
  rebuilds anything carrying that marker and reuses anything without it.
- `failed.ref` — the ref that failed, so the timer stops retrying it.
- `previous` — unchanged, which is what the rollback used.
- The vault — untouched. Nothing in the deploy path writes a record, and
  the pre-deploy archive was taken before anything else happened.

Pruning never removes the releases `current` and `previous` point at, so a
rolled-back release is still there to look at.

---

# If the server is lost: reset it

Reset the server (host panel reinstall), log in with your SSH key, re-run
setup and deploy; the vault comes back from the backups the LAN pulls (see
**The off-VPS copy**).

---

# Day 2

## Where the logs are

| What | Command |
| --- | --- |
| A deploy run | `journalctl -u careeros-deploy@prod -n 100 --no-pager` |
| The app | `journalctl -u careeros-prod -f` |
| Caddy, TLS | `journalctl -u caddy -n 50 --no-pager` |
| Timer schedule | `systemctl list-timers 'careeros-*'` |
| Vault backups | `ls -lh /srv/careeros/prod/backups/` |
| Which release is live | `readlink /srv/careeros/prod/app/current` |
| Memory and swap | `free -h` and `systemctl status careeros-prod` |

Nothing writes a log file: it all goes to the journal, so it rotates
itself and `journalctl -u` is the one place to look. Staging is the same
with `stg` in place of `prod`.

## The tester account

`deploy.sh` runs `tests/smoke.sh` against the local port after each
deploy, and a failure rolls the deploy back. It signs in as a **dedicated
tester**, never your account — a smoke test must not be able to see or
change your board.

Until that account exists the smoke test exits 2 and the deploy logs
`smoke test skipped: no credentials`, which is a loud skip and not a
failure, so the first deploy of an environment is not rolled back for it.

Create it with the password generated into a root-owned file and never
typed. The commands are in the header of [`smoke.sh`](smoke.sh); the
short version:

```bash
sudo install -m 600 -o root -g root /dev/null /etc/careeros/smoke-password
sudo sh -c 'openssl rand -base64 24 >/etc/careeros/smoke-password'
# then the python block from deploy/smoke.sh's header, which READS that
# file -- the `users create --password` CLI puts it in argv, so do not
# use it.
sudoedit /etc/careeros/prod.env    # SMOKE_EMAIL, SMOKE_PASSWORD
```

Use an address of your own choosing for it; nothing in this repository
has a default, on purpose.

Run it by hand any time:

```bash
sudo SMOKE_ENV_FILE=/etc/careeros/prod.env \
  /srv/careeros/prod/app/current/tests/smoke.sh http://127.0.0.1:8001
```

**Expected:** `-- GET /api/health 200`, `-- login ok`, three `GET` lines,
then `-- smoke ok: ...`.

## The off-VPS copy (backups, pull-from-home)

**Nothing on the VPS connects out.** It holds no credential for your LAN
and no address for it. The direction is always LAN → VPS:

| Where | What runs | What it does |
| --- | --- | --- |
| **[VPS]** | `deploy.sh prod` | a plain `tar.gz` of the vault before every production release, newest 14, in `/srv/careeros/prod/backups/` |
| **[VPS]** | `deploy/backup_prod.sh --full` / `--owner-data` | encrypted archives (`tar` into `zstd` into `age -R`, one stream, no plaintext on disk) in `/var/backups/careeros/<namespace>/`, plus a `.sha256` beside each |
| **[LAN]** | `deploy/pull_backups_lan.sh` | logs in, pulls the archives, verifies each against its manifest, and leaves a `<archive>.pulled` receipt behind |
| **[VPS]** | `backup_prod.sh` again | prunes only archives a receipt confirms are off the box |
| **[LAN]** | `pull_backups_lan.sh --check-stale` | the alarm: non-zero when a recent verified copy is not on the LAN |

The VPS can only create those archives, never open them: the age
recipients file on the box holds a **public** key and the private half is
yours, offline.

### [VPS] Creating the account the LAN logs in as — owner work

Nothing in this repository names this account. Pick a name, and use it
for `$BACKUP_USER` below and for `PULL_USER` on the LAN; both scripts
refuse to run rather than guess one.

```bash
BACKUP_USER=<the name you picked>
sudo useradd --system --create-home --shell /usr/sbin/nologin "$BACKUP_USER"
sudo install -d -m 700 -o "$BACKUP_USER" -g "$BACKUP_USER" \
     "/home/$BACKUP_USER/.ssh"
# The backup directory is made by the first backup run. `mkdir -p` here
# so this step works in either order; the group is what lets the pull
# key read the archives at all (backup_prod.sh keeps them 0750/0640).
sudo mkdir -p /var/backups/careeros
sudo chgrp -R "$BACKUP_USER" /var/backups/careeros
```

**Expected:** `id "$BACKUP_USER"` prints the account, and
`ls -ld /var/backups/careeros` shows that group.

Then two `authorized_keys` lines in `/home/$BACKUP_USER/.ssh/authorized_keys`,
one per key, because a forced command belongs to a key and reading and
writing need different ones:

```text
restrict,command="/usr/bin/rrsync -ro /var/backups/careeros",from="<your LAN address>" ssh-ed25519 AAAA...PULLKEY...
restrict,command="/usr/bin/rrsync -wo /var/backups/careeros/.receipts",from="<your LAN address>" ssh-ed25519 AAAA...RECEIPTKEY...
```

`rrsync -ro` refuses rsync's writing modes, `rrsync -wo` refuses its
reading modes, and both confine every path to their own directory. So one
key can read ciphertext and nothing else, and the other can create
receipt files and nothing else. Neither can decrypt or delete.

Finally, tell the backup script which group the receipts must belong to,
or the LAN's receipt write is refused and count-pruning stays off:

```bash
# in the cron line or the wrapper that runs backup_prod.sh
BACKUP_RECEIPT_GROUP=$BACKUP_USER
```

**Expected** from a LAN pull: `-- N receipt(s) written back to ...` and
`-- pull ok`. **If it fails**, paste back the whole output; it is one
`ALERT careeros-prod-backup-pull:` line naming the reason.

A restore is the only thing that proves a backup. Do one — decryption,
ownership, permissions, app startup — once before go-live and quarterly
after: **Restoring the vault from a backup**, below.

## Restoring the vault from a backup

There are two kinds of archive, and you pick by what you lost:

| Lost | Restore from | Where it lives |
| --- | --- | --- |
| A bad edit, a migration gone wrong, "undo the last hour" | a plain `vault-<timestamp>.tar.gz` (taken by every production deploy, newest 14 kept) | **[VPS]** `/srv/careeros/prod/backups/` |
| The box itself, or an archive you want to verify on your own machine | an encrypted `.tar.zst.age` archive | **[LAN]** where `pull_backups_lan.sh` pulled it |

### Route A — on the VPS, from a deploy-time `tar.gz`

**[VPS]** Stop the app first so the restore is not racing a live server:

```bash
sudo systemctl stop careeros-prod
ls -lht /srv/careeros/prod/backups/ | head
```

**Expected:** the newest `vault-<timestamp>.tar.gz` files, one per production
deploy. Pick the one from before the damage, and unpack it beside the
current vault instead of over it, so you can look before you commit:

```bash
cd /srv/careeros/prod/backups
sudo mkdir -p /tmp/restore
sudo tar -xzf vault-<timestamp>.tar.gz -C /tmp/restore
sudo diff -rq /tmp/restore/vault /srv/careeros/prod/vault | head -30
```

**Expected:** `diff` prints the differences (files only in one side,
differing contents) and exits 1 — that is it doing its job, not a
failure. Read them; they should be exactly the damage you expect to undo.
Then swap:

```bash
sudo mv /srv/careeros/prod/vault /srv/careeros/prod/vault.broken
sudo mv /tmp/restore/vault /srv/careeros/prod/vault
sudo chown -R careeros-prod:careeros-prod /srv/careeros/prod/vault
sudo systemctl start careeros-prod
curl -s http://127.0.0.1:8001/api/health
```

**Expected:** `{"ok":true}`, and the app in the browser shows the restored
records. Keep `vault.broken` until you are sure, then remove it.

**If it fails:** paste back the `diff` output and
`journalctl -u careeros-prod -n 100 --no-pager`.

### Route B — from an encrypted archive (needs your private age key)

The VPS cannot open these — it holds only the public recipients file.
Decryption happens on **[LAN]** (or any machine holding your private key):

```bash
mkdir -p /tmp/restore
age -d -i ~/.config/age/careeros-backup.txt \
    <archive>.tar.zst.age | zstd -d | tar -x -C /tmp/restore
find /tmp/restore -maxdepth 1 | head    # sanity: real files, not garbage
```

**Expected:** `age` and `zstd` exit silently; `/tmp/restore` now *is* the
vault tree (the encrypted archives are tarred from inside the source, so
no `vault/` subdirectory appears — unlike Route A). A wrong key prints
`age: error: no matching identity found` and creates nothing. Verify
before trusting: `sha256sum -c <archive>.tar.zst.age.sha256` prints `OK`.

To get the vault back onto a (possibly freshly reset) VPS, re-run
`setup-vps.sh` and the first deploy, then push the restored tree up as
the `ubuntu` user — the VPS never reaches back to you, but you can always
reach it:

```bash
scp -r /tmp/restore ubuntu@app.career-os.ch:/tmp/restore-vault
ssh ubuntu@app.career-os.ch 'sudo systemctl stop careeros-prod &&
  sudo mv /srv/careeros/prod/vault /srv/careeros/prod/vault.broken &&
  sudo mv /tmp/restore-vault /srv/careeros/prod/vault &&
  sudo chown -R careeros-prod:careeros-prod /srv/careeros/prod/vault &&
  sudo systemctl start careeros-prod &&
  curl -s http://127.0.0.1:8001/api/health'
```

**Expected:** `{"ok":true}`.

> ### STOP AND CHECK
> - Which archive did you restore, and does its timestamp precede the
>   damage? Restoring a post-damage backup undoes nothing and looks like
>   success.
> - After a prod restore: sign in and check one record you know should
>   exist, and one you know should NOT (the thing you were undoing).
> - The restored vault is now the truth. The next deploy takes a fresh
>   pre-deploy archive of it automatically.

## Why the app users hold no key

`careeros-prod` and `careeros-stg` never hold a repository credential.
The deploy keys live in `/root/.ssh/`, root-owned, and the deploy unit
runs as `root`.

- The app users exist to do two things: read their release tree and write
  their vault. That is all `ReadWritePaths=` grants them.
- A repository credential in an app user's home would turn **any**
  compromise of the app process into read access to your source. The app
  is the thing exposed to the internet; it is the last place a key
  belongs.
- `careeros-deploy@.service` runs as root **precisely so** the key never
  lives where the app can reach it. The fetch happens as root, and the
  built release is then `chown`ed to the app user, which cannot read the
  key that fetched it.
- The keys are **read-only on GitHub**, so even the deploy path cannot
  push. A compromise of root on this box reads your source; it does not
  rewrite it.
- One key per environment, with `IdentitiesOnly=yes`, so a staging deploy
  cannot use production's key even by accident.

---

# Known gaps

Four things the toolchain cannot settle on its own. None is a bug in these
scripts; each is a decision or a change in the app.

### 1. The React front end is not built, so most pages 404

`deploy.sh` installs `requirements.txt` into a venv. It does **not** run
`npm ci && npm run build`, and `setup-vps.sh` does not install Node.

A release therefore carries no `frontend/dist`, so `CAREEROS_REACT_UI`
has nothing to serve and the React-only routes — `/`, `/companies`,
`/experiences`, `/taxonomy`, `/notes` and every detail page — answer 404.
What works is `/jobs` in its Jinja rendering plus the whole JSON API.
`tests/smoke.sh` asserts only routes that exist either way, so it stays
honest about this rather than hiding it.

Three ways out, your call: build on the VPS (add Node to `setup-vps.sh`
and a build step to `deploy.sh` — most convenient, biggest new surface);
build on the Mac and copy `frontend/dist` into the release; or commit the
build output. Until one is chosen, leave `CAREEROS_REACT_UI` commented
out in both env files so the app serves the Jinja rendering instead of a
blank page.

*Closed by:* a front-end build PR, whichever of the three you pick.

### 2. An environment with no LLM key settles extractions as `not_configured`

This is the app behaving correctly, recorded here because it is what you
will see on a fresh environment: with `LLM_BASE_URL`/`LLM_MODEL` unset,
an extraction reports `not_configured` and the record keeps its
heuristic reading, attributed to the heuristic. A visible failure, with no
invented fields.

There is no "mock" or "off" switch to set: the app on this release reads
no `LLM_MOCK` and no `LLM_DISABLED`, so putting either in an env file
would change nothing and read like a setting that does.

*Closed by:* a future app PR adding those two switches, if an explicit
off-state is ever worth having. Nothing here waits on it.

### 3. The session cookie is not flagged `Secure`

Both environments are reached only through Caddy over HTTPS, and the
cookie is `HttpOnly` and `SameSite=Lax` already. But the app on this
release reads no `SESSION_COOKIE_SECURE`, so the flag cannot be turned on
from an env file and a `SESSION_COOKIE_SECURE=1` line would be read by
nothing.

Functionally this is fine over HTTPS. It is a hardening gap, not a
breakage: the cookie would also be sent over plain HTTP if anything ever
reached the app that way, and nothing does.

*Closed by:* a future app PR that reads the flag from the environment;
then one line in each env file turns it on.

### 4. The app runs on Flask's built-in server

The units start `python -m careeros.server --host 127.0.0.1 --port
800X`, which is what `careeros/server.py`'s `main()` does: Flask's own
`app.run()`. There is no ASGI entry point in the codebase and no
`gunicorn` in `requirements.txt`, so the units start what exists. Both
processes bind the loopback with Caddy in front, which covers TLS and the
public surface, but Flask's development server is not meant for sustained
traffic.

For one owner and a tester this is very likely fine. Before real traffic,
adding `gunicorn` to `requirements.txt` and changing one `ExecStart` line
is the whole change.

*Closed by:* a WSGI-server PR, when traffic justifies it.

---

## Open questions

- `failed.ref` stops a bad ref being retried, but nothing tells you it was
  written. Is a journal line enough, or should a failed deploy reach you
  the way the nightly pipeline's alerts do?
- The LAN→prod data path (`sync_vault_to_prod.sh`, `promote_incoming.sh`,
  `backup_prod.sh`, `pre_deploy_backup.sh`, `pull_backups_lan.sh`) is
  older than this deploy path and is not used by anything in this file.
  `deploy.sh` takes its own plain vault archive before a production
  release. Which of the five do you want to keep?
- Nothing here has run against real systemd, real Caddy or a real GitHub
  deploy key. Every command above is written from the scripts and the
  verified facts about the box, not from a transcript.
