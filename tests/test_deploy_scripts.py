"""The deploy scripts' own decisions: the guards, the locks, the swap.

Same idiom as test_nightly_pipeline.py -- the real scripts are run as
subprocesses against fixture directories, with PATH-shadowing stubs
standing in for rsync, ssh, curl, zstd and age. Nothing here touches the
network, a real credential, a real vault or a real VPS, and everything
passes as a non-privileged user: these scripts exist to move the owner's
data, so the one thing a test of them must never do is move any.

What they protect, in order of how much it would cost to get wrong:
the sync refusing a night that did not finish, the promotion refusing a
generation it cannot vouch for, the backup refusing to write plaintext,
and the smoke test keeping a password out of argv.
"""
import hashlib
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'deploy'
PIPELINE = ROOT / 'scripts' / 'nightly_pipeline.sh'
DAY = '2026-10-22'

#: rsync, faked by doing the copy locally. A stub that only recorded its
#: arguments would prove the sync calls rsync and nothing about what
#: lands on the far side, and the promotion tests need a generation that
#: the real sync really produced.
RSYNC_STUB = '''#!/usr/bin/env python3
import os, pathlib, shutil, sys

args = sys.argv[1:]
with open(os.environ['STUB_LOG'], 'a') as log:
    log.write('rsync ' + ' '.join(args) + '\\n')
if '--dry-run' in args:
    # Failing ONLY the inspection is its own failure mode: the run that
    # proceeds to the destructive transfer having inspected nothing.
    if os.environ.get('STUB_RSYNC_FAIL_DRYRUN'):
        sys.stderr.write('stub rsync refusing the dry run\\n')
        sys.exit(23)
    sys.exit(0)
if os.environ.get('STUB_RSYNC_FAIL'):
    sys.stderr.write('stub rsync refusing\\n')
    sys.exit(23)
dest = args[-1]
if ':' not in dest:
    # A pull. STUB_VPS, when set, is what the VPS backup directory holds,
    # so a run can actually have something arrive; without it the fixture
    # has already placed everything and there is nothing to copy.
    origin = os.environ.get('STUB_VPS')
    if origin:
        root = pathlib.Path(origin)
        for item in root.rglob('*'):
            if not item.is_file():
                continue
            landing = pathlib.Path(dest) / item.relative_to(root)
            if landing.exists() and '--ignore-existing' in args:
                continue
            landing.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, landing)
    sys.exit(0)

# A push. Every trailing argument that names something on this disk is a
# source: the receipt transfer hands rsync one path per receipt file, not
# a directory, so there can be more than one.
sources = []
for candidate in reversed(args[:-1]):
    if candidate.startswith('-') or not os.path.exists(candidate):
        break
    sources.insert(0, candidate)
target = pathlib.Path(os.environ['STUB_INCOMING']) / dest.split(':', 1)[1]
for source in sources:
    if source.endswith('/'):
        target.mkdir(parents=True, exist_ok=True)
        for item in pathlib.Path(source).iterdir():
            if item.is_dir():
                shutil.copytree(item, target / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target / item.name)
    elif target.is_dir():
        shutil.copy2(source, target / os.path.basename(source))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
sys.exit(0)
'''

#: ssh is never actually invoked by the stub rsync, but it has to exist
#: on PATH for the -e string to be believable, and a test that reached
#: the network would hang rather than fail.
SSH_STUB = '''#!/bin/sh
echo "ssh $*" >> "$STUB_LOG"
echo "stub ssh refuses to connect anywhere" >&2
exit 255
'''

#: age, standing in for the real thing: it records that it was asked and
#: writes something that is not the plaintext. STUB_AGE_SLEEP holds the
#: run inside its archive pipeline, which is where a second run of the
#: same namespace finds it; STUB_AGE_PREEMPT publishes the final archive
#: name from under it, which is what the other run of the same second
#: would do if the lock did not cover publication.
AGE_STUB = '''#!/bin/sh
echo "age $*" >> "$STUB_LOG"
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2;;
    *) shift;;
  esac
done
if [ -n "$STUB_AGE_SLEEP" ]; then sleep "$STUB_AGE_SLEEP"; fi
{ echo "age-encrypted-stub"; cat; } > "$out"
if [ -n "$STUB_AGE_PREEMPT" ]; then
  echo "an archive some other run published" > "$(echo "$out" | sed 's/\\.partial\\.[0-9]*$//')"
fi
'''

#: zstd, standing in for a compressor this host does not have.
ZSTD_STUB = '''#!/bin/sh
echo "zstd $*" >> "$STUB_LOG"
cat
'''

#: curl, which is where the password would leak if smoke.sh ever put it
#: on a command line. It records every argument it was given, answers
#: each URL with the smallest body that keeps the script going, and
#: prints the status code -w asks for.
CURL_STUB = r'''#!/usr/bin/env python3
import os, sys

args = sys.argv[1:]
with open(os.environ['STUB_LOG'], 'a') as log:
    log.write('curl ' + ' '.join(args) + '\n')
    # Every SMOKE_ variable this process INHERITED. argv is one way a
    # password leaks into a child; the environment is the other, and
    # /proc/<pid>/environ is just as readable.
    log.write('curl-inherited ' + ','.join(
        sorted(name for name in os.environ if name.startswith('SMOKE_'))) + '\n')
out = None
for index, arg in enumerate(args):
    if arg == '-o':
        out = args[index + 1]
url = args[-1]
path = url.split(os.environ['STUB_BASE'], 1)[-1] or '/'
bodies = {
    '/login': '{"next": "/jobs", "ok": true}',
    '/': '<html>home</html>',
    '/jobs': '<table><a href="/jobs/channel-manager-job-030">Channel</a></table>',
    '/jobs/channel-manager-job-030': '<html>one job</html>',
}
code = '200' if path in bodies else '404'
if out:
    with open(out, 'w') as handle:
        handle.write(bodies.get(path, 'not found'))
sys.stdout.write(code)
'''

#: The nightly's python, as in test_nightly_pipeline.py: enough to let
#: the shell around it make its own decisions.
NIGHTLY_PYTHON_STUB = """#!/bin/sh
echo "stub $*"
case "$*" in
  *export*) mkdir -p "$(dirname "$NIGHTLY_POOL")"; echo "- id: one" > "$NIGHTLY_POOL";;
esac
exit 0
"""

HOSTNAME = subprocess.run(['hostname'], capture_output=True, text=True).stdout.strip()
#: This account's primary group, which stands in for the group of the
#: restricted account the owner created on the VPS: the receipts
#: directory has to be group-owned by the group the LAN's inbound receipt
#: write arrives as, and a test can only check that against a group this
#: host actually has.
GROUP = subprocess.run(['id', '-gn'], capture_output=True, text=True).stdout.strip()


def write_executable(path, body):
    path.write_text(body)
    path.chmod(0o755)
    return path


def export_body(postings, day=DAY):
    """One pipeline export, in the shape the pipeline really writes it.

    A `summary: postings:` header AND a top-level `postings:` list of that
    many MAPPINGS, each carrying `key:` (verified against
    data/classification/run_2026-10-21.yaml and
    data/ats/exports/golden_set_pool_2026-10-21.yaml, where both hold 715
    records, both agree, and every record has a `key` --
    scripts/import_pool_to_vault.py indexes the pool by it, joins the
    classification run on it, and drops a row that has none).

    The LAN side counts the header; the VPS side counts the list, checks
    every entry is a record with that key, and refuses a generation whose
    header disagrees with its payload -- so a fixture carrying only the
    header would be a fixture of a manifest that lies about its own bytes.
    """
    records = ''.join(f'- key: posting-{index:04d}\n  title: a posting\n'
                      for index in range(postings))
    return f'day: {day!r}\nsummary:\n  postings: {postings}\npostings:\n{records}'


def tenants_body(provider, count):
    """One provider's tenants.yaml, in the shape the feed store writes it.

    A `count:` header AND a `tenants:` list of that many records, each with
    the `tenant` key (verified against data/personio/tenants.yaml and
    data/ats/*/tenants.yaml; careeros/feeds/store.py writes `count` beside
    the list it just built). The VPS counts the records and refuses a file
    whose own header disagrees with its own list, so a fixture with a
    header over an empty list would be a fixture of exactly the lie the
    tenant floor exists to catch.
    """
    records = ''.join(f'- tenant: {provider}-{index:05d}\n  status: fetchable\n'
                      for index in range(count))
    return f'provider: {provider}\ncount: {count}\ntenants:\n{records}'


@pytest.fixture
def lan(tmp_path):
    """A LAN pipeline host: one clean night's output, a push key, stubs."""
    data = tmp_path / 'data'
    (data / 'nightly').mkdir(parents=True)
    (data / 'nightly' / f'nightly_{DAY}.log').write_text(
        f'== nightly pipeline {DAY} (host {HOSTNAME}, pid 1234) ==\n'
        '-- fetch lever ok (attempt 1) in 3s\n'
        '== nightly finished, fails: none ==\n')

    def counted(path, postings):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(export_body(postings))

    counted(data / 'ats' / 'exports' / f'golden_set_pool_{DAY}.yaml', 204)
    counted(data / 'classification' / f'run_{DAY}.yaml', 204)
    for provider, count in (('personio', 2467), ('greenhouse', 2923), ('lever', 91),
                            ('ashby', 3038), ('recruitee', 452), ('smartrecruiters', 629)):
        where = data / 'personio' if provider == 'personio' else data / 'ats' / provider
        where.mkdir(parents=True, exist_ok=True)
        (where / 'tenants.yaml').write_text(tenants_body(provider, count))
        (where / 'runs.yaml').write_text(f'provider: {provider}\ncount: 3\nruns:\n')

    keys = tmp_path / 'ssh'
    keys.mkdir(mode=0o700)
    key = keys / 'id_ed25519'
    key.write_text('NOT A KEY, a fixture\n')
    key.chmod(0o600)
    # The pull's second credential: one authorized_keys line carries one
    # forced command, so reading archives and writing receipts cannot be
    # the same key.
    receipt_key = keys / 'receipt_ed25519'
    receipt_key.write_text('NOT A KEY EITHER, the receipt fixture\n')
    receipt_key.chmod(0o600)
    (keys / 'known_hosts').write_text('app.career-os.ch ssh-ed25519 AAAAfixture\n')

    stubs = tmp_path / 'bin'
    stubs.mkdir()
    write_executable(stubs / 'rsync', RSYNC_STUB)
    write_executable(stubs / 'ssh', SSH_STUB)
    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    log = tmp_path / 'stub.log'

    def run(script, *args, env=None):
        environment = {
            **os.environ,
            'PATH': f"{stubs}:{os.environ['PATH']}",
            'STUB_LOG': str(log),
            'STUB_INCOMING': str(incoming),
            'SYNC_DATA': str(data),
            'SYNC_VAULT': '',
            'CAREEROS_VAULT': '',
            'SYNC_SSH_KEY': str(key),
            'SYNC_KNOWN_HOSTS': str(keys / 'known_hosts'),
            # Both scripts refuse to invent the account name they log in
            # as, so every run states one. The name is this fixture's
            # own: nothing in the repo has a default.
            'SYNC_USER': 'sync-account-under-test',
            **(env or {}),
        }
        return subprocess.run(['bash', str(DEPLOY / script), *args],
                              capture_output=True, text=True, env=environment, timeout=120)

    run.data = data
    run.incoming = incoming
    run.stub_log = log
    run.tmp = tmp_path
    run.keys = keys
    yield run


