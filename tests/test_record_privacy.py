"""Protects the M2 data split (CAREER-39, owner decisions D3, D4, D10):
a job and an experience belong to one user and reach nobody else down any
path, companies and the tag vocabulary stay one shared universe every
user reads, and writing a shared record stays with the admin.

Every client here signs in for real, through POST /login and the signed
cookie, rather than through conftest's `signed_in` patch: the whole point
is which user the request is, so the thing under test has to be the real
session.
"""

import pytest

from careeros import intake, server, users, vault

PASSWORD = 'correct horse battery staple'

#: A title per user, so a leak is recognisable in a response body
#: whatever shape the leak takes.
TITLES = {'admin': 'Admin Only Role', 'one': 'Tester One Role', 'two': 'Tester Two Role'}
POSITIONS = {'admin': 'Admin Only Position', 'one': 'Tester One Position',
             'two': 'Tester Two Position'}
NOTE_TITLES = {'admin': 'Admin private note', 'one': 'One private note',
               'two': 'Two private note'}

SHARED_COMPANY = 'Shared Universe Holdings'

#: An id of the right shape that no record carries. Every cross-user
#: answer is compared against the answer for this, because "somebody
#: else's record" and "no such record" have to be indistinguishable.
ABSENT_JOB = 'JOB-404'
ABSENT_EXPERIENCE = 'EXP-404'

#: A tag the registry does not hold. Proposing it is a write to shared
#: vocabulary, which is the admin's alone.
NEW_TAG = 'tool:rustlang'


@pytest.fixture
def root(tmp_path):
    return tmp_path / 'vault'


@pytest.fixture
def people(root):
    """One admin and two testers, so "another user" is a tester rather
    than only ever the admin."""
    root.mkdir(parents=True, exist_ok=True)
    return {
        'admin': users.create_user(root, email='owner@example.test', name='Owner',
                                   role='admin', password=PASSWORD),
        'one': users.create_user(root, email='one@example.test', name='Tester One',
                                 role='tester', password=PASSWORD),
        'two': users.create_user(root, email='two@example.test', name='Tester Two',
                                 role='tester', password=PASSWORD),
    }


@pytest.fixture
def company(root, people):
    return vault.save_company(root, {'name': SHARED_COMPANY, 'sectors': ['J'],
                                     'size_class': 'small'})


@pytest.fixture
def records(root, people, company):
    """One job and one position per user, each carrying a private note,
    all linked to the one shared company.

    Written straight through the vault with an explicit owner, which is
    the only way to set up three users' records without driving three
    intake flows; the stamping tests below cover the API's own create
    paths.
    """
    jobs, positions = {}, {}
    for key, user in people.items():
        jobs[key] = vault.save_job(root, {
            'title': TITLES[key], 'url': f'https://example.test/{key}/posting',
            'company_id': company['id'], 'description': f'Posting text for {key}.',
            'status': 'interested', 'location': 'Zurich',
            vault.OWNER_FIELD: user['id'],
            **vault.notes_payload([vault.new_note(NOTE_TITLES[key], 'Body.')]),
        })
        positions[key] = vault.save_experience(root, {
            'title': POSITIONS[key], 'company': SHARED_COMPANY,
            'company_id': company['id'], 'start': '2020-01', 'end': 'present',
            # Both halves on purpose: `skills` is what the Taxonomy
            # page's own breakdown counts, and sending `tags` too keeps
            # save_experience from translating the legacy field.
            'skills': ['Mentoring'], 'tags': ['experience-type:employment'],
            vault.OWNER_FIELD: user['id'],
        })
    return {'jobs': jobs, 'positions': positions}


@pytest.fixture
def app(root, people, raw_session):
    built = server.create_app(root)
    built.config['TESTING'] = True
    return built


@pytest.fixture
def clients(app, people):
    """One signed-in client per user, by the same key the records use."""
    built = {}
    for key, user in people.items():
        client = app.test_client()
        response = client.post('/login', json={'email': user['email'], 'password': PASSWORD})
        assert response.status_code == 200, response.get_data(as_text=True)
        built[key] = client
    return built


def body(response):
    return response.get_data(as_text=True)


# --- Jobs: one user's board is their own ---------------------------------

def test_a_job_list_holds_only_the_readers_own_jobs(clients, records, people):
    for key, client in clients.items():
        listed = client.get('/api/jobs').get_json()
        assert [job['title'] for job in listed] == [TITLES[key]]
        assert [job[vault.OWNER_FIELD] for job in listed] == [people[key]['id']]


def test_the_board_holds_only_the_readers_own_jobs(clients, records):
    for key, client in clients.items():
        board = client.get('/api/jobs?view=board').get_json()
        assert [entry['title'] for entry in board['entries']] == [TITLES[key]]
        assert board['counts'] == {'open': 1, 'ended': 0}
        text = body(client.get('/api/jobs?view=board'))
        for other, title in TITLES.items():
            assert (title in text) is (other == key)


#: Every per-job path, as (method, url template, json payload). Each one
#: reaches a job record, so each one has to answer for somebody else's
#: job exactly as it answers for a job that does not exist.
JOB_PATHS = (
    ('get', '/api/jobs/{id}', None),
    ('get', '/api/jobs/{id}?view=page', None),
    ('get', '/api/jobs/{id}/taxonomy', None),
    ('put', '/api/jobs/{id}', {'title': 'Renamed by a stranger'}),
    ('delete', '/api/jobs/{id}', None),
    ('post', '/api/jobs/{id}/enrich', None),
    ('post', '/api/jobs/{id}/extract', None),
    ('post', '/api/jobs/{id}/re-extract', None),
    ('post', '/api/jobs/{id}/paste-description', {'description': 'Pasted by a stranger.'}),
    ('post', '/api/jobs/{id}/promote', None),
    ('post', '/api/jobs/{id}/resolve', None),
    ('post', '/api/jobs/{id}/resolve-review', {'review_token': 'anything'}),
    ('post', '/api/jobs/{id}/notes', {'title': 'Added by a stranger', 'body': 'x'}),
    ('post', '/api/watch/scan?job={id}', None),
)


@pytest.mark.parametrize('method,template,payload', JOB_PATHS)
def test_another_users_job_answers_exactly_like_a_job_that_does_not_exist(
        clients, records, method, template, payload):
    client = clients['two']
    theirs = records['jobs']['one']['id']
    call = getattr(client, method)
    kwargs = {'json': payload} if payload is not None else {}
    mine = call(template.format(id=theirs), **kwargs)
    absent = call(template.format(id=ABSENT_JOB), **kwargs)
    assert mine.status_code == absent.status_code == 404
    # Byte for byte the same answer, whichever words this route uses for
    # a record that is not there: that identity is the no-existence-leak
    # requirement, not any one message.
    assert mine.get_json() == absent.get_json()
    assert mine.get_json()['error'].endswith('not found.')
    assert TITLES['one'] not in body(mine)


def test_a_refused_job_write_changes_nothing(clients, records, root):
    theirs = records['jobs']['one']['id']
    assert clients['two'].put(f'/api/jobs/{theirs}',
                              json={'title': 'Renamed by a stranger'}).status_code == 404
    assert clients['two'].delete(f'/api/jobs/{theirs}').status_code == 404
    stored = vault.load_job(root, theirs)
    assert stored['title'] == TITLES['one']


def test_another_users_job_note_cannot_be_edited_or_deleted(clients, records, root):
    theirs = records['jobs']['one']
    note_id = theirs['note_list'][0]['id']
    route = f"/api/jobs/{theirs['id']}/notes/{note_id}"
    for response in (clients['two'].patch(route, json={'title': 'Rewritten'}),
                     clients['two'].delete(route)):
        assert response.status_code == 404
        assert response.get_json() == {'error': 'Job not found.'}
    assert vault.load_job(root, theirs['id'])['note_list'][0]['title'] == NOTE_TITLES['one']


def test_the_notes_page_holds_only_the_readers_own_job_notes(clients, records):
    for key, client in clients.items():
        titles = [row['title'] for row in client.get('/api/notes').get_json()['notes']]
        for other, title in NOTE_TITLES.items():
            assert (title in titles) is (other == key)


def test_a_watch_sweep_reports_only_the_readers_own_jobs(clients, records, monkeypatch):
    """A scan with no job argument used to walk every posting in the
    vault, and every event it reports names a job id and a title."""
    seen = []

    def fetch(url):
        seen.append(url)
        return '<title>Still open</title><main>Posting text.</main>'

    monkeypatch.setattr(intake, 'fetch_url', fetch)
    response = clients['two'].post('/api/watch/scan')
    assert response.status_code == 200
    assert seen == ['https://example.test/two/posting']
    for event in response.get_json()['events']:
        assert event['job_id'] == records['jobs']['two']['id']


def test_the_search_surface_carries_no_job_at_all(clients, records):
    """Search is the saved criteria and reaches no job record, so there
    is nothing on it to scope. Pinned so it stays that way: a later
    change that puts matching jobs on this surface has to scope them."""
    for route in ('/api/search', '/api/search?view=page'):
        text = body(clients['two'].get(route))
        for title in TITLES.values():
            assert title not in text


# --- Experiences: the same, for the private record kind that is not a job

def test_an_experience_list_holds_only_the_readers_own_positions(clients, records):
    for key, client in clients.items():
        for route in ('/api/experiences', '/api/experiences?view=page'):
            text = body(client.get(route))
            for other, title in POSITIONS.items():
                assert (title in text) is (other == key)


EXPERIENCE_PATHS = (
    ('get', '/api/experiences/{id}', None),
    ('get', '/api/experiences/{id}?view=page', None),
    ('get', '/api/experiences/{id}/edit', None),
    ('put', '/api/experiences/{id}', {'title': 'Renamed by a stranger'}),
    ('post', '/api/experiences/{id}', {'title': 'Renamed by a stranger'}),
    ('delete', '/api/experiences/{id}', None),
    ('post', '/api/experiences/{id}/link-company', {'unlink': True}),
)


@pytest.mark.parametrize('method,template,payload', EXPERIENCE_PATHS)
def test_another_users_experience_answers_like_one_that_does_not_exist(
        clients, records, method, template, payload):
    client = clients['two']
    theirs = records['positions']['one']['id']
    call = getattr(client, method)
    kwargs = {'json': payload} if payload is not None else {}
    mine = call(template.format(id=theirs), **kwargs)
    absent = call(template.format(id=ABSENT_EXPERIENCE), **kwargs)
    assert mine.status_code == absent.status_code == 404
    assert mine.get_json() == absent.get_json()
    assert POSITIONS['one'] not in body(mine)


def test_a_refused_experience_write_changes_nothing(clients, records, root):
    theirs = records['positions']['one']['id']
    assert clients['two'].put(f'/api/experiences/{theirs}',
                              json={'title': 'Renamed'}).status_code == 404
    assert clients['two'].delete(f'/api/experiences/{theirs}').status_code == 404
    assert vault.load_experience(root, theirs)['title'] == POSITIONS['one']


def test_the_taxonomy_page_counts_only_the_readers_own_positions(clients, records):
    """The skill breakdown is over experiences, so an unscoped count
    would say how many positions everybody holds."""
    for client in clients.values():
        page = client.get('/api/taxonomy').get_json()
        counts = {row['skill']: row['count'] for row in page['skills']}
        assert counts == {'Mentoring': 1}
        # The company breakdowns are shared universe and stay vault-wide.
        assert sum(row['count'] for row in page['sizes']) == 1


# --- The admin gets no window into a tester's private records (D3) -------

def test_the_admin_sees_their_own_jobs_and_positions_and_no_others(clients, records):
    text = body(clients['admin'].get('/api/jobs?view=board'))
    assert TITLES['admin'] in text
    assert TITLES['one'] not in text and TITLES['two'] not in text
    listed = body(clients['admin'].get('/api/experiences?view=page'))
    assert POSITIONS['admin'] in listed
    assert POSITIONS['one'] not in listed and POSITIONS['two'] not in listed


@pytest.mark.parametrize('method,template,payload', JOB_PATHS)
def test_the_admin_cannot_reach_a_testers_job_either(clients, records, method, template, payload):
    client = clients['admin']
    theirs = records['jobs']['one']['id']
    kwargs = {'json': payload} if payload is not None else {}
    response = getattr(client, method)(template.format(id=theirs), **kwargs)
    assert response.status_code == 404
    assert TITLES['one'] not in body(response)


def test_the_admin_cannot_reach_a_testers_position_either(clients, records):
    theirs = records['positions']['one']['id']
    assert clients['admin'].get(f'/api/experiences/{theirs}').status_code == 404


# --- A company page is shared, its linked records are not ----------------

def test_a_company_profile_links_only_the_readers_own_records(clients, records, company):
    for key, client in clients.items():
        page = client.get(f"/api/companies/{company['id']}?view=page").get_json()
        assert [job['title'] for job in page['jobs']] == [TITLES[key]]
        assert [exp['title'] for exp in page['experiences']] == [POSITIONS[key]]
        assert [entry['title'] for entry in page['entries']] == [TITLES[key]]
        # The company itself is the same record for everybody.
        assert page['company']['name'] == SHARED_COMPANY


def test_the_company_directory_counts_only_the_readers_own_open_jobs(clients, records, company):
    for client in clients.values():
        page = client.get('/api/companies?view=page').get_json()
        assert page['counts'] == {company['id']: 1}
        assert [entry['name'] for entry in page['entries']] == [SHARED_COMPANY]


# --- Shared records: everybody reads, the admin writes (D3) --------------

def test_a_tester_reads_companies_and_vocabulary(clients, company):
    client = clients['one']
    assert [c['name'] for c in client.get('/api/companies').get_json()] == [SHARED_COMPANY]
    assert client.get('/api/companies?view=page').status_code == 200
    assert client.get(f"/api/companies/{company['id']}").status_code == 200
    assert client.get(f"/api/companies/{company['id']}?view=page").status_code == 200
    assert client.get('/api/taxonomy').status_code == 200
    registry = client.get('/api/experiences/new').get_json()
    assert 'experience-type' in registry['tags']['facets']


def shared_writes(company_id):
    """Every write that changes a shared record, as (method, url, json).

    CAREER-41: company NOTES left this list. Adding one is open to every
    signed-in user and edit/delete are the author's alone, answered as
    404 rather than 403 (see the note-authorship tests below). The
    company record itself -- its fields, its delete, its classification
    writes -- stays the admin's alone.
    """
    return (
        ('put', f'/api/companies/{company_id}', {'notes': 'Edited by a tester'}),
        ('delete', f'/api/companies/{company_id}', None),
        ('post', f'/api/companies/{company_id}/enrich', None),
        ('post', f'/api/companies/{company_id}/retry', None),
        ('post', '/api/companies/backfill-sector-size', None),
    )


