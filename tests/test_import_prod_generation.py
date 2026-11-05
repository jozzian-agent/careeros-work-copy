"""import_prod_generation.sh: the guards around one real import.

Same idiom as the rest of this file's neighbours: the real script runs as
a subprocess against fixture directories. The vault is a real tmp_path
vault built through `careeros.vault`/`careeros.users`, the generation is
a real prod-export-shaped upload (the shape verified against
data/prod-export/2026-11-03/), and IMPORT_RELEASE points at this repo so
the wrapper runs the SAME import_pool_to_vault.py a promoted release
would carry. Nothing here touches the network, a real credential, the
live vault or a real VPS.

What these tests protect, in the order it would cost:
an apply without a fresh backup, a generation whose bytes are not the
ones its MANIFEST vouches for, a pipeline generation being imported as
if it were an export one, and --dry-run writing nothing.
"""
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from careeros import users, vault

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'deploy'
SCRIPT = DEPLOY / 'import_prod_generation.sh'
GEN = '2026-11-03T165340Z'

POOL_KEY = 'greenhouse:acme:7001'
POOL_URL = 'https://job-boards.greenhouse.io/acme/jobs/7001'
OWNER_URL = 'https://job-boards.greenhouse.io/acme/jobs/9999'
PASSWORD = 'correct horse battery staple'
#: The posting text a generation carries in descriptions.yaml, resolved on
#: the LAN host from the frozen snapshot this VPS-shaped fixture has none of.
DESCRIPTION_TEXT = 'Acme is hiring a platform engineer in Zürich.'


# --- the fixtures ----------------------------------------------------------

@pytest.fixture
def prod_vault(tmp_path):
    """A production-shaped vault: one user, and one job THEY own whose url
    also appears in the pool export, so 'never touches records with an
    owner_id' is tested against a real collision, not an assumption."""
    root = tmp_path / 'vault'
    (root / 'jobs').mkdir(parents=True)
    user = users.create_user(root, email='owner@example.test', name='Owner',
                             role='admin', password=PASSWORD)
    mine = vault.save_job(root, {
        'title': 'My own reading of this posting', 'url': OWNER_URL,
        'status': 'applied', 'description': 'The owner wrote this.',
        vault.OWNER_FIELD: user['id']})
    return root, mine


def export_generation(incoming, *, postings=None, classified=None, complete=GEN,
                      header='# careeros prod-export manifest', tamper=None,
                      descriptions=None, list_descriptions=True):
    """One prod-export generation, written the way export_jobs_for_prod.py
    writes it: MANIFEST header + counts + `--` + sha256 lines, COMPLETE
    last. `tamper` rewrites one payload file WITHOUT updating its digest:
    the bytes-and-manifest disagreement the checksum gate exists for.

    `descriptions` is the `key -> text` mapping descriptions.yaml
    carries; None writes NO descriptions.yaml, which is a generation
    exported before the file existed -- the legacy shape this wrapper
    still has to import.

    `list_descriptions=False` writes the file but leaves it OUT of the
    checksum section: `sha256sum -c` verifies the lines a manifest HAS,
    so an unlisted payload passes that gate without being vouched for by
    anything, which is its own guard.
    """
    generation = incoming / GEN
    generation.mkdir(parents=True)
    postings = postings if postings is not None else [pool_posting(POOL_KEY, POOL_URL),
                                                      pool_posting('greenhouse:acme:9999', OWNER_URL)]
    classified = classified if classified is not None else [classified_row(POOL_KEY)]
    (generation / 'pool.yaml').write_text(
        yaml.safe_dump({'day': '2026-11-03', 'postings': postings}, allow_unicode=True))
    (generation / 'classification.yaml').write_text(
        yaml.safe_dump({'day': '2026-11-03', 'postings': classified}, allow_unicode=True))
    files = ['pool.yaml', 'classification.yaml']
    lines = [header, 'day: 2026-11-03',
             'source_pool: /fixture/pool.yaml', 'source_run: /fixture/run.yaml',
             f'postings: {len(postings)}']
    if descriptions is not None:
        (generation / 'descriptions.yaml').write_text(
            yaml.safe_dump({'day': '2026-11-03', 'descriptions': descriptions},
                           allow_unicode=True))
        if list_descriptions:
            files.append('descriptions.yaml')
        lines.append(f'descriptions: {len(descriptions)}')
    lines.append('--')
    for relative in files:
        digest = hashlib.sha256((generation / relative).read_bytes()).hexdigest()
        lines.append(f'{digest}  {relative}')
    (generation / 'MANIFEST').write_text('\n'.join(lines) + '\n')
    # AFTER the manifest: a rewrite the digests do not know about, which is
    # the only shape the checksum gate can be tested against.
    if tamper:
        (generation / tamper[0]).write_text(tamper[1])
    if complete is not None:
        (generation / 'COMPLETE').write_text(f'{complete}\n')
    return generation


