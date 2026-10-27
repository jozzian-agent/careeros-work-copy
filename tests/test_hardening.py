"""The 2026-10-27 privacy audit's hardening findings: 2, 7, 8 and 10.

Four separate holes with one shape in common -- a check that exists but
is reached down only one of the paths that get to the write:

* **2, note authorship.** A note carries the session user who wrote it.
  `create_note` stamps that; the generic record PUT persisted whatever
  `note_list` a client sent, stamps and all, so a tester could write a
  note as somebody else or re-stamp one of their own.
* **7, HEAD as a mutation.** Flask answers HEAD on every rule that
  allows GET by running the handler with `request.method == 'HEAD'`, so
  `if request.method == 'GET': <read>` fell through to the write half.
  A HEAD request with a body could save criteria, update a record, or
  sign in.
* **8, two principals in one request.** The gate validated a user and
  `session_owner` read the record again. A disable or a reset between
  the two made `owner` None, and an unscoped owner is every vault
  reader's "no filter".
* **10, unthrottled sign-in.** The one unauthenticated POST the rate
  limiter did not count.

Every client here signs in for real, through POST /login and the signed
cookie, rather than through conftest's `signed_in` patch: three of the
four findings are about who the request is or how it got in, so the
thing under test has to be the real session. Same multi-user shape as
tests/test_record_privacy.py and tests/test_search_privacy.py -- one
admin and two testers, so "somebody else" is a tester and not only ever
the admin.
"""

import inspect
import time
from datetime import datetime, timezone

import pytest

from careeros import invites, password_reset, ratelimit, server, users, vault
from careeros import tokens as link_tokens

PASSWORD = 'correct horse battery staple'

#: A title per user, so a leak is recognisable in a response body
#: whatever shape the leak takes.
TITLES = {'admin': 'Admin Only Role', 'one': 'Tester One Role', 'two': 'Tester Two Role'}
NOTE_TITLES = {'admin': 'Admin private note', 'one': 'One private note',
               'two': 'Two private note'}

SHARED_COMPANY = 'Shared Universe Holdings'

#: Two addresses the test client is seen from, so the per-IP half of the
#: login limiter is a thing a test can tell apart from the per-email half.
ONE_IP = '203.0.113.9'
OTHER_IP = '198.51.100.4'


@pytest.fixture
def root(tmp_path):
    return tmp_path / 'vault'


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """No limiter tunable from the ambient environment, so every budget
    here is the default or the one the test sets."""
    for name in ('CAREEROS_RATE_LIMIT', 'CAREEROS_RATE_WINDOW',
                 'CAREEROS_LOGIN_RATE_LIMIT', 'CAREEROS_LOGIN_RATE_WINDOW',
                 'CAREEROS_TRUSTED_PROXY'):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def people(root):
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
    """One job per user, each carrying one note of its owner's, and one
    position for tester one. Written straight through the vault, which is
    the only way to set up three users' records without driving three
    intake flows."""
    jobs, positions = {}, {}
    for key, user in people.items():
        jobs[key] = vault.save_job(root, {
            'title': TITLES[key], 'url': f'https://example.test/{key}/posting',
            'company_id': company['id'], 'description': f'Posting text for {key}.',
            'status': 'interested', 'location': 'Zurich',
            vault.OWNER_FIELD: user['id'],
            **vault.notes_payload([vault.new_note(NOTE_TITLES[key], 'Body.',
                                                  author_id=user['id'])]),
        })
    positions['one'] = vault.save_experience(root, {
        'title': 'Tester One Position', 'company': SHARED_COMPANY,
        'company_id': company['id'], 'start': '2020-01', 'end': 'present',
        'tags': ['experience-type:employment'],
        vault.OWNER_FIELD: people['one']['id'],
    })
    return {'jobs': jobs, 'positions': positions}


@pytest.fixture
def app(root, people, raw_session):
    built = server.create_app(root)
    built.config['TESTING'] = True
    return built


def signed_in_client(app, user, ip=ONE_IP):
    client = app.test_client()
    response = client.post('/login', json={'email': user['email'], 'password': PASSWORD},
                           environ_base={'REMOTE_ADDR': ip})
    assert response.status_code == 200, response.get_data(as_text=True)
    return client


@pytest.fixture
def clients(app, people):
    """One signed-in client per user, by the same key the records use."""
    return {key: signed_in_client(app, user) for key, user in people.items()}


def body(response):
    return response.get_data(as_text=True)


def note_titles(root, job_id):
    return [note['title'] for note in vault.load_job(root, job_id)['note_list']]


