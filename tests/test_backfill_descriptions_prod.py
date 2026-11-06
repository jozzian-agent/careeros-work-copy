"""backfill_descriptions_prod.sh: the guards around one real backfill.

Same idiom as tests/test_import_prod_generation.py: the real script runs
as a subprocess against fixture directories. The vault is a real tmp_path
vault built through careeros.vault/careeros.users, shaped like the
production one after importing generation 2026-11-03 -- jobs with EMPTY
descriptions -- and IMPORT_RELEASE points at this repo so the wrapper
runs the SAME backfill_descriptions.py a promoted release would carry.
Nothing here touches the network, a real credential, the live vault or a
real VPS.

What these tests protect, in the order it would cost:
an apply without a fresh backup, a generation that carries no posting
text (the exact shape of 2026-11-03 -- refused, not silently no-op),
descriptions.yaml the MANIFEST does not vouch for, tampered bytes, a
pipeline generation, and --dry-run writing nothing.
"""
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from careeros import users, vault

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'deploy'
SCRIPT = DEPLOY / 'backfill_descriptions_prod.sh'
GEN = '2026-11-04T090000Z'
PASSWORD = 'correct horse battery staple'

POOL_KEY = 'greenhouse:acme:7001'
POOL_URL = 'https://job-boards.greenhouse.io/acme/jobs/7001'
OWNER_URL = 'https://job-boards.greenhouse.io/acme/jobs/9999'
DESCRIPTION_TEXT = 'Acme is hiring a platform engineer in Zürich.'


# --- the fixtures ----------------------------------------------------------

@pytest.fixture
def prod_vault(tmp_path):
    """A vault shaped like production after the 2026-11-03 import: one
    ownerless imported job with an EMPTY description (the 752-job shape),
    and one job the OWNER holds whose url also appears in the pool, so
    'never touches records with an owner_id' is tested against a real
    collision, not an assumption."""
    root = tmp_path / 'vault'
    (root / 'jobs').mkdir(parents=True)
    user = users.create_user(root, email='owner@example.test', name='Owner',
                             role='admin', password=PASSWORD)
    empty = vault.save_job(root, {
        'title': 'Platform Engineer', 'url': POOL_URL, 'source_id': POOL_KEY,
        'status': 'new', 'origin': 'discovered', 'in_pipeline': False,
        'description': ''})
    mine = vault.save_job(root, {
        'title': 'My own reading of this posting', 'url': OWNER_URL,
        'source_id': 'greenhouse:acme:9999', 'status': 'applied',
        'origin': 'discovered', 'in_pipeline': True,
        'description': '', vault.OWNER_FIELD: user['id']})
    return root, empty, mine


def export_generation(incoming, *, postings=None, complete=GEN,
                      header='# careeros prod-export manifest', tamper=None,
                      descriptions=None, list_descriptions=True):
    """One prod-export generation carrying descriptions.yaml -- the shape
    every export since 2026-11-03 writes. `descriptions=None` writes NO
    descriptions.yaml: the legacy shape (2026-11-03 itself), which this
    wrapper must REFUSE because a backfill without text has nothing to
    give. `tamper` rewrites one payload file WITHOUT updating its digest.
    """
    generation = incoming / GEN
    generation.mkdir(parents=True)
    postings = postings if postings is not None else [
        {'key': POOL_KEY, 'url': POOL_URL}, {'key': 'greenhouse:acme:9999', 'url': OWNER_URL}]
    (generation / 'pool.yaml').write_text(
        yaml.safe_dump({'day': '2026-11-04', 'postings': postings}, allow_unicode=True))
    files = ['pool.yaml']
    lines = [header, 'day: 2026-11-04',
             'source_pool: /fixture/pool.yaml', 'source_run: /fixture/run.yaml',
             f'postings: {len(postings)}']
    if descriptions is not None:
        (generation / 'descriptions.yaml').write_text(
            yaml.safe_dump({'day': '2026-11-04', 'descriptions': descriptions},
                           allow_unicode=True))
        if list_descriptions:
            files.append('descriptions.yaml')
        lines.append(f'descriptions: {len(descriptions)}')
    lines.append('--')
    for relative in files:
        digest = hashlib.sha256((generation / relative).read_bytes()).hexdigest()
        lines.append(f'{digest}  {relative}')
    (generation / 'MANIFEST').write_text('\n'.join(lines) + '\n')
    # AFTER the manifest: a rewrite the digests do not know about.
    if tamper:
        (generation / tamper[0]).write_text(tamper[1])
    if complete is not None:
        (generation / 'COMPLETE').write_text(f'{complete}\n')
    return generation


