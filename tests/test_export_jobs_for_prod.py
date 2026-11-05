"""export_jobs_for_prod.py: owner-exclusion, dedupe keys, manifest, dry-run.

Runs against fixture trees only (live-vault probes time out — owner
acceptance rule). The fixture vault holds: one owned job that shadows a
pool posting by source_id, one owned job that shadows another by url,
and one ownerless universe job from an "earlier import" that must also
block its posting (idempotence).
"""
import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from careeros.feeds import store as store_module

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'scripts' / 'export_jobs_for_prod.py'

#: One posting whose frozen snapshot really exists in the fixture store,
#: and the text that snapshot holds.
DESCRIBED_KEY = 'greenhouse:acme:7001'
DESCRIBED_TEXT = 'Acme is hiring a platform engineer in Zürich.'


def make_pool(tmp_path, keys):
    rows = []
    for i, k in enumerate(keys):
        rows.append({'key': k, 'title': f'Title {i}',
                     'url': f'https://example.com/job/{i}',
                     'provider': 'lever', 'tenant': f't{i}'})
    p = {'provider': 'combined', 'day': '2026-11-03', 'postings': rows}
    f = tmp_path / 'pool.yaml'
    f.write_text(yaml.safe_dump(p))
    return f


def make_run(tmp_path, keys):
    rows = [{'key': k, 'title': f'Title {i}', 'values': {}, 'metrics': {},
             'review': {}} for i, k in enumerate(keys)]
    r = {'day': '2026-11-03', 'layer': 'llm', 'postings': rows}
    f = tmp_path / 'run.yaml'
    f.write_text(yaml.safe_dump(r))
    return f


def make_vault(tmp_path, jobs):
    v = tmp_path / 'vault'
    (v / 'jobs').mkdir(parents=True)
    for i, job in enumerate(jobs):
        (v / 'jobs' / f'job-{i}.yaml').write_text(yaml.safe_dump(job))
    return v


def addressed_rows(keys):
    """Pool rows carrying the (tenant, posting_id, content_hash) triple
    the snapshot lookup addresses by, which the plain `make_pool` rows
    deliberately do not: a row the store cannot be asked about is the
    "no description" case and already has its own test above."""
    rows = []
    for i, key in enumerate(keys):
        provider, tenant, posting_id = key.split(':')
        rows.append({'key': key, 'title': f'Title {i}',
                     'url': f'https://example.com/job/{i}',
                     'provider': provider, 'tenant': tenant, 'posting_id': posting_id,
                     'content_hash': chr(ord('a') + i) * 64})
    return rows


def make_addressed_pool(tmp_path, rows):
    f = tmp_path / 'pool.yaml'
    f.write_text(yaml.safe_dump({'provider': 'combined', 'day': '2026-11-03',
                                 'postings': rows}, allow_unicode=True))
    return f


def make_stores(tmp_path, texts):
    """A frozen-snapshot tree under `--stores`, written through
    `store_module` itself so the path the export resolves is the one the
    fetch pipeline writes (same reasoning as tests/test_pool_import.py).

    `texts` is a sequence of `(row, description)` pairs; a row left out
    of it has no snapshot, which is how the "resolved nothing" case is
    built.
    """
    stores = tmp_path / 'stores'
    for row, text in texts:
        store = store_module.Store(stores / row['provider'], provider=row['provider'])
        store.write_snapshot(
            store.posting_snapshot_path(row['tenant'], row['posting_id'], row['content_hash']),
            yaml.safe_dump({'snapshot_id': row['key'], 'content_hash': row['content_hash'],
                            'posting': {'description': text}}, allow_unicode=True))
    stores.mkdir(parents=True, exist_ok=True)
    return stores


