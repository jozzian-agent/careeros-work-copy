---
type: Routine
title: "Push a staged export to production by hand"
description: "push_to_prod.sh: stage, verify, upload one generation to the VPS incoming directory; host-key pinning, permissions, failure recovery."
timestamp: 2026-11-04
---

# Push a staged export to production by hand

`deploy/push_to_prod.sh` (owner decision 2026-11-04: classified jobs onto
production, first pushes started by hand; automation later). The LAN-side
half of a three-part path:

1. **Export** (merged): `scripts/export_jobs_for_prod.py` stages the
   ownerless slice of one night's pool + classification into
   `data/prod-export/<DATE>/` — see [import-pool.md](import-pool.md),
   "The export half".
2. **Upload** (this doc): `deploy/push_to_prod.sh DATE` verifies and
   rsyncs that directory into `/srv/careeros/prod/incoming/<generation>/`
   on the VPS over the dedicated write-confined push key.
3. **Import on the VPS** (separate PR, pending): consumes the uploaded
   generation against the real prod vault. Until it ships, an uploaded
   generation just sits in `incoming/` — with one caveat below.

**Caveat until the import step exists:** `deploy/promote_incoming.sh` run
without arguments picks the **newest COMPLETE generation** in `incoming/`
and deletes it after a move if validation fails (its header: "A
generation that fails validation after the move is deleted"). An export
generation is NOT a pipeline generation — it carries `pool.yaml` /
`classification.yaml` / `MANIFEST`, not the mandatory
`golden_set_pool_<day>.yaml` layout — so it would fail validation and be
destroyed. Until the VPS-side import ships: do not run
`promote_incoming.sh` (bare or named) while an export generation sits in
`incoming/`.

## What the owner runs

From the Mac (the staged export, the push key and the pinned host key all
live on the LAN host, so the script runs there):

```bash
ssh root@192.168.1.203 '/root/work/careeros-dashboard/deploy/push_to_prod.sh 2026-11-03 --dry-run'
ssh root@192.168.1.203 '/root/work/careeros-dashboard/deploy/push_to_prod.sh 2026-11-03'
```

Dry run first, always: it does everything locally (find-or-rerun export,
checksum verify) plus `rsync --dry-run` against the real target, prints
file names, sizes and the generation name, and writes nothing remotely.

The host is never hard-coded. Set it once, either way:

```bash
# on the LAN host, one-line file the script reads:
echo 'app.career-os.ch' | sudo tee /etc/careeros/push-host
# or per invocation:
SYNC_HOST=app.career-os.ch deploy/push_to_prod.sh 2026-11-03
```

If the staged export for DATE is missing, the script re-runs the export
step — which needs `CAREEROS_VAULT` pointed at the vault to check
ownership against (read-only). It never guesses a vault path.

## Generation naming and the COMPLETE marker

Same convention as `deploy/sync_vault_to_prod.sh`: the generation is
`<DATE>T<HHMMSS>Z` (UTC clock at push time, day from the argument, so a
push after midnight still files under the right day), and `COMPLETE` is a
**separate, last transfer** — rsync gives no ordering inside one run, so a
marker that travelled with the payload could land before the data it
vouches for. A generation without COMPLETE is invisible to
`deploy/promote_incoming.sh`, which is exactly the half-finished state.

The script **never deletes anything remote** (no `--delete` on any
transfer, tested) and **never overwrites a generation**: the pre-flight
dry run requires every remote item to be a pure creation (`+++++++++`);
any update or delete line aborts the push before a byte moves.

Upload modes are `D770,F640` with `--no-owner --no-group` — see
"Permissions" for why they differ from the vault sync's `D750,F640`.

## Host-key pinning (owner does the comparison)

The script pins with `StrictHostKeyChecking=yes` against a dedicated file,
`/root/.ssh/careeros-push/known_hosts` (never the shared `~/.ssh/known_hosts`,
never `accept-new`, never `ssh-keygen -R`). To populate it:

```bash
# (a) on the VPS: print the real host key fingerprint
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub

# (b) on the LAN host: print what this host sees for the name it will connect to
ssh-keyscan -t ed25519 app.career-os.ch | ssh-keygen -lf -

# (c) COMPARE the two fingerprints yourself. Only if they match, pin:
mkdir -p /root/.ssh/careeros-push && chmod 700 /root/.ssh/careeros-push
ssh-keyscan -t ed25519 app.career-os.ch >> /root/.ssh/careeros-push/known_hosts
chmod 600 /root/.ssh/careeros-push/known_hosts
```

State on 2026-11-04 (LAN host): `app.career-os.ch` resolves to
179.237.122.209 (IPv4; AAAA also present), the served ed25519 host key is
`SHA256:43TqkmQcuOpxAq2/aXIKEByadu58TY5rgNJ6efeS/jo`, and the existing
shared `known_hosts` entry **matches** it — `ssh -v` reports "known and
matches", and authentication with the push key succeeds. The dedicated
file still wants populating via (a)–(c) so the push path does not share
fate with the shared file.

## Permissions on the VPS (owner runs these once; the agent never does)

The uploaded generation must be readable **and movable** by `careeros-prod`
without root, because the VPS-side import/promotion runs as the prod
account. With files arriving as `careeros-push:careeros-push`, `D770/F640`:

```bash
# on the VPS, as root:
usermod -aG careeros-push careeros-prod        # prod may read the group's files
chmod 2775 /srv/careeros/prod/incoming         # group-writable + setgid:
                                               # - mv OUT of incoming needs write on incoming/
                                               # - setgid keeps new dirs in the careeros-push group
chgrp careeros-push /srv/careeros/prod/incoming  # (already true if owned by careeros-push)
```

Why this shape, checked against the repo:

- `deploy/promote_incoming.sh` moves `$DEPLOY_INCOMING/$GEN` to
  `$DEPLOY_ROOT/generations/` and then chmods 750/640 (+ chown only when
  run as root) — so promotion as root works regardless; the group setup
  above is what lets the **non-root** import path read and move.
- `mv`/`rm` of a directory inside `incoming/` requires write permission on
  `incoming/` itself — mode 755 owner-only would force root for every
  promotion; 2775 with prod in the group avoids that.
- The push key's `authorized_keys` line is `restrict,command="/usr/bin/rrsync
  -wo /srv/careeros/prod/incoming"` (owner-confirmed 2026-11-04): the key
  can write under `incoming/` and nothing else — the same confinement
  pattern as `deploy/sync_vault_to_prod.sh`'s header ("THE SSH SIDE") and
  RUNBOOK "The off-VPS copy".

Trade-off, stated honestly: group membership lets `careeros-prod` read
everything the `careeros-push` group can — which is only `incoming/`
contents (pipeline exports, no owner data by construction: the export
excludes everything already in a vault and never carries `owner_id`).

## Failed or half-finished uploads

| Symptom | State on the VPS | What to do |
| --- | --- | --- |
| Script aborts before/at the pre-flight dry run | nothing created | fix the cause (checksum mismatch, target not empty, host key), re-run |
| Payload rsync fails mid-transfer | `incoming/<GEN>/` exists, **no COMPLETE** | harmless: promotion ignores it. Delete it as root (`rm -rf /srv/careeros/prod/incoming/<GEN>`), then re-run — a new generation name is minted |
| COMPLETE transfer fails after payload | same as above, script says so | same: remove, re-run |
| Generation name already taken (pre-flight refuses) | an older push left debris | inspect `ls /srv/careeros/prod/incoming/`, remove the debris as root, re-run |
| Uploaded but import goes wrong later | generation is in `generations/` | the import step's own rollback (prod vault backup restore) applies; the uploaded bytes are immutable inputs, not the problem surface |

Nothing the script does is destructive remotely; the only cleanup is a
root `rm -rf` of one incoming generation directory, which by construction
holds only what a push created.

## Security invariants (tested in `tests/test_push_to_prod.py`)

- No rsync invocation ever carries `--delete` or `--max-delete`.
- COMPLETE is the last transfer; a payload failure means no marker.
- A pre-flight dry-run failure is a hard abort, never read as "empty target".
- Checksum mismatch aborts before any network call.
- Missing/loose key (not 0600, dir not 0700) or missing pinned known_hosts
  abort before any network call.
- Receipts: one line per successful push appended to
  `data/prod-export/push-receipts.log` (local only, no secrets).
