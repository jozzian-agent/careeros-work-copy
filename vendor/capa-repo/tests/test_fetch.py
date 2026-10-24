"""The default safe HTTP fetch adapter (org_intake/fetch.py, R2). Pure
unit tests for each guard class - no real network destination is ever
reached, so these run safely in any sandboxed CI environment.
"""
import time
import urllib.request as request

import pytest

from org_intake import fetch


# --- Guard: a literal private/reserved IP is rejected, no DNS needed ------

@pytest.mark.parametrize('host', ['10.255.255.1', '127.0.0.1', '169.254.1.1', '0.0.0.0'])
def test_check_url_rejects_private_and_reserved_literal_ips(host):
    with pytest.raises(ValueError):
        fetch.check_url(f'http://{host}/')


def test_check_url_accepts_a_public_literal_ip():
    # 8.8.8.8 is a real, globally-routable address, but resolving a
    # literal IP host is purely local (no DNS query, no socket opened) -
    # this is still a no-network check.
    assert fetch.check_url('http://8.8.8.8/') == 'http://8.8.8.8/'


# --- F8a: a hostname that resolves (via DNS) to a private IP is rejected -

def test_check_url_rejects_hostname_resolving_to_a_private_ip_via_dns(monkeypatch):
    # The hostname text itself names nothing unsafe - only its DNS
    # resolution does. This fails if the DNS-resolution guard in
    # check_url (as opposed to the literal-IP-only check_url_format) is
    # ever removed: without it, this hostname would sail through.
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(2, 1, 6, '', ('10.255.255.1', port))]

    monkeypatch.setattr(fetch.socket, 'getaddrinfo', fake_getaddrinfo)
    with pytest.raises(ValueError):
        fetch.check_url('https://private-by-dns.example/')


def test_default_fetch_rejects_private_destination_without_any_network_call():
    with pytest.raises(ValueError):
        fetch.default_fetch('http://10.255.255.1/')


def test_default_fetch_rejects_structurally_malformed_url():
    with pytest.raises(ValueError):
        fetch.default_fetch('https://[broken')


# --- Guard: a redirect hop to a private destination is rejected ----------

def test_safe_redirect_rejects_hop_to_private_destination():
    handler = fetch._SafeRedirect()
    req = request.Request('http://8.8.8.8/')
    with pytest.raises(ValueError):
        handler.redirect_request(req, None, 302, 'Found', {}, 'http://10.255.255.1/')


# --- Guard: a redirect loop is capped, never followed forever ------------

def test_safe_redirect_enforces_max_hop_count():
    handler = fetch._SafeRedirect(max_hops=2)
    req = request.Request('http://8.8.8.8/')
    handler.redirect_request(req, None, 302, 'Found', {}, 'http://8.8.8.8/a')
    handler.redirect_request(req, None, 302, 'Found', {}, 'http://8.8.8.8/b')
    with pytest.raises(ValueError):
        handler.redirect_request(req, None, 302, 'Found', {}, 'http://8.8.8.8/c')


# --- Guard: the response body is capped, never read unbounded ------------

