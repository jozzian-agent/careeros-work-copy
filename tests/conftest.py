"""Suite-wide offline network guard."""
import pytest
from careeros import intake, server

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