def load_export_script():
    """The export script, loaded by path: `scripts/` is not a package.

    `resolve_descriptions` is called DIRECTLY by the duplicate-key tests
    below, because `main()` drops duplicate keys before it ever gets
    there -- the guard exists for the case where that exclusion broke,
    which no pool file can reproduce through the CLI.
    """
    spec = importlib.util.spec_from_file_location('export_jobs_for_prod', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


export_script = load_export_script()


def load_export_script_without_the_duplicate_guard():
    """The same module with the conflict check compiled out, so the
    duplicate tests can show the refusal is the GUARD's and not the
    fixture's doing."""
    source = SCRIPT.read_text()
    patched = source.replace('if key in seen and seen[key] != text:', 'if False:')
    assert patched != source, 'the duplicate guard moved; this patch no longer applies'
    module = ModuleType('export_jobs_for_prod_unguarded')
    module.__file__ = str(SCRIPT)
    exec(compile(patched, str(SCRIPT), 'exec'), module.__dict__)
    return module


def run_script(*args, env_extra=None):
    env = dict(__import__('os').environ)
    env['PYTHONPATH'] = str(REPO / 'vendor' / 'capa-repo') + ':' + str(REPO)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, env=env)


def test_export_excludes_owned_and_keeps_the_rest(tmp_path):
    pool = make_pool(tmp_path, ['lever:a:1', 'lever:a:2', 'lever:a:3', 'lever:a:4'])
    run = make_run(tmp_path, ['lever:a:1', 'lever:a:2', 'lever:a:3', 'lever:a:4'])
    vault = make_vault(tmp_path, [
        {'id': 'j1', 'title': 'owned by source_id', 'owner_id': 'u1',
         'source_id': 'lever:a:1', 'url': 'https://elsewhere.example/x'},
        {'id': 'j2', 'title': 'owned by url', 'owner_id': 'u1',
         'source_id': None, 'url': 'https://example.com/job/1'},
        {'id': 'j3', 'title': 'ownerless universe from earlier import',
         'owner_id': None, 'source_id': 'lever:a:3', 'url': None},
    ])
    out = tmp_path / 'out'
    r = run_script('--pool', pool, '--classification', run,
                   '--vault', vault, '--out', out)
    assert r.returncode == 0, r.stderr
    assert 'postings out:      1' in r.stdout
    assert 'excluded (already in vault, source_id/url): 3' in r.stdout

    staged = yaml.safe_load((out / 'pool.yaml').read_text())
    assert [row['key'] for row in staged['postings']] == ['lever:a:4']
    staged_run = yaml.safe_load((out / 'classification.yaml').read_text())
    assert [row['key'] for row in staged_run['postings']] == ['lever:a:4']

    manifest = (out / 'MANIFEST').read_text()
    assert 'postings: 1' in manifest
    digest = hashlib.sha256((out / 'pool.yaml').read_bytes()).hexdigest()
    assert digest in manifest


def test_dry_run_writes_nothing(tmp_path):
    pool = make_pool(tmp_path, ['lever:a:1'])
    run = make_run(tmp_path, ['lever:a:1'])
    vault = make_vault(tmp_path, [])
    out = tmp_path / 'out'
    r = run_script('--pool', pool, '--classification', run,
                   '--vault', vault, '--out', out, '--dry-run')
    assert r.returncode == 0, r.stderr
    assert 'dry run, nothing written' in r.stdout
    assert not out.exists()
    # Including descriptions.yaml: a rehearsal that wrote the posting
    # text would be a rehearsal that wrote the biggest file of the three.
    assert not (out / 'descriptions.yaml').exists()


def test_refuses_a_non_empty_out_dir(tmp_path):
    pool = make_pool(tmp_path, ['lever:a:1'])
    run = make_run(tmp_path, ['lever:a:1'])
    vault = make_vault(tmp_path, [])
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'stale.yaml').write_text('x')
    r = run_script('--pool', pool, '--classification', run,
                   '--vault', vault, '--out', out)
    assert r.returncode != 0
    assert 'not empty' in r.stderr + r.stdout


def test_unparseable_vault_job_fails_closed(tmp_path):
    pool = make_pool(tmp_path, ['lever:a:1'])
    run = make_run(tmp_path, ['lever:a:1'])
    vault = make_vault(tmp_path, [])
    (vault / 'jobs' / 'broken.yaml').write_text('{{{not yaml')
    out = tmp_path / 'out'
    r = run_script('--pool', pool, '--classification', run,
                   '--vault', vault, '--out', out)
    assert r.returncode != 0
    assert 'does not parse' in r.stderr + r.stdout
    assert not out.exists()


