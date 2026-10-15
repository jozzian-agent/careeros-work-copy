---
type: Routine
title: "Move a vault onto the D7 status list"
description: "Back up a vault, run the one-time D7 status migration against it, verify it and roll it back."
timestamp: 2026-10-15
---

# Move a vault onto the D7 status list

Owner decision D7 (2026-10-15) settles the statuses as new, interested,
applied, interviewing, offer, won, rejected, stopped. Withdrawn is renamed
to Stopped, and Closed stops being a status at all: a posting that is gone
is a fact about the posting, so it is the `closed` flag on the job.

A vault written before that holds jobs in `withdrawn` and `closed`, which
`vault.save_job` now refuses, so any edit to one of those jobs fails until
it is migrated. `scripts/migrate_board_d7_statuses.py` moves them.

This is the owner's action. The commands below were proven against fixture
copies of a vault on 2026-10-15 (`tests/test_migrate_board_d7_statuses.py`
runs the same code); the quoted output is a fixture run, so the numbers
from the real vault will differ.

## What it writes

- Job records only, one YAML file each, and only the jobs whose status is
  `withdrawn` or `closed`. No company, experience or tags file is touched.
- Per job: `status`, and for a job that was Closed also `closed: true` and
  `closed_at`.
- Nothing else. Stored history is left exactly as it is, because history
  records what happened: an event written while Closed was a status keeps
  reading in the words of its own time.
- Nothing twice: the run is idempotent, and a second run reports
  `nothing to change, every job is already on the D7 list`.

## Before running

- The instance is on the commit that carries this chunk. The migration
  leaves jobs in statuses the older code also accepts, but only the new
  code refuses to write `closed`/`withdrawn` back, and only the new code
  reads the `closed` flag. Restart the server on this commit first, which
  also backfills `closed`, `closed_at`, `closed_reviewed_at` and
  `end_reason` onto every record (`vault.migrate_job_fields`, additive and
  idempotent, runs at startup).
- The server may keep running. The script takes the same cross-process
  write lock (`vault.WriteLock`) the server takes, and holds it around the
  read, the report and the writes, so no request can interleave.
- Decide the vault path. VAULT below is that path. Pass it explicitly
  rather than relying on a default, so a run can never land on a vault
  nobody named.

## The sequence

Run from the repository root, in the product virtual environment.

```bash
export VAULT=/path/to/the/vault
export BACKUP=~/careeros-vault.before-board-d7-$(date +%Y%m%d)

# 1. Back up the whole vault, to a copy OUTSIDE it, and never over an
#    existing backup (-n). Check the copy before going on. Note: the copy
#    is per-file atomic but not one point in time while the server runs;
#    stop the server first if the vault is being written to.
cp -rn "$VAULT" "$BACKUP"
ls "$VAULT"/jobs | wc -l
ls "$BACKUP"/jobs | wc -l

# 2. Dry run. Writes nothing and prints the whole move report.
.venv/bin/python scripts/migrate_board_d7_statuses.py --vault "$VAULT"

# 3. Read the report. Every line is one job: where it is, where it goes,
#    and for a Closed job where its status and its closed date came from.
#    Only then apply. The apply prints the same report before it writes.
.venv/bin/python scripts/migrate_board_d7_statuses.py --vault "$VAULT" --apply
```

A dry run on the five-job fixture prints:

```
vault=/tmp/fixture  mode=DRY RUN  date=2026-10-15
----------------------------------------------------------------------
before : new=1, closed=3, withdrawn=1  |  closed flag set: 0
JOB-004  closed -> stopped  (last status before Closed, from history), closed=True, closed_at=2026-10-15 (migration date)
JOB-003  closed -> new  (history does not say, so the first status), closed=True, closed_at=2026-10-15 (migration date)
JOB-002  closed -> interested  (last status before Closed, from history), closed=True, closed_at=2026-09-20 (posting gone event)
JOB-001  withdrawn -> stopped  (renamed)
moved 1: closed -> interested
moved 1: closed -> new
moved 1: closed -> stopped
moved 1: withdrawn -> stopped
after  : new=2, interested=1, stopped=2  |  closed flag set: 3
----------------------------------------------------------------------
5 jobs: 1 renamed, 3 un-closed, 1 already on the D7 list
DRY RUN: nothing was written. Re-run with --apply to write.
```

The apply repeats that report, then adds what is on disk afterwards:

```
on disk: new=2, interested=1, stopped=2  |  closed flag set: 3
wrote 4 record(s)
```

A run that skipped a record says so on stderr and exits non-zero, so a
partly written sweep is never reported as a success.

## Verify

Three checks, each a short script in the product virtual environment with
VAULT still exported.

1. No job is left in a retired status, and every stored status is one of
   the eight:

```python
import os
from careeros import vault
held = sorted(set(job.get('status') for job in vault.list_jobs(os.environ['VAULT'])))
print('statuses held:', held)
print('retired left:', [status for status in held if status not in vault.STATUSES])
```

2. Every job that was Closed now carries the flag and a date:

```python
import os
from careeros import vault
for job in vault.list_jobs(os.environ['VAULT']):
    if job.get('closed'):
        print(job['id'], job['status'], 'closed_at', job.get('closed_at'))
```

3. The board reads it: the open and ended split, which closed postings
   the banner will ask about, and the search-so-far counts:

```python
import os
from careeros.web.pages import jobs
board = jobs.page_context(os.environ['VAULT'])
print('split:', board['counts'])
print('to review:', board['closed_review'])
print('search so far:', board['search_so_far'])
```

Expect: `retired left: []`, one line per formerly Closed job, and a split
whose two numbers add up to the job count.

## If it goes wrong

Put the vault aside and restore the backup. Moving rather than deleting
keeps the half-migrated vault for a look afterwards.

```bash
mv "$VAULT" "$VAULT.failed-board-d7"
cp -r "$BACKUP" "$VAULT"
```

Restart the server afterwards, and remember that the restored records sit
in `withdrawn`/`closed` again, which this commit refuses to write: an edit
to one of those jobs fails until the migration runs.

## Open questions

- A job whose watch never recorded a `posting_gone` event gets the
  migration date as its `closed_at`, so every such job crosses the
  one-week review threshold on the same day, a week after the migration.
- Nothing clears the `closed` flag if a posting comes back online. The
  watcher sets it and the owner's Keep action quiets it, which is all D7
  asks for.
