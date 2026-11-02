"""One-shot migration: move a vault off the three job families v2 merged away.

CAREER-129. Taxonomy v2 replaces the 40-family list with 61, and three of
the old 40 are gone -- not removed, ABSORBED, each into the family whose
meaning already covered it:

    chief-product-officer         -> product-manager
    ict-business-analysis-manager -> ict-business-analyst
    innovation-officer            -> innovation-manager

A code that no longer exists is not a cosmetic problem here, because the
vault's `function` facet vocabulary is enforced on write:
`vault.validate_tags` raises for an unknown token and `vault.save_job`
rejects an unknown function id outright. So a stored record still naming
one of the three would stop saving the next time anybody edited it. The
swap has to be atomic in that sense, and this script is the atomic half.

## Why the order of the two steps is the whole design

Every absorbing family above is one of the 37 the v2 list KEEPS, so it is
already in a seeded vault's registry. That is what makes a safe order
possible at all:

  1. rewrite the records (jobs: `function`, `tags`, `values`), which can
     only ever point at a code the registry already holds, and
  2. only then remove the three absorbed entries from the registry.

Done the other way round, every record still holding an absorbed code
would be unsaveable in between. The 24 NEW families are not this
script's business: they enter the registry through the ordinary seed
(`vault.seed_function_facet`, docs/runbooks/seed-function-facet.md),
which adds and updates and never removes -- which is also why removing
the three absorbed ones has to happen here.

## What it rewrites

  * `jobs/*.yaml` -> `function` (the facet-id list the board filters on),
    `tags` (any `function:<code>` token) and `values.occupation_family`
    (the D4 record's own `value`, and every entry of the `ranked` list
    CAREER-129 adds).
  * `tags.yaml` -> the `function` facet's value list.

A record that ends up naming the absorbing family twice keeps it once:
the rewrite is a set operation on a list whose order is the registry's,
not the record's.

NOT REWRITTEN: `data/classification/run_*.yaml`. Those are dated staging
outputs of a run that happened, not records -- rewriting them would make
a past measurement claim it used a vocabulary that did not exist yet.
The next run writes the new codes by itself.

Safety rails, the same ones every `migrate_*` script here follows:
  * dry run by default; nothing is written without `--apply`, and the
    full report is printed first in both modes
  * the vault path comes from `--vault` or `CAREEROS_VAULT`; neither
    means stop, not guess
  * the whole sweep holds `vault.WriteLock`
  * writes go through the vault's own atomic writer, one file at a time,
    so no company rollup and no status history event fires
  * one record's failure is reported and skipped, and a sweep that
    skipped anything exits non-zero
  * idempotent: after a run there is no absorbed code left to find, so a
    second run reports nothing to change
  * the report names records by id, never by title

Usage:
  python scripts/migrate_family_taxonomy_v2.py --vault /path/to/vault
  python scripts/migrate_family_taxonomy_v2.py --vault /path/to/vault --apply
"""
import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careeros import taxonomy, vault  # noqa: E402

#: The absorbed code -> the family that absorbs it (owner decision
#: 2026-11-02). Three, and the list is closed: a family that is merely
#: RENAMED keeps its code, and a family that is added needs no migration,
#: so this mapping is exactly the codes that stop existing.
MERGED = {
    'chief-product-officer': 'product-manager',
    'ict-business-analysis-manager': 'ict-business-analyst',
    'innovation-officer': 'innovation-manager',
}

#: The facet whose vocabulary these codes live in, in a vault.
FACET = 'function'


def check_targets():
    """Every absorbing family exists in the shipped v2 list, or stop.

    Read from the taxonomy rather than trusted: if the list and this
    mapping ever disagree, the migration would rewrite a record onto a
    code nothing accepts, which is the exact breakage it exists to
    prevent. Checked before a vault is opened, so it fails on the wrong
    repository state rather than half-way through a sweep.
    """
    missing = sorted(target for target in set(MERGED.values())
                     if not taxonomy.valid_code('occupation_family', target))
    if missing:
        raise SystemExit('the shipped occupation_family list does not carry the absorbing '
                         f"famil(ies) {', '.join(missing)}; nothing was read or written")
    present = sorted(code for code in MERGED
                     if taxonomy.valid_code('occupation_family', code))
    if present:
        raise SystemExit(f"the shipped occupation_family list still carries {', '.join(present)}, "
                         'so this migration has nothing to migrate away from; nothing was '
                         'read or written')