# --- descriptions.yaml: the text the VPS cannot resolve for itself -------

def test_descriptions_are_resolved_for_the_kept_rows(tmp_path):
    """The whole point of the file: the LAN host reads its own frozen
    snapshots and ships the text, because the VPS has no store tree."""
    rows = addressed_rows([DESCRIBED_KEY, 'greenhouse:acme:7002'])
    pool = make_addressed_pool(tmp_path, rows)
    run = make_run(tmp_path, [row['key'] for row in rows])
    stores = make_stores(tmp_path, [(rows[0], DESCRIBED_TEXT)])
    out = tmp_path / 'out'
    r = run_script('--pool', pool, '--classification', run, '--vault',
                   make_vault(tmp_path, []), '--out', out, '--stores', stores)
    assert r.returncode == 0, r.stderr
    assert 'descriptions resolved: 1/2' in r.stdout

    shipped = yaml.safe_load((out / 'descriptions.yaml').read_text())
    assert shipped['day'] == '2026-11-03'
    # Only the row with a snapshot: a row whose text could not be
    # resolved is absent rather than present-and-empty, so the importer's
    # coverage count is a count of real text.
    assert shipped['descriptions'] == {DESCRIBED_KEY: DESCRIBED_TEXT}


def test_the_manifest_covers_descriptions_yaml(tmp_path):
    rows = addressed_rows([DESCRIBED_KEY, 'greenhouse:acme:7002'])
    pool = make_addressed_pool(tmp_path, rows)
    run = make_run(tmp_path, [row['key'] for row in rows])
    stores = make_stores(tmp_path, [(rows[0], DESCRIBED_TEXT)])
    out = tmp_path / 'out'
    r = run_script('--pool', pool, '--classification', run, '--vault',
                   make_vault(tmp_path, []), '--out', out, '--stores', stores)
    assert r.returncode == 0, r.stderr
    manifest = (out / 'MANIFEST').read_text()
    assert 'descriptions: 1' in manifest
    digest = hashlib.sha256((out / 'descriptions.yaml').read_bytes()).hexdigest()
    assert f'{digest}  descriptions.yaml' in manifest
    # Three checksum lines now, which is what push_to_prod.sh requires.
    body = manifest.split('--\n', 1)[1].strip().splitlines()
    assert sorted(line.split()[-1] for line in body) == [
        'classification.yaml', 'descriptions.yaml', 'pool.yaml']


def test_an_excluded_row_ships_no_description(tmp_path):
    """The mapping covers the postings that travel and nothing else: a
    posting the owner already has is not in the generation, so shipping
    its text would be shipping text for a row nobody will import."""
    rows = addressed_rows([DESCRIBED_KEY, 'greenhouse:acme:7002'])
    pool = make_addressed_pool(tmp_path, rows)
    run = make_run(tmp_path, [row['key'] for row in rows])
    stores = make_stores(tmp_path, [(rows[0], DESCRIBED_TEXT),
                                    (rows[1], 'Backend work in Zurich.')])
    vault = make_vault(tmp_path, [{'id': 'j1', 'title': 'owned', 'owner_id': 'u1',
                                   'source_id': DESCRIBED_KEY, 'url': None}])
    out = tmp_path / 'out'
    r = run_script('--pool', pool, '--classification', run,
                   '--vault', vault, '--out', out, '--stores', stores)
    assert r.returncode == 0, r.stderr
    shipped = yaml.safe_load((out / 'descriptions.yaml').read_text())
    assert list(shipped['descriptions']) == ['greenhouse:acme:7002']
    assert 'descriptions: 1' in (out / 'MANIFEST').read_text()


