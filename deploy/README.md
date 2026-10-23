# deploy/ — putting Career OS on the VPS

Everything here runs **on the server**, by you, as root. The agent never
connects to the VPS. Read [the runbook](../docs/runbooks/deploy-runbook.md)
for why the setup is shaped this way; this file is the copy-paste version.

Read **Known gaps** at the bottom before the first production deploy.
Three things in it are decisions only you can make.

## What is in here

| File | What it is |
| --- | --- |
| `setup-vps.sh` | First-time setup of a fresh Ubuntu VM. Idempotent. |
| `deploy.sh` | One deploy of one environment. What the timers run. |
| `systemd/` | The two app services, the deploy template, the two timers. |
| `Caddyfile` | The reverse proxy, exactly as runbook Part 4 specifies. |

Six older scripts also live here — `sync_vault_to_prod.sh`,
`promote_incoming.sh`, `backup_prod.sh`, `pre_deploy_backup.sh`,
`pull_backups_lan.sh`, `smoke.sh`. They belong to the LAN→prod model and
are **not** used by anything in this file. They stay until you retire
them (runbook, "Carry-over note").

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
/root/.ssh/careeros-{prod,stg}_deploy
```

| | Staging | Production |
| --- | --- | --- |
| URL | staging.career-os.ch | app.career-os.ch |
| Deploys | latest `main`, every 2 min | newest `v*` tag, every 5 min |
| Port | 127.0.0.1:8002 | 127.0.0.1:8001 |
| Service | `careeros-stg` | `careeros-prod` |
| Vault | synthetic | live |

---

## 1. Copy the folder over and read it

The script runs as root, so a mistake or a hidden instruction in here is
the main risk in the whole setup. Read it before you run it.

```bash
scp -r deploy ubuntu@<your-vps>:~/deploy
ssh ubuntu@<your-vps>
less ~/deploy/setup-vps.sh
less ~/deploy/deploy.sh
```

Take an Infomaniak snapshot of the VPS first, and make sure your own SSH
public key is already on the box.

## 2. Run the setup

See what it would do, then do it:

```bash
sudo bash ~/deploy/setup-vps.sh --dry-run
sudo bash ~/deploy/setup-vps.sh
```

It installs python3.11, Caddy, ufw and unattended-upgrades; creates the
two `nologin` service users and the directory tree above; creates the two
env files with **placeholders only**; generates the two deploy keys;
records GitHub's host key; installs and enables the units and timers; and
opens 22, 80 and 443.

Safe to re-run. It never overwrites an env file, a deploy key, or a
`Caddyfile` you have edited.

It does **not** start the app services (they have no configuration and no
release yet) and does **not** touch SSH password login (step 7).

## 3. Add the two deploy keys on GitHub

`setup-vps.sh` prints both public keys at the end. On **your own** repo
`github.com/jozzian/careeros` → Settings → Deploy keys → Add deploy key.
Paste each one. Leave **Allow write access OFF** — the servers only pull.

Print them again any time:

```bash
cat /root/.ssh/careeros-prod_deploy.pub
cat /root/.ssh/careeros-stg_deploy.pub
```

The script also prints the fingerprint of the `github.com` host key it
recorded. Compare it against the fingerprints GitHub publishes
("GitHub's SSH key fingerprints" in their docs) before the first deploy.
`deploy.sh` runs with `StrictHostKeyChecking=yes`, so if that key is ever
wrong the deploy stops instead of trusting it.

## 4. Fill in the env files

```bash
sudoedit /etc/careeros/stg.env
sudoedit /etc/careeros/prod.env
```

`sudoedit` keeps every value off the command line and out of shell
history. Each file arrives with commented placeholders; the full list of
variables and what each one does is [`.env.example`](../.env.example).

Minimum for a usable environment:

```text
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=the-model-name
LLM_API_KEY=<the key for THIS environment>
SESSION_COOKIE_SECURE=1
```

One OpenRouter key per environment, each with its own spend limit
(runbook Part 5). Never reuse the production key in staging. Until a key
exists, set `LLM_MOCK=1` (canned replies, no network) or `LLM_DISABLED=1`
(one clean "LLM disabled" error) so the app says what it is doing instead
of failing at the transport.

Check the permissions — root-owned, 0640, group = the service's group:

```bash
ls -l /etc/careeros/
```

## 5. Caddy and the staging password

DNS first: point `staging.career-os.ch` and `app.career-os.ch` at the VPS
(A and AAAA), and confirm 80 and 443 are open in the Infomaniak panel as
well as in ufw. Then:

```bash
caddy hash-password                      # prompts, prints a hash
sudoedit /etc/caddy/Caddyfile            # replace PASTE_HASH_HERE
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

