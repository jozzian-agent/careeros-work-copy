"""Invitation records and the invite command line.

An invite is how an account comes to exist without the owner typing a
password for somebody else: the owner runs one command on the server,
the address gets a mail with a one-time link, and the person behind it
chooses their own name and password on the accept page. There is no
public signup and no web UI for this — the command line is the only way
in, exactly like `python -m careeros.users`.

The rules that matter:

- An invite always creates the normal non-admin role
  (`users.DEFAULT_ROLE`). There is no argument, no flag and no code path
  here that creates an admin: the only admin route stays the accounts
  command's explicit `--role admin`.
- The link works ONCE and expires after seven days (`EXPIRY`). Both
  facts live in the token record and are enforced by `tokens.consume`
  under the vault write lock, so two racing submits cannot both win.
- The vault stores only the token's hash, never the token
  (`careeros/tokens.py`). The one place a raw link reaches a terminal is
  `--print-link`, which exists for exactly one situation: an environment
  whose mail is not configured or whose provider refused the send.
- A second invite for the same address REPLACES an unexpired one: the
  old record is deleted, so its token is dead the moment the new mail
  goes out, and at most one live link per address exists at a time.
- An address that already has an account is refused, here and again at
  accept time: an invite is a way to create an account, never a way to
  take over one.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from careeros import mail, tokens, users, vault

#: Where invite records live, one YAML file per token named by its hash.
FOLDER = 'invites'

#: How long an invite link works. Seven days: long enough for a mail to
#: be read after a weekend, short enough that a forwarded link does not
#: stay a working account-creation endpoint forever.
EXPIRY = timedelta(days=7)

#: The path the mailed link points at. The link itself is built by
#: `mail.absolute_url` from APP_BASE_URL and from nothing else — never
#: from a request, never from a Host header.
ACCEPT_PATH = '/accept-invite/'

SUBJECT = 'You are invited to Career OS'

BODY = (
    'You are invited to Career OS.\n'
    '\n'
    'Open this link to create your account. It works once and expires '
    'in {days} days:\n'
    '\n'
    '{link}\n'
    '\n'
    'If you were not expecting this mail, ignore it and nothing happens.'
)


def load(root, token):
    """The record this invite token belongs to, or None."""
    return tokens.load(root, FOLDER, token)


def accept_path(token):
    """The link path for one token, without the base URL."""
    return f'{ACCEPT_PATH}{token}'


def _delete_live_for(root, email):
    """Drop every unexpired invite for this address. Called under the
    write lock by `create_invite`, which is what makes "replaced" true
    at the instant the new record lands rather than eventually."""
    for path in sorted((Path(root) / FOLDER).glob('*.yaml')):
        record = vault._read(path)
        if (record and record.get('email') == email
                and tokens.state(record) == tokens.TOKEN_LIVE):
            path.unlink()


def create_invite(root, email, name=''):
    """Store one invite record and return `(record, token)`.

    The raw token exists only in this return value: the record on disk
    holds its hash. An unexpired invite for the same address is
    replaced, so its token stops working here.
    """
    address = users.normalize_email(email)
    token = tokens.new_token()
    now = datetime.now(timezone.utc)
    record = {
        'email': address,
        'name': (name or '').strip(),
        'token_hash': tokens.token_hash(token),
        'created_at': now.isoformat(),
        'expires_at': (now + EXPIRY).isoformat(),
    }
    with vault.WriteLock(root):
        _delete_live_for(root, address)
        vault._write(tokens.storage_path(root, FOLDER, token), record)
    return record, token


def accept(root, token, name, password):
    """Spend one invite link and create the account it was for.

    Verification, the account creation and the burn happen inside one
    hold of the vault write lock (`tokens.consume`), so a second submit
    of the same link — a double click, two tabs, two workers — finds the
    record already used and is refused.

    The account is `users.DEFAULT_ROLE`, always. Refusals: an account on
    this email already exists (an invite creates, it never takes over),
    a missing name, or a password that fails `users.validate_password`.
    A refusal raises before the token is burned, so the link still works
    for a corrected second try until it expires.
    """
    def create(record):
        if users.find_by_email(root, record['email']):
            raise ValueError(f'An account with the email {record["email"]} already '
                             'exists, so this invite cannot create a second one. '
                             'Use the password reset if it is yours.')
        display = (name or '').strip() or record.get('name', '')
        if not display:
            raise ValueError('A name is required.')
        users.validate_password(password)
        return users.create_user(root, email=record['email'], name=display,
                                 role=users.DEFAULT_ROLE, password=password)

    _, user = tokens.consume(root, FOLDER, token, create)
    return user


# --- The invite command line ------------------------------------------------

def _send(root, record, token):
    """Mail the invite. Returns None on success and a refusal string on
    any failure — a refusal is a visible failure of the command, never
    a quiet one, and never a fake success."""
    link = None
    try:
        link = mail.absolute_url(accept_path(token))
    except mail.MailNotConfigured as error:
        return str(error)
    body = BODY.format(days=EXPIRY.days, link=link)
    try:
        result = mail.send(root, [record['email']], SUBJECT, body)
    except (mail.MailNotConfigured, mail.MailCapReached) as refusal:
        return str(refusal)
    if result.status != 'sent':
        return result.error or 'the mail was not sent'
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='python -m careeros.invites',
        description='Invite one person to create a tester account. '
                    'An invite can never create an admin.')
    parser.add_argument('--vault', default=None,
                        help='Vault directory. Overrides CAREEROS_VAULT.')
    parser.add_argument('--email', required=True,
                        help='The address to invite.')
    parser.add_argument('--name', default='',
                        help='Optional name to prefill on the accept page.')
    parser.add_argument('--print-link', action='store_true',
                        help='Print the link instead of mailing it. The '
                             'fallback for an environment whose mail is '
                             'not configured or whose provider refused '
                             'the send — and the only place a raw invite '
                             'link is ever printed.')
    args = parser.parse_args(argv)

    root = users.vault_root(args.vault)
    root.mkdir(parents=True, exist_ok=True)
    address = users.normalize_email(args.email)
    if users.find_by_email(root, address):
        raise SystemExit(f'A user with the email {address} already exists; '
                         'nothing was invited. To replace their password, use '
                         '`python -m careeros.users reset-password`.')
    try:
        record, token = create_invite(root, address, args.name)
    except ValueError as error:
        raise SystemExit(str(error))

    if args.print_link:
        # The point of the flag: the link goes to the owner's terminal
        # instead of through a provider that is not working. It is still
        # built from APP_BASE_URL, so an unset one is a refusal here too
        # rather than a half link the invitee cannot follow.
        try:
            link = mail.absolute_url(accept_path(token))
        except mail.MailNotConfigured as error:
            raise SystemExit(f'The invite is stored but no link can be built: {error}')
        print(link)
        print(f'Invited {address}. Printed the link instead of mailing it; '
              f'it works once and expires in {EXPIRY.days} days.')
        return

    refusal = _send(root, record, token)
    if refusal:
        # Non-zero and named: the invite record exists but nobody can
        # reach it, which is a failed command and not a sent mail.
        print(f'The invite for {address} is stored, but the mail failed: '
              f'{refusal}', file=sys.stderr)
        print('Fix the mail configuration, or re-run with --print-link to '
              'hand the link over yourself (that replaces this invite).',
              file=sys.stderr)
        raise SystemExit(1)
    print(f'Invited {address}. The mail was sent; the link works once and '
          f'expires in {EXPIRY.days} days.')


if __name__ == '__main__':
    main()
