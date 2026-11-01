"""Protects the admin review list for company requests: that only the
admin reaches any of the three endpoints, what a row says and what it
deliberately does not, and that approving or rejecting one answers every
open request asking for the same company.

Every client here signs in for real, through POST /login and the signed
cookie, rather than through conftest's `signed_in` patch: the whole
point is which user the request is, so the thing under test has to be
the real session. Synthetic fixture vault; no test here reaches the
network.
"""
import pytest

from careeros import server, users, vault

PASSWORD = 'correct horse battery staple'

#: A name no other fixture in this repository uses, so a leak into a
#: non-admin's answer is recognisable whatever shape it takes.
ASKED_FOR = 'Zqwibble Thornfax AG'

#: The tester's own job title, which the admin may NOT read (decision
#: D3): the review list sends the job id and no title for it.
TESTER_JOB_TITLE = 'Snorbleth Underkeep Engineer'


@pytest.fixture
def root(tmp_path):
    root = tmp_path / 'vault'
    (root / 'jobs').mkdir(parents=True)
    return root


@pytest.fixture
def people(root):
    return {
        'admin': users.create_user(root, email='owner@example.test', name='Owner',
                                   role='admin', password=PASSWORD),
        'tester': users.create_user(root, email='one@example.test', name='Tester One',
                                    role='tester', password=PASSWORD),
    }


@pytest.fixture
def app(root, people, raw_session):
    built = server.create_app(root)
    built.config['TESTING'] = True
    return built


@pytest.fixture
def clients(app, people):
    built = {}
    for key, user in people.items():
        client = app.test_client()
        response = client.post('/login', json={'email': user['email'], 'password': PASSWORD})
        assert response.status_code == 200, response.get_data(as_text=True)
        built[key] = client
    return built


def waiting_request(root, people, name=ASKED_FOR, *, index=0, owner='tester', status='needs_admin'):
    """One request already parked for the admin, with the job it came
    from, written straight through the vault: how the request got there
    is PR #44's and the resolver's business, not this file's."""
    job = vault.save_job(root, {
        'title': TESTER_JOB_TITLE if owner == 'tester' else f'Admin Posting {index}',
        'url': f'https://pending.example/jobs/{owner}/{index}',
        'employer_named_in_posting': 'Pending Employer AG',
        vault.OWNER_FIELD: people[owner]['id']})
    request = vault.save_company_request(root, {
        'job_id': job['id'], 'name': name, vault.OWNER_FIELD: people[owner]['id']})
    if status != 'filed':
        request = vault.save_company_request(root, {'status': status}, request['id'])
    return request, job


def stored(root, identifier):
    return next(r for r in vault.list_company_requests(root) if r['id'] == identifier)


# --- Who may reach it ----------------------------------------------------

#: Every route of the review list, as (method, path template, payload).
ROUTES = [
    ('get', '/api/company-requests', None),
    ('post', '/api/company-requests/{id}/approve', {}),
    ('post', '/api/company-requests/{id}/reject', {}),
]


@pytest.mark.parametrize('method,template,payload', ROUTES)
def test_a_tester_is_refused_with_the_one_shared_write_message(
        clients, root, people, method, template, payload):
    """Resolving a request is a write to the shared companies record,
    which is the admin's alone (M2, decision D3), so every route here
    answers a tester the same 403 every other shared write does."""
    request, _job = waiting_request(root, people)
    call = getattr(clients['tester'], method)
    response = call(template.format(id=request['id']),
                    **({'json': payload} if payload is not None else {}))
    assert response.status_code == 403
    assert response.get_json() == {'error': users.SHARED_READ_ONLY}
    # And nothing moved.
    assert stored(root, request['id'])['status'] == 'needs_admin'


def test_a_testers_own_request_is_not_readable_through_the_review_list(clients, root, people):
    """Not even their own: the list is the admin's surface, and a tester
    asking for it learns nothing about any request at all."""
    waiting_request(root, people)
    response = clients['tester'].get('/api/company-requests')
    assert response.status_code == 403
    assert ASKED_FOR not in response.get_data(as_text=True)


# --- What a row says -----------------------------------------------------

def test_the_list_holds_the_waiting_requests_with_their_suggestions(clients, root, people):
    close = vault.save_company(root, {'name': 'Zqwibble Thornfax Systems'})
    request, job = waiting_request(root, people)

    response = clients['admin'].get('/api/company-requests')

    assert response.status_code == 200
    rows = response.get_json()['requests']
    assert len(rows) == 1
    row = rows[0]
    assert row['id'] == request['id']
    assert row['name'] == ASKED_FOR
    assert row['created_at'] == request['created_at']
    assert row['requester'] == {'id': people['tester']['id'], 'name': 'Tester One'}
    assert row['job']['id'] == job['id']
    # A scored hint to click, never a link: the company is close enough
    # to be offered and not close enough to have been matched.
    assert row['suggestions'] == [{'company_id': close['id'],
                                   'name': 'Zqwibble Thornfax Systems',
                                   'score': row['suggestions'][0]['score']}]
    assert 0 < row['suggestions'][0]['score'] < 1


