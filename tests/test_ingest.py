"""Offline structured ingestion contracts."""
import json
from time import monotonic
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import yaml

from careeros import ingest, intake, llm_client, vault
from careeros.server import SHARED_ATS_HOSTS, create_app


# Synthetic documentation endpoint (RFC 5737), never real infrastructure.
SYNTHETIC_ENDPOINT = 'http://192.0.2.5:9999'


@pytest.fixture(autouse=True)
def no_configuration(monkeypatch):
    for key in ('LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL'):
        monkeypatch.delenv(key, raising=False)


def client_for(content=None, error=None):
    create = Mock(side_effect=error, return_value=SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(content=content))]))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.mark.parametrize('fenced', [False, True])
def test_response_normalization(fenced):
    content = json.dumps(dict(title=123, company=None, location=456,
                             remote_ok='false', employment_type=789,
                             seniority=0, keywords=['Python', 42, None, 'Python'],
                             summary=123, ignored='discard'))
    if fenced:
        content = '```json\n' + content + '\n```'
    parsed = ingest.parse_response(content)
    assert parsed == dict(title='123', location='456', remote_ok=False,
                          employment_type='789', seniority='0',
                          keywords=['Python', '42'], summary='123')


@pytest.mark.parametrize('content', ['broken', '[]', 'null', '{}', '{"remote_ok":"maybe"}'])
def test_invalid_response(content):
    with pytest.raises(ValueError):
        ingest.parse_response(content)


@pytest.mark.parametrize('value,expected', [(True, True), (False, False), ('true', True),
                                          ('no', False), (0, False), (1, True)])
def test_remote_bool(value, expected):
    assert ingest.parse_response(json.dumps({'remote_ok': value}))['remote_ok'] is expected


def test_llm_request_and_result():
    client = client_for('```json\n{"title":"Senior Engineer","remote_ok":true}\n```')
    model = object()
    result = ingest.extract('Role: Engineer\nPython skills.', client=client, model=model)
    assert result['ingest_source'] == 'llm'
    assert result['title'] == 'Senior Engineer'
    assert result['remote_ok'] is True
    assert result['keywords'] == ['Python']
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs['model'] is model
    assert kwargs['temperature'] == 0
    assert kwargs['response_format'] == {'type': 'json_object'}
    assert kwargs['think'] is False
    assert kwargs['timeout'] == 120
    assert kwargs['messages'] == ingest.build_prompt('Role: Engineer\nPython skills.')
    assert 'No commentary, no markdown fences' in kwargs['messages'][0]['content']


@pytest.mark.parametrize('client', [client_for('not json'), client_for(error=TimeoutError()),
                                    client_for(error=RuntimeError())])
def test_errors_fall_back(client):
    result = ingest.extract('Senior Engineer at Example Labs\nRemote\nPython.',
                            client=client, model=object())
    assert result['ingest_source'] == 'heuristic'
    assert result['company'] == 'Example Labs'
    assert result['seniority'] == 'senior'


def test_unconfigured_fallback():
    assert ingest.extract('Engineer')['ingest_source'] == 'heuristic'


def test_total_deadline(monkeypatch):
    release = Event()
    client = client_for()
    client.chat.completions.create.side_effect = lambda **kwargs: release.wait(2)
    monkeypatch.setattr(ingest, 'TIMEOUT', .02)
    try:
        started = monotonic()
        assert ingest.extract('Engineer', client=client, model=object())['ingest_source'] == 'heuristic'
        assert monotonic() - started < 1.0
        assert not release.is_set()
    finally:
        release.set()


@pytest.mark.parametrize('layout,expected', [
    ('<h1>Senior Engineer at Example Labs</h1><p>Location: Remote</p>'
     '<p>Full-time</p><p>Build services with Python and SQL.</p>',
     dict(title='Senior Engineer', company='Example Labs', location='Remote',
          employment_type='full-time', seniority='senior', remote_ok=True)),
    ('<h1>Job title: Junior Analyst</h1><div>Company: Example Studio</div>'
     '<div>Location: Berlin</div><h2>Employment type</h2><p>Part time</p>'
     '<p>On-site only. Use Excel and SQL.</p>',
     dict(title='Junior Analyst', company='Example Studio', location='Berlin',
          employment_type='part-time', seniority='junior', remote_ok=False)),
])
def test_ats_description_shapes(layout, expected):
    posting = intake.Posting()
    posting.feed(layout)
    result = ingest.heuristic_extract('\n'.join(posting.text))
    for key, value in expected.items():
        assert result[key] == value
    assert 'SQL' in result['keywords']
    assert result['summary']
    posting = intake.ingest_posting('https://posting.example/role', layout)
    for key, value in expected.items():
        assert posting[key] == value


