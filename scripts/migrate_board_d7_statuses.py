"""One-shot migration: put every stored job on the D7 status list.

Owner decision D7 (2026-10-15): the statuses are new, interested, applied,
interviewing, offer, won, rejected, stopped. Withdrawn is renamed, and
Closed stops being a status at all, because a posting that is gone is a
fact about the posting rather than the owner's decision. This script moves
what is already stored onto that list, exactly by the owner's rules:

  * withdrawn becomes stopped
  * a job whose status is closed gets the `closed` flag, and its status
    goes back to the last status it held before Closed, read from its own
    history; a job whose history does not say becomes new
  * `closed_at` is the date of the "posting gone" history event, and the
    day this migration runs when there is no such event
  * nothing is ended on the owner's behalf: a restored job is open again,
    and the closed-postings review on the board is what asks about it

Safety rails:
  * dry run by default: nothing is written unless `--apply` is passed, and
    the full move report is printed before any write, in both modes
  * the vault path comes from `--vault` or `CAREEROS_VAULT`, and a run
    with neither stops rather than guessing
  * the whole sweep holds `vault.WriteLock`, so the server cannot write a
    job in the middle of it
  * writes go through the vault's own atomic writer, one file at a time,
    like `vault.migrate_job_fields`: a record written before today's rules
    must not be refused over a field this migration does not touch,
    `save_job` would append a status_changed event for a move the owner
    never made, and this sweep must not trigger the company rollups an
    ordinary record write does
  * a single record's failure is reported and skipped, never fatal for the rest,
    and a sweep that skipped anything exits non-zero
  * idempotent: a second run finds nothing left to change
  * the report names records by id, never by title, so it can be pasted
    into a build note or a PR without leaking the vault

What it deliberately leaves alone: stored history. An event written while
Closed or Withdrawn was still a status keeps its own words, because
history records what happened rather than what the vocabulary says today.
The backup is the runbook step (docs/runbooks/migrate-board-d7.md), not
this script.

Usage:
  python scripts/migrate_board_d7_statuses.py --vault /path/to/vault
  python scripts/migrate_board_d7_statuses.py --vault /path/to/vault --apply
"""
import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from careeros import vault  # noqa: E402

# The two retired status words. Neither is in `vault.STATUSES` any more,
# which is exactly why they are spelled out here: this script is the one
# place that still has to recognise them.
WITHDRAWN = 'withdrawn'
CLOSED = 'closed'

# Withdrawn is a rename, so a status read back out of history is renamed
# too: a job that went withdrawn, then closed, comes back as stopped.
RENAMED = {WITHDRAWN: 'stopped'}

RENAME = 'rename'
UNCLOSE = 'unclose'

# Where a restored status came from, for the report.
FROM_HISTORY = 'history'
FROM_DEFAULT = 'default'


def posting_gone_date(job):
    """The day this posting was found gone, from the job's own history, or
    None when no such event was ever recorded.

    The FIRST "posting gone" event, not the last: the day the posting went
    is the day it was first missed, and that is the day the board counts
    the week from.
    """
    for event in job.get('history') or []:
        if not isinstance(event, dict) or event.get('event') != 'posting_gone':
            continue
        stamp = str(event.get('ts') or '')[:10]
        try:
            return date.fromisoformat(stamp).isoformat()
        except ValueError:
            continue
    return None


def status_before_closed(job):
    """The status this job held before it was closed, read from history,
    or None when its history does not say.

    The last move INTO closed is the one that counts: a job closed, put
    back and closed again comes back to where it was the second time. The
    status it names is renamed if it is a retired word, and ignored
    entirely if it is not a status today, which is what makes `new` the
    answer for a job whose history only ever names Closed.
    """
    for event in reversed(job.get('history') or []):
        if not isinstance(event, dict) or event.get('event') != 'status_changed':
            continue
        before, separator, after = str(event.get('detail') or '').partition('->')
        if not separator or after.strip() != CLOSED:
            continue
        restored = RENAMED.get(before.strip(), before.strip())
        return restored if restored in vault.STATUSES else None
    return None


