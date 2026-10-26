"""Sending one mail from this app, the daily cap that bounds it, and the
command line that proves an environment can send at all.

## What this is, and what it is not

This is the seam the mail-shaped features are meant to be built on:
a password reset, an invite, an update to the testers. **None of those
exists.** Nothing in the web app calls anything here -- no route, no
template, no button -- and this module sends no product mail. The one
caller that ships is the admin command line at the bottom of this file,
which sends one test mail to one address the owner names.

`send` takes a LIST of recipients on purpose. "Send an update to all
testers" is one mail to many addresses rather than a loop over a
one-recipient function, and it is subject to the same cap as everything
else.

## Configuration is the environment, read when a mail is sent

`Config.from_env` is the only reader of the environment, and it runs per
call rather than at import: the module imports with no variables set at
all, which is what keeps it importable in a test and on a fresh clone.
Every variable is named in `.env.example` beside the file that reads it.

There is no default host, user, password or from-address, and none is
invented anywhere here: an environment with no SMTP configuration is a
working environment, exactly like one with no LLM key
(`careeros/ingest.py` settles an extraction there as `not_configured`).
Sending from it fails visibly -- `MailNotConfigured`, naming the
variables that are not set -- and never looks like a success.

## A refusal raises, an attempt returns

Two shapes, because they are two different facts:

* A refusal is a mail that was never attempted: the environment is not
  configured (`MailNotConfigured`), or today's cap is already spent
  (`MailCapReached`). Both are raised, and both happen BEFORE anything
  touches the network.
* An attempt returns a `Result`, whose status is `sent` or `failed` with
  the reason the server or the socket gave.

Either way one line reaches the log, and the log line for a failure says
`failed`. Nothing here can end quietly.

## The daily cap

`MAIL_DAILY_CAP` (default 150) addresses per UTC day, counted in the
vault -- `mail/count.yaml`, holding the day and the count, written
through the same tolerant reader and atomic writer every vault record
uses (`vault._read` / `vault._write`). One file rather than one per day:
a new day replaces the old count instead of leaving a trail nobody
reads. The count moves ONLY after a send the server accepted, so a
failed attempt never spends the owner's budget.

The read-bump-write is not locked. Two gunicorn workers sending in the
same instant can lose one count, so the cap bounds a runaway rather
than accounting exactly; a bound is what it is for, and a lock around it
would be machinery for a mail volume this app does not have.

## Secrets, and what a log line may hold

`SMTP_PASSWORD` is never logged and never put in an error message. The
body of a mail is never logged either, whole or in part: a reset link or
an invite token lives in a body. A log line holds the recipients, the
subject and the status, which is what the owner needs to see that a mail
went out without the mail itself being in the journal.

## Links

`absolute_url` builds every link from `APP_BASE_URL` and from nothing
else. This module imports no flask and reads no request context, so a
link in a mail cannot be built from a Host header a client chose.
"""

from __future__ import annotations

import argparse
import logging
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import NamedTuple

from careeros import vault

_logger = logging.getLogger(__name__)

#: How the connection is protected, a fixed list. `starttls` is the
#: default because it is what port 587 wants and what most providers
#: document first; `ssl` is an implicit-TLS connection on port 465.
#: There is no third value and no plaintext option: a mail carrying a
#: reset link is not sent over an unencrypted connection.
SECURITY_CHOICES = ('starttls', 'ssl')
DEFAULT_SECURITY = 'starttls'

#: The port each security mode uses unless `SMTP_PORT` says otherwise.
#: Derived from the mode rather than fixed, so an owner who sets only
#: `SMTP_SECURITY=ssl` does not also have to remember 465.
DEFAULT_PORTS = {'starttls': 587, 'ssl': 465}

#: Seconds per connection (`SMTP_TIMEOUT`). Every connection takes one:
#: a mail is sent from a request path or a command the owner is waiting
#: on, and an SMTP host that accepts the TCP connection and then says
#: nothing would otherwise hang until something else gave up.
DEFAULT_TIMEOUT = 20