def test_configuration_required():
    with pytest.raises(RuntimeError, match='LLM_BASE_URL'):
        llm_client.get_llm_client()
    with pytest.raises(RuntimeError, match='LLM_MODEL'):
        llm_client.get_llm_model()


def test_transport_runtime_configuration(monkeypatch):
    # Generate opaque configuration values so fixtures record no deployment names.
    base = 'https://' + uuid4().hex + '.invalid/v1'
    model = uuid4().hex
    monkeypatch.setenv('LLM_BASE_URL', base)
    monkeypatch.setenv('LLM_MODEL', model)
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"choices":[{"message":{"content":"{}"}}]}'
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(llm_client.request, 'build_opener', lambda *args: opener)
    client = llm_client.get_llm_client()
    assert client.api_key == 'not-needed'
    client.chat.completions.create(model=llm_client.get_llm_model(), messages=[], timeout=30)
    req = opener.open.call_args.args[0]
    assert req.full_url == base + '/chat/completions'
    assert json.loads(req.data)['model'] == model
    assert opener.open.call_args.kwargs['timeout'] == 30
    monkeypatch.setenv('LLM_API_KEY', uuid4().hex)
    assert llm_client.get_llm_client().api_key != 'not-needed'


@pytest.mark.parametrize('use_llm', [False, True])
def test_intake_persists_fields(tmp_path, monkeypatch, use_llm):
    description = 'Senior Engineer at Example Labs\nLocation: Remote\nFull-time. Build Python services.'
    html = '<script type="application/ld+json">' + json.dumps({
        '@type': 'JobPosting', 'title': 'Senior Engineer',
        'hiringOrganization': {'name': 'Example Labs'}, 'description': description,
    }) + '</script>'
    monkeypatch.setattr(intake, 'fetch_url', lambda url: html)
    if use_llm:
        monkeypatch.setattr(ingest, 'get_llm_client', lambda: client_for(json.dumps({
            'title': 'Lead Engineer', 'company': 'Example Labs', 'location': 'Remote',
            'employment_type': 'full-time', 'seniority': 'lead', 'remote_ok': True,
            'keywords': ['Python'], 'summary': 'Build Python services.',
        })))
        monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    app.testing = True
    api = app.test_client()
    response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
    assert response.status_code == 201
    job = response.json['job']
    assert job['description'] == description
    assert job['company'] == 'Example Labs'
    assert job['remote_ok'] is True
    assert job['keywords'] == ['Python']
    # The response always reflects the instant heuristic pass; the LLM result
    # (if any) only lands once the background thread below has been joined.
    assert job['seniority'] == 'senior'
    assert job['ingest_source'] == 'heuristic'
    assert job['source'] == 'posting.example'
    app.config['LLM_THREADS'][job['id']].join(timeout=2)
    enriched = api.get('/api/jobs/' + job['id']).json
    assert enriched['llm_pending'] is False
    assert enriched['seniority'] == ('lead' if use_llm else 'senior')
    assert enriched['ingest_source'] == ('llm' if use_llm else 'heuristic')
    path = next((tmp_path / 'jobs').glob('*.yaml'))
    stored = yaml.safe_load(path.read_text())
    stored['future_field'] = {'nested': [1, 2]}
    path.write_text(yaml.safe_dump(stored))
    updated = api.put('/api/jobs/' + job['id'], json={'notes': 'Owner note.'})
    assert updated.status_code == 200
    assert updated.json['future_field'] == {'nested': [1, 2]}
    assert updated.json['description'] == description
    assert updated.json['keywords'] == ['Python']
    assert api.get('/jobs/' + job['id']).status_code == 200


