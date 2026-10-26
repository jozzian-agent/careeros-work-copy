"""Protects the rules of the invite feature: an invite is created from
the command line only, always for the default (never admin) role, the
mailed link works once and dies after seven days, the vault stores only
the token's hash, a mail failure is a visible non-zero exit, and the
accept page is reachable without a session and rate-limited with one
generic refusal.

No real network: `smtplib.SMTP`/`SMTP_SSL` are replaced by the same
recording fake tests/test_mail.py uses, and conftest's offline guard
blocks everything else.
"""

import logging
import smtplib
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from careeros import invites, mail, ratelimit, server, tokens, users, vault

PASSWORD = 'correct horse battery staple'
INVITEE = 'friend@example.test'
BASE_URL = 'https://app.example.test'

#: Every variable the mail module reads, cleared before each test so no
#: ambient SMTP configuration on this machine can change an outcome.
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
    """The least an environment needs to send."""
    monkeypatch.setenv('SMTP_HOST', 'smtp.example.test')
    monkeypatch.setenv('SMTP_USER', 'mailer')
    monkeypatch.setenv('SMTP_PASSWORD', 'smtp-secret')
    monkeypatch.setenv('MAIL_FROM', 'careeros@example.test')


@pytest.fixture
def smtp(monkeypatch):
    """Records what the module did instead of connecting anywhere
    (the tests/test_mail.py fake, same shape)."""
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
    """An explicit vault root: nothing here may reach the default vault."""
    return tmp_path / 'vault'


@pytest.fixture
def app(root, raw_session):
    """An app with the real gate over the test vault."""
    built = server.create_app(root)
    built.config['TESTING'] = True
    return built


def body_of(message):
    return message.get_body(('plain',)).get_content()


def expire(record_path, ago=timedelta(minutes=1)):
    """Rewrite one stored record so its window closed in the past —
    time manipulation without a time machine."""
    record = vault._read(record_path)
    record['expires_at'] = (datetime.now(timezone.utc) - ago).isoformat()
    vault._write(record_path, record)


# --- the command line -------------------------------------------------------

def test_the_cli_stores_the_invite_and_mails_the_link(configured, root, smtp, capsys):
    invites.main(['--vault', str(root), '--email', INVITEE, '--name', 'Friend'])
    assert len(smtp) == 1
    message, to_addrs = smtp[0]['sent'][0]
    assert to_addrs == [INVITEE]
    assert message['Subject'] == invites.SUBJECT
    body = body_of(message)
    assert BASE_URL + invites.ACCEPT_PATH in body
    assert 'expires in 7 days' in body
    out = capsys.readouterr().out
    assert f'Invited {INVITEE}' in out and 'works once' in out


def test_an_address_with_an_account_is_refused_and_nothing_is_invited(
        configured, root, smtp):
    users.create_user(root, email=INVITEE, name='Exists', role='tester',
                      password=PASSWORD)
    with pytest.raises(SystemExit) as refused:
        invites.main(['--vault', str(root), '--email', INVITEE])
    assert 'already exists' in str(refused.value)
    assert smtp == [], 'a refused invite must not touch the network'
    assert not (root / invites.FOLDER).exists() or \
        list((root / invites.FOLDER).glob('*.yaml')) == []


def test_a_second_invite_replaces_the_first_so_the_old_link_dies(
        configured, root, smtp):
    _, first = invites.create_invite(root, INVITEE)
    _, second = invites.create_invite(root, INVITEE)
    assert first != second
    # The old record was deleted, not merely shadowed: its token finds
    # nothing, which reads as the one dead-link answer.
    assert invites.load(root, first) is None
    assert tokens.state(invites.load(root, second)) == tokens.TOKEN_LIVE
    live = list((root / invites.FOLDER).glob('*.yaml'))
    assert len(live) == 1, 'at most one live link per address'


def test_a_mail_failure_is_a_visible_non_zero_exit(configured, root, smtp, capsys):
    smtp.refuse(smtplib.SMTPException('provider said no'))
    with pytest.raises(SystemExit) as refused:
        invites.main(['--vault', str(root), '--email', INVITEE])
    assert refused.value.code == 1
    err = capsys.readouterr().err
    assert 'the mail failed' in err
    assert '--print-link' in err, 'the exit must name the way out'
    # The record exists but nobody can reach it: that is a failed
    # command, never a quiet one.
    assert len(list((root / invites.FOLDER).glob('*.yaml'))) == 1


def test_print_link_works_with_mail_unconfigured(root, smtp, capsys):
    # The point of the flag: an environment whose mail is not configured
    # can still hand the link over. No SMTP variables are set here.
    invites.main(['--vault', str(root), '--email', INVITEE, '--print-link'])
    out = capsys.readouterr().out
    assert out.startswith(BASE_URL + invites.ACCEPT_PATH)
    assert smtp == [], '--print-link must not touch the network'


