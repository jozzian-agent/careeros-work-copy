"""export_jobs_for_prod.py: owner-exclusion, dedupe keys, manifest, dry-run.

Runs against fixture trees only (live-vault probes time out — owner
acceptance rule). The fixture vault holds: one owned job that shadows a
pool posting by source_id, one owned job that shadows another by url,
and one ownerless universe job from an "earlier import" that must also
block its posting (idempotence).
"""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'scripts' / 'export_jobs_for_prod.py'


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
