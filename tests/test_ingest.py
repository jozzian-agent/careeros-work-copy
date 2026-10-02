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
from careeros.server import create_app


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
    assert kwargs['timeout'] == 30
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
    assert job['seniority'] == ('lead' if use_llm else 'senior')
    assert job['ingest_source'] == ('llm' if use_llm else 'heuristic')
    assert job['source'] == 'posting.example'
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
        client.chat.completions.create.side_effect = lambda **kwargs: release.wait(2)
        monkeypatch.setattr(ingest, 'TIMEOUT', .02)
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client)
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    try:
        api = create_app(tmp_path).test_client()
        response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
        assert response.status_code == 201
        path = next((tmp_path / 'jobs').glob('*.yaml'))
        stored = yaml.safe_load(path.read_text())
        assert stored['description'] == description
        assert stored['ingest_source'] == 'heuristic'
        client.chat.completions.create.assert_called_once()
    finally:
        release.set()