@pytest.fixture
def company_note(root, company):
    note = vault.new_note('Shared company note', 'Body.')
    vault.save_company(root, vault.notes_payload([note]), company['id'])
    return note


def test_a_tester_write_to_a_shared_record_is_refused_with_one_message(
        clients, company, company_note, root):
    for method, route, payload in shared_writes(company['id']):
        kwargs = {'json': payload} if payload is not None else {}
        response = getattr(clients['one'], method)(route, **kwargs)
        assert response.status_code == 403, f'{method} {route}'
        assert response.get_json() == {'error': users.SHARED_READ_ONLY}
    stored = vault.load_company(root, company['id'])
    assert stored['notes'] == ''
    assert [n['title'] for n in stored['note_list']] == ['Shared company note']


def test_the_admin_still_writes_a_shared_record(clients, company, company_note, root):
    edited = clients['admin'].put(f"/api/companies/{company['id']}",
                                  json={'contact_email': 'hr@shared.example'})
    assert edited.status_code == 200
    assert edited.get_json()['contact_email'] == 'hr@shared.example'
    added = clients['admin'].post(f"/api/companies/{company['id']}/notes",
                                  json={'title': 'Admin note', 'body': 'Body.'})
    assert added.status_code == 201
    assert clients['admin'].post(f"/api/companies/{company['id']}/retry").status_code in (200, 400)
    titles = [n['title'] for n in vault.load_company(root, company['id'])['note_list']]
    assert 'Admin note' in titles


def test_a_tester_cannot_be_told_which_company_ids_exist(clients, company):
    """The shared-write refusal comes after the record lookup, so a
    missing company still answers 404 and a tester cannot map the vault
    by comparing 403 against 404."""
    missing = clients['one'].put('/api/companies/CO-404', json={'notes': 'x'})
    assert missing.status_code == 404
    assert missing.get_json() == {'error': 'Company not found.'}


def test_a_tester_cannot_add_a_value_to_the_shared_vocabulary(clients, records, root):
    """Their own job and their own position save fine; what is refused is
    the half of the payload that would register a new tag value."""
    job = records['jobs']['two']['id']
    position = records['positions']['two']['id']
    for route, payload in (
            (f'/api/jobs/{job}', {'tags': [NEW_TAG], 'proposed_tags': [NEW_TAG]}),
            (f'/api/experiences/{position}', {'tags': [NEW_TAG], 'proposed_tags': [NEW_TAG]}),
            # The legacy skills-only payload proposes its own translation
            # inside save_experience, so it reaches the registry too.
            (f'/api/experiences/{position}', {'skills': ['Rustlang']}),
    ):
        response = clients['two'].put(route, json=payload)
        assert response.status_code == 403, route
        assert response.get_json() == {'error': users.SHARED_READ_ONLY}
    facets = vault.load_tags(root)['facets']
    assert not any(value['id'] == 'rustlang' for value in facets['tool']['values'])


def test_a_tester_still_picks_a_registered_tag_for_their_own_record(clients, records, root):
    position = records['positions']['two']['id']
    response = clients['two'].put(f'/api/experiences/{position}',
                                  json={'tags': ['experience-type:volunteer'],
                                        'proposed_tags': []})
    assert response.status_code == 200
    assert response.get_json()['tags'] == ['experience-type:volunteer']


def test_the_admin_still_adds_a_value_to_the_shared_vocabulary(clients, records, root):
    job = records['jobs']['admin']['id']
    response = clients['admin'].put(f'/api/jobs/{job}',
                                    json={'tags': [NEW_TAG], 'proposed_tags': [NEW_TAG]})
    assert response.status_code == 200
    assert response.get_json()['tags'] == [NEW_TAG]
    facets = vault.load_tags(root)['facets']
    assert any(value['id'] == 'rustlang' for value in facets['tool']['values'])


def test_the_classification_popup_is_told_who_may_propose_a_tag(clients, records):
    job_one = records['jobs']['one']['id']
    job_admin = records['jobs']['admin']['id']
    assert clients['one'].get(f'/api/jobs/{job_one}/taxonomy').get_json()['can_edit_shared'] is False
    assert clients['admin'].get(f'/api/jobs/{job_admin}/taxonomy').get_json()['can_edit_shared'] is True


def test_the_company_page_and_the_position_form_are_told_who_may_edit_shared(clients, company):
    route = f"/api/companies/{company['id']}?view=page"
    assert clients['one'].get(route).get_json()['can_edit_shared'] is False
    assert clients['admin'].get(route).get_json()['can_edit_shared'] is True
    assert clients['one'].get('/api/experiences/new').get_json()['can_edit_shared'] is False
    assert clients['admin'].get('/api/experiences/new').get_json()['can_edit_shared'] is True


# --- New records are stamped with whoever added them (D4) ----------------

def test_a_job_added_through_intake_belongs_to_whoever_added_it(clients, people, root, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url',
                        lambda url: '<title>Tester Posting</title><main>Build things.</main>')
    created = clients['two'].post('/api/jobs/intake',
                                  json={'url': 'https://example.test/fresh/posting'})
    assert created.status_code == 201
    job = created.get_json()['job']
    assert job[vault.OWNER_FIELD] == people['two']['id']
    # And it reaches nobody else, neither the other tester nor the admin.
    for key in ('one', 'admin'):
        assert clients[key].get(f"/api/jobs/{job['id']}").status_code == 404
        assert job['id'] not in [j['id'] for j in clients[key].get('/api/jobs').get_json()]
    assert job['id'] in [j['id'] for j in clients['two'].get('/api/jobs').get_json()]


def test_a_position_added_through_the_api_belongs_to_whoever_added_it(clients, people, root):
    created = clients['two'].post('/api/experiences', json={
        'title': 'Fresh Position', 'company': SHARED_COMPANY,
        'start': '2021-02', 'end': 'present'})
    assert created.status_code == 201
    position = created.get_json()
    assert position[vault.OWNER_FIELD] == people['two']['id']
    for key in ('one', 'admin'):
        assert clients[key].get(f"/api/experiences/{position['id']}").status_code == 404


def test_a_payload_cannot_name_somebody_else_as_the_owner(clients, people, records, root):
    """Ownership is stamped by the path that creates a record and never
    moves (D4), so a client that sends owner_id changes nothing."""
    job = records['jobs']['two']['id']
    position = records['positions']['two']['id']
    assert clients['two'].put(f'/api/jobs/{job}',
                              json={vault.OWNER_FIELD: people['one']['id']}).status_code == 200
    assert vault.load_job(root, job)[vault.OWNER_FIELD] == people['two']['id']
    assert clients['two'].put(f'/api/experiences/{position}',
                              json={vault.OWNER_FIELD: people['one']['id']}).status_code == 200
    assert vault.load_experience(root, position)[vault.OWNER_FIELD] == people['two']['id']
    created = clients['two'].post('/api/experiences', json={
        'title': 'Handed Over', 'company': SHARED_COMPANY, 'start': '2021-02', 'end': 'present',
        vault.OWNER_FIELD: people['one']['id']})
    assert created.get_json()[vault.OWNER_FIELD] == people['two']['id']


def test_the_same_posting_added_by_two_users_is_two_private_records(clients, people, monkeypatch):
    """Decision D4: a posting belongs to whoever added it, so the
    duplicate check is scoped to the adder's own jobs. Telling one user
    that another already holds the link would name their job."""
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Shared Link</title><main>Text.</main>')
    url = 'https://example.test/popular/posting'
    first = clients['one'].post('/api/jobs/intake', json={'url': url}).get_json()
    second = clients['two'].post('/api/jobs/intake', json={'url': url}).get_json()
    assert 'duplicate' not in first and 'duplicate' not in second
    assert first['job']['id'] != second['job']['id']
    assert first['job'][vault.OWNER_FIELD] == people['one']['id']
    assert second['job'][vault.OWNER_FIELD] == people['two']['id']
    # Their own second attempt is still caught.
    again = clients['two'].post('/api/jobs/intake', json={'url': url}).get_json()
    assert again['duplicate'] is True
    assert again['existing']['id'] == second['job']['id']


# --- B2: the All jobs tab (CAREER-89) -----------------------------------
#
# The tab shows every job that is NOT private to another user: the records
# no user owns (what the API and the feed pool add) plus the reader's own.
# So it widens what a read reaches by one category, and the D3 rule above
# has to keep holding for everything else -- including for the admin,
# whose own tab shows a tester nothing.

POOL_TITLE = 'Pool Added Role'
POOL_URL = 'https://example.test/pool/posting'
POOL_NOTE_TITLE = 'Pool note'
UNIVERSE = '/api/jobs?view=universe'


@pytest.fixture
def pool_job(root, people, company):
    """A job no user owns, carrying a note, the way a record written
    before the split or added outside a session does."""
    return vault.save_job(root, {
        'title': POOL_TITLE, 'url': POOL_URL, 'company_id': company['id'],
        'status': 'interested', 'location': 'Zurich', 'description': 'Pool posting text.',
        **vault.notes_payload([vault.new_note(POOL_NOTE_TITLE, 'Body.')]),
    })


def on_my_board(client):
    return {entry['id']: entry['on_my_board']
            for entry in client.get(UNIVERSE).get_json()['entries']}


def test_all_jobs_holds_the_ownerless_half_plus_the_readers_own(clients, records, pool_job):
    for key, client in clients.items():
        titles = sorted(entry['title'] for entry in client.get(UNIVERSE).get_json()['entries'])
        assert titles == sorted([POOL_TITLE, TITLES[key]])
        # And no other user's title reaches the response in any shape,
        # the same check the board itself gets above.
        text = body(client.get(UNIVERSE))
        for other, title in TITLES.items():
            assert (title in text) is (other == key)


def test_all_jobs_says_which_entries_are_on_my_board(clients, records, pool_job):
    """An ownerless record is the admin's by inheritance, so for them it
    is already on the board; for a tester it is the one entry that offers
    "Add to my jobs"."""
    assert on_my_board(clients['admin']) == {records['jobs']['admin']['id']: True,
                                             pool_job['id']: True}
    assert on_my_board(clients['one']) == {records['jobs']['one']['id']: True,
                                           pool_job['id']: False}


def test_add_to_my_jobs_copies_a_pool_posting_onto_my_own_board(clients, people, root, pool_job):
    response = clients['one'].post(f"/api/jobs/{pool_job['id']}/promote")
    assert response.status_code == 201
    added = response.get_json()
    assert added['id'] != pool_job['id']
    assert added[vault.OWNER_FIELD] == people['one']['id']
    assert added['status'] == 'new'
    assert added['in_pipeline'] is True
    # The posting travels; nobody's own handling of it does.
    assert (added['url'], added['company_id'], added['description']) == (
        pool_job['url'], pool_job['company_id'], pool_job['description'])
    assert added['note_list'] == []
    assert 'promoted' in [event['event'] for event in added['history']]
    # The universe record is left exactly as it was, so it is still
    # nobody's and still on every reader's tab (D4: ownership never moves).
    assert vault.load_job(root, pool_job['id'])[vault.OWNER_FIELD] is None
    assert on_my_board(clients['two'])[pool_job['id']] is False
    # And the copy shows a status from here on, on both surfaces.
    assert added['id'] in [entry['id'] for entry in
                           clients['one'].get('/api/jobs?view=board').get_json()['entries']]
    assert on_my_board(clients['one'])[added['id']] is True


def test_a_second_add_creates_no_second_board_entry(clients, root, people, pool_job):
    first = clients['one'].post(f"/api/jobs/{pool_job['id']}/promote")
    second = clients['one'].post(f"/api/jobs/{pool_job['id']}/promote")
    assert second.status_code == 200
    assert second.get_json()['id'] == first.get_json()['id']
    mine = vault.list_jobs(root, users.owner(people['one']))
    assert [job['url'] for job in mine].count(POOL_URL) == 1


def test_the_admin_adds_nothing_because_a_pool_posting_is_already_theirs(clients, root, pool_job):
    before = len(vault.list_jobs(root))
    response = clients['admin'].post(f"/api/jobs/{pool_job['id']}/promote")
    assert response.status_code == 200
    assert response.get_json()['id'] == pool_job['id']
    assert len(vault.list_jobs(root)) == before


def test_adding_another_users_job_answers_like_a_job_that_does_not_exist(clients, records, root):
    theirs = records['jobs']['one']['id']
    before = len(vault.list_jobs(root))
    mine = clients['two'].post(f'/api/jobs/{theirs}/promote')
    absent = clients['two'].post(f'/api/jobs/{ABSENT_JOB}/promote')
    assert mine.status_code == absent.status_code == 404
    assert mine.get_json() == absent.get_json()
    assert len(vault.list_jobs(root)) == before


def test_the_directory_count_is_the_universe_and_not_another_users_board(clients, records,
                                                                        company, pool_job):
    """B3 (CAREER-90): the open-jobs count on a company is the universe's
    open jobs -- the ownerless ones plus my own -- so a company whose
    postings came in through the API no longer reads "No open jobs" to
    everybody. Another user's private posting is still not counted."""
    for key, client in clients.items():
        counts = client.get('/api/companies?view=page').get_json()['counts']
        # Two: the pool posting and this reader's own. Three users hold
        # one each at this company, and only one of them is the reader.
        assert counts == {company['id']: 2}, key


# --- The pages rendered without a React build follow the same rules ----

def test_the_jinja_board_is_headed_my_jobs_and_holds_only_the_readers_own(clients, records):
    """`/jobs` falls back to a Jinja rendering when there is no React
    build, so the rename and the scoping have to hold there too."""
    for key, client in clients.items():
        html = body(client.get('/jobs'))
        assert '<h1>My Jobs</h1>' in html
        assert '<h1>Jobs</h1>' not in html
        for other, title in TITLES.items():
            assert (title in html) is (other == key)


def test_the_jinja_pages_offer_a_new_tag_to_the_admin_only(clients, records):
    job = {key: records['jobs'][key]['id'] for key in ('admin', 'one')}
    position = {key: records['positions'][key]['id'] for key in ('admin', 'one')}
    # The control's own markup, not the bare id: both pages' inline
    # scripts name the same ids, so a substring check would match the
    # script whether or not the control is rendered.
    for key, present in (('admin', True), ('one', False)):
        taxonomy = body(clients[key].get(f'/jobs/{job[key]}/taxonomy'))
        assert ('<input id="new-tag-input"' in taxonomy) is present
        assert ('<select id="new-tag-facet"' in taxonomy) is present
        assert ('propose a new value' in taxonomy) is present
        assert ('Only the admin adds new values' in taxonomy) is not present
        # Adding a tag the registry already holds stays available to
        # everybody, so the button and the registry select never go.
        assert 'id="add-tag"' in taxonomy and 'id="tag-select"' in taxonomy
        form = body(clients[key].get(f'/experiences/{position[key]}/edit'))
        assert ('<input data-new-tag=' in form) is present