def pool_posting(key, url, **extra):
    return {'key': key, 'url': url, 'content_hash': 'a' * 64,
            'provider': 'greenhouse', 'tenant': 'acme', 'posting_id': key.rsplit(':', 1)[-1],
            'company': 'Acme Industries AG', 'title': extra.pop('title', 'Platform Engineer'),
            'municipality_label': 'Zürich',
            'published_at': '2026-10-15T17:05:29.750+00:00', 'has_salary': False,
            **extra}


def classified_row(key):
    """One classification row, family record carrying the CAREER-129
    `ranked` list: the top-3 half the brief asks to be confirmed as
    arriving on the imported job."""
    from careeros import taxonomy
    return {'key': key,
            'values': {
                'language': taxonomy.make_value_record('language', 'en', 'feed',
                                                       confidence=0.9),
                'occupation_family': taxonomy.make_value_record(
                    'occupation_family', 'software-engineer', 'llm', confidence=0.95,
                    ranked=[{'value': 'software-engineer', 'rank': 1,
                             'source': 'llm', 'confidence': 0.95},
                            {'value': 'software-developer', 'rank': 2,
                             'source': 'llm', 'confidence': None}]),
            },
            'salary': None}


@pytest.fixture
def backups(tmp_path):
    """A fresh deploy-time vault archive, the shape deploy.sh writes."""
    directory = tmp_path / 'backups'
    directory.mkdir()
    archive = directory / 'vault-20261103T170000Z.tar.gz'
    archive.write_bytes(b'fixture archive bytes')
    return directory


@pytest.fixture
def vps(tmp_path, prod_vault, backups):
    """The wrapper's whole world: incoming/, vault, backups, a release
    that is this repo, and the venv python that has PyYAML."""
    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    root, mine = prod_vault
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
            # Set-but-empty: run the import as the invoking user, the same
            # escape hatch promote_incoming.sh's DEPLOY_OWNER has, because
            # a test host has no careeros-prod account.
            'IMPORT_USER': '',
            'DEPLOY_DATA_LOCK': str(tmp_path / 'data.lock'),
            **(env or {}),
        }
        # `script` names the file to run: a test that has to prove a
        # guard is load-bearing runs a COPY with that one line removed,
        # which is the only way to show the refusal came from the guard.
        return subprocess.run(['bash', str(script), *args],
                              capture_output=True, text=True, env=environment, timeout=300)

    run.incoming = incoming
    run.root = root
    run.mine = mine
    run.backups = backups
    return run


# --- the guards: refuse, name the reason, write nothing ---------------------

def test_a_missing_complete_marker_is_refused_before_anything_is_read(vps):
    export_generation(vps.incoming, complete=None)
    done = vps(GEN)
    assert done.returncode != 0
    assert 'incomplete generation' in done.stdout
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


