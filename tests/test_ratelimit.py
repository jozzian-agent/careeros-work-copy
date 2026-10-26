"""Protects the rules of the per-key counter: a budget is spent per key,
email and IP budgets are independent, an expired window forgets, the
counts live in the vault so two "workers" (two app instances over one
root) share one budget, and the env knobs are read fresh and validated.

No SMTP here — this module never sends, it only counts.
"""

import time
from pathlib import Path

import pytest

from careeros import ratelimit, vault


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ('CAREEROS_RATE_LIMIT', 'CAREEROS_RATE_WINDOW'):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def root(tmp_path):
    """An explicit vault root: nothing here may reach the default vault."""
    return tmp_path / 'vault'


# --- the budget -------------------------------------------------------------

def test_a_key_may_hit_exactly_limit_times_then_is_refused(root):
    key = ratelimit.email_key('owner@example.test')
    results = [ratelimit.hit(root, key) for _ in range(ratelimit.DEFAULT_LIMIT + 2)]
    assert results == [True] * ratelimit.DEFAULT_LIMIT + [False, False]


def test_check_reads_without_spending(root):
    key = ratelimit.email_key('owner@example.test')
    assert ratelimit.check(root, key) is True
    for _ in range(ratelimit.DEFAULT_LIMIT):
        assert ratelimit.check(root, key) is True, 'the read half never moves the counter'
        assert ratelimit.hit(root, key) is True
    assert ratelimit.check(root, key) is False
    assert ratelimit.hit(root, key) is False


def test_email_and_ip_budgets_are_independent(root):
    email_key = ratelimit.email_key('owner@example.test')
    ip_key = ratelimit.ip_key('203.0.113.9')
    for _ in range(ratelimit.DEFAULT_LIMIT):
        ratelimit.hit(root, email_key)
    assert ratelimit.hit(root, email_key) is False, 'the address is spent'
    assert ratelimit.hit(root, ip_key) is True, 'the IP never spent anything'


def test_keys_for_counts_both_halves_and_skips_a_missing_ip():
    keys = ratelimit.keys_for(email='Owner@Example.Test', ip='203.0.113.9')
    assert keys == ['email:owner@example.test', 'ip:203.0.113.9']
    assert ratelimit.keys_for(email='owner@example.test') == ['email:owner@example.test']
    assert ratelimit.keys_for(ip='203.0.113.9') == ['ip:203.0.113.9']
    assert ratelimit.keys_for() == []


def test_allowed_refuses_only_when_every_key_has_budget(root):
    email_key = ratelimit.email_key('owner@example.test')
    ip_key = ratelimit.ip_key('203.0.113.9')
    assert ratelimit.allowed(root, email='owner@example.test', ip='203.0.113.9')
    for _ in range(ratelimit.DEFAULT_LIMIT):
        ratelimit.hit(root, ip_key)
    assert ratelimit.allowed(root, email='owner@example.test',
                             ip='203.0.113.9') is False
    assert ratelimit.check(root, email_key) is True, \
        'refusal through the IP must not spend the address budget'


# --- windows ----------------------------------------------------------------

def test_an_expired_window_is_forgotten(root):
    key = ratelimit.email_key('owner@example.test')
    now = 1_000_000.0
    for _ in range(ratelimit.DEFAULT_LIMIT):
        ratelimit.hit(root, key, now=now)
    assert ratelimit.hit(root, key, now=now) is False
    later = now + ratelimit.DEFAULT_WINDOW + 1
    assert ratelimit.check(root, key, now=later) is True
    assert ratelimit.hit(root, key, now=later) is True, 'a fresh window starts over'


def test_the_state_file_only_ever_holds_live_windows(root):
    key = ratelimit.email_key('owner@example.test')
    now = 1_000_000.0
    ratelimit.hit(root, key, now=now)
    path = Path(root) / ratelimit.STATE_FILE
    assert (vault._read(path) or {})['windows'][key]['count'] == 1
    # One hit after the window closed prunes the dead entry on write.
    ratelimit.hit(root, key, now=now + ratelimit.DEFAULT_WINDOW + 1)
    stored = (vault._read(path) or {})['windows']
    assert stored[key]['count'] == 1
    assert stored[key]['until'] > now + ratelimit.DEFAULT_WINDOW


# --- the vault is the shared memory -----------------------------------------

def test_two_apps_over_one_root_share_one_budget(root):
    """The deployment runs two gunicorn workers; here, two module-level
    reads over one vault root stand in for them — the counts must agree
    because they live in the file, not in any process."""
    key = ratelimit.email_key('owner@example.test')
    for _ in range(ratelimit.DEFAULT_LIMIT):
        assert ratelimit.hit(root, key) is True
    # A second "worker" sees the spent budget immediately.
    assert ratelimit.check(root, key) is False
    assert ratelimit.hit(root, key) is False
    stored = (vault._read(Path(root) / ratelimit.STATE_FILE) or {})['windows']
    # A refused attempt still counts — spending the budget is the point.
    assert stored[key]['count'] == ratelimit.DEFAULT_LIMIT + 1


# --- configuration ----------------------------------------------------------

def test_the_env_knobs_are_read_fresh(monkeypatch, root):
    monkeypatch.setenv('CAREEROS_RATE_LIMIT', '2')
    monkeypatch.setenv('CAREEROS_RATE_WINDOW', '60')
    assert ratelimit.limit_and_window() == (2, 60)
    key = ratelimit.email_key('owner@example.test')
    assert [ratelimit.hit(root, key) for _ in range(3)] == [True, True, False]


def test_a_nonsense_knob_is_a_visible_refusal(monkeypatch):
    monkeypatch.setenv('CAREEROS_RATE_LIMIT', 'lots')
    with pytest.raises(ValueError, match='CAREEROS_RATE_LIMIT'):
        ratelimit.limit_and_window()
    monkeypatch.setenv('CAREEROS_RATE_LIMIT', '0')
    with pytest.raises(ValueError, match='CAREEROS_RATE_LIMIT'):
        ratelimit.limit_and_window()


def test_the_defaults_are_the_documented_ones():
    assert ratelimit.limit_and_window() == (5, 3600)
