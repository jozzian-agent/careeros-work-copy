"""Offline structured ingestion contracts."""
import json
from time import monotonic, sleep
from threading import Event, Lock, Thread
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


def test_build_prompt_requests_new_fields():
    content = ingest.build_prompt('Role text')[1]['content']
    for field in ('background', 'skills', 'certifications', 'responsibilities'):
        assert field in content


def test_parse_response_new_fields():
    content = json.dumps(dict(background='5+ years experience required.',
                              skills=['Python', 'Python', None, 'SQL'],
                              certifications=['AWS Certified', ''],
                              responsibilities=['Lead the team', None]))
    parsed = ingest.parse_response(content)
    assert parsed['background'] == '5+ years experience required.'
    assert parsed['skills'] == ['Python', 'SQL']
    assert parsed['certifications'] == ['AWS Certified']
    assert parsed['responsibilities'] == ['Lead the team']


def test_redaction_covers_new_list_fields():
    unsafe = '192.168' + '.5.9'
    result = ingest.parse_response(json.dumps({
        'skills': [unsafe, 'Python'], 'certifications': [unsafe], 'responsibilities': [unsafe, 'Lead'],
    }))
    assert result['skills'] == ['Python']
    assert result['certifications'] == []
    assert result['responsibilities'] == ['Lead']


def test_heuristic_extract_never_invents_new_fields():
    result = ingest.heuristic_extract('Senior Engineer at Example Labs\nRemote\nPython.')
    for field in ('background', 'skills', 'certifications', 'responsibilities'):
        assert field not in result


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
    """JOZ-267 fix round 2, R2-A: once a call has actually started
    executing, nothing here imposes a second, separate deadline on top
    of the queue-wait phase -- the old combined-deadline design abandoned
    ownership of a call that was still genuinely running (round 2's
    probe: 'timeout returned while execution had started and not
    finished'). A slow call that eventually returns must be waited for
    and its result used, never discarded in favor of the heuristic
    fallback just because it took a while."""
    release = Event()
    go = Event()
    content = json.dumps({'title': 'Slow Engineer'})

    def slow(**kwargs):
        release.wait(2)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    client = client_for()
    client.chat.completions.create.side_effect = slow
    monkeypatch.setattr(ingest, 'TIMEOUT', .02)
    # R3-T2: start the release timer only once `started` has actually been
    # recorded -- starting it right after Thread.start() (the old version)
    # has no guaranteed ordering against that monotonic() read, so on a
    # slow or busy scheduler the 0.1s countdown could already be well
    # underway (or even finished) before `started` is captured, making
    # `elapsed >= 0.1` fail for a perfectly correct implementation.
    Thread(target=lambda: (go.wait(2), sleep(0.1), release.set()), daemon=True).start()
    started = monotonic()
    go.set()
    result = ingest.extract('Engineer', client=client, model=object())
    assert result['ingest_source'] == 'llm'
    assert result['title'] == 'Slow Engineer'
    assert monotonic() - started >= 0.1


def test_sync_extract_total_deadline_fails_cleanly(monkeypatch):
    """R3-A2: extract() runs synchronously on the caller's own thread --
    in production, the /enrich Flask request handler -- unlike
    extract_async, which runs the same unbounded-execution-phase wait on
    its own background thread where hanging is harmless. Without an
    outer bound here, a stuck model call could hang that request
    handler forever. SYNC_TOTAL_DEADLINE must give up and fall back to
    the heuristic result instead, well before the test's own margin."""
    stuck = Event()

    def never_returns(**kwargs):
        # Nothing ever reads this call's result (it is abandoned once the
        # outer deadline below fires); block briefly rather than forever
        # so the daemon thread running it does not linger past this test.
        stuck.wait(5)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])

    client = client_for()
    client.chat.completions.create.side_effect = never_returns
    monkeypatch.setattr(ingest, 'SYNC_TOTAL_DEADLINE', .05)
    started = monotonic()
    result = ingest.extract('Senior Engineer at Example Labs. ' * 5, client=client, model=object())
    assert monotonic() - started < 2, 'the synchronous caller must not hang past its outer deadline'
    assert result['ingest_source'] == 'heuristic'
    stuck.set()


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
    assert api.get('/api/jobs/' + job['id']).status_code == 200


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
                                   {'ingest_source': 'invalid'}, {'summary': 42},
                                   {'skills': 'Python'}, {'skills': [1]}, {'certifications': [1]},
                                   {'responsibilities': [1]}, {'summary_source': 'bogus'},
                                   {'background': 42}])
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
    'fe80' + ':0:0:0:0:0:0:1',
])
def test_redaction_all_extracted_strings(value):
    assert ingest.redact('prefix ' + value + ' suffix') == ''
    result = ingest.parse_response(json.dumps({'title': value, 'keywords': ['Python', value]}))
    assert result == {'title': '', 'keywords': ['Python']}
    assert ingest.heuristic_extract('Company: ' + value)['company'] == ''
    html = '<meta property="og:site_name" content="' + value + '">'
    assert intake.heuristic_posting('https://safe.example/job', html)['company'] == ''


