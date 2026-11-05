"""Export classified pool postings as ownerless universe jobs for prod (owner decision 2026-11-04).

WHY THIS EXISTS
  `scripts/import_pool_to_vault.py` imports a pool + classification pair
  into a vault, and that vault is expected to be the WHOLE picture: it
  dedupes by `source_id` and by url against every stored job, and it
  writes company records into the shared vault. Running it against a
  tree staged on the LAN host would need the production vault's job and
  company indexes locally -- which is exactly the owner data the vault
  sync deliberately never ships (see deploy/sync_vault_to_prod.sh,
  "`jobs/` is NOT in it ... Splitting it needs a content-aware export
  that does not exist yet"). THIS is that content-aware export, the
  first half; the import half runs on the VPS, against the real vault,
  where the dedupe indexes are complete.

WHAT IT WRITES
  One directory, shaped so `deploy/promote_incoming.sh`'s manifest
  checks and a VPS-side import can consume it without knowing about the
  LAN host:

    <out>/pool.yaml            a copy of the day's pool export rows that
                               survived the owner filter (see below)
    <out>/classification.yaml  the matching slice of the run file
    <out>/descriptions.yaml    pool key -> posting text, resolved here
                               because the frozen ATS snapshots this
                               reads exist ONLY on the LAN host; the
                               VPS-side import takes it with
                               --descriptions instead of --stores
    <out>/MANIFEST             sha256 of every file + row counts, the
                               same shape sync_vault_to_prod.sh writes

  descriptions.yaml is written even when no snapshot resolved (an empty
  mapping), so push_to_prod.sh can require the file unconditionally and
  a coverage problem is visible in the import report rather than
  expressed as a missing file.

  The pool export never carries an `owner_id` field at all (confirmed:
  0 of 797 rows in golden_set_pool_2026-11-03.yaml have one) -- the
  pool is feed data, ownerless by construction, and ownership only
  exists inside vault job records. So "only postings without an
  owner_id" is enforced HERE against the owner's live vault: a posting
  whose `key` matches the `source_id` of a stored job, or whose
  normalized url matches any stored job's url, is EXCLUDED from the
  export. That is the same two dedupe keys import_pool_to_vault.py
  applies at import time (its docstring, "Idempotence"); applying them
  at export time means the staged tree provably holds no posting that
  shadows an owned record, and the VPS-side import re-checks anyway
  (its indexes are the authoritative ones).

WHAT IT NEVER DOES
  * It writes nothing outside <out> (a fresh directory; refuses to run
    into a non-empty one).
  * It reads the vault but never writes it.
  * It sends nothing anywhere. The upload is a separate, manual step
    (deploy/push_to_prod.sh) the owner starts.

USAGE
  python scripts/export_jobs_for_prod.py \
      --pool data/ats/exports/golden_set_pool_2026-11-03.yaml \
      --classification data/classification/run_2026-11-03.yaml \
      --vault /path/to/the/owners/vault \
      --out /tmp/careeros-prod-export/2026-11-03

  --dry-run prints the counts and the sample and writes nothing.
"""
import argparse
import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from org_intake.url import normalize_url  # noqa: E402

#: The importer's own description resolution, loaded by path because
#: `scripts/` is not a package. The frozen-snapshot lookup
#: (`description_for`) and its store-root rule (`store_root`) are that
#: module's, so this export resolves exactly the text the LAN-side
#: import would have written -- one reading of "which snapshot belongs
#: to which pool row", not two that can drift.
_IMPORTER_PATH = Path(__file__).resolve().parent / 'import_pool_to_vault.py'
_spec = importlib.util.spec_from_file_location('_import_pool_to_vault', _IMPORTER_PATH)
_importer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_importer)

#: Same default as import_pool_to_vault.py: a stored job whose
#: `source_id` equals the pool key is the same posting.
SOURCE_ID_FIELD = 'source_id'
OWNER_FIELD = 'owner_id'

#: The name the generation carries the resolved posting text under, and
#: the one push_to_prod.sh requires and import_prod_generation.sh passes
#: to the importer's --descriptions.
DESCRIPTIONS_NAME = 'descriptions.yaml'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def vault_blocked_keys(vault_root):
    """The two dedupe indexes, read off the stored jobs.

    Returns (source_ids, normalized_urls) of every stored job, owned or
    not: a universe job already imported by an earlier run blocks its
    posting too, which is what makes a second export+import a no-op
    rather than a duplicate.
    """
    root = Path(vault_root)
    jobs_dir = root / 'jobs'
    source_ids = set()
    urls = set()
    if not jobs_dir.is_dir():
        return source_ids, urls
    for f in jobs_dir.iterdir():
        if f.suffix not in ('.yaml', '.yml'):
            continue
        try:
            rec = yaml.safe_load(f.read_text())
        except yaml.YAMLError:
            # An unreadable job file must fail CLOSED: we cannot prove
            # this record does not shadow a posting, so we do not export
            # anything that night. Import is allowed to be optimistic
            # because it runs where the truth lives; export is not.
            raise SystemExit(f'export aborted: {f} does not parse as YAML')
        if not isinstance(rec, dict):
            continue
        sid = rec.get(SOURCE_ID_FIELD)
        if sid:
            source_ids.add(str(sid))
        for field in ('url', 'normalized_url'):
            u = rec.get(field)
            if u:
                urls.add(normalize_url(str(u)))
    return source_ids, urls


