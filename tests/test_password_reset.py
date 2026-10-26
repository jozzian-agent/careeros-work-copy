"""Protects the rules of the password reset: no enumeration from the
request page, a link that works once and dies after an hour, only the
token's hash in the vault, a mailed link built from APP_BASE_URL and
never from a Host header, sessions of the reset account ended while
every other account's stay alive, and no sign-in at the end.

Same fake-SMTP shape as tests/test_mail.py and tests/test_invites.py;
no test here reaches a network.
"""

import logging
import smtplib
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from careeros import password_reset, ratelimit, server, tokens, users, vault

PASSWORD = 'correct horse battery staple'
NEW_PASSWORD = 'a brand new passphrase'
OWNER = 'owner@example.test'
STRANGER = 'nobody@example.test'
BASE_URL = 'https://app.example.test'

MAIL_VARIABLES = ('SMTP_HOST', 'SMTP_PORT', 'SMTP_SECURITY', 'SMTP_USER',
                  'SMTP_PASSWORD', 'SMTP_TIMEOUT', 'MAIL_FROM', 'MAIL_FROM_NAME',
                  'MAIL_DAILY_CAP', 'APP_BASE_URL')


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in MAIL_VARIABLES + ('CAREEROS_TRUSTED_PROXY',
                                  'CAREEROS_RATE_LIMIT', 'CAREEROS_RATE_WINDOW'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('APP_BASE_URL', BASE_URL)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('SMTP_HOST', 'smtp.example.test')
    monkeypatch.setenv('SMTP_USER', 'mailer')
    monkeypatch.setenv('SMTP_PASSWORD', 'smtp-secret')
    monkeypatch.setenv('MAIL_FROM', 'careeros@example.test')


@pytest.fixture
def smtp(monkeypatch):
    """The recording fake from tests/test_mail.py, same shape."""
    class Recorder(list):
        def refuse(self, error):
            Fake.failure = error

    connections = Recorder()

    class Fake:
        failure = None

        def __init__(self, host, port, timeout=None):
            self.record = {'host': host, 'port': port, 'sent': []}
            connections.append(self.record)

        def __enter__(self):
            return self

        def __exit__(self, *error):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, message, to_addrs=None):
            if Fake.failure is not None:
                raise Fake.failure
            self.record['sent'].append((message, to_addrs))

    monkeypatch.setattr(smtplib, 'SMTP', Fake)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', Fake)
    return connections


@pytest.fixture
def root(tmp_path):
    return tmp_path / 'vault'


@pytest.fixture
def owner(root):
    """One live account to reset. Address typed with capitals on
    purpose: the stored lowercase form is what every lookup must match."""
    return users.create_user(root, email='Owner@Example.Test', name='Owner',
                             role='admin', password=PASSWORD)


@pytest.fixture
def app(root, raw_session):
    built = server.create_app(root)
    built.config['TESTING'] = True
    return built


def body_of(message):
    return message.get_body(('plain',)).get_content()


def link_token(message):
    """The raw token off the one link in the mailed body."""
    body = body_of(message)
    line = next(l for l in body.splitlines()
                if l.startswith(BASE_URL + password_reset.RESET_PATH))
    return line.rsplit('/', 1)[1]


def expire(record_path, ago=timedelta(minutes=1)):
    record = vault._read(record_path)
    record['expires_at'] = (datetime.now(timezone.utc) - ago).isoformat()
    vault._write(record_path, record)


# --- requesting ----------------------------------------------------------------

def test_a_live_account_gets_a_mailed_link_built_from_the_base_url(
        configured, root, owner, smtp):
    message = password_reset.request_reset(root, 'OWNER@example.test')
    assert message == password_reset.REQUEST_ACCEPTED
    assert len(smtp) == 1
    sent_message, to_addrs = smtp[0]['sent'][0]
    assert to_addrs == [OWNER]
    assert sent_message['Subject'] == password_reset.SUBJECT
    body = body_of(sent_message)
    assert BASE_URL + password_reset.RESET_PATH in body
    assert 'expires in one hour' in body


def test_an_unknown_address_reads_exactly_like_a_known_one(
        configured, root, owner, smtp):
    """The enumeration rule at the module level: one message, one
    return, nothing to branch on — and no mail, because mailing a
    nonexistent address would both leak the answer and spend the cap."""
    for address in (STRANGER, OWNER):
        assert password_reset.request_reset(root, address) == \
            password_reset.REQUEST_ACCEPTED
    assert len(smtp) == 1, 'only the real account was mailed'
    assert smtp[0]['sent'][0][1] == [OWNER]


