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
3. **Import on the VPS**: `deploy/import_prod_generation.sh GEN`
   consumes the uploaded generation against the real prod vault —
   "The import step" below.

**Promotion never touches an export generation.** An export generation is
NOT a pipeline generation — it carries `pool.yaml` / `classification.yaml`
/ `descriptions.yaml` / a `# careeros prod-export manifest` header, not
the mandatory `golden_set_pool_<day>.yaml` layout — and
`promote_incoming.sh` DELETES a generation that fails validation after
its move. Since 2026-11-04 the
promoter reads that manifest header: a bare run skips export generations
with a line naming the skip, and a run that names one is refused before
anything moves (tests: `tests/test_deploy_scripts.py`,
`test_promote_skips_an_export_generation_rather_than_destroying_it` and
friends). So an upload waiting in `incoming/` is safe from promotion; the
import step below is what consumes it.

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

The checksum step is a check by NAME, not by count: every line in the
MANIFEST's checksum section is verified, AND `pool.yaml`,
`classification.yaml` and `descriptions.yaml` must each HAVE a line of
their own. A manifest can carry the right number of lines and still
leave one payload vouched for by nothing — the shape that would send a
`descriptions.yaml` whose bytes no digest covers. Extra lines beyond the
three are fine; the loop verifies them too.

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
dry run requires every remote item to be a pure creation (an itemized
`+++++++++` tail in either direction, `<f` for an upload, `>f` for a
receive, plus rsync's `created directory` info line for a new generation);
any update or delete line aborts the push before a byte moves. Belt and
braces: the payload transfer also carries `--ignore-existing`, so even a
file that appeared between pre-flight and transfer is never overwritten
(the pre-flight itself deliberately does not carry it, so it cannot mask
a taken generation name).

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

## The import step (on the VPS)

`deploy/import_prod_generation.sh <GEN> [--dry-run]
[--allow-low-descriptions]`, root-run like `promote_incoming.sh` (the
backup directory is root-only), dropping to `careeros-prod` via `runuser`
for the import itself — so the process that writes the vault is the
account that owns it, and no release code ever runs as root. Reading the
generation needs exactly the group setup above
and nothing more: files arrive 640/dirs 770 group `careeros-push`, and
`careeros-prod` is a member.

Prerequisite: the release carrying `scripts/import_pool_to_vault.py`
(this code) must be promoted — the script runs the import out of
`/srv/careeros/prod/app/current`, with that release's venv python. The
owner tags and promotes after merge; until then the script refuses with a
line saying so.

What it checks before any vault write: COMPLETE names the generation,
the MANIFEST header says prod-export (a pipeline generation is
`promote_incoming.sh`'s business, not this one's), `sha256sum -c` over
every manifest line, that a `descriptions.yaml` present in the
generation HAS a manifest line of its own (`sha256sum -c` verifies the
lines a manifest has, so an unlisted payload would otherwise pass it
untouched; the refusal is the same posture as the symlink one and
happens before the importer is invoked), the data lock (a backup or
promotion cannot interleave), and — on an apply only — a `vault-*.tar.gz` in
`/srv/careeros/prod/backups/` younger than 60 minutes. A refusal prints
the exact `tar` command that makes the backup. A dry run needs no backup:
rehearsing must not require insuring.

The import itself is the EXISTING `scripts/import_pool_to_vault.py`
(unchanged behaviour; its rules and their tests live in
[import-pool.md](import-pool.md) and `tests/test_pool_import.py`):
create-only, ownerless `in_pipeline: false` records, skips anything the
vault already holds by url/source_id, never touches a record with an
owner. Jobs arrive WITH their classification — the coded `values` block
including the family top-3 (`ranked` inside the `occupation_family`
record) and salary — because `coded_half` validates and stores the
classification row's `values` verbatim (`vault.validate_value_records`).

The posting text arrives too, as data: the generation carries
`descriptions.yaml` (pool `key` → text, resolved on the LAN host where
the frozen ATS snapshots live — the VPS has none and never will), and
this script passes it to the import with `--descriptions`. The report
then prints a `description coverage:` line over the postings to import.
Below 95% a dry run warns loudly and an apply REFUSES, naming
`--allow-low-descriptions` as the override; pass that flag to this
script and it reaches the import. A generation exported before
`descriptions.yaml` existed carries none, is still importable, and takes
the old honest path: every job lands with an empty description, counted
under "descriptions missing". The generation stays in `incoming/` after a
successful import — it is an input and a record of what was imported, not
a release. Removing it is an owner decision.

### The owner's commands, in order

```bash
# 0. (once) the group setup in "Permissions" above, if not already done.

# 1. backup (the apply refuses without one younger than 60 minutes)
sudo tar -czf /srv/careeros/prod/backups/vault-$(date -u +%Y%m%dT%H%M%SZ).tar.gz \
    -C /srv/careeros/prod vault

# 2. rehearse: validates, prints the report with a 5-row sample, writes nothing
sudo /srv/careeros/prod/app/current/deploy/import_prod_generation.sh 2026-11-03T165340Z --dry-run

# 3. apply
sudo /srv/careeros/prod/app/current/deploy/import_prod_generation.sh 2026-11-03T165340Z

# 4. verify: count universe-only jobs (compare with the report's imported: line)
sudo grep -rl '^in_pipeline: false' /srv/careeros/prod/vault/jobs | wc -l
```

Expected at each step: (1) prints nothing and exits 0; (2) ends with
`-- dry run ok: nothing was written` above a report whose `imported:`
line matches the export's posting count minus the duplicates it names,
and whose `description coverage:` line reads 100% or close to it (read
this one before applying: the apply refuses below 95%);
(3) ends with `-- import ok: <GEN> is in /srv/careeros/prod/vault`;
(4) a number equal to the universe jobs the vault held before plus
`imported:`.

### Rollback

The import only creates records, so rollback means removing the vault
state the run added — restore the backup from step 1 (or the newest
`vault-*.tar.gz` from before the damage), following
[deploy/RUNBOOK.md](../../deploy/RUNBOOK.md), "Restoring the vault from a
backup", Route A:

```bash
sudo systemctl stop careeros-prod
cd /srv/careeros/prod/backups
sudo mkdir -p /tmp/restore
sudo tar -xzf vault-<timestamp>.tar.gz -C /tmp/restore
sudo diff -rq /tmp/restore/vault /srv/careeros/prod/vault | head -30   # read this
sudo mv /srv/careeros/prod/vault /srv/careeros/prod/vault.broken
sudo mv /tmp/restore/vault /srv/careeros/prod/vault
sudo chown -R careeros-prod:careeros-prod /srv/careeros/prod/vault
sudo systemctl start careeros-prod
curl -s http://127.0.0.1:8001/api/health                                # {"ok":true}
```

Verify the rollback with the same count as step 4: it should read the
pre-import number again. A restore also rewinds anything testers did
between backup and rollback — that is the trade the 60-minute freshness
gate exists to keep small.

### What testers see after the import

The imported postings are ownerless universe records
(`in_pipeline: false`): they appear on the **All jobs** tab for every
signed-in user, on **nobody's board**, with their coded values (family,
language, municipality, …), salary where the classification carried one,
the posting text the generation's `descriptions.yaml` carried (empty only
for a posting the LAN host had no snapshot for — or for a whole
generation exported before that file existed), and the company each was
linked to (created where the vault had none). Pasting one of their urls
into "Add a job" hits the existing duplicate rule: the universe record is
offered for promotion, never added twice.

Docs checked: import-pool.md (the LAN half it points at), deploy/RUNBOOK.md
("Restoring the vault from a backup" Route A, "The off-VPS copy" table),
docs/index.md, scheduled-jobs.md (no new scheduled job: this step is
owner-run by design).

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
