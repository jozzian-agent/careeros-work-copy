"""Suite-wide offline network guard and signed-in client."""
import pytest
from careeros import intake, server, users

# M1: every page and every API call needs a session now. The suite's
# existing tests are about records and not about the door, so one autouse
# fixture signs all of them in rather than every test file growing a
# login step. It replaces the one function the gate reads, so no test
# needs a cookie, a secret key or a user record in its own vault, and no
# test client had to change.
#
# The tests that are about the door itself take `raw_session`, which puts
# the real loader back and drives the real cookie path end to end.
# Identity and the one field the gate reads, and no credential of any
# kind: nothing here signs a cookie or checks a password, because the
# function this replaces is the one that has already done both.
SUITE_USER = {'id': 'USER-001', 'email': 'suite@careeros.test', 'name': 'Suite',
              'role': 'admin', 'disabled': False}
_REAL_SESSION_USER = users.session_user


#
# Both fixtures below hold their own MonkeyPatch rather than the shared
# `monkeypatch` fixture: a test that calls monkeypatch.undo() mid-test to
# drop its own patch would otherwise sign itself out halfway through.
@pytest.fixture(autouse=True)
def signed_in():
    patcher = pytest.MonkeyPatch()
    patcher.setattr(users, 'session_user', lambda root: SUITE_USER)
    yield SUITE_USER
    patcher.undo()


@pytest.fixture
def raw_session():
    """Undo `signed_in` for a test that exercises the gate itself."""
    patcher = pytest.MonkeyPatch()
    patcher.setattr(users, 'session_user', _REAL_SESSION_USER)
    yield
    patcher.undo()

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise RuntimeError('Network disabled by test fixture')
    monkeypatch.setattr(intake, 'fetch_url', blocked)
    monkeypatch.setattr(intake, 'fetch_url_follow', blocked)
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



def post_ai(client, path, *, timeout=30.0):
    """POST to one of the async AI endpoints and wait for its queued work.

    CAREER-36: /enrich, /extract, /re-extract and the company /enrich all
    answer 202 with the queued status and do the work on the AI queue, so
    a test that wants to see the outcome reads it off the record after
    this returns, never out of the response body. Returns the response so
    a caller can still assert on the status code it got.
    """
    response = client.post(path)
    assert client.application.config['AI_QUEUE'].drain(timeout), (
        'the AI queue did not finish inside the timeout')
    return response


def write_legacy_size_range(root, company_id, size_range):
    """Put a numeric `size_range` on a stored company, the way a vault
    written before the size scale was settled still holds one.

    `vault.save_company` refuses to persist a range now (owner decision
    2026-10-15: the class is the only size scale), so a test that needs
    the records the consistency guards and the retirement migration exist
    for has to write the YAML the old path left behind. Returns the
    reloaded record."""
    import yaml
    from pathlib import Path
    from careeros import vault

    path = next(Path(root, 'companies').glob(f'*-{company_id.lower()}.yaml'))
    data = yaml.safe_load(path.read_text())
    data['size_range'] = size_range
    path.write_text(yaml.safe_dump(data))
    return vault.load_company(root, company_id)


@pytest.fixture
def api_client(tmp_path):
    """Isolated page-contract records, using the suite's offline guard."""
    import shutil
    from pathlib import Path
    from careeros import vault

    root = tmp_path / 'vault'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'sample' / 'vault', root)
    app = server.create_app(root)
    posting_url = vault.list_jobs(root)[0]['url']
    for collection in ('jobs', 'companies', 'experiences'):
        for record in (root / collection).glob('*.yaml'):
            record.unlink()
    tags = vault.default_tags()
    tags['facets']['function']['values'] = [
        {'id': 'builder', 'label': 'Builder', 'source': 'local-extension'}]
    vault.save_tags(root, tags)
    company = vault.save_company(root, {
        'name': 'Contract Studio', 'sectors': ['J'], 'size_class': 'small',
        'locations': ['Zurich'], 'notes': 'Owner notes',
        'review_flags': ['sector-ambiguous'],
    })
    job = vault.save_job(root, {
        'title': 'Contract Builder', 'url': posting_url, 'company_id': company['id'],
        'company_link_state': 'needs_review', 'location': 'Zurich',
        'description': 'Original source text', 'summary': 'Generated summary',
        'summary_source': 'ai', 'notes': '**Owner notes**', 'function': ['builder'],
        'tags': ['function:builder'],
        'ingest_state': 'extract_failed',
        'ingest_error': {'stage': 'extract', 'reason': 'empty_content', 'at': '2026-10-10'},
    })
    exp = vault.save_experience(root, {
        'title': 'Earlier Builder', 'company': 'Frozen label',
        'company_id': company['id'], 'start': '2024-01', 'end': 'present',
        'detail': '**Career story**', 'highlights': ['Built things'],
        'tags': ['function:builder'],
    })
    app.config['CONTRACT_IDS'] = (job['id'], company['id'], exp['id'])
    return app.test_client()


@pytest.fixture
def assert_json_shape():
    """Assert exact object keys and JSON types recursively."""
    def check(value, shape):
        if isinstance(shape, dict):
            assert type(value) is dict
            assert sorted(value) == sorted(shape)
            for key, expected in shape.items():
                check(value[key], expected)
        elif isinstance(shape, list):
            assert type(value) is list
            if shape:
                for item in value:
                    check(item, shape[0])
            else:
                assert value == []
        else:
            assert type(value).__name__ == shape
    return check
