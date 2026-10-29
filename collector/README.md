# Waiting-list collector (CAREER-99 PR B)

Small separate service, **not part of the app**: own system user, own
data directory, stdlib-only Python (system `python3`, no venv, no pip
install on the VPS). It accepts `POST /waitlist` from the landing page
and stores **only email address and UTC timestamp** — nothing else, no
third party involved.

- Port: **8003** on 127.0.0.1 (8001 = app prod, 8002 = app staging).
  Only Caddy talks to it; see the `career-os.ch` block in
  `deploy/Caddyfile`.
- Data: `/srv/careeros/waitlist/data/waitlist.sqlite3`, SQLite, one
  table `waitlist(email TEXT PRIMARY KEY, added_at TEXT)`.
  `PRAGMA secure_delete=ON` (persisted in the DB header): purged or
  deleted addresses are zero-overwritten in the file, not just removed
  from the index. `journal_mode=DELETE`, so there is never a WAL/SHM
  side file that could retain data.
- Privacy: file 0600 in a 0700 directory, owned by `careeros-waitlist`
  (re-asserted on every start). The app users (`careeros-prod`,
  `careeros-stg`) and Caddy cannot read it. Logs contain counts and
  outcome classes only — never an email address, never a request body.
- Honeypot: the landing form sends a hidden `website` field. If it is
  filled, nothing is stored and the response is byte-identical to a
  real success.
- Rate limit: 3 submissions per hour per client IP, sliding window, in
  memory (resets on service restart; that is deliberate — nuisance
  filter, not a security boundary). Over the limit → HTTP 429.
  Client IP = last `X-Forwarded-For` entry; Caddy overwrites the header
  with the real peer (`header_up X-Forwarded-For {remote_host}`), so a
  client cannot pick its own bucket by sending a fake header.

## Install (owner runs these on the VPS, `ubuntu@ov-5e1fbd`)

All commands below assume the PR is merged and the release containing
`collector/` is deployed to `/srv/careeros/app/current` (prod
promote). Run as root (`sudo -i`).

1. **System user** (once):

   ```bash
   sudo useradd --system --shell /usr/sbin/nologin \
        --home-dir /srv/careeros/waitlist --no-create-home careeros-waitlist
   ```

2. **Data directory** (once):

   ```bash
   sudo mkdir -p /srv/careeros/waitlist/data
   sudo chown -R careeros-waitlist:careeros-waitlist /srv/careeros/waitlist
   sudo chmod 700 /srv/careeros/waitlist /srv/careeros/waitlist/data
   ```

3. **systemd units** (after the release is deployed):

   ```bash
   sudo cp /srv/careeros/app/current/deploy/systemd/careeros-waitlist.service \
           /srv/careeros/app/current/deploy/systemd/careeros-waitlist-purge.service \
           /srv/careeros/app/current/deploy/systemd/careeros-waitlist-purge.timer \
           /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now careeros-waitlist.service
   sudo systemctl enable --now careeros-waitlist-purge.timer
   ```

4. **Caddy** (after the landing files are rsync'd to
   `/srv/careeros/landing`): add the `www.career-os.ch` and
   `career-os.ch` blocks from `deploy/Caddyfile` to
   `/etc/caddy/Caddyfile` (`sudoedit`), then:

   ```bash
   sudo caddy validate --config /etc/caddy/Caddyfile
   sudo systemctl reload caddy
   ```

## Smoke check (after install)

```bash
curl -s http://127.0.0.1:8003/healthz        # → {"ok": true}
curl -s -X POST http://127.0.0.1:8003/waitlist \
     -H 'Content-Type: application/json' \
     -d '{"email":"smoke-test@example.invalid","website":""}'   # → {"ok": true}
```

Then delete the smoke address (next section) so the store stays clean.

## Operator commands

**Delete one address on request** (the address is read from stdin, so
it lands in no shell history and no process list; nothing is echoed
back):

```bash
sudo -u careeros-waitlist python3 \
     /srv/careeros/app/current/collector/waitlist_collector.py delete \
     --db /srv/careeros/waitlist/data/waitlist.sqlite3
# then type the address and press Enter, then Ctrl-D on a new line
```

**Run the purge by hand** (the timer does this daily at 03:30):

```bash
sudo systemctl start careeros-waitlist-purge.service
journalctl -u careeros-waitlist-purge -n 5    # prints counts only
```

**Look at the store** (counts only — do not `cat` the file into a
terminal you might paste from):

```bash
sudo -u careeros-waitlist python3 -c \
  'import sqlite3; print(sqlite3.connect("/srv/careeros/waitlist/data/waitlist.sqlite3").execute("SELECT COUNT(*) FROM waitlist").fetchone()[0])'
```

## Retention promise

The landing page says: kept for **at most 12 months**, then deleted
permanently. `careeros-waitlist-purge.timer` fires daily at 03:30 and
deletes every row whose `added_at` is older than 12 months (365 days).
With `secure_delete=ON` the bytes are gone from the file immediately;
boundary behaviour is covered by `tests/test_waitlist_collector.py`.

## Backups

`/srv/careeros/waitlist` is **outside every backup path this repo
controls**: `deploy/deploy.sh` archives only `/srv/careeros/vault`
(prod), nothing touches the waitlist directory. The VPS provider takes
**no disk snapshots** (owner confirmed 2026-10-29; recovery is a server
reset), so `secure_delete` deletion is deletion everywhere — the
12-month promise holds against every copy of the data.