def test_enrichment_legacy_job(tmp_path, monkeypatch):
    job = vault.save_job(tmp_path, {'title': 'Owner title', 'url': 'https://posting.example/role',
                                    'remote_ok': False})
    monkeypatch.setattr(intake, 'fetch_url', lambda url:
                        '<h1>Senior Engineer at Example Labs</h1><p>Remote. Python.</p>')
    api = create_app(tmp_path).test_client()
    response = api.post('/api/jobs/' + job['id'] + '/enrich')
    assert response.status_code == 200
    assert response.json['title'] == 'Owner title'
    assert response.json['remote_ok'] is False
    assert response.json['description']
    assert response.json['keywords'] == ['Python']
    assert response.json['ingest_source'] == 'heuristic'


@pytest.mark.parametrize('values', [{'keywords': 'Python'}, {'keywords': [1]},
                                   {'ingest_source': 'invalid'}, {'summary': 42}])
def test_vault_validates_structured_fields(tmp_path, values):
    with pytest.raises(ValueError):
        vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'} | values)


@pytest.mark.parametrize('content', [
    '```json {"title":"Engineer"}```',
    '```{"title":"Engineer"}```',
    '  ```JSON\n{"title":"Engineer"}```  ',
    '```\n{"title":"Engineer"}\n```',
])
def test_enclosing_fences(content):
    assert ingest.parse_response(content) == {'title': 'Engineer'}


def test_description_prompt_cap():
    description = 'x' * (ingest.MAX_DESCRIPTION_CHARS + 10_000)
    client = client_for('{"title":"Engineer"}')
    ingest.extract(description, client=client, model=object())
    messages = client.chat.completions.create.call_args.kwargs['messages']
    overhead = len(ingest.build_prompt('')[1]['content'])
    assert len(messages[1]['content']) == overhead + ingest.MAX_DESCRIPTION_CHARS
    assert messages == ingest.build_prompt(description[:ingest.MAX_DESCRIPTION_CHARS])


@pytest.mark.parametrize('region', ['main', 'article', 'body'])
def test_description_content_region(region):
    html = '<title>Site title</title><nav>Navigation</nav>'
    html += f'<{region}><h1>Engineer</h1><p>Python services.</p></{region}>'
    html += '<footer>Cookie preferences</footer>'
    assert intake.extract('https://posting.example/role', html)['description'] == 'Engineer\nPython services.'


def test_intake_parses_page_once(monkeypatch):
    html = '<title>Engineer</title><main>Python services.</main>'
    original_feed = intake.Posting.feed
    feeds = []
    def feed(self, content):
        feeds.append(content)
        return original_feed(self, content)
    original_schema = intake.job_schema
    schema = Mock(wraps=original_schema)
    monkeypatch.setattr(intake.Posting, 'feed', feed)
    monkeypatch.setattr(intake, 'job_schema', schema)
    assert intake.ingest_posting('https://posting.example/role', html)['title'] == 'Engineer'
    assert feeds.count(html) == 1
    assert schema.call_count == 1


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_transport_redirect_fails_closed(status, offline, monkeypatch):
    from email.message import Message
    from io import BytesIO
    from urllib.response import addinfourl

    # Restore the real opener factory hidden by the suite fixture.
    monkeypatch.undo()
    def blocked_connection(*args, **kwargs):
        raise AssertionError('Unexpected network connection')
    monkeypatch.setattr('socket.create_connection', blocked_connection)
    monkeypatch.setattr(llm_client.request, 'getproxies', lambda: {})
    requests = []
    class ControlledHTTP(llm_client.request.HTTPHandler):
        handler_order = 100

        def http_open(self, req):
            requests.append(req)
            headers = Message()
            headers['Location'] = 'http://redirect.example/target'
            response = addinfourl(BytesIO(b''), headers, req.full_url, status)
            response.msg = 'Redirect'
            return response

    client = llm_client.LLMClient('http://origin.example/v1', uuid4().hex)
    opener = client.opener
    opener.add_handler(ControlledHTTP())
    for _ in range(2):
        with pytest.raises(RuntimeError, match='redirects are disabled'):
            client.create(messages=[])
    assert client.opener is opener
    assert len(requests) == 2
    assert all(req.full_url == 'http://origin.example/v1/chat/completions' for req in requests)
    assert all(req.get_header('Authorization') == 'Bearer ' + client.api_key for req in requests)


