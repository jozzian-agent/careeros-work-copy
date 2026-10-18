"""The value-record migration (CAREER-57): that it adds the coded half
of a job record without touching the free-text half, that an owner's own
value survives it, that it writes nothing in a dry run, and that running
it twice changes nothing the second time."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import migrate_job_value_records as migrate  # noqa: E402

from careeros import taxonomy, vault  # noqa: E402


@pytest.fixture
def filled(tmp_path):
    """A vault with three jobs: one plain, one the owner edited by hand,
    one a model wrote the same field on."""
    (tmp_path / 'jobs').mkdir()
    vault.save_job(tmp_path, {'title': 'Senior Java-Entwickler/in 80-100%',
                              'url': 'https://example.test/a', 'location': '8001 Zürich',
                              'description': 'Wir suchen eine erfahrene Person. Festanstellung.'})
    vault.save_job(tmp_path, {'title': 'Junior Developer', 'url': 'https://example.test/b',
                              'seniority': 'director',
                              'field_provenance': {'seniority': 'user'}})
    vault.save_job(tmp_path, {'title': 'Junior Developer', 'url': 'https://example.test/c',
                              'seniority': 'director',
                              'field_provenance': {'seniority': 'llm'}})
    return tmp_path


def rows_for(root):
    return migrate.plan(list(migrate.records(root)))


def job_by_url(root, url):
    return next(job for job in vault.list_jobs(root) if job['url'] == url)


# --- the plan -------------------------------------------------------------

def test_every_job_gains_a_record_for_every_field(filled):
    rows = rows_for(filled)
    assert len(rows) == 3
    assert set(rows[0]['updates']['values']) == set(migrate.rules.FIELDS)


def test_a_settled_field_carries_the_phrase_that_decided_it(filled):
    row = next(row for row in rows_for(filled) if 'occupation_family' in row['settled'])
    record = row['updates']['values']['occupation_family']
    assert record['source'] == 'rule'
    assert record['evidence']['phrase']
    assert record['taxonomy_version']


def test_an_owner_written_free_text_field_wins_over_the_rules_layer(filled):
    rows = {row['id']: row for row in rows_for(filled)}
    owner = job_by_url(filled, 'https://example.test/b')
    record = rows[owner['id']]['updates']['values']['seniority']
    assert (record['value'], record['source']) == ('s5', 'user')


def test_a_model_written_free_text_field_does_not_win(filled):
    """The pipeline re-reads the posting anyway; pinning an old model's
    answer in place as though a person made it is what precedence exists
    to prevent."""
    rows = {row['id']: row for row in rows_for(filled)}
    machine = job_by_url(filled, 'https://example.test/c')
    record = rows[machine['id']]['updates']['values']['seniority']
    assert (record['value'], record['source']) == ('s1', 'rule')


# --- writing --------------------------------------------------------------

def test_a_dry_run_writes_nothing(filled, capsys):
    before = {path: path.read_bytes() for path in (filled / 'jobs').glob('*.yaml')}
    assert migrate.main(['--vault', str(filled)]) == 0
    assert {path: path.read_bytes() for path in (filled / 'jobs').glob('*.yaml')} == before
    assert 'DRY RUN' in capsys.readouterr().out


def test_applying_writes_the_values_and_the_app_can_still_read_them(filled):
    assert migrate.main(['--vault', str(filled), '--apply']) == 0
    job = job_by_url(filled, 'https://example.test/a')
    assert job['values']['occupation_family']['value'] == 'software-developer'
    assert job['values']['workload_min']['value'] == '80'
    # The record still loads through the ordinary save path, which is
    # what proves the new fields are part of the schema and not a blob.
    assert vault.save_job(filled, {'title': job['title']}, job['id'])['values'] == job['values']


def test_the_free_text_fields_are_left_exactly_as_they_were(filled):
    """Retiring them needs every reader to move in the same change, and
    those readers are out of this ticket's scope. The runbook lists
    them."""
    before = {job['id']: {field: job.get(field) for field in migrate.FREE_TEXT_FIELDS}
              for job in vault.list_jobs(filled)}
    migrate.main(['--vault', str(filled), '--apply'])
    after = {job['id']: {field: job.get(field) for field in migrate.FREE_TEXT_FIELDS}
             for job in vault.list_jobs(filled)}
    assert after == before


def test_field_provenance_is_not_touched(filled):
    migrate.main(['--vault', str(filled), '--apply'])
    owner = job_by_url(filled, 'https://example.test/b')
    assert owner['field_provenance'] == {'seniority': 'user'}


def test_no_history_event_is_appended(filled):
    """The sweep writes through the vault's own atomic writer, so a
    migration cannot look like something the owner did."""
    before = {job['id']: len(job.get('history') or []) for job in vault.list_jobs(filled)}
    migrate.main(['--vault', str(filled), '--apply'])
    after = {job['id']: len(job.get('history') or []) for job in vault.list_jobs(filled)}
    assert after == before


# --- idempotency ----------------------------------------------------------

def test_a_second_run_finds_nothing_to_change(filled, capsys):
    migrate.main(['--vault', str(filled), '--apply'])
    capsys.readouterr()
    assert migrate.main(['--vault', str(filled)]) == 0
    assert 'nothing to change' in capsys.readouterr().out


def test_a_second_apply_rewrites_no_file(filled):
    migrate.main(['--vault', str(filled), '--apply'])
    before = {path: path.read_bytes() for path in (filled / 'jobs').glob('*.yaml')}
    migrate.main(['--vault', str(filled), '--apply'])
    assert {path: path.read_bytes() for path in (filled / 'jobs').glob('*.yaml')} == before


def test_an_admin_value_written_afterwards_survives_a_re_run(filled):
    migrate.main(['--vault', str(filled), '--apply'])
    job = job_by_url(filled, 'https://example.test/a')
    edited = dict(job['values'])
    edited['occupation_family'] = taxonomy.make_value_record(
        'occupation_family', 'software-architect', 'admin')
    vault.save_job(filled, {'values': edited}, job['id'])
    migrate.main(['--vault', str(filled), '--apply'])
    assert job_by_url(filled, 'https://example.test/a')['values'][
        'occupation_family']['value'] == 'software-architect'


# --- the rails ------------------------------------------------------------

def test_a_vault_that_is_not_one_stops_the_run(tmp_path):
    with pytest.raises(SystemExit, match='does not look like'):
        migrate.main(['--vault', str(tmp_path)])


def test_no_vault_at_all_stops_rather_than_guessing(monkeypatch):
    monkeypatch.delenv('CAREEROS_VAULT', raising=False)
    with pytest.raises(SystemExit, match='no vault given'):
        migrate.main([])


def test_an_unreadable_record_is_named_and_skipped(filled, capsys):
    (filled / 'jobs' / 'broken.yaml').write_text(': not : yaml :\n')
    assert migrate.main(['--vault', str(filled)]) == 0
    assert 'broken.yaml' in capsys.readouterr().err