def test_descriptions_yaml_is_written_even_when_nothing_resolved(tmp_path):
    """An empty mapping is an ANSWER (no snapshot found), so the file is
    still written: push_to_prod.sh can then require it unconditionally
    and the import report turns the emptiness into a loud warning rather
    than the generation looking broken."""
    rows = addressed_rows([DESCRIBED_KEY])
    pool = make_addressed_pool(tmp_path, rows)
    run = make_run(tmp_path, [row['key'] for row in rows])
    stores = make_stores(tmp_path, [])
    out = tmp_path / 'out'
    r = run_script('--pool', pool, '--classification', run, '--vault',
                   make_vault(tmp_path, []), '--out', out, '--stores', stores)
    assert r.returncode == 0, r.stderr
    assert 'descriptions resolved: 0/1' in r.stdout
    shipped = yaml.safe_load((out / 'descriptions.yaml').read_text())
    assert shipped['descriptions'] == {}
    manifest = (out / 'MANIFEST').read_text()
    assert 'descriptions: 0' in manifest
    digest = hashlib.sha256((out / 'descriptions.yaml').read_bytes()).hexdigest()
    assert f'{digest}  descriptions.yaml' in manifest


def duplicate_rows():
    """Two rows under ONE pool key, addressing two DIFFERENT snapshots
    (`addressed_rows` gives them different content_hash values). This is
    what reaching `resolve_descriptions` with a duplicate looks like once
    the dedupe pass has failed to hold."""
    rows = addressed_rows([DESCRIBED_KEY, DESCRIBED_KEY])
    assert rows[0]['content_hash'] != rows[1]['content_hash']
    return rows


def test_a_duplicate_key_with_conflicting_text_aborts_the_export(tmp_path):
    """A data-integrity error and not a warning: the two rows resolve two
    different postings' text under one key, so shipping either one is a
    coin flip over what prod shows. The exporter already excludes
    duplicates; a conflicting one arriving here means that exclusion
    broke, which is not a thing to paper over."""
    rows = duplicate_rows()
    stores = make_stores(tmp_path, [(rows[0], DESCRIBED_TEXT),
                                    (rows[1], 'A different posting entirely, longer.')])
    with pytest.raises(SystemExit) as refusal:
        export_script.resolve_descriptions(rows, str(stores))
    assert DESCRIBED_KEY in str(refusal.value)
    assert 'appears more than once with different posting text' in str(refusal.value)


def test_a_duplicate_key_resolving_text_on_only_one_row_aborts_too(tmp_path):
    """"No text" is an answer about this key as much as text is, so empty
    against non-empty is a conflict: picking the row with text would be
    picking a snapshot, and picking the one without would drop a
    description that exists."""
    rows = duplicate_rows()
    stores = make_stores(tmp_path, [(rows[1], DESCRIBED_TEXT)])   # row 0 has no snapshot
    with pytest.raises(SystemExit) as refusal:
        export_script.resolve_descriptions(rows, str(stores))
    assert DESCRIBED_KEY in str(refusal.value)


def test_a_duplicate_key_with_identical_text_is_one_entry_and_no_error(tmp_path):
    """The harmless shape of the same bug: both rows resolve the SAME
    text, so there is nothing to choose between and nothing to refuse --
    the repeat is ignored and the mapping carries one entry."""
    rows = duplicate_rows()
    stores = make_stores(tmp_path, [(rows[0], DESCRIBED_TEXT),
                                    (rows[1], DESCRIBED_TEXT)])
    assert export_script.resolve_descriptions(rows, str(stores)) == {
        DESCRIBED_KEY: DESCRIBED_TEXT}


def test_a_duplicate_key_resolving_nothing_twice_is_no_error(tmp_path):
    """Two rows, no snapshot for either: one agreed answer ("no text"),
    so the key is simply absent from the mapping."""
    rows = duplicate_rows()
    assert export_script.resolve_descriptions(
        rows, str(make_stores(tmp_path, []))) == {}