def rewrite_ids(values):
    """A list of bare facet ids with the absorbed ones rewritten, order
    kept and duplicates folded out."""
    rewritten = [MERGED.get(value, value) if isinstance(value, str) else value
                 for value in values or ()]
    return list(dict.fromkeys(rewritten))


def rewrite_tokens(tokens):
    """The same for `facet:id` tag tokens, touching no other facet."""
    rewritten = []
    for token in tokens or ():
        if isinstance(token, str) and token.startswith(f'{FACET}:'):
            code = token.split(':', 1)[1]
            token = f'{FACET}:{MERGED.get(code, code)}'
        rewritten.append(token)
    return list(dict.fromkeys(rewritten))


def rewrite_record(record):
    """One D4 value record with its family (and every rank) rewritten.

    The record is rebuilt key by key rather than through
    `make_value_record`, on purpose: re-running the factory would stamp
    today's `taxonomy_version` and `classified_at` onto a value that was
    classified under the old list, which would erase the one fact that
    says which vocabulary read the posting. This migration changes the
    CODE and nothing about the reading.
    """
    changed = False
    updated = dict(record)
    value = record.get('value')
    if isinstance(value, str) and value in MERGED:
        updated['value'] = MERGED[value]
        changed = True
    ranked = record.get('ranked')
    if isinstance(ranked, list) and ranked:
        kept, seen = [], set()
        for item in ranked:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            code = item.get('value')
            code = MERGED.get(code, code) if isinstance(code, str) else code
            if code != item.get('value'):
                changed = True
            if code in seen:
                # The absorbed code and its absorber both ranked: one
                # family cannot hold two ranks, so the better rank wins
                # and the ranks below it close up.
                changed = True
                continue
            seen.add(code)
            kept.append(dict(item, value=code, rank=len(kept) + 1))
        if changed:
            updated['ranked'] = kept
    return (updated, True) if changed else (record, False)


def plan_jobs(root):
    """One row per stored job this migration would rewrite."""
    rows = []
    for path in sorted((Path(root) / 'jobs').glob('*.yaml')):
        if path.name.startswith(vault.RESERVED_PREFIX):
            # A reserved id is a number, not a job: nothing to rewrite.
            continue
        job = vault._read(path)
        if not job:
            print(f'  {path.name}: unreadable or empty, skipped', file=sys.stderr)
            continue
        updates, touched = {}, []
        functions = rewrite_ids(job.get('function'))
        if functions != (job.get('function') or []):
            updates['function'] = functions
            touched.append('function')
        tags = rewrite_tokens(job.get('tags'))
        if tags != (job.get('tags') or []):
            updates['tags'] = tags
            touched.append('tags')
        values = job.get('values')
        if isinstance(values, dict):
            record = values.get('occupation_family')
            if isinstance(record, dict):
                rewritten, changed = rewrite_record(record)
                if changed:
                    updates['values'] = dict(values, occupation_family=rewritten)
                    touched.append('values.occupation_family')
        if not updates:
            continue
        rows.append({'id': job.get('id'), 'path': path, 'updates': updates,
                     'fields': touched,
                     'codes': sorted({code for code in MERGED
                                      if _mentions(job, code)})})
    return rows


def _mentions(job, code):
    """Whether one stored job names one absorbed code anywhere this
    migration looks. Used for the report only."""
    if code in (job.get('function') or []):
        return True
    if f'{FACET}:{code}' in (job.get('tags') or []):
        return True
    record = (job.get('values') or {}).get('occupation_family')
    if isinstance(record, dict) and code in taxonomy.ranked_values(record):
        return True
    return False


