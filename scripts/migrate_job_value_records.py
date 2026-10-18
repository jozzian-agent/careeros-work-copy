"""One-shot migration: give every stored job its coded value records.

CAREER-57. A job has carried its classification as free text since the
beginning -- a `seniority` string, an `employment_type` string, a
`location` line, a `salary_note` -- with one word of provenance per
field in `field_provenance`. The taxonomy (CAREER-55) and the pipeline
(this ticket) replace that with D4 value records: a code from a versioned
list, the source that put it there, the phrase that decided it, and the
taxonomy version it was classified under.

This script puts the records on the records. It runs the rules layer over
each stored job and writes the result to the job's new `values` and
`salary` fields.

## What it writes, and what it deliberately does not

WRITES: `values` and `salary`, and nothing else. Both are new fields that
no record carried before, so nothing is overwritten on a first run.

DOES NOT WRITE: the free-text fields. `seniority`, `employment_type`,
`location`, `salary_note` and the free-text half of `requirement_groups`
all stay exactly as they are, and every page that reads them keeps
working. Retiring them is a second, separate step, because every reader
has to move in the same change as the field and those readers are the
React job page, the extraction popup, the job PUT allowlist and the
intake path -- work this ticket's brief does not cover. The runbook
(docs/runbooks/migrate-job-value-records.md) carries the reader
inventory, so the next person does not have to find them again.

DOES NOT TOUCH `field_provenance`, which keeps its `dict[str, str]`
shape. It is a map from field name to one word about who last wrote that
field; a value record carries its own source, its own confidence and its
own evidence, and putting one inside that mapping would mean changing the
validator and every reader of it to store something it was never for. The
two live side by side: `field_provenance` describes the free-text fields,
`values` describes the coded ones.

## How an owner edit survives

A free-text field that `field_provenance` marks `user` is translated into
a value record with the source `user`, which outranks every machine
source in the precedence order (admin > user > feed > rule > llm). So the
rules layer cannot overwrite a seniority the owner typed, on this run or
on any later one. A field a machine wrote is NOT carried across: the
pipeline re-reads the posting anyway, and pinning an old model's answer
in place as though a human had made it would be the one thing precedence
exists to prevent.

Safety rails, the same ones `migrate_board_d7_statuses.py` follows:
  * dry run by default; nothing is written without `--apply`, and the
    full report is printed first in both modes
  * the vault path comes from `--vault` or `CAREEROS_VAULT`; neither
    means stop, not guess
  * the whole sweep holds `vault.WriteLock`
  * writes go through the vault's own atomic writer, one file at a time,
    so no company rollup and no status history event fires
  * one record's failure is reported and skipped, and a sweep that
    skipped anything exits non-zero
  * idempotent: a second run reports nothing to change, because a stored
    value is only replaced by a strictly stronger source and the rules
    layer is not stronger than itself
  * the report names records by id, never by title

Usage:
  python scripts/migrate_job_value_records.py --vault /path/to/vault
  python scripts/migrate_job_value_records.py --vault /path/to/vault --apply
"""
import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careeros import classify, taxonomy, vault  # noqa: E402
from careeros.classify import rules  # noqa: E402

#: The free-text fields coded value records are meant to replace. Listed
#: here because the report counts how many records still carry one: that
#: count is what tells the owner how much the second step is worth.
FREE_TEXT_FIELDS = ('seniority', 'employment_type', 'location', 'salary_note')


def records(root):
    """Every stored job with the file it lives in, through the vault's
    own tolerant reader."""
    for path in sorted((Path(root) / 'jobs').glob('*.yaml')):
        data = vault._read(path)
        if data:
            yield path, data
        else:
            print(f'  {path.name}: unreadable or empty, skipped', file=sys.stderr)


def _same_salary(stored, fresh):
    """Whether two salary blocks say the same thing. `classified_at`
    moves on every run and is not part of what a block says."""
    if stored is None or fresh is None:
        return stored is None and fresh is None
    skip = ('classified_at',)
    return ({key: value for key, value in stored.items() if key not in skip}
            == {key: value for key, value in fresh.items() if key not in skip})