def forged_note(author_id, title='Forged by a stranger', note_id='forged'):
    """One note list entry that passes `validate_note_list` and carries
    somebody else's author stamp. Every REQUIRED_NOTE_FIELD is here on
    purpose: a payload the validator rejects would prove nothing about
    whether the write path accepts a foreign author."""
    at = '2026-10-27T00:00:00+00:00'
    return {'id': note_id, 'title': title, 'body': 'Written as somebody else.',
            'created': at, 'updated': at, 'author_id': author_id}


# --- Finding 2: a generic record write cannot touch a note ---------------


def test_a_job_put_cannot_write_a_note_stamped_with_another_user(
        clients, records, people, root):
    """The finding itself: a tester PUTs a note list onto their OWN job
    carrying tester two's author id. The stamp is the session's or it is
    nothing, so the write changes no note at all."""
    job = records['jobs']['one']
    response = clients['one'].put(f'/api/jobs/{job["id"]}',
                                  json={'note_list': [forged_note(people['two']['id'])]})
    assert response.status_code == 200, body(response)
    assert note_titles(root, job['id']) == [NOTE_TITLES['one']]
    stored = vault.load_job(root, job['id'])['note_list']
    assert [note['author_id'] for note in stored] == [people['one']['id']]
    # And the response cannot show what the record does not hold.
    assert 'Forged by a stranger' not in body(response)


def test_a_job_put_cannot_restamp_an_existing_note_as_somebody_else(
        clients, records, people, root):
    """The other half of the same hole: keeping the note's id and
    changing only its author would have re-attributed a note in place."""
    job = records['jobs']['one']
    existing = vault.load_job(root, job['id'])['note_list'][0]
    clients['one'].put(f'/api/jobs/{job["id"]}', json={'note_list': [
        {**existing, 'author_id': people['admin']['id'], 'title': 'Re-stamped'}]})
    stored = vault.load_job(root, job['id'])['note_list']
    assert [(note['title'], note['author_id']) for note in stored] == [
        (NOTE_TITLES['one'], people['one']['id'])]


def test_a_job_put_cannot_delete_a_note_through_the_note_list(
        clients, records, root):
    """A note list the generic write accepted could also take notes
    away, which is the same endpoint doing the delete endpoint's job
    without its ownership check."""
    job = records['jobs']['one']
    assert clients['one'].put(f'/api/jobs/{job["id"]}',
                              json={'note_list': []}).status_code == 200
    assert note_titles(root, job['id']) == [NOTE_TITLES['one']]


def test_a_company_put_cannot_write_a_note_stamped_with_another_user(
        clients, records, company, people, root):
    """The same hole on the company record, where several users' notes
    live in one file. This write is the admin's alone, which makes it the
    forgery with the least reach and the most readers: the admin may
    change a company, not author a note as one of its other readers."""
    notes = [vault.new_note(NOTE_TITLES['one'], 'Body.', author_id=people['one']['id'])]
    vault.save_company(root, vault.notes_payload(notes), company['id'])
    response = clients['admin'].put(f'/api/companies/{company["id"]}',
                                    json={'note_list': [forged_note(people['two']['id'])]})
    assert response.status_code == 200, body(response)
    stored = vault.load_company(root, company['id'])['note_list']
    assert [(note['title'], note['author_id']) for note in stored] == [
        (NOTE_TITLES['one'], people['one']['id'])]


def test_the_note_endpoint_still_stamps_the_session_author(clients, records, people, root):
    """The other side of the rule: taking notes out of the generic write
    must not take away the one path that writes them."""
    job = records['jobs']['one']
    created = clients['one'].post(f'/api/jobs/{job["id"]}/notes',
                                  json={'title': 'Through the endpoint', 'body': 'x'})
    assert created.status_code == 201, body(created)
    assert created.get_json()['author_id'] == people['one']['id']
    assert note_titles(root, job['id']) == [NOTE_TITLES['one'], 'Through the endpoint']


def test_an_ordinary_job_edit_still_saves(clients, records, root):
    """And the generic write still writes everything that is not a note,
    including the legacy free-text field, which carries no author."""
    job = records['jobs']['one']
    response = clients['one'].put(f'/api/jobs/{job["id"]}',
                                  json={'title': 'Renamed by its owner', 'notes': 'Legacy text'})
    assert response.status_code == 200, body(response)
    stored = vault.load_job(root, job['id'])
    assert stored['title'] == 'Renamed by its owner'
    assert stored['notes'] == 'Legacy text'


# --- Finding 7: HEAD is a read, on every route ---------------------------