#: Addresses per UTC day (`MAIL_DAILY_CAP`). A number the friend test
#: cannot reach by accident and a runaway loop cannot get past.
DEFAULT_DAILY_CAP = 150

#: The variables a send cannot do without. Named in this order, so the
#: message a half-configured environment produces is always the same.
REQUIRED = ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'MAIL_FROM')

#: Where the day's count lives, under the vault root.
COUNT_FILE = 'mail/count.yaml'

#: What an attempt can say about itself.
STATUSES = ('sent', 'failed')


class MailNotConfigured(RuntimeError):
    """Raised when this environment cannot send: a required variable is
    not set, or one that is set makes no sense. Names the variables, so
    the owner reads what to put in the env file and not that something
    went wrong."""


class MailCapReached(RuntimeError):
    """Raised when today's `MAIL_DAILY_CAP` is spent. Raised before the
    connection, so a capped send costs no network call."""


class Result(NamedTuple):
    """What one attempted mail did. `error` is set exactly when the
    status is `failed`."""

    status: str
    recipients: tuple
    error: str | None = None


def _text(env, name):
    return (env.get(name) or '').strip()


def _number(env, name, default):
    """One positive whole number from the environment, or the default.

    A value that is not one is a refused send naming the variable, never
    a silent fallback to the default: a `SMTP_PORT=587 ` typo'd into
    `SMTP_PORT=58x` would otherwise connect somewhere else entirely.
    """
    raw = _text(env, name)
    if not raw:
        return default
    if not raw.isdigit() or int(raw) <= 0:
        raise MailNotConfigured(f'{name} must be a positive whole number, not {raw!r}.')
    return int(raw)


@dataclass(frozen=True)
class Config:
    """Where mail goes out through, who it is from, and how much of it a
    day may carry.

    Read from the environment by `from_env` per call. Every default here
    is a real default (`DEFAULT_SECURITY`, `DEFAULT_PORTS`,
    `DEFAULT_TIMEOUT`, `DEFAULT_DAILY_CAP`); the four that matter --
    host, user, password and from-address -- have none, and an empty one
    is what `missing` reports.
    """

    host: str = ''
    port: int = DEFAULT_PORTS[DEFAULT_SECURITY]
    security: str = DEFAULT_SECURITY
    user: str = ''
    password: str = ''
    mail_from: str = ''
    from_name: str = ''
    base_url: str = ''
    timeout: int = DEFAULT_TIMEOUT
    daily_cap: int = DEFAULT_DAILY_CAP

    @classmethod
    def from_env(cls, environ=None):
        env = environ if environ is not None else os.environ
        security = _text(env, 'SMTP_SECURITY').lower() or DEFAULT_SECURITY
        if security not in SECURITY_CHOICES:
            raise MailNotConfigured(
                f'SMTP_SECURITY must be {" or ".join(SECURITY_CHOICES)}, not {security!r}.')
        return cls(
            host=_text(env, 'SMTP_HOST'),
            port=_number(env, 'SMTP_PORT', DEFAULT_PORTS[security]),
            security=security,
            # The one value not stripped: a password is taken exactly as
            # the env file gives it. Whether there IS one is still read
            # off its stripped form, in `missing` below.
            password=env.get('SMTP_PASSWORD') or '',
            user=_text(env, 'SMTP_USER'),
            mail_from=_text(env, 'MAIL_FROM'),
            from_name=_text(env, 'MAIL_FROM_NAME'),
            base_url=_text(env, 'APP_BASE_URL'),
            timeout=_number(env, 'SMTP_TIMEOUT', DEFAULT_TIMEOUT),
            daily_cap=_number(env, 'MAIL_DAILY_CAP', DEFAULT_DAILY_CAP),
        )

    def missing(self):
        """The required variables this configuration has nothing for."""
        values = {'SMTP_HOST': self.host, 'SMTP_USER': self.user,
                  'SMTP_PASSWORD': self.password, 'MAIL_FROM': self.mail_from}
        return tuple(name for name in REQUIRED if not values[name].strip())

    def require(self):
        """Refuse a send this environment cannot make.

        The message names every variable that is not set, so one reading
        of it is enough to finish the env file, rather than one failed
        send per missing line.
        """
        gaps = self.missing()
        if gaps:
            raise MailNotConfigured(
                'Mail is not configured: ' + ', '.join(gaps)
                + (' is not set.' if len(gaps) == 1 else ' are not set.')
                + ' Nothing was sent.')

    def sender(self):
        """The From header: the address, under the name if there is one."""
        return formataddr((self.from_name, self.mail_from)) if self.from_name else self.mail_from