def test_the_row_does_not_carry_a_job_title_the_admin_may_not_read(clients, root, people):
    """Decision D3: the admin reaches no part of a tester's job, and
    `GET /api/jobs/<id>` answers them 404 for one. So the review list
    sends the job id, which is already on the request record they do
    read, and no title."""
    waiting_request(root, people)
    response = clients['admin'].get('/api/company-requests')
    assert response.get_json()['requests'][0]['job']['title'] is None
    assert TESTER_JOB_TITLE not in response.get_data(as_text=True)


def test_the_row_does_carry_a_title_the_admin_may_read(clients, root, people):
    """The same rule from the other side: a request filed against the
    admin's own job names it, because that one is theirs to read."""
    waiting_request(root, people, owner='admin')
    response = clients['admin'].get('/api/company-requests')
    assert response.get_json()['requests'][0]['job']['title'] == 'Admin Posting 0'


def test_only_the_requests_waiting_for_the_admin_are_listed(clients, root, people):
    """A filed request is the nightly pass's, and a resolved one is
    nobody's. The list is what the pass could not settle."""
    waiting, _ = waiting_request(root, people, index=0)
    for index, status in enumerate(('filed', 'linked', 'created', 'rejected'), start=1):
        waiting_request(root, people, name=f'Other Name {index} AG',
                        index=index, status=status)
    rows = clients['admin'].get('/api/company-requests').get_json()['requests']
    assert [row['id'] for row in rows] == [waiting['id']]


# --- Approve: create ------------------------------------------------------

def test_approve_with_no_body_creates_the_company_and_links_the_job(clients, root, people):
    request, job = waiting_request(root, people)

    response = clients['admin'].post(f"/api/company-requests/{request['id']}/approve")

    assert response.status_code == 200
    companies = vault.list_companies(root)
    assert [c['name'] for c in companies] == [ASKED_FOR]
    assert response.get_json()['status'] == 'created'
    assert response.get_json()['resolved_company_id'] == companies[0]['id']
    linked = vault.load_job(root, job['id'])
    assert linked['company_id'] == companies[0]['id']
    assert linked['company_link_state'] == 'linked'
    assert linked['company_link_reason'] == 'manual'


def test_approve_with_a_chosen_company_links_to_that_one(clients, root, people):
    chosen = vault.save_company(root, {'name': 'Zqwibble Thornfax Systems'})
    request, job = waiting_request(root, people)

    response = clients['admin'].post(f"/api/company-requests/{request['id']}/approve",
                                     json={'company_id': chosen['id']})

    assert response.status_code == 200
    assert response.get_json()['status'] == 'linked'
    assert response.get_json()['resolved_company_id'] == chosen['id']
    assert vault.load_job(root, job['id'])['company_id'] == chosen['id']
    # No second company was written for the name that was asked for.
    assert [c['id'] for c in vault.list_companies(root)] == [chosen['id']]


def test_approving_one_request_answers_every_request_for_that_name(clients, root, people):
    """The same company gets asked for by several people. Resolving one
    of them and leaving the rest open would send the others round the
    nightly pass again for no reason."""
    first, first_job = waiting_request(root, people, index=0)
    second, second_job = waiting_request(root, people, name='ZQWIBBLE  thornfax ag',
                                        index=1, owner='admin', status='filed')

    clients['admin'].post(f"/api/company-requests/{first['id']}/approve")

    company = vault.list_companies(root)[0]
    for request in (first, second):
        assert stored(root, request['id'])['resolved_company_id'] == company['id']
    for job in (first_job, second_job):
        assert vault.load_job(root, job['id'])['company_id'] == company['id']


def test_a_request_for_a_different_name_is_left_waiting(clients, root, people):
    first, _ = waiting_request(root, people, index=0)
    other, other_job = waiting_request(root, people, name='Grumlewick Vastmoor Ltd', index=1)

    clients['admin'].post(f"/api/company-requests/{first['id']}/approve")

    assert stored(root, other['id'])['status'] == 'needs_admin'
    assert vault.load_job(root, other_job['id'])['company_id'] is None