def test_the_jinja_pages_404_on_another_users_record(clients, records):
    assert clients['two'].get(f"/jobs/{records['jobs']['one']['id']}/taxonomy").status_code == 404
    assert clients['two'].get(
        f"/experiences/{records['positions']['one']['id']}/edit").status_code == 404


# --- A record with no owner is the admin's, which is what the migration
# --- turns into stored facts (see scripts/migrate_record_owner.py) -------

def test_a_record_written_before_the_split_reads_as_the_admins(clients, root, people):
    legacy_job = vault.save_job(root, {'title': 'Legacy Role', 'url': 'https://example.test/legacy'})
    legacy_position = vault.save_experience(root, {'title': 'Legacy Position',
                                                   'company': 'Old Place',
                                                   'start': '2015-01', 'end': '2016-01'})
    assert legacy_job[vault.OWNER_FIELD] is None
    assert legacy_position[vault.OWNER_FIELD] is None
    assert clients['admin'].get(f"/api/jobs/{legacy_job['id']}").status_code == 200
    assert clients['admin'].get(f"/api/experiences/{legacy_position['id']}").status_code == 200
    for key in ('one', 'two'):
        assert clients[key].get(f"/api/jobs/{legacy_job['id']}").status_code == 404
        assert clients[key].get(f"/api/experiences/{legacy_position['id']}").status_code == 404


# --- Nothing private reaches a shared company record ---------------------
#
# A company is read by every user, so anything a job's save puts on one is
# published. These pin the privacy review's five blockers: the rollup, the
# contact-email promotion, the intake metadata fills, the experience
# link-company create, and the deletion counts.

def enrichment_of(root, company_id):
    return vault.load_company(root, company_id).get('enrichment') or {}


def test_shared_jobs_is_the_public_postings_and_nobody_elses(root, people):
    """The unit rule the rollup is built on.

    Owner decision 2026-10-27 (privacy audit finding 3): a public
    posting is a record NO user owns, and the admin is not an exception.
    This test asserted `mine['id'] in shared` until that decision -- see
    `enrich.contributes_to_shared` for why admitting it published the id
    and the posting date of a record no other user may read.
    """
    from careeros import enrich

    legacy = vault.save_job(root, {'title': 'Legacy', 'url': 'https://example.test/legacy'})
    mine = vault.save_job(root, {'title': 'Admin', 'url': 'https://example.test/admin',
                                 vault.OWNER_FIELD: people['admin']['id']})
    theirs = vault.save_job(root, {'title': 'Tester', 'url': 'https://example.test/tester',
                                   vault.OWNER_FIELD: people['one']['id']})
    orphan = vault.save_job(root, {'title': 'Orphan', 'url': 'https://example.test/orphan',
                                   vault.OWNER_FIELD: 'USER-404'})
    shared = {job['id'] for job in enrich.shared_jobs(root)}
    # The one record no user owns, and it is the only one.
    assert shared == {legacy['id']}
    # The admin's own job and the tester's, for the same reason: a job
    # with an owner is private to that owner, and the rollup is read by
    # everybody. An owner id naming no stored account stays out too,
    # which is a shape nothing produces (the accounts command line never
    # deletes one) and so a hand-edited file.
    for job in (mine, theirs, orphan):
        assert job['id'] not in shared


def test_a_vault_with_no_accounts_aggregates_every_job(tmp_path):
    """A pre-M1 vault holds only ownerless records and no tester to
    protect, so the rollup still reads all of them."""
    from careeros import enrich

    root = tmp_path / 'bare'
    root.mkdir()
    vault.save_job(root, {'title': 'Legacy', 'url': 'https://example.test/legacy'})
    assert [job['title'] for job in enrich.shared_jobs(root)] == ['Legacy']


def test_a_testers_job_adds_nothing_to_the_shared_company_rollup(root, people, company):
    """Blocker 1. The rollup publishes a posting's count, its locations,
    its keywords and the id of the posting its headcount came from.

    The baseline is a PUBLIC posting now rather than the admin's own job
    (owner decision 2026-10-27, privacy audit finding 3): the rollup is
    derived from records no user owns, so the admin's own posting is in
    the same position a tester's is. Its own half of the rule gets its
    own test below.
    """
    vault.save_job(root, {
        'title': 'Public Posting', 'url': 'https://example.test/public-roll',
        'company_id': company['id'], 'location': 'Bern', 'keywords': ['publicword'],
        'employee_count': 11, 'posted_date': '2026-01-01'})
    after_public = enrichment_of(root, company['id'])
    assert after_public['hiring_activity']['count'] == 1
    assert after_public['employee_count'] == 11

    tester_job = vault.save_job(root, {
        'title': 'Tester Posting', 'url': 'https://example.test/tester-roll',
        'company_id': company['id'], 'location': 'Secret Valley', 'keywords': ['secretword'],
        'employee_count': 999, 'posted_date': '2026-06-01',
        vault.OWNER_FIELD: people['one']['id']})
    after_tester = enrichment_of(root, company['id'])
    # Byte for byte the block the public posting produced: a tester's
    # save neither contributes to it nor rewrites it.
    assert after_tester == after_public
    assert 'Secret Valley' not in after_tester['locations_seen']
    assert 'secretword' not in after_tester['top_keywords']
    assert after_tester['hiring_activity']['count'] == 1
    # The headcount evidence names the posting it came from, which is the
    # sharpest form of the leak: a private job id on a shared record.
    assert after_tester['employee_count_evidence']['job_id'] != tester_job['id']
    assert after_tester['employee_count'] == 11


def test_a_company_response_never_names_another_users_job(clients, records, company):
    """The same leak seen from the endpoint a tester actually reads."""
    for key, client in clients.items():
        body_text = body(client.get(f"/api/companies/{company['id']}"))
        for other, job in records['jobs'].items():
            if other != key:
                assert job['id'] not in body_text
        page = client.get(f"/api/companies/{company['id']}?view=page").get_json()
        # Three users hold one posting each at this company and every one
        # of those jobs is owned, so the shared rollup is derived from
        # nothing at all and the company carries no hiring activity
        # (owner decision 2026-10-27, privacy audit finding 3). This read
        # `== 1` -- the admin's own posting -- until that decision.
        assert (page['company'].get('enrichment') or {}).get(
            'hiring_activity', {}).get('count') is None


def test_a_contact_email_is_promoted_from_a_public_posting_alone(root, people, company):
    """Blocker 3. The promotion fills an empty company contact from a
    job's own, which would publish an address a private posting carried.

    Owner decision 2026-10-27 (privacy audit finding 3) puts the admin's
    own job on the tester's side of this rule: only a PUBLIC posting --
    a record no user owns -- promotes. The last assertion read
    `== 'admin-found@shared.example'` until that decision.
    """
    for key in ('one', 'admin'):
        vault.save_job(root, {
            'title': f'{key} Posting', 'url': f'https://example.test/{key}-mail',
            'company_id': company['id'], 'contact_email': f'{key}-found@shared.example',
            'company_link_state': 'linked',
            vault.OWNER_FIELD: people[key]['id']})
        assert vault.load_company(root, company['id'])['contact_email'] == '', key

    vault.save_job(root, {
        'title': 'Public Posting', 'url': 'https://example.test/public-mail',
        'company_id': company['id'], 'contact_email': 'public-found@shared.example',
        'company_link_state': 'linked'})
    assert vault.load_company(root, company['id'])['contact_email'] == 'public-found@shared.example'


def test_a_testers_job_write_leaves_the_company_file_untouched(root, people, company, records):
    """Blocker 3, second half: a job save rewrote the shared company's
    rollup on every edit, whoever owned the job."""
    path = next((root / 'companies').glob(f"*-{company['id'].lower()}.yaml"))
    before = path.read_bytes()
    vault.save_job(root, {'location': 'Somewhere else'}, records['jobs']['two']['id'])
    assert path.read_bytes() == before


def test_a_testers_deleted_job_leaves_the_company_file_untouched(root, company, records):
    path = next((root / 'companies').glob(f"*-{company['id'].lower()}.yaml"))
    before = path.read_bytes()
    assert vault.delete_job(root, records['jobs']['two']['id']) is True
    assert path.read_bytes() == before


def test_a_tester_cannot_create_a_company_from_their_position(clients, records, root):
    """Blocker 2. `create` plus `confirm_create` walked straight past the
    near-match check and saved a shared company."""
    before = {c['id'] for c in vault.list_companies(root)}
    route = f"/api/experiences/{records['positions']['two']['id']}/link-company"
    for payload in ({'create': {'name': 'Tester Made This'}},
                    {'create': {'name': 'Tester Made This'}, 'confirm_create': True}):
        response = clients['two'].post(route, json=payload)
        assert response.status_code == 403, payload
        assert response.get_json() == {'error': users.SHARED_READ_ONLY}
    assert {c['id'] for c in vault.list_companies(root)} == before
    assert not any(c['name'] == 'Tester Made This' for c in vault.list_companies(root))


def test_a_tester_still_links_and_unlinks_their_own_position(clients, records, company):
    """The gate is on creating a company, not on pointing at one: both
    writes below touch the position alone."""
    route = f"/api/experiences/{records['positions']['two']['id']}/link-company"
    assert clients['two'].post(route, json={'unlink': True}).status_code == 200
    linked = clients['two'].post(route, json={'company_id': company['id']})
    assert linked.status_code == 200
    assert linked.get_json()['company_id'] == company['id']


def test_the_admin_still_creates_a_company_from_their_position(clients, records, root):
    route = f"/api/experiences/{records['positions']['admin']['id']}/link-company"
    created = clients['admin'].post(route, json={'create': {'name': 'Admin Made This'},
                                                 'confirm_create': True})
    assert created.status_code == 201
    assert any(c['name'] == 'Admin Made This' for c in vault.list_companies(root))


def test_a_testers_intake_adds_no_fact_to_the_company_it_resolves(clients, people, root, monkeypatch):
    """Blocker 4. The posting still finds or makes the one company it
    names, because the tester's own job has to point at something; what
    it must not do is write a single field onto that company."""
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
        '"hiringOrganization":{"name":"Freshly Resolved AG"}}</script>'
        '<main>Great role. Visit https://freshly-resolved.example for more.</main>'))
    created = clients['two'].post('/api/jobs/intake',
                                  json={'url': 'https://freshly-resolved.example/jobs/1'})
    assert created.status_code == 201
    job = created.get_json()['job']
    assert job[vault.OWNER_FIELD] == people['two']['id']
    resolved = vault.load_company(root, job['company_id']) if job.get('company_id') else None
    if resolved is not None:
        # Identity only: a name, and nothing a later reader could mistake
        # for a fact the vault learned from a private posting.
        assert not resolved.get('website')
        assert resolved.get('size_class') is None and resolved.get('size') is None
        assert resolved.get('sector') is None and resolved.get('sectors') == []
        assert resolved.get('sources') == []
        assert resolved.get('locations') == []
        assert not (resolved.get('enrichment') or {})


def test_the_admins_intake_still_fills_the_company_it_resolves(clients, root, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
        '"hiringOrganization":{"name":"Admin Resolved AG"}}</script>'
        '<main>Great role in Zurich.</main>'))
    created = clients['admin'].post('/api/jobs/intake',
                                    json={'url': 'https://admin-resolved.example/jobs/1'})
    assert created.status_code == 201
    job = created.get_json()['job']
    assert job.get('company_id')
    resolved = vault.load_company(root, job['company_id'])
    # The capability is gated, not removed: the same posting added by the
    # admin still records the website and the feed source.
    assert resolved.get('website')
    assert resolved.get('sources')


def test_deleting_a_company_counts_only_the_deleters_own_links(clients, records, company, root):
    """Blocker 5. The conflict used to carry a vault-wide count, which
    told the admin how many private records other users hold."""
    response = clients['admin'].delete(f"/api/companies/{company['id']}")
    assert response.status_code == 409
    data = response.get_json()
    # One job and one position of the admin's own link, out of three of
    # each in the vault.
    assert data['count'] == 2
    assert data['error'] == 'Still linked to 1 jobs and 1 experiences'
    for other in ('one', 'two'):
        assert records['jobs'][other]['id'] not in body(response)
        assert TITLES[other] not in body(response)
    assert vault.load_company(root, company['id']) is not None




def test_a_company_nothing_links_to_still_deletes(clients, root):
    spare = vault.save_company(root, {'name': 'Unlinked Holdings'})
    response = clients['admin'].delete(f"/api/companies/{spare['id']}")
    assert response.status_code == 200
    assert response.get_json() == {'deleted': spare['id']}
    assert vault.load_company(root, spare['id']) is None


# --- (A) A tester resolves to a company that exists, and never makes one -
#
# The creation boundary sits in careeros/org_store.py, because the pinned
# capability decides to create inside resolve_identity and this product
# does not edit vendor/. These pin the boundary from both sides.

def test_a_testers_intake_makes_no_company_when_none_exists(clients, people, root, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
        '"hiringOrganization":{"name":"Nobody Has This AG"}}</script><main>Role text.</main>'))
    before = {c['id'] for c in vault.list_companies(root)}
    created = clients['two'].post('/api/jobs/intake',
                                  json={'url': 'https://nobody-has-this.example/jobs/1'})
    assert created.status_code == 201
    job = created.get_json()['job']
    # No company was brought into existence, by this route or any other.
    assert {c['id'] for c in vault.list_companies(root)} == before
    # The job still landed, and still says who the posting is from: the
    # employer name is the job's own free text, which is what makes the
    # record readable without a shared record behind it.
    assert job['company_id'] is None
    assert job['company_link_state'] == 'pending'
    assert job['company_link_reason'] is None
    assert vault.load_job(root, job['id']) is not None


def test_a_testers_intake_links_a_company_that_already_exists(clients, people, root, company,
                                                              monkeypatch):
    """Resolve to existing, never create: the link is the whole point of
    keeping the ladder running for a tester."""
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
        f'"hiringOrganization":{{"name":"{SHARED_COMPANY}"}}}}</script><main>Role text.</main>'))
    before = {c['id'] for c in vault.list_companies(root)}
    created = clients['two'].post('/api/jobs/intake',
                                  json={'url': 'https://shared-universe.example/jobs/1'})
    job = created.get_json()['job']
    assert job['company_id'] == company['id']
    assert job['company_link_state'] == 'linked'
    assert {c['id'] for c in vault.list_companies(root)} == before
    # And it taught that company nothing: no identifier, no source.
    stored = vault.load_company(root, company['id'])
    assert stored['identifiers'] == [] and stored['sources'] == []


