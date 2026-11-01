"""Filing a company request: the ask a user who may not write a company
answers instead (owner ruling 2026-11-01).

A company is shared and admin-write, so the create form on the company
ask used to answer 403 for everybody else. What this protects is the
other half: the name gate, the one request per job, the day's budget, and
that a filing writes a private record and touches no company at all.

Fixtures are synthetic throughout, on a copy of sample/vault; no test
here reaches the network (tests/conftest.py's offline fixture blocks it
process-wide).
"""
from datetime import date, timedelta
from pathlib import Path
import shutil

import pytest

from careeros import vault
from careeros.server import (COMPANY_REQUEST_DAILY_CAP, COMPANY_REQUEST_LIMITED_MESSAGE,
                             create_app)

ROOT = Path(__file__).resolve().parents[1]

#: The suite's own signed-in user (tests/conftest.py SUITE_USER), which is
#: who every filing below is stamped for.
FILER = 'USER-001'


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / 'sample/vault', tmp_path / 'vault')
    return tmp_path / 'vault'


@pytest.fixture
def client(root):
    return create_app(root).test_client()


def asking_job(root, **fields):
    """A job whose company ask is open: the resolution finished with no
    company and no ambiguity, the posting named an employer, the reading
    is done. Every one of those is a vault default except the name."""
    return vault.save_job(root, {
        'title': 'Pending Link', 'url': 'https://pending.example/jobs/1',
        'employer_named_in_posting': 'Pending Employer AG',
        vault.OWNER_FIELD: FILER} | fields)


def file_request(client, job, name='Northwind AG'):
    return client.post('/api/jobs/' + job['id'] + '/company-request', json={'name': name})


# --- The name gate -------------------------------------------------------
#
# One function, and the one gate on what a later resolution may turn into
# a shared company name. Table-driven, because it is a pure function with
# a case per rule.

ACCEPTED = [
    'Northwind AG',
    'AB',                                     # the shortest name there is
    'x' * vault.COMPANY_NAME_MAX,             # and the longest
    'Müller & Söhne GmbH',                    # accents and punctuation
    '3M',                                     # a digit is a letter's equal
    "O'Neill, Inc.",
]

REJECTED = [
    ('', 'short'),
    ('   ', 'short'),
    ('A', 'short'),
    (' A ', 'short'),                         # stripped before it is measured
    ('x' * (vault.COMPANY_NAME_MAX + 1), 'long'),
    ('North\nwind', 'control'),               # inside the name, not around it
    ('North\twind', 'control'),
    ('Northwind\x00', 'control'),
    ('Northwind\x7f', 'control'),
    ('<script>alert(1)</script>', 'markup'),
    ('Northwind <AG>', 'markup'),
    ('a > b', 'markup'),
    ('...', 'empty'),
    ('--- & ---', 'empty'),
    ('!@#$%^', 'empty'),
]


@pytest.mark.parametrize('name', ACCEPTED)
def test_a_real_company_name_is_accepted(name):
    assert vault.validate_company_name(name) == name.strip()


@pytest.mark.parametrize('name,rule', REJECTED)
def test_a_name_that_breaks_one_rule_is_refused_with_its_own_message(name, rule):
    with pytest.raises(ValueError) as refused:
        vault.validate_company_name(name)
    assert str(refused.value) == vault.COMPANY_NAME_ERRORS[rule]


def test_the_name_is_stored_stripped():
    """Surrounding whitespace is not part of a name, and a name that is
    nothing but whitespace is nothing."""
    assert vault.validate_company_name('  Northwind AG \n') == 'Northwind AG'


def test_a_name_that_is_not_text_is_refused():
    """A client can send anything. Each of these is a ValueError and not
    a TypeError raised out of the middle of a length check."""
    for value in (None, 42, ['Northwind AG'], {'name': 'Northwind AG'}):
        with pytest.raises(ValueError) as refused:
            vault.validate_company_name(value)
        assert str(refused.value) == vault.COMPANY_NAME_ERRORS['type']


