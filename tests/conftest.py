"""Suite-wide offline network guard."""
import pytest
from careeros import intake

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise RuntimeError('Network disabled by test fixture')
    monkeypatch.setattr(intake, 'fetch_url', blocked)
    monkeypatch.setattr('urllib.request.build_opener', blocked)
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('8.8.8.8', 443))])