@pytest.fixture
def backups(tmp_path):
    """A fresh deploy-time vault archive, the shape deploy.sh writes."""
    directory = tmp_path / 'backups'
    directory.mkdir()
    archive = directory / 'vault-20261104T080000Z.tar.gz'
    archive.write_bytes(b'fixture archive bytes')
    return directory


@pytest.fixture
def vps(tmp_path, prod_vault, backups):
    """The wrapper's whole world: incoming/, vault, backups, a release
    that is this repo, and the venv python that has PyYAML."""
    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    root, empty, mine = prod_vault
    release = tmp_path / 'release'
    release.symlink_to(ROOT)

    def run(*args, env=None, script=SCRIPT):
        environment = {
            **os.environ,
            'IMPORT_INCOMING': str(incoming),
            'IMPORT_VAULT': str(root),
            'IMPORT_BACKUP_DIR': str(backups),
            'IMPORT_RELEASE': str(release),
            'IMPORT_PYTHON': sys.executable,
            # Set-but-empty: run the fill as the invoking user, the same
            # escape hatch import_prod_generation.sh has, because a test
            # host has no careeros-prod account.
            'IMPORT_USER': '',
            'DEPLOY_DATA_LOCK': str(tmp_path / 'data.lock'),
            **(env or {}),
        }
        return subprocess.run(['bash', str(script), *args],
                              capture_output=True, text=True, env=environment, timeout=300)

    run.incoming = incoming
    run.root = root
    run.empty = empty
    run.mine = mine
    run.backups = backups
    return run


def read_job(root, job):
    for path in sorted((Path(root) / 'jobs').glob('*.yaml')):
        data = vault._read(path)
        if data and data.get('id') == job['id']:
            return data
    raise AssertionError(f'job {job["id"]} not stored')


# --- the guards: refuse, name the reason, write nothing ---------------------

def test_a_generation_without_descriptions_is_refused(vps):
    """The exact shape of 2026-11-03: pool + classification, no text. A
    backfill against it has nothing to give -- the refusal tells the
    owner to export and upload a fresh generation instead."""
    export_generation(vps.incoming, descriptions=None)
    done = vps(GEN)
    assert done.returncode != 0
    assert 'carries no descriptions.yaml' in done.stdout
    assert 'export and upload a fresh generation' in done.stdout
    assert read_job(vps.root, vps.empty)['description'] == ''


def test_a_missing_complete_marker_is_refused(vps):
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT},
                      complete=None)
    done = vps(GEN)
    assert done.returncode != 0
    assert 'incomplete generation' in done.stdout
    assert read_job(vps.root, vps.empty)['description'] == ''


def test_bytes_that_disagree_with_the_manifest_are_refused(vps):
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT},
                      tamper=('descriptions.yaml', 'day: 2026-11-04\ndescriptions: {}\n'))
    done = vps(GEN)
    assert done.returncode != 0
    assert 'checksum mismatch' in done.stdout
    assert read_job(vps.root, vps.empty)['description'] == ''


def test_an_unlisted_descriptions_file_is_refused(vps):
    """sha256sum -c verifies the files the MANIFEST LISTS, so an unlisted
    descriptions.yaml passes that gate: text nothing vouches for, refused
    by the dedicated guard."""
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT},
                      list_descriptions=False)
    done = vps(GEN)
    assert done.returncode != 0
    assert 'no MANIFEST checksum line' in done.stdout
    assert read_job(vps.root, vps.empty)['description'] == ''