def test_bytes_that_disagree_with_the_manifest_are_refused(vps):
    """The checksum gate: a file rewritten after the export, MANIFEST not
    updated. sha256sum -c is what catches it, and nothing is imported."""
    export_generation(vps.incoming, tamper=('pool.yaml', 'day: 2026-11-03\npostings: []\n'))
    done = vps(GEN)
    assert done.returncode != 0
    assert 'checksum mismatch' in done.stdout
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


def test_a_complete_marker_naming_another_generation_is_refused(vps):
    export_generation(vps.incoming, complete='2099-01-01T000000Z')
    done = vps(GEN)
    assert done.returncode != 0
    assert 'does not name this generation' in done.stdout


def test_a_pipeline_generation_is_not_this_script_s_business(vps):
    """sync_vault_to_prod.sh's uploads land in the same incoming/. Their
    MANIFEST header is the one distinction that cannot be faked by a
    filename, and importing one would mean vault writes from bytes in a
    layout this path never validated."""
    export_generation(vps.incoming, header='# careeros pipeline generation manifest')
    done = vps(GEN)
    assert done.returncode != 0
    assert 'not a prod-export generation' in done.stdout
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


def test_apply_without_a_backup_is_refused_with_the_exact_command(vps, tmp_path):
    export_generation(vps.incoming)
    done = vps(GEN, env={'IMPORT_BACKUP_DIR': str(tmp_path / 'no-backups')})
    assert done.returncode != 0
    assert 'refusing to apply' in done.stdout
    assert 'tar -czf' in done.stdout, 'the refusal prints the command that makes one'
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


def test_apply_with_a_backup_older_than_the_limit_is_refused(vps):
    export_generation(vps.incoming)
    old = vps.backups / 'vault-20261103T170000Z.tar.gz'
    two_hours_ago = datetime.now() - timedelta(hours=2)
    stamp = two_hours_ago.timestamp()
    os.utime(old, (stamp, stamp))
    done = vps(GEN)
    assert done.returncode != 0
    assert 'over the 60-minute limit' in done.stdout
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


def test_dry_run_needs_no_backup_at_all(vps, tmp_path):
    """A rehearsal must be runnable the moment an upload lands; gating it
    on a backup would mean taking a backup to look at a dry run."""
    export_generation(vps.incoming)
    done = vps(GEN, '--dry-run', env={'IMPORT_BACKUP_DIR': str(tmp_path / 'no-backups')})
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'DRY RUN: nothing was written' in done.stdout
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


# --- dry-run writes nothing, and says what it would write -------------------

def test_dry_run_writes_nothing_and_shows_the_sample(vps):
    export_generation(vps.incoming)
    before = sorted(str(p.relative_to(vps.root)) for p in vps.root.rglob('*'))
    done = vps(GEN, '--dry-run')
    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(str(p.relative_to(vps.root)) for p in vps.root.rglob('*')) == before
    # The counts the brief names, plus the 5-row sample (one row here: the
    # second posting duplicates the owner's url and is skipped).
    assert 'imported:' in done.stdout
    assert 'skipped-duplicate:' in done.stdout
    assert 'sample (first 1):' in done.stdout
    assert POOL_KEY in done.stdout
    assert 'family=software-engineer' in done.stdout, 'the sample shows the coded family'


# --- the apply: what lands, and what is never touched -----------------------

def test_apply_imports_the_posting_with_its_classification(vps):
    export_generation(vps.incoming)
    done = vps(GEN)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'import ok' in done.stdout
    jobs = [job for job in vault.list_owned_jobs(vps.root) if job.get('source_id') == POOL_KEY]
    assert len(jobs) == 1
    job = jobs[0]
    assert job[vault.OWNER_FIELD] is None and job['in_pipeline'] is False
    # The classified half arrived WITH the job: the family record carries
    # its ranked top-3 through vault.validate_value_records untouched.
    family = job['values']['occupation_family']
    assert family['value'] == 'software-engineer'
    assert [entry['value'] for entry in family['ranked']] == \
        ['software-engineer', 'software-developer']
    assert job['values']['language']['value'] == 'en'


