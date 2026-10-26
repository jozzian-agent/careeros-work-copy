"""Protects the rules of `careeros/mail.py`: an unconfigured environment
fails visibly and connects to nothing, the daily cap refuses before the
network, the count moves only on a send that was accepted, and neither
the SMTP password nor a mail body ever reaches the log.

No real network: `smtplib.SMTP` and `smtplib.SMTP_SSL` are replaced by a
fake that records the one call shape the module makes.
"""

import logging
import os
import smtplib
import subprocess
import sys
from pathlib import Path

import pytest

from careeros import mail, vault

PASSWORD = 'correct horse battery staple'
HOST = 'smtp.example.test'
SENDER = 'careeros@example.test'
RECIPIENT = 'friend@example.test'
SECRET_BODY = 'Your reset link is https://app.example.test/reset/abc123'

#: Every variable the module reads. Cleared before each test, so no
#: ambient SMTP configuration on the machine running the suite can make
#: a test pass or fail for a reason the test does not state.
VARIABLES = ('SMTP_HOST', 'SMTP_PORT', 'SMTP_SECURITY', 'SMTP_USER', 'SMTP_PASSWORD',
             'SMTP_TIMEOUT', 'MAIL_FROM', 'MAIL_FROM_NAME', 'MAIL_DAILY_CAP',
             'APP_BASE_URL')


@pytest.fixture(autouse=True)
def no_mail_environment(monkeypatch):
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def root(tmp_path):
    """An explicit vault root, passed to every call: nothing here may
    reach the installed default vault."""
    return tmp_path / 'vault'


@pytest.fixture
def configured(monkeypatch):
    """The least an environment needs to send."""
    monkeypatch.setenv('SMTP_HOST', HOST)
    monkeypatch.setenv('SMTP_USER', 'mailer')
    monkeypatch.setenv('SMTP_PASSWORD', PASSWORD)
    monkeypatch.setenv('MAIL_FROM', SENDER)


class Recorder(list):
    """The connections a test's fake SMTP made, newest last, each a dict.
    An empty one is the assertion that nothing touched the network, and
    `refuse` makes the next handover fail the way a server does."""

    def refuse(self, error):
        for fake in self.fakes:
            fake.failure = error


@pytest.fixture
def smtp(monkeypatch):
    """Records what the module did instead of connecting anywhere."""
    connections = Recorder()

    class Fake:
        failure = None

        def __init__(self, host, port, timeout=None):
            self.record = {'kind': self.kind, 'host': host, 'port': port,
                           'timeout': timeout, 'starttls': False, 'login': None,
                           'sent': []}
            connections.append(self.record)

        def __enter__(self):
            return self

        def __exit__(self, *error):
            return False

        def starttls(self):
            self.record['starttls'] = True

        def login(self, user, password):
            self.record['login'] = (user, password)

        def send_message(self, message, to_addrs=None):
            if type(self).failure is not None:
                raise type(self).failure
            self.record['sent'].append((message, to_addrs))

    class Plain(Fake):
        kind = 'starttls'

    class Secure(Fake):
        kind = 'ssl'

    monkeypatch.setattr(smtplib, 'SMTP', Plain)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', Secure)
    connections.fakes = (Plain, Secure)
    return connections


def body_of(message):
    return message.get_body(('plain',)).get_content()


# --- not configured is a visible failure ----------------------------------

def test_an_unconfigured_environment_names_every_missing_variable(root, smtp):
    with pytest.raises(mail.MailNotConfigured) as refused:
        mail.send(root, [RECIPIENT], 'Hello', 'A body')
    for name in mail.REQUIRED:
        assert name in str(refused.value)
    assert 'Nothing was sent.' in str(refused.value)
    assert smtp == [], 'an unconfigured send must not touch the network'