def test_print_link_without_a_base_url_is_a_refusal_not_a_half_link(
        root, monkeypatch, capsys):
    monkeypatch.delenv('APP_BASE_URL')
    with pytest.raises(SystemExit) as refused:
        invites.main(['--vault', str(root), '--email', INVITEE, '--print-link'])
    assert 'APP_BASE_URL' in str(refused.value)
    assert 'no link can be built' in str(refused.value)


def test_mailing_without_a_base_url_is_a_refusal_not_a_traceback(
        root, monkeypatch, capsys):
    """The mailed route builds the same link; an unset APP_BASE_URL must
    land in the command's own refusal (exit 1, named, pointing at
    --print-link) and never escape as MailNotConfigured from `_send`."""
    monkeypatch.delenv('APP_BASE_URL')
    with pytest.raises(SystemExit) as refused:
        invites.main(['--vault', str(root), '--email', INVITEE])
    assert refused.value.code == 1
    err = capsys.readouterr().err
    assert 'the mail failed' in err
    assert 'APP_BASE_URL' in err
    assert '--print-link' in err


# --- what the vault stores ---------------------------------------------------

def test_the_vault_never_holds_the_raw_token(root):
    record, token = invites.create_invite(root, INVITEE, 'Friend')
    stored_path = tokens.storage_path(root, invites.FOLDER, token)
    assert stored_path.name == tokens.token_hash(token) + '.yaml'
    stored = vault._read(stored_path)
    assert stored['token_hash'] == tokens.token_hash(token)
    assert 'token' not in stored
    # Not in this record, and not in ANY file in the vault: the raw
    # token exists only in the return value and the mail.
    for path in Path(root).rglob('*'):
        if path.is_file():
            assert token not in path.read_text(errors='ignore')
    assert record['email'] == INVITEE


def test_the_invite_expiry_is_seven_days_and_an_expired_link_is_dead(root):
    record, token = invites.create_invite(root, INVITEE)
    created = datetime.fromisoformat(record['created_at'])
    expires = datetime.fromisoformat(record['expires_at'])
    assert expires - created == invites.EXPIRY == timedelta(days=7)
    # Still live a moment before the window closes, dead after it.
    assert tokens.state(record, now=expires - timedelta(seconds=1)) == tokens.TOKEN_LIVE
    assert tokens.state(record, now=expires + timedelta(seconds=1)) == tokens.TOKEN_DEAD
    expire(tokens.storage_path(root, invites.FOLDER, token))
    with pytest.raises(tokens.TokenError) as refused:
        invites.accept(root, token, 'Friend', PASSWORD)
    assert str(refused.value) == tokens.DEAD_LINK_MESSAGE
    assert users.find_by_email(root, INVITEE) is None


# --- accepting ---------------------------------------------------------------

def test_accept_creates_the_default_role_and_never_an_admin(root):
    _, token = invites.create_invite(root, INVITEE, 'Friend')
    user = invites.accept(root, token, 'Friend', PASSWORD)
    assert user['role'] == users.DEFAULT_ROLE
    assert users.DEFAULT_ROLE != 'admin'
    assert user['email'] == INVITEE
    # And the account really signs in with the chosen password.
    assert users.authenticate(root, INVITEE, PASSWORD)['id'] == user['id']


def test_accept_spends_the_link_so_a_second_one_is_dead(root):
    _, token = invites.create_invite(root, INVITEE, 'Friend')
    invites.accept(root, token, 'Friend', PASSWORD)
    assert tokens.state(invites.load(root, token)) == tokens.TOKEN_DEAD
    with pytest.raises(tokens.TokenError):
        invites.accept(root, token, 'Friend', PASSWORD)
    # Still exactly one account: the second submit created nothing.
    assert len(list((root / 'users').glob('*.yaml'))) == 1


def test_two_concurrent_accepts_cannot_both_win(root):
    """The race the write lock exists for: two workers, one link."""
    _, token = invites.create_invite(root, INVITEE, 'Friend')
    barrier = threading.Barrier(2)
    outcomes = []

    def submit():
        barrier.wait()
        try:
            outcomes.append(invites.accept(root, token, 'Friend', PASSWORD))
        except tokens.TokenError:
            outcomes.append(None)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len([o for o in outcomes if o is not None]) == 1
    assert len([o for o in outcomes if o is None]) == 1
    assert len(list((root / 'users').glob('*.yaml'))) == 1


