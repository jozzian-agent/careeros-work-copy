"""The ownership migration (CAREER-39 M2): that it gives every ownerless
job and experience to the admin, that it leaves a record which already
names an owner alone, that it touches nothing shared, that it writes
nothing in a dry run, and that running it twice changes nothing the
second time."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import migrate_record_owner as migrate  # noqa: E402

from careeros import users, vault  # noqa: E402

PASSWORD = 'correct horse battery staple'


@pytest.fixture
def legacy(tmp_path):
    """A vault as it stood before the split: one admin account, two jobs
    and one position that name no owner, one shared company, and one tag
    registry."""
    root = tmp_path / 'vault'
    root.mkdir()
    users.create_user(root, email='owner@example.test', name='Owner',
                      role='admin', password=PASSWORD)
    vault.save_job(root, {'title': 'Legacy Role', 'url': 'https://example.test/a'})
    vault.save_job(root, {'title': 'Another Legacy Role', 'url': 'https://example.test/b'})
    vault.save_experience(root, {'title': 'Legacy Position', 'company': 'Old Place',
                                 'start': '2015-01', 'end': '2016-01'})
    vault.save_company(root, {'name': 'Shared Holdings'})
    vault.save_tags(root, vault.default_tags())
    return root


def admin_id(root):
    return users.admins(root)[0]['id']


def owners(root):
    """Every private record's stored owner, by record id."""
    return {record['id']: record.get(vault.OWNER_FIELD)
            for record in vault.list_jobs(root) + vault.list_experiences(root)}


# --- the plan -------------------------------------------------------------

def test_every_ownerless_record_is_planned_for_the_admin(legacy):
    rows = migrate.plan(legacy, admin_id(legacy))
    assert sorted(row['id'] for row in rows) == ['EXP-001', 'JOB-001', 'JOB-002']
    assert {row['kind'] for row in rows} == {'jobs', 'experiences'}
    assert all(row['updates'] == {vault.OWNER_FIELD: admin_id(legacy)} for row in rows)


def test_a_record_that_already_names_an_owner_is_not_planned(legacy):
    vault.save_job(legacy, {vault.OWNER_FIELD: 'USER-009'}, 'JOB-001')
    rows = migrate.plan(legacy, admin_id(legacy))
    assert sorted(row['id'] for row in rows) == ['EXP-001', 'JOB-002']


def test_a_vault_with_no_admin_stops_rather_than_guessing(tmp_path):
    root = tmp_path / 'vault'
    root.mkdir()
    vault.save_job(root, {'title': 'Legacy Role', 'url': 'https://example.test/a'})
    with pytest.raises(SystemExit) as stop:
        migrate.resolve_owner(root)
    assert 'no admin account' in str(stop.value)


def test_a_vault_with_two_admins_asks_which_one(legacy):
    users.create_user(legacy, email='second@example.test', name='Second',
                      role='admin', password=PASSWORD)
    with pytest.raises(SystemExit) as stop:
        migrate.resolve_owner(legacy)
    assert '--owner' in str(stop.value)


def test_an_explicit_owner_has_to_exist(legacy):
    with pytest.raises(SystemExit) as stop:
        migrate.resolve_owner(legacy, 'USER-404')
    assert 'USER-404' in str(stop.value)


def test_an_explicit_owner_wins_over_the_admin(legacy):
    tester = users.create_user(legacy, email='one@example.test', name='Tester One',
                               role='tester', password=PASSWORD)
    assert migrate.resolve_owner(legacy, tester['id']) == tester['id']


# --- the run --------------------------------------------------------------

def test_a_dry_run_writes_nothing(legacy, capsys):
    assert migrate.main(['--vault', str(legacy)]) == 0
    assert set(owners(legacy).values()) == {None}
    assert 'DRY RUN' in capsys.readouterr().out


def test_applying_assigns_every_existing_record_to_the_admin(legacy, capsys):
    assert migrate.main(['--vault', str(legacy), '--apply']) == 0
    assert set(owners(legacy).values()) == {admin_id(legacy)}
    assert 'wrote 3 record(s)' in capsys.readouterr().out


def test_running_it_twice_changes_nothing(legacy, capsys):
    migrate.main(['--vault', str(legacy), '--apply'])
    before = {path.name: path.read_bytes()
              for kind in migrate.KINDS for path in sorted((legacy / kind).glob('*.yaml'))}
    capsys.readouterr()
    assert migrate.main(['--vault', str(legacy), '--apply']) == 0
    after = {path.name: path.read_bytes()
             for kind in migrate.KINDS for path in sorted((legacy / kind).glob('*.yaml'))}
    assert after == before
    assert 'nothing to change' in capsys.readouterr().out


def test_a_record_that_belongs_to_a_tester_survives_the_sweep(legacy):
    vault.save_job(legacy, {vault.OWNER_FIELD: 'USER-009'}, 'JOB-001')
    migrate.main(['--vault', str(legacy), '--apply'])
    assert owners(legacy)['JOB-001'] == 'USER-009'
    assert owners(legacy)['JOB-002'] == admin_id(legacy)