def absolute_url(path, config=None):
    """A link into the app, built from `APP_BASE_URL` and nothing else.

    The one place a mail gets a URL from. No request is in scope when a
    mail is built -- a tester update is not sent from anybody's request
    -- and a link built from a Host header is a link a client can
    choose, so there is deliberately no second source to fall back to.

    `APP_BASE_URL` unset is a visible failure here too: a mail with a
    half-built link in it is worse than a mail that was never sent.
    """
    config = config if config is not None else Config.from_env()
    if not config.base_url:
        raise MailNotConfigured('APP_BASE_URL is not set, so no link can be built.')
    return config.base_url.rstrip('/') + '/' + str(path).lstrip('/')


def _today():
    """Today, UTC, as the count file stores it. UTC and not local time,
    so the day a cap resets on is the same fact on every machine."""
    return datetime.now(timezone.utc).date().isoformat()


def sent_today(root):
    """How many addresses this vault has mailed today (UTC).

    A count from another day, a missing file and an unreadable one all
    read as zero: the file is a day's tally and not a record anybody
    owns, so there is nothing in it worth failing a send over.
    """
    stored = vault._read(Path(root) / COUNT_FILE) or {}
    count = stored.get('count')
    if stored.get('date') != _today() or not isinstance(count, int) or count < 0:
        return 0
    return count


def _record_sent(root, addressed):
    """Add one accepted mail's addresses to today's tally."""
    vault._write(Path(root) / COUNT_FILE,
                 {'date': _today(), 'count': sent_today(root) + addressed})


def _addresses(recipients):
    """The addresses one mail goes to, as a tuple.

    A single string is refused rather than treated as one recipient:
    `send(root, 'a@b.test', ...)` would otherwise iterate its
    characters, and silently addressing a mail to nobody is the kind of
    quiet failure this module exists to avoid.
    """
    if isinstance(recipients, str) or not isinstance(recipients, (list, tuple)):
        raise ValueError('Recipients must be a list of addresses.')
    addresses = tuple(value.strip() for value in recipients
                      if isinstance(value, str) and value.strip())
    if len(addresses) != len(recipients):
        raise ValueError('Every recipient must be an address.')
    if not addresses:
        raise ValueError('Sending needs at least one recipient.')
    return addresses


def _message(config, addresses, subject, text, html=None):
    """One mail, as a message. The body is plain text, with an optional
    HTML alternative beside it; there is no template engine here,
    because no feature has asked for one yet."""
    built = EmailMessage()
    built['From'] = config.sender()
    built['To'] = ', '.join(addresses)
    built['Subject'] = subject
    # Both headers are set here because `smtplib.send_message` adds
    # neither, and a message with no Date and no Message-ID is what a
    # spam filter scores down. The id is stamped with the sending
    # domain rather than make_msgid's default, which would put this
    # box's own hostname in every mail.
    built['Date'] = formatdate(localtime=False, usegmt=True)
    built['Message-ID'] = make_msgid(domain=config.mail_from.rpartition('@')[2] or None)
    built.set_content(text)
    if html:
        built.add_alternative(html, subtype='html')
    return built


def _deliver(config, built, addresses):
    """Connect, authenticate and hand the message over.

    The two security modes differ in one line each: `ssl` is TLS from
    the first byte, `starttls` upgrades a plain connection before
    anything is sent. Both take the timeout, and the password is used
    here and nowhere else.
    """
    connect = smtplib.SMTP_SSL if config.security == 'ssl' else smtplib.SMTP
    with connect(config.host, config.port, timeout=config.timeout) as server:
        if config.security == 'starttls':
            server.starttls()
        server.login(config.user, config.password)
        server.send_message(built, to_addrs=list(addresses))