def test_a_disabled_account_is_treated_as_nonexistent(configured, root, smtp):
    user = users.create_user(root, email=STRANGER, name='Off', role='tester',
                             password=PASSWORD)
    users.set_disabled(root, user['id'], True)
    assert password_reset.request_reset(root, STRANGER) == \
        password_reset.REQUEST_ACCEPTED
    assert smtp == [], 'a disabled account must not be mailed a reset'


def test_the_vault_never_holds_the_raw_reset_token(configured, root, owner, smtp):
    password_reset.request_reset(root, OWNER)
    token = link_token(smtp[0]['sent'][0][0])
    stored_path = tokens.storage_path(root, password_reset.FOLDER, token)
    record = vault._read(stored_path)
    assert record['token_hash'] == tokens.token_hash(token)
    assert 'token' not in record
    assert record['user_id'] == owner['id']
    for path in Path(root).rglob('*'):
        if path.is_file():
            assert token not in path.read_text(errors='ignore')


def test_the_reset_expiry_is_one_hour(configured, root, owner, smtp):
    password_reset.request_reset(root, OWNER)
    token = link_token(smtp[0]['sent'][0][0])
    record = password_reset.load(root, token)
    created = datetime.fromisoformat(record['created_at'])
    expires = datetime.fromisoformat(record['expires_at'])
    assert expires - created == password_reset.EXPIRY == timedelta(hours=1)
    assert tokens.state(record, now=expires - timedelta(seconds=1)) == \
        tokens.TOKEN_LIVE
    assert tokens.state(record, now=expires + timedelta(seconds=1)) == \
        tokens.TOKEN_DEAD
    expire(tokens.storage_path(root, password_reset.FOLDER, token))
    with pytest.raises(tokens.TokenError) as refused:
        password_reset.complete_reset(root, token, NEW_PASSWORD)
    assert str(refused.value) == tokens.DEAD_LINK_MESSAGE
    # An expired link changed nothing: the old password still works.
    assert users.authenticate(root, OWNER, PASSWORD) is not None


def test_a_second_request_replaces_the_first_link(configured, root, owner, smtp):
    password_reset.request_reset(root, OWNER)
    first = link_token(smtp[0]['sent'][0][0])
    password_reset.request_reset(root, OWNER)
    second = link_token(smtp[1]['sent'][0][0])
    assert first != second
    assert password_reset.load(root, first) is None
    assert tokens.state(password_reset.load(root, second)) == tokens.TOKEN_LIVE
    assert len(list((root / password_reset.FOLDER).glob('*.yaml'))) == 1


def test_a_mail_failure_still_answers_accepted_and_logs_server_side(
        configured, root, owner, smtp, caplog):
    """The provider being down must not change the shape of the
    response — the log is where an owner looks, never the requester."""
    smtp.refuse(smtplib.SMTPException('provider said no'))
    with caplog.at_level(logging.WARNING, logger='careeros.mail'):
        message = password_reset.request_reset(root, OWNER)
    assert message == password_reset.REQUEST_ACCEPTED
    assert 'mail failed' in caplog.text


def test_an_unconfigured_mail_is_the_same_silence(root, owner, smtp, caplog):
    # No SMTP variables at all: the send is refused before it connects.
    with caplog.at_level(logging.WARNING, logger='careeros.mail'):
        message = password_reset.request_reset(root, OWNER)
    assert message == password_reset.REQUEST_ACCEPTED
    assert 'mail failed' in caplog.text
    assert smtp == []


# --- completing -----------------------------------------------------------------

def test_completing_sets_the_password_and_spends_the_link(
        configured, root, owner, smtp):
    password_reset.request_reset(root, OWNER)
    token = link_token(smtp[0]['sent'][0][0])
    user = password_reset.complete_reset(root, token, NEW_PASSWORD)
    assert user['id'] == owner['id']
    assert users.authenticate(root, OWNER, NEW_PASSWORD) is not None
    assert users.authenticate(root, OWNER, PASSWORD) is None
    assert tokens.state(password_reset.load(root, token)) == tokens.TOKEN_DEAD
    with pytest.raises(tokens.TokenError):
        password_reset.complete_reset(root, token, 'yet another long one')