def test_the_admins_intake_still_creates_a_company(clients, root, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
        '"hiringOrganization":{"name":"Admin Creates This AG"}}</script><main>Role text.</main>'))
    created = clients['admin'].post('/api/jobs/intake',
                                    json={'url': 'https://admin-creates.example/jobs/1'})
    assert created.status_code == 201
    assert created.get_json()['job']['company_id']
    assert any(c['name'] == 'Admin Creates This AG' for c in vault.list_companies(root))


def test_a_read_only_store_refuses_to_create_and_no_ops_every_other_write(root, company):
    """The unit boundary. A write carrying an id is a no-op that answers
    with the record as it stands, so the ladder links and learns nothing."""
    from careeros.org_store import CompanyCreationDenied, VaultOrganisationStore

    store = VaultOrganisationStore(root, shared=False)
    with pytest.raises(CompanyCreationDenied):
        store.save_organisation({'name': 'Never Written'})
    assert not any(c['name'] == 'Never Written' for c in vault.list_companies(root))
    unchanged = store.save_organisation({'website': 'https://written.example'}, company['id'])
    assert unchanged['website'] is None
    assert vault.load_company(root, company['id'])['website'] is None


def test_a_tester_cannot_create_a_company_from_a_job_review(clients, records, root):
    """The review popup's other half: picking a candidate writes the
    owner's own job, creating a company writes the shared half."""
    job = vault.save_job(root, {
        'title': 'Needs Review', 'url': 'https://example.test/review',
        'company_link_state': 'needs_review',
        'company_review': {'candidates': [], 'at': '2026-10-18', 'token': 'tok'},
        vault.OWNER_FIELD: records['jobs']['two'][vault.OWNER_FIELD]})
    before = {c['id'] for c in vault.list_companies(root)}
    response = clients['two'].post(f"/api/jobs/{job['id']}/resolve-review",
                                   json={'review_token': 'tok', 'create': {'name': 'Review Made This'}})
    assert response.status_code == 403
    assert response.get_json() == {'error': users.SHARED_READ_ONLY}
    assert {c['id'] for c in vault.list_companies(root)} == before


def test_re_resolving_a_testers_job_creates_no_company(clients, records, root):
    """POST /resolve runs the same ladder, so it needs the same gate."""
    job = vault.save_job(root, {
        'title': 'Re-resolve Me', 'url': 'https://re-resolve.example/jobs/1',
        'company': 'Not In The Vault AG',
        vault.OWNER_FIELD: records['jobs']['two'][vault.OWNER_FIELD]})
    before = {c['id'] for c in vault.list_companies(root)}
    response = clients['two'].post(f"/api/jobs/{job['id']}/resolve")
    assert response.status_code == 200
    assert response.get_json()['company_id'] is None
    assert response.get_json()['company_link_state'] == 'pending'
    assert {c['id'] for c in vault.list_companies(root)} == before


# --- (B) Soft retire ----------------------------------------------------

@pytest.fixture
def foreign_linked(root, company, records):
    """The company with no link of the admin's left, and a tester's job
    and position still pointing at it: the state that makes a delete a
    retire rather than a removal."""
    vault.delete_job(root, records['jobs']['admin']['id'])
    vault.delete_experience(root, records['positions']['admin']['id'])
    return company


def test_deleting_a_foreign_linked_company_succeeds_and_tombstones_it(clients, foreign_linked, root):
    response = clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    assert response.status_code == 200
    assert response.get_json() == {'deleted': foreign_linked['id']}
    stored = vault.load_company(root, foreign_linked['id'])
    # The record is still on disk, so the tester's link still resolves.
    assert stored is not None
    assert stored['retired'] is True
    assert stored['retired_at']
    assert vault.is_retired(stored)


def test_a_retired_company_answers_the_admin_exactly_like_one_that_never_existed(
        clients, foreign_linked, root):
    """The whole point of the retire: no response shape tells the admin
    whether anybody else still holds records against it."""
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    retired, absent = foreign_linked['id'], 'CO-404'
    for method, template, payload in (
            ('get', '/api/companies/{id}', None),
            ('get', '/api/companies/{id}?view=page', None),
            ('put', '/api/companies/{id}', {'notes': 'Edited'}),
            ('delete', '/api/companies/{id}', None),
            ('post', '/api/companies/{id}/enrich', None),
            ('post', '/api/companies/{id}/retry', None),
            ('post', '/api/companies/{id}/notes', {'title': 'Note', 'body': 'x'}),
    ):
        kwargs = {'json': payload} if payload is not None else {}
        mine = getattr(clients['admin'], method)(template.format(id=retired), **kwargs)
        gone = getattr(clients['admin'], method)(template.format(id=absent), **kwargs)
        assert mine.status_code == gone.status_code == 404, f'{method} {template}'
        assert mine.get_json() == gone.get_json() == {'error': 'Company not found.'}


def test_a_second_delete_is_idempotent(clients, foreign_linked, root):
    """Asking again finds it gone, which is the truth from the admin's
    side, and writes nothing: the retire date does not move."""
    first = clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    assert first.status_code == 200
    stamped = vault.load_company(root, foreign_linked['id'])['retired_at']
    second = clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    assert second.status_code == 404
    assert second.get_json() == {'error': 'Company not found.'}
    assert vault.load_company(root, foreign_linked['id'])['retired_at'] == stamped


def test_every_admin_facing_list_hides_a_retired_company(clients, foreign_linked, root):
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    admin = clients['admin']
    assert [c['id'] for c in admin.get('/api/companies').get_json()] == []
    assert admin.get('/api/companies?view=page').get_json()['entries'] == []
    assert SHARED_COMPANY not in body(admin.get('/api/companies?view=page'))
    # The aggregate surfaces stop counting it, and the Notes page stops
    # listing its notes.
    taxonomy = admin.get('/api/taxonomy').get_json()
    assert all(row['count'] == 0 for row in taxonomy['industries'])
    assert sum(row['count'] for row in taxonomy['sizes']) == 0
    assert SHARED_COMPANY not in body(admin.get('/api/notes'))
    # And the position form's company picker, which is a list of ids to
    # link to: offering a retired one would be a control that cannot work.
    assert [c['id'] for c in admin.get('/api/experiences/new').get_json()['companies']] == []


def test_a_tester_still_reads_the_company_their_record_links(clients, foreign_linked, records, root):
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    for key in ('one', 'two'):
        client = clients[key]
        assert [c['id'] for c in client.get('/api/companies').get_json()] == [foreign_linked['id']]
        page = client.get(f"/api/companies/{foreign_linked['id']}?view=page")
        assert page.status_code == 200
        assert page.get_json()['company']['name'] == SHARED_COMPANY
        # Their own linked records still render, and still resolve the
        # company's label rather than falling back to stale free text.
        assert [job['title'] for job in page.get_json()['jobs']] == [TITLES[key]]
        board = client.get('/api/jobs?view=board').get_json()
        assert board['entries'][0]['company_name'] == SHARED_COMPANY
        library = client.get('/api/experiences?view=page').get_json()
        assert library['labels'][records['positions'][key]['id']] == SHARED_COMPANY


def test_a_tester_can_still_edit_the_job_that_links_a_retired_company(clients, foreign_linked,
                                                                      records, root):
    """The reason this is a retire and not a removal: a job pointing at a
    deleted company is refused by save_job on every later edit."""
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    theirs = records['jobs']['two']['id']
    edited = clients['two'].put(f'/api/jobs/{theirs}', json={'location': 'Winterthur'})
    assert edited.status_code == 200
    assert edited.get_json()['location'] == 'Winterthur'
    assert edited.get_json()['company_id'] == foreign_linked['id']


def test_the_admins_intake_never_resurrects_a_retired_company(clients, foreign_linked, root,
                                                              monkeypatch):
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
        f'"hiringOrganization":{{"name":"{SHARED_COMPANY}"}}}}</script><main>Role text.</main>'))
    created = clients['admin'].post('/api/jobs/intake',
                                    json={'url': 'https://fresh-posting.example/jobs/1'})
    assert created.status_code == 201
    linked = created.get_json()['job']['company_id']
    # A fresh record, not the tombstone, and the tombstone stays retired.
    assert linked != foreign_linked['id']
    assert vault.is_retired(vault.load_company(root, foreign_linked['id'])) is True
    assert vault.load_company(root, linked)['retired'] is False


def test_a_testers_new_posting_does_not_link_a_retired_company_either(
        clients, foreign_linked, root, monkeypatch):
    """A retired company takes no new link, from anybody.

    An earlier round let a tester's new posting resolve to the tombstone,
    on the reasoning that their own jobs already pointed at it. That is
    withdrawn: the rule is now the same for every caller, which is what
    makes a retired company and a deleted one indistinguishable on a
    write as well as on a read. Their existing link is grandfathered;
    this new posting is not, so it lands unplaced and creates nothing.
    """
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    before = {c['id'] for c in vault.list_companies(root)}
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
        f'"hiringOrganization":{{"name":"{SHARED_COMPANY}"}}}}</script><main>Role text.</main>'))
    created = clients['two'].post('/api/jobs/intake',
                                  json={'url': 'https://tester-posting.example/jobs/1'})
    # The intake still succeeds: a posting is never rejected (global
    # rule 4), it just has no company to point at.
    assert created.status_code == 201
    assert created.get_json()['job']['company_id'] is None
    assert created.get_json()['job']['company_link_state'] == 'pending'
    assert {c['id'] for c in vault.list_companies(root)} == before


def test_a_retired_company_cannot_be_linked_by_somebody_with_no_record_on_it(
        clients, foreign_linked, root, records):
    """Visibility is "my own record links it", so a user with no link
    gets the missing-record answer, same as the admin."""
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    vault.delete_experience(root, records['positions']['one']['id'])
    vault.delete_job(root, records['jobs']['one']['id'])
    spare = vault.save_experience(root, {
        'title': 'Unlinked Position', 'company': 'Free text', 'start': '2019-01', 'end': '2020-01',
        vault.OWNER_FIELD: records['positions']['one'][vault.OWNER_FIELD]})
    response = clients['one'].post(f"/api/experiences/{spare['id']}/link-company",
                                   json={'company_id': foreign_linked['id']})
    assert response.status_code == 404
    assert response.get_json() == {'error': 'Company not found.'}


def test_the_admin_keeps_the_scoped_conflict_when_their_own_record_links(clients, company, records,
                                                                        root):
    """The 409 half is unchanged: a link of their own is a conflict they
    can act on, so they are told the count."""
    response = clients['admin'].delete(f"/api/companies/{company['id']}")
    assert response.status_code == 409
    assert response.get_json() == {'error': 'Still linked to 1 jobs and 1 experiences', 'count': 2}
    assert vault.load_company(root, company['id'])['retired'] is False


def test_retire_company_is_idempotent_at_the_vault(root, company):
    first = vault.retire_company(root, company['id'])
    assert first['retired'] is True
    again = vault.retire_company(root, company['id'])
    assert again['retired_at'] == first['retired_at']
    with pytest.raises(ValueError):
        vault.retire_company(root, 'CO-404')


# --- The tombstone is not readable through a write or a suggestion ------
#
# Hiding a retired company from the read surfaces is not enough on its
# own: a response that treats a retired id differently from an id that
# was never used tells the admin their delete was a retire, and a write
# that accepts one puts the record back in front of them.

def test_a_retired_company_is_no_near_match_suggestion(clients, foreign_linked, records, root):
    """The link-company create flow offers a near-match before creating.
    A retired company coming back there while a deleted one does not is
    the tombstone, readable."""
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    route = f"/api/experiences/{records['positions']['admin']['id']}/link-company"
    # The admin's own position was deleted by the fixture, so give them
    # one to link from.
    spare = vault.save_experience(root, {
        'title': 'Admin Spare', 'company': 'Free text', 'start': '2018-01', 'end': '2019-01',
        vault.OWNER_FIELD: records['jobs']['admin'][vault.OWNER_FIELD]})
    route = f"/api/experiences/{spare['id']}/link-company"
    # A name one letter off the retired company's: close enough that
    # difflib would offer it if the lookup could see it.
    near = clients['admin'].post(route, json={'create': {'name': 'Shared Universe Holding'}})
    assert near.status_code == 201
    assert 'suggestion' not in near.get_json()
    assert foreign_linked['id'] not in body(near)
    assert SHARED_COMPANY not in body(near)
    # And the same request against a company that is live does suggest,
    # so the test is reading the filter and not a broken lookup.
    live = vault.save_company(root, {'name': 'Live Universe Holdings'})
    suggested = clients['admin'].post(route, json={'create': {'name': 'Live Universe Holding'}})
    assert suggested.get_json().get('suggestion', {}).get('id') == live['id']


def test_a_write_naming_a_retired_company_answers_like_a_deleted_one(clients, foreign_linked,
                                                                     records, root):
    """Blocker B2. A job PUT and an experience write validated raw
    existence, so a retired id was accepted where a deleted id was
    refused -- and the accepted link put the company back on the admin's
    own pages."""
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    retired, deleted = foreign_linked['id'], 'CO-404'
    job = vault.save_job(root, {'title': 'Admin Spare Job', 'url': 'https://example.test/spare',
                                vault.OWNER_FIELD: records['jobs']['admin'][vault.OWNER_FIELD]})
    position = vault.save_experience(root, {
        'title': 'Admin Spare Position', 'company': 'Free text', 'start': '2018-01', 'end': '2019-01',
        vault.OWNER_FIELD: records['jobs']['admin'][vault.OWNER_FIELD]})
    for method, route, key in (
            ('put', f"/api/jobs/{job['id']}", 'company_id'),
            ('put', f"/api/experiences/{position['id']}", 'company_id'),
            ('post', '/api/experiences', 'company_id'),
    ):
        base = ({'title': 'Fresh Position', 'company': 'Free text',
                 'start': '2021-01', 'end': 'present'} if method == 'post' else {})
        mine = getattr(clients['admin'], method)(route, json=base | {key: retired})
        gone = getattr(clients['admin'], method)(route, json=base | {key: deleted})
        assert mine.status_code == gone.status_code == 400, route
        assert mine.get_json() == gone.get_json() == {'error': 'Company not found.'}
    # Nothing linked, so nothing put the company back in front of them.
    assert vault.load_job(root, job['id'])['company_id'] is None
    assert vault.load_experience(root, position['id'])['company_id'] is None
    assert clients['admin'].get(f'/api/companies/{retired}').status_code == 404


def test_a_tester_cannot_make_a_new_link_to_a_retired_company_either(clients, foreign_linked,
                                                                     records, root):
    """One answer for every caller, which is what makes the tombstone
    undetectable rather than merely hidden."""
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    fresh = vault.save_job(root, {'title': 'Tester Fresh', 'url': 'https://example.test/fresh2',
                                  vault.OWNER_FIELD: records['jobs']['two'][vault.OWNER_FIELD]})
    refused = clients['two'].put(f"/api/jobs/{fresh['id']}",
                                 json={'company_id': foreign_linked['id']})
    absent = clients['two'].put(f"/api/jobs/{fresh['id']}", json={'company_id': 'CO-404'})
    assert refused.status_code == absent.status_code == 400
    assert refused.get_json() == absent.get_json() == {'error': 'Company not found.'}