def resolve_descriptions(rows, base=None):
    """`key -> posting text` for the kept rows, out of the LAN snapshots.

    Runs HERE and not on the VPS because the frozen snapshots
    (data/ats/<provider>, data/personio) exist only on the LAN host --
    `deploy/sync_vault_to_prod.sh` and this export both ship data, never
    the store trees. A row whose snapshot is missing, unreadable or
    holds no text simply does not appear in the mapping; the importer
    counts it as "descriptions missing" exactly as it does today.

    `--stores` (default: the repo-relative store roots the importer
    already uses) points the lookup at a fixture tree in tests.

    A pool key must appear once. `excluded_dup` above counts postings
    the VAULT already holds, not repeats inside the pool file, so a key
    that appears twice in the pool reaches this loop twice -- and if the
    two rows address different snapshots, shipping either text is a coin
    flip over which posting prod ends up showing. That aborts the export:
    a pool export with a repeated key is broken upstream and quietly
    picking a winner would hide it. Two rows resolving the SAME text is
    the harmless shape of the same bug and is ignored, because there is
    nothing to choose between.
    """
    stores = {}
    seen = {}
    resolved = {}
    for row in rows:
        key = row['key']
        text = _importer.description_for(row, stores, base, warn=None)
        # `seen` and not `resolved`: a row that resolved NO text is still
        # a reading of this key, so "" vs real text is a conflict too --
        # tracking only the non-empty answers would let the empty one
        # through unnoticed.
        if key in seen and seen[key] != text:
            raise SystemExit(
                f'export aborted: pool key {key} appears more than once with different '
                f'posting text ({len(seen[key])} vs {len(text)} characters); the '
                f'duplicate exclusion did not hold and choosing one of the two snapshots '
                f'would be a guess')
        seen[key] = text
        if text:
            resolved[key] = text
    return resolved


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--pool', required=True, help='the golden-set pool export YAML')
    ap.add_argument('--classification', required=True, help='the run_*.yaml classification file')
    ap.add_argument('--vault', required=True, help='vault to check ownership against (read-only)')
    ap.add_argument('--out', required=True, help='fresh directory to stage into')
    ap.add_argument('--stores', default=None,
                    help='base directory holding the per-provider staging stores '
                         '(default: data/ats/<provider>, data/personio)')
    ap.add_argument('--dry-run', action='store_true', help='print counts and write nothing')
    args = ap.parse_args(argv)

    pool = yaml.safe_load(Path(args.pool).read_text())
    run = yaml.safe_load(Path(args.classification).read_text())
    pool_rows = pool.get('postings') or []
    run_rows = {r['key']: r for r in (run.get('postings') or [])}

    source_ids, urls = vault_blocked_keys(args.vault)

    kept, excluded_owned, excluded_dup = [], 0, 0
    for row in pool_rows:
        key = row.get('key')
        if key in source_ids:
            excluded_dup += 1
            continue
        nu = normalize_url(str(row.get('url') or ''))
        if nu and nu in urls:
            excluded_dup += 1
            continue
        if row.get(OWNER_FIELD) is not None:
            # Cannot happen with today's exporter (the pool carries no
            # owner_id); kept as a belt-and-braces check so a future
            # pool format that grows the field cannot leak owner data.
            excluded_owned += 1
            continue
        if key in run_rows:
            kept.append(row)

    out = Path(args.out)
    print(f'-- export for prod from {args.pool}')
    print(f'   pool rows in:        {len(pool_rows)}')
    print(f'   excluded (already in vault, source_id/url): {excluded_dup}')
    print(f'   excluded (carries owner_id):                {excluded_owned}')
    print(f'   excluded (no classification row):           '
          f'{len(pool_rows) - excluded_dup - excluded_owned - len(kept)}')
    print(f'   postings out:      {len(kept)}')
    descriptions = resolve_descriptions(kept, args.stores)
    print(f'   descriptions resolved: {len(descriptions)}/{len(kept)}')
    print('-- sample (first 5):')
    for row in kept[:5]:
        fam = (run_rows[row['key']].get('values') or {}).get('occupation_family') or '?'
        print(f'   {row["key"]}  {row["title"][:60]!r}  family={fam}')

    if args.dry_run:
        print('-- dry run, nothing written')
        return 0
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'{out} exists and is not empty; refusing to mix generations')
    out.mkdir(parents=True, exist_ok=True)

    pool_out = dict(pool)
    pool_out['postings'] = kept
    (out / 'pool.yaml').write_text(
        yaml.safe_dump(pool_out, sort_keys=False, allow_unicode=True))
    run_out = dict(run)
    run_out['postings'] = [run_rows[r['key']] for r in kept]
    (out / 'classification.yaml').write_text(
        yaml.safe_dump(run_out, sort_keys=False, allow_unicode=True))
    # Written even when empty: push_to_prod.sh requires the file, and an
    # empty mapping is an ANSWER (no snapshot resolved) the import report
    # turns into a loud coverage warning -- a missing file would just be
    # a broken generation.
    (out / DESCRIPTIONS_NAME).write_text(yaml.safe_dump(
        {'day': pool.get('day'), 'descriptions': descriptions},
        sort_keys=False, allow_unicode=True))

    lines = ['# careeros prod-export manifest',
             f'day: {pool.get("day")}',
             f'source_pool: {args.pool}',
             f'source_run: {args.classification}',
             f'postings: {len(kept)}',
             f'descriptions: {len(descriptions)}',
             '--']
    for name in ('pool.yaml', 'classification.yaml', DESCRIPTIONS_NAME):
        lines.append(f'{sha256(out / name)}  {name}')
    (out / 'MANIFEST').write_text('\n'.join(lines) + '\n')
    print(f'-- staged {out}: {len(kept)} postings, {len(descriptions)} descriptions + MANIFEST')
    return 0


if __name__ == '__main__':
    sys.exit(main())