def send(root, recipients, subject, text, html=None, config=None):
    """Send one mail to one or more addresses. The seam every later
    mail-shaped feature is meant to call.

    `root` is the vault the day's count lives in, which is why it is the
    first argument rather than read from the environment here: the
    caller already knows which vault it is working on
    (`users.vault_root`).

    Raises `MailNotConfigured` or `MailCapReached` for a mail that was
    never attempted, and returns a `Result` for one that was. See the
    module docstring: a refusal raises, an attempt returns.
    """
    addresses = _addresses(recipients)
    try:
        # Inside the try, so a variable that is set to nonsense -- a
        # misspelled SMTP_SECURITY, a non-numeric port -- reads as a
        # failed mail in the log exactly like a variable that is unset.
        config = config if config is not None else Config.from_env()
        config.require()
        already = sent_today(root)
        if already + len(addresses) > config.daily_cap:
            raise MailCapReached(
                f'The daily mail cap is spent: {already} of {config.daily_cap} '
                f'already sent today, and this mail needs {len(addresses)} more. '
                'Nothing was sent.')
    except (MailNotConfigured, MailCapReached) as refusal:
        # Said in the log as well as raised, so a refusal reads as a
        # failed mail in the journal and not only in whatever caught it.
        _logger.warning('mail failed: to=%s subject=%r reason=%s',
                        ', '.join(addresses), subject, refusal)
        raise
    try:
        _deliver(config, _message(config, addresses, subject, text, html), addresses)
    except OSError as error:
        # Every socket, TLS and SMTP failure: smtplib.SMTPException and
        # ssl.SSLError are both OSError, as is a connection timeout.
        # The reason is whatever the server or the socket said, which
        # never includes the password: nothing echoes it back.
        reason = f'{type(error).__name__}: {error}'
        _logger.warning('mail failed: to=%s subject=%r reason=%s',
                        ', '.join(addresses), subject, reason)
        return Result('failed', addresses, reason)
    _record_sent(root, len(addresses))
    _logger.info('mail sent: to=%s subject=%r (%d of %d today)',
                 ', '.join(addresses), subject, sent_today(root), config.daily_cap)
    return Result('sent', addresses)


# --- The test-mail command line ------------------------------------------
#
# How the owner proves an environment can send mail, from the box itself,
# before any feature depends on it. It sends to an address they name and
# to nobody else, and it is the only caller of `send` that ships.

#: What the test mail says. Short, and it says what reading it proves.
TEST_SUBJECT = 'Career OS test mail'
TEST_BODY = ('This is the test mail from `python -m careeros.mail test`.\n\n'
             'If you are reading it, Career OS can send mail from this '
             'environment. Nothing else sent it, and nothing follows.\n')


def build_parser():
    parser = argparse.ArgumentParser(
        prog='python -m careeros.mail',
        description='Prove that this environment can send mail. Sends no product mail.')
    commands = parser.add_subparsers(dest='command', required=True)
    test = commands.add_parser(
        'test', help='Send one test mail to one address you name.')
    test.add_argument('--to', required=True,
                      help='The address to send the test mail to. Required: '
                           'this command never picks an address for you.')
    test.add_argument('--subject', default=TEST_SUBJECT)
    test.add_argument('--vault', default=None,
                      help='Vault directory, where the day count lives. '
                           'Overrides CAREEROS_VAULT.')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    # Imported here and not at the top: `users.vault_root` is the one
    # home of the rule that says which vault a process works on, and
    # `careeros.users` imports flask, which everything above this line
    # stays free of.
    from careeros import users

    root = users.vault_root(args.vault)
    try:
        config = Config.from_env()
        result = send(root, [args.to], args.subject, TEST_BODY, config=config)
    except (MailNotConfigured, MailCapReached, ValueError) as error:
        raise SystemExit(str(error))
    if result.status != 'sent':
        raise SystemExit(f'Could not send to {args.to}: {result.error}')
    print(f'Sent to {args.to} as {config.sender()}. '
          f'{sent_today(root)} of {config.daily_cap} mails sent today.')


if __name__ == '__main__':
    main()