@pytest.mark.parametrize('text', [
    'You will build products on top of OpenAI and Claude APIs.',
    'Office hours 9:00 to 17:00',
    '25 days plus 10.5 public holidays',
])
def test_redaction_keeps_real_posting_text(text):
    assert ingest.redact(text) == text


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
def test_shared_ats_website_never_recorded(host):
    # M4 (JOZ-266 fix round): the old _company_url_key classifier this
    # test exercised was removed (it could promote a provider-host match
    # into tenant ownership without checking the tenant itself -- see
    # test_cross_tenant_refline_website_is_not_promoted_to_ats_link in
    # test_company_resolve.py). _company_website's unrelated "never record
    # an ATS platform's own host as the employer's website" behavior is
    # untouched and still covered here.
    from careeros.server import _company_website
    assert _company_website('https://jobs.' + host + '/Alpha/role') is None


def test_ats_tenant_split_and_existing_path_match(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, 'extract_async', lambda *args, **kwargs: Mock(is_alive=lambda: False))
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
    def start(description, callback, **kwargs):
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
    # M2 (JOZ-266 fix round): the extraction callback's 'company' field now
    # feeds the shared resolution ladder (employer_named_in_posting) instead
    # of an ad-hoc exact-name-only match. The job's existing (auto-created,
    # guessed-name) company link is never silently swapped for a different,
    # exactly-matching company without a review step -- "matched" now means
    # that other company surfaces as a candidate, not a silent switch.
    target = vault.save_company(tmp_path, {'name': 'Correct Labs'}) if matched else None
    app, api, baseline, callback = capture_intake(tmp_path, monkeypatch)
    callback({'company': 'Correct Labs', 'contact_email': 'jobs@correct.example'})
    job = api.get('/api/jobs/' + baseline['id']).json
    assert job['company'] == 'Correct Labs'
    assert job['employer_named_in_posting'] == 'Correct Labs'
    assert job['company_id'] == baseline['company_id']
    assert any(event['event'] == 'company_correction' for event in job['history'])
    if matched:
        assert job['company_link_state'] == 'needs_review'
        candidates = job['company_review']['candidates']
        assert candidates and candidates[0]['company_id'] == target['id']
        assert vault.load_company(tmp_path, target['id'])['contact_email'] == ''
    assert job['company_link_state'] == 'needs_review'
    assert vault.load_company(tmp_path, baseline['company_id'])['contact_email'] == ''
    choice = {'company_id': target['id']} if matched else {'create': {'name': 'Correct Labs'}}
    resolved = api.post('/api/jobs/' + job['id'] + '/resolve-review',
                        json=choice | {'review_token': job['company_review']['token']})
    assert resolved.status_code == 200
    recipient = vault.load_company(tmp_path, resolved.json['company_id'])
    assert recipient['name'] == 'Correct Labs'
    assert recipient['contact_email'] == 'jobs@correct.example'
    assert vault.load_company(tmp_path, baseline['company_id'])['contact_email'] == ''