def test_a_pipeline_generation_is_not_this_script_s_business(vps):
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT},
                      header='# careeros pipeline generation manifest')
    done = vps(GEN)
    assert done.returncode != 0
    assert 'not a prod-export generation' in done.stdout
    assert read_job(vps.root, vps.empty)['description'] == ''


def test_apply_without_a_backup_is_refused_with_the_exact_command(vps, tmp_path):
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT})
    done = vps(GEN, env={'IMPORT_BACKUP_DIR': str(tmp_path / 'no-backups')})
    assert done.returncode != 0
    assert 'refusing to apply' in done.stdout
    assert 'tar -czf' in done.stdout, 'the refusal prints the command that makes one'
    assert read_job(vps.root, vps.empty)['description'] == ''


def test_apply_with_a_backup_older_than_the_limit_is_refused(vps):
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT})
    old = vps.backups / 'vault-20261104T080000Z.tar.gz'
    two_hours_ago = datetime.now() - timedelta(hours=2)
    stamp = two_hours_ago.timestamp()
    os.utime(old, (stamp, stamp))
    done = vps(GEN)
    assert done.returncode != 0
    assert 'over the 60-minute limit' in done.stdout
    assert read_job(vps.root, vps.empty)['description'] == ''


def test_dry_run_needs_no_backup_at_all(vps, tmp_path):
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT})
    done = vps(GEN, '--dry-run', env={'IMPORT_BACKUP_DIR': str(tmp_path / 'no-backups')})
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'dry run ok' in done.stdout
    assert read_job(vps.root, vps.empty)['description'] == ''


def test_a_release_without_the_backfill_script_is_refused(vps):
    """A promoted release predating CAREER-131 carries import_pool_to_
    vault.py but not backfill_descriptions.py: the wrapper names the
    missing script rather than dying on a python traceback."""
    release = vps.root.parent / 'old-release'
    (release / 'scripts').mkdir(parents=True)
    (release / 'scripts' / 'import_pool_to_vault.py').write_text('# predates CAREER-131\n')
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT})
    done = vps(GEN, '--dry-run', env={'IMPORT_RELEASE': str(release)})
    assert done.returncode != 0
    assert 'carries no backfill script' in done.stdout


# --- the runs ----------------------------------------------------------------

def test_dry_run_writes_nothing_and_reports_the_counts(vps):
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT})
    before = sorted(str(p.relative_to(vps.root)) for p in vps.root.rglob('*'))
    done = vps(GEN, '--dry-run')
    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(str(p.relative_to(vps.root)) for p in vps.root.rglob('*')) == before
    assert 'matched' in done.stdout and 'would fill' in done.stdout
    assert POOL_KEY in done.stdout, 'the sample names the job it would fill'


def test_apply_fills_the_empty_job_and_stamps_provenance(vps):
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT})
    done = vps(GEN)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'backfill ok' in done.stdout
    filled = read_job(vps.root, vps.empty)
    assert filled['description'] == DESCRIPTION_TEXT
    assert filled['field_provenance']['description'] == 'feed'


def test_the_owner_s_record_is_never_touched(vps):
    """The pool carries the owner's own job key; the fill must skip the
    owned record and leave it byte-identical."""
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT,
                                                  'greenhouse:acme:9999': 'IGNORED'})
    done = vps(GEN)
    assert done.returncode == 0, done.stdout + done.stderr
    mine = read_job(vps.root, vps.mine)
    assert mine['description'] == ''
    assert mine[vault.OWNER_FIELD] == vps.mine[vault.OWNER_FIELD]


def test_a_second_apply_is_a_no_op(vps):
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT})
    assert vps(GEN).returncode == 0
    done = vps(GEN)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'nothing to fill' in done.stdout
    assert read_job(vps.root, vps.empty)['description'] == DESCRIPTION_TEXT


def test_an_unknown_flag_is_a_usage_error(vps):
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT})
    done = vps(GEN, '--nope')
    assert done.returncode == 2
    assert 'usage:' in done.stderr