def test_a_half_configured_environment_names_only_what_is_missing(monkeypatch, root, smtp):
    monkeypatch.setenv('SMTP_HOST', HOST)
    monkeypatch.setenv('SMTP_USER', 'mailer')
    monkeypatch.setenv('MAIL_FROM', SENDER)
    with pytest.raises(mail.MailNotConfigured) as refused:
        mail.send(root, [RECIPIENT], 'Hello', 'A body')
    assert 'SMTP_PASSWORD' in str(refused.value)
    assert 'SMTP_HOST' not in str(refused.value)
    assert smtp == []


def test_a_refused_send_reads_as_failed_in_the_log(root, smtp, caplog):
    with caplog.at_level(logging.WARNING, logger='careeros.mail'):
        with pytest.raises(mail.MailNotConfigured):
            mail.send(root, [RECIPIENT], 'Hello', 'A body')
    assert 'mail failed' in caplog.text
    assert RECIPIENT in caplog.text


def test_a_nonsense_variable_is_refused_by_name(monkeypatch, configured, root, smtp):
    monkeypatch.setenv('SMTP_SECURITY', 'plaintext')
    with pytest.raises(mail.MailNotConfigured) as refused:
        mail.send(root, [RECIPIENT], 'Hello', 'A body')
    assert 'SMTP_SECURITY' in str(refused.value)
    monkeypatch.setenv('SMTP_SECURITY', 'starttls')
    monkeypatch.setenv('SMTP_PORT', '58x')
    with pytest.raises(mail.MailNotConfigured) as refused:
        mail.send(root, [RECIPIENT], 'Hello', 'A body')
    assert 'SMTP_PORT' in str(refused.value)
    assert smtp == []


# --- the two connection paths ---------------------------------------------

def test_starttls_is_the_default_path(configured, root, smtp):
    result = mail.send(root, [RECIPIENT], 'Hello', 'A body')
    assert result == mail.Result('sent', (RECIPIENT,), None)
    assert len(smtp) == 1
    connection = smtp[0]
    assert connection['kind'] == 'starttls'
    assert (connection['host'], connection['port']) == (HOST, 587)
    assert connection['timeout'] == mail.DEFAULT_TIMEOUT
    assert connection['starttls'] is True
    assert connection['login'] == ('mailer', PASSWORD)
    message, to_addrs = connection['sent'][0]
    assert to_addrs == [RECIPIENT]
    assert message['To'] == RECIPIENT
    assert message['From'] == SENDER
    assert message['Subject'] == 'Hello'
    assert body_of(message).strip() == 'A body'


def test_ssl_connects_with_tls_from_the_first_byte(monkeypatch, configured, root, smtp):
    monkeypatch.setenv('SMTP_SECURITY', 'ssl')
    assert mail.send(root, [RECIPIENT], 'Hello', 'A body').status == 'sent'
    connection = smtp[0]
    assert connection['kind'] == 'ssl'
    assert connection['port'] == 465
    assert connection['starttls'] is False, 'implicit TLS must not be upgraded again'


def test_port_timeout_and_sender_name_come_from_the_environment(
        monkeypatch, configured, root, smtp):
    monkeypatch.setenv('SMTP_PORT', '2525')
    monkeypatch.setenv('SMTP_TIMEOUT', '5')
    monkeypatch.setenv('MAIL_FROM_NAME', 'Career OS')
    mail.send(root, [RECIPIENT], 'Hello', 'A body')
    assert (smtp[0]['port'], smtp[0]['timeout']) == (2525, 5)
    assert smtp[0]['sent'][0][0]['From'] == f'Career OS <{SENDER}>'


def test_one_mail_reaches_a_whole_list_of_recipients(configured, root, smtp):
    everybody = ['one@example.test', 'two@example.test', 'three@example.test']
    result = mail.send(root, everybody, 'An update', 'A body')
    assert result.recipients == tuple(everybody)
    assert len(smtp) == 1, 'a list of recipients is one mail, not one per address'
    message, to_addrs = smtp[0]['sent'][0]
    assert to_addrs == everybody
    assert message['To'] == ', '.join(everybody)
    assert mail.sent_today(root) == 3


