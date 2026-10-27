"""Protects per-user search criteria (2026-10-27 privacy audit, finding 4).

Criteria used to be one shared `search.yaml`: every signed-in user read
the last saver's roles, must-haves, avoids and notes, and every save
replaced them for everybody. They are a per-user kind now, so this file
asks the two questions that makes true -- can A read B's criteria, and
can A's save change B's -- down every surface that touches them, plus
the one-time migration of the old shared file to the admin.

Every client here signs in for real, through POST /login and the signed
cookie, rather than through conftest's `signed_in` patch: the whole
point is which user the request is, so the thing under test has to be
the real session.
"""

import pytest
import yaml

from careeros import server, users, vault

PASSWORD = 'correct horse battery staple'

#: One criteria payload per user, every value recognisable, so a leak is
#: visible whatever shape it takes.
CRITERIA = {
    'admin': {'roles': ['Admin Only Role'], 'must_haves': ['Admin must-have'],
              'nice_to_haves': ['Admin nice-to-have'], 'avoid': ['Admin avoids this'],
              'notes': 'Admin private criteria notes'},
    'one': {'roles': ['Tester One Role'], 'must_haves': ['One must-have'],
            'nice_to_haves': ['One nice-to-have'], 'avoid': ['One avoids this'],
            'notes': 'Tester One private criteria notes'},
    'two': {'roles': ['Tester Two Role'], 'must_haves': ['Two must-have'],
            'nice_to_haves': ['Two nice-to-have'], 'avoid': ['Two avoids this'],
            'notes': 'Tester Two private criteria notes'},
}

#: The shared file a vault written before the split holds. Its values
#: appear nowhere else, so "this reader got the legacy file" is a
#: substring check.
LEGACY = {
    'updated': '2026-01-02',
    'roles': ['Legacy Shared Role'],
    'must_haves': ['Legacy must-have'],
    'nice_to_haves': ['Legacy nice-to-have'],
    'avoid': ['Legacy avoids this'],
    'notes': 'Legacy shared criteria notes',
}


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
def app(root, people, raw_session):
    built = server.create_app(root)
    built.config['TESTING'] = True
    return built


def sign_in(app, user):
    client = app.test_client()
    response = client.post('/login', json={'email': user['email'], 'password': PASSWORD})
    assert response.status_code == 200, response.get_data(as_text=True)
    return client


@pytest.fixture
def clients(app, people):
    """One signed-in client per user, by the same key CRITERIA uses."""
    return {key: sign_in(app, user) for key, user in people.items()}


def body(response):
    return response.get_data(as_text=True)


def legacy_file(root):
    path = root / vault.LEGACY_SEARCH_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(LEGACY, sort_keys=False))
    return path


def stored(root, user):
    """One user's criteria file as bytes, or None if they have none."""
    path = root / vault.SEARCH_DIR / f"{user['id'].lower()}.yaml"
    return path.read_bytes() if path.exists() else None


def saved(client, payload):
    response = client.post('/api/search', json=payload)
    assert response.status_code == 200, body(response)
    return response.get_json()


def values_of(payload):
    """Every recognisable string in one criteria payload."""
    return [item for key, value in payload.items()
            for item in (value if isinstance(value, list) else [value])]


# --- Three users, three sets of criteria ---------------------------------

def test_each_user_reads_only_their_own_criteria(clients, people):
    for key, client in clients.items():
        assert saved(client, CRITERIA[key])[vault.OWNER_FIELD] == people[key]['id']
    for key, client in clients.items():
        read = client.get('/api/search').get_json()
        assert {k: v for k, v in read.items() if k not in ('updated', vault.OWNER_FIELD)} \
            == CRITERIA[key]
        assert read[vault.OWNER_FIELD] == people[key]['id']
        # And nothing of anybody else's, in either GET's whole body.
        for surface in ('/api/search', '/api/search?view=page'):
            text = body(client.get(surface))
            for other, payload in CRITERIA.items():
                for value in values_of(payload):
                    assert (value in text) is (other == key), (surface, value)


def test_the_search_page_holds_only_the_readers_own_criteria(clients, people):
    for key, client in clients.items():
        saved(client, CRITERIA[key])
    for key, client in clients.items():
        page = client.get('/api/search?view=page').get_json()
        assert {k: v for k, v in page['data'].items()
                if k not in ('updated', vault.OWNER_FIELD)} == CRITERIA[key]
        assert page['data'][vault.OWNER_FIELD] == people[key]['id']


def test_a_testers_save_leaves_the_admin_criteria_untouched(clients, people, root):
    before = saved(clients['admin'], CRITERIA['admin'])
    on_disk = stored(root, people['admin'])
    for key in ('one', 'two'):
        saved(clients[key], CRITERIA[key])
    assert stored(root, people['admin']) == on_disk, 'a tester save rewrote the admin file'
    assert clients['admin'].get('/api/search').get_json() == before
    assert vault.load_search(root, users.owner(people['admin'])) == before