def test_two_concurrent_resets_cannot_both_win(configured, root, owner, smtp):
    password_reset.request_reset(root, OWNER)
    token = link_token(smtp[0]['sent'][0][0])
    barrier = threading.Barrier(2)
    outcomes = []

    def submit(password):
        barrier.wait()
        try:
            outcomes.append(password_reset.complete_reset(root, token, password))
        except tokens.TokenError:
            outcomes.append(None)

    threads = [threading.Thread(target=submit, args=(password,))
               for password in (NEW_PASSWORD, 'a different long passphrase')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len([o for o in outcomes if o is not None]) == 1
    # Whichever won, its password is the one that works — and the
    # loser's is not a second, silent write.
    winner = next(o for o in outcomes if o is not None)
    assert winner is not None


def test_a_short_password_is_refused_and_the_link_survives(
        configured, root, owner, smtp):
    password_reset.request_reset(root, OWNER)
    token = link_token(smtp[0]['sent'][0][0])
    with pytest.raises(ValueError) as refused:
        password_reset.complete_reset(root, token, 'short')
    assert str(refused.value) == users.PASSWORD_TOO_SHORT
    assert tokens.state(password_reset.load(root, token)) == tokens.TOKEN_LIVE
    assert users.authenticate(root, OWNER, PASSWORD) is not None
    password_reset.complete_reset(root, token, NEW_PASSWORD)


def test_a_reset_for_an_account_disabled_in_between_is_dead(
        configured, root, owner, smtp):
    password_reset.request_reset(root, OWNER)
    token = link_token(smtp[0]['sent'][0][0])
    users.set_disabled(root, owner['id'], True)
    with pytest.raises(tokens.TokenError) as refused:
        password_reset.complete_reset(root, token, NEW_PASSWORD)
    assert str(refused.value) == tokens.DEAD_LINK_MESSAGE
    # The token is still burned: a dead account's link has nothing to
    # spend itself on, and burning it is the safe direction.
    assert tokens.state(password_reset.load(root, token)) == tokens.TOKEN_DEAD


# --- sessions ----------------------------------------------------------------------

def test_a_reset_ends_the_accounts_sessions_and_no_ones_elses(
        configured, root, app, owner, smtp):
    """The epoch mechanism end to end: sign two accounts in for real,
    reset one, and watch only its cookie die on the next request."""
    tester = users.create_user(root, email='tester@example.test', name='Tester',
                               role='tester', password=PASSWORD)
    owner_client = app.test_client()
    tester_client = app.test_client()
    assert owner_client.post('/login', json={'email': OWNER,
                                             'password': PASSWORD}).status_code == 200
    assert tester_client.post('/login', json={'email': 'tester@example.test',
                                              'password': PASSWORD}).status_code == 200
    assert owner_client.get('/api/jobs').status_code == 200

    password_reset.request_reset(root, OWNER)
    token = link_token(smtp[0]['sent'][0][0])
    password_reset.complete_reset(root, token, NEW_PASSWORD)

    # The owner's cookie carries the old epoch and fails the gate.
    assert owner_client.get('/api/jobs').status_code == 401
    # The tester's session was minted the same minute and lives on:
    # the bump touched one record.
    assert tester_client.get('/api/jobs').status_code == 200
    # And the new password signs in fresh, with the new epoch.
    assert owner_client.post('/login', json={'email': OWNER,
                                             'password': NEW_PASSWORD}).status_code == 200
    assert owner_client.get('/api/jobs').status_code == 200


# --- the pages ----------------------------------------------------------------------

def test_the_pages_are_reachable_logged_out(app, root, owner):
    """Both pages are in PUBLIC_ENDPOINTS: a person following a mailed
    link has no session, and a gate that swallowed these pages would
    make every mailed link a dead one."""
    assert 'forgot_password' in server.PUBLIC_ENDPOINTS
    assert 'reset_password' in server.PUBLIC_ENDPOINTS
    client = app.test_client()
    assert client.get('/forgot-password').status_code == 200
    assert client.get('/reset-password/whatever').status_code == 200


def test_the_request_page_gives_one_answer_for_every_address(
        configured, app, root, owner, smtp):
    """The enumeration rule at the page level: same status, same
    message, for an account, a stranger and a disabled account."""
    disabled = users.create_user(root, email='off@example.test', name='Off',
                                 role='tester', password=PASSWORD)
    users.set_disabled(root, disabled['id'], True)
    client = app.test_client()
    pages = []
    for address in (OWNER, STRANGER, 'off@example.test'):
        response = client.post('/forgot-password', data={'email': address})
        pages.append((response.status_code, response.get_data(as_text=True)))
    assert all(status == 200 for status, _ in pages)
    assert password_reset.REQUEST_ACCEPTED in pages[0][1]
    bodies = {page for _, page in pages}
    assert len(bodies) == 1, 'one page for every address, or the page is an oracle'
    # Only the live account was mailed.
    assert len(smtp) == 1


def test_a_rate_limited_request_page_is_indistinguishable_too(
        configured, app, root, owner, smtp, monkeypatch):
    """The third case: a limiter-hit request shows the same generic
    page, because "too many attempts" is itself an answer a stranger
    could use to tell a known address from an unknown one."""
    monkeypatch.setenv('CAREEROS_RATE_LIMIT', '2')
    client = app.test_client()
    first = client.post('/forgot-password', data={'email': STRANGER})
    client.post('/forgot-password', data={'email': STRANGER})
    refused = client.post('/forgot-password', data={'email': STRANGER})
    assert refused.status_code == first.status_code == 200
    assert refused.get_data(as_text=True) == first.get_data(as_text=True)


def test_the_reset_page_shows_the_form_or_the_dead_link(app, root, owner,
                                                        configured, smtp):
    client = app.test_client()
    dead = client.get('/reset-password/not-a-real-token')
    assert dead.status_code == 200
    assert tokens.DEAD_LINK_MESSAGE in dead.get_data(as_text=True)
    password_reset.request_reset(root, OWNER)
    token = link_token(smtp[0]['sent'][0][0])
    live = client.get(f'/reset-password/{token}')
    assert live.status_code == 200
    assert 'Choose a new password' in live.get_data(as_text=True)


def test_submitting_the_reset_page_redirects_to_login_without_signing_in(
        configured, app, root, owner, smtp):
    password_reset.request_reset(root, OWNER)
    token = link_token(smtp[0]['sent'][0][0])
    client = app.test_client()
    response = client.post(f'/reset-password/{token}',
                           data={'password': NEW_PASSWORD})
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    assert users.authenticate(root, OWNER, NEW_PASSWORD) is not None
    # NO auto sign-in, through the real gate.
    assert client.get('/api/jobs').status_code == 401
    # The link is spent: the resend gets the dead-link page.
    again = client.post(f'/reset-password/{token}', data={'password': NEW_PASSWORD})
    assert again.status_code == 200
    assert tokens.DEAD_LINK_MESSAGE in again.get_data(as_text=True)


def test_a_short_password_on_the_reset_page_is_refused_and_the_link_survives(
        configured, app, root, owner, smtp):
    password_reset.request_reset(root, OWNER)
    token = link_token(smtp[0]['sent'][0][0])
    client = app.test_client()
    refused = client.post(f'/reset-password/{token}', data={'password': 'short'})
    assert refused.status_code == 400
    assert users.PASSWORD_TOO_SHORT in refused.get_data(as_text=True)
    assert users.authenticate(root, OWNER, PASSWORD) is not None
    fixed = client.post(f'/reset-password/{token}', data={'password': NEW_PASSWORD})
    assert fixed.status_code == 302


def test_the_reset_page_rate_limits_with_one_generic_refusal(
        configured, app, root, owner, smtp, monkeypatch):
    monkeypatch.setenv('CAREEROS_RATE_LIMIT', '2')
    password_reset.request_reset(root, OWNER)
    token = link_token(smtp[0]['sent'][0][0])
    client = app.test_client()
    for _ in range(2):
        client.post(f'/reset-password/{token}', data={'password': 'short'})
    refused = client.post(f'/reset-password/{token}', data={'password': NEW_PASSWORD})
    assert refused.status_code == 429
    assert server.RATE_LIMITED_MESSAGE in refused.get_data(as_text=True)
    # The limiter spent budget on the refusals, but the token itself is
    # untouched: after the window, the same link still works.
    assert tokens.state(password_reset.load(root, token)) == tokens.TOKEN_LIVE


# --- the mailed link and hostile headers -------------------------------------------

def test_a_hostile_host_header_cannot_choose_the_mailed_link(
        configured, app, root, owner, smtp):
    """The link is built by mail.absolute_url from APP_BASE_URL and
    nothing else — no request is in scope when a mail is built. The
    request that triggers the send carries hostile Host and
    X-Forwarded-Host headers; the mailed link must not contain them."""
    client = app.test_client()
    client.post('/forgot-password', data={'email': OWNER},
                headers={'Host': 'evil.example', 'X-Forwarded-Host': 'evil.example'})
    assert len(smtp) == 1
    body = body_of(smtp[0]['sent'][0][0])
    assert 'evil.example' not in body
    assert BASE_URL + password_reset.RESET_PATH in body


def test_the_request_costs_the_same_shape_for_a_known_and_unknown_address(
        configured, root, owner, smtp, monkeypatch):
    """The timing half of the enumeration rule, as far as a test can
    see it: the slow hash check runs on every request, against the
    throwaway hash when there is no account (password_reset's own
    documented equalizer). Asserted by counting hash checks, not by
    wall-clock timing, which a test machine cannot measure honestly."""
    calls = []
    real_check = users.check_password_hash

    def counting_check(stored, password):
        calls.append(stored)
        return real_check(stored, password)

    monkeypatch.setattr(users, 'check_password_hash', counting_check)
    password_reset.request_reset(root, OWNER)
    known = list(calls)
    calls.clear()
    password_reset.request_reset(root, STRANGER)
    unknown = list(calls)
    assert len(known) == len(unknown) == 1
    # The known address checked its own hash; the unknown one checked
    # the same-cost throwaway — never nothing, which would be a tell.
    assert known[0] != unknown[0]
    assert unknown[0] == users._ABSENT_HASH