def plan(pairs, today):
    """One row per job this migration would touch, in list order.

    Pure: it reads records and returns rows, so the planned change is
    testable without a vault and identical in dry-run and apply mode.
    `pairs` is the `(path, data)` sequence `records()` yields, and every
    row carries its own `path`: the write step must never have to guess
    which file a row belongs to, because a record with no `id` (or a
    duplicated one) would make an id-keyed lookup write onto the wrong
    file. A record with no `id` is reported and never planned.
    `updates` is the payload the row writes onto the stored record.
    """
    rows = []
    for path, job in pairs:
        status = job.get('status')
        if not job.get('id'):
            if status in (WITHDRAWN, CLOSED):
                print(f"  {path.name}: status {status} but no id: left untouched, "
                      'fix the record by hand and re-run', file=sys.stderr)
            continue
        row = {'id': job.get('id'), 'path': path, 'status': status}
        if status == WITHDRAWN:
            rows.append(row | {'action': RENAME, 'new_status': RENAMED[WITHDRAWN],
                               'updates': {'status': RENAMED[WITHDRAWN]}})
            continue
        if status != CLOSED:
            if status not in vault.STATUSES:
                print(f"  {job.get('id')}: status {status!r} is not a D7 status and not "
                      'retired: left alone, fix the record by hand', file=sys.stderr)
            continue
        restored = status_before_closed(job)
        gone = posting_gone_date(job)
        closed_at = gone or today.isoformat()
        rows.append(row | {
            'action': UNCLOSE,
            'new_status': restored or vault.STATUSES[0],
            'source': FROM_HISTORY if restored else FROM_DEFAULT,
            'closed_at': closed_at,
            'closed_at_source': 'posting gone event' if gone else 'migration date',
            'updates': {'status': restored or vault.STATUSES[0], 'closed': True,
                        'closed_at': closed_at},
        })
    return rows


def describe(row):
    """One report line for one planned change."""
    if row['action'] == RENAME:
        return f"{row['id']}  {row['status']} -> {row['new_status']}  (renamed)"
    reason = ('last status before Closed, from history' if row['source'] == FROM_HISTORY
              else 'history does not say, so the first status')
    return (f"{row['id']}  {row['status']} -> {row['new_status']}  "
            f"({reason}), closed=True, closed_at={row['closed_at']} "
            f"({row['closed_at_source']})")


def status_counts(jobs):
    """How many jobs sit in each stored status, and how many carry the
    closed flag. Every status any record holds is counted, retired words
    included, which is the point of the before half of the report."""
    counts = {}
    for job in jobs:
        key = job.get('status') or vault.STATUSES[0]
        counts[key] = counts.get(key, 0) + 1
    return counts, sum(1 for job in jobs if job.get('closed'))


def moves(rows):
    """How many jobs move from where to where: the matrix the owner asked
    the report for, keyed by `old -> new`."""
    matrix = {}
    for row in rows:
        key = f"{row['status']} -> {row['new_status']}"
        matrix[key] = matrix.get(key, 0) + 1
    return matrix


def projected(counts, rows):
    """The status counts this migration would leave behind, so a dry run
    reports an after as well as a before."""
    after = dict(counts)
    for row in rows:
        after[row['status']] = after.get(row['status'], 0) - 1
        after[row['new_status']] = after.get(row['new_status'], 0) + 1
    return {status: count for status, count in after.items() if count}


def show_counts(label, counts, closed):
    """One line of status counts, in board order, with any retired word
    left over after it."""
    order = [status for status in vault.STATUSES if status in counts]
    order += sorted(status for status in counts if status not in vault.STATUSES)
    listed = ', '.join(f"{status}={counts[status]}" for status in order) or 'no jobs'
    print(f"{label}: {listed}  |  closed flag set: {closed}")