def test_the_endpoint_answers_the_name_message_as_a_400(client, root):
    job = asking_job(root)
    response = file_request(client, job, name='A')
    assert response.status_code == 400
    assert response.json == {'error': vault.COMPANY_NAME_ERRORS['short']}
    assert vault.list_company_requests(root) == []


def test_the_writer_refuses_a_name_no_endpoint_would_accept(root):
    """The gate is in the writer too, so the stored record cannot hold a
    name the endpoint would have refused."""
    job = asking_job(root)
    with pytest.raises(ValueError):
        vault.save_company_request(root, {'job_id': job['id'], 'name': '<b>'})
    assert vault.list_company_requests(root) == []


# --- Filing ---------------------------------------------------------------

def test_filing_writes_a_private_request_and_no_company(client, root):
    job = asking_job(root)
    before = {company['id'] for company in vault.list_companies(root)}
    response = file_request(client, job, name='Northwind AG')
    assert response.status_code == 201
    assert response.json == {
        'id': 'CR-001', 'job_id': job['id'], 'name': 'Northwind AG',
        'created_at': date.today().isoformat(), 'status': 'filed',
        'resolved_company_id': None, 'resolution_note': '',
        vault.OWNER_FIELD: FILER,
    }
    # The whole point: the shared half is untouched, and the job is still
    # waiting for a company rather than linked to one this wrote.
    assert {company['id'] for company in vault.list_companies(root)} == before
    stored = vault.load_job(root, job['id'])
    assert stored['company_id'] is None
    assert stored['company_link_state'] == 'pending'


def test_the_request_is_stored_under_its_own_kind_and_number(client, root):
    job = asking_job(root)
    assert file_request(client, job).status_code == 201
    paths = sorted(path.name for path in (root / 'company_requests').glob('*.yaml'))
    assert paths == ['northwind-ag-cr-001.yaml']
    assert vault.ID_PREFIXES['company_requests'] == 'CR-'


def test_a_needs_review_job_can_be_asked_about_too(client, root):
    """The two shapes of the same ask. A review with candidates offers
    picking one, which is a write to the owner's own job and always was
    open to them; naming a company instead is this."""
    job = asking_job(root, company_link_state='needs_review', company_review={
        'candidates': [], 'at': '2026-11-01', 'token': 'current'})
    response = file_request(client, job)
    assert response.status_code == 201
    assert response.json['job_id'] == job['id']


def test_a_second_filing_for_the_same_job_updates_the_one_request(client, root):
    """A change of mind and a double click are the same thing here: one
    open request per job, with the name last asked for."""
    job = asking_job(root)
    first = file_request(client, job, name='Northwind AG')
    assert first.status_code == 201
    second = file_request(client, job, name='Northwind Systems Zurich')
    assert second.status_code == 200
    assert second.json['id'] == first.json['id']
    assert second.json['name'] == 'Northwind Systems Zurich'
    assert second.json['created_at'] == first.json['created_at']
    assert len(vault.list_company_requests(root)) == 1


def test_the_second_filing_is_validated_like_the_first(client, root):
    """An update is a name reaching the vault, so it goes through the same
    gate, and a refused one leaves the stored name alone."""
    job = asking_job(root)
    assert file_request(client, job, name='Northwind AG').status_code == 201
    response = file_request(client, job, name='<b>')
    assert response.status_code == 400
    assert response.json == {'error': vault.COMPANY_NAME_ERRORS['markup']}
    assert vault.active_company_request(root, job['id'])['name'] == 'Northwind AG'


def test_two_jobs_get_two_requests(client, root):
    """One request per job, not one per person: the name is about the
    posting in front of them."""
    first = asking_job(root, url='https://pending.example/jobs/a')
    second = asking_job(root, url='https://pending.example/jobs/b')
    assert file_request(client, first, name='First AG').status_code == 201
    assert file_request(client, second, name='Second AG').status_code == 201
    assert {request['job_id'] for request in vault.list_company_requests(root)} == {
        first['id'], second['id']}


