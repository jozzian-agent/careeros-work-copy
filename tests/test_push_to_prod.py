"""push_to_prod.sh: fixture tests with a fake rsync (no real upload ever).

The shim records every rsync invocation and replays canned output, so the
tests prove the ORDER (dry-run pre-flight, payload, COMPLETE last), the
refusals (manifest mismatch, non-empty target) and the absence of any
delete flag — all without a network.
"""
import hashlib
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'deploy' / 'push_to_prod.sh'

# The REAL shape of an upload's itemized dry-run output, captured 2026-11-04
# against the live rrsync target: an upload's creations start with `<f`
# (sending), NOT `>f` (receiving), and rsync prints a `created directory`
# info line when the generation directory is new. Fixtures that canned
# `>f+++` let a classifier accepting only `>f+++` ship: it counted all four
# of these lines as "updates" and refused a perfectly new generation.
CREATION_ONLY = (
    'created directory 2026-11-03T151246Z\n'
    'cd+++++++++ ./\n'
    '<f+++++++++ MANIFEST\n'
    '<f+++++++++ classification.yaml\n'
    '<f+++++++++ pool.yaml\n'
)
# Receiving-direction creations are legal too (a local-path variant).
CREATION_ONLY_RECEIVE = (
    '>f+++++++++ pool.yaml\n'
    '>f+++++++++ classification.yaml\n'
    '>f+++++++++ MANIFEST\n'
    'cd+++++++++ ./\n'
)
# An update, not a creation -- in EITHER direction this is a refusal: the
# generation name is taken or half-populated.
NON_EMPTY_TARGET = (
    '<f+++++++++ pool.yaml\n'
    '<f.st...... classification.yaml\n'
)
NON_EMPTY_TARGET_RECEIVE = (
    '>f+++++++++ pool.yaml\n'
    '>f.st...... classification.yaml\n'   # an update, not a creation
)
DELETION_LINE = '*deleting old.yaml\n<f+++++++++ pool.yaml\n'


@pytest.fixture()
def env(tmp_path):
    """A staged export, a fake key, and a fake-rsync shim on PATH."""
    export_root = tmp_path / 'prod-export'
    day = '2026-11-03'
    d = export_root / day
    d.mkdir(parents=True)
    pool = {'day': day, 'postings': [{'key': 'lever:a:1', 'title': 'T'}]}
    run = {'day': day, 'postings': [{'key': 'lever:a:1', 'values': {}}]}
    (d / 'pool.yaml').write_text(yaml.safe_dump(pool))
    (d / 'classification.yaml').write_text(yaml.safe_dump(run))
    lines = ['# careeros prod-export manifest', f'day: {day}',
             f'postings: {len(pool["postings"])}', '--']
    for name in ('pool.yaml', 'classification.yaml'):
        digest = hashlib.sha256((d / name).read_bytes()).hexdigest()
        lines.append(f'{digest}  {name}')
    (d / 'MANIFEST').write_text('\n'.join(lines) + '\n')

    keydir = tmp_path / 'key'
    keydir.mkdir(mode=0o700)
    key = keydir / 'id_ed25519'
    key.write_text('fake private key material\n')
    key.chmod(0o600)
    known = tmp_path / 'known_hosts'
    known.write_text('fake.host ssh-ed25519 AAAAfake\n')

    shimdir = tmp_path / 'shim'
    shimdir.mkdir()
    log = tmp_path / 'rsync-calls.log'
    shim = shimdir / 'rsync'
    shim.write_text(f'''#!/bin/bash
echo "CALL: $*" >>{log}
dry=0
for a in "$@"; do [[ $a == "--dry-run" || $a == "-ni" ]] && dry=1; done
if (( dry )); then
  cat "${{FAKE_DRY_OUT:-/dev/null}}"
  exit ${{FAKE_DRY_RC:-0}}
fi
echo "Total transferred file size: 12,345 bytes"
exit ${{FAKE_SEND_RC:-0}}
''')
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

    e = dict(os.environ)
    e.update({
        'PATH': f'{shimdir}:{e["PATH"]}',
        'SYNC_HOST': 'fake.example.invalid',
        'SYNC_USER': 'careeros-push',
        'SYNC_SSH_KEY': str(key),
        'SYNC_KNOWN_HOSTS': str(known),
        'EXPORT_ROOT': str(export_root),
        'FAKE_DRY_OUT': str(tmp_path / 'dry.out'),
        'FAKE_RSYNC_LOG': str(log),
    })
    (tmp_path / 'dry.out').write_text(CREATION_ONLY)
    return {'env': e, 'log': log, 'day': day, 'export': d,
            'root': export_root, 'tmp': tmp_path, 'dry_file': tmp_path / 'dry.out'}


def run_push(env, *args):
    return subprocess.run([str(SCRIPT), env['day'], *args],
                          capture_output=True, text=True, env=env['env'])


def calls(env):
    if not env['log'].exists():
        return []
    return env['log'].read_text().splitlines()