def plan(pairs, *, at=None):
    """What this migration would write, one row per job that changes.

    The merge is `classify.merge`, which is the one place precedence is
    applied, so this script cannot disagree with the pipeline about who
    wins.
    """
    rows = []
    for path, job in pairs:
        subject = classify.from_vault_job(job)
        stored = vault.validate_value_records(job.get('values'))
        carried = classify.merge(stored, subject['values'])
        merged = classify.merge(carried, rules.classify(subject, at=at))
        salary = classify.salary.classify(subject, at=at)
        if not _same_salary(job.get('salary'), salary):
            salary_update = {'salary': salary}
        else:
            salary_update = {}
        if merged == stored and not salary_update:
            continue
        rows.append({
            'id': job.get('id'), 'path': path,
            'updates': {'values': merged, **salary_update},
            'added': sorted(set(merged) - set(stored)),
            'from_free_text': sorted(set(carried) - set(stored)),
            'settled': sorted(field for field, record in merged.items()
                              if record['value'] != taxonomy.UNKNOWN),
            'review': classify.review(merged, salary),
            'salary': bool(salary),
            'free_text_kept': [field for field in FREE_TEXT_FIELDS
                               if str(job.get(field) or '').strip()],
        })
    return rows


def write(root, rows):
    """Write every planned change, one record at a time, to the exact
    file the row was planned from."""
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


def report(jobs, rows, root, apply_changes):
    """Print the whole plan, in both modes, before anything is written."""
    print(f"vault={root}  mode={'APPLY' if apply_changes else 'DRY RUN'}  "
          f"taxonomy={taxonomy.TAXONOMY_VERSION}")
    print('-' * 78)
    if not rows:
        print(f'{len(jobs)} jobs: nothing to change, every job already carries its value '
              'records')
        return
    settled = Counter(field for row in rows for field in row['settled'])
    carried = Counter(field for row in rows for field in row['from_free_text'])
    owed = Counter(reason for row in rows for reason in row['review'].values())
    kept = Counter(field for row in rows for field in row['free_text_kept'])
    for row in rows:
        print(f"  {row['id']}: {len(row['settled'])}/{len(row['updates']['values'])} fields "
              f"settled, {len(row['review'])} need review"
              + (', salary read' if row['salary'] else ''))
    print('-' * 78)
    print(f'{len(rows)} of {len(jobs)} jobs gain value records')
    print('settled per field: ' + ', '.join(f'{field}={settled[field]}'
                                            for field in rules.FIELDS if settled[field]))
    if carried:
        print('carried from a free-text field the owner wrote: '
              + ', '.join(f'{field}={count}' for field, count in sorted(carried.items())))
    if owed:
        print('needs review: ' + ', '.join(f'{reason}={count}'
                                           for reason, count in sorted(owed.items())))
    print(f"salary blocks: {sum(1 for row in rows if row['salary'])}")
    print('free-text fields still stored and still read by the app: '
          + ', '.join(f'{field}={count}' for field, count in sorted(kept.items()) if count))
    print('  (retiring them is the second step; see '
          'docs/runbooks/migrate-job-value-records.md)')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', help='vault path (default: the CAREEROS_VAULT variable)')
    parser.add_argument('--apply', action='store_true',
                        help='actually write (default: dry run, writes nothing)')
    args = parser.parse_args(argv)

    given = args.vault or os.environ.get('CAREEROS_VAULT')
    if not given:
        raise SystemExit('no vault given: pass --vault PATH or set CAREEROS_VAULT')
    root = Path(given)
    if not (root / 'jobs').is_dir():
        raise SystemExit(f'{root} does not look like a CareerOS vault (missing jobs/)')

    with vault.WriteLock(root):
        pairs = list(records(root))
        jobs = [data for _, data in pairs]
        rows = plan(pairs)
        report(jobs, rows, root, args.apply)
        if not rows:
            return 0
        if not args.apply:
            print('DRY RUN: nothing was written. Re-run with --apply to write.')
            return 0
        written = write(root, rows)
        print(f'wrote {len(written)} record(s)')
        left = plan(list(records(root)))
        if left:
            raise SystemExit(f'{len(left)} record(s) still differ from the plan above: '
                             'check the vault by hand')
        if len(written) < len(rows):
            raise SystemExit(f"{len(rows) - len(written)} of {len(rows)} planned write(s) "
                             'were skipped (see the errors above)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
