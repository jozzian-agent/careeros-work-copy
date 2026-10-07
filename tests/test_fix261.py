from threading import Event, current_thread
from unittest.mock import Mock

import pytest
from careeros import intake, ingest, vault
from careeros.server import create_app


@pytest.mark.parametrize('attribute', [
    'class="menu-planning-text"', 'id="header-of-department"',
    'class="navigation-systems-engineer"', 'class="share-your-experience"',
    'class="social-worker"', 'class="related-experience"',
])
def test_duties_survive_ambiguous_chrome_names(attribute):
    assert intake.extract('https://posting.example/job', f'<div {attribute}>Real job duties.</div>')['description'] == 'Real job duties.'


@pytest.mark.parametrize('tag', sorted(intake.VOID_TAGS))
def test_void_widget_cannot_hide_following_content(tag):
    parser = intake.Posting()
    parser.feed(f'<{tag} class="social-icon"><p>Real job duties.</p>')
    assert parser.hidden == 0
    assert 'Real job duties.' in ''.join(parser.text)


@pytest.mark.parametrize('html,expected', [
    ('<main><form></bogus>Secret</form><p>Real.</p></main>', 'Real.'),
    ('<nav><p>Menu</nav><p>Real job duties.</p>', 'Real job duties.'),
    ('<div>Build APIs.</div>Lead teams.', 'Build APIs.\nLead teams.'),
    ('<div>Select how often (in days) to receive an alert:</div><div>Create Alert</div><p>Build alert systems.</p>', 'Build alert systems.'),
])
def test_structural_and_edge_chrome(html, expected):
    assert intake.extract('https://posting.example/job', html)['description'] == expected


@pytest.mark.parametrize('text,expected', [
    ('We use agile methods.', 'We use agile methods.'),
    ('JavaScript engineer needed. Build services.', 'JavaScript engineer needed. Build services.'),
    ('Build services. We use cookies.', 'Build services.'),
])
def test_summary_filters_specific_notices_everywhere(text, expected):
    assert ingest.heuristic_extract(text)['summary'] == expected


def setup_refresh(tmp_path, monkeypatch):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/job',
        'original_url': 'https://source.example/job', 'description': 'Stored duties.',
        'summary': 'Polluted summary.', 'summary_source': 'ai'})
    app = create_app(tmp_path)
    callbacks = []
    monkeypatch.setattr(ingest, 'extract_async', lambda text, callback, **kwargs: callbacks.append((text, callback)) or Mock(is_alive=lambda: False))
    return job, app, app.test_client(), callbacks


def join_refresh(app, job):
    app.config['REFRESH_THREADS'][job['id']].join(2)
    assert not app.config['REFRESH_THREADS'][job['id']].is_alive()


def test_reserved_background_refresh_returns_without_waiting_and_pending_skips(tmp_path, monkeypatch):
    job, app, api, callbacks = setup_refresh(tmp_path, monkeypatch)
    entered, release = Event(), Event()
    calls = []
    def fetch(url):
        calls.append((url, current_thread().name, job['id'] in app.config['LLM_PENDING']))
        entered.set()
        assert release.wait(2)
        return '<p>Fresh duties.</p>'
    monkeypatch.setattr(intake, 'fetch_url', fetch)
    try:
        assert api.post('/api/jobs/' + job['id'] + '/extract').status_code == 202
        assert entered.wait(1)
        assert api.post('/api/jobs/' + job['id'] + '/extract').status_code == 202
        assert len(calls) == 1
        assert calls[0][1] != 'MainThread' and calls[0][2]
        assert vault.load_job(tmp_path, job['id'])['description'] == 'Stored duties.'
    finally:
        release.set()
        join_refresh(app, job)
    updated = vault.load_job(tmp_path, job['id'])
    assert updated['refresh'] == 'ok'
    assert any(e['event'] == 'description_refreshed' for e in updated['history'])
    assert callbacks[0][0] == 'Fresh duties.'


def test_refresh_failure_is_persisted_and_visible(tmp_path, monkeypatch):
    job, app, api, callbacks = setup_refresh(tmp_path, monkeypatch)
    api.post('/api/jobs/' + job['id'] + '/extract')
    join_refresh(app, job)
    updated = vault.load_job(tmp_path, job['id'])
    assert updated['refresh'] == 'failed'
    assert any(e['event'] == 'description_refresh_failed' for e in updated['history'])
    assert callbacks[0][0] == 'Stored duties.'
    assert 'Live page unavailable — enriched stored text' in api.get('/jobs/' + job['id']).text


@pytest.mark.parametrize('when', ['fetch', 'callback'])
def test_original_url_change_rejects_stale_results(tmp_path, monkeypatch, when):
    job, app, api, callbacks = setup_refresh(tmp_path, monkeypatch)
    def change():
        vault.save_job(tmp_path, {'original_url': 'https://new.example/job'}, job['id'])
    def fetch(url):
        if when == 'fetch':
            change()
        return '<p>Fresh duties.</p>'
    monkeypatch.setattr(intake, 'fetch_url', fetch)
    api.post('/api/jobs/' + job['id'] + '/extract')
    join_refresh(app, job)
    if when == 'fetch':
        assert not callbacks
        assert vault.load_job(tmp_path, job['id'])['description'] == 'Stored duties.'
    else:
        change()
        callbacks[0][1]({'summary': 'Stale summary.'})
    assert vault.load_job(tmp_path, job['id'])['summary'] == 'Polluted summary.'
    assert job['id'] not in app.config['LLM_PENDING']


@pytest.mark.parametrize('fields,owner,expected,source', [
    ({'summary': ''}, False, '', ''),
    ({'summary': '  '}, False, '', ''),
    ({'skills': ['Python']}, False, 'Polluted summary.', 'ai'),
    ({'summary': ''}, True, 'Owner summary.', ''),
])
def test_empty_and_absent_summary_preserve_owner_edits(tmp_path, monkeypatch, fields, owner, expected, source):
    job, app, api, callbacks = setup_refresh(tmp_path, monkeypatch)
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<p>Fresh duties.</p>')
    api.post('/api/jobs/' + job['id'] + '/extract')
    join_refresh(app, job)
    if owner:
        api.put('/api/jobs/' + job['id'], json={'summary': 'Owner summary.'})
    callbacks[0][1](fields)
    updated = vault.load_job(tmp_path, job['id'])
    assert (updated['summary'], updated['summary_source']) == (expected, source)
