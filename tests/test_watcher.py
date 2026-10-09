from urllib.error import HTTPError
import pytest
from careeros import vault, intake, watcher
from careeros.server import create_app

@pytest.fixture
def job(tmp_path):
    return vault.save_job(tmp_path, {'title':'Builder', 'url':'https://fiction.example/job'})

def fail(code=None):
    def fetch(url):
        if code:
            raise HTTPError(url, code, 'failure', {}, None)
        raise OSError('offline')
    return fetch

def read(root, job):
    return vault.load_job(root, job['id'])

@pytest.mark.parametrize('code', [404,410])
def test_gone(tmp_path, job, code):
    events = watcher.scan(tmp_path, fetch=fail(code))
    assert events[0]['event'] == 'posting_gone'
    assert events[0]['detail'] == f'HTTP {code}'
    assert read(tmp_path,job)['watch']['watch_status'] == 'gone'
    assert watcher.scan(tmp_path, fetch=lambda _: pytest.fail('gone fetched')) == []

@pytest.mark.parametrize('code', [None,500,403])
def test_errors(tmp_path, job, code):
    for count in (1,2,3):
        events = watcher.scan(tmp_path, fetch=fail(code))
        watch = read(tmp_path,job)['watch']
        assert watch['consecutive_errors'] == count
        assert watch['watch_status'] == ('gone' if count==3 else 'error')
        assert bool(events) == (count==3)

def test_recovery(tmp_path, job):
    watcher.scan(tmp_path, fetch=fail())
    assert watcher.scan(tmp_path, fetch=lambda _: 'body') == []
    assert read(tmp_path,job)['watch']['consecutive_errors'] == 0
    assert read(tmp_path,job)['history'][-1]['event'] == 'watch_started'
    assert watcher.scan(tmp_path, fetch=lambda _: 'body  ') == []
    assert watcher.scan(tmp_path, fetch=lambda _: 'changed')[0]['event'] == 'posting_changed'

@pytest.mark.parametrize('salary', ['', 'Owner salary'])
def test_salary(tmp_path,job,salary):
    vault.save_job(tmp_path, {'salary_note':salary},job['id'])
    events = watcher.scan(tmp_path, fetch=lambda _: 'Salary CHF 120,000-140,000')
    assert bool(events) == (not salary)
    assert read(tmp_path,job)['salary_note'] == (salary or 'Salary CHF 120,000-140,000')