def test_sending_to_nobody_is_refused(configured, root, smtp):
    with pytest.raises(ValueError):
        mail.send(root, [], 'Hello', 'A body')
    with pytest.raises(ValueError):
        mail.send(root, RECIPIENT, 'Hello', 'A body')
    assert smtp == []


def test_a_failed_connection_returns_the_reason(configured, root, smtp):
    smtp.refuse(smtplib.SMTPAuthenticationError(535, b'bad credentials'))
    result = mail.send(root, [RECIPIENT], 'Hello', 'A body')
    assert result.status == 'failed'
    assert 'SMTPAuthenticationError' in result.error


# --- the daily cap --------------------------------------------------------

def test_the_cap_refuses_the_mail_after_the_last_one(monkeypatch, configured, root, smtp):
    monkeypatch.setenv('MAIL_DAILY_CAP', '3')
    for number in (1, 2, 3):
        assert mail.send(root, [RECIPIENT], f'Mail {number}', 'A body').status == 'sent'
        assert mail.sent_today(root) == number
    with pytest.raises(mail.MailCapReached) as refused:
        mail.send(root, [RECIPIENT], 'Mail 4', 'A body')
    assert '3' in str(refused.value)
    assert len(smtp) == 3, 'a capped mail must be refused before it connects'
    assert mail.sent_today(root) == 3


def test_the_cap_refuses_a_batch_it_cannot_hold_whole(monkeypatch, configured, root, smtp):
    monkeypatch.setenv('MAIL_DAILY_CAP', '2')
    with pytest.raises(mail.MailCapReached):
        mail.send(root, ['one@example.test', 'two@example.test', 'three@example.test'],
                  'An update', 'A body')
    assert smtp == []
    assert mail.sent_today(root) == 0


def test_the_count_moves_only_on_a_send_the_server_accepted(configured, root, smtp):
    smtp.refuse(smtplib.SMTPDataError(451, b'try later'))
    assert mail.send(root, [RECIPIENT], 'Hello', 'A body').status == 'failed'
    assert mail.sent_today(root) == 0, 'a failed mail must not spend the budget'


def test_a_count_from_another_day_does_not_bind_today(monkeypatch, configured, root, smtp):
    monkeypatch.setenv('MAIL_DAILY_CAP', '1')
    vault._write(Path(root) / mail.COUNT_FILE, {'date': '2026-10-01', 'count': 150})
    assert mail.sent_today(root) == 0
    assert mail.send(root, [RECIPIENT], 'Hello', 'A body').status == 'sent'
    assert mail.sent_today(root) == 1


def test_an_unreadable_count_file_is_not_a_cap(configured, root, smtp):
    path = Path(root) / mail.COUNT_FILE
    path.parent.mkdir(parents=True)
    path.write_text('this is not a count\n\t- [')
    assert mail.sent_today(root) == 0
    assert mail.send(root, [RECIPIENT], 'Hello', 'A body').status == 'sent'


# --- what a log line may hold ---------------------------------------------

def test_neither_the_password_nor_the_body_reaches_the_log(configured, root, smtp, caplog):
    with caplog.at_level(logging.DEBUG, logger='careeros.mail'):
        mail.send(root, [RECIPIENT], 'Reset your password', SECRET_BODY,
                  html=f'<p>{SECRET_BODY}</p>')
        smtp.refuse(smtplib.SMTPServerDisconnected('gone'))
        mail.send(root, [RECIPIENT], 'Reset your password', SECRET_BODY)
    assert PASSWORD not in caplog.text
    assert SECRET_BODY not in caplog.text
    assert 'abc123' not in caplog.text, 'no part of a body, however small'
    # What it does say: who it went to, what it was about, and how it went.
    assert RECIPIENT in caplog.text
    assert 'Reset your password' in caplog.text
    assert 'mail sent' in caplog.text and 'mail failed' in caplog.text