`caddy hash-password` prompts for the password, so it never lands in argv
or in history. The placeholder must stay a placeholder in Git.

If `/etc/caddy/Caddyfile` was not the stock default, `setup-vps.sh` left
it alone and said so; compare it against `deploy/Caddyfile` yourself.

## 6. The first staging deploy

```bash
sudo systemctl start careeros-deploy@stg
journalctl -u careeros-deploy@stg -n 80 --no-pager
```

Every step is one timestamped line. A good first run ends with
`deployed <commit> on port 8002`. Then:

```bash
sudo systemctl start careeros-stg
curl -s http://127.0.0.1:8002/healthz        # {"status":"ok"}
```

Production is the same once a `v*` tag exists in your repo:

```bash
sudo systemctl start careeros-deploy@prod
sudo systemctl start careeros-prod
curl -s http://127.0.0.1:8001/healthz
```

Both services are already `enable`d, so they come back after a reboot.

## 7. Harden SSH — last, and with a second terminal open

```bash
# In terminal A, confirm key login works and KEEP IT OPEN:
ssh -o PasswordAuthentication=no ubuntu@<your-vps> 'echo key login works'

# Only then, in terminal B:
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sshd -t && sudo systemctl reload ssh

# Now prove it again from a THIRD terminal before closing terminal A.
```

`setup-vps.sh` deliberately does not do this. The Infomaniak console is
your fallback if it goes wrong.

---

## How the timers behave

```bash
systemctl list-timers 'careeros-*'
journalctl -u careeros-deploy@stg -n 50 --no-pager
journalctl -u careeros-deploy@prod --since '1 hour ago' --no-pager
```

- Staging checks every 2 minutes, production every 5, measured from the
  **end** of the last run, so a slow deploy is never queued behind itself.
- One run at a time **across both environments**: `careeros-deploy@.service`
  holds `flock` on `/run/careeros/deploy.lock`, and a run that cannot get
  the lock exits quietly rather than waiting.
- A run that finds nothing new ends in a second with `already running …`.
- `Persistent=true`, so a box that was off catches up once.

A production run, in order: vault backup → verify the archive → prune to
14 → build the release → prove it imports → flip `current` → restart →
poll `/healthz` for 60s → `tests/smoke.sh` → prune to 2 releases. A
failure at the health check or the smoke test rolls back on its own.

## Rollback and unpinning

Automatic, after a failed deploy: `current` goes back to `previous`, the
service restarts, `/healthz` is polled again, and the bad ref is written
to `failed.ref` so the timer does not redeploy it every few minutes. A
newer commit or tag deploys normally over it.

By hand, and it **stays** rolled back:

```bash
sudo /srv/careeros/deploy.sh prod --rollback
```

That flips `current` back, restarts, and writes
`/srv/careeros/prod/app/rollback.pin`. **While that file exists the timer
deploys nothing** — it logs that it is skipping, so `journalctl` shows
why nothing is happening.

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

## Where the logs are

| What | Command |
| --- | --- |
| A deploy run | `journalctl -u careeros-deploy@prod -n 100 --no-pager` |
| The app | `journalctl -u careeros-prod -f` |
| Caddy, TLS | `journalctl -u caddy -n 50 --no-pager` |
| Timer schedule | `systemctl list-timers 'careeros-*'` |
| Vault backups | `ls -lh /srv/careeros/prod/backups/` |
| Which release is live | `readlink /srv/careeros/prod/app/current` |

Nothing writes a log file: it all goes to the journal, so it rotates
itself and `journalctl -u` is the one place to look.

## The smoke tester account

`deploy.sh` runs `tests/smoke.sh` against the local port after each
deploy, and a failure rolls the deploy back. It signs in as a **dedicated
tester**, never your account — a smoke test must not be able to see or
change your board.

Until the account exists the smoke test exits 2 and the deploy logs
`smoke test skipped: no credentials`, which is a loud skip and not a
failure, so the first deploy of an environment is not rolled back for it.