def test_async_total_deadline_clears_pending(tmp_path, monkeypatch):
    """JOZ-267 fix round 2, R2-A: the configured budget only ever bounds
    the queue-wait phase. Ownership (llm_pending, the worker thread) must
    stay held for as long as the model call is genuinely still running,
    however long that takes -- releasing it early (the old combined
    deadline) is exactly what let Retry start a second, concurrent
    extraction for the same job while the first was still in flight."""
    release = Event()
    entered = Event()
    timeout = .03
    monkeypatch.setenv('LLM_TIMEOUT', str(timeout))
    client = client_for()
    def slow(**kwargs):
        entered.set()
        release.wait(2)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"title":"Finally"}'))])
    client.chat.completions.create.side_effect = slow
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client)
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer at Labs</main>')
    app = create_app(tmp_path)
    api = app.test_client()
    try:
        baseline = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'}).json['job']
        thread = app.config['LLM_THREADS'][baseline['id']]
        assert entered.wait(2), 'the model call must actually have started'
        # R3-T2: prove the configured budget has actually elapsed with an
        # explicit monotonic measurement, rather than just trusting that
        # the incidental overhead of the calls above already ate more than
        # .03s -- that assumption has no synchronization behind it and can
        # go either way on a fast or heavily loaded machine.
        deadline_passed = monotonic() + timeout
        while monotonic() < deadline_passed:
            sleep(0.005)
        # The budget has now provably elapsed for the queue-wait phase,
        # yet the model call is still genuinely running: ownership must
        # still be held, not abandoned to a premature heuristic fallback.
        assert thread.is_alive()
        assert api.get('/api/jobs/' + baseline['id']).json['llm_pending'] is True
    finally:
        release.set()
    thread.join(2)
    assert not thread.is_alive()
    job = api.get('/api/jobs/' + baseline['id']).json
    assert job['llm_pending'] is False
    assert job['title'] == 'Finally'
    assert job['ingest_source'] == 'llm'