def test_the_duplicate_guard_is_what_aborts_and_not_the_fixture(tmp_path):
    """Non-vacuous half: with the conflict check compiled out, the SAME
    fixture resolves without complaint -- and to whichever row happened
    to come last, which is precisely the coin flip the guard refuses."""
    rows = duplicate_rows()
    other = 'A different posting entirely, longer.'
    stores = make_stores(tmp_path, [(rows[0], DESCRIBED_TEXT), (rows[1], other)])
    unguarded = load_export_script_without_the_duplicate_guard()
    assert unguarded.resolve_descriptions(rows, str(stores)) == {DESCRIBED_KEY: other}
    assert unguarded.resolve_descriptions(list(reversed(rows)), str(stores)) == {
        DESCRIBED_KEY: DESCRIBED_TEXT}


def test_a_pool_file_with_a_conflicting_duplicate_key_aborts_the_cli(tmp_path):
    """Through the real CLI, because `excluded_dup` counts postings the
    VAULT already holds and not repeats inside the pool file: a pool that
    names one key twice reaches the resolver twice, and the export stops
    there with nothing staged."""
    rows = addressed_rows([DESCRIBED_KEY, DESCRIBED_KEY])
    pool = make_addressed_pool(tmp_path, rows)
    run = make_run(tmp_path, [DESCRIBED_KEY])
    stores = make_stores(tmp_path, [(rows[0], DESCRIBED_TEXT),
                                    (rows[1], 'A different posting entirely.')])
    out = tmp_path / 'out'
    r = run_script('--pool', pool, '--classification', run, '--vault',
                   make_vault(tmp_path, []), '--out', out, '--stores', stores)
    assert r.returncode != 0
    assert DESCRIBED_KEY in r.stderr
    assert 'appears more than once with different posting text' in r.stderr
    # Resolution happens before anything is written, so there is no
    # half-staged generation for push_to_prod.sh to find.
    assert not out.exists()


def test_a_pool_file_repeating_a_key_with_the_same_text_still_exports(tmp_path):
    """The agreed-answer case through the CLI: both rows resolve the same
    text, the generation is staged, and descriptions.yaml carries one
    entry for the key."""
    rows = addressed_rows([DESCRIBED_KEY, DESCRIBED_KEY])
    pool = make_addressed_pool(tmp_path, rows)
    run = make_run(tmp_path, [DESCRIBED_KEY])
    stores = make_stores(tmp_path, [(rows[0], DESCRIBED_TEXT),
                                    (rows[1], DESCRIBED_TEXT)])
    out = tmp_path / 'out'
    r = run_script('--pool', pool, '--classification', run, '--vault',
                   make_vault(tmp_path, []), '--out', out, '--stores', stores)
    assert r.returncode == 0, r.stderr + r.stdout
    assert 'descriptions resolved: 1/2' in r.stdout
    shipped = yaml.safe_load((out / 'descriptions.yaml').read_text())
    assert shipped['descriptions'] == {DESCRIBED_KEY: DESCRIBED_TEXT}


def test_a_pool_the_stores_cannot_be_asked_about_still_exports(tmp_path):
    """The default-roots path, unchanged: rows with no snapshot
    addressing resolve nothing and the generation is still complete."""
    pool = make_pool(tmp_path, ['lever:a:1'])
    run = make_run(tmp_path, ['lever:a:1'])
    out = tmp_path / 'out'
    r = run_script('--pool', pool, '--classification', run, '--vault',
                   make_vault(tmp_path, []), '--out', out)
    assert r.returncode == 0, r.stderr
    assert yaml.safe_load((out / 'descriptions.yaml').read_text())['descriptions'] == {}


def test_vault_never_written(tmp_path):
    pool = make_pool(tmp_path, ['lever:a:1', 'lever:a:2'])
    run = make_run(tmp_path, ['lever:a:1', 'lever:a:2'])
    vault = make_vault(tmp_path, [{'id': 'j1', 'owner_id': 'u1',
                                   'source_id': 'lever:a:1'}])
    before = sorted(p.name for p in vault.rglob('*'))
    out = tmp_path / 'out'
    r = run_script('--pool', pool, '--classification', run,
                   '--vault', vault, '--out', out)
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in vault.rglob('*')) == before