def test_a_grandfathered_link_keeps_saving_on_every_write_path(clients, foreign_linked, records,
                                                               root):
    """The reason the delete leaves a tombstone at all: the records that
    pointed at the company when it went keep working."""
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    job, position = records['jobs']['two']['id'], records['positions']['two']['id']
    edited = clients['two'].put(f'/api/jobs/{job}', json={'location': 'Baden'})
    assert edited.status_code == 200 and edited.get_json()['company_id'] == foreign_linked['id']
    moved = clients['two'].put(f'/api/experiences/{position}', json={'summary': 'Reworded'})
    assert moved.status_code == 200 and moved.get_json()['company_id'] == foreign_linked['id']
    # Sending the same id explicitly is still the same link, so it is
    # still grandfathered.
    resent = clients['two'].put(f'/api/jobs/{job}', json={'company_id': foreign_linked['id']})
    assert resent.status_code == 200
    # Unlinking works, and is one-way: they cannot link back.
    unlinked = clients['two'].put(f'/api/jobs/{job}', json={'company_id': None})
    assert unlinked.status_code == 200 and unlinked.get_json()['company_id'] is None
    assert clients['two'].put(f'/api/jobs/{job}',
                              json={'company_id': foreign_linked['id']}).status_code == 400


def test_linkable_company_at_the_vault(root, company):
    """The unit rule, so the two write paths cannot drift from it."""
    assert vault.linkable_company(root, company['id']) is True
    assert vault.linkable_company(root, 'CO-404') is False
    vault.retire_company(root, company['id'])
    assert vault.linkable_company(root, company['id']) is False
    assert vault.linkable_company(root, company['id'], current=company['id']) is True
    assert vault.linkable_company(root, company['id'], current='CO-002') is False


# --- A tester selects a company without mutating it ---------------------

def review_job(root, owner_id, employer='Tester Private Employer Text'):
    """One job parked in needs_review with a candidate to pick."""
    return vault.save_job(root, {
        'title': 'Needs Review', 'url': 'https://example.test/review-pick',
        'employer_named_in_posting': employer,
        'company_link_state': 'needs_review',
        'company_review': {'candidates': [], 'at': '2026-10-18', 'token': 'tok'},
        vault.OWNER_FIELD: owner_id})


def test_a_tester_review_selection_links_the_job_and_writes_no_name_variant(
        clients, records, company, root):
    """The new blocker. apply_review teaches the chosen company a
    `name_variant` carrying the posting's employer text, so a tester
    selecting a candidate was writing their own private posting's words
    onto a record every user reads."""
    job = review_job(root, records['jobs']['two'][vault.OWNER_FIELD])
    before = vault.load_company(root, company['id'])['identifiers']
    response = clients['two'].post(f"/api/jobs/{job['id']}/resolve-review",
                                   json={'review_token': 'tok', 'company_id': company['id']})
    # Selection is theirs: the job is linked and the review is cleared.
    assert response.status_code == 200
    assert response.get_json()['company_id'] == company['id']
    assert response.get_json()['company_link_state'] == 'linked'
    assert response.get_json()['company_review'] is None
    # The shared record is untouched, and their employer text is nowhere
    # on it.
    stored = vault.load_company(root, company['id'])
    assert stored['identifiers'] == before
    assert 'Tester Private Employer Text' not in str(stored)


def test_the_admins_review_selection_still_writes_the_name_variant(clients, records, company, root):
    """The capability is gated, not removed: the variant is what keeps
    the same fuzzy case from asking twice."""
    job = review_job(root, records['jobs']['admin'][vault.OWNER_FIELD],
                     employer='Admin Employer Text')
    response = clients['admin'].post(f"/api/jobs/{job['id']}/resolve-review",
                                     json={'review_token': 'tok', 'company_id': company['id']})
    assert response.status_code == 200
    assert response.get_json()['company_id'] == company['id']
    stored = vault.load_company(root, company['id'])
    assert {'type': 'name_variant', 'value': 'Admin Employer Text',
            'provenance': 'user'} in stored['identifiers']


# --- Resolution reads the caller's own jobs and nobody else's -----------
#
# Owner decision 2026-10-18, overturning an earlier round of this work
# which argued the whole vault should be read so one ATS tenant resolved
# to one company for everybody. `employer_named_in_posting` is text from
# a private posting and the ladder acts on it: one foreign job on the
# same tenant turns a clean `linked` into `needs_review`/`shared_tenant`,
# and makes an admin resolution publish a tester's ATS association as an
# identifier on a shared company.

#: Two postings under one Lever tenant. Same provider and tenant, so the
#: ladder treats them as one employer's board, which is what makes the
#: cross-user influence visible.
TENANT_URL = 'https://jobs.lever.co/sharedtenant/role-one'
OTHER_TENANT_URL = 'https://jobs.lever.co/sharedtenant/role-two'


def tenant_job(root, owner_id, url, employer, company_id=None):
    """One job carrying the ATS identity and the employer text the ladder
    reads, as intake would have left it."""
    match = intake.posting_ats(url)
    return vault.save_job(root, {
        'title': f'Posting for {employer}', 'url': url,
        'ats_provider': match.provider, 'ats_tenant': match.tenant,
        'ats_posting_id': match.posting_id,
        'employer_named_in_posting': employer,
        'company_id': company_id,
        'company_link_state': 'linked' if company_id else 'pending',
        'company_link_reason': 'ats_tenant' if company_id else None,
        vault.OWNER_FIELD: owner_id})


def test_a_foreign_private_job_cannot_change_the_admins_resolution(clients, people, root,
                                                                   monkeypatch):
    """The repro: a tester's posting on the same tenant, naming a
    different employer, flipped the admin's own resolution of that tenant
    from a clean `linked` to `needs_review` with reason `shared_tenant`.

    The flip is decided by `tenant_employer_names`, which the ladder
    consults only on the rung-1 path: a posting whose own text names no
    employer at all, resolved purely by the tenant identifier. So the
    admin's second posting here carries no employer name, which is what
    puts the decision in the hands of whatever OTHER postings that tenant
    has on file.
    """
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
        '"hiringOrganization":{"name":"Tenant Owner AG"}}</script><main>Role text.</main>'))
    # The admin's own first posting on the tenant: creates the company and
    # teaches it the tenant identifier.
    first = clients['admin'].post('/api/jobs/intake', json={'url': TENANT_URL}).get_json()
    company_id = first['job']['company_id']
    assert company_id and first['job']['company_link_state'] == 'linked'

    # A tester's posting on the SAME tenant, naming a different employer.
    tenant_job(root, people['two']['id'], 'https://jobs.lever.co/sharedtenant/role-three',
               'Somebody Elses Employer AG')

    # The admin's next posting on that tenant, naming nobody, resolves
    # exactly as it would have before the tester added theirs.
    monkeypatch.setattr(intake, 'fetch_url',
                        lambda url: '<main>A role, with no employer named anywhere.</main>')
    second = clients['admin'].post('/api/jobs/intake',
                                   json={'url': OTHER_TENANT_URL}).get_json()
    assert second['job']['company_link_state'] == 'linked'
    assert second['job']['company_link_reason'] != 'shared_tenant'
    assert second['job']['company_id'] == company_id
    assert second['job']['company_review'] is None
    assert 'Somebody Elses Employer AG' not in body(
        clients['admin'].get(f'/api/companies/{company_id}'))


def test_a_foreign_private_job_cannot_publish_a_shared_identifier(clients, people, root,
                                                                  monkeypatch):
    """The legacy fallback derived a company link from another user's
    posting on the same tenant, and the ladder then taught that tenant
    onto the company as a shared identifier."""
    company = vault.save_company(root, {'name': 'Quiet Holdings'})
    # Only a tester's job ties this tenant to that company.
    tenant_job(root, people['two']['id'], TENANT_URL, 'Quiet Holdings', company['id'])
    before = vault.load_company(root, company['id'])['identifiers']
    assert before == []

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Posting with no employer name.</main>')
    created = clients['admin'].post('/api/jobs/intake',
                                    json={'url': OTHER_TENANT_URL}).get_json()
    # The admin's posting does not inherit the tester's link...
    assert created['job']['company_id'] != company['id']
    # ...and the tester's ATS association is not published on the shared
    # company as an identifier.
    assert vault.load_company(root, company['id'])['identifiers'] == before


def test_a_testers_resolution_reads_only_their_own_jobs(clients, people, root, monkeypatch):
    """Their own tenant history still works; the admin's is invisible to
    it, so the tester resolves on their own evidence alone."""
    company = vault.save_company(root, {'name': 'Tenant Owner AG'})
    # The admin's job ties the tenant to the company. The tester cannot
    # see it, so it cannot be their legacy hint.
    tenant_job(root, people['admin']['id'], TENANT_URL, 'Tenant Owner AG', company['id'])
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Posting with no employer name.</main>')
    theirs = clients['two'].post('/api/jobs/intake',
                                 json={'url': OTHER_TENANT_URL}).get_json()
    assert theirs['job']['company_id'] is None
    assert theirs['job']['company_link_state'] == 'pending'

    # Give the tester their own job on that tenant, linked, and the hint
    # is theirs to use: the next posting resolves off their own history.
    tenant_job(root, people['two']['id'], 'https://jobs.lever.co/sharedtenant/role-four',
               'Tenant Owner AG', company['id'])
    again = clients['two'].post('/api/jobs/intake',
                                json={'url': 'https://jobs.lever.co/sharedtenant/role-five'}).get_json()
    assert again['job']['company_id'] == company['id']
    # And still taught the shared company nothing.
    assert vault.load_company(root, company['id'])['identifiers'] == []


def test_tenant_employer_names_reads_one_scope(root, people):
    """The unit rule under both readers."""
    from careeros import enrich

    tenant_job(root, people['admin']['id'], TENANT_URL, 'Admin Employer AG')
    tenant_job(root, people['two']['id'], OTHER_TENANT_URL, 'Tester Employer AG')
    legacy = tenant_job(root, None, 'https://jobs.lever.co/sharedtenant/role-six', 'Legacy Employer AG')
    assert legacy[vault.OWNER_FIELD] is None

    admin_scope = users.owner(people['admin'])
    assert sorted(server.tenant_employer_names(root, TENANT_URL, admin_scope)) == [
        'Admin Employer AG', 'Legacy Employer AG']
    tester_scope = users.owner(people['two'])
    assert server.tenant_employer_names(root, TENANT_URL, tester_scope) == ['Tester Employer AG']
    # Unscoped is the host's own view, which is what the cron watcher and
    # the migration scripts run under.
    assert len(server.tenant_employer_names(root, TENANT_URL, None)) == 3
    # And the scope a queue path reconstructs from a record matches the
    # scope that record's owner reads under.
    assert enrich.record_owner_scope(root, {vault.OWNER_FIELD: people['two']['id']}) == tester_scope
    assert enrich.record_owner_scope(root, {}) == admin_scope


# --- resolve-review validates before it writes --------------------------

def test_a_retired_id_on_resolve_review_writes_nothing(clients, foreign_linked, records, root):
    """Blocker N2. apply_review teaches the company a name_variant on its
    way through, and the link validation ran only afterwards inside
    save_job: a retired id left the variant behind and then answered 400."""
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    job = review_job(root, records['jobs']['admin'][vault.OWNER_FIELD],
                     employer='Admin Employer Text')
    before = vault.load_company(root, foreign_linked['id'])
    retired = clients['admin'].post(f"/api/jobs/{job['id']}/resolve-review",
                                    json={'review_token': 'tok', 'company_id': foreign_linked['id']})
    absent = clients['admin'].post(f"/api/jobs/{job['id']}/resolve-review",
                                   json={'review_token': 'tok', 'company_id': 'CO-404'})
    # The same request with the same outcome, retired or never there.
    assert retired.status_code == absent.status_code == 400
    assert retired.get_json() == absent.get_json() == {'error': 'Company not found.'}
    # Byte for byte: no name_variant, no identifier, nothing.
    assert vault.load_company(root, foreign_linked['id']) == before
    assert 'Admin Employer Text' not in str(vault.load_company(root, foreign_linked['id']))
    # And the job is untouched: still in review, still unlinked.
    stored = vault.load_job(root, job['id'])
    assert stored['company_id'] is None
    assert stored['company_link_state'] == 'needs_review'


def test_a_grandfathered_id_on_resolve_review_still_works(clients, foreign_linked, records, root):
    """The validation is linkable_company, so a record already pointing
    at the retired company may re-affirm that link."""
    # The link has to predate the retire to be grandfathered, so this is
    # the tester's existing job put into review rather than a fresh one.
    job = vault.save_job(root, {
        'company_link_state': 'needs_review',
        'company_review': {'candidates': [], 'at': '2026-10-18', 'token': 'tok'},
        'employer_named_in_posting': 'Tester Employer Text',
    }, records['jobs']['two']['id'])
    clients['admin'].delete(f"/api/companies/{foreign_linked['id']}")
    response = clients['two'].post(f"/api/jobs/{job['id']}/resolve-review",
                                   json={'review_token': 'tok', 'company_id': foreign_linked['id']})
    assert response.status_code == 200
    assert response.get_json()['company_id'] == foreign_linked['id']
    # Still no variant written: the tester's store is read-only.
    assert 'Tester Employer Text' not in str(vault.load_company(root, foreign_linked['id']))


# --- No id allocation oracle -------------------------------------------
#
# Soft retire keeps the tombstone record, with its id, when a foreign
# record links the company, and removes the file when none does. The two
# answer identically by design -- but an id used to be `max stored id +
# 1`, so the NEXT company id differed: the tombstone still occupied its
# number and a removed record did not. One more company and the admin
# knew which had happened, and therefore whether somebody else privately
# links that company. Ids are monotonic now (vault.ID_COUNTER_FILE).

def one_company_vault(tmp_path, name, foreign_link):
    """A vault with one admin, one tester, one company, and the tester's
    private job linking it or not. Returns (root, clients, company)."""
    root = tmp_path / name
    root.mkdir(parents=True)
    admin = users.create_user(root, email='owner@example.test', name='Owner',
                              role='admin', password=PASSWORD)
    tester = users.create_user(root, email='one@example.test', name='Tester One',
                               role='tester', password=PASSWORD)
    company = vault.save_company(root, {'name': SHARED_COMPANY})
    if foreign_link:
        vault.save_job(root, {'title': 'Tester Posting', 'url': 'https://example.test/t',
                              'company_id': company['id'],
                              vault.OWNER_FIELD: tester['id']})
    app = server.create_app(root)
    app.config['TESTING'] = True
    client = app.test_client()
    assert client.post('/login', json={'email': admin['email'],
                                       'password': PASSWORD}).status_code == 200
    return root, client, company


