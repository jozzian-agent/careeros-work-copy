"""Backfill empty descriptions on jobs already in a vault (CAREER-131).

The hand-push path (docs/runbooks/push-to-prod.md) imports a prod-export
generation into the production vault. A generation exported BEFORE
`descriptions.yaml` existed -- generation `2026-11-03` is the one on
production today -- carries only `pool.yaml` + `classification.yaml`, so
every job it imported landed with an EMPTY description and the import
report counted them under "descriptions missing" (deploy/import_prod_
generation.sh, "DESCRIPTIONS, HONESTLY"). The posting text was never
lost: it lives in the frozen ATS snapshots on the LAN host, which
`scripts/export_jobs_for_prod.py` resolves into a `key -> text`
mapping. This script is the step that puts that text onto the jobs that
are still empty.

## What it writes

ONE FIELD, `description`, and ONLY on a job whose stored description is
empty or whitespace. It also confirms `field_provenance.description`
reads `feed` on a job it fills -- the posting text is the feed's word,
the same provenance `scripts/import_pool_to_vault.py` stamps (its
`FEED_PROVENANCE`/`FEED_FILLED_FIELDS`), never a reading of the posting
and never a person's.

A job is matched to the generation by its `source_id`, the pool `key`
the importer stored verbatim (`ashby:Clera:120eb994-...`, stable across
runs). The text comes from the generation's `descriptions.yaml`; the
set of keys this generation could touch comes from its `pool.yaml`, so a
job that matched a pool row but has no resolved text is counted as "no
source text" rather than silently skipped.

## What it never writes

* **No existing description is overwritten.** A job whose description is
  already non-empty is counted under "already had text" and left byte
  for byte alone. This is the rule that makes the script safe to re-run
  and safe against a job an owner has since edited.
* **No record with an owner is touched.** An ownerless universe record
  is what the import created; an owned record is a person's, and a bulk
  backfill nobody has reviewed never rewrites one -- the same posture
  `import_pool_to_vault.py` and `migrate_record_owner.py` hold. Owned
  records that match a pool key are counted and skipped, not filled.
* **Nothing but `description` and its provenance stamp.** No company
  rollup, no status history event, no re-dating: writes go through the
  vault's own atomic writer one file at a time (`vault._write`), exactly
  as the migration scripts in this directory do, so no derived data
  fires off a free-text fill.

## Idempotence

A second run fills nothing: every job it filled on the first run now has
a non-empty description and counts as "already had text".

## Usage

  # dry run (the default): print the whole report, write nothing
  python scripts/backfill_descriptions.py --vault /path/to/vault \\
      --descriptions GEN/descriptions.yaml --pool GEN/pool.yaml
  # apply
  python scripts/backfill_descriptions.py --vault /path/to/vault \\
      --descriptions GEN/descriptions.yaml --pool GEN/pool.yaml --apply

The vault path comes from --vault or CAREEROS_VAULT; neither means stop,
not guess. See docs/runbooks/backfill-descriptions.md.
"""
import argparse
import importlib.util
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careeros import vault  # noqa: E402

#: The importer's own descriptions reader and pool reader, loaded by path
#: because `scripts/` is not a package. `load_descriptions` is the strict
#: `key -> text` reader the VPS-side import already uses (it refuses a
#: non-text value and a colliding key coercion), and `load_yaml` is the
#: tolerant pool reader -- so this backfill reads a generation exactly the
#: way the import does, one reading of the file and not two that can drift.
_IMPORTER_PATH = Path(__file__).resolve().parent / 'import_pool_to_vault.py'
_spec = importlib.util.spec_from_file_location('_pool_importer', _IMPORTER_PATH)
assert _spec is not None and _spec.loader is not None, f'cannot load {_IMPORTER_PATH}'
_importer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_importer)

#: The provenance word a filled description carries, the importer's own
#: (import_pool_to_vault.FEED_PROVENANCE): the posting text is the feed's
#: word. Read from the importer rather than restated, so the two cannot
#: drift.
FEED_PROVENANCE = _importer.FEED_PROVENANCE
DESCRIPTION_FIELD = 'description'
PROVENANCE_FIELD = 'field_provenance'


def jobs(root):
    """Every stored job with the file it lives in, through the vault's own
    tolerant reader. An id-reservation tombstone (`vault.RESERVED_PREFIX`)
    holds a number, not a record, so it is skipped and never deserialised.
    """
    for path in sorted((Path(root) / 'jobs').glob('*.yaml')):
        if path.name.startswith(vault.RESERVED_PREFIX):
            continue
        data = vault._read(path)
        if data:
            yield path, data
        else:
            print(f'  {path.name}: unreadable or empty, skipped', file=sys.stderr)


def has_text(value):
    """A stored description counts as present when it has a non-whitespace
    character. `None`, a missing field, '' and '   ' are all "empty": the
    same reading `universe_context`'s `has_description` uses, so a job the
    All jobs tab shows as having no text is a job this backfill may fill.
    """
    return bool(str(value or '').strip())


