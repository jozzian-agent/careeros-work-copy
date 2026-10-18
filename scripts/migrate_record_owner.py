"""One-shot migration: give every stored job and experience an owner.

CAREER-39 M2. Jobs, experiences, companies and the tag vocabulary were
one shared world: every logged-in user saw all of it. The split makes a
job and an experience private to one user (owner decisions D3 and D4)
and leaves companies and vocabulary shared. That is the `owner_id` field
(vault.OWNER_FIELD), and no record written before this change carries
one.

This script fills it in. Every ownerless job and every ownerless
experience is assigned to the admin account, which is the one account
that existed while those records were being added, so the migration
hands them to the person who added them.

## What it writes, and what it deliberately does not

WRITES: `owner_id`, and nothing else, on jobs and experiences that have
none. It is a new field no record carried before, so nothing is
overwritten on a first run.

ALSO WRITES, once: `ids.yaml`, the vault's record-number high-water
marks (`vault.initialize_id_counters`). The live vault predates that
file, and an id used to be `max stored id + 1`, which made the next id a
readable fact about which records the vault still holds. Seeding the
counters from what is stored now is what makes an existing vault
monotonic from its next write rather than from its next delete. It is
not an ownership change, so it happens whether or not any record needs
an owner, and it is idempotent: a mark the counter already holds is left
alone, and a counter standing above the stored records is never pulled
down to them.

DOES NOT WRITE: a record that already names an owner. A job a tester
added after the split is theirs, and a second run of this script must
not move it to the admin. That is also what makes the script idempotent:
after one run there is nothing left with no owner.

DOES NOT TOUCH companies, tags.yaml or search.yaml. Companies and
vocabulary stay one shared universe by decision (D3), so there is
nothing on them to assign. The company high-water mark IS recorded in
`ids.yaml`, which is a fact about numbers handed out and not about any
company record.

## Why the admin, and what happens before this runs

A vault that has not been migrated yet still works, because the read
side has the same rule: `vault.Owner` lets the admin see the records
that carry no owner (`inherits_ownerless`), so the admin's board is
whole either way and nobody else's shows a record they did not add.
Running this turns that read-time rule into stored facts, which is what
makes a second admin account, or a later change to that rule, safe.

A vault with no admin account is an error rather than a guess: there is
no second-best owner for somebody's private jobs. A vault with more than
one admin is also an error, because picking one of them would be a
guess as well; pass `--owner USER-00X` to say which.

Safety rails, the same ones `migrate_job_value_records.py` follows:
  * dry run by default; nothing is written without `--apply`, and the
    full report is printed first in both modes
  * the vault path comes from `--vault` or `CAREEROS_VAULT`; neither
    means stop, not guess
  * the whole sweep holds `vault.WriteLock`
  * writes go through the vault's own atomic writer, one file at a time,
    so no company rollup and no status history event fires
  * one record's failure is reported and skipped, and a sweep that
    skipped anything exits non-zero
  * idempotent: a second run reports nothing to change
  * the report names records by id, never by title

Usage:
  python scripts/migrate_record_owner.py --vault /path/to/vault
  python scripts/migrate_record_owner.py --vault /path/to/vault --apply
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careeros import users, vault  # noqa: E402

#: The two private record kinds, by the vault directory they live in.
#: Companies and the vocabulary are shared and are not here.
KINDS = ('jobs', 'experiences')


def records(root, kind):
    """Every stored record of one kind with the file it lives in, through
    the vault's own tolerant reader. A directory that is not there yields
    nothing: a vault may hold jobs and no experiences."""
    for path in sorted((Path(root) / kind).glob('*.yaml')):
        data = vault._read(path)
        if data and vault.is_reserved(data):
            # An id-reservation tombstone holds a number, not a record,
            # so it is not a job or an experience needing an owner and it
            # is not counted as one. Its number still reaches the counter
            # marks this records, because those read the directory raw.
            continue
        if data:
            yield path, data
        else:
            print(f'  {path.name}: unreadable or empty, skipped', file=sys.stderr)


def resolve_owner(root, given=None):
    """The user id every ownerless record is assigned to.

    An explicit `--owner` wins and is checked against the stored
    accounts, so a typo cannot assign a vault's whole history to a user
    that does not exist. Otherwise it is the one admin.
    """
    if given:
        user = users.load_user(root, given)
        if user is None:
            raise SystemExit(f'no user with the id {given} in {root}')
        return user['id']
    found = users.admins(root)
    if not found:
        raise SystemExit(
            f'{root} has no admin account, so there is nobody to assign the existing '
            'records to. Create one (python -m careeros.users create --role admin ...) '
            'or name an owner with --owner USER-00X.')
    if len(found) > 1:
        names = ', '.join(user['id'] for user in found)
        raise SystemExit(f'{root} has more than one admin ({names}). '
                         'Name the one to assign to with --owner USER-00X.')
    return found[0]['id']


def plan(root, owner):
    """What this migration would write, one row per record that changes.

    A record is a row when it has no owner. A falsy stored value counts
    as none: an empty string is not a user id, and the read side treats
    it the same way (see vault.Owner.owns).
    """
    rows = []
    for kind in KINDS:
        for path, data in records(root, kind):
            if data.get(vault.OWNER_FIELD):
                continue
            rows.append({'id': data.get('id'), 'kind': kind, 'path': path,
                         'updates': {vault.OWNER_FIELD: owner}})
    return rows


def write(rows):
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


def plan_id_counters(root):
    """The id high-water marks `vault.initialize_id_counters` would
    record, without recording them.

    A read, so the dry run stays a dry run. Empty on a vault whose
    counter file already holds every mark, which is every vault written
    since `ids.yaml` existed and every vault this has already run on.
    """
    counters = vault._read(Path(root) / vault.ID_COUNTER_FILE) or {}
    planned = {}
    for kind in vault.ID_PREFIXES:
        highest = vault._highest_allocated(root, kind)
        if highest and counters.get(kind) != highest:
            planned[kind] = highest
    return planned


def report(root, owner, counts, rows, apply_changes, counters=None):
    """Print the whole plan, in both modes, before anything is written."""
    print(f"vault={root}  mode={'APPLY' if apply_changes else 'DRY RUN'}  owner={owner}")
    print('-' * 78)
    if counters:
        print('id high-water marks to record in ' + vault.ID_COUNTER_FILE + ': '
              + ', '.join(f'{kind}={number}' for kind, number in sorted(counters.items())))
    else:
        print(f'{vault.ID_COUNTER_FILE}: already records every id high-water mark')
    total = sum(counts.values())
    if not rows:
        print(f'{total} private record(s): nothing to change, every job and experience '
              'already names its owner')
        return
    for row in rows:
        print(f"  {row['id']}: {row['kind'][:-1]} with no owner -> {owner}")
    print('-' * 78)
    for kind in KINDS:
        changing = sum(row['kind'] == kind for row in rows)
        print(f'{kind}: {changing} of {counts[kind]} gain an owner')
    print('companies and the tag vocabulary are shared universe and are not touched')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', help='vault path (default: the CAREEROS_VAULT variable)')
    parser.add_argument('--owner', default=None,
                        help='user id to assign to (default: the one admin account)')
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
        owner = resolve_owner(root, args.owner)
        counts = {kind: sum(1 for _ in records(root, kind)) for kind in KINDS}
        rows = plan(root, owner)
        # Planned, not written, so the dry run still writes nothing. What
        # initialize_id_counters would record is exactly the marks this
        # reports, because it is idempotent against what is stored.
        counters = plan_id_counters(root)
        report(root, owner, counts, rows, args.apply, counters)
        if not rows and not counters:
            return 0
        if not args.apply:
            print('DRY RUN: nothing was written. Re-run with --apply to write.')
            return 0
        if counters:
            recorded = vault.initialize_id_counters(root)
            print(f'recorded id high-water marks: '
                  + ', '.join(f'{kind}={number}' for kind, number in sorted(recorded.items())))
            if plan_id_counters(root):
                raise SystemExit(f'{vault.ID_COUNTER_FILE} still does not record every '
                                 'high-water mark: check the vault by hand')
        if not rows:
            return 0
        written = write(rows)
        print(f'wrote {len(written)} record(s)')
        left = plan(root, owner)
        if left:
            raise SystemExit(f'{len(left)} record(s) still carry no owner: '
                             'check the vault by hand')
        if len(written) < len(rows):
            raise SystemExit(f"{len(rows) - len(written)} of {len(rows)} planned write(s) "
                             'were skipped (see the errors above)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
