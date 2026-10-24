"""Default safe HTTP fetch adapter.

Restores every guard careeros/intake.py lines 31-145 applied to a posting
fetch - a DNS resolution check against private/reserved address ranges
(ipaddress), per-redirect destination revalidation, a bounded redirect
hop count, a response body size cap, environment proxies disabled, and an
overall timeout - behind one importable `default_fetch(url)` callable.
The deadline is also re-checked before every redirect hop (via
_SafeRedirect's before_hop) and around every body chunk read, exactly as
careeros/intake.py's fetch_url_follow does (~lines 105-145); an oversized
body keeps that function's original silent-truncation behavior rather
than raising.

classify_sector/classify_size (enrich.py) use this adapter whenever a
caller omits `fetch=` entirely, so the contract's literal Interface
examples work as written against real data. A caller that wants no
network call at all still passes `fetch=None` explicitly; a caller that
wants its own fetcher (a test double, or a product's own HTTP client)
still passes it in as `fetch=`, same as before.

This module performs real network I/O when called; the SSRF guard
(_rejects_unsafe_target) in enrich.py is a separate, lighter-weight,
no-DNS structural check used before any `fetch` (including this default)
is ever invoked.
"""
import ipaddress
import socket
import time
from queue import Empty, Queue
from threading import Thread
from urllib import request
from urllib.parse import urljoin, urlsplit

DEFAULT_TIMEOUT = 15
MAX_REDIRECTS = 5
MAX_REDIRECT_BODY = 65536
MAX_BODY_SIZE = 2_000_000


def is_unsafe_ip(ip):
    """A single place naming every non-public address category this
    adapter refuses to fetch from: private, loopback, link-local,
    multicast, reserved, or unspecified."""
    return any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast,
                ip.is_reserved, ip.is_unspecified))


def check_url_format(url):
    """Structural check only (scheme + host). No DNS - safe to call before
    any network access, including as a pre-fetch guard."""
    if not isinstance(url, str) or urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).hostname:
        raise ValueError('Provide an HTTP or HTTPS URL.')
    return url


def check_url(url):
    """Structural check plus a DNS resolution check: every address a
    hostname resolves to must be public, so a hostname that resolves to a
    private/loopback/link-local/reserved address is rejected even though
    its literal text never named an IP at all."""
    check_url_format(url)
    parsed = urlsplit(url)
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80),
            type=socket.SOCK_STREAM)
    except OSError as error:
        raise ValueError('Host must resolve to a public IP address.') from error
    if not addresses:
        raise ValueError('Host must resolve to a public IP address.')
    for address in addresses:
        if is_unsafe_ip(ipaddress.ip_address(address[4][0])):
            raise ValueError('Host must resolve only to public IP addresses.')
    return url


class _SafeRedirect(request.HTTPRedirectHandler):
    """Follows redirects like a normal browser would, but re-runs the full
    safety check (check_url: structural plus public-IP-only DNS) on EVERY
    hop, so a public destination cannot bounce the fetcher onto a
    private/internal address, and caps the hop count so a redirect loop
    cannot run forever. One instance per opener (one opener per fetch), so
    the hop counter never spans unrelated requests.

    The stock handler drains each intermediate redirect body with an
    unbounded fp.read() before following the hop; here that read is
    bounded (MAX_REDIRECT_BODY) and the intermediate response is always
    closed. before_hop, when given, runs before each hop is followed and
    may raise (the caller's own deadline check) to abort the fetch -
    mirrors careeros/intake.py's SafeRedirect."""

    def __init__(self, max_hops=MAX_REDIRECTS, before_hop=None):
        super().__init__()
        self.max_hops = max_hops
        self.hops = 0
        self.before_hop = before_hop

    def http_error_302(self, req, fp, code, msg, headers):
        try:
            fp.read(MAX_REDIRECT_BODY)
        finally:
            fp.close()
        if self.before_hop is not None:
            self.before_hop()
        return super().http_error_302(req, fp, code, msg, headers)

    # 308 (Permanent Redirect, method-preserving) matters here: the stock
    # handler aliases it to its unbounded 302 implementation, so omitting
    # it from this alias line would let 308 hops bypass the bounded drain,
    # the forced close, and the before_hop deadline check entirely.
    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.hops >= self.max_hops:
            raise ValueError('Too many redirects.')
        self.hops += 1
        target = urljoin(req.full_url, newurl)
        check_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def default_fetch(url, timeout=DEFAULT_TIMEOUT, max_hops=MAX_REDIRECTS, max_body=MAX_BODY_SIZE):
    """The safe default fetch adapter classify_sector/classify_size use
    when `fetch=` is omitted entirely (R2 - see the module docstring).
    Runs the fetch on a background thread so a hang before even the
    socket timeout engages (e.g. a slow DNS lookup) still cannot block the
    caller past `timeout` seconds."""
    deadline = time.monotonic() + timeout
    result = Queue(maxsize=1)

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError('Fetch deadline exceeded.')
        return seconds

    def worker():
        try:
            check_url(url)
            opener = request.build_opener(request.ProxyHandler({}), _SafeRedirect(max_hops, before_hop=remaining))
            req = request.Request(url, headers={'User-Agent': 'org-intake/1 default-fetch'})
            with opener.open(req, timeout=min(10, remaining())) as response:
                chunks, size = [], 0
                while size < max_body:
                    remaining()
                    chunk = response.read1(min(65536, max_body - size))
                    remaining()
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                result.put((True, b''.join(chunks).decode('utf-8', errors='replace')))
        except Exception as error:
            result.put((False, error))

    Thread(target=worker, daemon=True).start()
    try:
        success, value = result.get(timeout=timeout)
    except Empty as error:
        raise TimeoutError('Fetch deadline exceeded.') from error
    if not success:
        raise value
    return value
