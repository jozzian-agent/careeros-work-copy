"""A per-key request counter, stored in the vault so workers agree.

The three unauthenticated POSTs — forgot password, accept an invite,
submit a reset — are the only places a stranger can make the server do
password work on their behalf, so each is counted per email address AND
per client IP, and refused past a limit.

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
CAREEROS_RATE_LIMIT attempts per CAREEROS_RATE_WINDOW seconds per key.
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


def _positive_int(name, default):
    raw=(os.environ.get(name) or '').strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError(f'{name} must be a positive whole number, not {raw!r}.')
    return int(raw)


def limit_and_window():
    """The configured (limit, window_seconds), read fresh on every call
    so a test or an env-file edit takes effect without a restart."""
    return (_positive_int('CAREEROS_RATE_LIMIT', DEFAULT_LIMIT),
            _positive_int('CAREEROS_RATE_WINDOW', DEFAULT_WINDOW))


def email_key(email):
    """The counter key for one address. Lowercased the same way user
    records are, so `Owner@X` and `owner@x` share one budget."""
    from careeros import users

    return f'email:{users.normalize_email(str(email or ""))}'


def ip_key(address):
    """The counter key for one client IP."""
    return f'ip:{address or ""}'


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


def check(root, key, now=None):
    """Whether one more attempt on this key is allowed right now.

    Counts nothing: this is the read half, for a page that wants to
    know before it asks for a form. `hit` is the counting half.
    """
    limit, window = limit_and_window()
    now = time.time() if now is None else now
    counters = _locked_counters(root, now, window)
    entry = counters.get(key)
    return (entry['count'] if entry else 0) < limit


def hit(root, key, now=None):
    """Count one attempt on this key. True when it was still within the
    limit, False when this attempt is the one over.

    Read-and-write under one hold of the lock, so two concurrent hits
    cannot both read the same count and both squeeze under the limit.
    """
    limit, window = limit_and_window()
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


def keys_for(email=None, ip=None):
    """Both keys one request is counted under. The IP half is skipped
    when the app has no address to count (a test client), so the
    per-address limit still does its whole job."""
    keys = [email_key(email)] if email else []
    if ip:
        keys.append(ip_key(ip))
    return keys


def allowed(root, email=None, ip=None):
    """Whether a request from this address on this IP may proceed.

    Every key has to have budget: the limits are per key, and a request
    is refused as soon as one of its counters is spent.
    """
    return all(check(root, key) for key in keys_for(email, ip))


def register(root, email=None, ip=None):
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
    keys = keys_for(email, ip)
    if not keys:
        return True
    limit, window = limit_and_window()
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
