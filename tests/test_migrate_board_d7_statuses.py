"""Protects scripts/migrate_board_d7_statuses.py: Withdrawn becomes
Stopped, a Closed job goes back where it was with the flag set, a dry run
writes nothing, and a second run has nothing left to do.

Fixture-only vaults; the live owner vault is never touched by tests.
"""
import importlib.util
from datetime import date
from pathlib import Path

import pytest

from careeros import vault

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'migrate_board_d7_statuses.py'
URL = 'https://fiction.example/job'


@pytest.fixture(scope='module')
def script():
    spec = importlib.util.spec_from_file_location('migrate_board_d7_statuses', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_retired(root, identifier, status, history=()):
    """Put a retired status, and the history behind it, onto a stored job.

    `vault.save_job` refuses both words now (decision D7), so a record
    this migration exists for has to be written the way the old path left
    it behind: the file itself.
    """
    path = next(Path(root, 'jobs').glob(f'*-{identifier.lower()}.yaml'))
    data = vault._read(path)
    data['status'] = status
    data['history'] = list(history)
    vault._write(path, data)
    return data


def moves(*pairs, gone=None):
    """A stored history: one status move per pair, and optionally a
    "posting gone" event on the given date."""
    history = [{'ts': f'2026-09-0{index + 1}T09:00:00+00:00', 'event': 'status_changed',
                'detail': f'{old} -> {new}'} for index, (old, new) in enumerate(pairs)]
    if gone:
        history.append({'ts': f'{gone}T07:30:00+00:00', 'event': 'posting_gone',
                        'detail': 'HTTP 404'})
    return history


@pytest.fixture
def vault_root(tmp_path):
    """Five jobs: a withdrawn one, a closed one whose history says where it
    was and when the posting went, a closed one with no history at all, a
    closed one that was withdrawn before it closed, and one already on the
    D7 list."""
    for kind in ('jobs', 'companies', 'experiences'):
        (tmp_path / kind).mkdir()
    for title in ('Quit Early', 'Closed With History', 'Closed Blank',
                  'Closed After Withdrawn', 'Still Open'):
        vault.save_job(tmp_path, {'title': title, 'url': f'{URL}/{title.lower()}'})
    identifiers = {job['title']: job['id'] for job in vault.list_jobs(tmp_path)}
    write_retired(tmp_path, identifiers['Quit Early'], 'withdrawn',
                  moves(('new', 'applied'), ('applied', 'withdrawn')))
    write_retired(tmp_path, identifiers['Closed With History'], 'closed',
                  moves(('new', 'interested'), ('interested', 'closed'), gone='2026-09-20'))
    write_retired(tmp_path, identifiers['Closed Blank'], 'closed')
    write_retired(tmp_path, identifiers['Closed After Withdrawn'], 'closed',
                  moves(('applied', 'withdrawn'), ('withdrawn', 'closed')))
    return tmp_path, identifiers


def stored(root):
    return {job['title']: (job['status'], job.get('closed'), job.get('closed_at'))
             for job in vault.list_jobs(root)}


# --- what the rules say ---------------------------------------------------

def test_withdrawn_becomes_stopped(script, vault_root):
    root, _ = vault_root
    rows = script.plan(list(script.records(root)), date(2026, 10, 15))
    row = next(row for row in rows if row['status'] == 'withdrawn')
    assert row['new_status'] == 'stopped'
    assert row['updates'] == {'status': 'stopped'}


def test_a_closed_job_goes_back_to_where_history_says_it_was(script, vault_root):
    root, identifiers = vault_root
    rows = script.plan(list(script.records(root)), date(2026, 10, 15))
    row = next(row for row in rows if row['id'] == identifiers['Closed With History'])
    assert row['new_status'] == 'interested'
    assert row['source'] == script.FROM_HISTORY
    assert row['updates']['closed'] is True


def test_a_closed_job_with_no_history_becomes_new(script, vault_root):
    root, identifiers = vault_root
    rows = script.plan(list(script.records(root)), date(2026, 10, 15))
    row = next(row for row in rows if row['id'] == identifiers['Closed Blank'])
    assert row['new_status'] == 'new'
    assert row['source'] == script.FROM_DEFAULT


def test_a_status_read_from_history_is_renamed_too(script, vault_root):
    """A job that was withdrawn and then closed comes back as stopped:
    Withdrawn is a rename, wherever the word is read from."""
    root, identifiers = vault_root
    rows = script.plan(list(script.records(root)), date(2026, 10, 15))
    row = next(row for row in rows if row['id'] == identifiers['Closed After Withdrawn'])
    assert row['new_status'] == 'stopped'


def test_the_last_move_into_closed_decides(script):
    """A job closed, put back and closed again comes back to where it was
    the second time."""
    job = {'id': 'JOB-009', 'status': 'closed',
            'history': moves(('new', 'closed'), ('closed', 'applied'), ('applied', 'closed'))}
    assert script.status_before_closed(job) == 'applied'


def test_the_closed_date_comes_from_the_posting_gone_event(script, vault_root):
    root, identifiers = vault_root
    rows = script.plan(list(script.records(root)), date(2026, 10, 15))
    row = next(row for row in rows if row['id'] == identifiers['Closed With History'])
    assert row['closed_at'] == '2026-09-20'
    assert row['closed_at_source'] == 'posting gone event'


def test_without_a_posting_gone_event_the_closed_date_is_the_migration_date(script, vault_root):
    root, identifiers = vault_root
    rows = script.plan(list(script.records(root)), date(2026, 10, 15))
    row = next(row for row in rows if row['id'] == identifiers['Closed Blank'])
    assert row['closed_at'] == '2026-10-15'
    assert row['closed_at_source'] == 'migration date'


def test_the_first_posting_gone_event_is_the_day_it_went(script):
    job = {'id': 'JOB-009', 'history': [
        {'ts': '2026-09-10T07:00:00+00:00', 'event': 'posting_gone', 'detail': 'HTTP 404'},
        {'ts': '2026-09-30T07:00:00+00:00', 'event': 'posting_gone', 'detail': 'HTTP 410'}]}
    assert script.posting_gone_date(job) == '2026-09-10'


def test_a_job_already_on_the_d7_list_is_left_alone(script, vault_root):
    root, identifiers = vault_root
    rows = script.plan(list(script.records(root)), date(2026, 10, 15))
    assert identifiers['Still Open'] not in [row['id'] for row in rows]


# --- the run and its report ----------------------------------------------

def test_a_dry_run_writes_nothing(script, vault_root, capsys):
    root, _ = vault_root
    before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
    script.main(['--vault', str(root)])
    assert {path: path.read_bytes() for path in root.rglob('*') if path.is_file()} == before
    assert 'DRY RUN: nothing was written' in capsys.readouterr().out


def test_the_report_is_printed_in_both_modes(script, vault_root, capsys):
    """The move report comes before any write, so an apply can never put
    through a move the run did not show."""
    root, _ = vault_root
    script.main(['--vault', str(root)])
    dry = capsys.readouterr().out
    script.main(['--vault', str(root), '--apply'])
    applied = capsys.readouterr().out
    for output in (dry, applied):
        assert 'before : new=1, closed=3, withdrawn=1  |  closed flag set: 0' in output
        assert 'moved 1: withdrawn -> stopped' in output
        assert 'moved 1: closed -> interested' in output
        assert 'moved 1: closed -> new' in output
        assert 'moved 1: closed -> stopped' in output
        assert 'after  : new=2, interested=1, stopped=2  |  closed flag set: 3' in output
        assert '5 jobs: 1 renamed, 3 un-closed, 1 already on the D7 list' in output
    assert applied.index('before :') < applied.index('wrote 4 record(s)')


def test_the_report_counts_before_and_after(script, vault_root, capsys):
    root, _ = vault_root
    script.main(['--vault', str(root)])
    lines = capsys.readouterr().out.splitlines()
    before = next(line for line in lines if line.startswith('before'))
    after = next(line for line in lines if line.startswith('after'))
    assert 'withdrawn=1' in before and 'closed=3' in before
    assert 'withdrawn' not in after and 'closed=' not in after
    assert 'closed flag set: 0' in before and 'closed flag set: 3' in after


def test_an_apply_moves_every_job_onto_the_d7_list(script, vault_root, capsys):
    root, _ = vault_root
    script.main(['--vault', str(root), '--apply'])
    assert 'wrote 4 record(s)' in capsys.readouterr().out
    assert stored(root) == {
        'Quit Early': ('stopped', False, None),
        'Closed With History': ('interested', True, '2026-09-20'),
        'Closed Blank': ('new', True, date.today().isoformat()),
        'Closed After Withdrawn': ('stopped', True, date.today().isoformat()),
        'Still Open': ('new', False, None),
    }
    assert {job['status'] for job in vault.list_jobs(root)} <= set(vault.STATUSES)


def test_a_second_apply_changes_nothing(script, vault_root, capsys):
    root, _ = vault_root
    script.main(['--vault', str(root), '--apply'])
    capsys.readouterr()
    before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
    script.main(['--vault', str(root), '--apply'])
    assert {path: path.read_bytes() for path in root.rglob('*') if path.is_file()} == before
    assert 'nothing to change' in capsys.readouterr().out


def test_the_migration_leaves_history_as_it_was(script, vault_root):
    """History records what happened, so an event written while Closed was
    a status keeps its own words."""
    root, identifiers = vault_root
    before = vault.load_job(root, identifiers['Closed With History'])['history']
    script.main(['--vault', str(root), '--apply'])
    assert vault.load_job(root, identifiers['Closed With History'])['history'] == before


def test_a_migrated_job_is_readable_through_the_ordinary_save_path(script, vault_root):
    """The point of the migration: a record the vault would have refused
    saves again afterwards."""
    root, identifiers = vault_root
    script.main(['--vault', str(root), '--apply'])
    identifier = identifiers['Closed With History']
    saved = vault.save_job(root, {'end_reason': 'Posting closed', 'status': 'stopped'}, identifier)
    assert saved['status'] == 'stopped'
    assert saved['closed'] is True


def test_the_vault_can_come_from_the_environment(script, vault_root, monkeypatch, capsys):
    root, _ = vault_root
    monkeypatch.setenv('CAREEROS_VAULT', str(root))
    script.main([])
    assert f'vault={root}' in capsys.readouterr().out


def test_a_run_with_no_vault_stops(script, monkeypatch):
    monkeypatch.delenv('CAREEROS_VAULT', raising=False)
    with pytest.raises(SystemExit):
        script.main([])


def test_a_path_that_is_not_a_vault_stops(script, tmp_path, monkeypatch):
    monkeypatch.delenv('CAREEROS_VAULT', raising=False)
    with pytest.raises(SystemExit):
        script.main(['--vault', str(tmp_path / 'nowhere')])


def test_a_record_that_cannot_be_written_is_skipped_and_the_run_fails(script, vault_root, monkeypatch, capsys):
    root, _ = vault_root

    def refuse(path, data):
        raise OSError('disk is full')

    monkeypatch.setattr(vault, '_write', refuse)
    with pytest.raises(SystemExit):
        script.main(['--vault', str(root), '--apply'])
    assert 'wrote 0 record(s)' in capsys.readouterr().out


def test_an_id_less_record_is_left_untouched_and_never_writes_onto_another(script, vault_root, capsys):
    """A retired status in a record with no id must not be planned, and
    must not make the sweep write its plan onto a healthy record: the
    row that used to be joined back by id would land on whichever file
    the id key resolved to (review MUST-FIX 1, 2026-10-15)."""
    root, _ = vault_root
    orphan = Path(root, 'jobs', 'zzz-orphan.yaml')
    orphan.write_text("title: Orphan\nurl: https://fiction.example/orphan\nstatus: closed\n")

    rows = script.plan(list(script.records(root)), date(2026, 10, 15))
    assert all(row.get('id') for row in rows)
    assert 'zzz-orphan.yaml' not in [row['path'].name for row in rows]
    assert 'no id' in capsys.readouterr().err

    script.main(['--vault', str(root), '--apply'])
    assert 'status: closed' in orphan.read_text()