# --- Which jobs may be asked about ---------------------------------------

def test_a_job_that_is_not_asking_about_its_company_refuses_the_filing(client, root):
    """The endpoint reads the page's own ask, so every state the page
    does not ask about is refused rather than filed: a resolved company,
    a posting that named no employer, a reading that is not finished, and
    a job whose one ask is a failed reading."""
    cases = {
        'linked': {'company_link_state': 'linked'},
        'no employer name': {'employer_named_in_posting': None},
        'blank employer name': {'employer_named_in_posting': '   '},
        'still being read': {'ingest_state': 'fetched'},
        'queued': {'ingest_state': 'stub'},
        'read failed': {'ingest_state': 'extract_failed', 'description': '',
                        'ingest_error': {'stage': 'extract', 'reason': 'empty_content',
                                         'at': '2026-11-01'}},
    }
    for index, (case, fields) in enumerate(cases.items()):
        job = asking_job(root, url=f'https://pending.example/jobs/{index}', **fields)
        response = file_request(client, job)
        assert response.status_code == 409, case
        assert response.json == {'error': 'This job is not asking about its company.'}
    assert vault.list_company_requests(root) == []


def test_a_job_that_is_not_there_answers_not_found(client, root):
    response = client.post('/api/jobs/JOB-404/company-request', json={'name': 'Northwind AG'})
    assert response.status_code == 404
    assert response.json == {'error': 'Job not found.'}


def test_a_body_that_is_not_an_object_is_refused(client, root):
    job = asking_job(root)
    response = client.post('/api/jobs/' + job['id'] + '/company-request', json=['Northwind AG'])
    assert response.status_code == 400
    assert vault.list_company_requests(root) == []


# --- The day's budget -----------------------------------------------------

def seed_requests(root, count, *, owner_id=FILER, day=None):
    """`count` filed requests, written straight through the vault, each
    against its own job so the per-job rule is not what the cap test is
    measuring."""
    day = day or date.today().isoformat()
    for index in range(count):
        job = vault.save_job(root, {
            'title': f'Seeded {index}', 'url': f'https://seeded.example/{owner_id}/{index}',
            'employer_named_in_posting': 'Seeded Employer AG', vault.OWNER_FIELD: owner_id})
        vault.save_company_request(root, {
            'job_id': job['id'], 'name': f'Seeded Employer {index}',
            'created_at': day, vault.OWNER_FIELD: owner_id})


def test_the_cap_refuses_the_filing_past_it(client, root):
    """Ten filings in a day go through and the eleventh does not, with a
    message that says what to do about it."""
    seed_requests(root, COMPANY_REQUEST_DAILY_CAP)
    job = asking_job(root)
    response = file_request(client, job)
    assert response.status_code == 429
    assert response.json == {'error': COMPANY_REQUEST_LIMITED_MESSAGE}
    assert len(vault.list_company_requests(root)) == COMPANY_REQUEST_DAILY_CAP


def test_the_last_filing_inside_the_cap_still_goes_through(client, root):
    seed_requests(root, COMPANY_REQUEST_DAILY_CAP - 1)
    job = asking_job(root)
    assert file_request(client, job).status_code == 201
    assert len(vault.list_company_requests(root)) == COMPANY_REQUEST_DAILY_CAP


def test_another_users_filings_do_not_spend_this_users_budget(client, root):
    """The cap is counted off the stamped owner, so a full day of
    somebody else's requests costs this user nothing."""
    seed_requests(root, COMPANY_REQUEST_DAILY_CAP, owner_id='USER-002')
    job = asking_job(root)
    assert file_request(client, job).status_code == 201