def test_nothing_shared_is_touched(legacy):
    shared = {name: (legacy / name).read_bytes() for name in ('tags.yaml',)}
    companies = {path.name: path.read_bytes() for path in (legacy / 'companies').glob('*.yaml')}
    migrate.main(['--vault', str(legacy), '--apply'])
    assert {name: (legacy / name).read_bytes() for name in shared} == shared
    assert {path.name: path.read_bytes()
            for path in (legacy / 'companies').glob('*.yaml')} == companies


def test_only_the_owner_field_is_written(legacy):
    before = yaml.safe_load(next((legacy / 'jobs').glob('*job-001.yaml')).read_text())
    migrate.main(['--vault', str(legacy), '--apply'])
    after = yaml.safe_load(next((legacy / 'jobs').glob('*job-001.yaml')).read_text())
    assert after.pop(vault.OWNER_FIELD) == admin_id(legacy)
    assert after == {key: value for key, value in before.items() if key != vault.OWNER_FIELD}


def test_a_vault_that_is_not_one_stops(tmp_path, capsys):
    with pytest.raises(SystemExit) as stop:
        migrate.main(['--vault', str(tmp_path / 'nowhere')])
    assert 'does not look like a CareerOS vault' in str(stop.value)


def test_no_vault_named_stops(monkeypatch):
    monkeypatch.delenv('CAREEROS_VAULT', raising=False)
    with pytest.raises(SystemExit) as stop:
        migrate.main([])
    assert 'no vault given' in str(stop.value)


def test_a_vault_with_no_experiences_directory_still_migrates(tmp_path):
    """A vault may hold jobs and no positions at all."""
    root = tmp_path / 'vault'
    root.mkdir()
    users.create_user(root, email='owner@example.test', name='Owner',
                      role='admin', password=PASSWORD)
    vault.save_job(root, {'title': 'Legacy Role', 'url': 'https://example.test/a'})
    assert migrate.main(['--vault', str(root), '--apply']) == 0
    assert owners(root)['JOB-001'] == admin_id(root)


# --- Tombstones are not records the migration has to own ---------------

@pytest.fixture
def with_tombstones(legacy):
    """The legacy vault after a delete of each private kind, so every
    record directory holds an id-reservation tombstone."""
    migrate.main(['--vault', str(legacy), '--apply'])
    assert vault.delete_job(legacy, 'JOB-002') is True
    assert vault.delete_experience(legacy, 'EXP-001') is True
    for kind in ('jobs', 'experiences'):
        assert list((legacy / kind).glob(f'{vault.RESERVED_PREFIX}*.yaml')), kind
    return legacy


def test_a_rerun_does_not_count_a_tombstone_as_a_record_to_own(with_tombstones, capsys):
    """A tombstone holds a number, not a job, so it needs no owner and
    must not be reported as one waiting for a backfill."""
    capsys.readouterr()
    assert migrate.main(['--vault', str(with_tombstones), '--apply']) == 0
    out = capsys.readouterr().out
    assert 'nothing to change, every job and experience already names its owner' in out
    # Counted over the records that are left -- JOB-001 alone, since the
    # fixture deleted the other job and the one position -- never over
    # the two tombstones they left behind.
    assert '1 private record(s)' in out
    assert 'JOB-002' not in out and 'EXP-001' not in out
    # And no tombstone gained an owner_id or anything else.
    stones = {path.name: vault._read(path) for kind in ('jobs', 'experiences')
              for path in (with_tombstones / kind).glob(f'{vault.RESERVED_PREFIX}*.yaml')}
    assert sorted(stones) == ['_reserved-exp-001.yaml', '_reserved-job-002.yaml']
    assert sorted(stones.values(), key=lambda d: d['id']) == [
        {'id': 'EXP-001', 'reserved': True}, {'id': 'JOB-002', 'reserved': True}]


def test_a_rerun_leaves_the_counters_correct_with_tombstones(with_tombstones, capsys):
    """The counter marks read the directory raw, so a reserved number is
    still part of the high-water mark and a rerun records nothing new."""
    before = (with_tombstones / vault.ID_COUNTER_FILE).read_bytes()
    capsys.readouterr()
    assert migrate.main(['--vault', str(with_tombstones), '--apply']) == 0
    assert 'already records every id high-water mark' in capsys.readouterr().out
    assert (with_tombstones / vault.ID_COUNTER_FILE).read_bytes() == before
    # The deleted numbers are still out of circulation afterwards.
    assert vault.next_job_id(with_tombstones) == 'JOB-003'
    assert vault._next(with_tombstones, 'experiences') == 'EXP-002'


def test_the_migration_seeds_counters_from_tombstones_too(legacy):
    """A vault whose counter file is gone but whose tombstones remain:
    the seeding has to read the reserved numbers, or it would seed a mark
    below one already handed out."""
    migrate.main(['--vault', str(legacy), '--apply'])
    vault.delete_job(legacy, 'JOB-002')
    (legacy / vault.ID_COUNTER_FILE).unlink()
    assert migrate.plan_id_counters(legacy)['jobs'] == 2
    assert migrate.main(['--vault', str(legacy), '--apply']) == 0
    assert vault._read(legacy / vault.ID_COUNTER_FILE)['jobs'] == 2
    assert vault.next_job_id(legacy) == 'JOB-003'
