"""User records, the accounts command line, and the session the gate reads.

M1 puts a real door on the app: every page and every API call needs a
logged-in user. A user record carries an identity and nothing else, and
it still does after M2: the data hangs off the identity from the other
side, as the `owner_id` field on a job or an experience record (see
vault.OWNER_FIELD), so nothing here has to list what a user owns.

What M2 adds here is the two readings of a user that the rest of the app
asks for: `owner`, the scope a user's own records are read under, and
`is_admin`, which decides whether they may change the shared ones.

CAREER-116 adds the one thing in the record that is a preference rather
than an identity: `locale`, which language this user wants the app in.
It is stored here because the server is the ground truth for it, and read
back by `locale` below and by GET /api/me; nothing sets it yet.

A user record never holds the plain password. The only thing stored is a
werkzeug hash, and the plain text exists for the length of one call: the
command line hands it to generate_password_hash, and a sign-in hands it
to check_password_hash. Nothing logs it, nothing returns it and no other
record kind holds a field for it.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from flask import g, session
from werkzeug.security import check_password_hash, generate_password_hash

from careeros import i18n, vault

#: The two roles, a fixed list (PROJECT.md Roles). One admin manages
#: accounts from the command line; a tester signs in and uses the app.
#: The gate still asks only whether there is a user, never which kind.
#: Since M2 the role is read in exactly one more place, `is_admin`, which
#: decides who may change the shared records; what a user may see of the
#: private ones is decided by ownership and not by role (D3).
ROLES = ('admin', 'tester')

#: The role the command line gives a new account unless told otherwise.
#: An admin therefore cannot be created by leaving an argument out, which
#: is what makes `--role admin` an explicit act rather than a default.
DEFAULT_ROLE = 'tester'

#: How many testers the friend test plans for (PROJECT.md: five friends).
#: Recorded, deliberately not enforced: refusing the sixth account would
#: be a rule the brief does not ask for, and the owner adding one more
#: tester is not a mistake worth blocking.
TESTER_PLAN = 5

#: The vault file the session cookie is signed with, and the mode it is
#: written under. It is a secret, so only the owner may read it.
SECRET_KEY_FILE = 'secret_key'
SECRET_KEY_MODE = 0o600

#: The least a stored key may be and still be treated as one. A key this
#: module writes is 64 hex characters, so anything shorter is a file that
#: was truncated, emptied or half-written rather than a key somebody chose.
#: Such a file is replaced instead of used: a zero-byte key signs nothing,
#: and a server that adopted one would answer every request with a 500
#: until a person noticed and deleted the file by hand.
SECRET_KEY_MIN_BYTES = 32

#: How long a session cookie stays valid. The session has to survive a
#: browser restart, so it is a persistent cookie with a long life rather
#: than a session-scoped one.
SESSION_MAX_AGE = timedelta(days=30)

#: The only thing the cookie carries. The role, the name and whether the
#: account is disabled are read from the record on every request, so a
#: client that unpacked the cookie would find nothing worth forging.
SESSION_FIELD = 'user_id'

#: The second thing the cookie carries: the session epoch of the record
#: at sign-in time. `session_user` compares it against the record's own
#: epoch on every request, and a password reset bumps that epoch — so
#: every cookie minted before the reset stops passing the gate on its
#: next request. Per account, by construction: bumping one user's epoch
#: ends that user's sessions and nobody else's. A record or cookie with
#: no epoch reads as 0, which is what keeps sessions minted before this
#: field existed valid until something bumps them.
SESSION_EPOCH_FIELD = 'session_epoch'

#: The shortest password any account path accepts. No password rule
#: existed anywhere before the invite and reset pages arrived, and both
#: let a person choose their own password from a browser — so the rule
#: lives here, beside the hash, and every path that sets a password
#: (accounts command line, invite accept, password reset) runs it.
#: Ten characters is the documented minimum; there is no complexity
#: rule, because a length floor a person can meet with a passphrase is
#: worth more than a character-class rule they meet with "Password1!".
PASSWORD_MIN_LENGTH = 10

#: One message for every failed sign-in, whichever half was wrong. An
#: unknown email and a wrong password are indistinguishable in the
#: response, so the login page cannot be used to find out who has an
#: account.
SIGN_IN_FAILED = 'Wrong email or password.'

#: What an API call without a session is told. It names no record and no
#: route, so a caller learns only that it has to sign in.
LOGIN_REQUIRED = 'login required'

#: What a tester is told when they try to change shared data (M2,
#: decision D3). Companies and the tag vocabulary are one universe every
#: user reads and the admin alone edits. It names the two kinds rather
#: than the route, so the same sentence serves every shared write path,
#: and it says who may instead of only saying no.
SHARED_READ_ONLY = 'Only the admin can change companies and vocabulary.'

#: What a too-short password is told. Says the floor and nothing about
#: the account or the other fields.
PASSWORD_TOO_SHORT = (f'A password must be at least {PASSWORD_MIN_LENGTH} '
                      'characters long.')

_EMAIL_RE = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')

#: The hash a sign-in is checked against when there is no account to check
#: against. Hashing is the slow part of a sign-in, so returning before it
#: for an unknown or disabled email would answer those two measurably
#: faster than a wrong password and make the clock say what the one
#: message refuses to: whether that address has an account. Computed once
#: at import, from a value nothing keeps, so no password can match it.
_ABSENT_HASH = generate_password_hash(secrets.token_urlsafe(32))


def vault_root(explicit=None):
    """The vault a process works on: an explicit path wins, then
    CAREEROS_VAULT, then the installed default.

    One home for the rule the server and this command line both follow,
    so the accounts command can never write a user into a different vault
    than the one the server reads.
    """
    from careeros.server import DEFAULT_VAULT

    return Path(explicit if explicit is not None else
                os.environ.get('CAREEROS_VAULT', DEFAULT_VAULT)).expanduser()


def secret_key(root):
    """The key the session cookie is signed with, read from the vault or
    created there the first time.

    A signed cookie is worthless once the key changes, so the key cannot
    be generated per process: a restart would sign every tester out. It
    lives in the vault beside the records it guards, and it is created
    with owner-only permissions. A file that was copied in with looser
    permissions is tightened here rather than trusted.

    This never returns an unusable key. A missing file, a missing vault
    directory and an unreadable or truncated file all end in a written
    key, because every request reads the session and a server with no key
    cannot answer one.
    """
    path = Path(root) / SECRET_KEY_FILE
    try:
        stored = path.read_bytes().strip()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        stored = b''
    if len(stored) >= SECRET_KEY_MIN_BYTES:
        if path.stat().st_mode & 0o777 != SECRET_KEY_MODE:
            os.chmod(path, SECRET_KEY_MODE)
        return stored
    if path.exists():
        # Said out loud, because it is not a quiet repair: the old key is
        # gone, so every cookie signed with it stops being accepted.
        print(f'Warning: {path} is not a usable signing key '
              f'({len(stored)} bytes); writing a new one. '
              'Everybody signed in with the old key has to sign in again.',
              file=sys.stderr)
        return _write_secret_key(path, replace=True)
    return _write_secret_key(path)


def _write_secret_key(path, replace=False):
    """Put a new key in the vault, so that it appears whole or not at all.

    Written to a temporary file beside it and moved into place, the same
    way vault._write saves a record: a process that dies mid-write cannot
    leave a half-written or zero-byte key behind, which is the state that
    would turn every later request into a 500.

    A first create is moved in with a hard link, which fails when the file
    is already there. That is what keeps the race safe: two servers
    starting together cannot end up signing with two different keys,
    because the loser of the create adopts the winner's file. Replacing a
    key already found unusable has no winner to protect, so it overwrites.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32).encode()
    descriptor, name = tempfile.mkstemp(dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(value)
        os.chmod(temporary, SECRET_KEY_MODE)
        if replace:
            os.replace(temporary, path)
            return value
        try:
            os.link(temporary, path)
        except FileExistsError:
            return path.read_bytes().strip()
        return value
    finally:
        temporary.unlink(missing_ok=True)


def _entries(root):
    """Every stored user, as (path, record).

    Uses the vault's own reader, so one unreadable file cannot take down
    the sign-in path for everybody, the same rule the job and company
    listings already follow.
    """
    for path in sorted((Path(root) / 'users').glob('*.yaml')):
        data = vault._read(path)
        # An id-reservation tombstone is not an account (vault.reserve_id).
        # No command deletes one, so none exists today; filtered here all
        # the same, because the allocator this kind shares would leave one
        # the day a delete arrives, and a tombstone reaching the sign-in
        # path would be an account with no email and no hash.
        if data and not vault.is_reserved(data):
            yield path, data


def list_users(root):
    """Every stored user, oldest account first."""
    return sorted((d for _, d in _entries(root)), key=lambda d: str(d.get('created_at', '')))


def load_user(root, identifier):
    return next((d for _, d in _entries(root) if d.get('id') == identifier), None)


def normalize_email(value):
    """The one form an address is stored and looked up under. An address
    typed with different capitals is the same account, so the record holds
    the lowercase form and every lookup goes through here."""
    return value.strip().lower() if isinstance(value, str) else value


def validate_password(password):
    """The one password rule. Raises ValueError for a password no
    account may be created or reset with; returns nothing, because
    there is nothing to hand back — the caller hashes what it was given.
    """
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(PASSWORD_TOO_SHORT)


def find_by_email(root, email):
    wanted = normalize_email(email)
    return next((d for _, d in _entries(root) if d.get('email') == wanted), None)


def next_id(root):
    """What the next account id would be, without taking it.

    Numbered through the vault's own monotonic allocator like every other
    record kind (vault.ID_PREFIXES), so no account id is ever reused.
    There is no command that deletes an account, so this kind never had
    the reuse oracle the others did; it shares the allocator anyway,
    because "a record id is handed out once" is easier to keep true as
    one rule than as three.
    """
    return vault._next(root, 'users')


def admins(root):
    return [user for user in list_users(root) if user.get('role') == 'admin']


def validate_user(data, existing=None):
    """Check and normalize one user record, merging onto the stored one.

    Same shape as the other record kinds' validation-on-save: an
    allowlist of fields, a key outside it changes nothing, and an invalid
    value is a refused write rather than a stored surprise.
    """
    if not isinstance(data, dict):
        raise ValueError('User must be an object.')
    # A plain password has no field to land in, and dropping one quietly
    # would be the worst kind of silent drop, so asking for it is an
    # error rather than a no-op (CAREER-30: no drop is silent).
    if 'password' in data:
        raise ValueError('A user record never stores a plain password; pass a password_hash.')
    defaults: dict = dict(email='', name='', role=DEFAULT_ROLE, password_hash='',
                          created_at='', disabled=False,
                          locale=i18n.DEFAULT_LOCALE)
    # `session_epoch` is allowed but not defaulted: a record carries it
    # only once something bumped it, so every record written before the
    # field existed keeps its exact shape (and the stored-fields test its
    # exact list) until the first reset touches it.
    if isinstance((existing or {}).get(SESSION_EPOCH_FIELD), int) or \
            isinstance((data or {}).get(SESSION_EPOCH_FIELD), int):
        defaults[SESSION_EPOCH_FIELD] = 0
    # The allowlist filters the merged record, not just the payload. A key
    # outside it that reached the file some other way -- a `password:` line
    # added by hand -- is therefore dropped by the next save of that
    # record, rather than being carried forward forever because no payload
    # ever mentioned it.
    result = {key: value for key, value in (defaults | (existing or {}) | data).items()
              if key in defaults}
    for key in ('email', 'name', 'role', 'password_hash', 'created_at', 'locale'):
        if not isinstance(result[key], str):
            raise ValueError(f'{key} must be text.')
    if SESSION_EPOCH_FIELD in result and type(result[SESSION_EPOCH_FIELD]) is not int:
        raise ValueError(f'{SESSION_EPOCH_FIELD} must be a whole number.')
    result['email'] = normalize_email(result['email'])
    result['name'] = result['name'].strip()
    if not _EMAIL_RE.fullmatch(result['email']):
        raise ValueError('Email must be an address.')
    if not result['name']:
        raise ValueError('Name is required.')
    if result['role'] not in ROLES:
        raise ValueError('Role must be one of ' + ', '.join(ROLES) + '.')
    # Which languages exist is the catalog's answer, not a list kept here:
    # `i18n.available_locales` reads the catalog directory, so adding a
    # `de.json` widens what a record may say with no change in this file.
    locales = i18n.available_locales()
    if result['locale'] not in locales:
        raise ValueError('Locale must be one of ' + ', '.join(locales) + '.')
    # A hash, never a password. Every werkzeug hash carries its method and
    # salt separated by '$', so a plain password written into this field
    # by mistake is refused here instead of being stored in the clear.
    if '$' not in result['password_hash']:
        raise ValueError('password_hash must be a werkzeug password hash.')
    if type(result['disabled']) is not bool:
        raise ValueError('disabled must be boolean.')
    result['created_at'] = result['created_at'] or vault.timestamp()
    return result


def save_user(root, data, identifier=None):
    """Persist one user record, allocating an id for a new one.

    Email uniqueness is checked here rather than by each caller, so no
    path can create a second account on one address.
    """
    existing = next(((p, d) for p, d in _entries(root) if d.get('id') == identifier),
                    None) if identifier else None
    if identifier and not existing:
        raise KeyError(identifier)
    result = validate_user(data, existing[1] if existing else None)
    clash = find_by_email(root, result['email'])
    if clash and clash['id'] != (identifier or ''):
        raise ValueError(f"A user with the email {result['email']} already exists.")
    result['id'] = identifier or vault._allocate(root, 'users')
    path = Path(root) / 'users' / f"{vault.slugify(result['name'])}-{result['id'].lower()}.yaml"
    vault._write(path, result)
    if existing and existing[0] != path:
        existing[0].unlink()
    return result


def create_user(root, *, email, name, role, password):
    """Create one account. The plain password is hashed here and is not
    part of the record this returns."""
    validate_password(password)
    return save_user(root, dict(email=email, name=name, role=role,
                                password_hash=generate_password_hash(password)))


def set_password(root, identifier, password):
    """Replace one account's password. The old hash is gone after this, so
    the old password stops working on the next sign-in."""
    validate_password(password)
    return save_user(root, dict(password_hash=generate_password_hash(password)), identifier)


def set_disabled(root, identifier, disabled):
    """Turn one account off or back on. A disabled user is rejected on
    their next request, so this ends a live session too."""
    return save_user(root, dict(disabled=disabled), identifier)


def bump_session_epoch(root, identifier):
    """End every live session of one account, and only that account's.

    The cookie carries the epoch its sign-in saw; the gate compares it
    against the record's on every request (session_user). Bumping the
    record therefore invalidates every cookie minted before the bump —
    which is what a password reset needs — while every other account's
    epoch, and every other session, is untouched.
    """
    user = load_user(root, identifier)
    if user is None:
        raise KeyError(identifier)
    epoch = user.get(SESSION_EPOCH_FIELD)
    current = epoch if isinstance(epoch, int) else 0
    return save_user(root, {SESSION_EPOCH_FIELD: current + 1}, identifier)


def authenticate(root, email, password):
    """The user these credentials belong to, or None.

    One answer for every failure, so the caller has nothing to tell apart
    and cannot accidentally report which half was wrong. A disabled
    account fails here like a wrong password does, and costs the same: the
    hash check runs on every attempt, against _ABSENT_HASH when there is
    no account to check, so the three failures take the same time as well
    as reading the same.
    """
    if not isinstance(password, str):
        return None
    user = find_by_email(root, email)
    absent = user is None or bool(user.get('disabled'))
    try:
        matched = check_password_hash(
            _ABSENT_HASH if absent else user.get('password_hash', ''), password)
    except ValueError:
        # A record whose hash is unreadable cannot authenticate anybody.
        return None
    return None if absent or not matched else user


def sign_in(user):
    """Put this user's id and the record's session epoch in the session.

    session.clear() first so signing in never inherits anything from
    whatever was in the cookie before, and permanent so the cookie
    survives the browser closing.
    """
    session.clear()
    session[SESSION_FIELD] = user['id']
    # The epoch stamps the cookie with the generation of sessions it
    # belongs to; a later bump of the record's epoch ends it (see
    # bump_session_epoch). No epoch in the record reads as 0.
    epoch = user.get(SESSION_EPOCH_FIELD)
    session[SESSION_EPOCH_FIELD] = epoch if isinstance(epoch, int) else 0
    session.permanent = True


def sign_out():
    session.clear()


def session_user(root):
    """The user this request is signed in as, or None.

    The record is re-read on every request on purpose: the cookie holds
    an id, so disabling an account takes effect on that account's next
    request rather than whenever its cookie happens to expire.
    The same re-read compares the cookie's session epoch against the
    record's, so a password reset ends the sessions minted before it on
    their next request too.
    """
    identifier = session.get(SESSION_FIELD)
    if not isinstance(identifier, str):
        return None
    user = load_user(root, identifier)
    if user is None or user.get('disabled'):
        return None
    record_epoch = user.get(SESSION_EPOCH_FIELD)
    if session.get(SESSION_EPOCH_FIELD, 0) != (record_epoch if isinstance(record_epoch, int) else 0):
        return None
    return user


def is_admin(user):
    """Whether this user may change shared records (M2, decision D3).

    The one place the role is read as a permission. Companies and the tag
    vocabulary are one shared universe every user reads; changing them
    stays with the admin, and a tester gets SHARED_READ_ONLY instead.
    """
    return (user or {}).get('role') == 'admin'


def locale(user):
    """Which language this user wants the app in.

    The one place the read default lives. `validate_user` defaults the
    field on save, so every record written from now on carries it -- but
    every account created before CAREER-116 is a stored record with no
    `locale` line until something saves it again, and such a record is
    not half-configured: it is a user who never chose, which is the
    catalog's own language. Consumers ask here instead of each repeating
    a `.get`, so there is one answer to change the day a browser header
    gets a say.

    A stored value the catalog no longer ships reads as the default for
    the same reason: a translation that was removed, or a line edited
    into the file by hand, must not reach a client as a language it has
    no strings for. Only a save can refuse such a value outright
    (`validate_user`); a read has a record in front of it already.
    """
    chosen = (user or {}).get('locale')
    return chosen if chosen in i18n.available_locales() else i18n.DEFAULT_LOCALE


def owner(user):
    """The ownership scope this user's reads and writes run under.

    Returns a `vault.Owner`, which is what every job and experience read
    is filtered through. The admin inherits the records that carry no
    owner, because those are the pre-M2 records the migration hands them
    (see vault.Owner and scripts/migrate_record_owner.py).

    None for no user. No request path may hand that None to a vault
    reader -- `owner=None` means "unscoped, read everything" there --
    so a request resolves its scope through `request_owner` below, which
    refuses rather than returning None.
    """
    return None if user is None else vault.Owner(user['id'], is_admin(user))


# --- One principal per request (2026-10-27 privacy audit, finding 8) -----
#
# The gate (server.require_login) used to validate a user and then every
# later reading of "who is this" -- the ownership scope, the admin check,
# the Jinja pages' own -- called `session_user` again. Two readings of one
# request are two answers whenever anything changes in between: a reset or
# a disable landing between them turned a request the gate had let in into
# one with no user, and `owner(None)` is None, which every vault reader
# takes as "unscoped, read the whole vault".
#
# So the principal is resolved ONCE, cached on `flask.g` (per request, by
# definition), and a request that cannot resolve one is refused instead of
# being read as unscoped.

#: Where the resolved principal is cached on `flask.g`. Set even when it
#: is None, so "resolved to nobody" is told apart from "not yet resolved"
#: and the record is never read twice in one request.
REQUEST_PRINCIPAL = '_careeros_principal'


class IdentityUnresolved(Exception):
    """A request whose principal cannot be resolved, raised rather than
    answered with None.

    None is not a safe value to pass on: `owner(None)` is None and an
    unscoped `owner` is every vault reader's "no filter". A missing
    identity therefore has to stop the request, which is what raising
    does; `server.create_app` turns this into the same 401 the gate
    gives a request with no session at all.
    """


def request_user(root):
    """The one principal of this request, resolved once and cached on `g`.

    The gate resolves it first, so every later reading in the same
    request is the gate's own answer rather than a fresh read of the
    record that may by then say something else.
    """
    if not hasattr(g, REQUEST_PRINCIPAL):
        setattr(g, REQUEST_PRINCIPAL, session_user(root))
    return getattr(g, REQUEST_PRINCIPAL)


def request_principal(root):
    """This request's principal, or `IdentityUnresolved`.

    What every consumer of identity behind the gate calls: a request that
    got this far has a session, so no user here is the race the finding
    describes and is refused, never read as "see everything".
    """
    user = request_user(root)
    if user is None:
        raise IdentityUnresolved(LOGIN_REQUIRED)
    return user


def request_owner(root):
    """The ownership scope this request reads and writes under, failing
    closed when there is no principal to build one from."""
    return owner(request_principal(root))


# --- The accounts command line -------------------------------------------
#
# The first admin cannot sign in to create themselves, so accounts are
# managed from here. There is no web UI for user management in M1.

def _print_users(root):
    users = list_users(root)
    if not users:
        print('No users yet.')
        return
    width = max(len(user.get('email', '')) for user in users)
    for user in users:
        state = 'disabled' if user.get('disabled') else 'active'
        print(f"{user.get('id', ''):<9} {user.get('email', ''):<{width}} "
              f"{user.get('role', ''):<7} {state:<8} {user.get('name', '')}")


def _require(root, email):
    user = find_by_email(root, email)
    if user is None:
        raise SystemExit(f'No user with the email {normalize_email(email)}.')
    return user


def _create(root, args):
    # An admin is only ever created by asking for one: the default role is
    # tester, so there is no argument a caller can leave out and end up
    # with a second admin by accident. When they do ask while an admin
    # already exists, the command says so rather than complying quietly.
    if args.role == 'admin' and admins(root):
        print('Warning: an admin already exists. Creating a second admin because '
              '--role admin was asked for.', file=sys.stderr)
    try:
        user = create_user(root, email=args.email, name=args.name,
                           role=args.role, password=args.password)
    except ValueError as error:
        raise SystemExit(str(error))
    print(f"Created {user['id']} {user['role']} {user['email']} ({user['name']}).")


def _reset_password(root, args):
    user = _require(root, args.email)
    set_password(root, user['id'], args.password)
    # Said here because a reset is the thing a person does when they think
    # an account is compromised, and it is not the thing that ends the
    # session somebody else may already hold: the cookie carries an id, so
    # it keeps passing the gate whatever the password now is.
    print(f"Reset the password for {user['id']} {user['email']}. "
          'The old password no longer works. '
          'Anyone already signed in as this account stays signed in: a reset '
          'does not end a live session. To end one, disable the account, or '
          "delete the vault's secret_key file to sign everybody out.")


def _set_state(root, args, disabled):
    user = _require(root, args.email)
    set_disabled(root, user['id'], disabled)
    word = 'Disabled' if disabled else 'Enabled'
    print(f"{word} {user['id']} {user['email']}."
          + (' Their session ends on their next request.' if disabled else ''))


def build_parser():
    parser = argparse.ArgumentParser(
        prog='python -m careeros.users',
        description='Manage CareerOS accounts. There is no public signup.')
    parser.add_argument('--vault', default=None,
                        help='Vault directory. Overrides CAREEROS_VAULT.')
    commands = parser.add_subparsers(dest='command', required=True)

    create = commands.add_parser('create', help='Create one account.')
    create.add_argument('--email', required=True)
    create.add_argument('--name', required=True)
    create.add_argument('--role', choices=ROLES, default=DEFAULT_ROLE,
                        help=f'Default {DEFAULT_ROLE}. An admin has to be asked for.')
    create.add_argument('--password', required=True)

    commands.add_parser('list', help='List every account. Never prints a hash.')

    reset = commands.add_parser('reset-password', help='Replace one account password.')
    reset.add_argument('--email', required=True)
    reset.add_argument('--password', required=True)

    disable = commands.add_parser('disable', help='Turn one account off.')
    disable.add_argument('--email', required=True)

    enable = commands.add_parser('enable', help='Turn one account back on.')
    enable.add_argument('--email', required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = vault_root(args.vault)
    if args.command == 'list':
        _print_users(root)
        return
    # Every write holds the vault write lock, the same one the server
    # holds, so an account change cannot interleave with a record write
    # from a running instance. The directory is created first because the
    # lock is taken on it, and bootstrapping the first admin is allowed to
    # be the thing that brings a fresh vault into existence.
    root.mkdir(parents=True, exist_ok=True)
    with vault.WriteLock(root):
        if args.command == 'create':
            _create(root, args)
        elif args.command == 'reset-password':
            _reset_password(root, args)
        elif args.command == 'disable':
            _set_state(root, args, True)
        elif args.command == 'enable':
            _set_state(root, args, False)


if __name__ == '__main__':
    main()