def plan(root, descriptions, pool_keys):
    """What this backfill would write, and the four counts the owner reads.

    One row per job this run would fill. The counts answer, over the jobs
    whose `source_id` is one of this generation's pool keys:

      matched          a stored job whose source_id is in the generation
      filled           matched, empty description, and text to fill it with
      already_had_text matched, but the description is already non-empty
                       (never overwritten)
      no_source_text   matched, empty description, and the generation
                       resolved no text for that key
      owned_skipped    matched a pool key but carries an owner_id -- a
                       person's record, never touched by a bulk backfill

    `owned_skipped` is reported beside the four the owner asked for rather
    than folded into one of them, so "matched" stays the honest total of
    jobs this generation names in the vault.
    """
    rows = []
    counts = Counter()
    for path, data in jobs(root):
        source_id = data.get('source_id')
        if not source_id or str(source_id) not in pool_keys:
            continue  # not a job this generation imported
        counts['matched'] += 1
        if data.get(vault.OWNER_FIELD):
            counts['owned_skipped'] += 1
            continue
        if has_text(data.get(DESCRIPTION_FIELD)):
            counts['already_had_text'] += 1
            continue
        text = descriptions.get(str(source_id), '')
        if not has_text(text):
            counts['no_source_text'] += 1
            continue
        counts['filled'] += 1
        rows.append({'id': data.get('id'), 'source_id': str(source_id),
                     'path': path, 'text': text})
    return rows, counts


def write(rows):
    """Write every planned fill, one record at a time, to the exact file
    the row was planned from. Re-reads the record first and re-checks the
    never-overwrite rule, so a concurrent save between plan and write
    cannot be clobbered: a description that is non-empty by the time this
    runs is left alone and the row is skipped (counted, reported)."""
    written, skipped = [], []
    for row in rows:
        try:
            data = vault._read(row['path'])
            if data is None:
                raise ValueError('record vanished or became unreadable')
            if has_text(data.get(DESCRIPTION_FIELD)):
                # Filled by somebody else between plan and write: the
                # never-overwrite rule wins over this run's plan.
                skipped.append(row['id'])
                continue
            data[DESCRIPTION_FIELD] = row['text']
            provenance = data.get(PROVENANCE_FIELD)
            if not isinstance(provenance, dict):
                provenance = {}
            provenance[DESCRIPTION_FIELD] = FEED_PROVENANCE
            data[PROVENANCE_FIELD] = provenance
            vault._write(row['path'], data)
        except Exception as error:  # noqa: BLE001 - report and keep sweeping
            print(f"  skipped {row['id']} ({type(error).__name__}: {error})",
                  file=sys.stderr)
            skipped.append(row['id'])
            continue
        written.append(row['id'])
    return written, skipped


def report(root, counts, rows, apply_changes, sample=5):
    """Print the whole plan, in both modes, before anything is written."""
    print(f"vault={root}  mode={'APPLY' if apply_changes else 'DRY RUN'}")
    print('-' * 78)
    print(f"matched (a job this generation's pool names):  {counts['matched']}")
    print(f"  would fill (empty + text available):         {counts['filled']}")
    print(f"  already had text (never overwritten):        {counts['already_had_text']}")
    print(f"  no source text (empty, none resolved):       {counts['no_source_text']}")
    print(f"  owned, skipped (a person's record):          {counts['owned_skipped']}")
    if rows:
        print('-' * 78)
        print(f'sample (first {min(sample, len(rows))} of {len(rows)} to fill), by id:')
        for row in rows[:sample]:
            preview = row['text'].strip().replace('\n', ' ')[:60]
            print(f"  {row['id']}  {row['source_id']}  {len(row['text'])} chars  {preview!r}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(__doc__ or '').splitlines()[0] if __doc__ else
        'Backfill empty descriptions on jobs already in a vault')
    parser.add_argument('--vault', help='vault path (default: the CAREEROS_VAULT variable)')
    parser.add_argument('--descriptions', required=True,
                        help="the generation's descriptions.yaml (key -> posting text)")
    parser.add_argument('--pool', required=True,
                        help="the generation's pool.yaml (the set of keys it names)")
    parser.add_argument('--apply', action='store_true',
                        help='actually write (default: dry run, writes nothing)')
    args = parser.parse_args(argv)

    given = args.vault or os.environ.get('CAREEROS_VAULT')
    if not given:
        raise SystemExit('no vault given: pass --vault PATH or set CAREEROS_VAULT')
    root = Path(given)
    if not (root / 'jobs').is_dir():
        raise SystemExit(f'{root} does not look like a CareerOS vault (missing jobs/)')

    # The generation's two files, read with the importer's own readers.
    descriptions = _importer.load_descriptions(args.descriptions)
    pool = _importer.load_yaml(args.pool)
    pool_keys = {str(row['key']) for row in (pool.get('postings') or []) if row.get('key')}
    if not pool_keys:
        raise SystemExit(f'{args.pool} names no posting key; nothing to match against')

    with vault.WriteLock(root):
        rows, counts = plan(root, descriptions, pool_keys)
        report(root, counts, rows, args.apply)
        if not rows:
            print('-' * 78)
            print('nothing to fill: every matched job already has text or has none to give')
            return 0
        if not args.apply:
            print('-' * 78)
            print('DRY RUN: nothing was written. Re-run with --apply to write.')
            return 0
        written, skipped = write(rows)
        print('-' * 78)
        print(f'wrote {len(written)} description(s)')
        # A row skipped because a concurrent save filled it first is not a
        # failure; one skipped because the write raised IS. Re-plan: any
        # job still empty with text available is a write that did not land.
        left, _ = plan(root, descriptions, pool_keys)
        unexpected = [row_id for row_id in skipped if row_id in {r['id'] for r in left}]
        if unexpected:
            raise SystemExit(f'{len(unexpected)} planned write(s) did not land '
                             f'(ids: {", ".join(map(str, unexpected[:10]))}); '
                             'check the vault by hand')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