def pull_env(lan, dest, **extra):
    """The pull's two credentials and its destination, as the owner's own
    `authorized_keys` pair would be."""
    return {
        'PULL_DEST': str(dest),
        'PULL_USER': 'pull-account-under-test',
        'PULL_SSH_KEY': str(lan.keys / 'id_ed25519'),
        'PULL_RECEIPT_SSH_KEY': str(lan.keys / 'receipt_ed25519'),
        'PULL_KNOWN_HOSTS': str(lan.keys / 'known_hosts'),
        **extra,
    }


@pytest.fixture
def vps(tmp_path, lan):
    """A VPS: the incoming directory the LAN just wrote into, locks, root."""
    pipeline_root = tmp_path / 'srv' / 'pipeline'
    pipeline_root.mkdir(parents=True)

    def run(*args, env=None):
        environment = {
            **os.environ,
            'PATH': f"{tmp_path / 'bin'}:{os.environ['PATH']}",
            'STUB_LOG': str(lan.stub_log),
            'DEPLOY_INCOMING': str(lan.incoming),
            'DEPLOY_ROOT': str(pipeline_root),
            'DEPLOY_LOCK': str(tmp_path / 'deploy.lock'),
            'DEPLOY_DATA_LOCK': str(tmp_path / 'data.lock'),
            'DEPLOY_OWNER': '',
            # The interpreter that has PyYAML. On the VPS that is the
            # release venv's python, not necessarily the system one, which
            # is exactly why the script takes it as a variable.
            'PROMOTE_PYTHON': sys.executable,
            **(env or {}),
        }
        return subprocess.run(['bash', str(DEPLOY / 'promote_incoming.sh'), *args],
                              capture_output=True, text=True, env=environment, timeout=120)

    run.root = pipeline_root
    run.incoming = lan.incoming
    return run


def generation_in(incoming):
    names = sorted(path.name for path in incoming.iterdir() if path.is_dir())
    assert len(names) == 1, f'expected one generation, found {names}'
    return names[0]


def restamp(generation, relative):
    """Rewrite one file's sha256 line in a generation's MANIFEST.

    What a writer who still has the generation in `incoming/` can do: put
    other bytes in a file AND make the manifest agree with them. Every
    check that compares the tree to the manifest then passes, which is why
    the content checks exist at all.
    """
    digest = hashlib.sha256((generation / relative).read_bytes()).hexdigest()
    manifest = generation / 'MANIFEST'
    lines = [f'{digest}  {relative}' if line.endswith(f'  {relative}') else line
             for line in manifest.read_text().splitlines()]
    manifest.write_text('\n'.join(lines) + '\n')


def clone_generation(incoming, source, name):
    """A second generation, without waiting a second for a new name."""
    target = incoming / name
    subprocess.run(['cp', '-a', str(incoming / source), str(target)], check=True)
    manifest = target / 'MANIFEST'
    manifest.write_text(re.sub(rf'^generation: {source}$', f'generation: {name}',
                              manifest.read_text(), flags=re.M))
    (target / 'COMPLETE').write_text(f'{name}\n')
    return name


# --- the sync's guards ----------------------------------------------------

def test_sync_refuses_a_day_with_no_completion_manifest(lan):
    (lan.data / 'nightly' / f'nightly_{DAY}.log').unlink()
    done = lan('sync_vault_to_prod.sh', DAY)
    assert done.returncode != 0
    assert 'ALERT careeros-vault-sync 2026-10-22: no nightly completion manifest' in done.stdout
    assert not list(lan.incoming.iterdir()), 'nothing may be uploaded without one'


def test_sync_refuses_a_night_that_did_not_finish_clean(lan):
    log = lan.data / 'nightly' / f'nightly_{DAY}.log'
    log.write_text(log.read_text().replace('fails: none', 'fails: fetch:lever'))
    done = lan('sync_vault_to_prod.sh', DAY)
    assert done.returncode != 0
    assert 'did not finish clean' in done.stdout


def test_sync_reads_the_last_verdict_in_the_day_log_not_any_verdict(lan):
    """The day's log is appended to. A clean night followed by a re-run
    that broke leaves both verdicts in one file, and "is a clean one in
    here anywhere" would push whatever the broken re-run left behind."""
    log = lan.data / 'nightly' / f'nightly_{DAY}.log'
    first = log.read_text()
    log.write_text(first
                   + f'== nightly pipeline {DAY} (host {HOSTNAME}, pid 2345) ==\n'
                   + '-- fetch lever FAILED after 3 attempt(s) in 9s\n'
                   + '== nightly finished, fails: fetch:lever ==\n')
    done = lan('sync_vault_to_prod.sh', DAY)
    assert done.returncode != 0
    assert "last verdict: '== nightly finished, fails: fetch:lever =='" in done.stdout
    assert not list(lan.incoming.iterdir())

    # And the other way round: a night that broke and was re-run clean is
    # pushed, because the final verdict is what describes the data on disk.
    log.write_text(first.replace('fails: none', 'fails: fetch:lever') + first)
    done = lan('sync_vault_to_prod.sh', DAY)
    assert done.returncode == 0, done.stdout + done.stderr
    assert generation_in(lan.incoming).startswith(f'{DAY}T')


def test_sync_refuses_a_log_with_no_verdict_at_all(lan):
    log = lan.data / 'nightly' / f'nightly_{DAY}.log'
    log.write_text(f'== nightly pipeline {DAY} (host {HOSTNAME}, pid 1234) ==\n')
    done = lan('sync_vault_to_prod.sh', DAY)
    assert done.returncode != 0
    assert 'holds no nightly verdict line' in done.stdout


def test_sync_aborts_when_the_pipeline_still_holds_its_lock(lan):
    """A pipeline that is still writing `data/` must block this, or the
    counts describe one tree and the staged copy another."""
    lock = lan.data / 'nightly' / '.pipeline.lock'
    lock.touch()
    holder = subprocess.Popen(['flock', str(lock), 'sleep', '30'])
    try:
        time.sleep(0.5)
        done = lan('sync_vault_to_prod.sh', DAY, env={'SYNC_LOCK_TIMEOUT': '1'})
        assert done.returncode != 0
        assert 'still holds' in done.stdout and 'after 1s' in done.stdout
        assert not list(lan.incoming.iterdir()), 'and nothing was read or pushed'
    finally:
        holder.kill()
        holder.wait()


def test_sync_takes_the_pipeline_lock_shared_so_a_second_reader_is_not_blocked(lan):
    """Shared, not exclusive: the pipeline lock exists to keep a sync out
    of a RUNNING pipeline, and another reader of a finished tree is
    harmless. Two SYNCS are kept apart by the sync lock instead."""
    lock = lan.data / 'nightly' / '.pipeline.lock'
    lock.touch()
    holder = subprocess.Popen(['flock', '-s', str(lock), 'sleep', '30'])
    try:
        time.sleep(0.5)
        done = lan('sync_vault_to_prod.sh', DAY, env={'SYNC_LOCK_TIMEOUT': '2'})
        assert done.returncode == 0, done.stdout + done.stderr
    finally:
        holder.kill()
        holder.wait()


def test_sync_reads_the_verdict_only_once_it_holds_the_pipeline_lock(lan, tmp_path):
    """The verdict used to be read BEFORE the lock was taken, so a re-run
    could change it in the window between "this night finished clean" and
    the staging copy -- and the data that got pushed would be the data of a
    run whose verdict nothing had looked at.

    The lock holder here rewrites the day log to a broken verdict and only
    then releases, so the two orders give opposite answers: read first and
    the sync sees `fails: none` and pushes; read under the lock and it sees
    what is actually on disk and refuses.
    """
    lock = lan.data / 'nightly' / '.pipeline.lock'
    lock.touch()
    log = lan.data / 'nightly' / f'nightly_{DAY}.log'
    broken = tmp_path / 'what-the-rerun-left.log'
    broken.write_text(log.read_text().replace('fails: none', 'fails: classify'))
    holder = subprocess.Popen(
        ['flock', str(lock), 'sh', '-c',
         f'sleep 2; cp {shlex.quote(str(broken))} {shlex.quote(str(log))}'])
    try:
        time.sleep(0.3)
        done = lan('sync_vault_to_prod.sh', DAY, env={'SYNC_LOCK_TIMEOUT': '30'})
        assert done.returncode != 0, done.stdout + done.stderr
        assert "last verdict: '== nightly finished, fails: classify =='" in done.stdout, \
            'the verdict it acted on is the one that was there once it had the lock'
        assert not list(lan.incoming.iterdir())
    finally:
        holder.kill()
        holder.wait()


def test_a_second_sync_refuses_rather_than_minting_the_same_generation(lan):
    """Two syncs started in the same second mint the same
    `<day>T<HHMMSS>Z` name and upload over each other; two started a second
    apart build two generations out of one tree. The sync lock is
    exclusive and non-blocking, so the second one says so and stops."""
    lock = lan.data / 'nightly' / '.sync.lock'
    lock.touch()
    holder = subprocess.Popen(['flock', str(lock), 'sleep', '30'])
    try:
        time.sleep(0.5)
        done = lan('sync_vault_to_prod.sh', DAY, env={'SYNC_LOCK_TIMEOUT': '5'})
        assert done.returncode != 0
        assert 'another sync is running' in done.stdout
        assert 'refusing to build a second generation out of the same tree' in done.stdout
        assert not list(lan.incoming.iterdir()), 'and nothing was read or pushed'
    finally:
        holder.kill()
        holder.wait()


def test_sync_refuses_an_empty_source_file(lan):
    """An export that exists and holds nothing is the worst case: it would
    propagate as a legitimate night in which the world went quiet."""
    (lan.data / 'ats' / 'exports' / f'golden_set_pool_{DAY}.yaml').write_text('')
    done = lan('sync_vault_to_prod.sh', DAY)
    assert done.returncode != 0
    assert 'mandatory file(s) missing or empty' in done.stdout
    assert f'golden_set_pool_{DAY}.yaml' in done.stdout
    assert not list(lan.incoming.iterdir())


def test_sync_refuses_degenerate_counts(lan):
    (lan.data / 'ats' / 'exports' / f'golden_set_pool_{DAY}.yaml').write_text(
        'summary:\n  postings: 3\n')
    done = lan('sync_vault_to_prod.sh', DAY)
    assert done.returncode != 0
    assert 'degenerate pool: 3 posting(s) under the 50 floor' in done.stdout

    # A tenant list that lost its contents: the fetch would find nothing
    # and the night would look quiet rather than broken.
    for tenants in lan.data.rglob('tenants.yaml'):
        tenants.write_text('count: 0\ntenants:\n')
    done = lan('sync_vault_to_prod.sh', DAY, env={'SYNC_MIN_POOL_ROWS': '1'})
    assert done.returncode != 0
    assert 'degenerate tenant pool: 0 tenant(s) under the 1000 floor' in done.stdout