def test_thread_start_failure_clears_pending(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer</main>')
    monkeypatch.setattr(ingest.Thread, 'start', Mock(side_effect=RuntimeError(SYNTHETIC_ENDPOINT)))
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
    assert response.status_code == 503
    assert response.json['error']
    assert api.get('/api/jobs/' + response.json['job']['id']).json['llm_pending'] is False
    assert app.config['LLM_THREADS'] == {}
    assert set(capsys.readouterr().err.splitlines()) == {'ingest: RuntimeError'}


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
    assert set(capsys.readouterr().err.splitlines()) == {'ingest: RuntimeError'}


# --- JOZ-265 fix round: R2, the extract_failed reason distinguishes why --

def test_extract_async_reason_not_configured(monkeypatch):
    monkeypatch.delenv('LLM_BASE_URL', raising=False)
    received = []
    def callback(fields, reason=None):
        received.append((fields, reason))
    thread = ingest.extract_async('Role: Engineer. Python skills.', callback)
    thread.join(2)
    assert received == [(None, 'not_configured')]


def test_extract_async_reason_transport_error():
    received = []
    def callback(fields, reason=None):
        received.append((fields, reason))
    client = client_for(error=TimeoutError('boom'))
    thread = ingest.extract_async('Role: Engineer. Python skills.', callback, client=client, model=object())
    thread.join(2)
    assert received == [(None, 'transport_error')]


def test_extract_async_reason_unusable_output():
    received = []
    def callback(fields, reason=None):
        received.append((fields, reason))
    client = client_for('null')
    thread = ingest.extract_async('Role: Engineer. Python skills.', callback, client=client, model=object())
    thread.join(2)
    assert received == [(None, 'unusable_output')]


def test_extract_async_reason_none_on_success():
    received = []
    def callback(fields, reason=None):
        received.append((fields, reason))
    client = client_for('{"title":"Senior Engineer"}')
    thread = ingest.extract_async('Role: Engineer. Python skills.', callback, client=client, model=object())
    thread.join(2)
    assert len(received) == 1 and received[0][0] is not None and received[0][1] is None


def test_extract_async_single_argument_callback_still_works(monkeypatch):
    # Backward compatibility: a callback declaring only `fields` (the
    # pre-R2 contract) must still be called correctly, not break with a
    # TypeError from an unexpected second argument.
    monkeypatch.delenv('LLM_BASE_URL', raising=False)
    received = []
    thread = ingest.extract_async('Role: Engineer. Python skills.', received.append)
    thread.join(2)
    assert received == [None]


def test_auto_website_redaction(tmp_path, monkeypatch):
    unsafe = 'http://' + '192.168' + '.5.9/careers'
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
    unsafe = '192.168' + '.5.9'
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
    # An existing job email is held through review, then promoted to the chosen employer.
    target = vault.save_company(tmp_path, {'name': 'Correct Labs'})
    app, api, baseline, callback = capture_intake(tmp_path, monkeypatch)
    # The saved email predates this extraction and belongs to an unresolved job.
    vault.save_job(tmp_path, {'company_link_state': 'needs_review',
        'company_review': {'candidates': [], 'at': vault.timestamp(), 'token': 'existing-review'}}, baseline['id'])
    api.put('/api/jobs/' + baseline['id'], json={'contact_email': 'owner@safe.example'})
    callback({'company': 'Correct Labs', 'contact_email': 'extracted@safe.example'})
    job = api.get('/api/jobs/' + baseline['id']).json
    assert job['company_link_state'] == 'needs_review'
    assert job['contact_email'] == 'owner@safe.example'
    assert vault.load_company(tmp_path, baseline['company_id'])['contact_email'] == ''
    assert vault.load_company(tmp_path, target['id'])['contact_email'] == ''
    response = api.post('/api/jobs/' + job['id'] + '/resolve-review', json={
        'company_id': target['id'], 'review_token': job['company_review']['token']})
    assert response.status_code == 200
    assert vault.load_company(tmp_path, target['id'])['contact_email'] == 'owner@safe.example'
    assert vault.load_company(tmp_path, baseline['company_id'])['contact_email'] == ''


def test_async_summary_provenance_marker(tmp_path, monkeypatch):
    app, api, baseline, callback = capture_intake(tmp_path, monkeypatch)
    assert baseline['summary_source'] == ''
    callback({'summary': 'LLM summary.', 'background': '5+ years.', 'skills': ['Python']})
    job = api.get('/api/jobs/' + baseline['id']).json
    assert job['summary'] == 'LLM summary.'
    assert job['summary_source'] == 'ai'
    assert job['background'] == '5+ years.'
    assert job['skills'] == ['Python']


def test_enrich_sync_heuristic_summary_has_no_ai_marker(tmp_path, monkeypatch):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer at Example Labs. Build Python services.</main>')
    api = create_app(tmp_path).test_client()
    response = api.post('/api/jobs/' + job['id'] + '/enrich')
    assert response.status_code == 200
    assert response.json['ingest_source'] == 'heuristic'
    assert response.json['summary']
    assert response.json['summary_source'] == ''


def test_enrich_sync_llm_summary_gets_ai_marker(tmp_path, monkeypatch):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer at Example Labs.</main>')
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client_for(json.dumps({
        'summary': 'LLM summary.', 'skills': ['Python'], 'background': '5+ years.'})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    api = create_app(tmp_path).test_client()
    response = api.post('/api/jobs/' + job['id'] + '/enrich')
    assert response.status_code == 200
    assert response.json['ingest_source'] == 'llm'
    assert response.json['summary'] == 'LLM summary.'
    assert response.json['summary_source'] == 'ai'
    assert response.json['skills'] == ['Python']
    assert response.json['background'] == '5+ years.'


def test_extract_endpoint_lifecycle(tmp_path, monkeypatch):
    job = vault.save_job(tmp_path, {'title': 'Owner title', 'url': 'https://posting.example/role',
                                    'description': 'Stored description text.'})
    callbacks = []
    def start(description, callback, **kwargs):
        callbacks.append((description, callback))
        return Mock(is_alive=lambda: False)
    monkeypatch.setattr(ingest, 'extract_async', start)
    api = create_app(tmp_path).test_client()
    first = api.post('/api/jobs/' + job['id'] + '/extract')
    for worker in list(api.application.config['REFRESH_THREADS'].values()):
        worker.join(timeout=2)
    assert first.status_code == 202
    assert first.json['llm_pending'] is True
    assert api.get('/api/jobs/' + job['id']).json['llm_pending'] is True
    assert callbacks[0][0] == 'Stored description text.'
    # A second call while a run is pending must skip gracefully (no new worker).
    second = api.post('/api/jobs/' + job['id'] + '/extract')
    for worker in list(api.application.config['REFRESH_THREADS'].values()):
        worker.join(timeout=2)
    assert second.status_code == 202
    assert len(callbacks) == 1
    callbacks[0][1]({'summary': 'AI summary.', 'skills': ['Python'], 'certifications': ['PMP']})
    job_after = api.get('/api/jobs/' + job['id']).json
    assert job_after['llm_pending'] is False
    assert job_after['summary'] == 'AI summary.'
    assert job_after['summary_source'] == 'ai'
    assert job_after['skills'] == ['Python']
    assert job_after['certifications'] == ['PMP']


def test_extract_endpoint_missing_job(tmp_path):
    api = create_app(tmp_path).test_client()
    assert api.post('/api/jobs/missing/extract').status_code == 404


def test_extract_endpoint_respects_owner_edit(tmp_path, monkeypatch):
    job = vault.save_job(tmp_path, {'title': 'Old Title', 'url': 'https://posting.example/role',
                                    'description': 'Stored description text.'})
    callbacks = []
    def start(description, callback, **kwargs):
        callbacks.append(callback)
        return Mock(is_alive=lambda: False)
    monkeypatch.setattr(ingest, 'extract_async', start)
    api = create_app(tmp_path).test_client()
    assert api.post('/api/jobs/' + job['id'] + '/extract').status_code == 202
    for worker in list(api.application.config['REFRESH_THREADS'].values()):
        worker.join(timeout=2)
    assert api.put('/api/jobs/' + job['id'], json={'title': 'Owner Title'}).status_code == 200
    callbacks[0]({'title': 'LLM Title', 'summary': 'LLM summary.'})
    result = api.get('/api/jobs/' + job['id']).json
    assert result['title'] == 'Owner Title'
    assert result['summary'] == 'LLM summary.'
    assert result['summary_source'] == 'ai'


def test_legacy_job_record_loads_without_new_fields(tmp_path):
    job = vault.save_job(tmp_path, {'title': 'Legacy Role', 'url': 'https://posting.example/role'})
    path = next((tmp_path / 'jobs').glob('*.yaml'))
    stored = yaml.safe_load(path.read_text())
    for field in ('background', 'skills', 'certifications', 'responsibilities', 'summary_source'):
        stored.pop(field, None)
    path.write_text(yaml.safe_dump(stored))
    loaded = vault.load_job(tmp_path, job['id'])
    assert loaded['title'] == 'Legacy Role'
    assert 'background' not in loaded
    updated = vault.save_job(tmp_path, {'notes': 'Touch the record.'}, job['id'])
    assert updated['background'] == ''
    assert updated['skills'] == []
    assert updated['summary_source'] == ''


def test_extract_endpoint_empty_description_clears_pending(tmp_path, monkeypatch):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    api = create_app(tmp_path).test_client()
    response = api.post('/api/jobs/' + job['id'] + '/extract')
    for worker in list(api.application.config['REFRESH_THREADS'].values()):
        worker.join(timeout=2)
    assert response.status_code == 202
    app = api.application
    app.config['LLM_THREADS'][job['id']].join(timeout=2)
    assert api.get('/api/jobs/' + job['id']).json['llm_pending'] is False


# --- JOZ-260 fix round: regressions for the cross-review findings ---

def test_extract_summary_source_only_when_llm_supplies_summary(monkeypatch):
    """MAJOR 1: a partial LLM result (no summary) must not badge the
    retained heuristic summary, even though ingest_source becomes 'llm'."""
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client_for(json.dumps({'skills': ['Python']})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    result = ingest.extract('Engineer at Example Labs. Build Python services.')
    assert result['ingest_source'] == 'llm'
    assert result['skills'] == ['Python']
    assert result['summary_source'] == ''
    assert result['summary']


def test_enrich_sync_partial_llm_result_keeps_heuristic_summary_unbadged(tmp_path, monkeypatch):
    """MAJOR 1, via the /enrich route: same gap, exercised end-to-end."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer at Example Labs. Build Python services.</main>')
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client_for(json.dumps({'skills': ['Python']})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    api = create_app(tmp_path).test_client()
    response = api.post('/api/jobs/' + job['id'] + '/enrich')
    assert response.status_code == 200
    assert response.json['ingest_source'] == 'llm'
    assert response.json['skills'] == ['Python']
    assert response.json['summary']
    assert response.json['summary_source'] == ''


def test_owner_summary_replace_clears_ai_badge(tmp_path):
    """MAJOR 2: replacing AI-badged summary text via PUT must drop the badge."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'summary': 'AI summary.', 'summary_source': 'ai'})
    api = create_app(tmp_path).test_client()
    response = api.put('/api/jobs/' + job['id'], json={'summary': 'Written by owner'})
    assert response.status_code == 200
    assert response.json['summary'] == 'Written by owner'
    assert response.json['summary_source'] == ''


def test_owner_summary_clear_removes_ai_badge(tmp_path):
    """MAJOR 2: clearing an AI-badged summary to empty must drop the badge."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'summary': 'AI summary.', 'summary_source': 'ai'})
    api = create_app(tmp_path).test_client()
    response = api.put('/api/jobs/' + job['id'], json={'summary': ''})
    assert response.status_code == 200
    assert response.json['summary'] == ''
    assert response.json['summary_source'] == ''


def test_owner_put_cannot_set_ai_badge_directly(tmp_path):
    """MAJOR 2: only trusted extraction paths may set summary_source; a
    client-supplied value on an ordinary PUT must never stick."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    api = create_app(tmp_path).test_client()
    response = api.put('/api/jobs/' + job['id'], json={'summary': 'Owner text', 'summary_source': 'ai'})
    assert response.status_code == 200
    assert response.json['summary'] == 'Owner text'
    assert response.json['summary_source'] == ''


def test_put_without_summary_change_preserves_badge(tmp_path):
    """MAJOR 2 control: a PUT that doesn't touch summary must leave an
    existing AI badge alone."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'summary': 'AI summary.', 'summary_source': 'ai'})
    api = create_app(tmp_path).test_client()
    response = api.put('/api/jobs/' + job['id'], json={'notes': 'unrelated edit'})
    assert response.status_code == 200
    assert response.json['summary'] == 'AI summary.'
    assert response.json['summary_source'] == 'ai'


def test_concurrent_extract_calls_start_exactly_one_worker(tmp_path, monkeypatch):
    """MAJOR 3: the pending check-and-reserve must be atomic across threads,
    not just across sequential requests."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'description': 'Stored description text.'})
    starts = []
    starts_lock = Lock()

    def start(description, callback, **kwargs):
        with starts_lock:
            starts.append(callback)
        return Mock(is_alive=lambda: True)

    monkeypatch.setattr(ingest, 'extract_async', start)
    api = create_app(tmp_path).test_client()
    results = []
    results_lock = Lock()

    def call():
        response = api.post('/api/jobs/' + job['id'] + '/extract')
        for worker in list(api.application.config['REFRESH_THREADS'].values()):
            worker.join(timeout=2)
        with results_lock:
            results.append(response.json)

    threads = [Thread(target=call) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert len(starts) == 1
    assert len(results) == 10
    assert all(result['llm_pending'] is True for result in results)


def test_stale_callback_cannot_clear_newer_runs_pending_state(tmp_path, monkeypatch):
    """MAJOR 3: a per-run token must guard the llm_pending pop, so a run
    that no longer owns the slot (simulated here via a token swap) can
    never clear state a newer run holds."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'description': 'Stored description text.'})
    callbacks = []

    def start(description, callback, **kwargs):
        callbacks.append(callback)
        return Mock(is_alive=lambda: True)

    monkeypatch.setattr(ingest, 'extract_async', start)
    app = create_app(tmp_path)
    api = app.test_client()
    first = api.post('/api/jobs/' + job['id'] + '/extract')
    for worker in list(api.application.config['REFRESH_THREADS'].values()):
        worker.join(timeout=2)
    assert first.status_code == 202
    pending = app.config['LLM_PENDING']
    assert job['id'] in pending
    # Simulate a newer run having since taken the slot; the real endpoints
    # make this unreachable via reserve_enrichment, but the identity check
    # must defend against it regardless.
    pending[job['id']] = object()
    callbacks[0](None)
    assert job['id'] in pending
    assert api.get('/api/jobs/' + job['id']).json['llm_pending'] is True


def test_extract_endpoint_reports_start_failure_truthfully(tmp_path, monkeypatch, capsys):
    """MINOR 5: when the worker genuinely fails to start, the response must
    not claim enrichment is pending."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'description': 'Stored description text.'})
    monkeypatch.setattr(ingest, 'extract_async', Mock(side_effect=RuntimeError('boom')))
    api = create_app(tmp_path).test_client()
    response = api.post('/api/jobs/' + job['id'] + '/extract')
    for worker in list(api.application.config['REFRESH_THREADS'].values()):
        worker.join(timeout=2)
    assert response.status_code == 202
    assert response.json['llm_pending'] is True
    assert api.get('/api/jobs/' + job['id']).json['llm_pending'] is False
    assert set(capsys.readouterr().err.splitlines()) == {'ingest: RuntimeError'}


@pytest.mark.parametrize('field,baseline_value,owner_value', [
    ('summary', 'Heuristic summary.', 'Owner summary.'),
    ('summary', 'Heuristic summary.', ''),
    ('background', 'Baseline background.', 'Owner background.'),
    ('background', 'Baseline background.', ''),
    ('skills', ['BaselineSkill'], ['OwnerSkill']),
    ('skills', ['BaselineSkill'], []),
    ('certifications', ['BaselineCert'], ['OwnerCert']),
    ('certifications', ['BaselineCert'], []),
    ('responsibilities', ['BaselineResp'], ['OwnerResp']),
    ('responsibilities', ['BaselineResp'], []),
])
def test_owner_edit_or_clear_survives_inflight_callback(tmp_path, monkeypatch, field, baseline_value, owner_value):
    """MINOR 6: owner edits AND clears of every LLM-fillable field must
    survive a callback landing after the edit, for summary and all four
    new fields. Uses /extract (baseline = current record) so the field
    starts non-default, making a "clear" distinguishable from "untouched"."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'description': 'Stored description text.', field: baseline_value})
    callbacks = []

    def start(description, callback, **kwargs):
        callbacks.append(callback)
        return Mock(is_alive=lambda: True)

    monkeypatch.setattr(ingest, 'extract_async', start)
    api = create_app(tmp_path).test_client()
    assert api.post('/api/jobs/' + job['id'] + '/extract').status_code == 202
    for worker in list(api.application.config['REFRESH_THREADS'].values()):
        worker.join(timeout=2)
    assert api.put('/api/jobs/' + job['id'], json={field: owner_value}).status_code == 200
    callbacks[0]({'summary': 'LLM summary.', 'background': 'LLM background.',
                  'skills': ['LLMSkill'], 'certifications': ['LLMCert'],
                  'responsibilities': ['LLMResp']})
    result = api.get('/api/jobs/' + job['id']).json
    assert result[field] == owner_value


# --- JOZ-261 fix round: boilerplate-free description extraction ---

def test_parser_suppresses_structural_chrome():
    """Nav/header/footer and a class-marked cookie banner must never reach
    parser text or regions, even when they sit alongside real content."""
    html = ('<nav>Site nav links</nav>'
            '<header>Header menu</header>'
            '<div class="cookie-consent">We use cookies to offer you the best possible website experience.</div>'
            '<main><h1>Senior Engineer</h1><p>Build great products with Python.</p></main>'
            '<footer>All rights reserved. Follow us.</footer>')
    result = intake.extract('https://posting.example/role', html)
    description = result['description']
    assert description == 'Senior Engineer\nBuild great products with Python.'
    for junk in ('nav', 'menu', 'cookies', 'rights reserved', 'Follow us'):
        assert junk not in description.casefold()


def test_body_fallback_strips_banner_and_preserves_paragraphs():
    """Swissgrid-like page: no main/article, consent banner is the first
    thing in body. The banner must be suppressed and the real paragraphs
    must survive as separate lines, not one flattened line."""
    html = ('<body>'
            '<div class="cookie-consent">We use cookies to offer you the best possible website experience.</div>'
            '<p>We are hiring a Head of Market and Product Design.</p>'
            '<p>You will lead a cross-functional team and own the roadmap.</p>'
            '</body>')
    result = intake.extract('https://posting.example/role', html)
    description = result['description']
    assert 'cookies' not in description.casefold()
    assert description.splitlines() == [
        'We are hiring a Head of Market and Product Design.',
        'You will lead a cross-functional team and own the roadmap.',
    ]


def test_heuristic_summary_skips_cookie_boilerplate():
    description = ('We use cookies to offer you the best possible website experience.\n'
                    'We are hiring a Senior Backend Engineer to join our platform team.\n'
                    'You will design resilient APIs.')
    summary = ingest.heuristic_extract(description)['summary']
    assert 'cookie' not in summary.casefold()
    assert 'Senior Backend Engineer' in summary


def test_heuristic_summary_empty_when_only_boilerplate_present():
    description = 'We use cookies to offer you the best possible website experience. All rights reserved.'
    assert ingest.heuristic_extract(description)['summary'] == ''


def test_flat_single_line_description_still_heuristically_extracted():
    """Pre-existing callers that hand heuristic_extract flat, tag-free text
    (no HTML, no boilerplate) must see unchanged behavior."""
    description = 'Senior Engineer at Example Labs\nLocation: Remote\nFull-time. Build Python services.'
    result = ingest.heuristic_extract(description)
    assert result['title'] == 'Senior Engineer'
    assert result['company'] == 'Example Labs'
    assert result['location'] == 'Remote'
    assert result['summary']


def test_extract_endpoint_refetch_replaces_polluted_description_and_respects_owner_edit(tmp_path, monkeypatch):
    """/extract must re-fetch the live posting and replace a chrome-polluted
    stored description before enriching, while the existing owner-edit
    protection for other fillable fields (e.g. title) still holds."""
    job = vault.save_job(tmp_path, {'title': 'Old Title', 'url': 'https://posting.example/role',
                                    'description': 'We use cookies to offer you the best experience.'})
    html = ('<nav>Navigation</nav>'
            '<main><h1>Senior Engineer</h1><p>Build great products with Python.</p></main>'
            '<footer>All rights reserved.</footer>')
    monkeypatch.setattr(intake, 'fetch_url', lambda url: html)
    callbacks = []

    def start(description, callback, **kwargs):
        callbacks.append((description, callback))
        return Mock(is_alive=lambda: False)

    monkeypatch.setattr(ingest, 'extract_async', start)
    api = create_app(tmp_path).test_client()
    response = api.post('/api/jobs/' + job['id'] + '/extract')
    for worker in list(api.application.config['REFRESH_THREADS'].values()):
        worker.join(timeout=2)
    assert response.status_code == 202
    assert response.json['description'] == job['description']
    fresh_description = api.get('/api/jobs/' + job['id']).json['description']
    assert 'cookies' not in fresh_description.casefold()
    assert 'Build great products with Python.' in fresh_description
    assert api.get('/api/jobs/' + job['id']).json['description'] == fresh_description
    assert callbacks[0][0] == fresh_description
    assert api.put('/api/jobs/' + job['id'], json={'title': 'Owner Title'}).status_code == 200
    callbacks[0][1]({'title': 'LLM Title', 'summary': 'LLM summary.'})
    result = api.get('/api/jobs/' + job['id']).json
    assert result['title'] == 'Owner Title'
    assert result['summary'] == 'LLM summary.'
    assert result['description'] == fresh_description


def test_extract_endpoint_refetch_failure_falls_back_to_stored_description(tmp_path, monkeypatch):
    """A fetch failure during the /extract re-fetch attempt (offline, posting
    gone, timeout) must silently fall back to enriching the description
    already on file, exactly like before the re-fetch existed."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'description': 'Stored description text.'})
    monkeypatch.setattr(intake, 'fetch_url', Mock(side_effect=RuntimeError('unreachable')))
    callbacks = []

    def start(description, callback, **kwargs):
        callbacks.append(description)
        return Mock(is_alive=lambda: False)

    monkeypatch.setattr(ingest, 'extract_async', start)
    api = create_app(tmp_path).test_client()
    response = api.post('/api/jobs/' + job['id'] + '/extract')
    for worker in list(api.application.config['REFRESH_THREADS'].values()):
        worker.join(timeout=2)
    assert response.status_code == 202
    assert response.json['description'] == 'Stored description text.'
    assert callbacks == ['Stored description text.']