Create it with the password generated into a root-owned file and never
typed. The three commands are in the header of
[`smoke.sh`](smoke.sh) — the short version:

```bash
sudo install -m 600 -o root -g root /dev/null /etc/careeros/smoke-password
sudo sh -c 'openssl rand -base64 24 >/etc/careeros/smoke-password'
# then the python block from deploy/smoke.sh's header, which READS that
# file -- the `users create --password` CLI puts it in argv, so do not
# use it.
sudoedit /etc/careeros/prod.env    # SMOKE_EMAIL, SMOKE_PASSWORD
```

Run it by hand any time:

```bash
sudo SMOKE_ENV_FILE=/etc/careeros/prod.env \
  /srv/careeros/prod/app/current/tests/smoke.sh http://127.0.0.1:8001
```

---

## Known gaps

Three things the toolchain cannot settle on its own. None of them is a
bug in these scripts; each is a decision.

### 1. The React front end is not built, so most pages 404

`deploy.sh` installs `requirements.txt` into a venv. It does **not** run
`npm ci && npm run build`, and `setup-vps.sh` does not install Node.

Consequence: a release carries no `frontend/dist`, so `CAREEROS_REACT_UI`
has nothing to serve and the React-only routes — `/`, `/companies`,
`/experiences`, `/taxonomy`, `/notes`, and every detail page — answer
404. What works is `/jobs` in its Jinja rendering plus the whole JSON
API. `tests/smoke.sh` deliberately asserts only routes that exist either
way, so it stays honest about this rather than hiding it.

Also note `frontend/package.json` pins `vite ^8`, which needs Node 20+;
Ubuntu 24.04 ships Node 18, so installing Node means adding a NodeSource
repo on the VPS.

Three ways out, your call:

- Build on the VPS: add Node 20+ to `setup-vps.sh` and an `npm ci && npm
  run build` step to `deploy.sh`. Most convenient, biggest new surface
  (an npm install on the production host).
- Build on your Mac and `scp frontend/dist` into the release, then set
  `CAREEROS_REACT_UI=1`. No new surface, one manual step per release.
- Commit the build output. Simplest for the server, noisiest in Git.

Until one of them is chosen, leave `CAREEROS_REACT_UI` commented out in
both env files so the app serves the Jinja rendering instead of a blank
page.

### 2. The capability submodule may not be fetchable with a deploy key

`vendor/capa-repo` is a submodule of `jozzian/capa-repo`, recorded with
an **HTTPS** URL, and `careeros/server.py` imports `org_intake` from it at
module level — so a release that cannot fetch it cannot start.
`deploy.sh` runs `git submodule update --init --recursive` and fails the
deploy with a clear message if that does not work.

It works as-is only if `jozzian/capa-repo` is **public**. If it is
private, an environment deploy key will not help: GitHub allows a given
key to be a deploy key on exactly one repository, so the
`careeros-prod` key cannot also authorise `capa-repo`. Your options are
to make `capa-repo` public, to use a machine user with read access to
both, or to vendor the capability into the app repo. Decide this before
the first deploy — it is the one gap that stops a deploy outright.

### 3. The app runs on Flask's built-in server

The systemd units start `python -m careeros.server`, which is what
`careeros/server.py`'s `main()` does and what `README.md` documents:
Flask's own `app.run()`. There is no ASGI entry point in the codebase and
no `uvicorn` or `gunicorn` in `requirements.txt`, so the units start what
exists. Both processes bind 127.0.0.1 and Caddy is in front, which covers
TLS and the public surface, but Flask's development server is
single-threaded-by-default and is not meant for sustained traffic.

For one owner and a tester this is very likely fine. Before real traffic,
adding `gunicorn` to `requirements.txt` and changing one `ExecStart` line
is the whole change.

## Open questions

- Should the six carry-over scripts be retired now that `deploy.sh` takes
  its own pre-deploy vault backup? (Runbook, "Carry-over note".)
- `failed.ref` stops a bad ref being retried, but nothing tells you it
  was written. Is a journal line enough, or should a failed deploy reach
  you the way the nightly pipeline's alerts do?
- No rehearsal VM was used (owner decision, 2026-10-23), so nothing here
  has run against real systemd, real Caddy or a real GitHub deploy key.
  See `tmp-deploy-toolchain-summary.md` for exactly what was and was not
  verified.