def test_default_fetch_caps_response_body_size(monkeypatch):
    chunk = b'x' * 1000

    class FakeResponse:
        def __init__(self):
            self.remaining = 1_000_000  # far more than the cap below

        def read1(self, n):
            if self.remaining <= 0:
                return b''
            take = min(n, len(chunk), self.remaining)
            self.remaining -= take
            return chunk[:take]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeOpener:
        def open(self, req, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(fetch, 'check_url', lambda url: url)
    monkeypatch.setattr(fetch.request, 'build_opener', lambda *args, **kwargs: FakeOpener())

    result = fetch.default_fetch('http://8.8.8.8/', max_body=2000)
    # F8d: strictly bounded by max_body itself, not by max_body plus a
    # whole extra chunk - each read1 call is already given no more than
    # the remaining headroom, so the total can never overshoot the cap.
    assert len(result.encode('utf-8')) <= 2000


# --- Guard: environment proxies are disabled ------------------------------

def test_default_fetch_builds_opener_with_proxies_disabled(monkeypatch):
    captured = {}

    class FakeResponse:
        def read1(self, n):
            return b''

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeOpener:
        def open(self, req, timeout=None):
            return FakeResponse()

    def fake_build_opener(*handlers, **kwargs):
        captured['handlers'] = handlers
        return FakeOpener()

    monkeypatch.setattr(fetch, 'check_url', lambda url: url)
    monkeypatch.setattr(fetch.request, 'build_opener', fake_build_opener)

    fetch.default_fetch('http://8.8.8.8/')
    proxy_handlers = [h for h in captured['handlers'] if isinstance(h, request.ProxyHandler)]
    assert proxy_handlers and proxy_handlers[0].proxies == {}


# --- F4: the deadline is re-checked before every redirect hop and around -
# --- every body chunk read, not just at the top of default_fetch --------

def test_safe_redirect_before_hop_runs_before_following_each_hop(monkeypatch):
    calls = []

    class FakeFp:
        def read(self, n):
            return b''

        def close(self):
            pass

    monkeypatch.setattr(request.HTTPRedirectHandler, 'http_error_302',
                         lambda self, req, fp, code, msg, headers: 'followed')
    handler = fetch._SafeRedirect(before_hop=lambda: calls.append('checked'))
    req = request.Request('http://8.8.8.8/')
    result = handler.http_error_302(req, FakeFp(), 302, 'Found', {})
    assert calls == ['checked']
    assert result == 'followed'


def test_safe_redirect_before_hop_aborting_stops_the_hop(monkeypatch):
    followed = []

    class FakeFp:
        def read(self, n):
            return b''

        def close(self):
            pass

    def before_hop():
        raise TimeoutError('deadline exceeded mid-redirect')

    monkeypatch.setattr(request.HTTPRedirectHandler, 'http_error_302',
                         lambda self, req, fp, code, msg, headers: followed.append('followed'))
    handler = fetch._SafeRedirect(before_hop=before_hop)
    req = request.Request('http://8.8.8.8/')
    with pytest.raises(TimeoutError):
        handler.http_error_302(req, FakeFp(), 302, 'Found', {})
    assert followed == []


def test_default_fetch_aborts_mid_redirect_when_deadline_exceeded(monkeypatch):
    # Drives several redirect hops through the handler default_fetch
    # itself builds (so before_hop is the real `remaining` closure bound
    # to default_fetch's own deadline) under a controlled clock: the
    # first two hops are still within budget, the third is not.
    clock = {'t': 0.0}
    monkeypatch.setattr(fetch.time, 'monotonic', lambda: clock['t'])
    monkeypatch.setattr(request.HTTPRedirectHandler, 'http_error_302',
                         lambda self, req, fp, code, msg, headers: 'followed')

    captured = {}

    class FakeFp:
        def read(self, n):
            return b''

        def close(self):
            pass

    class FakeOpener:
        def open(self, req, timeout=None):
            handler = captured['handler']
            for _ in range(4):  # well under max_hops; the 3rd iteration must abort
                clock['t'] += 2
                handler.http_error_302(req, FakeFp(), 302, 'Found', {})
            raise AssertionError('must not reach a real redirect follow')

    def fake_build_opener(*handlers, **kwargs):
        captured['handler'] = next(h for h in handlers if isinstance(h, fetch._SafeRedirect))
        return FakeOpener()

    monkeypatch.setattr(fetch, 'check_url', lambda url: url)
    monkeypatch.setattr(fetch.request, 'build_opener', fake_build_opener)

    with pytest.raises(TimeoutError):
        fetch.default_fetch('http://8.8.8.8/', timeout=5)


def test_default_fetch_aborts_mid_body_read_when_deadline_exceeded(monkeypatch):
    # Advancing the clock past the deadline in between the two remaining()
    # checks that bracket each chunk read must abort the fetch, even
    # though the chunk itself was delivered successfully.
    clock = {'t': 0.0}
    monkeypatch.setattr(fetch.time, 'monotonic', lambda: clock['t'])

    class FakeResponse:
        def read1(self, n):
            clock['t'] += 10  # advances well past the 5s budget below
            return b'x' * min(n, 100)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeOpener:
        def open(self, req, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(fetch, 'check_url', lambda url: url)
    monkeypatch.setattr(fetch.request, 'build_opener', lambda *a, **k: FakeOpener())

    with pytest.raises(TimeoutError):
        fetch.default_fetch('http://8.8.8.8/', timeout=5)


# --- F8b: a server that never responds still aborts within budget --------

def test_default_fetch_times_out_when_the_server_never_responds(monkeypatch):
    # H3: the never-responding server is simulated without any real
    # wall-clock wait and without leaking threads. What the OLD version of
    # this test actually blocked on was the main thread's own
    # `result.get(timeout=budget)` against a REAL queue. That queue is
    # replaced here with a fake one whose `get` raises Empty immediately
    # (no wait at all) while recording the timeout it was asked to wait
    # for, so the assertion below is tied to the exact budget
    # default_fetch computed and passed down, not to a wall-clock race
    # bounded by an unrelated multiplier.
    budget = 0.2
    get_calls = []

    class FakeQueue:
        def __init__(self, maxsize=1):
            pass

        def put(self, item):
            pass

        def get(self, timeout=None):
            get_calls.append(timeout)
            raise fetch.Empty('simulated deadline, no real wait')

    class HangingOpener:
        def open(self, req, timeout=None):
            # The worker thread no longer blocks forever: with FakeQueue in
            # place its outcome is irrelevant (put is a no-op, get raises
            # Empty immediately), so it exits at once and no thread leaks.
            raise RuntimeError('opener result is discarded by FakeQueue')

    monkeypatch.setattr(fetch, 'Queue', FakeQueue)
    monkeypatch.setattr(fetch, 'check_url', lambda url: url)
    monkeypatch.setattr(fetch.request, 'build_opener', lambda *a, **k: HangingOpener())

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        fetch.default_fetch('http://8.8.8.8/', timeout=budget)
    # No real wait at all - the fake queue raised Empty immediately.
    assert time.monotonic() - started < 0.05
    # The deadline guard actually asked the queue to wait for exactly the
    # budget it was given.
    assert get_calls == [budget]