@pytest.mark.parametrize('failure', ['malformed', 'timeout'])
def test_intake_failure_persists_description(tmp_path, monkeypatch, failure):
    description = 'Engineer at Example Labs\nBuild Python services.'
    html = '<main>' + description + '</main>'
    monkeypatch.setattr(intake, 'fetch_url', lambda url: html)
    client = client_for('invalid json')
    release = Event()
    if failure == 'timeout':
        client.chat.completions.create.side_effect = lambda **kwargs: release.wait(.1)
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client)
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    try:
        app = create_app(tmp_path)
        app.testing = True
        api = app.test_client()
        response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
        assert response.status_code == 201
        job_id = response.json['job']['id']
        app.config['LLM_THREADS'][job_id].join(timeout=2)
        path = next((tmp_path / 'jobs').glob('*.yaml'))
        stored = yaml.safe_load(path.read_text())
        assert stored['description'] == description
        assert stored['ingest_source'] == 'heuristic'
        client.chat.completions.create.assert_called_once()
    finally:
        release.set()


def test_llm_timeout_env_default(monkeypatch):
    monkeypatch.delenv('LLM_TIMEOUT', raising=False)
    assert ingest.get_timeout() == ingest.TIMEOUT


def test_llm_timeout_env_honored(monkeypatch):
    monkeypatch.setenv('LLM_TIMEOUT', '7.5')
    assert ingest.get_timeout() == 7.5
    client = client_for('{"title":"Engineer"}')
    ingest.extract('Engineer role', client=client, model=object())
    assert client.chat.completions.create.call_args.kwargs['timeout'] == 7.5


def test_llm_timeout_env_ignores_garbage(monkeypatch):
    monkeypatch.setenv('LLM_TIMEOUT', 'not-a-number')
    assert ingest.get_timeout() == ingest.TIMEOUT


def test_llm_failure_logs_class_name_only(capsys):
    client = client_for(error=RuntimeError('token=super-secret at ' + SYNTHETIC_ENDPOINT))
    result = ingest.extract('Engineer at Example Labs', client=client, model=object())
    assert result['ingest_source'] == 'heuristic'
    err = capsys.readouterr().err
    assert err.count('\n') == 1
    assert 'RuntimeError' in err
    assert 'secret' not in err and SYNTHETIC_ENDPOINT not in err


@pytest.mark.parametrize('text,expected', [
    ('Contact us at jobs@acme-labs.example for details.', 'jobs@acme-labs.example'),
    ('Apply via jobs@example.com today.', ''),
    ('Background sprite logo@2x.png used in header.', ''),
    ('Errors reported to oops@sentry.io, ignore.', ''),
    ('No email address appears in this text.', ''),
])
def test_contact_email_regex(text, expected):
    assert ingest.find_contact_email(text) == expected
    assert ingest.heuristic_extract(text)['contact_email'] == expected


def test_find_mailto_prefers_explicit_link():
    html = '<a href="mailto:jobs@acme.example?subject=Role">Email us</a>'
    assert intake.find_mailto(html) == 'jobs@acme.example'


def test_find_mailto_excludes_placeholder_domain():
    html = '<a href="mailto:jobs@example.com">Email</a>'
    assert intake.find_mailto(html) == ''


def test_find_mailto_absent():
    assert intake.find_mailto('<p>No link here.</p>') == ''


def test_heuristic_posting_mailto_overrides_text_guess(monkeypatch):
    html = ('<main>Role description. Reach recruiter@guess.example for questions.</main>'
            '<a href="mailto:jobs@acme.example">Apply</a>')
    data = intake.heuristic_posting('https://acme.example/role', html)
    assert data['contact_email'] == 'jobs@acme.example'


def test_company_contact_email_fill(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Acme'})
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://acme.example/job',
                                    'company_id': company['id'], 'contact_email': 'jobs@acme.example'})
    assert vault.load_company(tmp_path, company['id'])['contact_email'] == 'jobs@acme.example'
    vault.save_job(tmp_path, {'contact_email': 'other@acme.example'}, job['id'])
    assert vault.load_company(tmp_path, company['id'])['contact_email'] == 'jobs@acme.example'