def test_a_refusal_leaves_the_link_unspent_for_a_corrected_retry(root):
    _, token = invites.create_invite(root, INVITEE, 'Friend')
    with pytest.raises(ValueError) as refused:
        invites.accept(root, token, 'Friend', 'short')
    assert str(refused.value) == users.PASSWORD_TOO_SHORT
    assert tokens.state(invites.load(root, token)) == tokens.TOKEN_LIVE
    # The corrected second try still works.
    invites.accept(root, token, 'Friend', PASSWORD)
    assert users.find_by_email(root, INVITEE) is not None


def test_an_account_created_between_invite_and_accept_refuses_the_takeover(root):
    _, token = invites.create_invite(root, INVITEE, 'Friend')
    users.create_user(root, email=INVITEE, name='Owner made one first',
                      role='tester', password=PASSWORD)
    with pytest.raises(ValueError) as refused:
        invites.accept(root, token, 'Attacker', 'another long passphrase')
    assert 'already exists' in str(refused.value)
    # The invite is a way to CREATE an account, never to take one over:
    # the existing password still works and the record is untouched.
    assert users.authenticate(root, INVITEE, PASSWORD) is not None


def test_a_missing_name_is_refused_even_when_the_invite_had_none(root):
    _, token = invites.create_invite(root, INVITEE)
    with pytest.raises(ValueError) as refused:
        invites.accept(root, token, '   ', PASSWORD)
    assert 'name is required' in str(refused.value).lower()


# --- the accept page -----------------------------------------------------------

def test_the_page_is_reachable_logged_out_and_shows_the_form(app, root):
    _, token = invites.create_invite(root, INVITEE, 'Friend')
    client = app.test_client()
    response = client.get(f'/accept-invite/{token}')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'Accept your invite' in page
    assert 'value="Friend"' in page, 'the invited name prefills the form'
    assert "name='password'" in page


def test_an_unknown_or_dead_token_gets_the_one_dead_link_page(app, root):
    client = app.test_client()
    unknown = client.get('/accept-invite/not-a-real-token')
    assert unknown.status_code == 200
    assert tokens.DEAD_LINK_MESSAGE in unknown.get_data(as_text=True)
    _, token = invites.create_invite(root, INVITEE)
    expire(tokens.storage_path(root, invites.FOLDER, token))
    expired = client.get(f'/accept-invite/{token}')
    assert expired.status_code == 200
    assert tokens.DEAD_LINK_MESSAGE in expired.get_data(as_text=True)


def test_submitting_the_form_creates_the_account_and_redirects_to_login(
        app, root):
    _, token = invites.create_invite(root, INVITEE, 'Friend')
    client = app.test_client()
    response = client.post(f'/accept-invite/{token}',
                           data={'name': 'Friend', 'password': PASSWORD})
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    assert users.find_by_email(root, INVITEE) is not None
    # NO auto sign-in: the person came from a mailbox, and signing in
    # with the password they just chose proves they have it. The real
    # gate (raw_session) says this client has no session.
    assert client.get('/api/jobs').status_code == 401
    # And the link is spent: the resent form gets the dead-link page.
    again = client.post(f'/accept-invite/{token}',
                        data={'name': 'Friend', 'password': PASSWORD})
    assert again.status_code == 200
    assert tokens.DEAD_LINK_MESSAGE in again.get_data(as_text=True)


def test_a_short_password_on_the_page_is_refused_and_the_link_survives(
        app, root):
    _, token = invites.create_invite(root, INVITEE)
    client = app.test_client()
    refused = client.post(f'/accept-invite/{token}',
                          data={'name': 'Friend', 'password': 'short'})
    assert refused.status_code == 400
    assert users.PASSWORD_TOO_SHORT in refused.get_data(as_text=True)
    assert users.find_by_email(root, INVITEE) is None
    fixed = client.post(f'/accept-invite/{token}',
                        data={'name': 'Friend', 'password': PASSWORD})
    assert fixed.status_code == 302


def test_the_page_rate_limits_with_one_generic_refusal(app, root, monkeypatch):
    monkeypatch.setenv('CAREEROS_RATE_LIMIT', '2')
    _, token = invites.create_invite(root, INVITEE, 'Friend')
    client = app.test_client()
    for _ in range(2):
        client.post(f'/accept-invite/{token}',
                    data={'name': '', 'password': 'short'})
    refused = client.post(f'/accept-invite/{token}',
                          data={'name': 'Friend', 'password': PASSWORD})
    assert refused.status_code == 429
    page = refused.get_data(as_text=True)
    assert server.RATE_LIMITED_MESSAGE in page
    # The refusal says nothing about the token, the account or which
    # limit was hit — and the token was NOT spent by the refusals.
    assert 'not valid' not in page
    assert tokens.state(invites.load(root, token)) == tokens.TOKEN_LIVE