def test_the_password_is_not_in_any_error_message(monkeypatch, configured, root, smtp):
    monkeypatch.setenv('SMTP_PORT', '58x')
    with pytest.raises(mail.MailNotConfigured) as refused:
        mail.send(root, [RECIPIENT], 'Hello', 'A body')
    assert PASSWORD not in str(refused.value)
    smtp.refuse(smtplib.SMTPAuthenticationError(535, b'bad credentials'))
    monkeypatch.delenv('SMTP_PORT')
    assert PASSWORD not in (mail.send(root, [RECIPIENT], 'Hello', 'A body').error or '')


# --- links ----------------------------------------------------------------

def test_absolute_url_is_built_from_app_base_url_alone(monkeypatch):
    monkeypatch.setenv('APP_BASE_URL', 'https://app.example.test/')
    assert mail.absolute_url('/reset/abc') == 'https://app.example.test/reset/abc'
    assert mail.absolute_url('reset/abc') == 'https://app.example.test/reset/abc'
    monkeypatch.setenv('APP_BASE_URL', 'https://other.example.test')
    assert mail.absolute_url('/reset/abc') == 'https://other.example.test/reset/abc'


def test_a_link_with_no_base_url_is_a_visible_failure():
    with pytest.raises(mail.MailNotConfigured) as refused:
        mail.absolute_url('/reset/abc')
    assert 'APP_BASE_URL' in str(refused.value)


def test_importing_the_module_needs_no_environment_and_no_flask():
    """The two import-time promises: sending reads the environment, so
    importing reads none of it, and nothing here may reach a request --
    which is what keeps a link in a mail off the Host header."""
    done = subprocess.run(
        [sys.executable, '-c',
         'import sys, careeros.mail; print("flask" in sys.modules)'],
        env={'PYTHONPATH': os.pathsep.join(path for path in sys.path if path)},
        capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == 'False'


# --- the test-mail command line -------------------------------------------

def test_the_test_command_sends_one_mail_and_says_so(configured, root, smtp, capsys):
    mail.main(['test', '--to', RECIPIENT, '--vault', str(root)])
    assert len(smtp) == 1
    message, to_addrs = smtp[0]['sent'][0]
    assert to_addrs == [RECIPIENT]
    assert message['Subject'] == mail.TEST_SUBJECT
    assert mail.sent_today(root) == 1, 'the named vault is the one that counts'
    printed = capsys.readouterr().out
    assert RECIPIENT in printed
    assert f'1 of {mail.DEFAULT_DAILY_CAP}' in printed


def test_the_test_command_takes_a_subject(configured, root, smtp):
    mail.main(['test', '--to', RECIPIENT, '--vault', str(root), '--subject', 'Proof'])
    assert smtp[0]['sent'][0][0]['Subject'] == 'Proof'


def test_the_test_command_requires_an_address(configured, root, smtp):
    with pytest.raises(SystemExit) as stopped:
        mail.main(['test', '--vault', str(root)])
    assert stopped.value.code == 2, 'argparse refuses a command with no --to'
    assert smtp == []


def test_the_test_command_exits_non_zero_when_it_cannot_send(root, smtp):
    with pytest.raises(SystemExit) as stopped:
        mail.main(['test', '--to', RECIPIENT, '--vault', str(root)])
    assert stopped.value.code not in (0, None)
    assert 'SMTP_HOST' in str(stopped.value.code)
    assert smtp == []


def test_the_test_command_exits_non_zero_when_the_server_refuses(
        configured, root, smtp):
    smtp.refuse(smtplib.SMTPRecipientsRefused({RECIPIENT: (550, b'no such user')}))
    with pytest.raises(SystemExit) as stopped:
        mail.main(['test', '--to', RECIPIENT, '--vault', str(root)])
    assert stopped.value.code not in (0, None)
    assert RECIPIENT in str(stopped.value.code)
    assert mail.sent_today(root) == 0