def test_intake_matches_company_by_netloc(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Role One</title>')
    app = create_app(tmp_path)
    app.testing = True
    api = app.test_client()
    first = api.post('/api/jobs/intake', json={'url': 'https://jobs.acme-careers.example/role-one'}).json
    cid = first['company']['id']
    assert vault.load_company(tmp_path, cid)['website'] == 'https://jobs.acme-careers.example'
    monkeypatch.setattr(intake, 'fetch_url', lambda url:
                        '<meta property="og:site_name" content="Totally Different Name">')
    second = api.post('/api/jobs/intake', json={'url': 'https://jobs.acme-careers.example/role-two'}).json
    assert second['company']['id'] == cid


def test_llm_pending_lifecycle(tmp_path, monkeypatch):
    release = Event()
    client = client_for('{"title":"Lead Engineer"}')

    def slow_create(**kwargs):
        release.wait(2)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"title":"Lead Engineer"}'))])
    client.chat.completions.create.side_effect = slow_create
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Engineer</title><main>Role text.</main>')
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client)
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    app.testing = True
    api = app.test_client()
    try:
        job_id = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'}).json['job']['id']
        assert api.get('/api/jobs/' + job_id).json['llm_pending'] is True
        release.set()
        app.config['LLM_THREADS'][job_id].join(timeout=2)
        assert api.get('/api/jobs/' + job_id).json['llm_pending'] is False
    finally:
        release.set()


def test_async_llm_update_respects_owner_edit(tmp_path, monkeypatch):
    release = Event()
    client = client_for()

    def slow_create(**kwargs):
        release.wait(2)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(
            {'title': 'LLM Title', 'seniority': 'lead', 'summary': 'LLM summary.'})))])
    client.chat.completions.create.side_effect = slow_create
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Engineer</title><main>Role at Example.</main>')
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client)
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    app.testing = True
    api = app.test_client()
    try:
        job_id = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'}).json['job']['id']
        assert api.put('/api/jobs/' + job_id, json={'title': 'Owner Title'}).status_code == 200
        release.set()
        app.config['LLM_THREADS'][job_id].join(timeout=2)
        job = api.get('/api/jobs/' + job_id).json
        assert job['title'] == 'Owner Title'
        assert job['summary'] == 'LLM summary.'
        assert job['ingest_source'] == 'llm'
    finally:
        release.set()


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf', '-inf', 'garbage'])
def test_timeout_rejects_nonpositive_nonfinite(value, monkeypatch, capsys):
    monkeypatch.setenv('LLM_TIMEOUT', value)
    assert ingest.get_timeout() == ingest.TIMEOUT
    assert capsys.readouterr().err == 'ingest: ValueError\n'


@pytest.mark.parametrize('value', [
    '.'.join(['10', '1', '2', '3']),
    '.'.join(['172', '16', '2', '3']),
    '.'.join(['172', '31', '2', '3']),
    '.'.join(['192', '168', '2', '3']),
    '.'.join(['169', '254', '2', '3']),
    'worker.internal' + ':' + '9876',
    *ingest.PROVIDER_MODEL_BLOCKLIST,
])
def test_redaction_all_extracted_strings(value):
    assert ingest.redact('prefix ' + value + ' suffix') == ''
    result = ingest.parse_response(json.dumps({'title': value, 'keywords': ['Python', value]}))
    assert result == {'title': '', 'keywords': ['Python']}
    assert ingest.heuristic_extract('Company: ' + value)['company'] == ''
    html = '<meta property="og:site_name" content="' + value + '">'
    assert intake.heuristic_posting('https://safe.example/job', html)['company'] == ''


@pytest.mark.parametrize('email', ['invalid', 'jobs@example.com', 'logo@2x.png', 'oops@sentry.io'])
def test_llm_contact_email_validation(email):
    assert ingest.parse_response(json.dumps({'contact_email': email}))['contact_email'] == ''


def test_find_mailto_continues_after_invalid():
    html = ''.join('<a href="mailto:' + value + '">Email</a>' for value in
                   ['invalid', 'jobs@example.com', 'logo@2x.png', 'jobs@valid.example'])
    assert intake.find_mailto(html) == 'jobs@valid.example'


@pytest.mark.parametrize('url', ['https://WWW.Acme.Example.:443/path', 'http://acme.example:80/a'])
def test_netloc_normalization(url):
    from careeros.server import _netloc
    assert _netloc(url) == 'acme.example'