def test_yesterdays_filings_do_not_spend_todays_budget(client, root):
    """The budget comes back tomorrow, which is the whole message the 429
    gives, and it comes back with no stored window to expire."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    seed_requests(root, COMPANY_REQUEST_DAILY_CAP, day=yesterday)
    job = asking_job(root)
    assert file_request(client, job).status_code == 201


def test_updating_the_one_open_request_is_not_a_new_filing(client, root):
    """Past the cap, a name the owner already asked about can still be
    corrected: the update writes no new record, so there is nothing for
    the cap to refuse."""
    job = asking_job(root)
    assert file_request(client, job, name='Northwind AG').status_code == 201
    seed_requests(root, COMPANY_REQUEST_DAILY_CAP - 1)
    response = file_request(client, job, name='Northwind Systems Zurich')
    assert response.status_code == 200
    assert response.json['name'] == 'Northwind Systems Zurich'


# --- The stored record ----------------------------------------------------

def test_a_request_record_carries_the_fields_the_resolver_will_write(root):
    """`resolved_company_id` and `resolution_note` are in the record from
    the first day, empty, so resolving one is a change to one module and
    not a schema migration."""
    job = asking_job(root)
    record = vault.save_company_request(root, {'job_id': job['id'], 'name': 'Northwind AG'})
    assert record['resolved_company_id'] is None
    assert record['resolution_note'] == ''
    assert record['status'] == vault.COMPANY_REQUEST_OPEN == 'filed'


def test_a_status_the_list_does_not_name_is_refused(root):
    job = asking_job(root)
    with pytest.raises(ValueError):
        vault.save_company_request(root, {'job_id': job['id'], 'name': 'Northwind AG',
                                          'status': 'resolved-ish'})


def test_a_request_must_name_the_job_it_came_from(root):
    with pytest.raises(ValueError):
        vault.save_company_request(root, {'name': 'Northwind AG'})


def test_a_payload_key_the_record_does_not_store_changes_nothing(root):
    job = asking_job(root)
    record = vault.save_company_request(root, {
        'job_id': job['id'], 'name': 'Northwind AG', 'company_id': 'CO-001'})
    assert 'company_id' not in record


def test_an_update_keeps_the_fields_it_was_not_sent(root):
    job = asking_job(root)
    record = vault.save_company_request(root, {
        'job_id': job['id'], 'name': 'Northwind AG', vault.OWNER_FIELD: FILER})
    updated = vault.save_company_request(root, {'name': 'Northwind Systems'}, record['id'])
    assert updated[vault.OWNER_FIELD] == FILER
    assert updated['job_id'] == job['id']
    assert updated['created_at'] == record['created_at']


def test_updating_a_request_that_is_not_there_raises(root):
    with pytest.raises(KeyError):
        vault.save_company_request(root, {'name': 'Northwind AG'}, 'CR-404')


def test_only_the_open_request_for_that_job_is_the_active_one(root):
    """`active_company_request` is what makes a second filing an update
    and what the page reads to say the ask was asked, so it answers for
    one job and for the open status alone."""
    job = asking_job(root)
    other = asking_job(root, url='https://pending.example/jobs/other')
    record = vault.save_company_request(root, {'job_id': job['id'], 'name': 'Northwind AG',
                                               vault.OWNER_FIELD: FILER})
    assert vault.active_company_request(root, job['id'])['id'] == record['id']
    assert vault.active_company_request(root, other['id']) is None
    vault.save_company_request(root, {'status': 'linked'}, record['id'])
    assert vault.active_company_request(root, job['id']) is None


def test_a_request_number_is_never_reissued(root):
    """The same allocator every numbered kind uses, so the id of the next
    request says nothing about what the vault holds."""
    job = asking_job(root)
    first = vault.save_company_request(root, {'job_id': job['id'], 'name': 'First AG'})
    assert first['id'] == 'CR-001'
    assert vault._next(root, 'company_requests') == 'CR-002'
    second = vault.save_company_request(root, {'job_id': job['id'], 'name': 'Second AG'})
    assert second['id'] == 'CR-002'