def test_deleting_a_company_leaks_nothing_through_the_next_id(tmp_path, raw_session):
    """Two vaults identical but for one tester's private link on the
    company being deleted. Every admin-visible answer has to match."""
    answers, next_ids, stored = {}, {}, {}
    for foreign_link in (False, True):
        root, client, company = one_company_vault(
            tmp_path, f'vault-{foreign_link}', foreign_link)
        deleted = client.delete(f"/api/companies/{company['id']}")
        answers[foreign_link] = (deleted.status_code, deleted.get_json())
        # The admin's own next company, created through the route a
        # differential repro would use.
        position = vault.save_experience(root, {
            'title': 'Admin Position', 'company': 'Free text',
            'start': '2020-01', 'end': '2021-01'})
        created = client.post(f"/api/experiences/{position['id']}/link-company",
                              json={'create': {'name': 'A Wholly Different Name AG'},
                                    'confirm_create': True})
        assert created.status_code == 201
        next_ids[foreign_link] = created.get_json()['company_id']
        stored[foreign_link] = vault.load_company(root, company['id'])
        # Whichever vault this is, the id just handed out is not the one
        # the deleted-or-retired company holds.
        assert next_ids[foreign_link] != company['id']

    # The delete answers match, which was already true...
    assert answers[False] == answers[True] == (200, {'deleted': 'CO-001'})
    # ...and so does the next id, which is the fix.
    assert next_ids[False] == next_ids[True] == 'CO-002'
    # The two vaults really did differ: one kept the tombstone, one did
    # not. If this stops being true the test above proves nothing.
    assert stored[False] is None
    assert stored[True] is not None and stored[True]['retired'] is True


@pytest.mark.parametrize('kind,prefix', [('jobs', 'JOB-'), ('companies', 'CO-'),
                                         ('experiences', 'EXP-'), ('users', 'USER-')])
def test_no_record_kind_ever_reuses_an_id(tmp_path, kind, prefix):
    """The audit, as a rule rather than four readings of it: a number is
    handed out once, whether the record was deleted, retired or is still
    there. Notes are not here because a note id is a uuid and never a
    sequence."""
    root = tmp_path / f'ids-{kind}'
    root.mkdir(parents=True)

    def create(index):
        if kind == 'jobs':
            return vault.save_job(root, {'title': f'Job {index}',
                                         'url': f'https://example.test/{index}'})['id']
        if kind == 'companies':
            return vault.save_company(root, {'name': f'Company {index}'})['id']
        if kind == 'experiences':
            return vault.save_experience(root, {'title': f'Position {index}', 'company': 'X',
                                                'start': '2020-01', 'end': '2021-01'})['id']
        return users.create_user(root, email=f'u{index}@example.test', name=f'U{index}',
                                 role='tester', password=PASSWORD)['id']

    def remove(identifier):
        if kind == 'jobs':
            return vault.delete_job(root, identifier)
        if kind == 'companies':
            return vault.delete_company(root, identifier)
        if kind == 'experiences':
            return vault.delete_experience(root, identifier)
        # No command deletes an account, so the hand-edited file is the
        # only way this kind loses a record at all.
        return next((root / 'users').glob(f'*-{identifier.lower()}.yaml')).unlink() or True

    seen = [create(1), create(2)]
    assert seen == [f'{prefix}001', f'{prefix}002']
    # Remove the highest, and the number it held does not come back.
    assert remove(seen[-1])
    assert vault._next(root, kind) == f'{prefix}003'
    seen.append(create(3))
    assert seen[-1] == f'{prefix}003'
    # Remove them all, and allocation still only counts up.
    for identifier in (seen[0], seen[2]):
        remove(identifier)
    seen.append(create(4))
    assert seen[-1] == f'{prefix}004'
    assert len(set(seen)) == len(seen)


def test_a_retired_company_does_not_free_its_number(root, company, people):
    vault.retire_company(root, company['id'])
    assert vault.next_company_id(root) != company['id']
    assert vault.save_company(root, {'name': 'After The Retire'})['id'] != company['id']


def test_the_counter_survives_a_lost_or_hand_edited_file(root, people):
    """The disk scan stays in the maximum, so a counter file that is
    deleted, emptied or edited downwards still cannot reissue a number a
    stored record carries."""
    first = vault.save_company(root, {'name': 'One'})['id']
    second = vault.save_company(root, {'name': 'Two'})['id']
    counter = root / vault.ID_COUNTER_FILE
    assert counter.is_file()
    counter.unlink()
    assert vault.next_company_id(root) == 'CO-003'
    counter.write_text('companies: 1\n')
    assert vault.next_company_id(root) == 'CO-003'
    counter.write_text('nonsense')
    assert vault.save_company(root, {'name': 'Three'})['id'] == 'CO-003'
    assert {first, second} == {'CO-001', 'CO-002'}


# --- The oracle does not come back through the counter fallback --------
#
# The counter closed ordinary allocation, but `_highest_allocated` falls
# back to the surviving records when the counter file is missing or has
# been reset, and a hard delete used to remove the record without
# preserving its number. So on such a vault the number came back after a
# delete and did not after a retire: the differential, one layer down.
# Every hard delete now persists the high-water mark before unlinking.

#: The counter states the fallback has to answer the same under: the file
#: as the allocator leaves it, gone, and present but reset to zero.
COUNTER_STATES = ('valid', 'missing', 'reset')


def counter_state(root, state):
    path = root / vault.ID_COUNTER_FILE
    if state == 'missing':
        path.unlink(missing_ok=True)
    elif state == 'reset':
        path.write_text(''.join(f'{kind}: 0\n' for kind in vault.ID_PREFIXES))


@pytest.mark.parametrize('state', COUNTER_STATES)
@pytest.mark.parametrize('removal', ['delete', 'retire'])
def test_the_next_company_id_is_the_same_however_the_last_one_went(tmp_path, state, removal):
    """Codex's repro table, all six cells. The id handed out next must be
    the same whichever counter state the vault is in and whichever way
    the highest-numbered company left, and must never be the number that
    left."""
    root = tmp_path / f'{state}-{removal}'
    root.mkdir(parents=True)
    target = vault.save_company(root, {'name': 'Target'})
    # A job linking it, which is what makes the retire branch reachable
    # at the endpoint and is harmless here.
    vault.save_job(root, {'title': 'J', 'url': 'https://example.test/j',
                          'company_id': target['id']})
    counter_state(root, state)

    if removal == 'delete':
        assert vault.delete_company(root, target['id']) is True
        assert vault.load_company(root, target['id']) is None
    else:
        assert vault.retire_company(root, target['id'])['retired'] is True

    assert vault.next_company_id(root) == 'CO-002'
    assert vault.save_company(root, {'name': 'Next'})['id'] == 'CO-002'
    assert vault.next_company_id(root) == 'CO-003'


@pytest.mark.parametrize('state', COUNTER_STATES)
@pytest.mark.parametrize('kind', ['jobs', 'experiences'])
def test_a_hard_delete_never_frees_its_number_in_any_counter_state(tmp_path, state, kind):
    """The same for the two kinds that only ever hard-delete: they have
    no tombstone to compare against, but the freed number was readable
    all the same."""
    root = tmp_path / f'{kind}-{state}'
    root.mkdir(parents=True)
    prefix = vault.ID_PREFIXES[kind]
    if kind == 'jobs':
        first = vault.save_job(root, {'title': 'One', 'url': 'https://example.test/1'})['id']
        second = vault.save_job(root, {'title': 'Two', 'url': 'https://example.test/2'})['id']
        remove, create = vault.delete_job, (
            lambda: vault.save_job(root, {'title': 'Three', 'url': 'https://example.test/3'}))
    else:
        make = lambda n: vault.save_experience(root, {'title': n, 'company': 'X',
                                                      'start': '2020-01', 'end': '2021-01'})
        first, second = make('One')['id'], make('Two')['id']
        remove, create = vault.delete_experience, (lambda: make('Three'))
    assert [first, second] == [f'{prefix}001', f'{prefix}002']

    counter_state(root, state)
    assert remove(root, second)
    # Deleting the lower one too, so nothing stored carries a number at
    # all: the fallback has nothing left to recover from.
    assert remove(root, first)
    assert vault._next(root, kind) == f'{prefix}003'
    assert create()['id'] == f'{prefix}003'


def test_a_hard_delete_writes_the_counter_file_on_a_vault_that_had_none(tmp_path):
    """The invariant `_highest_allocated`'s fallback relies on: a vault
    that has ever deleted through this module has a counter file, so
    falling back to the surviving records only ever happens on a vault
    that has never deleted."""
    root = tmp_path / 'invariant'
    root.mkdir(parents=True)
    company = vault.save_company(root, {'name': 'Only'})
    (root / vault.ID_COUNTER_FILE).unlink()
    assert not (root / vault.ID_COUNTER_FILE).exists()
    vault.delete_company(root, company['id'])
    assert (root / vault.ID_COUNTER_FILE).is_file()
    assert vault._read(root / vault.ID_COUNTER_FILE)['companies'] == 1


def test_retaining_the_high_water_mark_is_idempotent(tmp_path):
    root = tmp_path / 'retain'
    root.mkdir(parents=True)
    vault.save_company(root, {'name': 'One'})
    # The allocator already recorded it, so there is nothing to retain.
    assert vault.retain_id_high_water(root, 'companies') is None
    # A kind with no records has no mark to record either.
    assert vault.retain_id_high_water(root, 'experiences') is None
    (root / vault.ID_COUNTER_FILE).unlink()
    assert vault.retain_id_high_water(root, 'companies') == 1
    assert vault.retain_id_high_water(root, 'companies') is None


def test_initialize_id_counters_seeds_an_existing_vault_once(tmp_path):
    """The migration angle: the live vault predates the counter, so it is
    seeded from what is stored and only once."""
    root = tmp_path / 'legacy'
    root.mkdir(parents=True)
    vault.save_job(root, {'title': 'One', 'url': 'https://example.test/1'})
    vault.save_job(root, {'title': 'Two', 'url': 'https://example.test/2'})
    vault.save_company(root, {'name': 'One'})
    (root / vault.ID_COUNTER_FILE).unlink()

    assert vault.initialize_id_counters(root) == {'jobs': 2, 'companies': 1}
    # Idempotent: a second pass records nothing.
    assert vault.initialize_id_counters(root) == {}
    # And it never pulls a counter down to the stored records, which is
    # the state every vault is in once anything has been deleted.
    vault.delete_job(root, 'JOB-002')
    assert vault.initialize_id_counters(root) == {}
    assert vault.next_job_id(root) == 'JOB-003'


def test_the_migration_initializes_counters_idempotently(tmp_path, capsys):
    """Through the script the owner actually runs."""
    import sys
    sys.path.insert(0, str(server.Path(__file__).resolve().parents[1] / 'scripts'))
    import migrate_record_owner as migrate

    root = tmp_path / 'migrate-ids'
    root.mkdir(parents=True)
    users.create_user(root, email='owner@example.test', name='Owner',
                      role='admin', password=PASSWORD)
    vault.save_job(root, {'title': 'Legacy', 'url': 'https://example.test/legacy'})
    vault.save_company(root, {'name': 'Legacy Co'})
    (root / vault.ID_COUNTER_FILE).unlink()

    # The dry run reports the marks and writes nothing.
    assert migrate.main(['--vault', str(root)]) == 0
    assert 'id high-water marks to record' in capsys.readouterr().out
    assert not (root / vault.ID_COUNTER_FILE).exists()

    assert migrate.main(['--vault', str(root), '--apply']) == 0
    assert 'recorded id high-water marks' in capsys.readouterr().out
    recorded = vault._read(root / vault.ID_COUNTER_FILE)
    assert recorded['jobs'] == 1 and recorded['companies'] == 1 and recorded['users'] == 1

    # Safe twice: nothing left to record, and the file does not move.
    before = (root / vault.ID_COUNTER_FILE).read_bytes()
    assert migrate.main(['--vault', str(root), '--apply']) == 0
    assert 'already records every id high-water mark' in capsys.readouterr().out
    assert (root / vault.ID_COUNTER_FILE).read_bytes() == before


# --- The reservation tombstone -----------------------------------------
#
# The counter closed ordinary allocation and the pre-delete mark closed
# the vault that had never written one. What stayed open was damage AFTER
# a hard delete: lose, reset or corrupt the counter then, and the
# fallback reads only the records that survive, where a deleted number
# left no trace at all -- while a retired one is still a stored record.
# So a hard delete now reserves its number in the directory the fallback
# scans. A tombstone holds the id and the word reserved, and nothing
# else, and no record reader ever sees one.

#: Every way the counter file can stop being usable. `corrupt` is the one
#: the earlier rounds missed: `_read` answers None for it, exactly like a
#: missing file.
COUNTER_DAMAGE = ('valid', 'missing', 'reset', 'corrupt')


def damage_counter(root, state):
    path = root / vault.ID_COUNTER_FILE
    if state == 'missing':
        path.unlink(missing_ok=True)
    elif state == 'reset':
        path.write_text(''.join(f'{kind}: 0\n' for kind in vault.ID_PREFIXES))
    elif state == 'corrupt':
        path.write_text('[ not a mapping at all')


@pytest.mark.parametrize('state', COUNTER_DAMAGE)
@pytest.mark.parametrize('removal', ['delete', 'retire'])
def test_the_next_id_survives_counter_damage_after_the_removal(tmp_path, state, removal):
    """The post-delete repro table. The counter is damaged AFTER the
    company goes, so the mark written before the delete is no help: only
    the reservation keeps the number out of circulation."""
    root = tmp_path / f'post-{state}-{removal}'
    root.mkdir(parents=True)
    target = vault.save_company(root, {'name': 'Target'})
    vault.save_job(root, {'title': 'J', 'url': 'https://example.test/j',
                          'company_id': target['id']})
    if removal == 'delete':
        assert vault.delete_company(root, target['id']) is True
    else:
        assert vault.retire_company(root, target['id'])['retired'] is True
    damage_counter(root, state)

    assert vault.next_company_id(root) == 'CO-002'
    assert vault.save_company(root, {'name': 'Next'})['id'] == 'CO-002'