@pytest.mark.parametrize('host', SHARED_ATS_HOSTS)
def test_shared_ats_tenant_keys(host):
    from careeros.server import _company_url_key, _company_website
    first = 'https://jobs.' + host + '/Alpha/role'
    assert _company_url_key(first) == _company_url_key('https://jobs.' + host + '/alpha/other')
    assert _company_url_key(first) != _company_url_key('https://jobs.' + host + '/beta/role')
    assert _company_website(first) is None


def test_ats_tenant_split_and_existing_path_match(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, 'extract_async', lambda *args: Mock(is_alive=lambda: False))
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Engineer</title>')
    existing = vault.save_company(tmp_path, {'name': 'Existing tenant', 'website': 'https://jobs.lever.co/ALPHA'})
    api = create_app(tmp_path).test_client()
    first = api.post('/api/jobs/intake', json={'url': 'https://jobs.lever.co/alpha/one'}).json
    second = api.post('/api/jobs/intake', json={'url': 'https://jobs.lever.co/beta/two'}).json
    third = api.post('/api/jobs/intake', json={'url': 'https://jobs.lever.co/BETA/three'}).json
    assert first['company']['id'] == existing['id']
    assert second['company']['id'] != existing['id']
    assert second['company']['website'] is None
    assert third['company']['id'] == second['company']['id']


def capture_intake(tmp_path, monkeypatch):
    callbacks = []
    monkeypatch.setattr(intake, 'fetch_url', lambda url:
                        '<title>Engineer</title><main>Location: Basel\nCompany: Initial Labs</main>')
    def start(description, callback):
        callbacks.append(callback)
        return Mock(is_alive=lambda: False)
    monkeypatch.setattr(ingest, 'extract_async', start)
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
    assert response.status_code == 201
    return app, api, response.json['job'], callbacks[0]


def test_async_owner_clear_and_success_flag(tmp_path, monkeypatch):
    app, api, baseline, callback = capture_intake(tmp_path, monkeypatch)
    assert baseline['location']
    api.put('/api/jobs/' + baseline['id'], json={'location': ''})
    callback({'location': 'London', 'summary': 'Useful summary.'})
    job = api.get('/api/jobs/' + baseline['id']).json
    assert job['location'] == ''
    assert job['summary'] == 'Useful summary.'
    assert job['enriched'] is True
    assert job['llm_pending'] is False
    assert app.config['LLM_THREADS'] == {}


def test_async_url_change_discards_entire_result(tmp_path, monkeypatch):
    app, api, baseline, callback = capture_intake(tmp_path, monkeypatch)
    api.put('/api/jobs/' + baseline['id'], json={'url': 'https://other.example/role'})
    callback({'title': 'Stale title', 'contact_email': 'jobs@other.example'})
    job = api.get('/api/jobs/' + baseline['id']).json
    assert job['title'] == baseline['title']
    assert job['enriched'] is False
    assert job['ingest_source'] == 'heuristic'
    assert job['contact_email'] == ''
    assert job['llm_pending'] is False


@pytest.mark.parametrize('matched', [False, True])
def test_async_company_correction_and_email(tmp_path, monkeypatch, matched):
    target = vault.save_company(tmp_path, {'name': 'Correct Labs'}) if matched else None
    app, api, baseline, callback = capture_intake(tmp_path, monkeypatch)
    callback({'company': 'Correct Labs', 'contact_email': 'jobs@correct.example'})
    job = api.get('/api/jobs/' + baseline['id']).json
    assert job['company'] == 'Correct Labs'
    assert job['company_id'] == (target['id'] if matched else baseline['company_id'])
    assert any(event['event'] == 'company_correction' for event in job['history'])
    if matched:
        assert vault.load_company(tmp_path, target['id'])['contact_email'] == 'jobs@correct.example'
        assert vault.load_company(tmp_path, baseline['company_id'])['contact_email'] == ''