def test_a_payload_owner_id_cannot_write_to_another_user(clients, people, root):
    mine = saved(clients['admin'], CRITERIA['admin'])
    on_disk = stored(root, people['admin'])
    theft = saved(clients['one'], CRITERIA['one'] | {vault.OWNER_FIELD: people['admin']['id']})
    assert theft[vault.OWNER_FIELD] == people['one']['id']
    assert stored(root, people['admin']) == on_disk
    assert clients['admin'].get('/api/search').get_json() == mine


# --- A user who has never saved anything --------------------------------

def test_a_brand_new_user_starts_empty(app, root, clients, people):
    for key, client in clients.items():
        saved(client, CRITERIA[key])
    newcomer = users.create_user(root, email='three@example.test', name='Tester Three',
                                 role='tester', password=PASSWORD)
    client = sign_in(app, newcomer)
    assert client.get('/api/search').get_json() is None
    page = client.get('/api/search?view=page').get_json()
    assert page['data'] is None
    assert stored(root, newcomer) is None
    text = body(client.get('/api/search?view=page'))
    for payload in CRITERIA.values():
        for value in values_of(payload):
            assert value not in text


# --- The legacy shared file ---------------------------------------------

def test_the_legacy_shared_file_migrates_to_the_admin_exactly_once(
        clients, people, root):
    path = legacy_file(root)
    original = path.read_bytes()

    # First read copies it, date and all: moving a file is not an edit.
    first = clients['admin'].get('/api/search').get_json()
    assert {k: v for k, v in first.items() if k != vault.OWNER_FIELD} == LEGACY
    assert first[vault.OWNER_FIELD] == people['admin']['id']
    assert stored(root, people['admin']) is not None

    # A second read before any edit is the same answer, not a second copy.
    assert clients['admin'].get('/api/search').get_json() == first
    assert clients['admin'].get('/api/search?view=page').get_json()['data'] == first

    # The admin edits. Every later read is the edit; the legacy file never
    # comes back.
    edited = saved(clients['admin'], CRITERIA['admin'])
    for _ in range(2):
        again = clients['admin'].get('/api/search').get_json()
        assert again == edited
        for value in values_of({k: v for k, v in LEGACY.items() if k != 'updated'}):
            assert value not in body(clients['admin'].get('/api/search?view=page'))

    # And the legacy file itself is untouched by all of it.
    assert path.read_bytes() == original


def test_a_tester_never_reads_the_legacy_shared_file(clients, people, root):
    path = legacy_file(root)
    original = path.read_bytes()
    for key in ('one', 'two'):
        client = clients[key]
        assert client.get('/api/search').get_json() is None
        assert client.get('/api/search?view=page').get_json()['data'] is None
        for surface in ('/api/search', '/api/search?view=page'):
            text = body(client.get(surface))
            for value in values_of({k: v for k, v in LEGACY.items() if k != 'updated'}):
                assert value not in text, (surface, value)
        assert stored(root, people[key]) is None
    assert path.read_bytes() == original


def test_an_admin_who_saved_first_never_gets_the_legacy_file(clients, people, root):
    """The once-rule is "the owner's own record exists", so a save before
    any read closes the migration just as a read does."""
    path = legacy_file(root)
    mine = saved(clients['admin'], CRITERIA['admin'])
    assert clients['admin'].get('/api/search').get_json() == mine
    assert path.read_bytes() == yaml.safe_dump(LEGACY, sort_keys=False).encode()


# --- The vault functions themselves -------------------------------------

def test_criteria_cannot_be_read_or_written_without_an_owner(root, people):
    root.mkdir(parents=True, exist_ok=True)
    for call in (lambda: vault.load_search(root, None),
                 lambda: vault.save_search(root, None, {})):
        with pytest.raises(ValueError):
            call()
    # Nor under an id that is not a record id: the owner names a file here.
    for bad in ('../escape', 'USER-001/../../etc', '', ' '):
        with pytest.raises(ValueError):
            vault.load_search(root, vault.Owner(bad, True))
        with pytest.raises(ValueError):
            vault.save_search(root, vault.Owner(bad, True), {})


def test_two_owners_criteria_are_two_files(root, people):
    root.mkdir(parents=True, exist_ok=True)
    one, two = users.owner(people['one']), users.owner(people['two'])
    vault.save_search(root, one, CRITERIA['one'])
    vault.save_search(root, two, CRITERIA['two'])
    assert vault.load_search(root, one)['roles'] == CRITERIA['one']['roles']
    assert vault.load_search(root, two)['roles'] == CRITERIA['two']['roles']
    assert sorted(p.name for p in (root / vault.SEARCH_DIR).glob('*.yaml')) == [
        f"{people['one']['id'].lower()}.yaml", f"{people['two']['id'].lower()}.yaml"]
