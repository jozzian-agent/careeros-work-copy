"""The stored-text cleanup (brief 2026-10-18, section 6): that it takes
markup and entity escapes out of stored job and company text, takes a
leading site code out of a company name, turns a careers page's name into
a provisional title that asks the owner for the real one, leaves text the
owner typed alone, writes nothing in a dry run, and changes nothing on a
second run."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clean_stored_text as cleanup  # noqa: E402

from careeros import ingest, vault  # noqa: E402
from careeros.web.pages.jobs import needs_attention  # noqa: E402

MARKED_UP_TITLE = 'Lead Business &amp; Technology Engineering (w/m/d),<br/>80-100% Zürich / hybrid'
CLEAN_TITLE = 'Lead Business & Technology Engineering (w/m/d), 80-100% Zürich / hybrid'
CODED_NAME = 'CHE003 Thomson Reuters Enterprise Centre GmbH'


@pytest.fixture
def dirty(tmp_path):
    """A synthetic vault holding one record per defect the owner found,
    plus two records that are already clean, so a run has something to
    leave alone. Never the live vault."""
    root = tmp_path / 'vault'
    root.mkdir()
    vault.save_job(root, {'title': MARKED_UP_TITLE, 'url': 'https://example.test/a',
                          'company': 'Sanitas Krankenversicherung',
                          'description': 'First line<br/>Second line'})
    vault.save_job(root, {'title': 'Job Offers', 'url': 'https://example.test/b',
                          'company': 'Finders'})
    vault.save_job(root, {'title': 'Careers and jobs', 'url': 'https://example.test/c',
                          'company': 'Syngenta'})
    vault.save_job(root, {'title': 'Product Manager', 'url': 'https://example.test/d',
                          'company': 'ewz'})
    # name_source 'auto' is what a company created from a posting
    # carries (org_intake.identity._create_record); 'owner' is the
    # vault's default for one the owner typed.
    vault.save_company(root, {'name': CODED_NAME, 'name_source': 'auto',
                              'locations': ['Switzerland, Zug, Zug', 'Switzerland'],
                              'notes': 'Met at a fair &amp; followed up'})
    vault.save_company(root, {'name': 'Northwind Systems', 'name_source': 'auto'})
    return root


def jobs_by_title(root):
    return {job['title']: job for job in vault.list_jobs(root)}


def names(root):
    return sorted(company['name'] for company in vault.list_companies(root))


def run(root, *args):
    return cleanup.main(['--vault', str(root), *args])


# --- markup ---------------------------------------------------------------

def test_markup_and_entities_leave_a_stored_title(dirty):
    assert run(dirty, '--apply') == 0
    assert CLEAN_TITLE in jobs_by_title(dirty)


def test_markup_leaves_a_stored_description_without_joining_two_lines(dirty):
    assert run(dirty, '--apply') == 0
    description = jobs_by_title(dirty)[CLEAN_TITLE]['description']
    assert '<br/>' not in description
    assert description == 'First line Second line'


# --- an internal code in a company name -----------------------------------

def test_a_leading_site_code_leaves_a_company_name(dirty):
    assert run(dirty, '--apply') == 0
    assert 'Thomson Reuters Enterprise Centre GmbH' in names(dirty)
    assert CODED_NAME not in names(dirty)


def test_a_name_the_owner_set_is_never_rewritten(dirty):
    company = next(c for c in vault.list_companies(dirty) if c['name'] == CODED_NAME)
    vault.save_company(dirty, {'name_source': 'owner'}, company['id'])
    assert run(dirty, '--apply') == 0
    assert CODED_NAME in names(dirty)


# --- a careers page is not a job title ------------------------------------

@pytest.mark.parametrize('heading, expected', [
    ('Job Offers', 'Finders opportunity'),
    ('Careers and jobs', 'Syngenta opportunity'),
])
def test_a_generic_heading_becomes_a_provisional_title(dirty, heading, expected):
    assert run(dirty, '--apply') == 0
    titles = jobs_by_title(dirty)
    assert heading not in titles
    assert expected in titles


def test_a_job_with_no_evidenced_title_asks_the_owner_for_one(dirty):
    assert run(dirty, '--apply') == 0
    job = jobs_by_title(dirty)['Finders opportunity']
    assert job['field_status']['title'] == 'not_evidenced'
    assert job['field_status_reason']['title'] == ingest.NO_TITLE_REASON
    assert needs_attention(job) is True


def test_a_real_title_is_left_exactly_as_it_is(dirty):
    before = jobs_by_title(dirty)['Product Manager']
    assert run(dirty, '--apply') == 0
    after = jobs_by_title(dirty)['Product Manager']
    assert after == before
    assert needs_attention(after) is False


def test_a_title_the_owner_typed_is_never_rewritten(dirty):
    job = jobs_by_title(dirty)['Job Offers']
    vault.save_job(dirty, {'field_provenance': {'title': 'user'}}, job['id'])
    assert run(dirty, '--apply') == 0
    assert 'Job Offers' in jobs_by_title(dirty)


# --- the safety rails -----------------------------------------------------

def test_the_dry_run_is_the_default_and_writes_nothing(dirty, capsys):
    before = {job['id']: job for job in vault.list_jobs(dirty)}
    assert run(dirty) == 0
    assert {job['id']: job for job in vault.list_jobs(dirty)} == before
    out = capsys.readouterr().out
    assert 'DRY RUN' in out
    assert 'nothing was written' in out


def test_the_dry_run_names_the_records_and_fields_it_would_change(dirty, capsys):
    assert run(dirty) == 0
    out = capsys.readouterr().out
    assert 'JOB-001: description, title' in out
    assert 'CO-001: name, notes' in out
    # Never the text itself: a description is a whole posting.
    assert '<br/>' not in out


def test_a_second_run_finds_nothing_left_to_change(dirty, capsys):
    assert run(dirty, '--apply') == 0
    capsys.readouterr()
    assert run(dirty, '--apply') == 0
    assert 'nothing to change' in capsys.readouterr().out


def test_a_vault_that_is_not_one_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        cleanup.main(['--vault', str(tmp_path / 'nowhere')])


def test_no_vault_given_stops_rather_than_guessing(monkeypatch):
    monkeypatch.delenv('CAREEROS_VAULT', raising=False)
    with pytest.raises(SystemExit):
        cleanup.main([])


# --- id-reservation tombstones --------------------------------------------

def test_a_tombstone_is_skipped_by_its_name_whatever_it_holds(dirty, capsys):
    """This sweep walks the record directories itself, so it skips a
    tombstone on the `_reserved-` name `vault.reserve_id` writes, before
    the file is read at all. For an offline reader the prefix is the
    whole contract: a tombstone whose stored `reserved` flag is gone
    holds no text to clean all the same (CAREER-94)."""
    stone = dirty / 'jobs' / f'{vault.RESERVED_PREFIX}42.yaml'
    stone.write_text('id: JOB-042\ntitle: Lead &amp; Learn\n', encoding='utf-8')
    before = stone.read_bytes()
    assert run(dirty, '--apply') == 0
    out = capsys.readouterr().out
    # The four stored jobs, never the five files in the directory.
    assert 'jobs: 3 of 4 change' in out
    assert 'JOB-042' not in out
    assert stone.read_bytes() == before