#: The methods that change something. A rule that allows one of these
#: AND answers HEAD is a rule where Flask's automatic HEAD runs a
#: handler that has a write in it.
MUTATING_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})

#: Every such rule in the app, swept out of the url_map below rather
#: than listed from the audit report, and pinned here so a route added
#: later has to be looked at. The react_* rules are absent because they
#: are GET-only; /logout and the per-record action POSTs are absent
#: because they allow no GET and so answer no HEAD.
ENDPOINTS_ANSWERING_HEAD_AND_A_MUTATION = [
    'accept_invite', 'company_api', 'experience_api', 'experience_collection',
    'forgot_password', 'job_api', 'login', 'reset_password', 'search_api',
]


def dual_method_rules(app):
    return sorted({rule.endpoint for rule in app.url_map.iter_rules()
                   if 'HEAD' in (rule.methods or set())
                   and (rule.methods or set()) & MUTATING_METHODS})


def test_the_routes_that_answer_head_and_a_mutation_are_the_known_set(app):
    assert dual_method_rules(app) == ENDPOINTS_ANSWERING_HEAD_AND_A_MUTATION


def test_no_route_that_answers_head_branches_on_a_method_equality_check(app):
    """The structural half of the fix, so a route added later cannot
    reintroduce the hole quietly.

    `request.method == 'GET'` is false for HEAD and falls through to the
    write; `request.method == 'DELETE'` is merely harmless today. Both
    are banned in favour of `reading()` and `in` membership on an
    explicit set, because the shape is what made the bug invisible.
    """
    offenders = {endpoint: inspect.getsource(app.view_functions[endpoint])
                 for endpoint in dual_method_rules(app)}
    assert [endpoint for endpoint, source in offenders.items()
            if 'request.method ==' in source] == []


def test_reading_is_true_for_head_and_false_for_every_write(app):
    for method in ('GET', 'HEAD'):
        with app.test_request_context('/api/search', method=method):
            assert server.reading() is True
    for method in sorted(MUTATING_METHODS):
        with app.test_request_context('/api/search', method=method):
            assert server.reading() is False


def test_head_does_not_save_search_criteria(clients, records, people, root):
    saved = clients['one'].post('/api/search', json={'roles': ['Mine']})
    assert saved.status_code == 200, body(saved)
    assert clients['one'].head('/api/search',
                               json={'roles': ['Replaced by HEAD']}).status_code == 200
    assert vault.load_search(root, users.owner(people['one']))['roles'] == ['Mine']


def test_head_does_not_update_a_job(clients, records, root):
    job = records['jobs']['one']
    assert clients['one'].head(f'/api/jobs/{job["id"]}',
                               json={'title': 'Renamed by HEAD'}).status_code == 200
    assert vault.load_job(root, job['id'])['title'] == TITLES['one']


def test_head_does_not_update_a_company(clients, company, records, root):
    assert clients['admin'].head(f'/api/companies/{company["id"]}',
                                 json={'name': 'Renamed by HEAD'}).status_code == 200
    assert vault.load_company(root, company['id'])['name'] == SHARED_COMPANY


def test_head_does_not_create_an_experience(clients, records, root):
    assert clients['one'].head('/api/experiences', json={
        'title': 'Created by HEAD', 'company': SHARED_COMPANY,
        'start': '2021-01', 'end': 'present'}).status_code == 200
    assert [exp['title'] for exp in vault.list_experiences(root)] == ['Tester One Position']


def test_head_does_not_update_an_experience(clients, records, root):
    position = records['positions']['one']
    assert clients['one'].head(f'/api/experiences/{position["id"]}',
                               json={'title': 'Renamed by HEAD'}).status_code == 200
    assert vault.load_experience(root, position['id'])['title'] == 'Tester One Position'


def test_head_on_the_login_page_does_not_sign_anybody_in(app, people, records):
    """The one that matters most: HEAD is a method no browser form can
    send and every crawler does. Running the POST half of this handler
    authenticated the request and set the session cookie."""
    client = app.test_client()
    response = client.head('/login', data={'email': people['one']['email'],
                                           'password': PASSWORD})
    assert client.get('/api/jobs').status_code == 401, 'HEAD /login created a session'
    assert response.status_code == 200
    assert 'Set-Cookie' not in response.headers


def test_head_on_the_invite_page_does_not_create_an_account(app, root, people):
    _, token = invites.create_invite(root, 'invitee@example.test', 'Invitee')
    client = app.test_client()
    assert client.head(f'/accept-invite/{token}',
                       data={'name': 'Invitee', 'password': PASSWORD}).status_code == 200
    assert users.find_by_email(root, 'invitee@example.test') is None
    # And the link is unspent, so the real POST still works afterwards.
    assert link_tokens.state(invites.load(root, token)) is link_tokens.TOKEN_LIVE