def test_the_owner_s_record_is_never_touched(vps):
    """The pool carries a posting whose url the owner already has as their
    own job. The import skips it and their record survives byte-identical:
    same owner, same status, same text."""
    export_generation(vps.incoming)
    before = vault.load_job(vps.root, vps.mine['id'])
    done = vps(GEN)
    assert done.returncode == 0, done.stdout + done.stderr
    assert vault.load_job(vps.root, vps.mine['id']) == before
    assert [job['url'] for job in vault.list_owned_jobs(vps.root)].count(OWNER_URL) == 1


def test_a_second_apply_imports_nothing_again(vps):
    """A re-run is a skip report, not a second copy of the universe. The
    generation stays in incoming/ after the first import (an input, not a
    release), so re-running it is a real scenario, not a hypothetical."""
    export_generation(vps.incoming)
    assert vps(GEN).returncode == 0
    done = vps(GEN)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'imported:                 0' in done.stdout
    assert 'skipped-duplicate:' in done.stdout
    keys = [job.get('source_id') for job in vault.list_owned_jobs(vps.root)]
    assert keys.count(POOL_KEY) == 1


# --- the posting text, which only the generation can carry ------------------

def test_a_generation_carrying_descriptions_imports_the_posting_text(vps):
    """The fix this path exists for: the text was resolved on the LAN
    host (no ATS snapshot exists here) and travels as data, so an
    imported job is not a title with an empty body."""
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT})
    done = vps(GEN)
    assert done.returncode == 0, done.stdout + done.stderr
    # The coverage line names the file the wrapper handed to
    # --descriptions, which is the generation's own.
    assert 'description coverage:     1/1 postings to import (100%)' in done.stdout
    assert f'{GEN}/descriptions.yaml' in done.stdout
    job = next(job for job in vault.list_owned_jobs(vps.root)
               if job.get('source_id') == POOL_KEY)
    assert job['description'] == DESCRIPTION_TEXT


def test_a_generation_without_descriptions_is_still_importable(vps):
    """A generation exported before descriptions.yaml existed: no
    --descriptions flag, no coverage gate, and the honest
    no-description import it always was."""
    export_generation(vps.incoming)
    done = vps(GEN)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'import ok' in done.stdout
    assert 'description coverage:' not in done.stdout
    job = next(job for job in vault.list_owned_jobs(vps.root)
               if job.get('source_id') == POOL_KEY)
    assert job['description'] == ''


def test_an_apply_below_the_coverage_floor_is_refused(vps):
    """descriptions.yaml that resolved nothing is a broken export, not a
    reason to fill prod with empty bodies. The import script refuses and
    the wrapper reports its exit; the vault is untouched."""
    export_generation(vps.incoming, descriptions={})
    done = vps(GEN)
    assert done.returncode != 0
    assert 'LOW DESCRIPTION COVERAGE' in done.stderr
    assert 'refusing to APPLY' in done.stderr
    assert 'the import script exited 1' in done.stdout
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


def test_allow_low_descriptions_is_passed_through_to_the_import(vps):
    """The owner's explicit override, on this script as well as the
    import script -- the refusal above names it, so it has to work."""
    export_generation(vps.incoming, descriptions={})
    done = vps(GEN, '--allow-low-descriptions')
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'import ok' in done.stdout
    job = next(job for job in vault.list_owned_jobs(vps.root)
               if job.get('source_id') == POOL_KEY)
    assert job['description'] == ''


def test_a_dry_run_reports_low_coverage_and_still_completes(vps):
    """A rehearsal never refuses: it is how the owner finds out before
    deciding, so it needs no override flag."""
    export_generation(vps.incoming, descriptions={})
    done = vps(GEN, '--dry-run')
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'LOW DESCRIPTION COVERAGE' in done.stderr
    assert 'DRY RUN: nothing was written' in done.stdout
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


@pytest.mark.parametrize('flags', [('--allow-low-descriptions', '--dry-run'),
                                   ('--dry-run', '--allow-low-descriptions')])