def records(root):
    """Every stored job with the file it lives in, through the vault's own
    tolerant reader: a corrupt or empty file is skipped here exactly as it
    is skipped everywhere else, and named on stderr so a retired status
    hiding in one cannot pass unnoticed."""
    for path in sorted((Path(root) / 'jobs').glob('*.yaml')):
        if path.name.startswith(vault.RESERVED_PREFIX):
            continue
        data = vault._read(path)
        if data:
            yield path, data
        else:
            print(f"  {path.name}: unreadable or empty, skipped", file=sys.stderr)


def write(root, rows):
    """Write every planned change, one record at a time, to the exact file
    the row was planned from. Returns the ids actually written; a record
    that cannot be written is reported to stderr and skipped, so one bad
    file cannot stop the sweep."""
    written = []
    for row in rows:
        try:
            data = vault._read(row['path'])
            data.update(row['updates'])
            vault._write(row['path'], data)
        except Exception as error:
            print(f"  skipped {row['id']} ({type(error).__name__}: {error})", file=sys.stderr)
            continue
        written.append(row['id'])
    return written


def report(jobs, rows, root, apply_changes, today):
    """Print the whole move report: where the jobs are now, every planned
    change, the move matrix, and where they would be afterwards.

    Printed in both modes and always before anything is written, so an
    --apply can never write a move this run did not just show.
    """
    before, closed_before = status_counts(jobs)
    print(f"vault={root}  mode={'APPLY' if apply_changes else 'DRY RUN'}  date={today.isoformat()}")
    print('-' * 70)
    show_counts('before ', before, closed_before)
    for row in rows:
        print(describe(row))
    matrix = moves(rows)
    for key in sorted(matrix):
        print(f"moved {matrix[key]}: {key}")
    show_counts('after  ', projected(before, rows),
                closed_before + sum(1 for row in rows if row['action'] == UNCLOSE))
    print('-' * 70)
    if not rows:
        print(f"{len(jobs)} jobs: nothing to change, every job is already on the D7 list")
        return
    print(f"{len(jobs)} jobs: {sum(1 for row in rows if row['action'] == RENAME)} renamed, "
          f"{sum(1 for row in rows if row['action'] == UNCLOSE)} un-closed, "
          f"{len(jobs) - len(rows)} already on the D7 list")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', help='vault path (default: the CAREEROS_VAULT environment variable)')
    parser.add_argument('--apply', action='store_true',
                        help='actually write (default: dry run, writes nothing)')
    args = parser.parse_args(argv)

    given = args.vault or os.environ.get('CAREEROS_VAULT')
    if not given:
        raise SystemExit('no vault given: pass --vault PATH or set CAREEROS_VAULT')
    root = Path(given)
    if not (root / 'jobs').is_dir():
        raise SystemExit(f"{root} does not look like a CareerOS vault (missing jobs/)")

    today = date.today()
    # One lock around read, report and write, so the plan that is printed
    # is the state that is then written.
    with vault.WriteLock(root):
        pairs = list(records(root))
        jobs = [data for _, data in pairs]
        rows = plan(pairs, today)
        report(jobs, rows, root, args.apply, today)
        if not rows:
            return
        if not args.apply:
            print('DRY RUN: nothing was written. Re-run with --apply to write.')
            return
        written = write(root, rows)
        stored, closed_after = status_counts([data for _, data in records(root)])
        show_counts('on disk', stored, closed_after)
        print(f"wrote {len(written)} record(s)")
        expected = projected(status_counts(jobs)[0], rows)
        expected_closed = status_counts(jobs)[1] + sum(1 for row in rows if row['action'] == UNCLOSE)
        if stored != expected or closed_after != expected_closed:
            raise SystemExit('the vault on disk does not match the report above: '
                             'nothing else was written, check the vault by hand')
        if len(written) < len(rows):
            # A skipped record printed its error to stderr, but a wrapper
            # reads the exit code: a partly written sweep is a failure,
            # not a success with a note.
            raise SystemExit(f"{len(rows) - len(written)} of {len(rows)} planned write(s) "
                             'were skipped (see the errors above)')


if __name__ == '__main__':
    main()