@pytest.mark.parametrize('state', COUNTER_DAMAGE)
@pytest.mark.parametrize('kind', ['jobs', 'experiences'])
def test_a_deleted_number_survives_counter_damage_for_every_kind(tmp_path, state, kind):
    """The two kinds that only hard-delete, with every record of the kind
    removed so the fallback has nothing but the reservations."""
    root = tmp_path / f'post-{kind}-{state}'
    root.mkdir(parents=True)
    prefix = vault.ID_PREFIXES[kind]
    if kind == 'jobs':
        make = lambda n: vault.save_job(root, {'title': n, 'url': f'https://example.test/{n}'})
        remove = vault.delete_job
    else:
        make = lambda n: vault.save_experience(root, {'title': n, 'company': 'X',
                                                      'start': '2020-01', 'end': '2021-01'})
        remove = vault.delete_experience
    first, second = make('One')['id'], make('Two')['id']
    assert [first, second] == [f'{prefix}001', f'{prefix}002']
    assert remove(root, second) and remove(root, first)
    damage_counter(root, state)

    assert vault._next(root, kind) == f'{prefix}003'
    assert make('Three')['id'] == f'{prefix}003'


def test_the_endpoint_answers_the_same_whichever_way_the_company_went(tmp_path, raw_session):
    """Through the route the differential repro uses, with the counter
    destroyed after the delete: same 200 shape, same next id, whether a
    foreign private link made it a retire or not."""
    answers, next_ids, tombstones = {}, {}, {}
    for foreign_link in (False, True):
        root, client, company = one_company_vault(
            tmp_path, f'post-vault-{foreign_link}', foreign_link)
        deleted = client.delete(f"/api/companies/{company['id']}")
        answers[foreign_link] = (deleted.status_code, deleted.get_json())
        damage_counter(root, 'corrupt')
        position = vault.save_experience(root, {
            'title': 'Admin Position', 'company': 'Free text',
            'start': '2020-01', 'end': '2021-01'})
        created = client.post(f"/api/experiences/{position['id']}/link-company",
                              json={'create': {'name': 'A Wholly Different Name AG'},
                                    'confirm_create': True})
        assert created.status_code == 201
        next_ids[foreign_link] = created.get_json()['company_id']
        tombstones[foreign_link] = sorted(
            p.name for p in (root / 'companies').glob(f'{vault.RESERVED_PREFIX}*.yaml'))
    assert answers[False] == answers[True] == (200, {'deleted': 'CO-001'})
    assert next_ids[False] == next_ids[True] == 'CO-002'
    # The two vaults really did take different branches: one reserved the
    # number, the other kept the record.
    assert tombstones[False] == ['_reserved-co-001.yaml']
    assert tombstones[True] == []


def test_a_tombstone_holds_the_id_and_nothing_else(root, company, people):
    """It is a number taken out of circulation, not a record of
    anything: no name, no owner, no counts, no user data at all."""
    stored = vault.load_company(root, company['id'])
    assert stored['name'] == SHARED_COMPANY
    vault.delete_company(root, company['id'])
    path = next((root / 'companies').glob(f'{vault.RESERVED_PREFIX}*.yaml'))
    assert vault._read(path) == {'id': company['id'], 'reserved': True}
    assert vault.is_reserved(vault._read(path)) is True
    # Nothing of the company it replaced is anywhere in the file.
    text = path.read_text()
    assert SHARED_COMPANY not in text and 'sector' not in text and 'size' not in text


def test_a_job_tombstone_holds_no_posting_data(root, people):
    """The same for the private kinds, where the record it replaces is
    one user's and nobody else's."""
    job = vault.save_job(root, {
        'title': 'Very Private Posting', 'url': 'https://example.test/private',
        'description': 'Secret posting text.', 'employer_named_in_posting': 'Secret Employer AG',
        vault.OWNER_FIELD: people['two']['id']})
    vault.delete_job(root, job['id'])
    path = next((root / 'jobs').glob(f'{vault.RESERVED_PREFIX}*.yaml'))
    assert vault._read(path) == {'id': job['id'], 'reserved': True}
    text = path.read_text()
    for secret in ('Very Private Posting', 'Secret posting text.', 'Secret Employer AG',
                   people['two']['id']):
        assert secret not in text


#: Every reader the audit covers, as (name, callable taking the vault
#: root and the admin's scope). Each one must answer without the
#: tombstone's id anywhere in it.
def tombstone_readers():
    from careeros import enrich
    from careeros.org_store import VaultOrganisationStore
    from careeros.web.pages import companies as companies_page
    from careeros.web.pages import experiences as experiences_page
    from careeros.web.pages import jobs as jobs_page
    from careeros.web.pages import notes as notes_page
    from careeros.web.pages import taxonomy as taxonomy_page
    return {
        'list_companies': lambda root, scope: vault.list_companies(root),
        'visible_companies': lambda root, scope: vault.visible_companies(root, scope),
        'load_company': lambda root, scope: vault.load_company(root, 'CO-001'),
        'may_see_company': lambda root, scope: vault.may_see_company(root, 'CO-001', scope),
        'linkable_company': lambda root, scope: vault.linkable_company(root, 'CO-001'),
        'linkable_company_grandfathered':
            lambda root, scope: vault.linkable_company(root, 'CO-001', current='CO-001'),
        'directory': lambda root, scope: companies_page.page_context(root, scope),
        'board': lambda root, scope: jobs_page.page_context(root, scope),
        'experiences_library': lambda root, scope: experiences_page.page_context(root, scope),
        'position_form': lambda root, scope: experiences_page.form_context(root, None, scope),
        'notes_page': lambda root, scope: notes_page.page_context(root, scope),
        'taxonomy_page': lambda root, scope: taxonomy_page.taxonomy_context(root, scope),
        'resolution_candidates':
            lambda root, scope: VaultOrganisationStore(root).list_organisations(),
        'resolution_load':
            lambda root, scope: VaultOrganisationStore(root).load_organisation('CO-001'),
        'rollup_jobs': lambda root, scope: enrich.shared_jobs(root),
        'list_users': lambda root, scope: users.list_users(root),
        'list_jobs': lambda root, scope: vault.list_jobs(root, scope),
        'list_experiences': lambda root, scope: vault.list_experiences(root, scope),
    }


@pytest.mark.parametrize('reader', sorted(tombstone_readers()))
def test_a_tombstone_is_invisible_to_every_reader(tmp_path, reader):
    """The audit, pinned one reader at a time. Filtering happens at
    `_records`, so this is really one rule -- but a later reader that
    bypasses it would show up here rather than in a privacy review."""
    import json

    root = tmp_path / f'invisible-{reader}'
    root.mkdir(parents=True)
    admin = users.create_user(root, email='owner@example.test', name='Owner',
                              role='admin', password=PASSWORD)
    gone = vault.save_company(root, {'name': 'Deleted Holdings'})
    vault.save_company(root, {'name': 'Kept Holdings'})
    doomed_job = vault.save_job(root, {'title': 'Doomed', 'url': 'https://example.test/d'})
    doomed_position = vault.save_experience(root, {'title': 'Doomed', 'company': 'X',
                                                   'start': '2020-01', 'end': '2021-01'})
    assert gone['id'] == 'CO-001'
    vault.delete_company(root, gone['id'])
    vault.delete_job(root, doomed_job['id'])
    vault.delete_experience(root, doomed_position['id'])
    # Every kind now holds a tombstone, so one reader cannot pass by
    # looking at the wrong directory.
    for kind in ('companies', 'jobs', 'experiences'):
        assert list((root / kind).glob(f'{vault.RESERVED_PREFIX}*.yaml'))

    answer = tombstone_readers()[reader](root, users.owner(admin))
    text = json.dumps(answer, default=str)
    for identifier in (gone['id'], doomed_job['id'], doomed_position['id']):
        assert identifier not in text, f'{reader} leaked {identifier}'
    assert '"reserved"' not in text and "'reserved'" not in text


def test_a_tombstone_is_not_a_foreign_link_for_the_deletion_check(clients, root, records,
                                                                  people):
    """The unscoped foreign-link check behind soft retire counts records,
    so a tombstone counting as one would turn an ordinary delete into a
    retire and keep a company alive forever."""
    spare = vault.save_company(root, {'name': 'Spare Holdings'})
    doomed = vault.save_job(root, {'title': 'Doomed', 'url': 'https://example.test/doomed',
                                   'company_id': spare['id'],
                                   vault.OWNER_FIELD: people['two']['id']})
    # The only record linking it goes, leaving a tombstone behind.
    vault.delete_job(root, doomed['id'])
    assert list((root / 'jobs').glob(f'{vault.RESERVED_PREFIX}*.yaml'))
    # Nothing links the company now, so this is a removal and not a retire.
    response = clients['admin'].delete(f"/api/companies/{spare['id']}")
    assert response.status_code == 200
    assert vault.load_company(root, spare['id']) is None
    assert list((root / 'companies').glob(f'{vault.RESERVED_PREFIX}*.yaml'))


def test_a_reserved_id_is_never_handed_out_again(root, people):
    """The whole point, stated once: the number is out of circulation."""
    first = vault.save_company(root, {'name': 'One'})['id']
    vault.delete_company(root, first)
    (root / vault.ID_COUNTER_FILE).unlink()
    for index in range(3):
        assert vault.save_company(root, {'name': f'Later {index}'})['id'] != first
    assert vault.reserve_id(root, 'companies', 'not-an-id') is None


# --- CAREER-41: a company note is private to its author -------------------

@pytest.fixture
def authored_company_notes(root, company, people):
    """One company note per user, each stamped with its author, plus one
    legacy note with no author at all (written before CAREER-41)."""
    notes = {}
    for key, user in people.items():
        notes[key] = vault.new_note(f'{key} company note', f'Body by {key}.',
                                    author_id=user['id'])
    legacy = vault.new_note('Legacy company note', 'Body from before authorship.')
    vault.save_company(root, vault.notes_payload([legacy, *notes.values()]), company['id'])
    return {'legacy': legacy, 'authored': notes}


#: Every path that carries a company's notes to a reader. All three must
#: answer with this reader's own notes and nobody else's.
COMPANY_NOTE_READ_PATHS = (
    lambda cid: f'/api/companies/{cid}?view=page',
    lambda cid: f'/api/companies/{cid}',
    lambda cid: '/api/notes',
)


def _note_titles(response_json, route):
    """The company-note titles one read path answered with. The three
    paths carry the same notes in three shapes: the page context's
    migrated `notes` list, the raw record's `note_list`, and the roll-up's
    rows (which mix job notes in, so only the company ones count)."""
    if route.endswith('/api/notes'):
        return {row['title'] for row in response_json['notes']
                if row['company_id'] is not None}
    if route.endswith('?view=page'):
        return {note['title'] for note in response_json['notes']}
    return {note['title'] for note in response_json['note_list']}


@pytest.mark.parametrize('route', COMPANY_NOTE_READ_PATHS,
                         ids=['detail-page', 'plain-record', 'notes-rollup'])
def test_a_company_note_is_visible_to_its_author_alone(clients, company, people,
                                                       authored_company_notes, route):
    """The one CAREER-41 rule, over all three read paths: a user reads
    their own company notes and nobody else's. The admin is no exception
    for authored notes, and is the only reader of the legacy one."""
    url = route(company['id'])
    for key, client in clients.items():
        response = client.get(url)
        assert response.status_code == 200, f'{key} {url}'
        titles = _note_titles(response.get_json(), url)
        expected = {f'{key} company note'}
        if key == 'admin':
            expected.add('Legacy company note')
        assert titles == expected, f'{key} {url}'


def test_a_company_note_cannot_be_edited_or_deleted_by_a_stranger(
        clients, company, people, authored_company_notes, root):
    """Edit and delete are the author's alone: another user's note id
    answers exactly like a note that does not exist (404), and the stored
    note survives untouched. The admin gets the same 404 over a user's
    authored note."""
    for key, client in clients.items():
        for other_key, other_user in people.items():
            if other_key == key:
                continue
            note = authored_company_notes['authored'][other_key]
            base = f'/api/companies/{company["id"]}/notes/{note["id"]}'
            patched = client.patch(base, json={'title': 'Rewritten by a stranger'})
            assert patched.status_code == 404, f'{key} patch {other_key}'
            deleted = client.delete(base)
            assert deleted.status_code == 404, f'{key} delete {other_key}'
    stored = vault.load_company(root, company['id'])
    titles = {n['title'] for n in stored['note_list']}
    assert titles == {'Legacy company note',
                      'admin company note', 'one company note', 'two company note'}


def test_a_legacy_company_note_is_the_admins_alone(
        clients, company, authored_company_notes, root):
    """A note with no author_id predates CAREER-41 and belongs to the
    admin by the same inheritance rule as an ownerless record: testers
    cannot read, edit or delete it, and no migration rewrites it."""
    legacy = authored_company_notes['legacy']
    assert legacy.get('author_id') is None
    for key in ('one', 'two'):
        client = clients[key]
        url = f'/api/companies/{company["id"]}?view=page'
        assert 'Legacy company note' not in body(client.get(url))
        assert 'Legacy company note' not in body(client.get('/api/notes'))
        base = f'/api/companies/{company["id"]}/notes/{legacy["id"]}'
        assert client.patch(base, json={'title': 'x'}).status_code == 404
        assert client.delete(base).status_code == 404
    # The admin reads it on every path and may edit it.
    admin = clients['admin']
    page = admin.get(f'/api/companies/{company["id"]}?view=page').get_json()
    assert 'Legacy company note' in {n['title'] for n in page['notes']}
    base = f'/api/companies/{company["id"]}/notes/{legacy["id"]}'
    assert admin.patch(base, json={'title': 'Legacy, kept'}).status_code == 200
    # Still no author after the edit: nothing rewrites a legacy note into
    # an authored one.
    stored = vault.load_company(root, company['id'])
    kept = next(n for n in stored['note_list'] if n['id'] == legacy['id'])
    assert kept['title'] == 'Legacy, kept'
    assert kept.get('author_id') is None


def test_a_tester_can_add_a_company_note(clients, company, people, root):
    """Adding is open to every signed-in user, and the new note is
    stamped with the session user's id here -- never taken from the
    payload, which a client could set to somebody else."""
    created = clients['one'].post(f'/api/companies/{company["id"]}/notes',
                                  json={'title': 'My own note', 'body': 'Private thoughts.',
                                        'author_id': people['two']['id']})
    assert created.status_code == 201
    note = created.get_json()
    assert note['author_id'] == people['one']['id'], 'the payload cannot name the author'
    stored = vault.load_company(root, company['id'])
    stored_note = next(n for n in stored['note_list'] if n['id'] == note['id'])
    assert stored_note['author_id'] == people['one']['id']
    # Visible to its author, and to nobody else -- not even the admin.
    one_page = clients['one'].get(f'/api/companies/{company["id"]}?view=page').get_json()
    assert 'My own note' in {n['title'] for n in one_page['notes']}
    admin_page = clients['admin'].get(f'/api/companies/{company["id"]}?view=page').get_json()
    assert 'My own note' not in {n['title'] for n in admin_page['notes']}
    two_page = clients['two'].get(f'/api/companies/{company["id"]}?view=page').get_json()
    assert 'My own note' not in {n['title'] for n in two_page['notes']}
    # The author can edit and delete what they just wrote.
    base = f'/api/companies/{company["id"]}/notes/{note["id"]}'
    assert clients['one'].patch(base, json={'body': 'Edited.'}).status_code == 200
    assert clients['one'].delete(base).status_code == 200
    stored = vault.load_company(root, company['id'])
    assert note['id'] not in {n['id'] for n in stored['note_list']}