def test_a_company_id_that_is_not_linkable_is_refused_before_anything_is_written(
        clients, root, people):
    """A retired id and one that never existed answer alike, which is
    what keeps the tombstone undetectable through a write."""
    retired = vault.save_company(root, {'name': 'Retired Holdings'})
    vault.save_company(root, {'retired': True}, retired['id'])
    request, job = waiting_request(root, people)
    # A second request for the same name whose job is gone, so the
    # refusal has something it could have settled on its way through if
    # the id were checked after the group rather than before it.
    stale, stale_job = waiting_request(root, people, index=1)
    vault.delete_job(root, stale_job['id'])

    for identifier in (retired['id'], 'CO-404'):
        response = clients['admin'].post(f"/api/company-requests/{request['id']}/approve",
                                         json={'company_id': identifier})
        assert response.status_code == 400
        assert response.get_json() == {'error': 'Company not found.'}

    assert stored(root, request['id'])['status'] == 'needs_admin'
    assert stored(root, stale['id'])['status'] == 'needs_admin'
    assert vault.load_job(root, job['id'])['company_id'] is None
    assert [c['id'] for c in vault.list_companies(root)] == [retired['id']]


def test_approving_a_request_whose_job_is_gone_creates_no_company(clients, root, people):
    """There is nothing left to link, so a company created here would be
    a shared record nothing points at."""
    request, job = waiting_request(root, people)
    vault.delete_job(root, job['id'])

    response = clients['admin'].post(f"/api/company-requests/{request['id']}/approve")

    assert response.status_code == 200
    assert response.get_json()['status'] == 'rejected'
    assert vault.list_companies(root) == []


# --- Reject ---------------------------------------------------------------

def test_reject_settles_the_request_and_touches_nothing_else(clients, root, people):
    request, job = waiting_request(root, people)

    response = clients['admin'].post(f"/api/company-requests/{request['id']}/reject",
                                     json={'note': 'Not a real employer.'})

    assert response.status_code == 200
    assert response.get_json()['status'] == 'rejected'
    assert response.get_json()['resolution_note'] == 'Not a real employer.'
    assert vault.list_companies(root) == []
    assert vault.load_job(root, job['id'])['company_id'] is None


def test_reject_needs_no_note(clients, root, people):
    request, _ = waiting_request(root, people)
    response = clients['admin'].post(f"/api/company-requests/{request['id']}/reject")
    assert response.status_code == 200
    assert response.get_json()['status'] == 'rejected'
    assert response.get_json()['resolution_note'] == ''


def test_rejecting_one_request_leaves_the_others_for_that_name_alone(clients, root, people):
    """A rejection is about this one ask. Somebody else asking for the
    same name has not been refused by it."""
    first, _ = waiting_request(root, people, index=0)
    second, _ = waiting_request(root, people, index=1, owner='admin')

    clients['admin'].post(f"/api/company-requests/{first['id']}/reject")

    assert stored(root, second['id'])['status'] == 'needs_admin'


def test_a_note_that_is_not_text_is_refused(clients, root, people):
    request, _ = waiting_request(root, people)
    response = clients['admin'].post(f"/api/company-requests/{request['id']}/reject",
                                     json={'note': 42})
    assert response.status_code == 400
    assert stored(root, request['id'])['status'] == 'needs_admin'


# --- The two refusals both writes share -----------------------------------

@pytest.mark.parametrize('action', ['approve', 'reject'])
def test_an_id_that_is_not_there_answers_not_found(clients, root, people, action):
    response = clients['admin'].post(f'/api/company-requests/CR-404/{action}')
    assert response.status_code == 404
    assert response.get_json() == {'error': 'Company request not found.'}


@pytest.mark.parametrize('action', ['approve', 'reject'])
@pytest.mark.parametrize('status', ['linked', 'created', 'rejected'])
def test_a_request_that_is_already_answered_is_refused(clients, root, people, action, status):
    """A second approve of a resolved request would create a second
    company for a name that now has one."""
    request, _ = waiting_request(root, people, status=status)
    response = clients['admin'].post(f"/api/company-requests/{request['id']}/{action}")
    assert response.status_code == 409
    assert response.get_json() == {'error': 'This company request is already resolved.'}
    assert stored(root, request['id'])['status'] == status
    assert vault.list_companies(root) == []


@pytest.mark.parametrize('action', ['approve', 'reject'])
def test_a_filed_request_may_still_be_answered_by_hand(clients, root, people, action):
    """The admin does not have to wait for the nightly pass to park a
    request before they can settle it."""
    request, _ = waiting_request(root, people, status='filed')
    response = clients['admin'].post(f"/api/company-requests/{request['id']}/{action}")
    assert response.status_code == 200
    assert stored(root, request['id'])['status'] != 'filed'