def test_async_total_deadline_clears_pending(tmp_path, monkeypatch, capsys):
    release = Event()
    monkeypatch.setenv('LLM_TIMEOUT', '.03')
    client = client_for()
    def slow(**kwargs):
        release.wait(2)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"title":"Too late"}'))])
    client.chat.completions.create.side_effect = slow
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client)
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer at Labs</main>')
    app = create_app(tmp_path)
    api = app.test_client()
    try:
        start = monotonic()
        baseline = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'}).json['job']
        thread = app.config['LLM_THREADS'][baseline['id']]
        thread.join(1)
        assert not thread.is_alive()
        assert monotonic() - start < 1
        job = api.get('/api/jobs/' + baseline['id']).json
        assert job['llm_pending'] is False
        assert job['title'] == baseline['title']
        assert job['ingest_source'] == 'heuristic'
        assert capsys.readouterr().err == 'ingest: TimeoutError\n'
        release.set()
        assert api.get('/api/jobs/' + baseline['id']).json['title'] == baseline['title']
    finally:
        release.set()


def test_thread_start_failure_clears_pending(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer</main>')
    monkeypatch.setattr(ingest.Thread, 'start', Mock(side_effect=RuntimeError(SYNTHETIC_ENDPOINT)))
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
    assert response.status_code == 201
    assert api.get('/api/jobs/' + response.json['job']['id']).json['llm_pending'] is False
    assert app.config['LLM_THREADS'] == {}
    assert capsys.readouterr().err == 'ingest: RuntimeError\n'


def test_callback_save_failure_contained(tmp_path, monkeypatch, capsys):
    app, api, baseline, callback = capture_intake(tmp_path, monkeypatch)
    monkeypatch.setattr(vault, 'save_job', Mock(side_effect=OSError(SYNTHETIC_ENDPOINT)))
    callback({'summary': 'Update'})
    assert api.get('/api/jobs/' + baseline['id']).json['llm_pending'] is False
    assert capsys.readouterr().err == 'ingest: OSError\n'


def test_entire_async_callback_contained(capsys):
    def callback(fields):
        raise RuntimeError(SYNTHETIC_ENDPOINT)
    thread = ingest.extract_async('', callback)
    thread.join(1)
    assert capsys.readouterr().err == 'ingest: RuntimeError\n'


def test_auto_website_redaction(tmp_path, monkeypatch):
    unsafe = 'http://' + 'internal.service' + ':' + '9876'
    monkeypatch.setattr(intake, 'fetch_url', lambda url:
                        '<script type="application/ld+json">' + json.dumps({
                            '@type': 'JobPosting', 'title': 'Engineer',
                            'hiringOrganization': {'name': 'Safe Labs', 'url': unsafe}
                        }) + '</script>')
    api = create_app(tmp_path).test_client()
    response = api.post('/api/jobs/intake', json={'url': 'https://jobs.lever.co/safe/role'})
    assert response.status_code == 201
    assert response.json['company']['website'] is None
    assert unsafe not in ''.join(p.read_text() for p in tmp_path.rglob('*.yaml'))


def test_async_redaction_and_invalid_email_never_persist(tmp_path, monkeypatch):
    app, api, baseline, callback = capture_intake(tmp_path, monkeypatch)
    unsafe = 'worker.internal' + ':' + '9876'
    callback({'title': unsafe, 'summary': unsafe, 'company': unsafe,
              'contact_email': 'jobs@example.com', 'keywords': [unsafe, 'Python']})
    job = api.get('/api/jobs/' + baseline['id']).json
    assert job['title'] == baseline['title']
    assert job['company'] == baseline['company']
    assert job['summary'] == baseline['summary']
    assert job['keywords'] == ['Python']
    assert job['contact_email'] == ''
    assert vault.load_company(tmp_path, job['company_id'])['contact_email'] == ''
    assert unsafe not in ''.join(p.read_text() for p in tmp_path.rglob('*.yaml'))


def test_redaction_retains_normal_content():
    text = 'Engineer with Python skills at https://safe.example/careers'
    assert ingest.redact(text) == text


def test_company_email_fill_migrates_existing_job_email(tmp_path, monkeypatch):
    target = vault.save_company(tmp_path, {'name': 'Correct Labs'})
    app, api, baseline, callback = capture_intake(tmp_path, monkeypatch)
    api.put('/api/jobs/' + baseline['id'], json={'contact_email': 'owner@safe.example'})
    callback({'company': 'Correct Labs', 'contact_email': 'extracted@safe.example'})
    job = api.get('/api/jobs/' + baseline['id']).json
    assert job['contact_email'] == 'owner@safe.example'
    assert vault.load_company(tmp_path, target['id'])['contact_email'] == 'owner@safe.example'
