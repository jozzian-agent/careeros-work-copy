"""Self-service password reset, by mail.

The second mail-shaped feature, and the one an existing account uses:
"Forgot password" asks for an email, a one-time link goes out when there
is an account, and the link sets a new password. The rules that matter:

- NO ENUMERATION. The request page answers with the same message, the
  same status and (as far as this module can arrange) the same time
  shape whether or not the address has an account. An unknown address,
  a disabled account and a rate-limited one all read as "if there is an
  account, a mail is on its way". The hash check below runs against
  `users._ABSENT_HASH` for the absent cases, the same trick the sign-in
  uses, so the slow part of the request costs the same either way. The
  one thing this cannot equalize is the SMTP send itself: mailing a
  nonexistent address would both leak the answer and waste the daily
  cap, so an existing account's request takes the extra milliseconds of
  a real send. Documented in docs/surfaces/accounts.md rather than
  solved by pretending.
- A reset link works ONCE and expires after ONE HOUR
  (`EXPIRY`) — shorter than an invite, because the person asking is
  already at their keyboard.
- A successful reset INVALIDATES every live session of that account and
  of no other account, by bumping the record's `session_epoch`
  (`users.bump_session_epoch`): cookies minted before the bump carry the
  old epoch and fail the gate on their next request. A reset is what a
  person does when they fear the account is in the wrong hands, so
  leaving an attacker's session alive through it would defeat the point.
  The CLI's `reset-password` keeps its old behaviour (documented there).
- The person is NOT signed in afterwards. They came from a link in a
  mailbox, not from a login they passed; making them sign in with the
  new password proves they have it.
- Disabled accounts are treated as nonexistent: no mail, same message.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from careeros import mail, tokens, users, vault

#: Where reset records live, one YAML file per token named by its hash.
FOLDER = 'resets'

#: How long a reset link works. One hour: the person asking is sitting
#: at their inbox, and a link this powerful should not linger in a
#: mailbox (or a forwarded one) for days.
EXPIRY = timedelta(hours=1)

#: The path the mailed link points at, built from APP_BASE_URL only.
RESET_PATH = '/reset-password/'

#: The one answer, whichever of the three cases is true. It promises a
#: mail conditionally — "if there is an account" — and the condition is
#: exactly what a stranger must not be able to test.
REQUEST_ACCEPTED = ('If there is an account with that email, a password '
                    'reset link is on its way.')

SUBJECT = 'Reset your Career OS password'

BODY = (
    'A password reset was asked for your Career OS account.\n'
    '\n'
    'Open this link to choose a new password. It works once and expires '
    'in one hour:\n'
    '\n'
    '{link}\n'
    '\n'
    'If you did not ask for this, ignore the mail — your password stays '
    'what it is, and nothing changes.'
)


def load(root, token):
    """The record this reset token belongs to, or None."""
    return tokens.load(root, FOLDER, token)


def request_reset(root, email):
    """Handle one forgot-password request. Always returns
    `REQUEST_ACCEPTED` and never raises for a no-account address; the
    caller shows the same message either way and has nothing to branch
    on, which is the enumeration resistance in one sentence.

    When there is a live, enabled account: replace any unexpired reset
    for it (the old token dies), store a new one and mail the link. A
    mail failure is logged server-side by `mail` itself and swallowed
    here — the response must not change shape because the provider was
    down, and the log is where an owner looks. The tension and its
    resolution are documented in docs/surfaces/accounts.md.
    """
    address = users.normalize_email(email)
    user = users.find_by_email(root, address) if address else None
    # The slow part runs on every request, present account or not, so
    # the clock says nothing the message refuses to. `_hash_of` returns
    # the real hash for a live account and the throwaway one otherwise.
    users.check_password_hash(
        users._ABSENT_HASH if user is None or user.get('disabled')
        else user.get('password_hash', ''),
        'timing equalizer, never a real password')
    if user is None or user.get('disabled'):
        return REQUEST_ACCEPTED

    token = tokens.new_token()
    now = datetime.now(timezone.utc)
    record = {
        'user_id': user['id'],
        'email': address,
        'token_hash': tokens.token_hash(token),
        'created_at': now.isoformat(),
        'expires_at': (now + EXPIRY).isoformat(),
    }
    with vault.WriteLock(root):
        _delete_live_for(root, address)
        vault._write(tokens.storage_path(root, FOLDER, token), record)
    try:
        result = mail.send(root, [address], SUBJECT,
                           BODY.format(link=mail.absolute_url(RESET_PATH + token)))
        if result.status != 'sent':
            # mail.send already logged the reason; nothing more is said
            # to the requester, whose message cannot depend on this.
            pass
    except (mail.MailNotConfigured, mail.MailCapReached):
        # Also already logged by mail.send. Same silence, same reason.
        pass
    return REQUEST_ACCEPTED


def _delete_live_for(root, email):
    """Drop every unexpired reset for this address, under the caller's
    hold of the write lock, so a replaced link is dead at once."""
    for path in sorted((Path(root) / FOLDER).glob('*.yaml')):
        record = vault._read(path)
        if (record and record.get('email') == email
                and tokens.state(record) == tokens.TOKEN_LIVE):
            path.unlink()


def complete_reset(root, token, password):
    """Spend one reset link and set the new password.

    Verification, the password write, the session-epoch bump and the
    burn happen inside one hold of the vault write lock
    (`tokens.consume`), so two concurrent submits cannot both succeed.
    The epoch bump is what ends every session minted before the reset —
    the cookie's own epoch no longer matches the record's — and it
    touches this account only.

    Returns the user record. No sign-in happens here or in the route:
    the person is sent to the login page with their new password.
    """
    #: Returned by the callback when the account vanished or was
    #: disabled between request and reset. A sentinel and not a raise,
    #: because a raise inside `then` leaves the token unspent (right
    #: for a password-rule refusal, wrong here): a dead account's link
    #: has nothing to spend itself on, and burning it is the safe
    #: direction.
    gone = object()

    def reset(record):
        user = users.load_user(root, record['user_id'])
        if user is None or user.get('disabled'):
            return gone
        users.validate_password(password)
        users.set_password(root, user['id'], password)
        users.bump_session_epoch(root, user['id'])
        return users.load_user(root, user['id'])

    _, user = tokens.consume(root, FOLDER, token, reset)
    if user is gone:
        # The token is burned; the message is the one dead-link
        # message, same as an expired token's.
        raise tokens.TokenError(tokens.DEAD_LINK_MESSAGE)
    return user