@pytest.mark.parametrize('fetch', [fail(),fail(404),lambda _: 'Salary CHF 120,000-140,000'])
def test_dry_run(tmp_path,job,fetch):
    before = {p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    watcher.scan(tmp_path,fetch=fetch,dry_run=True)
    assert {p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before

def test_history_api(tmp_path,job):
    client=create_app(tmp_path).test_client()
    result=client.put('/api/jobs/'+job['id'],json={'status':'applied','notes':'hello','history':[]}).json
    assert [e['event'] for e in result['history']] == ['created','status_changed','note_added']
    result=client.put('/api/jobs/'+job['id'],json={'notes':'edited'}).json
    assert len(result['history']) == 3
    assert b'History' in client.get('/jobs/'+job['id']).data

def test_legacy(tmp_path,job):
    path=next((tmp_path/'jobs').glob('*.yaml'))
    job.pop('history',None)
    vault._write(path,job)
    client=create_app(tmp_path).test_client()
    assert b'History' not in client.get('/jobs/'+job['id']).data
    assert watcher.scan(tmp_path,fetch=lambda _: 'body') == []
    assert [e['event'] for e in read(tmp_path,job)['history']] == ['watch_started']

@pytest.mark.parametrize('status', ['offer','rejected','closed','withdrawn'])
def test_skip(tmp_path,job,status):
    vault.save_job(tmp_path,{'status':status},job['id'])
    assert watcher.scan(tmp_path,fetch=lambda _: pytest.fail('ineligible fetched')) == []

def test_reactivate(tmp_path,job):
    watcher.scan(tmp_path,fetch=fail(404))
    vault.save_job(tmp_path,{'status':'applied'},job['id'])
    assert watcher.scan(tmp_path,fetch=lambda _: 'body') == []
    assert read(tmp_path,job)['watch']['watch_status'] == 'ok'

def test_cli(tmp_path,job,monkeypatch,capsys):
    monkeypatch.setattr(intake,'fetch_url',lambda _: 'body')
    assert watcher.main(['--vault',str(tmp_path)]) == 0
    assert capsys.readouterr().out == ''
    monkeypatch.setattr(intake,'fetch_url',fail(404))
    assert watcher.main(['--vault',str(tmp_path)]) == 0
    out=capsys.readouterr().out
    assert len(out.splitlines()) == 1 and '[JOB-001]' in out and out.startswith('gone:')

def test_unreadable(tmp_path,capsys):
    assert watcher.main(['--vault',str(tmp_path/'missing')]) == 1
    assert capsys.readouterr().out == ''

def test_endpoint(tmp_path,job,monkeypatch):
    monkeypatch.setattr(intake,'fetch_url',fail())
    client=create_app(tmp_path).test_client()
    response=client.post('/api/watch/scan?job='+job['id'])
    assert response.status_code == 200 and response.json['events'] == []
    assert response.json['watch_status'] == 'error'
    assert client.post('/api/watch/scan?job=missing').status_code == 404
    assert b'Check posting' in client.get('/jobs/'+job['id']).data

@pytest.mark.parametrize('mutation', ['delete','url','status','notes','salary'])
def test_concurrent_edit(tmp_path,job,mutation):
    def fetch(url):
        if mutation == 'delete':
            vault.delete_job(tmp_path,job['id'])
        else:
            updates={'url':{'url':'https://other.example/job'},'status':{'status':'closed'},
                     'notes':{'notes':'Owner edit'},'salary':{'salary_note':'Owner salary'}}[mutation]
            vault.save_job(tmp_path,updates,job['id'])
        return 'Salary CHF 120,000-140,000'
    events=watcher.scan(tmp_path,fetch=fetch)
    saved=read(tmp_path,job)
    if mutation in ('delete','url','status'):
        assert events == []
        assert saved is None or 'watch' not in saved
    elif mutation == 'notes':
        assert saved['notes'] == 'Owner edit'
    else:
        assert saved['salary_note'] == 'Owner salary' and events == []

def test_fetch_outside_save_inside(tmp_path,job,monkeypatch):
    class Lock:
        held=False
        def __enter__(self): self.held=True
        def __exit__(self,*args): self.held=False
    lock=Lock()
    save=vault.save_watch_result
    def fetch(url):
        assert not lock.held
        return 'body'
    def persist(*args):
        assert lock.held
        return save(*args)
    monkeypatch.setattr(vault,'save_watch_result',persist)
    watcher.scan(tmp_path,fetch=fetch,lock=lock)

def test_first_enrichment_only(tmp_path,job,monkeypatch):
    monkeypatch.setattr(intake,'fetch_url',lambda _: '<title>Builder</title>')
    client=create_app(tmp_path).test_client()
    for _ in range(2):
        assert client.post('/api/jobs/'+job['id']+'/enrich').status_code == 200
    assert [e['event'] for e in read(tmp_path,job)['history']].count('enriched') == 1

def test_single_job(tmp_path,job,monkeypatch):
    second=vault.save_job(tmp_path,{'title':'Other','url':'https://other.example/job'})
    fetched=[]
    monkeypatch.setattr(intake,'fetch_url',lambda url: fetched.append(url) or 'body')
    response=create_app(tmp_path).test_client().post('/api/watch/scan?job='+job['id'])
    assert response.status_code == 200
    assert fetched == [job['url']]
    assert 'watch' not in read(tmp_path,second)


def posting_body(title='Builder', description='Build useful tools', noise='3'):
    import json
    schema = {'@type': 'JobPosting', 'title': title,
              'hiringOrganization': {'name': 'Labs'},
              'description': description, 'datePosted': '2026-09-01'}
    return ('<script type="application/ld+json">' + json.dumps(schema).replace('<', r'\u003c') + '</script>'
            f'<input name="csrf" value="{noise}"><div nonce="{noise}">'
            f'posted {noise} hours ago</div><aside>Ad CHF {noise}000 in Berlin</aside>')


@pytest.mark.parametrize('structured', [True, False])
def test_hash_ignores_noise(tmp_path, job, structured):
    def body(noise, description):
        if structured:
            return posting_body(description=description, noise=noise)
        return (f'<title>Builder</title><input name="csrf" value="{noise}">'
                f'<main nonce="{noise}">{description}</main><p>posted {noise} hours ago</p>')
    watcher.scan(tmp_path, fetch=lambda _: body('3', 'Build useful tools'))
    assert watcher.scan(tmp_path, fetch=lambda _: body('4', 'Build \n useful\t tools')) == []


@pytest.mark.parametrize('change', [dict(title='Lead builder'), dict(description='Build different tools')])
def test_hash_detects_real_change(tmp_path, job, change):
    watcher.scan(tmp_path, fetch=lambda _: posting_body())
    assert [e['event'] for e in watcher.scan(tmp_path, fetch=lambda _: posting_body(**change))] == ['posting_changed']


def test_description_discards_hidden_content(tmp_path, job):
    watcher.scan(tmp_path, fetch=lambda _: posting_body())
    assert watcher.scan(tmp_path, fetch=lambda _: posting_body(
        description='Build <!-- random -->useful <script>nonce=42</script><style>.ad{}</style>tools')) == []


@pytest.mark.parametrize('version', [None, 1])
def test_hash_migration(tmp_path, job, version):
    job['watch'] = {'content_hash': 'old raw hash', 'watch_status': 'ok'}
    if version is not None:
        job['watch']['hash_version'] = version
    vault.save_watch_result(tmp_path, job)
    before = job['history']
    assert watcher.scan(tmp_path, fetch=lambda _: posting_body()) == []
    saved = read(tmp_path, job)
    assert saved['watch']['hash_version'] == 2
    assert saved['watch']['content_hash'] != 'old raw hash'
    assert saved['history'] == before
    assert watcher.scan(tmp_path, fetch=lambda _: posting_body(title='Changed'))[0]['event'] == 'posting_changed'


def test_history_cap():
    job = {'history': [dict(event='old', detail=str(i)) for i in range(60)]}
    latest = vault.append_event(job, 'posting_changed', 'new')
    assert len(job['history']) == 50
    assert job['history'][0]['detail'] == '11'
    assert job['history'][-1] == latest


def test_lock_rejects_nesting_without_second_flock(tmp_path, monkeypatch):
    calls = []
    # Stub flock so a regression fails promptly instead of hanging the suite.
    monkeypatch.setattr(vault.fcntl, 'flock', lambda fd, mode: calls.append(mode))
    lock = vault.WriteLock(tmp_path)
    with lock:
        with pytest.raises(RuntimeError, match='WriteLock is not reentrant across flock; refactor to acquire once'):
            with lock:
                pass
        assert calls == [vault.fcntl.LOCK_EX]
    with lock:
        pass
    assert calls == [vault.fcntl.LOCK_EX, vault.fcntl.LOCK_UN] * 2


@pytest.mark.parametrize('updates', [{'status': 'closed'}, {'url': ''}])
def test_ineligible_scan_and_button(tmp_path, job, updates, monkeypatch):
    from html.parser import HTMLParser
    job.update(updates)
    vault.save_watch_result(tmp_path, job)
    monkeypatch.setattr(intake, 'fetch_url', lambda _: pytest.fail('ineligible fetched'))
    client = create_app(tmp_path).test_client()
    data = client.post('/api/watch/scan?job=' + job['id']).json
    assert data['watch_status'] == 'not_watched'
    assert data['reason'] == 'Only jobs with status New/Interested/Applied/Interviewing and a posting URL are watched'
    buttons = []
    class Buttons(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == 'button':
                buttons.append(dict(attrs))
    parser = Buttons()
    parser.feed(client.get('/jobs/' + job['id']).text)
    button = next(b for b in buttons if b.get('id') == 'check-posting')
    assert 'disabled' in button and button['title'] == data['reason']


def test_check_posting_summary_placement_and_chunk(tmp_path, job):
    html = create_app(tmp_path).test_client().get('/jobs/' + job['id']).text
    assert html.index('id="check-posting"') < html.index('id="job-form"')
    assert 'Chunk 4' in html and 'Chunk 3' not in html


@pytest.mark.parametrize('data, reloads, message', [
    ({'events': [{'event': 'posting_changed', 'detail': 'changed'}]}, 1, ''),
    ({'events': [], 'watch_status': 'ok'}, 0, 'Unchanged'),
    ({'events': [], 'watch_status': 'not_watched', 'reason': 'Not eligible'}, 0, 'Not eligible'),
])
def test_check_posting_client_behavior(tmp_path, job, data, reloads, message):
    import json
    import re
    import subprocess
    html = create_app(tmp_path).test_client().get('/jobs/' + job['id']).text
    script = next(s for s in re.findall(r'<script>(.*?)</script>', html, re.S) if 'const checkPosting=' in s)
    harness = '''
const result={textContent:''}, button={disabled:false}; let reloads=0;
const document={getElementById:id=>id==='check-posting'?button:result};
const location={reload:()=>reloads++}; const sessionStorage={setItem:()=>{}};
const api=async()=>(DATA);
SCRIPT
(async()=>{await button.onclick();console.log(JSON.stringify({reloads,message:result.textContent}));})();
'''.replace('DATA', json.dumps(data)).replace('SCRIPT', script)
    completed = subprocess.run(['node', '-e', harness], capture_output=True, text=True, check=True)
    actual = json.loads(completed.stdout)
    assert actual['reloads'] == reloads
    if not reloads:
        assert actual['message'] == message