def test_an_author_note_write_preserves_notes_they_cannot_see(
        clients, company, people, authored_company_notes, root):
    """The write path saves against the FULL stored record: a tester's
    add/edit/delete must not silently drop the admin's legacy note or the
    other users' notes they can neither see nor address."""
    clients['one'].post(f'/api/companies/{company["id"]}/notes',
                        json={'title': 'Addition', 'body': ''})
    stored = vault.load_company(root, company['id'])
    assert {'Legacy company note', 'admin company note', 'two company note'} \
        <= {n['title'] for n in stored['note_list']}
    own = next(n for n in stored['note_list'] if n['title'] == 'one company note')
    base = f'/api/companies/{company["id"]}/notes/{own["id"]}'
    assert clients['one'].patch(base, json={'title': 'Renamed mine'}).status_code == 200
    assert clients['one'].delete(base).status_code == 200
    stored = vault.load_company(root, company['id'])
    assert {'Legacy company note', 'admin company note', 'two company note', 'Addition'} \
        == {n['title'] for n in stored['note_list']}


# --- The public-posting projection (privacy audit 2026-10-27) ------------
#
# Findings 1, 3, 5 and 6 of docs/audits/2026-10-27-privacy.md, under one
# owner decision: shared data is derived ONLY from public postings -- a
# record no user owns -- and a shared surface answers with an explicit
# allowlist of public posting facts rather than with whatever a record
# happens to hold.

#: The keys the All jobs payload adds to each entry on its way out
#: (`web.pages.jobs.universe_context`, `board_context` and the API's own
#: company decorations). Named here so the projection assertions below
#: can subtract them and hold what is left against the allowlist.
UNIVERSE_DECORATIONS = {'on_my_board', 'needs_attention', 'company_name',
                        'company_industry', 'company_size_class', 'pending'}

#: What a reader who does not own a job must never receive about it: the
#: notes and who wrote them, the history, the custom data, the provenance
#: and review bookkeeping, this installation's own ingest and AI run
#: state, somebody's workflow status and board state, and the user stamp.
PRIVATE_JOB_KEYS = (
    'notes', 'note_list', 'history', 'custom', 'field_provenance',
    'field_status', 'field_status_reason', 'values', 'company_review',
    'company_link_state', 'company_link_reason', 'status', 'in_pipeline',
    'added', 'closed_at', 'closed_reviewed_at', 'end_reason',
    'ai_status', 'ai_error', 'ai_started', 'ai_finished',
    'ingest_state', 'ingest_error', 'ingest_source', 'enriched',
    'origin', 'source', 'refresh', vault.OWNER_FIELD,
)

PRIVATE_NOTE_BODY = 'Rang the hiring manager at home.'
PRIVATE_CUSTOM_VALUE = 'salary floor 180k, do not share'


@pytest.fixture
def loaded_pool_job(root, people, company):
    """A job no user owns, carrying everything a reader of somebody
    else's record must not see: a note with an author, history events,
    custom data and field provenance.

    Ownerless is the admin's by inheritance (`vault.Owner`), so this is
    exactly the record finding 1 is about -- the admin's own handling of
    an inherited posting, on a tab every signed-in user reads.
    """
    created = vault.save_job(root, {
        'title': 'Loaded Pool Posting', 'url': 'https://example.test/pool/loaded',
        'company_id': company['id'], 'location': 'Zurich', 'status': 'interviewing',
        'description': 'Pool posting text.', 'posted_date': '2026-02-02',
        'custom': {'secret': PRIVATE_CUSTOM_VALUE},
        'field_provenance': {'title': 'user'},
        **vault.notes_payload([vault.new_note('Pool note', PRIVATE_NOTE_BODY,
                                              people['admin']['id'])]),
    })
    # A second write, so the record carries real history events rather
    # than only the one its creation wrote.
    return vault.save_job(root, {'status': 'offer'}, created['id'],
                          history_event=('note_added', 'Rang them again.'))


def universe_entry(client, job_id):
    entries = client.get(UNIVERSE).get_json()['entries']
    return next(entry for entry in entries if entry['id'] == job_id)


def test_the_allowlist_only_names_fields_a_job_actually_stores(root):
    """A typo in the allowlist would deny a field in silence, which is
    the one failure an allowlist cannot report for itself."""
    assert vault.PUBLIC_POSTING_FIELDS - {'id'} <= vault.job_field_names()
    # And the categories the owner decision excludes are excluded.
    assert not vault.PUBLIC_POSTING_FIELDS & set(PRIVATE_JOB_KEYS)


def test_a_reader_who_does_not_own_a_job_gets_public_posting_facts_only(
        clients, people, records, loaded_pool_job):
    """Finding 1. The All jobs tab answered with the complete job record,
    so an admin's notes, note authors, history, custom data and workflow
    state on an inherited ownerless posting were readable by every
    signed-in user."""
    for key in ('one', 'two'):
        entry = universe_entry(clients[key], loaded_pool_job['id'])
        for field in PRIVATE_JOB_KEYS:
            assert field not in entry, (key, field)
        # No value of any private field reaches the response in any
        # shape, nested or not. (The status vocabulary itself is in the
        # payload for the filter bar, so the stored status is checked by
        # key absence above rather than by text.)
        text = body(clients[key].get(UNIVERSE))
        for secret in (PRIVATE_NOTE_BODY, PRIVATE_CUSTOM_VALUE, 'Pool note',
                       people['admin']['id']):
            assert secret not in text, (key, secret)
        # The posting itself still reads, so the tab is not broken.
        assert entry['title'] == 'Loaded Pool Posting'
        assert (entry['location'], entry['posted_date']) == ('Zurich', '2026-02-02')
        # And nothing outside the allowlist is left: a field added to the
        # record later cannot ride onto this tab without a decision.
        assert set(entry) - UNIVERSE_DECORATIONS <= vault.PUBLIC_POSTING_FIELDS, key


def test_the_reader_keeps_their_own_jobs_whole_on_the_same_tab(clients, records,
                                                              loaded_pool_job):
    """The other half of finding 1's fix: the projection applies to the
    records a reader does NOT own. Their own entry is their own data and
    the tab is where they act on it, so it stays the full record -- and
    for the admin an ownerless record IS their own (`vault.Owner`)."""
    mine = universe_entry(clients['one'], records['jobs']['one']['id'])
    assert mine['status'] == 'interested' and mine[vault.OWNER_FIELD]
    assert mine['note_list'] and 'history' in mine
    admins = universe_entry(clients['admin'], loaded_pool_job['id'])
    assert admins['status'] == 'offer' and admins['note_list']


def test_an_owned_job_puts_nothing_of_itself_on_a_shared_company(clients, people,
                                                                 root, company):
    """Finding 3, from the endpoint a tester reads. The rollup published a
    posting's id and posting date in the headcount evidence, plus the
    company's posting count, locations, keywords and seniority range --
    derived from admin-owned jobs as well as public ones."""
    admin_job = vault.save_job(root, {
        'title': 'Admin Private Posting', 'url': 'https://example.test/admin-private',
        'company_id': company['id'], 'location': 'Admin Valley',
        'keywords': ['adminsecret'], 'seniority': 'director',
        'employee_count': 4242, 'posted_date': '2026-03-03',
        'contact_email': 'admin-private@shared.example',
        vault.OWNER_FIELD: people['admin']['id']})
    public_job = vault.save_job(root, {
        'title': 'Public Posting', 'url': 'https://example.test/public-roll2',
        'company_id': company['id'], 'location': 'Bern', 'keywords': ['publicword'],
        'seniority': 'junior', 'employee_count': 11, 'posted_date': '2026-01-01'})

    # Not the seniority: "director" is a substring of the companies
    # directory's own empty state. The seniority range is asserted
    # outright below instead.
    traces = (admin_job['id'], '2026-03-03', 'Admin Valley', 'adminsecret',
              '4242', 'admin-private@shared.example')
    # Every company surface, read by the users who do NOT own that job.
    # The profile's job section is the reader's OWN board by design (B3),
    # so the admin reading their own posting there is not the leak; what
    # finding 3 is about is the shared half carrying it to everybody.
    for key in ('one', 'two'):
        for path in (f"/api/companies/{company['id']}",
                     f"/api/companies/{company['id']}?view=page",
                     '/api/companies', '/api/companies?view=page'):
            text = body(clients[key].get(path))
            for trace in traces:
                assert trace not in text, (key, path, trace)

    # The counts are the public postings', not "every job at this company".
    enrichment = enrichment_of(root, company['id'])
    assert enrichment['hiring_activity'] == {'count': 1, 'most_recent_posted_date': '2026-01-01'}
    assert enrichment['locations_seen'] == ['Bern']
    assert enrichment['top_keywords'] == ['publicword']
    assert enrichment['seniority_range'] == {'min': 'junior', 'max': 'junior'}
    assert enrichment['employee_count_evidence'] == {
        'count': 11, 'job_id': public_job['id'], 'posted_date': '2026-01-01'}
    # And the contact promotion follows the same rule.
    assert vault.load_company(root, company['id'])['contact_email'] == ''


def test_a_testers_owned_job_puts_nothing_of_itself_on_a_shared_company(clients, people,
                                                                       root, company):
    """The rule the M2 split already had, kept green beside the admin's
    half above: owning a job is what keeps it out, whoever owns it."""
    tester_job = vault.save_job(root, {
        'title': 'Tester Private Posting', 'url': 'https://example.test/tester-private',
        'company_id': company['id'], 'location': 'Tester Valley',
        'keywords': ['testersecret'], 'employee_count': 777, 'posted_date': '2026-04-04',
        vault.OWNER_FIELD: people['one']['id']})
    for key in ('admin', 'two'):
        text = body(clients[key].get(f"/api/companies/{company['id']}?view=page"))
        for trace in (tester_job['id'], '2026-04-04', 'Tester Valley', 'testersecret', '777'):
            assert trace not in text, (key, trace)
    assert enrichment_of(root, company['id']) == {}


def test_add_to_my_jobs_copies_the_public_posting_facts_and_nothing_else(
        clients, people, root, loaded_pool_job):
    """Finding 6. The copy was every allowlisted job field minus a short
    blacklist, so `custom`, `field_provenance`, `values` and
    `company_review` travelled wholesale into the adding user's own
    record -- carrying somebody else's private text, stamped as theirs."""
    response = clients['one'].post(f"/api/jobs/{loaded_pool_job['id']}/promote")
    assert response.status_code == 201, body(response)
    added = response.get_json()
    stored = vault.load_job(root, added['id'])

    # A stored record always holds every field the vault defines, so the
    # check is on the VALUES: a field outside the allowlist is still its
    # own default, which is to say nothing travelled. The four the old
    # blacklist let through first:
    defaults = vault._record_defaults('jobs')
    for field in ('custom', 'field_provenance', 'values', 'company_review',
                  'notes', 'note_list', 'field_status', 'field_status_reason'):
        assert stored[field] == defaults[field], field
    assert PRIVATE_NOTE_BODY not in body(response)
    assert PRIVATE_CUSTOM_VALUE not in body(response)
    # Then every other field outside the allowlist, so a field added to
    # the record later cannot travel without a decision. The six the new
    # record sets for itself are named; `normalized_url` is computed from
    # the copied link by `add_job_to_board` and is allowlisted anyway.
    own = {'id', 'history', 'added', vault.OWNER_FIELD, 'status', 'in_pipeline'}
    for field, default in defaults.items():
        if field in vault.PUBLIC_POSTING_FIELDS or field in own:
            continue
        assert stored[field] == default, field

    # The posting travelled, the record is the adder's, and it starts on
    # their board in New with its own history.
    assert (stored['title'], stored['url'], stored['description']) == (
        loaded_pool_job['title'], loaded_pool_job['url'], loaded_pool_job['description'])
    assert stored[vault.OWNER_FIELD] == people['one']['id']
    assert (stored['status'], stored['in_pipeline']) == ('new', True)
    # Its own history: the add, and the creation the vault records for
    # every new record. None of the source record's events.
    assert [event['event'] for event in stored['history']] == ['promoted', 'created']
    # The source record is untouched and still holds its owner's own half.
    assert vault.load_job(root, loaded_pool_job['id'])['custom'] == {
        'secret': PRIVATE_CUSTOM_VALUE}


def test_the_company_schema_only_names_fields_a_company_actually_stores(root):
    assert vault.SHARED_COMPANY_FIELDS - {'id'} <= vault.company_field_names()


def test_a_non_admin_reads_the_shared_company_schema_and_no_more(clients, records,
                                                                 company, root):
    """Finding 5. `reader_company` filtered the notes and let `custom`,
    `field_provenance`, `review_flags`, `identifiers`, `sources` and
    `contact_email` through raw, so private text or an attribution placed
    in any of them reached every tester."""
    vault.save_company(root, {
        'custom': {'internal': 'board contact: ceo@private.example'},
        'contact_email': 'desk@shared.example',
        'review_flags': ['sector-ambiguous'],
    }, company['id'])
    withheld = ('custom', 'field_provenance', 'review_flags', 'identifiers',
                'sources', 'contact_email', 'name_source')
    paths = (f"/api/companies/{company['id']}", '/api/companies')

    for key in ('one', 'two'):
        for path in paths:
            payload = clients[key].get(path).get_json()
            record = payload[0] if isinstance(payload, list) else payload
            for field in withheld:
                assert field not in record, (key, path, field)
            assert 'ceo@private.example' not in body(clients[key].get(path))
            # And nothing outside the schema is left.
            assert set(record) <= vault.SHARED_COMPANY_FIELDS, (key, path)
        # The shared facts the surfaces actually render still arrive.
        page = clients[key].get(f"/api/companies/{company['id']}?view=page").get_json()
        assert page['company']['name'] == SHARED_COMPANY
        assert page['company']['sectors'] == ['J']
        assert page['company']['size_class'] == 'small'

    # The admin reads the record whole: they are the one person who may
    # change a company, and Edit company, Edit classification and Retry
    # are offered to nobody else.
    admin_record = clients['admin'].get(f"/api/companies/{company['id']}").get_json()
    assert admin_record['custom'] == {'internal': 'board contact: ceo@private.example'}
    assert admin_record['contact_email'] == 'desk@shared.example'
