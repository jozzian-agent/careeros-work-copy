"""Polite HTTP for the seeding scripts: one user agent, one rate limit,
one robots.txt check.

Shared by `seed_zefix_zurich.py` and `ats_overview.py`, which are the two
things in this repo that talk to hosts nobody here owns. It exists so the
politeness rules are stated once instead of twice:

  * `USER_AGENT` identifies CareerOS and carries a contact, per CAREER-19
    M2-1's wording.
  * `RateLimiter` keeps at least `min_interval` seconds between requests
    from one run (default 1.0, so never more than one request a second).
  * `robots_allows` answers whether a URL is fetchable for our agent,
    caching one robots.txt per host so a 500-domain sweep fetches each
    host's robots once.

This is the smallest shape of what CAREER-19 M2-1 asks for as one shared
element, built here because these two scripts need it now. When M2-1
lands its product-side fetcher beside `careeros.intake.fetch_url`, this
module is what it absorbs: delete it and point both scripts at that.

`request_text` is NOT a fourth fetcher by choice. `org_intake.fetch.
default_fetch` already carries every guard that matters (public-IP-only
DNS check, per-hop revalidation, bounded hops, body cap, proxies off) and
this module reuses its `check_url` for exactly that. The one thing it
cannot do is send our user agent: `default_fetch` hard-codes
`org-intake/1 default-fetch` and takes no header argument, and teaching
it one would edit the pinned capability and move the pin, which is a
wider decision than a seeding ticket makes. So the opener below is
`default_fetch` minus that single line, and it should be revisited the
moment either the capability's fetch takes a user agent or M2-1's
fetcher exists.

Nothing here raises on a bad response: a caller sweeping hundreds of
unrelated hosts wants a result it can count, so every failure comes back
as `ok=False` with a short reason (PROJECT.md: failures are visible
states with a reason, never silent).
"""
import time
import urllib.robotparser
from urllib import error as urlerror, request
from urllib.parse import urljoin, urlsplit

from org_intake.fetch import MAX_BODY_SIZE, MAX_REDIRECTS, check_url

# CAREER-19 M2-1: a user agent that says who is calling and how to reach
# the person responsible. The contact is deliberately the word "owner"
# until the owner decides which address to publish -- a placeholder is
# better than a guessed mailbox (AGENTS.md: never invent a field).
USER_AGENT = 'CareerOS/0.x (+contact: owner)'

DEFAULT_MIN_INTERVAL = 1.0
DEFAULT_TIMEOUT = 20


class RateLimiter:
    """At least `min_interval` seconds between `wait()` calls.

    `sleep` and `now` are injected so a test can drive the clock instead
    of spending real seconds, and so the test can assert on what was
    slept rather than on wall time.
    """

    def __init__(self, min_interval=DEFAULT_MIN_INTERVAL, *, sleep=time.sleep, now=time.monotonic):
        self.min_interval = max(0.0, float(min_interval))
        self._sleep = sleep
        self._now = now
        self._last = None
        self.requests = 0
        self.slept = 0.0

    def wait(self):
        """Block until the next request is allowed. Returns the seconds
        actually slept, which is 0.0 for the first call of a run."""
        slept = 0.0
        if self._last is not None and self.min_interval:
            slept = self.min_interval - (self._now() - self._last)
            if slept > 0:
                self._sleep(slept)
            else:
                slept = 0.0
        self._last = self._now()
        self.requests += 1
        self.slept += slept
        return slept


class _SafeRedirect(request.HTTPRedirectHandler):
    """Re-runs `check_url` on every hop and caps the hop count, so a
    public destination cannot bounce the fetch onto a private address and
    a redirect loop cannot run forever. One instance per opener, so the
    counter never spans two requests."""

    def __init__(self, max_hops=MAX_REDIRECTS):
        super().__init__()
        self.max_hops = max_hops
        self.hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.hops >= self.max_hops:
            raise ValueError('Too many redirects.')
        self.hops += 1
        target = urljoin(req.full_url, newurl)
        check_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def request_text(url, *, data=None, headers=None, timeout=DEFAULT_TIMEOUT,
                 max_body=MAX_BODY_SIZE, limiter=None):
    """One GET (or POST, when `data` is given) with our user agent.

    Returns a dict that is always the same shape:

        {'ok': bool, 'status': int|None, 'text': str,
         'final_url': str, 'error': str|None}

    `final_url` is where the response actually came from after redirects,
    which is itself ATS evidence: a company careers link that 302s to
    boards.greenhouse.io says more than the link did.
    """
    if limiter is not None:
        limiter.wait()
    sent = {'User-Agent': USER_AGENT}
    sent.update(headers or {})
    blank = {'ok': False, 'status': None, 'text': '', 'final_url': url}
    try:
        check_url(url)
        opener = request.build_opener(request.ProxyHandler({}), _SafeRedirect())
        with opener.open(request.Request(url, data=data, headers=sent), timeout=timeout) as response:
            body = response.read(max_body)
            charset = response.headers.get_content_charset() or 'utf-8'
            return {'ok': True, 'status': response.status,
                    'text': body.decode(charset, errors='replace'),
                    'final_url': response.geturl(), 'error': None}
    except urlerror.HTTPError as error:
        # A 4xx/5xx is an answer, not a crash: keep the status so a
        # caller can tell "no careers page" from "host unreachable".
        return {**blank, 'status': error.code, 'error': f'HTTP {error.code}'}
    except Exception as error:
        return {**blank, 'error': f'{type(error).__name__}: {error}'.strip()[:200]}


def robots_allows(url, *, cache=None, limiter=None, fetch=None):
    """Whether robots.txt lets our agent fetch `url`.

    Returns `(allowed, reason)`, where the reason reads as a clause a
    report can print as it stands: "disallowed by robots.txt", "no
    robots.txt (HTTP 404)", "robots.txt unreadable (...)".

    A missing or 4xx robots.txt means no restriction, which is the
    convention. A 5xx or an unreachable host means "assume not allowed":
    a sweep that cannot read the rules should not guess in its own
    favour. `cache` is a caller-owned dict so one host's robots.txt is
    fetched once per run.
    """
    cache = cache if cache is not None else {}
    fetch = fetch or request_text
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return False, 'not an http(s) URL'
    origin = f'{parts.scheme}://{parts.netloc}'
    if origin not in cache:
        result = fetch(f'{origin}/robots.txt', limiter=limiter)
        if result['ok']:
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(result['text'].splitlines())
            cache[origin] = (parser, 'robots.txt')
        elif result['status'] and 400 <= result['status'] < 500:
            cache[origin] = (None, f"no robots.txt (HTTP {result['status']})")
        else:
            cache[origin] = (False, f"robots.txt unreadable ({result['error']})")
    parser, reason = cache[origin]
    if parser is None:
        return True, reason
    if parser is False:
        return False, reason
    if parser.can_fetch(USER_AGENT, url):
        return True, 'allowed by robots.txt'
    return False, 'disallowed by robots.txt'