def plan_registry(root):
    """What the `function` facet's own value list would become, or None
    when it already carries none of the absorbed codes.

    An absorbed entry is REMOVED rather than renamed: its absorber is one
    of the 37 families v2 keeps, so the registry already holds it, and
    renaming would make two entries with one id.
    """
    tags = vault.load_tags(root)
    values = (tags['facets'].get(FACET) or {}).get('values') or []
    dropped = [value for value in values
               if isinstance(value, dict) and value.get('id') in MERGED]
    if not dropped:
        return None
    kept = [value for value in values if value not in dropped]
    return {'tags': tags, 'kept': kept,
            'dropped': sorted(value['id'] for value in dropped),
            'absent_absorbers': sorted({MERGED[value['id']] for value in dropped}
                                       - {value.get('id') for value in kept
                                          if isinstance(value, dict)})}


def write(root, rows, registry):
    """Records first, then the registry. See the module docstring on why
    that order is the whole point."""
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
    if registry is not None and len(written) == len(rows):
        tags = registry['tags']
        tags['facets'][FACET]['values'] = registry['kept']
        vault.save_tags(root, tags)
    elif registry is not None:
        print('  the function facet was NOT changed: some record(s) still name an absorbed '
              'code, and removing the entry under them would make those records unsaveable',
              file=sys.stderr)
    return written


def report(rows, registry, root, apply_changes):
    """Print the whole plan, in both modes, before anything is written."""
    print(f"vault={root}  mode={'APPLY' if apply_changes else 'DRY RUN'}  "
          f"taxonomy={taxonomy.TAXONOMY_VERSION}")
    print('  ' + ', '.join(f'{code} -> {target}' for code, target in sorted(MERGED.items())))
    print('-' * 78)
    if not rows and registry is None:
        print('nothing to change: no record and no registry entry names an absorbed family')
        return
    for row in rows:
        print(f"  {row['id']}: {', '.join(row['fields'])}  ({', '.join(row['codes'])})")
    per_code = Counter(code for row in rows for code in row['codes'])
    print('-' * 78)
    print(f'{len(rows)} record(s) rewritten'
          + (': ' + ', '.join(f'{code}={count}' for code, count in sorted(per_code.items()))
             if per_code else ''))
    if registry is None:
        print('function facet: no absorbed entry to remove')
        return
    print(f"function facet: removing {', '.join(registry['dropped'])}, "
          f"{len(registry['kept'])} entr(ies) left")
    if registry['absent_absorbers']:
        # Not fatal: the registry is seeded separately and the absorber
        # arrives with the next seed run. Said out loud because until it
        # does, a record this migration just rewrote cannot be saved.
        print('  WARNING: the facet does not yet hold '
              + ', '.join(registry['absent_absorbers'])
              + '; run the function-facet seed (docs/runbooks/seed-function-facet.md) '
                'before editing those records')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', help='vault path (default: the CAREEROS_VAULT variable)')
    parser.add_argument('--apply', action='store_true',
                        help='actually write (default: dry run, writes nothing)')
    args = parser.parse_args(argv)

    check_targets()
    given = args.vault or os.environ.get('CAREEROS_VAULT')
    if not given:
        raise SystemExit('no vault given: pass --vault PATH or set CAREEROS_VAULT')
    root = Path(given)
    if not (root / 'jobs').is_dir():
        raise SystemExit(f'{root} does not look like a CareerOS vault (missing jobs/)')

    with vault.WriteLock(root):
        rows = plan_jobs(root)
        registry = plan_registry(root)
        report(rows, registry, root, args.apply)
        if not rows and registry is None:
            return 0
        if not args.apply:
            print('DRY RUN: nothing was written. Re-run with --apply to write.')
            return 0
        written = write(root, rows, registry)
        print(f'wrote {len(written)} record(s)')
        left_rows, left_registry = plan_jobs(root), plan_registry(root)
        if left_rows or left_registry is not None:
            raise SystemExit(f'{len(left_rows)} record(s) and '
                             f"{0 if left_registry is None else len(left_registry['dropped'])} "
                             'registry entr(ies) still name an absorbed family: check the '
                             'vault by hand')
        if len(written) < len(rows):
            raise SystemExit(f"{len(rows) - len(written)} of {len(rows)} planned write(s) "
                             'were skipped (see the errors above)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
