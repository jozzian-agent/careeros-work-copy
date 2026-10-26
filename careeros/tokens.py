"""One-time link tokens: how they are made, stored and spent.

Both mail-shaped features — the invite and the password reset — hand a
person a link that works once and then dies. This module is the one home
for the rules that make such a link safe, so the two features cannot
drift apart on any of them:

- A token is 32 random bytes, URL-safe (`secrets.token_urlsafe(32)`).
- The vault stores ONLY a SHA-256 hash of it, never the token. A token
  this long is pure entropy, so a plain hash is the right tool here —
  the slow, salted werkzeug hashing exists to protect guessable
  passwords, and nothing about a 256-bit random token is guessable.
  Every comparison still goes through `hmac.compare_digest`, so a
  response says nothing about how much of a guess was right.
- A token is spent atomically: `consume` verifies and marks the record
  used under the vault write lock, so two concurrent submits of the
  same link cannot both win — whichever gets the lock first burns it.
- Nothing here logs a token or a link. The only place a raw token ever
  reaches a terminal is the invite command's explicit `--print-link`.

Records live as one YAML file per token under a feature's own folder,
named by the token hash (`invites/<sha256>.yaml`, `resets/<sha256>.yaml`).
The name is how a submit finds its record; the stored hash inside is
what the constant-time check compares against, so finding the file is
never the whole answer.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from pathlib import Path

from careeros import vault

#: Bytes of randomness in a token. 32 is what `secrets.token_urlsafe`
#: is asked for in the brief and far past any brute-force horizon.
TOKEN_BYTES = 32

#: One answer for every dead link — unknown, expired or already used.
#: A person holding a dead link is told it is dead and nothing more;
#: which of the three it is, is nobody's business but the vault's.
DEAD_LINK_MESSAGE = 'This link is not valid.'
TOKEN_DEAD = 'dead'
TOKEN_LIVE = 'live'


class TokenError(ValueError):
    """The link does not work: unknown token, expired, or already used.

    One exception for all three on purpose, so no caller can report
    them apart even by accident.
    """


def new_token():
    """A fresh token. Returned to exactly one caller and stored nowhere
    in the raw: the record that goes to disk holds `token_hash` of it."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token):
    """The only form of a token the vault ever holds."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def matches(stored_hash, token):
    """Whether this token is the one the record was made from.

    Constant-time on the hashes, so a wrong token learns nothing about
    the right one from the clock either.
    """
    if not isinstance(stored_hash, str) or not isinstance(token, str):
        return False
    return hmac.compare_digest(stored_hash, token_hash(token))


def storage_path(root, folder, token):
    """Where a token's record lives: one file per token, named by hash."""
    return Path(root) / folder / f'{token_hash(token)}.yaml'


def expires_at(record):
    """When a record's window closes, or None when it says nothing sane.

    A missing, malformed or naive timestamp reads as already expired —
    the safe direction for a record this module cannot vouch for.
    """
    raw = record.get('expires_at')
    if not isinstance(raw, str):
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment


def state(record, now=None):
    """`live` or `dead` for a record, without spending it.

    What a GET of an accept or reset page reads to decide between the
    form and the dead-link state. Unknown token is the caller's None
    record, which never reaches here.
    """
    now = now or datetime.now(timezone.utc)
    if not record or record.get('used_at'):
        return TOKEN_DEAD
    expiry = expires_at(record)
    if expiry is None or expiry <= now:
        return TOKEN_DEAD
    return TOKEN_LIVE


def load(root, folder, token):
    """The record this token belongs to, or None when there is none."""
    return vault._read(storage_path(root, folder, token))


def consume(root, folder, token, then=None):
    """Verify one token and mark it used, as one indivisible step.

    Under the vault write lock, so two workers (or two threads) racing
    the same link see the file in turn: the first marks it used, and
    the second reads a used record and is refused. `then(record)` runs
    inside the same lock, before `used_at` is written, so an action
    that refuses — a duplicate email, a weak password — leaves the
    token unspent rather than burning a link for a change that never
    happened.

    Returns `(record, then_result)`; `then_result` is None without a
    `then`. Raises TokenError for a link that does not work, with the
    one message for all three reasons.
    """
    path = storage_path(root, folder, token)
    with vault.WriteLock(root):
        record = vault._read(path)
        if record is None or not matches(record.get('token_hash'), token):
            raise TokenError(DEAD_LINK_MESSAGE)
        if state(record) is not TOKEN_LIVE:
            raise TokenError(DEAD_LINK_MESSAGE)
        result = then(record) if then is not None else None
        record['used_at'] = vault.timestamp()
        vault._write(path, record)
        return record, result