def test_both_flags_are_accepted_in_either_order(vps, flags):
    """Both orders really run: the parser is a loop over "$@", so an
    order that only one test exercised would be an order nothing
    checked."""
    export_generation(vps.incoming, descriptions={})
    done = vps(GEN, *flags)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'dry run ok' in done.stdout
    assert 'DRY RUN: nothing was written' in done.stdout
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


def test_an_unknown_flag_is_a_usage_error(vps):
    export_generation(vps.incoming)
    done = vps(GEN, '--no-such-flag')
    assert done.returncode == 2
    assert 'usage:' in done.stderr
    assert '--allow-low-descriptions' in done.stderr
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


def test_a_symlinked_descriptions_file_is_refused(vps, tmp_path):
    """The upload cannot create a symlink (rsync --no-links), so one in a
    generation is something else -- the same posture the payload checks
    in section 1 take, applied to the file that carries the text."""
    generation = export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT})
    elsewhere = tmp_path / 'elsewhere.yaml'
    elsewhere.write_text((generation / 'descriptions.yaml').read_text())
    (generation / 'descriptions.yaml').unlink()
    (generation / 'descriptions.yaml').symlink_to(elsewhere)
    done = vps(GEN)
    assert done.returncode != 0
    assert 'descriptions.yaml in the generation is a symlink' in done.stdout
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


def test_a_descriptions_file_the_manifest_does_not_list_is_refused(vps):
    """`sha256sum -c` verifies the lines a MANIFEST HAS, so a
    descriptions.yaml with no line of its own passes that gate without
    being vouched for by anything -- the one payload whose bytes could be
    swapped after the checksum step. The wrapper refuses before it builds
    the import command, so the importer is never invoked."""
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT},
                      list_descriptions=False)
    done = vps(GEN)
    assert done.returncode != 0
    assert 'descriptions.yaml is in the generation but has no MANIFEST checksum line' \
        in done.stdout
    # Not merely "the import failed": it never started.
    assert '-- import generation' not in done.stdout
    assert 'description coverage:' not in done.stdout
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


def test_the_unlisted_descriptions_guard_is_what_refuses(vps):
    """Non-vacuous half: the SAME generation, with the coverage check
    removed from a copy of the script, imports the unlisted file happily
    -- so the refusal above is the guard's doing and not some other
    objection to the fixture."""
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT},
                      list_descriptions=False)
    unguarded = vps.root.parent / 'import_prod_generation_unguarded.sh'
    source = SCRIPT.read_text().replace(
        "awk -v name=descriptions.yaml '$2 == name { found = 1 } END { exit !found }' \"$SUMS\" \\",
        'true \\')
    assert 'awk -v name=descriptions.yaml' not in source      # the patch really landed
    unguarded.write_text(source)
    done = vps(GEN, script=unguarded)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'description coverage:     1/1 postings to import (100%)' in done.stdout
    job = next(job for job in vault.list_owned_jobs(vps.root)
               if job.get('source_id') == POOL_KEY)
    assert job['description'] == DESCRIPTION_TEXT


def test_a_tampered_descriptions_file_is_refused_like_any_other(vps):
    """The MANIFEST check is `sha256sum -c` over every line the exporter
    wrote, so the new file is covered by the existing gate rather than by
    a second rule that could forget it."""
    export_generation(vps.incoming, descriptions={POOL_KEY: DESCRIPTION_TEXT},
                      tamper=('descriptions.yaml',
                              'day: 2026-11-03\ndescriptions: {}\n'))
    done = vps(GEN)
    assert done.returncode != 0
    assert 'checksum mismatch' in done.stdout
    assert vault.list_owned_jobs(vps.root) == [vps.mine]


def test_the_generation_survives_a_successful_import(vps):
    """The uploaded bytes are the record of what was imported and the
    input to a re-run; the wrapper reads them and moves nothing."""
    generation = export_generation(vps.incoming)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in generation.iterdir()}
    assert vps(GEN).returncode == 0
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in generation.iterdir()} == before
