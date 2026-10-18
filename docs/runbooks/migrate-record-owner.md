---
type: Routine
title: "Give a vault's existing jobs and experiences an owner"
description: "Back up a vault, run the one-time M2 ownership migration against it, verify it and roll it back."
timestamp: 2026-10-18
---

# Give a vault's existing jobs and experiences an owner

Owner decisions D3 and D4 (CAREER-39, milestone M2) split the vault:
every job and every experience belongs to one user and is visible to
nobody else, while companies and the tag vocabulary stay one shared
universe that everybody reads and the admin alone edits.

That ownership is the `owner_id` field on a job and an experience record
(`vault.OWNER_FIELD`). No record written before M2 carries one.
`scripts/migrate_record_owner.py` assigns every one of them to the admin
account, which is the account that existed while those records were
being added.

This is the owner's action. The commands below were proven against
fixture copies of a vault on 2026-10-18
(`tests/test_migrate_record_owner.py` runs the same code); the quoted
output is a fixture run, so the numbers from the real vault will differ.

## What it writes

- Job and experience records only, one YAML file each, and only the ones
  that carry no `owner_id`. No company, tags or search file is touched:
  those are shared by decision, so there is nothing on them to assign.
- Per record: `owner_id`, and nothing else.
- Once, at the vault root: `ids.yaml`, the record-number high-water mark
  per kind. The live vault predates that file, and an id used to be
  `max stored id + 1`, which made the next id a readable fact about
  which records the vault still holds. Seeding the marks from what is
  stored now is what makes the vault monotonic from its next write
  rather than from its next delete. It is not an ownership change, so it
  happens even on a vault where every record already names an owner.
- Nothing twice: the run is idempotent, and a second run reports
  `nothing to change, every job and experience already names its owner`.

## Before running

- The instance is on the commit that carries M2. The app works either
  way around this migration, because the read side carries the same
  rule: `vault.Owner` lets the admin see records that carry no owner, so
  the admin's board is whole before the migration runs and nobody else's
  shows a record they did not add. What the migration buys is stored
  facts instead of an inherited default, which is what makes a second
  admin account safe.
- There is exactly one admin account. With none, the script stops rather
  than guessing who owns somebody's private jobs; with more than one, it
  stops and asks for `--owner USER-00X`.
- The server may keep running. The script takes the same cross-process
  write lock (`vault.WriteLock`) the server takes, and holds it around
  the read, the report and the writes, so no request can interleave.
- Decide the vault path. VAULT below is that path. Pass it explicitly
  rather than relying on a default, so a run can never land on a vault
  nobody named.

## The sequence

Run from the repository root, in the product virtual environment.

```bash
export VAULT=/path/to/the/vault
export BACKUP=~/careeros-vault.before-record-owner-$(date +%Y%m%d)

# 1. Back up the whole vault, to a copy OUTSIDE it, and never over an
#    existing backup (-n). Check the copy before going on. Note: the copy
#    is per-file atomic but not one point in time while the server runs;
#    stop the server first if the vault is being written to.
cp -rn "$VAULT" "$BACKUP"
ls "$VAULT"/jobs | wc -l
ls "$BACKUP"/jobs | wc -l

# 2. Confirm which account the records will go to.
.venv/bin/python -m careeros.users --vault "$VAULT" list

# 3. Dry run. Writes nothing and prints the whole assignment report.
.venv/bin/python scripts/migrate_record_owner.py --vault "$VAULT"

# 4. Read the report. Every line is one record and where it goes. Only
#    then apply. The apply prints the same report before it writes.
.venv/bin/python scripts/migrate_record_owner.py --vault "$VAULT" --apply
```

A dry run on a three-record fixture prints:

```
vault=/tmp/fixture  mode=DRY RUN  owner=USER-001
------------------------------------------------------------------------------
id high-water marks to record in ids.yaml: companies=1, experiences=1, jobs=2
  JOB-001: job with no owner -> USER-001
  JOB-002: job with no owner -> USER-001
  EXP-001: experience with no owner -> USER-001
------------------------------------------------------------------------------
jobs: 2 of 2 gain an owner
experiences: 1 of 1 gain an owner
companies and the tag vocabulary are shared universe and are not touched
DRY RUN: nothing was written. Re-run with --apply to write.
```

The apply repeats that report, then says what it wrote:

```
recorded id high-water marks: companies=1, experiences=1, jobs=2
wrote 3 record(s)
```

A second run says `ids.yaml: already records every id high-water mark`
in place of the first line.

A run that skipped a record says so on stderr and exits non-zero, so a
partly written sweep is never reported as a success.

## Verify

Two checks, each a short script in the product virtual environment with
VAULT still exported.

1. Every private record names an owner, and it is an account that
   exists:

```python
import os
from careeros import users, vault
root = os.environ['VAULT']
known = {user['id'] for user in users.list_users(root)}
for record in vault.list_jobs(root) + vault.list_experiences(root):
    owner = record.get(vault.OWNER_FIELD)
    print(record['id'], owner, 'known' if owner in known else 'UNKNOWN OWNER')
```

2. The board reads it: the admin's own board is the whole vault, and a
   tester's is empty until they add something.

```python
import os
from careeros import users, vault
from careeros.web.pages import jobs
root = os.environ['VAULT']
for user in users.list_users(root):
    board = jobs.page_context(root, users.owner(user))
    print(user['id'], user['role'], 'jobs:', len(board['entries']))
```

Expect: no `UNKNOWN OWNER` line, every job counted on the admin's board,
and zero on each tester's.

3. The id counters are recorded, and the next id of each kind is above
   every stored record:

```python
import os
from pathlib import Path
from careeros import vault
root = os.environ['VAULT']
print('counters:', vault._read(Path(root) / vault.ID_COUNTER_FILE))
print('still to record:', vault.initialize_id_counters(root))
```

Expect a number for each kind the vault holds records of, and
`still to record: {}` -- the second line is the idempotency check, and
it writes nothing when the first line is already complete.

## If it goes wrong

Put the vault aside and restore the backup. Moving rather than deleting
keeps the half-migrated vault for a look afterwards.

```bash
mv "$VAULT" "$VAULT.failed-record-owner"
cp -r "$BACKUP" "$VAULT"
```

Restart the server afterwards. The restored records carry no owner
again, which the app still reads correctly for the admin.

## Open questions

- A vault that gains a second admin before this runs cannot be migrated
  without `--owner`, because either admin is a plausible owner of the
  pre-M2 records and the script will not pick for you.
- `search.yaml`, the saved criteria, is still one shared file. It is not
  a job or an experience, so this migration does not touch it, and the
  M2 brief does not cover it. Splitting it per user is open work.
- Rolling back to the backup restores the vault without `ids.yaml` if
  the backup predates this run. That is safe -- the allocator falls back
  to the stored records, which is what it did before the counter existed
  -- but the vault is then one delete away from the state this file
  exists to prevent, so re-run the migration after a rollback.