def test_head_on_the_reset_page_does_not_change_a_password(app, root, people):
    token = live_reset_token(root, people['one'])
    client = app.test_client()
    assert client.head(f'/reset-password/{token}',
                       data={'password': 'a brand new passphrase'}).status_code == 200
    assert users.authenticate(root, people['one']['email'], PASSWORD) is not None
    assert users.authenticate(root, people['one']['email'], 'a brand new passphrase') is None
    assert link_tokens.state(password_reset.load(root, token)) is link_tokens.TOKEN_LIVE


def test_head_on_the_forgot_password_page_mints_no_reset(app, root, people):
    client = app.test_client()
    assert client.head('/forgot-password',
                       data={'email': people['one']['email']}).status_code == 200
    assert not list((root / password_reset.FOLDER).glob('*.yaml'))


def live_reset_token(root, user):
    """One live reset record, written exactly the way `request_reset`
    writes it. Built here rather than through the request page because
    the raw token only ever leaves that path in an email, and no test
    here goes near SMTP."""
    token = link_tokens.new_token()
    now = datetime.now(timezone.utc)
    vault._write(link_tokens.storage_path(root, password_reset.FOLDER, token), {
        'user_id': user['id'], 'email': user['email'],
        'token_hash': link_tokens.token_hash(token),
        'created_at': now.isoformat(),
        'expires_at': (now + password_reset.EXPIRY).isoformat(),
    })
    return token


# --- Finding 8: one principal per request -------------------------------


def fading_session(first):
    """A reader of the signed-in user that answers once and then stops
    -- the account disabled, or its sessions ended by a reset, between
    the gate's reading and the next one. Returns (callable, calls)."""
    calls = []

    def read(root):
        calls.append(1)
        return first(root) if len(calls) == 1 else None

    return read, calls


def test_a_session_that_fades_after_the_gate_does_not_widen_the_read(
        app, clients, records, root):
    """The race in the finding. The gate let this request in, the second
    reading of the user answered None, and `owner=None` is every vault
    reader's "unscoped": the response held all three users' jobs."""
    faded, calls = fading_session(users.session_user)
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(users, 'session_user', faded)
        response = clients['one'].get('/api/jobs')
    text = body(response)
    for key, title in TITLES.items():
        assert (title in text) is (key == 'one'), f'{title} in a read scoped to tester one'
    assert len(calls) == 1, 'the user record was read more than once in one request'


def test_the_user_record_is_read_once_per_request(app, clients, records):
    """The rule behind the fix, stated on its own: one request, one
    principal. Two readings are two answers, and that is the race."""
    calls = []
    real = users.session_user

    def counting(root):
        calls.append(1)
        return real(root)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(users, 'session_user', counting)
        assert clients['one'].get('/api/jobs').status_code == 200
    assert len(calls) == 1


def test_a_principal_lost_after_the_gate_is_refused_not_read_as_unscoped(
        app, clients, records, people):
    """Fail closed. If identity goes missing between the gate and the
    ownership scope anyway, the request ends in the same 401 a request
    with no session gets -- never in a read with no filter."""
    faded, _ = fading_session(lambda root: people['one'])
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(users, 'request_user', faded)
        response = clients['one'].get('/api/jobs')
    assert response.status_code == 401
    assert response.get_json() == {'error': users.LOGIN_REQUIRED}
    for title in TITLES.values():
        assert title not in body(response)


def test_the_ownership_scope_refuses_to_be_built_without_a_principal(app, root):
    """The contract the consumers rely on: no principal raises, so no
    caller can accidentally pass None on to a vault reader."""
    with app.test_request_context('/api/jobs'):
        with pytest.raises(users.IdentityUnresolved):
            users.request_owner(root)
        with pytest.raises(users.IdentityUnresolved):
            users.request_principal(root)
        assert users.request_user(root) is None


def test_a_page_route_also_refuses_rather_than_reading_unscoped(
        app, clients, records, people):
    """The Jinja pages resolved their own owner too, with the same
    second reading and the same unscoped fallback."""
    faded, _ = fading_session(lambda root: people['one'])
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(users, 'request_user', faded)
        response = clients['one'].get('/jobs')
    assert response.status_code == 401
    for title in TITLES.values():
        assert title not in body(response)


# --- Finding 10: the login form is rate limited --------------------------