def test_sync_refuses_a_recomputed_day(lan):
    done = lan('sync_vault_to_prod.sh')
    assert done.returncode != 0
    assert 'the nightly\'s day is an argument' in done.stdout


def test_sync_names_the_variable_rather_than_guessing_an_account(lan):
    """No default account name anywhere in these scripts. A guessed one
    would turn "the owner has not told it who to log in as" into an ssh
    failure against a user that does not exist -- the same outage,
    reported as somebody else's problem."""
    done = lan('sync_vault_to_prod.sh', DAY, env={'SYNC_USER': ''})
    assert done.returncode != 0
    assert 'SYNC_USER is not set' in done.stdout
    assert 'name the restricted receiving account you created' in done.stdout


def test_sync_target_set_whole_still_works_without_sync_user(lan):
    # The override is the escape hatch for a host reached some other way,
    # so it has to be enough on its own.
    done = lan('sync_vault_to_prod.sh', DAY,
               env={'SYNC_USER': '', 'SYNC_TARGET': 'someone@elsewhere.example'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'SYNC_USER is not set' not in done.stdout
    assert 'someone@elsewhere.example' in done.stdout


def test_sync_refuses_a_loose_push_key(lan):
    (lan.tmp / 'ssh' / 'id_ed25519').chmod(0o644)
    done = lan('sync_vault_to_prod.sh', DAY)
    assert done.returncode != 0
    assert 'is mode 644, must be 600' in done.stdout


def test_sync_uploads_a_manifest_and_a_separate_complete_marker(lan):
    done = lan('sync_vault_to_prod.sh', DAY)
    assert done.returncode == 0, done.stdout + done.stderr
    generation = generation_in(lan.incoming)
    assert generation.startswith(f'{DAY}T')
    uploaded = lan.incoming / generation
    assert (uploaded / 'MANIFEST').is_file()
    assert (uploaded / 'COMPLETE').read_text().strip() == generation
    assert (uploaded / 'data' / 'classification' / f'run_{DAY}.yaml').is_file()
    assert (uploaded / 'data' / 'personio' / 'tenants.yaml').is_file()
    assert (uploaded / 'data' / 'ats' / 'lever' / 'runs.yaml').is_file()
    assert not (uploaded / 'vault').exists(), 'no vault root given, so no vault file travels'

    calls = lan.stub_log.read_text().splitlines()
    payload = [line for line in calls if line.startswith('rsync') and '--dry-run' not in line]
    assert len(payload) == 2, 'the marker is its own transfer, after the payload'
    assert payload[0].endswith(f'{generation}/') and '--delete' in payload[0]
    assert '--max-delete=50' in payload[0], \
        "rsync's own ceiling, for the deletions the dry run could not have seen"
    assert payload[1].endswith(f'{generation}/COMPLETE') and '--delete' not in payload[1]
    assert any('--dry-run' in line and '--delete' in line for line in calls), \
        'the deletion threshold is measured before anything is written'
    for hardening in ('StrictHostKeyChecking=yes', 'BatchMode=yes', 'IdentitiesOnly=yes',
                      'UserKnownHostsFile='):
        assert hardening in payload[0], hardening


def test_no_transfer_can_create_a_symlink_or_a_special_file_on_the_vps(lan):
    """`-a` implies `-l`, and `--safe-links` would still recreate a link
    that points inside the tree. Only the --no-* set makes "the uploader
    cannot plant a symlink on prod" true of the wire and not just of the
    staging step that happens to look first."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    calls = [line for line in lan.stub_log.read_text().splitlines()
             if line.startswith('rsync')]
    assert len(calls) == 3, 'the dry run, the payload and the marker'
    for line in calls:
        for flag in ('--no-links', '--no-devices', '--no-specials'):
            assert flag in line, f'{flag} missing from: {line}'


def test_sync_aborts_when_the_deletion_dry_run_itself_fails(lan):
    """A dry run that fails is not a dry run that found nothing. It used
    to be read as one -- stderr discarded, `|| true`, grep -c answering 0
    on an empty stream -- and the destructive transfer ran next."""
    done = lan('sync_vault_to_prod.sh', DAY, env={'STUB_RSYNC_FAIL_DRYRUN': '1'})
    assert done.returncode != 0
    assert 'the deletion dry run failed (rsync exit 23' in done.stdout
    assert 'refusing to transfer without knowing what it would delete' in done.stdout
    assert not list(lan.incoming.iterdir()), 'and nothing was transferred'
    calls = [line for line in lan.stub_log.read_text().splitlines()
             if line.startswith('rsync')]
    assert len(calls) == 1 and '--dry-run' in calls[0], \
        'the only rsync that ran is the one that failed'


def test_sync_delete_is_scoped_to_the_incoming_generation(lan):
    """--delete may only ever point inside the disposable incoming tree."""
    lan('sync_vault_to_prod.sh', DAY)
    for line in lan.stub_log.read_text().splitlines():
        if '--delete' not in line:
            continue
        destination = line.split()[-1]
        assert re.search(r':\d{4}-\d{2}-\d{2}T\d{6}Z/$', destination), destination


def test_sync_reports_a_failed_transfer_and_promotes_nothing(lan):
    done = lan('sync_vault_to_prod.sh', DAY, env={'STUB_RSYNC_FAIL': '1'})
    assert done.returncode != 0
    assert 'ALERT careeros-vault-sync' in done.stdout
    assert 'prod keeps serving its last promoted generation' in done.stdout


# --- the promotion's guards ----------------------------------------------

def test_promote_swaps_the_pointer_atomically(lan, vps):
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)

    done = vps()
    assert done.returncode == 0, done.stdout + done.stderr
    current = vps.root / 'current'
    assert current.is_symlink()
    assert os.readlink(current) == f'generations/{generation}', 'a relative target under the fixed root'
    assert (current / 'data' / 'classification' / f'run_{DAY}.yaml').is_file()
    assert not (lan.incoming / generation).exists(), 'promotion moves, it does not copy'
    assert 'validated' in done.stdout and 'promote ok' in done.stdout


def test_promote_refuses_a_generation_the_upload_never_finished(lan, vps):
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    (lan.incoming / generation / 'COMPLETE').unlink()

    done = vps(generation)
    assert done.returncode != 0
    assert 'incomplete generation' in done.stdout
    assert not (vps.root / 'current').exists(), 'prod keeps serving whatever it served'


def test_promote_refuses_a_generation_holding_a_symlink(lan, vps):
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    (lan.incoming / generation / 'data' / 'escape.yaml').symlink_to('/etc/passwd')

    done = vps(generation)
    assert done.returncode != 0
    assert 'symlink or special file' in done.stdout
    assert not (vps.root / 'current').exists()


def test_promote_refuses_a_file_the_manifest_does_not_vouch_for(lan, vps):
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    (lan.incoming / generation / 'data' / 'extra.yaml').write_text('added after the manifest\n')

    done = vps(generation)
    assert done.returncode != 0
    assert 'the tree and the manifest disagree' in done.stdout


def test_promote_refuses_bytes_that_changed_under_the_manifest(lan, vps):
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    (lan.incoming / generation / 'data' / 'classification' / f'run_{DAY}.yaml').write_text(
        'summary:\n  postings: 999999\n')

    done = vps(generation)
    assert done.returncode != 0
    assert 'checksum mismatch' in done.stdout


def test_promote_validates_after_the_move_so_a_late_rewrite_cannot_win(lan, vps):
    """The time-of-check/time-of-use hole. Validating in `incoming/` --
    the one directory the uploader's key can write -- and promoting
    afterwards leaves a window in which checked bytes can be replaced, and
    what gets served is bytes nothing vouched for. Validation now happens
    in the final location, so the only thing a late rewrite can do is make
    the generation fail: it is already out of reach when it is read.
    """
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    # Finished, vouched for, COMPLETE -- and then rewritten, which is
    # exactly what the old order would have promoted. Stamped into the
    # future as well, so the tree carries both marks a mid-flight writer
    # leaves: bytes that disagree with the manifest, and an mtime later
    # than the marker that says the upload finished.
    late = lan.incoming / generation / 'data' / 'classification' / f'run_{DAY}.yaml'
    late.write_text('summary:\n  postings: 1\n')
    after_marker = (lan.incoming / generation / 'COMPLETE').stat().st_mtime + 60
    os.utime(late, (after_marker, after_marker))

    done = vps(generation)
    assert done.returncode != 0
    assert 'checksum mismatch' in done.stdout
    assert not (vps.root / 'current').exists(), 'prod keeps serving whatever it served'
    assert not (vps.root / 'generations' / generation).exists(), \
        'and the rejected generation is gone: it was never pointed at, and leaving ' \
        'it would let the next run promote it by name'
    assert 'rejected generation removed' in done.stdout


def test_promote_refuses_a_generation_written_into_after_its_complete_marker(lan, vps):
    """The post-validation window, which the checksums alone cannot close.

    A rename revokes names, not already-open file descriptors: an rsync
    receiver still holding a payload file open keeps writing into the moved
    tree, and nothing in userspace can take that descriptor away. So the
    generation is read once more immediately before the pointer swap --
    checksummed again, and checked for any file stamped later than the
    COMPLETE marker that travelled with it.

    This is the mutation the earlier checks cannot see: the manifest is
    restamped to agree with the new bytes, so every byte-level check
    passes, and the only thing left that disagrees is the clock.

    300s, not 60: a payload file that looks slightly newer than the marker
    is two clocks disagreeing (the test below), and the guard tolerates
    120s of that. Five minutes is nobody's NTP skew.
    """
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    relative = f'data/classification/run_{DAY}.yaml'
    target = lan.incoming / generation / relative
    target.write_text(export_body(204) + '# written after the marker\n')
    restamp(lan.incoming / generation, relative)

    marker = lan.incoming / generation / 'COMPLETE'
    after_marker = marker.stat().st_mtime + 300
    os.utime(target, (after_marker, after_marker))
    # The restamp touched MANIFEST too; put it back, so the file the alert
    # names is the payload file this test is about and not the manifest.
    os.utime(lan.incoming / generation / 'MANIFEST',
             (marker.stat().st_mtime - 1, marker.stat().st_mtime - 1))

    done = vps(generation)
    assert done.returncode != 0
    assert 'stamped more than 120s after its COMPLETE marker' in done.stdout
    assert relative in done.stdout, 'and the alert names the file'
    assert not (vps.root / 'current').exists(), 'prod keeps serving whatever it served'
    assert not (vps.root / 'generations' / generation).exists()
    assert 'rejected generation removed' in done.stdout


def test_promote_tolerates_a_payload_a_minute_newer_than_its_marker(lan, vps):
    """The other side of that guard: clock skew is not a writer.

    rsync preserves the SOURCE's mtimes, so a legitimate payload file is
    OLDER than the COMPLETE marker this host's uploader pushed last. The
    only thing that can make one look slightly newer is the LAN host's
    clock disagreeing with the VPS's, and a bare `-newer` turned a few
    seconds of NTP drift into a refused night and a stale-sync alarm
    somebody has to come and look at. Within the 120s tolerance it
    promotes; past it (the test above) it does not.
    """
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    marker = lan.incoming / generation / 'COMPLETE'
    target = lan.incoming / generation / 'data' / 'classification' / f'run_{DAY}.yaml'
    skewed = marker.stat().st_mtime + 60
    os.utime(target, (skewed, skewed))

    done = vps(generation)
    assert done.returncode == 0, done.stdout + done.stderr
    assert os.readlink(vps.root / 'current') == f'generations/{generation}'


def test_promote_refuses_a_generation_a_process_still_holds_open(lan, vps):
    """The window the checksums and the clock both miss.

    A rename revokes names, not descriptors: an rsync receiver that had a
    payload file open when the generation was moved keeps writing into the
    moved inode, and the bytes can still match the manifest at the moment
    they are read. What a userspace script CAN do is see the holder -- so
    nothing may have a file in the tree open at the swap, and a generation
    that is still open is destroyed with the holding PIDs named.
    """
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    payload = lan.incoming / generation / 'data' / 'classification' / f'run_{DAY}.yaml'
    # One open descriptor on one payload file, inherited by a child that
    # outlives the promotion: a transfer that started before the move.
    holder = subprocess.Popen(['sh', '-c', 'exec 3< "$1"; sleep 30', 'sh', str(payload)])
    try:
        time.sleep(0.5)
        done = vps(generation)
        assert done.returncode != 0, done.stdout + done.stderr
        assert 'still open in another process' in done.stdout
        assert str(holder.pid) in done.stdout, 'and the alert names the holder'
        assert not (vps.root / 'current').exists(), 'prod keeps serving whatever it served'
        assert not (vps.root / 'generations' / generation).exists()
        assert 'rejected generation removed' in done.stdout
        # Nothing was wrong with the bytes: it is the holder that stopped
        # this, at the last check before the swap.
        assert 'validated' in done.stdout
        assert 'checksum mismatch' not in done.stdout
    finally:
        holder.kill()
        holder.wait()


def test_promote_fails_closed_when_the_quiescence_scan_itself_breaks(lan, vps, tmp_path):
    """The other failure mode of a check: it cannot run.

    A scan that suppresses its own errors and prints nothing is
    indistinguishable from a scan that found no holders -- treating the
    first as the second fails the check OPEN, which is the one thing a
    security check must never do. fuser's exit codes are the contract: 0
    holders listed, 1 nobody holds the file, anything else an inspection
    error. A stub that exits 2 on every file makes promotion refuse, name
    the failure, and leave the generation unpromoted and removed.
    """
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)

    stubs = tmp_path / 'bin'
    stubs.mkdir(exist_ok=True)
    broken = stubs / 'fuser'
    broken.write_text('#!/bin/sh\nexit 2\n')   # not 0, not 1: an inspection error
    broken.chmod(0o755)
    # lsof must not be reachable either, or the script would prefer it
    # only when fuser is absent -- fuser IS present here, so the fuser
    # branch runs; the stub shadows the real one via PATH order.

    done = vps(generation)
    assert done.returncode != 0, done.stdout + done.stderr
    assert 'could not inspect' in done.stdout
    assert 'has not passed' in done.stdout
    assert not (vps.root / 'current').exists(), 'prod keeps serving whatever it served'
    assert not (vps.root / 'generations' / generation).exists()


def test_promote_refuses_a_mandatory_file_that_is_a_bare_scalar(lan, vps):
    """`yaml.safe_load` returning something truthy is not validation. The
    file `ok` is valid YAML, parses to the string 'ok', and is not an
    export of anything."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    pool = f'data/ats/exports/golden_set_pool_{DAY}.yaml'
    (lan.incoming / generation / pool).write_text('ok\n')
    restamp(lan.incoming / generation, pool)

    done = vps(generation)
    assert done.returncode != 0
    assert f'{pool} is not a usable YAML document' in done.stdout
    assert 'it parses to a bare str' in done.stdout
    assert not (vps.root / 'current').exists()
    assert not (vps.root / 'generations' / generation).exists()


def test_promote_refuses_a_mandatory_file_that_is_an_empty_collection(lan, vps):
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    classified = f'data/classification/run_{DAY}.yaml'
    (lan.incoming / generation / classified).write_text('[]\n')
    restamp(lan.incoming / generation, classified)

    done = vps(generation)
    assert done.returncode != 0
    assert 'parses, but to an empty document' in done.stdout
    assert not (vps.root / 'current').exists()


def test_promote_counts_the_payload_so_an_omitted_header_is_not_a_bypass(lan, vps):
    """The floors used to be applied to the manifest header, and a header
    that said nothing meant no floor was enforced at all -- the uploader
    could promote a day with three postings in it by leaving a line out.
    The count now comes from the records in the file."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    pool = f'data/ats/exports/golden_set_pool_{DAY}.yaml'
    (lan.incoming / generation / pool).write_text(export_body(3))
    restamp(lan.incoming / generation, pool)
    manifest = lan.incoming / generation / 'MANIFEST'
    manifest.write_text(re.sub(r'^pool_postings: .*\n', '', manifest.read_text(), flags=re.M))

    done = vps(generation)
    assert done.returncode != 0
    assert 'degenerate pool_postings: 3 under the 50 floor' in done.stdout
    assert not (vps.root / 'current').exists()
    assert not (vps.root / 'generations' / generation).exists()


def test_promote_refuses_a_manifest_header_that_disagrees_with_the_payload(lan, vps):
    """The header is the uploader's claim about the payload. A claim that
    does not match what is in the file is a manifest describing some other
    night, whichever way round the difference goes."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    classified = f'data/classification/run_{DAY}.yaml'
    # 60 real records, above the floor, with a header still claiming 204.
    (lan.incoming / generation / classified).write_text(export_body(60))
    restamp(lan.incoming / generation, classified)

    done = vps(generation)
    assert done.returncode != 0
    assert 'the manifest header claims classified_postings: 204, the payload holds 60' in done.stdout
    assert 'does not describe the bytes it travelled with' in done.stdout
    assert not (vps.root / 'current').exists()
    assert not (vps.root / 'generations' / generation).exists()


def test_promote_counts_tenants_out_of_the_generations_own_files(lan, vps):
    """The tenant floor, on the twelve files the generation carries rather
    than on the one header line the uploader wrote."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    done = vps(generation, env={'PROMOTE_MIN_TENANTS': '9601'})
    assert done.returncode != 0
    assert 'degenerate tenants: 9600 under the 9601 floor' in done.stdout


def test_promote_refuses_a_tenants_file_whose_header_outruns_its_own_list(lan, vps):
    """The tenant floor used to be a sum of `count:` HEADER lines, so
    `count: 1000` over `tenants: []` was a thousand tenants as far as the
    floor was concerned -- a night that discovered nobody, promoted. The
    floor is now applied to the records in the list, and a header that
    disagrees with the list it sits on top of is the same lie the manifest
    header is checked for."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    relative = 'data/ats/greenhouse/tenants.yaml'
    (lan.incoming / generation / relative).write_text(
        'provider: greenhouse\ncount: 9999\ntenants: []\n')
    restamp(lan.incoming / generation, relative)

    done = vps(generation)
    assert done.returncode != 0
    assert f'{relative} says count: 9999 but its tenants list holds 0 record(s)' in done.stdout
    assert not (vps.root / 'current').exists()
    assert not (vps.root / 'generations' / generation).exists()
    assert 'rejected generation removed' in done.stdout


def test_promote_refuses_a_tenant_floor_the_parsed_records_do_not_reach(lan, vps):
    """And with the headers gone as well, so nothing is left to claim
    anything: what the floor sees is the records, and an emptied tenant
    list is a night whose discovery lost its data."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    for tenants in (lan.incoming / generation).rglob('tenants.yaml'):
        relative = str(tenants.relative_to(lan.incoming / generation))
        tenants.write_text('provider: emptied\ntenants: []\n')
        restamp(lan.incoming / generation, relative)
    manifest = lan.incoming / generation / 'MANIFEST'
    manifest.write_text(re.sub(r'^tenants: .*\n', '', manifest.read_text(), flags=re.M))

    done = vps(generation)
    assert done.returncode != 0
    assert 'degenerate tenants: 0 under the 1000 floor' in done.stdout
    assert 'rejected generation removed' in done.stdout
    assert not (vps.root / 'generations' / generation).exists()


def test_promote_alerts_rather_than_dying_on_a_tenants_file_it_cannot_count(lan, vps):
    """`set -euo pipefail` and a tenants.yaml the parser refuses: the
    script has to come back with an ALERT line and clean up after itself,
    not exit on `set -e` with a bare exit code, no ALERT line, and the
    moved generation left sitting in `generations/` for the next run to
    promote by name."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    relative = 'data/ats/lever/tenants.yaml'
    (lan.incoming / generation / relative).write_text(
        'provider: lever\ncount: 91\ntenants: 91\n')
    restamp(lan.incoming / generation, relative)

    done = vps(generation)
    assert done.returncode != 0
    assert f'{relative} is not a usable YAML document' in done.stdout, \
        'an alert, not a silent death'
    assert "its 'tenants:' key holds a int, not a list of records" in done.stdout
    assert 'rejected generation removed' in done.stdout
    assert not (vps.root / 'generations' / generation).exists()


def test_promote_refuses_a_postings_list_of_scalars(lan, vps):
    """`postings: [x, y, z]` is a list of three things and not a list of
    three records -- and sixty of them would have satisfied the floor
    while holding nothing the app can read."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    pool = f'data/ats/exports/golden_set_pool_{DAY}.yaml'
    (lan.incoming / generation / pool).write_text(
        'summary:\n  postings: 60\npostings:\n'
        + ''.join(f'- posting-{index:04d}\n' for index in range(60)))
    restamp(lan.incoming / generation, pool)

    done = vps(generation)
    assert done.returncode != 0
    assert f'{pool} is not a usable YAML document' in done.stdout
    assert "entry 0 of 'postings:' is a bare str, not a record" in done.stdout
    assert not (vps.root / 'current').exists()
    assert not (vps.root / 'generations' / generation).exists()


def test_promote_refuses_posting_records_without_the_key_they_are_read_by(lan, vps):
    """Mappings, but not records of anything: every reader downstream
    identifies a posting by `key` (scripts/import_pool_to_vault.py indexes
    the pool by it and joins the classification run on it), so a list of
    sixty mappings without one is sixty rows that import as nothing."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    classified = f'data/classification/run_{DAY}.yaml'
    (lan.incoming / generation / classified).write_text(
        'summary:\n  postings: 60\npostings:\n'
        + ''.join('- title: a posting\n  values: {}\n' for _ in range(60)))
    restamp(lan.incoming / generation, classified)

    done = vps(generation)
    assert done.returncode != 0
    assert f'{classified} is not a usable YAML document' in done.stdout
    assert "entry 0 of 'postings:' has no 'key:' key" in done.stdout
    assert not (vps.root / 'current').exists()
    assert not (vps.root / 'generations' / generation).exists()


def test_a_rejected_generation_does_not_outlive_its_rejection(lan, vps):
    """Twice over: the clean-up must not depend on which check failed."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    first = generation_in(lan.incoming)
    second = clone_generation(lan.incoming, first, f'{DAY}T235959Z')
    assert vps(first).returncode == 0

    (lan.incoming / second / 'data' / 'extra.yaml').write_text('nothing vouches for me\n')
    done = vps(second)
    assert done.returncode != 0
    assert 'the tree and the manifest disagree' in done.stdout
    assert not (vps.root / 'generations' / second).exists()
    assert os.readlink(vps.root / 'current') == f'generations/{first}', \
        'and the generation that was good is still the one being served'


def test_promote_refuses_an_empty_mandatory_file_whose_checksum_matches(lan, vps):
    """The worst case the checksums cannot see: a file that is byte-perfect
    and holds nothing. Prod would serve a day with no jobs in it."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    pool = f'data/ats/exports/golden_set_pool_{DAY}.yaml'
    (lan.incoming / generation / pool).write_text('')
    restamp(lan.incoming / generation, pool)

    done = vps(generation)
    assert done.returncode != 0
    assert 'is not a usable YAML document' in done.stdout
    assert 'parses, but to an empty document' in done.stdout
    assert not (vps.root / 'current').exists()
    assert not (vps.root / 'generations' / generation).exists()


def test_promote_refuses_a_mandatory_file_that_does_not_parse(lan, vps):
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    classified = f'data/classification/run_{DAY}.yaml'
    (lan.incoming / generation / classified).write_text('summary: { postings: [1, 2\n')
    restamp(lan.incoming / generation, classified)

    done = vps(generation)
    assert done.returncode != 0
    assert f'{classified} is not a usable YAML document' in done.stdout
    assert not (vps.root / 'current').exists()


def test_promote_fails_closed_when_it_cannot_parse_yaml_at_all(lan, vps):
    """No parser, no promotion. A validation step that cannot run is not a
    validation step that passed."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)
    done = vps(generation, env={'PROMOTE_PYTHON': '/nonexistent/python'})
    assert done.returncode != 0
    assert 'is not a usable YAML document' in done.stdout
    assert not (vps.root / 'current').exists()


def test_promote_enforces_its_own_record_floors(lan, vps):
    """The VPS re-checks the counts the LAN claims, rather than trusting
    that the LAN checked them."""
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    generation = generation_in(lan.incoming)

    done = vps(generation, env={'PROMOTE_MIN_POOL_ROWS': '100000'})
    assert done.returncode != 0
    assert 'degenerate pool_postings: 204 under the 100000 floor' in done.stdout
    assert not (vps.root / 'generations' / generation).exists()


def test_promote_refuses_a_source_host_it_was_not_told_to_expect(lan, vps):
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    first = generation_in(lan.incoming)
    second = clone_generation(lan.incoming, first, f'{DAY}T235959Z')

    done = vps(first, env={'PROMOTE_EXPECTED_SOURCE': 'some-other-host'})
    assert done.returncode != 0
    assert "the manifest's source is" in done.stdout
    assert 'not the expected' in done.stdout
    assert not (vps.root / 'current').exists()

    done = vps(second, env={'PROMOTE_EXPECTED_SOURCE': HOSTNAME})
    assert done.returncode == 0, done.stdout + done.stderr
    assert os.readlink(vps.root / 'current') == f'generations/{second}'


def test_promote_refuses_while_a_release_holds_the_deploy_lock(lan, vps, tmp_path):
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    lock = tmp_path / 'deploy.lock'
    lock.touch()
    holder = subprocess.Popen(['flock', str(lock), 'sleep', '30'])
    try:
        time.sleep(0.5)
        done = vps()
        assert done.returncode != 0
        assert 'a release holds' in done.stdout
        assert not (vps.root / 'current').exists()
    finally:
        holder.kill()
        holder.wait()


def test_the_previous_generation_survives_the_drain_window(lan, vps):
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    first = generation_in(lan.incoming)
    second = clone_generation(lan.incoming, first, f'{DAY}T235959Z')
    third = clone_generation(lan.incoming, first, f'{DAY}T235958Z')

    assert vps(first).returncode == 0
    done = vps(second)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (vps.root / 'generations' / first).is_dir(), \
        'readers inside the old generation get the drain window to finish'
    assert f'previous generation {first} kept' in done.stdout
    assert os.readlink(vps.root / 'current') == f'generations/{second}'

    # Past the window, the next promotion is what clears it.
    done = vps(third, env={'DEPLOY_DRAIN_SECONDS': '0'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert not (vps.root / 'generations' / first).exists()
    assert f'pruned generation {first}' in done.stdout
    assert (vps.root / 'current' / 'MANIFEST').is_file(), 'and prod still serves one'


def test_promote_refuses_to_replace_a_live_generation(lan, vps):
    assert lan('sync_vault_to_prod.sh', DAY).returncode == 0
    first = generation_in(lan.incoming)
    clone_generation(lan.incoming, first, 'second-copy-placeholder')
    assert vps(first).returncode == 0
    # The same name turns up in incoming again (a re-upload, a retry).
    subprocess.run(['mv', str(lan.incoming / 'second-copy-placeholder'),
                    str(lan.incoming / first)], check=True)
    manifest = lan.incoming / first / 'MANIFEST'
    manifest.write_text(re.sub(r'^generation: .*$', f'generation: {first}',
                              manifest.read_text(), flags=re.M))
    (lan.incoming / first / 'COMPLETE').write_text(f'{first}\n')

    done = vps(first)
    assert done.returncode != 0
    assert 'already promoted' in done.stdout


# --- the backup's fail-closed rule ---------------------------------------

@pytest.fixture
def backups(tmp_path):
    """A VPS backup setup: a source to archive and stubs for zstd and age."""
    source = tmp_path / 'srv' / 'pipeline' / 'current'
    source.mkdir(parents=True)
    (source / 'MANIFEST').write_text('generation: fixture\n')
    (source / 'data').mkdir()
    (source / 'data' / 'run.yaml').write_text('summary:\n  postings: 204\n' * 40)

    # The prod vault: the half a startup migration rewrites, and the half
    # nothing but a backup can put back.
    vault = tmp_path / 'vault'
    (vault / 'applications').mkdir(parents=True)
    (vault / 'applications' / 'app-1.yaml').write_text(
        'id: app-1\nstatus: applied\nnote: an-owner-edited-record\n')

    stubs = tmp_path / 'backup-bin'
    stubs.mkdir()
    write_executable(stubs / 'zstd', ZSTD_STUB)
    age = write_executable(stubs / 'age', AGE_STUB)
    recipients = tmp_path / 'recipients.txt'
    recipients.write_text('age1fixturerecipientnotarealkey\n')
    log = tmp_path / 'backup-stub.log'

    def environment(env=None):
        return {
            **os.environ,
            'PATH': f"{stubs}:{os.environ['PATH']}",
            'STUB_LOG': str(log),
            'BACKUP_DIR': str(tmp_path / 'var-backups'),
            'BACKUP_FULL_SOURCE': str(source),
            'BACKUP_OWNER_SOURCE': str(vault),
            'BACKUP_AGE_RECIPIENTS': str(recipients),
            'BACKUP_ZSTD_LEVEL': '1',
            # The group the LAN pull's inbound receipt write arrives
            # as. It has no default in the script -- the account is the
            # owner's, named by them -- so every run here names one, and
            # it has to be a group this host really has or every run
            # would be testing the chgrp-failed path.
            'BACKUP_RECEIPT_GROUP': GROUP,
            'DEPLOY_DATA_LOCK': str(tmp_path / 'data.lock'),
            **(env or {}),
        }

    def command(*args):
        script = args[0] if args and args[0].endswith('.sh') else 'backup_prod.sh'
        rest = args[1:] if script != 'backup_prod.sh' else args
        return ['bash', str(DEPLOY / script), *rest]

    def run(*args, env=None, with_age=True):
        if not with_age:
            age.unlink()
        return subprocess.run(command(*args), capture_output=True, text=True,
                              env=environment(env), timeout=120)

    def receipt(archive, digest=None):
        """What deploy/pull_backups_lan.sh leaves on the VPS once a copy of
        an archive is on the LAN and its checksum has been checked there.

        The hash is the point of it: `archive:` is a filename, and a
        filename is reused every time a namespace rolls round. `digest`
        overrides it, which is how a receipt about other bytes is written.
        """
        where = run.receipts / f'{archive.name}.pulled'
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_text(
            f'archive: {archive.name}\nverified_by: a-lan-host\n'
            f'sha256: {digest or hashlib.sha256(archive.read_bytes()).hexdigest()}\n')
        return where

    run.dir = tmp_path / 'var-backups'
    run.receipts = tmp_path / 'var-backups' / '.receipts'
    run.receipt = receipt
    run.command = command
    run.environment = environment
    run.recipients = recipients
    run.source = source
    run.vault = vault
    return run


@pytest.mark.skipif(shutil.which('age') is not None,
                    reason='a real age on PATH cannot be made absent without lying about it; '
                           'the recipient-file half of fail-closed is covered unconditionally')
def test_backup_fails_closed_without_age(backups):
    """No encryptor, no backup. The alternative -- a plaintext copy of
    somebody's job history on a rented VPS -- is not a fallback."""
    done = backups('--full', with_age=False)
    assert done.returncode != 0
    assert 'age is not installed; refusing to write an unencrypted backup' in done.stdout
    assert not backups.dir.exists(), 'and not one byte was written'


def test_backup_fails_closed_without_a_recipient_file(backups):
    backups.recipients.unlink()
    done = backups('--full')
    assert done.returncode != 0
    assert 'refusing to write an unencrypted backup' in done.stdout
    assert not backups.dir.exists()


def test_backup_fails_closed_on_a_recipient_file_that_holds_no_recipient(backups):
    backups.recipients.write_text('# I meant to put the key here\n')
    done = backups('--full')
    assert done.returncode != 0
    assert 'no recognisable age recipient' in done.stdout


def test_backup_refuses_an_empty_source(backups, tmp_path):
    done = backups('--owner-data', env={'BACKUP_OWNER_SOURCE': str(tmp_path / 'absent')})
    assert done.returncode != 0
    assert 'nothing to back up' in done.stdout


def test_a_full_backup_is_encrypted_verified_and_only_then_pruned(backups):
    done = backups('--full', env={'BACKUP_KEEP': '2'})
    assert done.returncode == 0, done.stdout + done.stderr
    archives = sorted((backups.dir / 'full').glob('*.tar.zst.age'))
    assert len(archives) == 1
    assert archives[0].read_text(errors='replace').startswith('age-encrypted-stub'), \
        'the bytes on disk went through age, not around it'
    assert archives[0].with_suffix('.age.sha256').is_file(), 'its manifest is beside it'
    assert not list((backups.dir / 'full').glob('*.partial'))
    assert stat.S_IMODE((backups.dir / 'full').stat().st_mode) == 0o750
    assert '1 archive(s) retained' in done.stdout

    # Three more, with the keep count at 2, each run finding the older
    # archives receipted as the LAN pull would have left them: the two
    # newest survive and pruning happened only after the new archive
    # verified.
    for _ in range(3):
        time.sleep(1.1)
        for archive in (backups.dir / 'full').glob('*.tar.zst.age'):
            backups.receipt(archive)
        assert backups('--full', env={'BACKUP_KEEP': '2'}).returncode == 0
    assert len(sorted((backups.dir / 'full').glob('*.tar.zst.age'))) == 2
    assert len(sorted((backups.dir / 'full').glob('*.sha256'))) == 2
    survivors = {a.name for a in (backups.dir / 'full').glob('*.tar.zst.age')}
    orphaned = [r.name for r in backups.receipts.glob('*.pulled')
                if r.name[:-len('.pulled')] not in survivors]
    assert not orphaned, \
        f'a pruned archive takes its receipt with it, or the directory only grows: {orphaned}'


def test_two_concurrent_backups_of_one_namespace_cannot_interleave(backups):
    """Two runs of the same namespace in the same second agree on the
    archive name: the name comes from the clock. The lock used to be
    released as soon as the archive bytes were written, so publication,
    checksumming and pruning all ran outside it -- one run renaming its
    partial onto the name the other was about to rename onto, each
    checksumming whatever won, and both deciding what to prune from a
    listing the other was changing.

    It is held from before anything is created until the process exits
    now, so the only two outcomes are: both runs complete (the second
    waited, and its name came from a later second), or the second finds
    the name taken and says so. Never a half-published archive.
    """
    first, second = (subprocess.Popen(backups.command('--full'),
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True,
                                      env=backups.environment({'STUB_AGE_SLEEP': '1'}))
                     for _ in range(2))
    outputs = [done.communicate(timeout=120)[0] for done in (first, second)]
    codes = [first.returncode, second.returncode]

    archives = sorted((backups.dir / 'full').glob('*.tar.zst.age'))
    assert sorted(codes) in ([0, 0], [0, 1]), codes
    assert len(archives) == codes.count(0), \
        f'one archive per run that said it succeeded: {codes}, {[a.name for a in archives]}'
    for output, code in zip(outputs, codes):
        if code != 0:
            assert 'already exists' in output, output
    assert not list((backups.dir / 'full').glob('*.partial*')), \
        'and no partial outlives either run, whichever way the race went'

    # Every published archive is whole: its own bytes, its own manifest.
    for archive in archives:
        assert archive.read_text(errors='replace').startswith('age-encrypted-stub')
        manifest = archive.with_name(f'{archive.name}.sha256')
        assert manifest.is_file()
        assert subprocess.run(['sha256sum', '--quiet', '-c', manifest.name],
                              cwd=archive.parent).returncode == 0, \
            f'{archive.name} does not read back to the manifest written beside it'


def test_a_backup_refuses_to_overwrite_an_archive_that_appeared_under_it(backups):
    """The last line of the same defence. If the final name exists at
    publication time, something this run knows nothing about wrote it --
    and `mv` would both destroy that copy and publish bytes whose manifest
    describes the other one. The stub age publishes the final name from
    under the run to make that moment reachable on purpose; the lock is
    what makes it unreachable in practice."""
    done = backups('--full', env={'STUB_AGE_PREEMPT': '1'})
    assert done.returncode != 0
    assert 'appeared while this run was compressing' in done.stdout
    assert 'refusing to overwrite it' in done.stdout

    published = sorted((backups.dir / 'full').glob('*.tar.zst.age'))
    assert len(published) == 1
    assert published[0].read_text() == 'an archive some other run published\n', \
        'the other run\'s archive is exactly as it was'
    assert not list((backups.dir / 'full').glob('*.partial*')), 'and this run cleaned up'
    assert not list((backups.dir / 'full').glob('*.sha256')), \
        'and wrote no manifest for an archive it did not publish'


def test_a_second_backup_waits_for_the_data_lock_rather_than_running_anyway(backups,
                                                                            tmp_path):
    """The lock is `-w`, not `-n`: a queued backup is a backup, where a
    refused one is a night with no copy of anything."""
    lock = tmp_path / 'held.lock'
    lock.touch()
    holder = subprocess.Popen(['flock', str(lock), 'sleep', '2'])
    try:
        time.sleep(0.3)
        started = time.monotonic()
        done = backups('--full', env={'DEPLOY_DATA_LOCK': str(lock)})
        waited = time.monotonic() - started
    finally:
        holder.kill()
        holder.wait()
    assert done.returncode == 0, done.stdout + done.stderr
    assert waited >= 1.2, f'it did not wait for the lock at all ({waited:.2f}s)'
    assert len(sorted((backups.dir / 'full').glob('*.tar.zst.age'))) == 1, \
        'and once it had the lock it did the whole run'


@pytest.mark.skipif(os.geteuid() != 0,
                    reason='chgrp and the setgid bit need root; the non-root path is '
                           'covered by its own test')
def test_the_receipt_directory_is_setgid_and_group_owned_for_the_push(backups):
    """What the runbook promised and only the owner was doing. 0770 grants
    the create to a GROUP, and the group has to be the one the LAN's
    receipt push arrives as or the write is granted to nobody who wants
    it. Setgid so a receipt created in there inherits that group instead of
    the pushing account's primary one."""
    done = backups('--full')
    assert done.returncode == 0, done.stdout + done.stderr
    where = backups.receipts.stat()
    assert stat.S_IMODE(where.st_mode) == 0o2770, 'group-writable, and setgid'
    assert where.st_gid == os.getgid(), f'group-owned to {GROUP}'


@pytest.mark.skipif(os.geteuid() != 0, reason='the chgrp is only attempted as root')
def test_a_backup_says_so_when_the_receipt_group_does_not_exist(backups):
    """Non-fatal: a backup that exists is worth more than a receipt
    directory with the right group on it. But silent is how the owner ends
    up with a pull that cannot write receipts and a prune that never
    runs."""
    done = backups('--full', env={'BACKUP_RECEIPT_GROUP': 'no-such-group-here'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert "cannot group-own" in done.stdout
    assert 'count-pruning will stop' in done.stdout
    assert stat.S_IMODE(backups.receipts.stat().st_mode) == 0o770, \
        'group-writable all the same, so placing the group by hand is all that is left'
    assert len(sorted((backups.dir / 'full').glob('*.tar.zst.age'))) == 1, \
        'and the backup itself happened'


@pytest.mark.skipif(os.geteuid() == 0,
                    reason='root is the path that can chgrp; this is the other one')
def test_a_non_root_backup_says_it_cannot_group_own_the_receipts(backups):
    done = backups('--full')
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'not root' in done.stdout and 'no setgid bit' in done.stdout


def test_a_backup_with_no_receipt_group_set_says_so_and_backs_up_anyway(backups):
    """BACKUP_RECEIPT_GROUP lost its default with the invented account
    name it was. Unset is not an error -- the archive is what matters --
    but it is said out loud, because until it is set the LAN's receipts
    cannot arrive and count-pruning stays off."""
    done = backups('--full', env={'BACKUP_RECEIPT_GROUP': ''})
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'BACKUP_RECEIPT_GROUP is not set' in done.stdout
    assert 'count-pruning stays off' in done.stdout
    assert stat.S_IMODE(backups.receipts.stat().st_mode) == 0o770
    assert len(sorted((backups.dir / 'full').glob('*.tar.zst.age'))) == 1, \
        'and the backup itself happened'


def test_count_pruning_waits_for_a_confirmed_off_vps_copy(backups):
    """"Keep 5" was deleting the sixth copy without anything having
    confirmed a second one exists. An archive nobody has receipted is the
    only copy there is, and the count is not a reason to delete it."""
    for index in range(4):
        if index:
            time.sleep(1.1)
        done = backups('--full', env={'BACKUP_KEEP': '2'})
        assert done.returncode == 0, done.stdout + done.stderr
    archives = sorted((backups.dir / 'full').glob('*.tar.zst.age'))
    assert len(archives) == 4, 'none of them is confirmed off the VPS, so none goes'
    assert 'no off-VPS receipt yet' in done.stdout
    assert 'only max-age=40d can remove it' in done.stdout

    # The LAN pulls and verifies them. Now the count may prune.
    for archive in archives:
        backups.receipt(archive)
    time.sleep(1.1)
    done = backups('--full', env={'BACKUP_KEEP': '2'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'off-VPS copy receipted' in done.stdout
    assert len(sorted((backups.dir / 'full').glob('*.tar.zst.age'))) == 2


def test_the_age_backstop_keeps_an_unreceipted_archive_nothing_newer_confirms(backups):
    """The age limit was deleting archives no confirmed off-VPS copy
    existed of, "because receipts can lag". They can lag for months -- a
    NAS off the network, a receipt key the owner never placed -- and in
    that state the age limit deletes the only copy there is, one run at a
    time. So an unreceipted archive is only ever aged out when something
    NEWER is confirmed to be off the box."""
    assert backups('--full').returncode == 0
    time.sleep(1.1)
    done = backups('--full', env={'BACKUP_MAX_AGE_DAYS': '-1'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'is past max-age=-1d but nothing newer is confirmed off-VPS; keeping it' in done.stdout
    assert 'fix the LAN pull' in done.stdout
    assert len(sorted((backups.dir / 'full').glob('*.tar.zst.age'))) == 2, \
        'both are kept: neither has a confirmed copy anywhere else'

    # Now the LAN confirms the newer one. A copy of something more recent
    # is off the VPS, so the old unreceipted archive may go.
    archives = sorted((backups.dir / 'full').glob('*.tar.zst.age'))
    backups.receipt(archives[-1])
    time.sleep(1.1)
    done = backups('--full', env={'BACKUP_MAX_AGE_DAYS': '-1', 'BACKUP_KEEP': '99'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'unreceipted but a newer archive is confirmed off-VPS' in done.stdout
    assert not archives[0].exists(), 'the oldest, unreceipted, now-covered archive goes'
    assert len(sorted((backups.dir / 'full').glob('*.tar.zst.age'))) >= 1, \
        'and the backstop never empties the directory'


def test_a_receipt_about_other_bytes_is_not_a_receipt(backups):
    """A receipt is a claim about bytes, not about a filename. One that
    records a hash the archive on this disk does not have is a stale
    receipt from a reused name, or a LAN host that verified something
    else -- and pruning on the strength of it deletes a copy nothing
    confirmed."""
    for index in range(4):
        if index:
            time.sleep(1.1)
        assert backups('--full', env={'BACKUP_KEEP': '2'}).returncode == 0
    archives = sorted((backups.dir / 'full').glob('*.tar.zst.age'))
    assert len(archives) == 4
    for archive in archives:
        backups.receipt(archive, digest='0' * 64)

    time.sleep(1.1)
    done = backups('--full', env={'BACKUP_KEEP': '2'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'the receipt is about other bytes, treating it as unreceipted' in done.stdout
    assert 'no off-VPS receipt yet' in done.stdout
    assert len(sorted((backups.dir / 'full').glob('*.tar.zst.age'))) == 5, \
        'nothing was pruned: every receipt is about bytes that are not here'

    # And a receipt filed under one archive's name but naming another is
    # the same thing: it is not about the archive it is filed under.
    (backups.receipts / f'{archives[0].name}.pulled').write_text(
        'archive: some-other-archive.tar.zst.age\nverified_by: a-lan-host\n'
        f'sha256: {hashlib.sha256(archives[0].read_bytes()).hexdigest()}\n')
    time.sleep(1.1)
    done = backups('--full', env={'BACKUP_KEEP': '2'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'its receipt does not name it; treating it as unreceipted' in done.stdout


def test_the_unconfirmed_copy_alert_fires_when_the_receipts_lag(backups):
    """Non-fatal, because a backup that exists only on the VPS is still
    better than no backup -- but silence here is how "mandatory off-VPS
    copy" became an accepted deviation in the first place."""
    assert backups('--full').returncode == 0
    time.sleep(1.1)
    done = backups('--full')
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'the off-VPS copy is unconfirmed' in done.stdout

    # Receipts for everything the pull has had time to fetch, and the
    # alert goes quiet: the newest archive is never receipted (it is
    # seconds old), so with one of the newest two confirmed the
    # "none of the newest two" condition no longer holds.
    for archive in (backups.dir / 'full').glob('*.tar.zst.age'):
        backups.receipt(archive)
    time.sleep(1.1)
    done = backups('--full')
    assert done.returncode == 0
    # The whole alert sentence, not just "unconfirmed": the pytest tmp
    # path embeds the test name, which contains that word, and stdout
    # prints the path being archived.
    assert 'the off-VPS copy is unconfirmed' not in done.stdout


def test_the_pre_deploy_wrapper_keeps_fourteen_in_its_own_namespace(backups):
    done = backups('pre_deploy_backup.sh')
    assert done.returncode == 0, done.stdout + done.stderr
    assert (backups.dir / 'pre-deploy').is_dir()
    assert done.stdout.count('keep=14') == 2, 'both halves, both retained for 14'
    assert not (backups.dir / 'full').exists(), 'a release backup is its own namespace'
    assert not (backups.dir / 'owner-data').exists()
    refused = backups('pre_deploy_backup.sh', '--owner-data')
    assert refused.returncode != 0
    assert 'takes no arguments' in refused.stdout


def test_the_pre_deploy_backup_covers_the_vault_the_migrations_rewrite(backups):
    """What this used to miss entirely. Migrations run at app startup, they
    rewrite the VAULT, and they have already run by the time the health
    check decides on a rollback -- so a pre-deploy backup of the pipeline
    generation alone covered the half a release cannot damage."""
    done = backups('pre_deploy_backup.sh')
    assert done.returncode == 0, done.stdout + done.stderr

    owner = sorted((backups.dir / 'pre-deploy-owner-data').glob('*.tar.zst.age'))
    assert len(owner) == 1, 'the prod vault is archived before a release, in its own namespace'
    body = owner[0].read_bytes()
    assert body.startswith(b'age-encrypted-stub'), 'through age, not around it'
    assert b'applications/app-1.yaml' in body, 'and it really holds the vault file'
    assert b'an-owner-edited-record' in body

    served = sorted((backups.dir / 'pre-deploy').glob('*.tar.zst.age'))
    assert len(served) == 1, 'and the served generation too, as before'
    assert b'MANIFEST' in served[0].read_bytes()
    assert 'the prod vault and the served generation are both archived' in done.stdout


def test_a_pre_deploy_backup_that_cannot_archive_the_vault_fails_the_release(backups, tmp_path):
    """Either half failing has to fail the whole thing: a release that
    cannot back up both halves is a release that must not start."""
    done = backups('pre_deploy_backup.sh',
                   env={'BACKUP_OWNER_SOURCE': str(tmp_path / 'absent')})
    assert done.returncode != 0
    assert 'nothing to back up' in done.stdout
    assert not (backups.dir / 'pre-deploy').exists(), \
        'and the second half is not attempted after the first fails'


def test_check_stale_is_the_alarm_for_a_job_that_stopped_running(backups):
    done = backups('--check-stale')
    assert done.returncode != 0
    assert 'no backup at all' in done.stdout

    assert backups('--full').returncode == 0
    assert backups('--owner-data', env={'BACKUP_OWNER_SOURCE': str(backups.source)}).returncode == 0
    done = backups('--check-stale')
    assert done.returncode == 0, done.stdout
    assert '-- full: newest backup 0d old' in done.stdout
    assert '-- owner-data: newest backup 0d old' in done.stdout

    done = backups('--check-stale', env={'BACKUP_STALE_FULL_DAYS': '-1'})
    assert done.returncode != 0
    assert 'over the -1d limit' in done.stdout


# --- the LAN pull ---------------------------------------------------------

def nas_archive(dest, namespace, name, body='age-encrypted-stub\nbody\n', manifest=True):
    """One archive on the LAN side, as rsync would have left it, with or
    without the `.sha256` the VPS writes beside it."""
    archive = dest / namespace / f'{namespace}_{name}.tar.zst.age'
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(body)
    if manifest:
        subprocess.run(['sha256sum', archive.name], cwd=archive.parent, check=True,
                       stdout=(archive.parent / f'{archive.name}.sha256').open('w'))
    return archive


def test_the_lan_pull_verifies_what_landed_and_sets_aside_what_does_not(lan, tmp_path):
    dest = tmp_path / 'nas'
    good = nas_archive(dest, 'full', '20261022T030000Z')
    nas_archive(dest, 'owner-data', '20261022T034500Z')
    tampered = nas_archive(dest, 'full', '20261022T040000Z')
    tampered.write_text('age-encrypted-stub\nsomething else entirely\n')

    done = lan('pull_backups_lan.sh', env=pull_env(lan, dest))
    assert done.returncode != 0, 'a checksum failure is a failed run'
    assert 'CHECKSUM FAILED' in done.stdout
    assert '1 archive(s) did not match their manifest' in done.stdout
    assert tampered.with_suffix('.age.unverified').is_file()
    assert not tampered.exists(), 'set aside, so the next run fetches it again'
    assert good.is_file()

    pulls = [line for line in lan.stub_log.read_text().splitlines() if line.startswith('rsync')]
    assert pulls, 'it did try to pull'
    assert '--ignore-existing' in pulls[0]
    for line in pulls:
        assert '--delete' not in line and '--remove-source-files' not in line, \
            'the LAN never deletes anything on the VPS'
        for flag in ('--no-links', '--no-devices', '--no-specials'):
            assert flag in line, f'{flag} missing from: {line}'


def test_the_lan_pull_fails_on_an_archive_it_cannot_verify(lan, tmp_path):
    """It used to count these as "awaiting their manifest" and exit 0. An
    archive whose `.sha256` never arrived is not an off-VPS copy; it is a
    file nobody can check, and the run that found it succeeded."""
    dest = tmp_path / 'nas'
    nas_archive(dest, 'full', '20261022T030000Z')
    nas_archive(dest, 'owner-data', '20261022T034500Z')
    unfinished = nas_archive(dest, 'full', '20261022T050000Z',
                             body='still being written\n', manifest=False)

    done = lan('pull_backups_lan.sh', env=pull_env(lan, dest))
    assert done.returncode != 0
    assert 'have no .sha256 manifest and cannot be verified' in done.stdout
    assert unfinished.name in done.stdout, 'and the alert names it'


def test_the_lan_pull_writes_a_receipt_back_for_every_archive_it_verified(lan, tmp_path):
    """The receipt is what lets prod prune by count without guessing
    whether a second copy exists. It is also the only thing this script
    writes on the VPS."""
    dest = tmp_path / 'nas'
    full = nas_archive(dest, 'full', '20261022T030000Z')
    owner = nas_archive(dest, 'owner-data', '20261022T034500Z')

    done = lan('pull_backups_lan.sh', env=pull_env(lan, dest))
    assert done.returncode == 0, done.stdout + done.stderr
    assert '2 verified' in done.stdout
    assert '2 receipt(s) written back' in done.stdout

    # STUB_INCOMING is where the stub rsync lands a push: the receipts
    # directory the VPS side would hold.
    receipts = sorted(path.name for path in lan.incoming.glob('*.pulled'))
    assert receipts == [f'{full.name}.pulled', f'{owner.name}.pulled']
    body = (lan.incoming / f'{full.name}.pulled').read_text()
    assert f'archive: {full.name}' in body
    assert 'verified_by:' in body
    assert f'sha256: {hashlib.sha256(full.read_bytes()).hexdigest()}' in body, \
        'the hash of the archive itself, which is what makes the receipt a claim ' \
        'about bytes rather than about a filename'

    # Two credentials, because one authorized_keys line carries one forced
    # command: the pull key cannot write and the receipt key cannot read.
    pushes = [line for line in lan.stub_log.read_text().splitlines()
              if line.startswith('rsync') and 'receipt_ed25519' in line]
    assert len(pushes) == 1, 'all the receipts in one transfer'
    assert 'id_ed25519' not in pushes[0].replace('receipt_ed25519', '')

    # FILES, and no directory metadata. `.receipts/` on the VPS belongs to
    # the backup account and is only group-writable for this key, so an
    # `rsync -a` of the directory would try to chown/chmod/utimes a
    # directory this account does not own -- which real rsync fails with
    # exit 23, however many receipts were verified.
    assert pushes[0].count('.pulled') == 2, 'the receipt files themselves, one path each'
    assert 'rsync -a ' not in pushes[0] and ' -a ' not in pushes[0]
    for flag in ('--no-perms', '--no-owner', '--no-group', '--no-times', '--chmod=F640'):
        assert flag in pushes[0], f'{flag} missing from: {pushes[0]}'


def test_the_lan_pull_refuses_a_manifest_that_vouches_for_another_file(lan, tmp_path):
    """A receipt has to prove THE NAMED ARCHIVE was verified. A `.sha256`
    that lists a different basename is not a manifest for this archive:
    `sha256sum -c` would go and hash whatever it names, and the receipt
    written afterwards would say these bytes had been checked when nothing
    had looked at them."""
    dest = tmp_path / 'nas'
    good = nas_archive(dest, 'full', '20261022T030000Z')
    nas_archive(dest, 'owner-data', '20261022T034500Z')
    liar = nas_archive(dest, 'full', '20261022T040000Z')
    (dest / 'full' / f'{liar.name}.sha256').write_text(
        f'{hashlib.sha256(liar.read_bytes()).hexdigest()}  {good.name}\n')

    done = lan('pull_backups_lan.sh', env=pull_env(lan, dest))
    assert done.returncode != 0
    assert f'MANIFEST MISMATCH: {liar.name}.sha256 vouches for' in done.stdout
    assert 'have a .sha256 manifest that names a different file' in done.stdout
    assert liar.is_file(), \
        'and it is left alone, not set aside: nothing has disagreed about its bytes'
    receipts = [path.name for path in lan.incoming.glob('*.pulled')]
    assert f'{liar.name}.pulled' not in receipts, 'no receipt for an archive nothing verified'
    assert f'{good.name}.pulled' in receipts, 'the ones that do check out still get theirs'


def test_the_lan_pull_checks_freshness_even_when_something_did_arrive(lan, tmp_path):
    """Freshness on EVERY run, not only on a run that pulled nothing. A
    pull that fetches today's owner-data archive while the newest full copy
    on the LAN is nine days old is not a healthy pull -- one of the two
    things prod cannot reproduce is not leaving the VPS, and "something
    arrived" was hiding it."""
    dest = tmp_path / 'nas'
    stale = nas_archive(dest, 'full', '20261013T030000Z')
    nine_days_ago = time.time() - 9 * 86400
    os.utime(stale, (nine_days_ago, nine_days_ago))

    # What the VPS still has to hand over: one fresh owner-data archive.
    vps_side = tmp_path / 'vps'
    nas_archive(vps_side, 'owner-data', '20261022T034500Z')

    done = lan('pull_backups_lan.sh', env=pull_env(lan, dest, STUB_VPS=str(vps_side)))
    assert done.returncode != 0, done.stdout + done.stderr
    assert '1 new archive(s), 2 verified' in done.stdout, 'it really did pull one'
    assert 'STALE full: the newest copy is 9d old' in done.stdout
    assert '1 archive(s) arrived, but the off-VPS copy is stale (full)' in done.stdout, \
        'and the alert names the class that is stale'
    assert '-- owner-data: newest copy 0d old' in done.stdout, 'the other half is fine'


def test_the_lan_pull_check_stale_is_the_alarm_for_backups_that_never_leave(lan, tmp_path):
    dest = tmp_path / 'nas'
    dest.mkdir()
    done = lan('pull_backups_lan.sh', '--check-stale', env=pull_env(lan, dest))
    assert done.returncode != 0
    assert 'STALE full: no copy at all' in done.stdout
    assert 'the off-VPS copy is stale' in done.stdout

    nas_archive(dest, 'full', '20261022T030000Z')
    nas_archive(dest, 'owner-data', '20261022T034500Z')
    done = lan('pull_backups_lan.sh', '--check-stale', env=pull_env(lan, dest))
    assert done.returncode == 0, done.stdout
    assert '-- full: newest copy 0d old' in done.stdout
    assert 'check-stale ok' in done.stdout

    done = lan('pull_backups_lan.sh', '--check-stale',
               env=pull_env(lan, dest, PULL_MAX_FULL_AGE_DAYS='-1'))
    assert done.returncode != 0
    assert 'over the -1d limit' in done.stdout

    # No credential is read for the alarm, so a missing key cannot silence it.
    assert 'no pull key' not in done.stdout


def test_the_lan_pull_fails_when_it_finds_nothing_new_and_nothing_recent(lan, tmp_path):
    """The run that used to say "0 archive(s) verified" and exit 0 -- the
    shape a pull takes for weeks after the VPS stopped letting it in."""
    dest = tmp_path / 'nas'
    dest.mkdir()
    done = lan('pull_backups_lan.sh', env=pull_env(lan, dest))
    assert done.returncode != 0
    assert '0 new archive(s), 0 verified' in done.stdout
    assert 'nothing new was pulled and the off-VPS copy is stale' in done.stdout


def test_the_lan_pull_names_the_variable_rather_than_guessing_an_account(lan, tmp_path):
    """Same contract as the sync's SYNC_USER: the restricted backup
    account on the VPS is one the owner created and named, so this script
    has no default for it and says which variable is missing."""
    dest = tmp_path / 'nas'
    nas_archive(dest, 'full', '20261022T030000Z')
    done = lan('pull_backups_lan.sh', env=pull_env(lan, dest, PULL_USER=''))
    assert done.returncode != 0
    assert 'PULL_USER is not set' in done.stdout
    assert 'name the restricted backup account you created' in done.stdout


def test_the_lan_pull_check_stale_needs_no_account_at_all(lan, tmp_path):
    # --check-stale reads the LAN side only: no connection, so no
    # credential and no account name. The alarm has to keep working on a
    # host that has not been given either.
    dest = tmp_path / 'nas'
    nas_archive(dest, 'full', '20261022T030000Z')
    done = lan('pull_backups_lan.sh', '--check-stale',
               env=pull_env(lan, dest, PULL_USER=''))
    assert 'PULL_USER is not set' not in done.stdout
    assert 'STALE owner-data' in done.stdout


def test_the_lan_pull_refuses_to_run_without_its_receipt_key(lan, tmp_path):
    dest = tmp_path / 'nas'
    nas_archive(dest, 'full', '20261022T030000Z')
    done = lan('pull_backups_lan.sh',
               env=pull_env(lan, dest, PULL_RECEIPT_SSH_KEY=str(tmp_path / 'absent')))
    assert done.returncode != 0
    assert 'no receipt key at' in done.stdout
    assert 'will not prune by count' in done.stdout


# --- the smoke test -------------------------------------------------------

@pytest.fixture
def smoke(tmp_path):
    stubs = tmp_path / 'smoke-bin'
    stubs.mkdir()
    write_executable(stubs / 'curl', CURL_STUB)
    env_file = tmp_path / 'prod.env'
    env_file.write_text('SMOKE_BASE_URL=https://app.career-os.test\n'
                        'SMOKE_EMAIL=tester@career-os.test\n'
                        "SMOKE_PASSWORD='correct horse battery staple'\n")
    env_file.chmod(0o640)
    log = tmp_path / 'curl.log'

    def run(*args, env=None):
        environment = {
            **os.environ,
            'PATH': f"{stubs}:{os.environ['PATH']}",
            'STUB_LOG': str(log),
            'STUB_BASE': 'https://app.career-os.test',
            'SMOKE_ENV_FILE': str(env_file),
            **(env or {}),
        }
        return subprocess.run(['bash', str(DEPLOY / 'smoke.sh'), *args],
                              capture_output=True, text=True, env=environment, timeout=120)

    run.log = log
    run.env_file = env_file
    return run


def test_smoke_signs_in_and_asserts_three_real_pages(smoke):
    done = smoke()
    assert done.returncode == 0, done.stdout + done.stderr
    assert '-- login ok' in done.stdout
    assert '-- GET / 200' in done.stdout
    assert '-- GET /jobs 200' in done.stdout
    assert '-- GET /jobs/channel-manager-job-030 200' in done.stdout, \
        'the detail page comes from the first link on the page it just loaded'
    assert 'smoke ok' in done.stdout


def test_the_smoke_password_never_reaches_argv(smoke):
    """A password on a command line is readable in /proc, and lands in the
    journal and in shell history. It goes in a 0600 file curl reads."""
    assert smoke().returncode == 0
    calls = smoke.log.read_text()
    assert 'correct horse battery staple' not in calls
    assert 'SMOKE_PASSWORD' not in calls
    login = next(line for line in calls.splitlines() if '/login' in line)
    assert '--data-binary' in login
    body = re.search(r'--data-binary @(\S+)', login).group(1)
    assert not Path(body).exists(), 'and the file is gone when the script is'


def test_smoke_names_the_step_that_failed(smoke):
    done = smoke('https://app.career-os.test/jobs')   # every path now 404s
    assert done.returncode != 0
    assert 'ALERT careeros-smoke: step login failed' in done.stdout

    smoke.env_file.write_text('SMOKE_EMAIL=tester@career-os.test\nSMOKE_PASSWORD=x\n')
    done = smoke()
    assert done.returncode != 0
    assert 'step env-file failed: no base URL' in done.stdout


def test_smoke_refuses_an_unreadable_env_file(smoke, tmp_path):
    done = smoke(env={'SMOKE_ENV_FILE': str(tmp_path / 'absent.env')})
    assert done.returncode != 0
    assert 'step env-file failed' in done.stdout
    assert 'is not readable' in done.stdout


# --- the chain onto the nightly ------------------------------------------

@pytest.fixture
def nightly(tmp_path):
    """The real nightly script, python stubbed, as test_nightly_pipeline does."""
    stub = write_executable(tmp_path / 'python-stub', NIGHTLY_PYTHON_STUB)
    data = tmp_path / 'nightly-data'
    (data / 'nightly').mkdir(parents=True)
    # -u matters: the child's "Serving HTTP ... port N" banner is the only
    # way to learn its port, but a pipe-attached stdout is block-buffered,
    # so without -u the line never flushes and the read below hangs.
    serving = subprocess.Popen(['python3', '-u', '-m', 'http.server', '0', '--bind', '127.0.0.1'],
                               cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True)
    port = None
    for line in serving.stdout:
        if 'port' in line:
            port = line.split('port')[1].split()[0].strip(' )')
            break

    def run(env=None):
        environment = {
            **os.environ,
            'NIGHTLY_PYTHON': str(stub),
            'NIGHTLY_DATA': str(data),
            'NIGHTLY_PROVIDERS': 'lever',
            'NIGHTLY_ATTEMPTS': '1',
            'NIGHTLY_BACKOFF': '0',
            'NIGHTLY_OLLAMA': f'http://127.0.0.1:{port}',
            'NIGHTLY_POOL': str(data / 'ats' / 'exports'
                                / f'golden_set_pool_{date.today().isoformat()}.yaml'),
            **(env or {}),
        }
        done = subprocess.run(['bash', str(PIPELINE)], capture_output=True, text=True,
                              env=environment, timeout=180)
        log = next(iter(sorted((data / 'nightly').glob('nightly_*.log'))), None)
        return done, (log.read_text() if log else '')

    yield run
    serving.terminate()


def test_with_the_flag_off_the_nightly_is_exactly_what_it_was(nightly):
    """A LAN-only install must not grow a prod sync by upgrading."""
    done, log = nightly()
    assert done.returncode == 0, done.stdout + done.stderr
    assert '== nightly finished, fails: none ==' in log
    assert 'sync' not in log, log
    assert 'sync' not in done.stdout
    assert log.rstrip().endswith('== nightly finished, fails: none ==')


def test_a_failed_sync_is_in_the_log_the_fails_line_and_the_exit_code(nightly, tmp_path):
    """And nothing the pipeline wrote changes: the sync only reads."""
    done, log = nightly(env={'SYNC_TO_PROD': '1', 'SYNC_DATA': str(tmp_path / 'no-data')})
    assert '== nightly finished, fails: none ==' in log, \
        'the night itself finished, which is what the sync reads as its manifest'
    assert 'ALERT careeros-vault-sync' in log
    assert '== sync FAILED' in log
    assert 'fails: sync' in log
    assert 'FAILED: sync' in done.stdout, 'and the owner hears about it'
    assert done.returncode == 1


def test_a_failed_night_syncs_nothing_at_all(nightly):
    done, log = nightly(env={'SYNC_TO_PROD': '1', 'NIGHTLY_PROVIDERS': 'bogus lever',
                             'NIGHTLY_OLLAMA': 'http://127.0.0.1:1'})
    assert 'FATAL: local LLM host' in log
    assert '-- sync skipped: the night ended with fails:' in log
    assert 'ALERT careeros-vault-sync' not in log
    assert done.returncode == 1
