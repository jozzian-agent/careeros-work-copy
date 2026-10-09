"""Suite-wide offline network guard."""
import pytest
from careeros import intake, server

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise RuntimeError('Network disabled by test fixture')
    monkeypatch.setattr(intake, 'fetch_url', blocked)
    monkeypatch.setattr('urllib.request.build_opener', blocked)
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('8.8.8.8', 443))])
    # JOZ-266 M7: the new-company enrichment cascade's default fetcher is
    # intake.fetch_url -- the same function most tests monkeypatch for
    # their own, unrelated posting-fetch mocking. Left enabled, a
    # background cascade thread would race an individual test's own mock
    # (or this fixture's `blocked` above) with no relation to what that
    # test is actually exercising. Off by default here; the one test that
    # exercises the cascade itself re-enables it explicitly.
    monkeypatch.setattr(server, 'AUTO_CASCADE_ENABLED', False)

