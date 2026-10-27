"""A per-key request counter, stored in the vault so workers agree.

The four unauthenticated POSTs — sign in, forgot password, accept an
invite, submit a reset — are the only places a stranger can make the
server do password work on their behalf, so each is counted per email
address AND per client IP, and refused past a limit.

A SCOPE keeps one of those four from spending another's budget. The
mailed-link three share the unscoped keys they have always used; the
login form counts under its own (`login:email:…`, `login:ip:…`) with its
own tunables, because a failed sign-in and a request for a reset link
are different acts and five wrong passwords must not block the reset
that fixes them (2026-10-27 privacy audit, finding 10).

The count lives in ONE vault file (`ratelimit/windows.yaml`), read and
written under the vault's own write lock. In-memory counters would be
per process, and the deployment runs two gunicorn workers: an attacker
would simply alternate between them and get double the budget. The file
is the `mail/count.yaml` pattern — a small tally, expired windows
dropped on every read, so it cannot grow without bound.

A key is a short prefix plus the value (`email:…`, `ip:…`), so one
address cannot spend an IP's budget or the other way round.

The limit is deliberately coarse. It exists to make guessing and
mail-bombing expensive, not to be an exact science: the defaults are
CAREEROS_RATE_LIMIT attempts per CAREEROS_RATE_WINDOW seconds per key,
and CAREEROS_LOGIN_RATE_LIMIT / CAREEROS_LOGIN_RATE_WINDOW for the login
scope. Every window ends, so no key is ever locked out for good.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from careeros import vault

#: One file, one lock, one read/write shape. Windows past their end are
#: dropped on every write, so the file only ever holds live counters.
STATE_FILE='ratelimit/windows.yaml'

#: Attempts one key may make inside one window before the next is
#: refused. Five per hour is far past any human mistyping their
#: password and far below anything an automated guesser wants.
DEFAULT_LIMIT = 5

#: How long a window lasts, in seconds. One hour.
DEFAULT_WINDOW=3600

#: The login form's own scope. A scope is a key prefix and a pair of env
#: tunables, nothing more; '' is the unscoped mailed-link budget.
LOGIN_SCOPE = 'login'

#: Login's own budget. Ten FAILED sign-ins an hour per address and per IP
#: (a success spends nothing, see server.login): past anyone mistyping a
#: password a few times, nowhere near what guessing a password needs.
DEFAULT_LOGIN_LIMIT = 10
DEFAULT_LOGIN_WINDOW = 3600

#: Each scope's (limit, window) defaults and the env vars that override
#: them. Same prefix and same naming as the pair the mailed-link POSTs
#: have always read, so one scope can be loosened without loosening the
#: other.
SCOPES = {
    '': ((DEFAULT_LIMIT, DEFAULT_WINDOW),
         ('CAREEROS_RATE_LIMIT', 'CAREEROS_RATE_WINDOW')),
    LOGIN_SCOPE: ((DEFAULT_LOGIN_LIMIT, DEFAULT_LOGIN_WINDOW),
                  ('CAREEROS_LOGIN_RATE_LIMIT', 'CAREEROS_LOGIN_RATE_WINDOW')),
}


def _positive_int(name, default):
    raw=(os.environ.get(name) or '').strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError(f'{name} must be a positive whole number, not {raw!r}.')
    return int(raw)


def limit_and_window(scope=''):
    """This scope's configured (limit, window_seconds), read fresh on
    every call so a test or an env-file edit takes effect without a
    restart."""
    (limit, window), (limit_var, window_var) = SCOPES[scope]
    return (_positive_int(limit_var, limit), _positive_int(window_var, window))


def _prefix(kind, scope):
    """The key prefix for one kind of counter in one scope. The unscoped
    prefixes are unchanged, so the counters already on disk keep
    counting for the pages that wrote them."""
    return f'{scope}:{kind}' if scope else kind


def email_key(email, scope=''):
    """The counter key for one address. Lowercased the same way user
    records are, so `Owner@X` and `owner@x` share one budget."""
    from careeros import users

    return f'{_prefix("email", scope)}:{users.normalize_email(str(email or ""))}'


def ip_key(address, scope=''):
    """The counter key for one client IP."""
    return f'{_prefix("ip", scope)}:{address or ""}'


def _live(counters, now, window):
    """Drop every window that has ended. Called before both a read and
    a write, so the stored file only ever holds counters that matter."""
    return {key: value for key, value in counters.items()
            if isinstance(value, dict) and
            isinstance(value.get('until'), (int, float)) and
            value['until'] > now and
            isinstance(value.get('count'), int) and value['count'] > 0}


def _locked_counters(root, now, window):
    """Read the live windows under the vault lock."""
    with vault.WriteLock(root):
        return _live((vault._read(Path(root) / STATE_FILE) or {}).get('windows') or {},
                     now, window)


def check(root, key, now=None, scope=''):
    """Whether one more attempt on this key is allowed right now.

    Counts nothing: this is the read half, for a page that wants to
    know before it asks for a form. `hit` is the counting half.
    """
    limit, window = limit_and_window(scope)
    now = time.time() if now is None else now
    counters = _locked_counters(root, now, window)
    entry = counters.get(key)
    return (entry['count'] if entry else 0) < limit


def hit(root, key, now=None, scope=''):
    """Count one attempt on this key. True when it was still within the
    limit, False when this attempt is the one over.

    Read-and-write under one hold of the lock, so two concurrent hits
    cannot both read the same count and both squeeze under the limit.
    """
    limit, window = limit_and_window(scope)
    now = time.time() if now is None else now
    with vault.WriteLock(root):
        path = Path(root) / STATE_FILE
        counters = _live((vault._read(path) or {}).get('windows') or {}, now, window)
        entry = counters.get(key)
        if entry is None:
            counters[key] = {'count': 1, 'until': now + window}
            allowed = limit >= 1
        else:
            entry['count'] += 1
            allowed = entry['count'] <= limit
        vault._write(path, {'windows': counters})
    return allowed


def keys_for(email=None, ip=None, scope=''):
    """Both keys one request is counted under. The IP half is skipped
    when the app has no address to count (a test client), so the
    per-address limit still does its whole job."""
    keys = [email_key(email, scope)] if email else []
    if ip:
        keys.append(ip_key(ip, scope))
    return keys


def allowed(root, email=None, ip=None, scope=''):
    """Whether a request from this address on this IP may proceed.

    Every key has to have budget: the limits are per key, and a request
    is refused as soon as one of its counters is spent.
    """
    return all(check(root, key, scope=scope) for key in keys_for(email, ip, scope))


def register(root, email=None, ip=None, scope=''):
    """Count one request under each of its keys. True when every key
    still had budget, False when at least one was spent.

    All keys are decided and counted in ONE lock hold over ONE file
    read/write, and a refused request only increments the keys that
    were ALREADY spent. That ordering matters for two attacks the
    naive `all(hit(key) ...)` shape allows:

    - Cross-key exhaustion: an already-blocked IP posting different
      users' emails would spend one of each victim's budget per
      request, locking real people out of password reset without ever
      rotating IPs. Here the victim's healthy email key is untouched
      by a request that is refused through the IP.
    - Unbounded state: a blocked IP posting fresh random email strings
      would create a new counter entry per string, growing the YAML
      that every later request parses and rewrites under the shared
      vault lock. A refused request creates no new entries at all.

    A key that is over the limit DOES keep counting on refusal (the
    spent budget grows past the limit) — that is the documented
    "a refused attempt still spends budget" rule, preserved.
    """
    keys = keys_for(email, ip, scope)
    if not keys:
        return True
    limit, window = limit_and_window(scope)
    now = time.time()
    with vault.WriteLock(root):
        path = Path(root) / STATE_FILE
        counters = _live((vault._read(path) or {}).get('windows') or {}, now, window)
        spent = [key for key in keys
                 if counters.get(key, {'count': 0})['count'] >= limit]
        for key in spent if spent else keys:
            entry = counters.get(key)
            if entry is None:
                counters[key] = {'count': 1, 'until': now + window}
            else:
                entry['count'] += 1
                entry['until'] = now + window
        vault._write(path, {'windows': counters})
    return not spent