def login(client, email, password=PASSWORD, ip=ONE_IP):
    return client.post('/login', json={'email': email, 'password': password},
                       environ_base={'REMOTE_ADDR': ip})


def test_guessing_a_password_is_refused_past_the_limit(app, people, monkeypatch):
    monkeypatch.setenv('CAREEROS_LOGIN_RATE_LIMIT', '3')
    client = app.test_client()
    email = people['one']['email']
    attempts = [login(client, email, 'wrong').status_code for _ in range(4)]
    assert attempts == [401, 401, 401, 429]
    # The budget is spent for the window, so the right password does not
    # buy a way around the limit either.
    refused = login(client, email)
    assert refused.status_code == 429
    assert refused.get_json() == {'error': server.RATE_LIMITED_MESSAGE}
    assert client.get('/api/jobs').status_code == 401


def test_the_limit_is_counted_per_ip_as_well_as_per_address(app, people, monkeypatch):
    """Rotating the address but not the IP buys nothing: both keys are
    counted and a request is refused as soon as either is spent."""
    monkeypatch.setenv('CAREEROS_LOGIN_RATE_LIMIT', '2')
    client = app.test_client()
    for index in range(2):
        assert login(client, f'stranger{index}@example.test', 'wrong').status_code == 401
    assert login(client, 'stranger9@example.test', 'wrong').status_code == 429
    # The real account, same IP, correct password: the IP's budget is
    # spent, so this is refused too.
    assert login(client, people['one']['email']).status_code == 429


def test_a_spent_address_does_not_block_another_account_from_elsewhere(
        app, people, monkeypatch):
    monkeypatch.setenv('CAREEROS_LOGIN_RATE_LIMIT', '2')
    client = app.test_client()
    for _ in range(3):
        login(client, people['one']['email'], 'wrong')
    assert login(client, people['one']['email']).status_code == 429
    other = app.test_client()
    assert login(other, people['two']['email'], ip=OTHER_IP).status_code == 200


def test_signing_in_successfully_spends_no_budget(app, people, monkeypatch):
    """A person on a third device has not guessed anything. Only the
    failures are counted, so the limiter cannot lock out the account it
    is there to protect."""
    monkeypatch.setenv('CAREEROS_LOGIN_RATE_LIMIT', '2')
    email = people['one']['email']
    for _ in range(4):
        assert login(app.test_client(), email).status_code == 200


def test_the_login_window_ends_so_nobody_is_locked_out_for_good(
        app, people, monkeypatch):
    monkeypatch.setenv('CAREEROS_LOGIN_RATE_LIMIT', '1')
    monkeypatch.setenv('CAREEROS_LOGIN_RATE_WINDOW', '1')
    client = app.test_client()
    email = people['one']['email']
    assert login(client, email, 'wrong').status_code == 401
    assert login(client, email, 'wrong').status_code == 429
    # The window is a second long, so the counter is stale by now and
    # dropped on the next read.
    time.sleep(1.2)
    assert login(client, email).status_code == 200


def test_the_login_budget_is_its_own_and_lives_in_the_shared_vault_file(
        app, root, people, monkeypatch):
    """Vault-backed, so the two gunicorn workers share one budget rather
    than an attacker alternating between them for double; and scoped, so
    wrong passwords cannot spend the budget of the reset request that
    fixes them."""
    monkeypatch.setenv('CAREEROS_LOGIN_RATE_LIMIT', '1')
    client = app.test_client()
    login(client, people['one']['email'], 'wrong')
    windows = (vault._read(root / ratelimit.STATE_FILE) or {})['windows']
    assert set(windows) == {
        ratelimit.email_key(people['one']['email'], ratelimit.LOGIN_SCOPE),
        ratelimit.ip_key(ONE_IP, ratelimit.LOGIN_SCOPE)}
    # The mailed-link keys are untouched, so that page's own budget --
    # and the limit it reads -- are whole.
    assert ratelimit.allowed(root, email=people['one']['email'], ip=ONE_IP) is True


def test_a_refused_sign_in_says_the_same_thing_whatever_was_wrong(app, people):
    """The generic failure the finding asks to keep: an unknown address
    and a wrong password are one answer, so the form cannot be used to
    find out who has an account. The limiter's own refusal is allowed to
    be a 429 -- it says nothing about the account either."""
    client = app.test_client()
    unknown = login(client, 'nobody@example.test', 'wrong')
    wrong = login(client, people['one']['email'], 'wrong')
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.get_json() == wrong.get_json() == {'error': users.SIGN_IN_FAILED}
    assert people['one']['email'] not in server.RATE_LIMITED_MESSAGE