def test_happy_path_complete_is_last_and_receipt_written(env):
    r = run_push(env)
    assert r.returncode == 0, r.stderr
    c = calls(env)
    assert len(c) == 3, c
    assert '--dry-run' in c[0]                      # pre-flight first
    assert '--dry-run' not in c[1]                  # payload second
    assert 'COMPLETE' in c[2]                       # marker LAST
    assert '/COMPLETE' in c[2] and '--dry-run' not in c[2]
    assert 'manifest ok' in r.stdout
    assert 'push ok' in r.stdout
    assert '12345' in r.stdout or '12,345' in r.stdout  # bytes reported
    receipt = (env['root'] / 'push-receipts.log').read_text()
    assert f"gen={env['day']}T" in receipt and 'postings=1' in receipt


def test_no_invocation_ever_carries_a_delete_flag(env):
    r = run_push(env)
    assert r.returncode == 0, r.stderr
    for line in calls(env):
        assert '--delete' not in line
        assert '--max-delete' not in line


def test_manifest_mismatch_refuses_before_any_rsync(env):
    p = env['export'] / 'pool.yaml'
    p.write_text(p.read_text() + '# tampered\n')
    r = run_push(env)
    assert r.returncode != 0
    assert 'checksum mismatch' in r.stderr
    assert calls(env) == []          # nothing reached the wire
    assert not (env['root'] / 'push-receipts.log').exists()


def test_existing_generation_refuses_no_overwrite(env):
    env['dry_file'].write_text(NON_EMPTY_TARGET)
    r = run_push(env)
    assert r.returncode != 0
    assert 'not empty' in r.stderr
    c = calls(env)
    assert len(c) == 1 and '--dry-run' in c[0]   # only the pre-flight ran
    assert not (env['root'] / 'push-receipts.log').exists()


def test_existing_generation_refuses_receive_direction_too(env):
    """The update tail is foreign whichever direction character it wears."""
    env['dry_file'].write_text(NON_EMPTY_TARGET_RECEIVE)
    r = run_push(env)
    assert r.returncode != 0
    assert 'not empty' in r.stderr
    assert len(calls(env)) == 1


def test_receive_direction_creations_are_allowed(env):
    env['dry_file'].write_text(CREATION_ONLY_RECEIVE)
    r = run_push(env, '--dry-run')
    assert r.returncode == 0, r.stderr
    assert 'nothing sent, no receipt written' in r.stdout


def test_payload_transfer_carries_ignore_existing(env):
    """Belt-and-braces: no transfer may overwrite an existing remote file."""
    r = run_push(env)
    assert r.returncode == 0, r.stderr
    c = calls(env)
    assert '--ignore-existing' not in c[0]      # the pre-flight stays strict
    assert '--ignore-existing' in c[1]          # payload cannot overwrite
    assert '--ignore-existing' not in c[2]      # COMPLETE travels alone


def test_deletion_in_preflight_refuses(env):
    env['dry_file'].write_text(DELETION_LINE)
    r = run_push(env)
    assert r.returncode != 0
    assert 'never deletes' in r.stderr
    assert len(calls(env)) == 1


def test_dry_run_writes_nothing_remotely_and_no_receipt(env):
    r = run_push(env, '--dry-run')
    assert r.returncode == 0, r.stderr
    c = calls(env)
    assert len(c) == 1 and '--dry-run' in c[0]
    assert 'nothing sent, no receipt written' in r.stdout
    assert env['day'] + 'T' in r.stdout              # generation named
    assert not (env['root'] / 'push-receipts.log').exists()


def test_preflight_failure_is_not_swallowed(env):
    env['env']['FAKE_DRY_RC'] = '12'
    r = run_push(env)
    assert r.returncode != 0
    assert 'pre-flight dry run failed' in r.stderr
    assert len(calls(env)) == 1


def test_payload_failure_means_no_complete_marker(env):
    env['env']['FAKE_SEND_RC'] = '11'
    r = run_push(env)
    assert r.returncode != 0
    assert 'COMPLETE' not in ''.join(calls(env)[1:])   # marker never sent
    assert not (env['root'] / 'push-receipts.log').exists()


def test_missing_host_is_a_usage_error(env):
    del env['env']['SYNC_HOST']
    # Point the fallback at a nonexistent path: the real /etc/careeros/push-host
    # may exist on the machine running the tests (it does in production).
    env['env']['PUSH_HOST_FILE'] = str(env['tmp'] / 'no-such-push-host')
    r = run_push(env)
    assert r.returncode != 0
    assert 'SYNC_HOST' in r.stderr
    assert calls(env) == []


def test_loose_key_modes_refuse(env):
    env['env']['SYNC_SSH_KEY']  # fixture key is 600 in a 700 dir
    k = Path(env['env']['SYNC_SSH_KEY'])
    k.chmod(0o644)
    r = run_push(env)
    assert r.returncode != 0
    assert 'must be 600' in r.stderr
    assert calls(env) == []


def test_bad_date_argument_is_usage(env):
    r = subprocess.run([str(SCRIPT), 'not-a-date'],
                       capture_output=True, text=True, env=env['env'])
    assert r.returncode == 2
    assert 'usage' in r.stderr
