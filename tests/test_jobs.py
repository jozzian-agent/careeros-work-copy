"""Chunk 3 contracts; no intake test is allowed to reach the network."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import pytest
from careeros import ingest, intake, vault
from careeros.server import create_app
from careeros.web.ui import JS as UI_JS

ROOT = Path(__file__).resolve().parents[1]

def llm_client_for(content):
    """Minimal stand-in LLM client, same shape as test_ingest.py's client_for."""
    create = Mock(return_value=SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(content=content))]))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

@pytest.fixture
def client(tmp_path):
    shutil.copytree(ROOT/'sample/vault', tmp_path/'vault')
    return create_app(tmp_path/'vault').test_client()

@pytest.mark.parametrize('kind,prefix', [('jobs','JOB'),('companies','CO')])
def test_roundtrip(tmp_path, kind, prefix):
    save = vault.save_job if kind=='jobs' else vault.save_company
    load = vault.load_job if kind=='jobs' else vault.load_company
    listing = vault.list_jobs if kind=='jobs' else vault.list_companies
    allocate = vault.next_job_id if kind=='jobs' else vault.next_company_id
    data = {'title':'Builder', 'url':'https://fiction.example/job'} if kind=='jobs' else {'name':'Fiction Studio'}
    assert listing(tmp_path)==[]
    assert allocate(tmp_path)==prefix+'-001'
    first=save(tmp_path,data)
    assert load(tmp_path,first['id'])==first
    assert allocate(tmp_path)==prefix+'-002'
    second=save(tmp_path,data)
    updated=save(tmp_path,{'notes':'**hello**'},first['id'])
    assert updated['notes']=='**hello**'
    assert len(listing(tmp_path))==2
    for name, content in [('bad','['),('list','- value'),('empty','')]:
        (tmp_path/kind/(name+'.yaml')).write_text(content)
    assert len(listing(tmp_path))==2
    assert second['id']==prefix+'-002'

@pytest.mark.parametrize('url,html,title,company,source', [
 ('https://boards.greenhouse.io/fiction/jobs/123','<meta property="og:title" content="Platform Lead | Careers"><meta property="og:site_name" content="Moonbutton">','Platform Lead','Moonbutton','Greenhouse'),
 ('https://careers.fiction.co.uk/role','<title>Engineer - Fiction Careers</title>','Engineer','Fiction','fiction.co.uk'),
 ('https://fiction.example/senior-builder','','senior builder','Fiction','fiction.example'),
])
def test_extraction(url,html,title,company,source):
    result=intake.extract(url,html)
    assert (result['title'],result['company'],result['source'])==(title,company,source)

@pytest.mark.parametrize('text,disclosed', [('Salary USD 120,000 - 150,000 annually',True),('Compensation EUR 90k',True),('CHF 120000',True),('Our product costs USD 40',False),('Competitive salary',False)])
def test_salary(text,disclosed):
    result=intake.extract('https://fiction.example/job',text)
    assert result['salary_info'] is disclosed
    assert bool(result['salary_note']) is disclosed

@pytest.mark.parametrize('meta,expected', [('<meta itemprop="datePublished" content="2026-09-25T10:00:00Z">','2026-09-25'),('<meta name="date" content="invalid">',None),('2026-09-25',None)])
def test_dates(meta,expected):
    assert intake.extract('https://fiction.example/job',meta)['posted_date']==expected

# m10: expected final ingest_state is chosen from the input fixture (what
# body text, if any, the fetch yields), never read back off the response
# under test. Real body text is attempted and, since no LLM is configured
# in this test environment, fails visibly ('extract_failed', settling only
# after the background worker runs); a fetch that raises never gets to
# extraction at all ('fetch_failed'). Meta-only html (O2, fix round 2: the
# verification round's probe found this settling at 'fetched'/error None
# forever, a dead pipeline that looked healthy) has no body text at all, so
# Phase B itself now recognizes "fetched but nothing extractable" as a
# failure and settles there synchronously, before the response is even
# returned -- not via the async worker's callback, which never gets real
# text to fail over in the first place.
@pytest.mark.parametrize('html,expected_final_state,expected_reason,settles_synchronously', [
    ('<meta property="og:title" content="Builder | Careers"><meta property="og:site_name" content="Moonbutton">',
     'extract_failed', 'empty_content', True),
    ('<title>Builder</title><p>Remote London</p>', 'extract_failed', 'not_configured', False),
    (None, 'fetch_failed', None, True),
])
def test_intake(client,monkeypatch,html,expected_final_state,expected_reason,settles_synchronously):
    calls=[]
    def fetch(url):
        calls.append(url)
        if html is None:
            raise TimeoutError()
        return html
    monkeypatch.setattr(intake,'fetch_url',fetch)
    response=client.post('/api/jobs/intake',json={'url':'https://fiction.example/platform-builder'})
    assert response.status_code==201
    data=response.json
    assert calls==['https://fiction.example/platform-builder']
    assert data['job']['company_id']==data['company']['id']
    assert data['job']['status']=='new' and data['job']['enriched'] is False
    assert data['job']['added']==date.today().isoformat()
    assert data['company']['website'] == 'https://fiction.example'
    client.application.config['LLM_THREADS'][data['job']['id']].join(timeout=2)
    after = client.get('/api/jobs/'+data['job']['id']).json
    assert after['llm_pending'] is False
    assert after['ingest_state'] == expected_final_state
    if settles_synchronously:
        # Already final in the very first response; the background worker
        # (still started, per the LLM_THREADS contract above) is a no-op.
        assert data['job']['ingest_state'] == expected_final_state
        assert after == data['job'] | {'llm_pending': False}
        if expected_reason:
            assert data['job']['ingest_error']['reason'] == expected_reason
    else:
        # A real attempt was made over real text and found nothing usable;
        # the failure must be visible (JOZ-265 global rule 2), not silent.
        assert data['job']['ingest_state'] == 'fetched' and data['job']['ingest_error'] is None
        # R2: no LLM_BASE_URL is set in this test environment, so the
        # specific reason is 'not_configured', not a generic catch-all.
        assert after['ingest_error'] == {'stage': 'extract', 'reason': expected_reason, 'at': after['ingest_error']['at']}
        before_events = [event['event'] for event in data['job']['history']]
        after_events = [event['event'] for event in after['history']]
        assert after_events[:len(before_events)] == before_events
        assert after_events[len(before_events):] == ['extract_failed']
        ignore = {'ingest_state', 'ingest_error', 'history', 'llm_pending'}
        assert {k: v for k, v in after.items() if k not in ignore} == \
               {k: v for k, v in data['job'].items() if k not in ignore}
    if html is None:
        assert data['job']['title']=='platform builder'


def test_dedupe(client,monkeypatch):
    monkeypatch.setattr(intake,'fetch_url',lambda url:'<meta property="og:site_name" content="pEbBlEoRbIt StUdIo">')
    before=len(client.get('/api/companies').json)
    data=client.post('/api/jobs/intake',json={'url':'https://fiction.example/job'}).json
    assert data['company']['id']=='CO-001'
    assert len(client.get('/api/companies').json)==before


def test_crud_and_routes(client):
    for route in ['/jobs','/jobs/JOB-001','/companies','/companies/CO-001','/api/jobs','/api/jobs/JOB-001','/api/companies','/api/companies/CO-001']:
        assert client.get(route).status_code==200
    result=client.put('/api/jobs/JOB-001',json={'status':'applied','notes':'**Ready** <script>bad()</script>'})
    assert result.status_code==200
    assert result.json['status_changed']==date.today().isoformat()
    assert result.json['title']=='Platform Engineering Lead'
    html=client.get('/jobs/JOB-001').text
    assert '<strong>Ready</strong>' in html and '<script>bad()</script>' not in html
    assert client.put('/api/jobs/JOB-001',json={'status':'bogus'}).status_code==400
    assert client.put('/api/companies/CO-001',json={'sector':'Tools','locations':['Remote'],'notes':'**Studio**'}).status_code==200
    assert '<strong>Studio</strong>' in client.get('/companies/CO-001').text
    assert client.delete('/api/jobs/JOB-001').status_code==200
    for route in ['/api/jobs/JOB-001','/jobs/JOB-001','/api/companies/CO-999','/companies/CO-999']:
        assert client.get(route).status_code==404
    assert client.put('/api/jobs/JOB-001',json={}).status_code==404
    assert client.delete('/api/jobs/JOB-001').status_code==404

@pytest.mark.parametrize('payload', [{'status':[]},{'salary_info':'yes'},{'remote_ok':1},{'custom':[]},{'added':'bad'},{'company_id':'CO-999'},{'url':'javascript:alert(1)'},{'original_url':'data:text/html,bad'}])
def test_invalid_job(client,payload):
    assert client.put('/api/jobs/JOB-001',json=payload).status_code==400

@pytest.mark.parametrize('payload', [{'name':''},{'locations':'Remote'},{'website':'javascript:alert(1)'},{'sector':12},{'custom':[]}])
def test_invalid_company(client,payload):
    assert client.put('/api/companies/CO-001',json=payload).status_code==400

@pytest.mark.parametrize('payload', [{'url':'file:///etc/passwd'},{'url':''},{'url':None},[],{}])
def test_invalid_intake(client,payload):
    assert client.post('/api/jobs/intake',json=payload).status_code==400


def test_board_badges(client):
    html=client.get('/jobs').text
    assert html.count('class="chip salary-badge"')==1
    for title in ['Platform Engineering Lead','Developer Tools Manager','Staff Backend Engineer','Engineering Manager']:
        assert title in html
    assert 'Enrichment pending' in html
    assert '2 open jobs' in client.get('/companies').text
    assert client.put('/api/jobs/JOB-001',json={'status':'closed'}).status_code==200
    assert '1 open jobs' in client.get('/companies').text


def test_host_path_not_introduced():
    forbidden='/root/'+'career-os'
    for folder in ('careeros','tests','scripts','sample','docs'):
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and path.suffix in ('.py','.md','.yaml','.html'):
                count=path.read_text().count(forbidden)
                assert count==(1 if path==ROOT/'careeros/server.py' else 0), path


REAL_FETCH = intake.fetch_url


@pytest.mark.parametrize('address', ['127.0.0.1', '169.254.169.254', '192.168.1.1', '::1', '0.0.0.0', '224.0.0.1', '240.0.0.1'])
def test_private_destination_rejected(monkeypatch, address):
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', (address, 80))])
    url = 'http://' + ('[' + address + ']' if ':' in address else address) + '/x'
    with pytest.raises(ValueError, match='public'):
        intake.check_url(url)
    with pytest.raises(ValueError, match='public'):
        REAL_FETCH(url)


def test_public_destination_and_mixed_dns(monkeypatch):
    assert intake.check_url('https://fiction.example/job') == 'https://fiction.example/job'
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('8.8.8.8', 443)), (2, 1, 6, '', ('10.0.0.1', 443))])
    with pytest.raises(ValueError, match='public'):
        intake.check_url('https://fiction.example/job')


def test_redirect_to_private_rejected(monkeypatch):
    from urllib.request import HTTPRedirectHandler
    def opener(*handlers):
        redirect = next(h for h in handlers if isinstance(h, HTTPRedirectHandler))
        class FakeOpener:
            def open(self, request, timeout):
                return redirect.redirect_request(request, None, 302, 'Found', {}, 'http://127.0.0.1/x')
        return FakeOpener()
    monkeypatch.setattr('urllib.request.build_opener', opener)
    with pytest.raises(ValueError, match='[Rr]edirect'):
        REAL_FETCH('https://fiction.example/job')


def test_fetch_deadline_fallback(client, monkeypatch):
    from unittest.mock import Mock
    import time
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    def slow_read(*args):
        time.sleep(.08)
        return b'x'
    response.read1 = slow_read
    response.read = slow_read
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr('urllib.request.build_opener', lambda *a: opener)
    monkeypatch.setattr(intake, 'FETCH_BUDGET', .02, raising=False)
    monkeypatch.setattr(intake, 'fetch_url', REAL_FETCH)
    with pytest.raises(TimeoutError, match='deadline'):
        REAL_FETCH('https://fiction.example/job')
    result = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/slow-role'})
    assert result.status_code == 201
    assert result.json['job']['title'] == 'slow role'
    assert result.json['job']['url'] == 'https://fiction.example/slow-role'


@pytest.mark.parametrize('salary', [True, False])
def test_curated_job_detail(client, salary):
    client.put('/api/jobs/JOB-001', json={'salary_info': salary, 'remote_ok': True, 'salary_note': '<b>Pay</b>'})
    html = client.get('/jobs/JOB-001').text
    for value in ['Platform Engineering Lead', 'Harbourline', 'pebbleorbit.example', '2026-09-25', '2026-10-01', 'Posted date', 'Added date', '>Remote<', 'Enrichment pending']:
        assert value in html
    for value in ['<dt>Custom</dt>', 'Salary Info', '<dd>True</dd>', '<dd>False</dd>', '<dt>Company Id</dt>', '<dt>Url</dt>']:
        assert value not in html
    assert ('Salary disclosed' in html) is salary
    if salary:
        assert '&lt;b&gt;Pay&lt;/b&gt;' in html


def test_external_link_markup(client):
    html = client.get('/jobs/JOB-001').text
    assert ('href="https://pebbleorbit.example/careers/platform-engineering-lead" '
            'target="_blank" rel="noopener noreferrer" class="external"') in html
    internal_link = '<a href="/companies/CO-001">Pebbleorbit Studio</a>'
    assert internal_link in html


def test_external_link_markup_both_urls(client):
    html = client.get('/jobs/JOB-005').text
    assert html.count('class="external"') == 2
    assert html.count('target="_blank"') == 2
    assert 'Open posting' in html and 'Original posting' in html


def schema_html(**values):
    import json
    data = {'@type': 'JobPosting', 'title': 'Platform Builder',
            'hiringOrganization': {'name': 'Lanternpeak Labs', 'sameAs': 'https://lanternpeak.example'},
            'jobLocation': {'address': {'addressLocality': 'Basel', 'addressCountry': 'CH'}},
            'datePosted': '2026-09-20', 'employmentType': 'FULL_TIME', 'validThrough': '2026-12-01'}
    data.update(values)
    return '<script type="application/ld+json">'+json.dumps({'@graph': [data]})+'</script>'


@pytest.mark.parametrize('salary', ["CHF 95'000 - 110'000", 'CHF 95,000–110,000'])
def test_personio_schema(salary):
    result = intake.extract('https://lanternpeak.jobs.personio.de/job/123', schema_html(description=salary)+'<meta property="og:title" content="Wrong">')
    assert result['title'] == 'Platform Builder'
    assert result['company'] == 'Lanternpeak Labs'
    assert result['source'] == 'Personio'
    assert result['website'] == 'https://lanternpeak.example'
    assert result['salary_info'] and salary in result['salary_note']
    assert result['location'] == 'Basel, CH'
    assert result['posted_date'] == '2026-09-20'
    assert result['employment_type'] == 'FULL_TIME'
    assert result['valid_through'] == '2026-12-01'


@pytest.mark.parametrize('hostpath,label', [
    ('jobs.personio.de/lantern-peak/123','Personio'),
    ('lantern-peak.jobs.personio.com/job/123','Personio'),
    ('boards.greenhouse.io/lantern-peak/jobs/123','Greenhouse'),
    ('job-boards.greenhouse.io/lantern-peak/jobs/123','Greenhouse'),
    ('jobs.lever.co/lantern-peak/123','Lever'),
    ('apply.workable.com/lantern-peak/123','Workable'),
    ('lantern-peak.workable.com/123','Workable'),
    ('jobs.ashbyhq.com/lantern-peak/123','Ashby'),
    ('careers.smartrecruiters.com/lantern-peak/123','SmartRecruiters'),
    ('lantern-peak.smartrecruiters.com/123','SmartRecruiters'),
    ('lantern-peak.bamboohr.com/careers/123','BambooHR'),
    ('lantern-peak.monday.com/123','Monday'),
])
def test_ats_slugs(hostpath,label):
    url = 'https://' + hostpath
    result = intake.extract(url, '<title>Builder</title>')
    assert result['company'] == 'Lantern Peak'
    assert result['source'] == label and result['original_url'] == url


@pytest.mark.parametrize('html,company', [
    ('<meta property="og:site_name" content="jobs.ch"><title>Builder</title>', ''),
    ('<meta property="og:title" content="Builder at Lanternpeak Labs">', 'Lanternpeak Labs'),
    ('<p>Company: Lanternpeak Labs</p>', 'Lanternpeak Labs'),
    (schema_html(), 'Lanternpeak Labs'),
])
def test_jobs_ch(html,company):
    assert intake.extract('https://www.jobs.ch/en/vacancies/123',html)['company'] == company


def test_unknown_company_intake(client, monkeypatch):
    monkeypatch.setattr(intake,'fetch_url',lambda url:'<title>Builder</title>')
    response=client.post('/api/jobs/intake',json={'url':'https://jobs.ch/en/vacancies/123'})
    assert response.status_code == 201
    assert response.json['company'] is None
    assert response.json['job']['company_id'] is None


def test_enrich_merge(client,monkeypatch):
    vault.save_job(client.application.config['VAULT_PATH'], {'source':'','location':'','posted_date':None,'salary_info':False,'salary_note':''}, 'JOB-001')
    client.put('/api/jobs/JOB-001',json={'title':'Owner title','notes':'Owner notes','custom':{'keep':1},'status':'applied'})
    monkeypatch.setattr(intake,'fetch_url',lambda url:schema_html(description="CHF 95'000 - 110'000"))
    response=client.post('/api/jobs/JOB-001/enrich')
    assert response.status_code == 200
    job=response.json
    assert (job['title'],job['notes'],job['status'],job['custom']) == ('Owner title','Owner notes','applied',{'keep':1})
    assert job['location'] == 'Basel, CH' and job['posted_date'] == '2026-09-20'
    assert job['salary_info'] and job['enriched']
    # M3: the shared ladder never silently renames or relinks an already
    # (weakly) linked company just because the posting's employer text
    # differs -- it stays on the job's existing company and flags review.
    assert job['company_id'] == 'CO-001'
    assert client.get('/api/companies/CO-001').json['name'] == 'Pebbleorbit Studio'
    assert job['company_link_state'] == 'needs_review'
    assert job['employer_named_in_posting'] == 'Lanternpeak Labs'
    assert 'id="enrich-job"' not in client.get('/jobs/JOB-001').text


def test_enrich_failure_unchanged(client,monkeypatch):
    before=client.get('/api/jobs/JOB-001').json
    companies=client.get('/api/companies').json
    def fail(url):
        raise TimeoutError()
    monkeypatch.setattr(intake,'fetch_url',fail)
    assert client.post('/api/jobs/JOB-001/enrich').status_code == 422
    assert client.get('/api/jobs/JOB-001').json == before
    assert client.get('/api/companies').json == companies
    assert client.post('/api/jobs/missing/enrich').status_code == 404


def test_enrich_private_guard(client,monkeypatch):
    client.put('/api/jobs/JOB-001',json={'url':'http://127.0.0.1/posting'})
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**kw:[(2,1,6,'',('127.0.0.1',80))])
    calls=[]
    monkeypatch.setattr(intake,'fetch_url',lambda url:calls.append(url))
    assert client.post('/api/jobs/JOB-001/enrich').status_code == 422
    assert not calls


def test_job_views(client):
    html=client.get('/jobs').text
    assert 'id="view-toggle"' in html and 'id="enrich-pending"' in html
    for status in vault.STATUSES:
        assert 'data-column="'+status+'"' in html
    for label in ['Title','Company','Source','Status','Location','Posted','Added']:
        assert '>'+label+'</button></th>' in html
    assert 'id="enrich-job"' in client.get('/jobs/JOB-001').text


def test_enrich_company_dedupe_and_exclusive_rename(client,monkeypatch):
    # M3 (JOZ-266 fix round): /enrich now routes company linking through
    # the shared ladder. A conflicting employer name no longer silently
    # renames the auto-created company in place, and an exact match
    # elsewhere no longer silently steals the job away from its existing
    # link -- both surface for owner review instead (never silently keep
    # a provisional guess uncontested, never silently relink).
    monkeypatch.setattr(intake,'fetch_url',lambda url:schema_html(hiringOrganization={'name':'Exclusive Test Labs'}))
    created=client.post('/api/jobs/intake',json={'url':'https://jobs.personio.de/lanternpeak/123'}).json
    identifier=created['job']['id']
    company_id=created['company']['id']
    assert created['company']['name_source'] == 'auto'
    monkeypatch.setattr(intake,'fetch_url',lambda url:schema_html(hiringOrganization={'name':'Renamed Labs','url':'https://renamed.example'}))
    first=client.post('/api/jobs/'+identifier+'/enrich').json
    assert first['company_id'] == company_id
    assert first['company_link_state'] == 'needs_review'
    assert client.get('/api/companies/'+company_id).json['name'] == 'Exclusive Test Labs'
    monkeypatch.setattr(intake,'fetch_url',lambda url:schema_html(hiringOrganization={'name':'pEbBlEoRbIt StUdIo'}))
    second=client.post('/api/jobs/'+identifier+'/enrich').json
    assert second['company_id'] == company_id
    assert second['company_link_state'] == 'needs_review'
    candidates = second['company_review']['candidates']
    assert candidates and candidates[0]['company_id'] == 'CO-001'
    assert len(client.get('/api/companies').json) == 5


def test_invalid_schema_and_website():
    html='<script type="application/ld+json">invalid</script>'+schema_html(hiringOrganization={'name':'Labs','sameAs':'javascript:bad','url':'https://labs.example'})
    assert intake.extract('https://jobs.lever.co/labs/123',html)['website'] == 'https://labs.example'


def test_enrich_preserves_shared_company(client, monkeypatch):
    # M3: a shared company (more than one job linked) is never forked into
    # a second, duplicate company just because one of its jobs' posting
    # text no longer matches exactly -- the ladder flags review and keeps
    # the existing link instead (no duplicate company without identifiers).
    before_count = len(client.get('/api/companies').json)
    assert client.post('/api/companies/CO-001/enrich').status_code == 200
    before = client.get('/api/companies/CO-001').json
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html(hiringOrganization={'name':'Different Test Labs'}))
    result = client.post('/api/jobs/JOB-001/enrich')
    assert result.status_code == 200
    assert result.json['company_id'] == 'CO-001'
    assert result.json['company_link_state'] == 'needs_review'
    assert len(client.get('/api/companies').json) == before_count
    assert client.get('/api/companies/CO-001').json == before


@pytest.mark.parametrize('wrapper', ['array', 'object'])
def test_schema_shapes(wrapper):
    import json
    node = {'title':'Structured title', 'hiringOrganization':{'name':'Structured Employer'}}
    value = [node] if wrapper == 'array' else node
    result = intake.extract('https://jobs.lever.co/fallback/123', '<script type="application/ld+json">'+json.dumps(value)+'</script>')
    assert result['company'] == 'Structured Employer'
    assert result['title'] == 'Structured title'


@pytest.mark.parametrize('matching', [True, False])
@pytest.mark.parametrize('website', [None, 'https://owner.example'])
def test_enrich_owner_company(client, monkeypatch, matching, website):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html(hiringOrganization={'name':'Exclusive Auto Labs', 'url':'https://lanternpeak.example'}))
    created = client.post('/api/jobs/intake', json={'url':'https://fiction.example/job'}).json
    cid, jid = created['company']['id'], created['job']['id']
    name = 'Exclusive Auto Labs' if matching else 'Owner Verified Labs'
    edited = client.put('/api/companies/'+cid, json={'name':name, 'website':website}).json
    assert client.post('/api/jobs/'+jid+'/enrich').status_code == 200
    company = client.get('/api/companies/'+cid).json
    assert company['name'] == name
    assert company['website'] == (website or 'https://lanternpeak.example')
    assert edited['name_source'] == 'owner'


def test_enrich_salary_only_first_time(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html(description='Salary CHF 120000'))
    vault.save_job(client.application.config['VAULT_PATH'], {'salary_info':False, 'salary_note':''}, 'JOB-001')
    first = client.post('/api/jobs/JOB-001/enrich').json
    assert first['salary_info'] and first['salary_note']
    client.put('/api/jobs/JOB-001', json={'salary_info':False, 'salary_note':'', 'location':''})
    second = client.post('/api/jobs/JOB-001/enrich').json
    assert second['salary_info'] is False and second['salary_note'] == ''
    assert second['location'] == ''
    assert second['field_provenance']['location'] == 'user'


def test_enrich_fetch_outside_save_inside_lock(tmp_path, monkeypatch):
    from careeros import server
    shutil.copytree(ROOT/'sample/vault', tmp_path/'vault')
    class LockSpy:
        held = False
        def __enter__(self):
            self.held = True
        def __exit__(self, *args):
            self.held = False
    lock = LockSpy()
    monkeypatch.setattr(server, 'RLock', lambda: lock)
    client = server.create_app(tmp_path/'vault').test_client()
    phases = []
    def fetch(url):
        phases.append(('fetch', lock.held))
        return schema_html()
    save = vault.save_job
    def save_spy(*args, **kwargs):
        phases.append(('save', lock.held))
        return save(*args, **kwargs)
    monkeypatch.setattr(intake, 'fetch_url', fetch)
    monkeypatch.setattr(vault, 'save_job', save_spy)
    assert client.post('/api/jobs/JOB-001/enrich').status_code == 200
    assert phases == [('fetch', False), ('save', True)]


@pytest.mark.parametrize('salary', ['95,000-110,000 CHF', '120k-150k USD', 'CHF 95,000-110,000', '3 years experience'])
def test_trailing_salary(salary):
    assert intake.extract('https://fiction.example/job', salary)['salary_info'] is (salary != '3 years experience')


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('field,value', [('url','https://fiction.example/job'), ('url','/job'), ('mainEntityOfPage',{'@id':'https://fiction.example/job'})])
def test_multiple_postings_url_match(reverse, field, value):
    first = schema_html(title='Requested job', **{field:value})
    second = schema_html(title='Similar job', url='https://fiction.example/other')
    html = second+first if reverse else first+second
    assert intake.extract('https://fiction.example/job', html)['title'] == 'Requested job'
    assert intake.extract('https://fiction.example/unmatched', html)['title'] == ('Similar job' if reverse else 'Requested job')


def test_mobile_sort_markup(client):
    html = client.get('/jobs').text
    assert 'for="job-sort">Sort by' in html
    assert '<select id="job-sort">' in html
    assert '<thead><tr>' in html
    assert 'value="6:desc">Added (descending)' in html


def test_unknown_company_provenance(client, monkeypatch):
    root = client.application.config['VAULT_PATH']
    company = vault.save_company(root, {'name':'Legacy owner', 'website':'https://owner.example'})
    job = vault.save_job(root, {'title':'Legacy', 'url':'https://fiction.example/job', 'company_id':company['id']})
    import yaml
    path = next(p for p in (root/'companies').glob('*.yaml') if yaml.safe_load(p.read_text())['id'] == company['id'])
    data = yaml.safe_load(path.read_text())
    data.pop('name_source')
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html())
    assert client.post('/api/jobs/'+job['id']+'/enrich').json['company_id'] == company['id']
    assert vault.load_company(root, company['id'])['name'] == 'Legacy owner'
    assert vault.load_company(root, company['id'])['website'] == 'https://owner.example'


@pytest.mark.parametrize('website', [None, 'https://kept.example'])
def test_matching_auto_company_offers_exact_match_as_review_candidate(client, monkeypatch, website):
    # M3: an exact name match to a DIFFERENT, auto-named company than the
    # one already (weakly) linked is surfaced as a review candidate --
    # never a silent switch (JOB-001 stays on CO-001; the unrelated
    # "Matching Auto Labs" company it exactly matches is untouched).
    root = client.application.config['VAULT_PATH']
    company = vault.save_company(root, {'name':'Matching Auto Labs', 'name_source':'auto', 'website':website})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html(hiringOrganization={'name':'Matching Auto Labs', 'url':'https://lanternpeak.example'}))
    result = client.post('/api/jobs/JOB-001/enrich').json
    assert result['company_id'] == 'CO-001'
    assert result['company_link_state'] == 'needs_review'
    candidates = result['company_review']['candidates']
    assert candidates and candidates[0]['company_id'] == company['id']
    assert vault.load_company(root, company['id'])['website'] == website


def test_company_any_put_marks_owner(client):
    edited = client.put('/api/companies/CO-001', json={'notes':'Verified', 'name_source':'auto'})
    assert edited.status_code == 200
    assert edited.json['name_source'] == 'owner'


@pytest.mark.parametrize('mutation', ['edit', 'delete', 'url'])
def test_enrich_reloads_after_fetch(client, monkeypatch, mutation):
    def fetch(url):
        if mutation == 'delete':
            assert client.delete('/api/jobs/JOB-001').status_code == 200
        else:
            payload = {'url':'https://fiction.example/new'} if mutation == 'url' else {'location':'Owner location', 'enriched':True, 'salary_info':False, 'salary_note':''}
            assert client.put('/api/jobs/JOB-001', json=payload).status_code == 200
        return schema_html(description='Salary CHF 120000')
    monkeypatch.setattr(intake, 'fetch_url', fetch)
    response = client.post('/api/jobs/JOB-001/enrich')
    assert response.status_code == {'edit':200, 'delete':404, 'url':409}[mutation]
    if mutation == 'edit':
        assert response.json['location'] == 'Owner location'
        assert response.json['salary_info'] is False
    elif mutation == 'delete':
        assert client.get('/api/jobs/JOB-001').status_code == 404
    else:
        assert client.get('/api/jobs/JOB-001').json['enriched'] is False


def test_delete_company_storage(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Disposable'})
    assert vault.delete_company(tmp_path, company['id'])
    assert vault.load_company(tmp_path, company['id']) is None
    with pytest.raises(ValueError, match='not found'):
        vault.delete_company(tmp_path, company['id'])


def test_delete_company_api_roundtrip(client):
    created = client.post('/api/jobs/intake', json={'url':'https://disposable.example/job'}).json
    cid, jid = created['company']['id'], created['job']['id']
    blocked = client.delete('/api/companies/'+cid)
    assert blocked.status_code == 409
    assert blocked.json == {'error':'Still linked to 1 jobs', 'count':1}
    assert client.get('/api/jobs/'+jid).status_code == 200
    assert client.delete('/api/jobs/'+jid).status_code == 200
    assert client.delete('/api/companies/'+cid).json == {'deleted':cid}
    assert client.get('/api/companies/'+cid).status_code == 404
    assert client.get('/companies/'+cid).status_code == 404
    assert client.delete('/api/companies/'+cid).status_code == 404


@pytest.mark.parametrize('kind,identifier,label', [('jobs','JOB-001','Delete job'), ('companies','CO-001','Delete company')])
def test_delete_detail_buttons(client, kind, identifier, label):
    html = client.get('/'+kind+'/'+identifier).text
    assert label in html and 'class="danger"' in html
    singular = 'job' if kind == 'jobs' else 'company'
    record = client.get('/api/'+kind+'/'+identifier).json
    name = record['title' if kind == 'jobs' else 'name']
    assert '<dialog id="confirm">' in html
    assert f'Are you sure you want to delete this {singular}?' in html
    assert f'This removes {name} from your {kind}.' in html
    assert f'<button id="cancel-delete" autofocus>Keep {singular}</button>' in html
    assert f'<button class="danger" id="confirm-delete">{label}</button>' in html
    assert f"document.getElementById('delete-{singular}').onclick=()=>dialog.showModal()" in html
    assert "document.getElementById('cancel-delete').onclick=()=>dialog.close()" in html
    assert f"await api('/api/{kind}/'+" in html and "'DELETE'" in html
    assert f"location.href='/{kind}'" in html
    assert 'dialog.close();toast(err.message,true)' in html
    assert 'confirm(' not in html
    assert label not in client.get('/'+kind).text


def rich_schema(employees=125):
    return schema_html(
        hiringOrganization={'name':'Rich Labs', 'url':'https://rich.example',
                            'industry':'Software', 'numberOfEmployees':employees,
                            'address':{'addressLocality':'Bern', 'addressCountry':'CH'}},
        jobLocation=[{'address':{'addressLocality':'Basel', 'addressRegion':'BS',
                                'addressCountry':{'name':'CH'}}}])


@pytest.mark.parametrize('employees,bucket', [(1,'1-10'), (10,'1-10'), (11,'11-50'),
    (50,'11-50'), (51,'51-200'), (200,'51-200'), (201,'201-1000'),
    (1000,'201-1000'), (1001,'1000+'), ({'@type':'QuantitativeValue','value':125},'51-200'),
    (None,None), ('unknown',None)])
def test_company_size_extraction(employees, bucket):
    assert intake.extract('https://rich.example/job', rich_schema(employees))['size'] == bucket


def test_rich_company_intake(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: rich_schema())
    data = client.post('/api/jobs/intake', json={'url':'https://rich.example/job'}).json
    assert data['company']['sector'] == 'Software'
    # With a raw employee count present, the creation payload carries the
    # atomically derived pair and drops the bucket-only legacy string, so
    # size_range and size_class always come from the same count in one write.
    assert data['company']['size'] is None
    assert data['company']['size_range'] == '51-200'
    assert data['company']['size_class'] == 'medium'  # 125 employees per EU thresholds
    assert data['company']['locations'] == ['Basel','BS','CH']
    assert data['job']['location'] == 'Basel, BS, CH'


@pytest.mark.parametrize('action', ['intake','enrich'])
@pytest.mark.parametrize('owner_values', [False, True])
def test_company_metadata_fill_only(client, monkeypatch, action, owner_values):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html(hiringOrganization={'name':'Rich Labs'}, jobLocation=[]))
    created = client.post('/api/jobs/intake', json={'url':'https://rich.example/job'}).json
    cid = created['company']['id']
    values = {'sector':'Owner sector', 'size':'Owner size', 'locations':['Owner location']} if owner_values else {'sector':None,'size':None,'locations':[]}
    client.put('/api/companies/'+cid, json=values)
    monkeypatch.setattr(intake, 'fetch_url', lambda url: rich_schema())
    response = client.post('/api/jobs/intake', json={'url':'https://rich.example/other'}) if action == 'intake' else client.post('/api/jobs/'+created['job']['id']+'/enrich')
    assert response.status_code in (200,201)
    company = client.get('/api/companies/'+cid).json
    expected = values if owner_values else {'sector':'Software','size':'51-200','locations':['Basel','BS','CH']}
    assert {key:company[key] for key in expected} == expected
    assert company['name_source'] == 'owner'


def test_company_missing_metadata(client):
    data = client.post('/api/jobs/intake', json={'url':'https://empty.example/job'}).json
    assert data['company']['sector'] is None
    assert data['company']['size'] is None
    assert data['company']['locations'] == []


@pytest.mark.parametrize('location,remote_ok,expected', [
    ('Hybrid, Zurich, Remote', True, False),
    ('REMOTE', True, False),
    ('remote', True, False),
    ('Zurich', True, True),
    ('Zurich', False, False),
    ('Remote', False, False),
    (None, True, True),
    ('', True, True),
    ('Remotedorf', True, True),
    ('Remotenberg, CH', True, True),
])
def test_show_remote_chip(location, remote_ok, expected):
    from careeros.web.pages.jobs import show_remote_chip
    assert show_remote_chip({'location': location, 'remote_ok': remote_ok}) is expected


@pytest.mark.parametrize('location,remote_ok,mentions,chip', [
    ('Hybrid, Zurich, Remote', True, 1, False),
    ('Hybrid, Zurich, REMOTE', True, 1, False),
    ('Zurich', True, 1, True),
    ('Zurich', False, 0, False),
    ('Remote', False, 1, False),
])
def test_job_detail_location_and_header(client, location, remote_ok, mentions, chip):
    root = client.application.config['VAULT_PATH']
    vault.save_job(root, {'location': location, 'remote_ok': remote_ok}, 'JOB-001')
    response = client.get('/jobs/JOB-001')
    assert response.status_code == 200
    html = response.text
    assert html.lower().count('remote') == mentions
    assert ('<span class="chip">Remote</span>' in html) is chip
    title = vault.load_job(root, 'JOB-001')['title']
    assert f'<div class="page-header job-detail-header spaced"><h1>{title}</h1><small class="muted">JOB-001</small></div>' in html
    assert vault.load_job(root, 'JOB-001')['location'] == location


def test_kanban_move_markup(client):
    import re
    from html import escape
    html = client.get('/jobs').text
    cards = re.findall(r'<article class="card job-card"(.*?)</article>', html, re.S)
    records = client.get('/api/jobs').json
    assert len(cards) == len(records)
    for job in records:
        card = next(card for card in cards if f'data-id="{job["id"]}"' in card)
        assert 'draggable="true"' in card
        assert 'tabindex="0"' not in card
        assert f'data-status="{job["status"]}"' in card
        assert f'aria-label="Move {escape(job["title"], quote=True)} to"' in card
        for status in vault.STATUSES:
            assert f'value="{status}"' in card
        assert f'value="{job["status"]}" selected' in card
    for event in ('dragstart', 'dragover', 'drop', 'dragend'):
        assert f"cards.addEventListener('{event}'" in html
    assert "moveJob(e.target.closest('.job-card'),e.target.value)" in html
    assert "await api(url,'PUT',{status})" in html
    assert "api(url,'GET')" not in html
    assert 'origin.insertBefore(card,' in html
    assert 'row.dataset.status=value' in html


def test_kanban_refresh_hooks(client):
    html = client.get('/jobs').text
    assert "window.addEventListener('pageshow',e=>{if(e.persisted)refresh()" in html
    assert "document.addEventListener('visibilitychange'" in html
    assert 'elapsed>30000' in html
    assert "fetch('/jobs',{cache:'no-store'})" in html
    assert 'if(pendingMoves||dragged){refreshQueued=true;return;}' in html


def test_kanban_rendered_styles(client):
    import re
    from careeros.web import theme
    html = client.get('/jobs').text
    styles = ''.join(re.findall(r'<style>(.*?)</style>', html, re.S))
    assert theme.CSS_VARS in styles
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b', styles.replace(theme.CSS_VARS, ''))
    assert '.kanban-column.drag-over {' in styles
    assert '-webkit-line-clamp:2;line-clamp:2;' in styles
    assert '.job-chips {display:flex;flex-wrap:wrap;gap:6px;}' in styles
    assert '.kanban {flex-direction:column;}' in styles
    assert 'button,.button,input,select {min-height:44px;}' in styles


def test_job_detail_ai_summary_badge(client):
    root = client.application.config['VAULT_PATH']
    vault.save_job(root, {'summary': 'Heuristic summary.'}, 'JOB-001')
    html = client.get('/jobs/JOB-001').text
    assert 'Heuristic summary.' in html
    assert 'AI-generated' not in html
    vault.save_job(root, {'summary': 'AI summary.', 'summary_source': 'ai'}, 'JOB-001')
    html = client.get('/jobs/JOB-001').text
    assert 'AI summary.' in html
    assert 'AI-generated' in html


def test_job_detail_extracted_sections(client):
    root = client.application.config['VAULT_PATH']
    vault.save_job(root, {'background': '5+ years experience.', 'skills': ['Python', 'SQL'],
                          'certifications': ['PMP'], 'responsibilities': ['Lead the team']}, 'JOB-001')
    html = client.get('/jobs/JOB-001').text
    assert 'Background required' in html and '5+ years experience.' in html
    assert 'class="job-chips"' in html and '>Python<' in html and '>SQL<' in html
    assert 'Certifications' in html and 'PMP' in html
    assert 'Responsibilities' in html and 'Lead the team' in html


def test_job_detail_hides_empty_extracted_sections(client):
    html = client.get('/jobs/JOB-001').text
    for label in ['Background required', '<h2>Skills</h2>', 'Certifications', 'Responsibilities',
                 'Original description', 'AI-generated']:
        assert label not in html


def test_job_detail_original_description_collapsible(client):
    root = client.application.config['VAULT_PATH']
    long_text = 'Paragraph one.\n\n' + ('Filler sentence. ' * 100)
    vault.save_job(root, {'description': long_text}, 'JOB-001')
    html = client.get('/jobs/JOB-001').text
    assert 'Original description' in html
    assert '<details>' in html and '<summary>Show full description</summary>' in html
    assert 'Paragraph one.' in html


def test_job_detail_short_description_not_collapsible(client):
    root = client.application.config['VAULT_PATH']
    vault.save_job(root, {'description': 'Short description.'}, 'JOB-001')
    html = client.get('/jobs/JOB-001').text
    assert 'Short description.' in html
    assert '<details>' not in html


def test_job_detail_reenrich_button_present(client):
    html = client.get('/jobs/JOB-001').text
    assert 'id="extract-job"' in html and 'Enrich with AI' in html
    assert 'id="extract-pending-chip"' not in html


def test_job_detail_shows_pending_ai_state(client, monkeypatch):
    import re
    from careeros import ingest
    from unittest.mock import Mock
    monkeypatch.setattr(ingest, 'extract_async', lambda description, callback: Mock(is_alive=lambda: True))
    assert client.post('/api/jobs/JOB-001/extract').status_code == 202
    html = client.get('/jobs/JOB-001').text
    assert 'id="extract-pending-chip"' in html
    assert re.search(r'id="extract-job"[^>]*\bdisabled\b', html)


def test_job_detail_polls_only_while_pending(client, monkeypatch):
    """MINOR 4: the page must poll for completion while enrichment is
    pending, and must not poll when it isn't."""
    from careeros import ingest
    from unittest.mock import Mock
    html = client.get('/jobs/JOB-001').text
    assert 'if(false)pollTimer=setInterval(checkEnrichment,4000)' in html
    monkeypatch.setattr(ingest, 'extract_async', lambda description, callback: Mock(is_alive=lambda: True))
    assert client.post('/api/jobs/JOB-001/extract').status_code == 202
    html = client.get('/jobs/JOB-001').text
    assert 'if(true)pollTimer=setInterval(checkEnrichment,4000)' in html
    assert 'data.llm_pending' in html
    assert 'notesOriginal' in html


def test_job_detail_whitespace_only_description_hides_section(client):
    """NIT 7: whitespace-only descriptions must not render an empty section."""
    root = client.application.config['VAULT_PATH']
    vault.save_job(root, {'description': ' ' * 1201}, 'JOB-001')
    html = client.get('/jobs/JOB-001').text
    assert 'Original description' not in html


def test_job_detail_description_boundary_1200_not_collapsible(client):
    root = client.application.config['VAULT_PATH']
    vault.save_job(root, {'description': 'a' * 1200}, 'JOB-001')
    html = client.get('/jobs/JOB-001').text
    assert 'Original description' in html
    assert '<details>' not in html


def test_job_detail_description_boundary_1201_reconstructs_exactly(client):
    import re
    root = client.application.config['VAULT_PATH']
    text = 'a' * 1200 + 'b'
    vault.save_job(root, {'description': text}, 'JOB-001')
    html = client.get('/jobs/JOB-001').text
    assert '<details>' in html
    preview = re.search(r'<p class="preserve">(a+)</p>', html).group(1)
    rest = re.search(r'<summary>Show full description</summary><p class="preserve">(.*?)</p>', html, re.S).group(1)
    assert len(preview) == 1200
    assert len(rest) == 1
    assert preview + rest == text


def test_job_detail_description_escapes_html_in_both_halves(client):
    root = client.application.config['VAULT_PATH']
    text = '<script>evil()</script>' * 60 + '<b>tail</b>'
    assert len(text) > 1200
    vault.save_job(root, {'description': text}, 'JOB-001')
    html = client.get('/jobs/JOB-001').text
    assert '<script>evil()' not in html
    assert '&lt;script&gt;evil()&lt;/script&gt;' in html
    assert '<b>tail</b>' not in html
    assert '&lt;b&gt;tail&lt;/b&gt;' in html


def test_full_record_status_update(client):
    fields = {'notes':'Keep notes', 'custom':{'keep':['detail']}, 'description':'Keep description', 'keywords':['Python']}
    assert client.put('/api/jobs/JOB-001', json=fields).status_code == 200
    current = client.get('/api/jobs/JOB-001').json
    updated = client.put('/api/jobs/JOB-001', json=current | {'status':'applied'})
    assert updated.status_code == 200
    for key, value in fields.items():
        assert updated.json[key] == value
    assert updated.json['status'] == 'applied'


# --- Generic careers-page titles (JOB-023 regression, 2026-10-07) ----------

def test_generic_meta_title_not_used_as_job_title():
    # rivia.com/careers?ashby_jid=... had <title>Careers</title>; the URL
    # fallback is 'careers' too, so the provisional company title must win.
    result = intake.extract(
        'https://www.rivia.com/careers?ashby_jid=0929307d',
        '<title>Careers</title><meta property="og:title" content="Careers">')
    assert result['title'] != 'Careers'
    assert result['title'].endswith('opportunity')


@pytest.mark.parametrize('meta', [
    'Careers', 'careers', 'Jobs', 'Openings', 'Join Us', 'Work with us',
    'Apply now', 'Careers at Rivia', 'Jobs | Fiction', 'We are hiring'])
def test_generic_title_variants_rejected(meta):
    result = intake.extract('https://fiction.example/role', f'<title>{meta}</title>')
    assert not intake.GENERIC_TITLE_RE.match(result['title']) or result['title'].endswith('opportunity')


def test_real_titles_untouched_by_generic_filter():
    for meta, expected in [('Platform Lead | Careers', 'Platform Lead'),
                           ('Senior Backend Engineer', 'Senior Backend Engineer'),
                           ('Care Manager', 'Care Manager')]:
        result = intake.extract('https://fiction.example/role', f'<title>{meta}</title>')
        assert result['title'] == expected


def test_llm_generic_title_does_not_overwrite_existing():
    data = {'title': 'Rivia opportunity', 'company': 'Rivia'}
    fields = {'title': 'Careers', 'company': 'Rivia', 'location': 'Zurich',
              'employment_type': '', 'remote_ok': None, 'ingest_source': 'llm'}
    merged = intake._merge_extracted(data, fields, {}, intake.Posting())
    assert merged['title'] == 'Rivia opportunity'
    assert merged['location'] == 'Zurich'


def test_llm_real_title_still_overwrites():
    data = {'title': 'Rivia opportunity', 'company': 'Rivia'}
    fields = {'title': 'Senior Product Manager', 'company': 'Rivia', 'location': '',
              'employment_type': '', 'remote_ok': None, 'ingest_source': 'llm'}
    merged = intake._merge_extracted(data, fields, {}, intake.Posting())
    assert merged['title'] == 'Senior Product Manager'


def test_job_detail_has_editable_title(client):
    html = client.get('/jobs/JOB-001').text
    assert 'id="title"' in html
    assert 'PUT' in html and 'title:document.getElementById(\'title\')' in html


def test_job_title_editable_via_api(client):
    root = client.application.config['VAULT_PATH']
    response = client.put('/api/jobs/JOB-001', json={'title': 'Renamed Role'})
    assert response.status_code == 200
    assert response.json['title'] == 'Renamed Role'
    assert vault.load_job(root, 'JOB-001')['title'] == 'Renamed Role'


# --- JOZ-265: hard duplicate check, two-phase stub, promote -----------------

def test_stub_is_visible_before_fetch_completes(client, monkeypatch):
    root = client.application.config['VAULT_PATH']
    release = threading.Event()

    def slow_fetch(url):
        release.wait(timeout=5)
        return '<title>Slow Role</title><p>Remote. Build things.</p>'
    monkeypatch.setattr(intake, 'fetch_url', slow_fetch)

    outcome = {}
    def run():
        outcome['response'] = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/slow-role'})
    worker = threading.Thread(target=run)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        stub = None
        while time.monotonic() < deadline and stub is None:
            stub = next((j for j in vault.list_jobs(root) if j.get('url') == 'https://fiction.example/slow-role'), None)
            if stub is None:
                time.sleep(0.01)
        assert stub is not None, 'stub was not visible while the fetch was still in flight'
        assert stub['ingest_state'] == 'stub'
        assert stub['in_pipeline'] is True
        assert stub['origin'] == 'manual'
        assert stub['source_id'] is None
        assert stub['status'] == 'new'
    finally:
        release.set()
        worker.join(timeout=5)
    data = outcome['response'].json
    assert data['job']['ingest_state'] == 'fetched'
    assert data['job']['id'] == stub['id']


def test_fetch_failure_sets_ingest_state_and_keeps_stub(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', Mock(side_effect=TimeoutError()))
    data = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/unreachable-role'}).json
    job = data['job']
    assert job['ingest_state'] == 'fetch_failed'
    assert job['ingest_error'] == {'stage': 'fetch', 'reason': 'TimeoutError', 'at': job['ingest_error']['at']}
    assert job['in_pipeline'] is True
    assert vault.load_job(client.application.config['VAULT_PATH'], job['id']) is not None
    client.application.config['LLM_THREADS'][job['id']].join(timeout=2)
    assert client.get('/api/jobs/' + job['id']).json['ingest_state'] == 'fetch_failed'


def test_retry_from_fetch_failed_reaches_complete(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', Mock(side_effect=TimeoutError()))
    job = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/retry-role'}).json['job']
    client.application.config['LLM_THREADS'][job['id']].join(timeout=2)
    assert vault.load_job(client.application.config['VAULT_PATH'], job['id'])['ingest_state'] == 'fetch_failed'

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Retry Role</title><p>Remote. Build Python services.</p>')
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: llm_client_for(json.dumps({'title': 'Retry Role'})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    retry = client.post('/api/jobs/' + job['id'] + '/extract')
    assert retry.status_code == 202
    app = client.application
    app.config['REFRESH_THREADS'][job['id']].join(timeout=2)
    app.config['LLM_THREADS'][job['id']].join(timeout=2)
    final = client.get('/api/jobs/' + job['id']).json
    assert final['ingest_state'] == 'complete'
    assert final['ingest_error'] is None
    assert 'Build Python services' in final['description']


def test_hard_duplicate_same_url_warns_without_creating(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Role</title><p>Remote. Python.</p>')
    before = len(client.get('/api/jobs').json)
    first = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/dup-role?utm_source=linkedin'}).json
    client.application.config['LLM_THREADS'][first['job']['id']].join(timeout=2)
    assert len(client.get('/api/jobs').json) == before + 1

    second = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/dup-role?utm_campaign=newsletter'})
    assert second.status_code == 200
    body = second.json
    assert body['duplicate'] is True
    assert body['basis'] == 'same_url'
    assert body['existing']['id'] == first['job']['id']
    assert body['actions'] == ['open_existing', 'add_anyway']
    assert len(client.get('/api/jobs').json) == before + 1


def test_hard_duplicate_same_ats_posting_id_with_different_tracking_params(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Role</title><p>Remote. Python.</p>')
    first = client.post('/api/jobs/intake', json={
        'url': 'https://boards.greenhouse.io/acme/jobs/555111'}).json
    client.application.config['LLM_THREADS'][first['job']['id']].join(timeout=2)

    # Different host form of the same Greenhouse posting: normalized_url
    # differs, but provider/tenant/posting id are the same.
    second = client.post('/api/jobs/intake', json={
        'url': 'https://job-boards.greenhouse.io/acme/jobs/555111?utm_source=twitter&ref=newsletter'})
    assert second.status_code == 200
    assert second.json['basis'] == 'same_ats_posting_id'
    assert second.json['existing']['id'] == first['job']['id']


def test_hard_duplicate_add_anyway_force_creates_second_record(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Role</title><p>Remote.</p>')
    first = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/force-role'}).json
    client.application.config['LLM_THREADS'][first['job']['id']].join(timeout=2)

    forced = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/force-role', 'force': True})
    assert forced.status_code == 201
    second_job = forced.json['job']
    assert second_job['id'] != first['job']['id']
    assert any(entry['event'] == 'duplicate_override' for entry in second_job['history'])
    client.application.config['LLM_THREADS'][second_job['id']].join(timeout=2)


def test_hard_duplicate_promote_action_for_universe_record(client):
    root = client.application.config['VAULT_PATH']
    universe_job = vault.save_job(root, {'title': 'Universe role', 'url': 'https://fiction.example/universe-role',
                                         'normalized_url': 'https://fiction.example/universe-role',
                                         'in_pipeline': False, 'origin': 'discovered'})
    assert universe_job['normalized_url'] == 'https://fiction.example/universe-role'

    response = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/universe-role?utm_source=x'})
    assert response.status_code == 200
    body = response.json
    assert body['duplicate'] is True
    assert body['basis'] == 'same_url'
    assert body['existing']['id'] == universe_job['id']
    assert body['actions'][0] == 'promote'


def test_promote_flips_in_pipeline(client):
    root = client.application.config['VAULT_PATH']
    job = vault.save_job(root, {'title': 'Universe role', 'url': 'https://fiction.example/universe2',
                                'in_pipeline': False, 'origin': 'discovered'})
    assert job['in_pipeline'] is False

    result = client.post('/api/jobs/' + job['id'] + '/promote')
    assert result.status_code == 200
    assert result.json['in_pipeline'] is True
    assert any(entry['event'] == 'promoted' for entry in result.json['history'])

    # Idempotent: promoting an already-piped job is a no-op, not an error.
    again = client.post('/api/jobs/' + job['id'] + '/promote')
    assert again.status_code == 200
    assert again.json['in_pipeline'] is True


def test_promote_missing_job_404(client):
    assert client.post('/api/jobs/JOB-999/promote').status_code == 404


# --- JOZ-265 fix round: M1, DNS/SSRF must run after the stub is saved -----

def test_dns_failure_creates_fetch_failed_stub_not_400(client, monkeypatch):
    import socket as socket_module
    monkeypatch.setattr(socket_module, 'getaddrinfo',
                        Mock(side_effect=socket_module.gaierror('simulated DNS failure')))
    # The suite-wide offline fixture replaces intake.fetch_url outright;
    # restore the real implementation so its internal check_url (DNS) runs.
    monkeypatch.setattr(intake, 'fetch_url', REAL_FETCH)
    before = len(client.get('/api/jobs').json)
    response = client.post('/api/jobs/intake', json={'url': 'https://unresolvable.example/role'})
    assert response.status_code == 201
    job = response.json['job']
    assert job['ingest_state'] == 'fetch_failed'
    assert job['ingest_error']['stage'] == 'fetch'
    assert len(client.get('/api/jobs').json) == before + 1
    # Retryable: the stub survives and the /extract retry path accepts it.
    assert client.post('/api/jobs/' + job['id'] + '/extract').status_code == 202


def test_dns_resolved_only_after_stub_persisted(client, monkeypatch):
    # Real check_url (and therefore real DNS resolution via
    # socket.getaddrinfo) must run; only the actual HTTP fetch underneath
    # it is faked, same pattern as test_fetch_deadline_fallback.
    import socket as socket_module
    root = client.application.config['VAULT_PATH']
    calls = []

    def recording_getaddrinfo(*args, **kwargs):
        stub = next((j for j in vault.list_jobs(root) if j.get('url') == 'https://call-order.example/role'), None)
        calls.append(stub is not None)
        return [(2, 1, 6, '', ('93.184.216.34', 443))]
    monkeypatch.setattr(socket_module, 'getaddrinfo', recording_getaddrinfo)
    # The suite-wide offline fixture replaces intake.fetch_url outright;
    # restore the real implementation so its internal check_url actually
    # runs (and calls the patched getaddrinfo above).
    monkeypatch.setattr(intake, 'fetch_url', REAL_FETCH)

    response_mock = Mock()
    response_mock.__enter__ = Mock(return_value=response_mock)
    response_mock.__exit__ = Mock(return_value=False)
    response_mock.read1 = Mock(side_effect=[b'<title>Role</title>', b''])
    opener = Mock()
    opener.open.return_value = response_mock
    monkeypatch.setattr('urllib.request.build_opener', lambda *a: opener)

    response = client.post('/api/jobs/intake', json={'url': 'https://call-order.example/role'})
    assert response.status_code == 201
    assert calls, 'DNS resolution never happened'
    assert all(calls), 'DNS was resolved before the stub was persisted'


def test_ssrf_blocked_address_creates_fetch_failed_stub_not_400(client, monkeypatch):
    import socket as socket_module
    monkeypatch.setattr(socket_module, 'getaddrinfo',
                        lambda *a, **kw: [(2, 1, 6, '', ('127.0.0.1', 80))])
    monkeypatch.setattr(intake, 'fetch_url', REAL_FETCH)
    before = len(client.get('/api/jobs').json)
    response = client.post('/api/jobs/intake', json={'url': 'https://ssrf-probe.example/role'})
    assert response.status_code == 201
    job = response.json['job']
    assert job['ingest_state'] == 'fetch_failed'
    assert len(client.get('/api/jobs').json) == before + 1


# --- JOZ-265 fix round: M2, Phase B must not clobber a concurrent owner edit

@pytest.mark.parametrize('field,owner_value', [('title', 'Owner Title'), ('description', 'Owner wrote this.'),
                                               ('location', 'Owner Location')])
def test_concurrent_owner_edit_during_fetch_survives(client, monkeypatch, field, owner_value):
    root = client.application.config['VAULT_PATH']
    release = threading.Event()

    def slow_fetch(url):
        release.wait(timeout=5)
        return '<title>Scraped Title</title><p>Remote. Build things in Zurich.</p>'
    monkeypatch.setattr(intake, 'fetch_url', slow_fetch)

    outcome = {}
    def run():
        outcome['response'] = client.post('/api/jobs/intake', json={'url': 'https://m2-probe.example/' + field})
    worker = threading.Thread(target=run)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        stub = None
        while stub is None and time.monotonic() < deadline:
            stub = next((j for j in vault.list_jobs(root)
                        if j.get('url') == 'https://m2-probe.example/' + field), None)
            if stub is None:
                time.sleep(0.01)
        assert stub is not None
        vault.save_job(root, {field: owner_value}, stub['id'])
    finally:
        release.set()
        worker.join(timeout=5)
    final = vault.load_job(root, stub['id'])
    assert final[field] == owner_value


# NOTE on the brief's "owner clears a field to empty during fetch -> stays
# empty" regression: at Phase A, 'title' is the only stub field with a
# non-blank baseline (stub_title(url)) an owner edit could clear in a way
# snapshot-equality could even observe, and vault.save_job rejects a blank
# title outright (title is required), so there is no way to construct this
# case against Phase B's heuristic merge specifically. description/location
# both start at '' in the stub, so clearing them to '' is observationally
# identical to "never touched" at this phase; there is nothing yet to
# protect. The same snapshot-equality mechanism IS exercised against a real,
# non-blank-baseline clear-to-empty during the LLM callback phase (baseline
# is the heuristic-filled value, not the stub default) by the pre-existing
# test_async_owner_clear_and_success_flag in test_ingest.py, which clears
# 'location' to '' while an LLM callback is in flight and asserts it stays
# ''. See the fix-round report (M2) for this call.


def test_automated_fill_lands_when_field_still_at_baseline(client, monkeypatch):
    # Control case: with no concurrent edit, the scraped value lands.
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Scraped Title</title><p>Remote. Zurich.</p>')
    data = client.post('/api/jobs/intake', json={'url': 'https://m2-control.example/role'}).json
    assert data['job']['title'] == 'Scraped Title'


# --- JOZ-265 fix round 2: O1 (was M2), field_provenance must survive BOTH
# the Phase B merge AND the later LLM callback, not just the first one. ---

def _wait_for_stub(root, url, timeout=5):
    deadline = time.monotonic() + timeout
    stub = None
    while stub is None and time.monotonic() < deadline:
        stub = next((j for j in vault.list_jobs(root) if j.get('url') == url), None)
        if stub is None:
            time.sleep(0.01)
    assert stub is not None, 'stub never appeared'
    return stub


@pytest.mark.parametrize('field,owner_value,llm_value', [
    ('title', 'Owner Title', 'LLM Title'),
    ('location', 'Owner Location', 'LLM Location'),
])
def test_owner_edit_during_fetch_survives_llm_callback_too(client, monkeypatch, field, owner_value, llm_value):
    # Probe evidence from the verification round: Phase B's own protection
    # (M2) let the owner's edit survive the fetch merge, but the saved
    # result then became the LLM phase's baseline -- so apply_llm_update's
    # job.get(key)==baseline.get(key) check trivially matched (baseline WAS
    # the owner's value) and the LLM callback clobbered it right back.
    root = client.application.config['VAULT_PATH']
    release = threading.Event()

    def slow_fetch(url):
        release.wait(timeout=5)
        return '<title>Scraped Title</title><p>Remote. Build things in Zurich.</p>'
    monkeypatch.setattr(intake, 'fetch_url', slow_fetch)
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: llm_client_for(json.dumps({field: llm_value})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)

    outcome = {}
    def run():
        outcome['response'] = client.post('/api/jobs/intake', json={'url': 'https://o1-probe.example/' + field})
    worker = threading.Thread(target=run)
    worker.start()
    try:
        stub = _wait_for_stub(root, 'https://o1-probe.example/' + field)
        edited = client.put('/api/jobs/' + stub['id'], json={field: owner_value})
        assert edited.status_code == 200
        assert edited.json['field_provenance'][field] == 'user'
    finally:
        release.set()
        worker.join(timeout=5)
    client.application.config['LLM_THREADS'][stub['id']].join(timeout=2)
    final = vault.load_job(root, stub['id'])
    assert final[field] == owner_value, 'owner edit must survive the LLM callback, not just the fetch merge'
    assert final['field_provenance'][field] == 'user'


def test_owner_clears_field_during_fetch_stays_empty_through_callback(client, monkeypatch):
    # The brief's "owner clears a field to empty" case, previously
    # unconstructible against Phase B (round 1's limitation: baseline
    # equality can't observe a blank-to-blank clear). field_provenance
    # gates on ownership, not value equality, so this is now directly
    # testable, through BOTH the fetch merge and the LLM callback.
    root = client.application.config['VAULT_PATH']
    release = threading.Event()

    def slow_fetch(url):
        release.wait(timeout=5)
        return '<title>Scraped Title</title><p>Remote. Build things in Zurich.</p>'
    monkeypatch.setattr(intake, 'fetch_url', slow_fetch)
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: llm_client_for(json.dumps({'location': 'LLM Location'})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)

    outcome = {}
    def run():
        outcome['response'] = client.post('/api/jobs/intake', json={'url': 'https://o1-clear-probe.example/role'})
    worker = threading.Thread(target=run)
    worker.start()
    try:
        stub = _wait_for_stub(root, 'https://o1-clear-probe.example/role')
        assert client.put('/api/jobs/' + stub['id'], json={'location': 'Temporary'}).status_code == 200
        cleared = client.put('/api/jobs/' + stub['id'], json={'location': ''})
        assert cleared.status_code == 200
        assert cleared.json['location'] == ''
        assert cleared.json['field_provenance']['location'] == 'user'
    finally:
        release.set()
        worker.join(timeout=5)
    assert outcome['response'].json['job']['location'] == ''
    client.application.config['LLM_THREADS'][stub['id']].join(timeout=2)
    final = vault.load_job(root, stub['id'])
    assert final['location'] == '', 'a deliberate clear-to-empty must stay empty through fetch AND the LLM callback'
    assert final['field_provenance']['location'] == 'user'


# --- m10 (JOZ-266 fix round): list view parity with kanban's review chip --

def test_list_view_shows_review_indicator_for_linked_company(client):
    root = client.application.config['VAULT_PATH']
    vault.save_job(root, {'company_link_state': 'needs_review', 'company_link_reason': 'fuzzy_name'}, 'JOB-001')
    html = client.get('/jobs').text
    list_view = html.split('id="list-view"', 1)[1]
    assert 'company-review-chip' in list_view


# --- M1 (JOZ-266 fix round): owner link decision protected as a group --

def test_owner_link_decision_survives_concurrent_phase_b_resolution(client, monkeypatch):
    """The owner's link decision (company_id, company_link_state,
    company_link_reason) is a coherent group; automation must never flip
    any of the three once the owner has set them, even when a field's new
    value happens to coincide with whatever Phase B's own baseline
    already had (company_link_state: 'linked' both before and after, for
    entirely different reasons)."""
    root = client.application.config['VAULT_PATH']
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html(hiringOrganization={'name': 'Acme Robotics'}))
    first = client.post('/api/jobs/intake', json={
        'url': 'https://boards.greenhouse.io/m1acme/jobs/111'}).json
    tenant_company_id = first['job']['company_id']
    assert first['job']['company_link_state'] == 'linked'
    other = vault.save_company(root, {'name': 'Totally Other Staffing'})

    release = threading.Event()

    def slow_fetch(url):
        release.wait(timeout=5)
        return schema_html(hiringOrganization={'name': 'Totally Other Staffing'})
    monkeypatch.setattr(intake, 'fetch_url', slow_fetch)

    outcome = {}
    def run():
        outcome['response'] = client.post('/api/jobs/intake', json={
            'url': 'https://boards.greenhouse.io/m1acme/jobs/222'})
    worker = threading.Thread(target=run)
    worker.start()
    try:
        stub = _wait_for_stub(root, 'https://boards.greenhouse.io/m1acme/jobs/222')
        # Rung 1 already linked the stub to the tenant owner, at stub time.
        assert stub['company_id'] == tenant_company_id
        assert stub['company_link_state'] == 'linked'
        edited = client.put('/api/jobs/' + stub['id'], json={'company_id': other['id']})
        assert edited.status_code == 200
        assert edited.json['company_id'] == other['id']
        assert edited.json['company_link_state'] == 'linked'
        assert edited.json['company_link_reason'] == 'manual'
        for key in ('company_id', 'company_link_state', 'company_link_reason'):
            assert edited.json['field_provenance'][key] == 'user'
    finally:
        release.set()
        worker.join(timeout=5)
    client.application.config['LLM_THREADS'][stub['id']].join(timeout=2)
    final = vault.load_job(root, stub['id'])
    # The fetch resolved the SAME posting to the tenant owner again (still
    # 'linked', coincidentally -- for a completely different reason) --
    # that coincidence must never let automation clobber the owner's
    # explicit, different choice.
    assert final['company_id'] == other['id']
    assert final['company_link_state'] == 'linked'
    assert final['company_link_reason'] == 'manual'


def test_put_company_link_state_equal_to_baseline_takes_user_provenance(client, monkeypatch):
    """A bare PUT of company_link_state alone (no company_id in the same
    payload) must still be marked owner-provenance, even when its new
    value is identical to whatever automation already had -- otherwise a
    later automation run can silently re-decide it since nothing ever
    marked it as the owner's."""
    root = client.application.config['VAULT_PATH']
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html(hiringOrganization={'name': 'Acme Robotics'}))
    data = client.post('/api/jobs/intake', json={
        'url': 'https://boards.greenhouse.io/m1equalbaseline/jobs/111'}).json
    job_id = data['job']['id']
    assert data['job']['company_link_state'] == 'linked'
    client.application.config['LLM_THREADS'][job_id].join(timeout=2)

    edited = client.put('/api/jobs/' + job_id, json={'company_link_state': 'linked'})
    assert edited.status_code == 200
    assert edited.json['company_link_state'] == 'linked'
    assert edited.json['field_provenance']['company_link_state'] == 'user'

    rerun = client.post('/api/jobs/' + job_id + '/resolve')
    assert rerun.status_code == 200
    assert rerun.json['company_link_state'] == 'linked'


def test_automation_fills_untouched_fields_and_marks_provenance(client, monkeypatch):
    # The other half of O1: automation must still fill whatever the owner
    # never touched, and now also leaves a provenance trail for it.
    monkeypatch.setattr(intake, 'fetch_url',
                        lambda url: '<title>Scraped Title</title><p>Remote. Build things in Zurich.</p>')
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: llm_client_for(json.dumps({'seniority': 'senior'})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    data = client.post('/api/jobs/intake', json={'url': 'https://o1-control.example/role'}).json
    assert data['job']['title'] == 'Scraped Title'
    assert data['job']['field_provenance']['title'] == 'scrape'
    client.application.config['LLM_THREADS'][data['job']['id']].join(timeout=2)
    final = client.get('/api/jobs/' + data['job']['id']).json
    assert final['seniority'] == 'senior'
    assert final['field_provenance']['seniority'] == 'llm'


# --- JOZ-265 fix round: M3, every failure must be visible, never silent ---

def test_parse_failure_after_fetch_sets_failed_state_not_500(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Ok</title>')
    def boom(url, html):
        raise RuntimeError('parser exploded')
    monkeypatch.setattr(intake, 'heuristic_posting', boom)
    before = len(client.get('/api/jobs').json)
    response = client.post('/api/jobs/intake', json={'url': 'https://m3-parse.example/role'})
    assert response.status_code == 201
    job = response.json['job']
    assert job['ingest_state'] in ('fetch_failed', 'extract_failed')
    assert job['ingest_error']['reason'] == 'RuntimeError'
    assert job['history'][-1]['event'] in ('fetch_failed', 'extract_failed')
    assert len(client.get('/api/jobs').json) == before + 1


def test_empty_fetch_result_sets_fetch_failed_with_reason(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '   ')
    response = client.post('/api/jobs/intake', json={'url': 'https://m3-empty.example/role'})
    assert response.status_code == 201
    job = response.json['job']
    assert job['ingest_state'] == 'fetch_failed'
    assert job['ingest_error']['stage'] == 'fetch'
    assert job['ingest_error']['reason']
    assert job['history'][-1]['event'] == 'fetch_failed'


def test_worker_start_failure_sets_extract_failed(client, monkeypatch):
    # O2 (fix round 2): a worker that never started must not be reported
    # with the same 201 this route uses when extraction actually gets
    # underway -- that is indistinguishable from success to a caller that
    # only checks response.ok, even though the body happens to carry the
    # failure too. Confirmed via vault reload: the failure state, error,
    # and history are durably persisted, not just reflected in this one
    # response body.
    monkeypatch.setattr(intake, 'fetch_url',
                        lambda url: '<title>Ok</title><p>Remote. Python engineer role with real text.</p>')
    monkeypatch.setattr(ingest, 'extract_async', Mock(side_effect=RuntimeError('worker boom')))
    before = len(client.get('/api/jobs').json)
    response = client.post('/api/jobs/intake', json={'url': 'https://m3-worker.example/role'})
    assert response.status_code == 503
    assert response.json['error']
    job = response.json['job']
    assert job['ingest_state'] == 'extract_failed'
    assert job['ingest_error']['stage'] == 'extract'
    assert job['history'][-1]['event'] == 'extract_failed'
    assert job['id'] not in client.application.config['LLM_PENDING']
    assert len(client.get('/api/jobs').json) == before + 1
    persisted = client.get('/api/jobs/' + job['id']).json
    assert persisted['ingest_state'] == 'extract_failed'
    assert persisted['ingest_error'] == job['ingest_error']
    assert persisted['llm_pending'] is False


def test_callback_exception_persists_failure_state(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url',
                        lambda url: '<title>Ok</title><p>Remote. Python engineer role with real text.</p>')
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: llm_client_for(json.dumps({'title': 'New Title'})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    root = client.application.config['VAULT_PATH']
    orig_save_job = vault.save_job
    def flaky_save_job(root_, data, identifier=None, **kwargs):
        if 'enriched' in data:
            raise RuntimeError('callback save boom')
        return orig_save_job(root_, data, identifier, **kwargs)
    monkeypatch.setattr(vault, 'save_job', flaky_save_job)
    response = client.post('/api/jobs/intake', json={'url': 'https://m3-callback.example/role'})
    job = response.json['job']
    client.application.config['LLM_THREADS'][job['id']].join(timeout=2)
    monkeypatch.setattr(vault, 'save_job', orig_save_job)
    final = vault.load_job(root, job['id'])
    assert final['ingest_state'] == 'extract_failed'
    assert final['ingest_error']['reason'] == 'RuntimeError'
    assert final['history'][-1]['event'] == 'extract_failed'


# --- JOZ-265 fix round: M4, ATS dedupe must respect tenant boundaries -----

def test_hard_duplicate_same_posting_id_different_tenant_is_not_a_duplicate(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Role</title><p>Remote. Python.</p>')
    before = len(client.get('/api/jobs').json)
    first = client.post('/api/jobs/intake', json={'url': 'https://a.recruitee.com/o/software-engineer'}).json
    client.application.config['LLM_THREADS'][first['job']['id']].join(timeout=2)
    assert len(client.get('/api/jobs').json) == before + 1

    second = client.post('/api/jobs/intake', json={'url': 'https://b.recruitee.com/o/software-engineer'})
    assert second.status_code == 201
    assert len(client.get('/api/jobs').json) == before + 2


# --- JOZ-265 fix round: m11, ingest_state/ingest_error consistency --------

@pytest.mark.parametrize('payload', [
    {'ingest_state': 'complete', 'ingest_error': {'stage': 'fetch', 'reason': 'x', 'at': '2026-01-01T00:00:00Z'}},
    {'ingest_state': 'fetch_failed', 'ingest_error': None},
    {'ingest_state': 'fetch_failed', 'ingest_error': {'stage': 'bogus', 'reason': 'x', 'at': '2026-01-01T00:00:00Z'}},
])
def test_inconsistent_ingest_state_error_pairs_rejected(client, payload):
    assert client.put('/api/jobs/JOB-001', json=payload).status_code == 400


def test_duplicate_warning_panel_markup_no_native_confirm(client):
    html = client.get('/jobs').text
    assert '<dialog id="duplicate-warning">' in html
    assert 'id="duplicate-open-existing"' in html
    assert 'id="duplicate-promote"' in html
    assert 'id="duplicate-add-anyway"' in html
    assert 'id="duplicate-cancel"' in html
    assert 'confirm(' not in html



def test_duplicate_warning_payload_always_includes_add_anyway(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Role</title><p>Remote. Python.</p>')
    first = client.post('/api/jobs/intake', json={'url': 'https://m8-probe.example/role'}).json
    client.application.config['LLM_THREADS'][first['job']['id']].join(timeout=2)
    dup = client.post('/api/jobs/intake', json={'url': 'https://m8-probe.example/role'}).json
    assert 'add_anyway' in dup['actions']

    root = client.application.config['VAULT_PATH']
    universe = vault.save_job(root, {'title': 'Universe role', 'url': 'https://m8-universe.example/role',
                                     'normalized_url': 'https://m8-universe.example/role',
                                     'in_pipeline': False, 'origin': 'discovered'})
    dup_universe = client.post('/api/jobs/intake', json={'url': 'https://m8-universe.example/role'}).json
    assert dup_universe['actions'] == ['promote', 'open_existing', 'add_anyway']


def test_retry_from_extract_failed_clears_prior_error(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url',
                        lambda url: '<title>Role</title><p>Remote. Python engineer role with real text.</p>')
    data = client.post('/api/jobs/intake', json={'url': 'https://m11-retry.example/role'}).json
    job_id = data['job']['id']
    client.application.config['LLM_THREADS'][job_id].join(timeout=2)
    assert vault.load_job(client.application.config['VAULT_PATH'], job_id)['ingest_state'] == 'extract_failed'

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Retry Role</title><p>Remote. Build Python services.</p>')
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: llm_client_for(json.dumps({'title': 'Retry Role'})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    retry = client.post('/api/jobs/' + job_id + '/extract')
    assert retry.status_code == 202
    app = client.application
    app.config['REFRESH_THREADS'][job_id].join(timeout=2)
    app.config['LLM_THREADS'][job_id].join(timeout=2)
    final = client.get('/api/jobs/' + job_id).json
    assert final['ingest_state'] == 'complete'
    assert final['ingest_error'] is None


# =====================================================================
# JOZ-265 fix round 2: N1, N2, N3 (new findings from the verification
# round) and O4 (behavioral coverage for the already-closed m8 dialog fix)
# =====================================================================

# --- N1: retry must not leave 'fetched'/error-None when the worker fails
# to even start; the error-clearing has to be atomic with a successful
# handoff, not with the attempt. ---

def test_retry_worker_start_failure_does_not_leave_fetched_with_no_error(client, monkeypatch):
    # The initial intake already hits this same worker-start failure (O2);
    # confirm that starting point, then exercise the identical failure a
    # second time through the /extract RETRY path specifically, which has
    # its own, separate code path for clearing a prior error.
    monkeypatch.setattr(intake, 'fetch_url',
                        lambda url: '<title>Ok</title><p>Remote. Python engineer role with real text.</p>')
    monkeypatch.setattr(ingest, 'extract_async', Mock(side_effect=RuntimeError('worker boom')))
    data = client.post('/api/jobs/intake', json={'url': 'https://n1-retry.example/role'}).json
    job_id = data['job']['id']
    assert vault.load_job(client.application.config['VAULT_PATH'], job_id)['ingest_state'] == 'extract_failed'

    retry = client.post('/api/jobs/' + job_id + '/extract')
    assert retry.status_code == 202
    client.application.config['REFRESH_THREADS'][job_id].join(timeout=2)
    final = client.get('/api/jobs/' + job_id).json
    assert final['ingest_state'] == 'extract_failed'
    assert final['ingest_error'] == {'stage': 'extract', 'reason': 'worker_start_failed', 'at': final['ingest_error']['at']}
    assert final['history'][-1]['event'] == 'extract_failed'
    assert final['llm_pending'] is False


# --- N2: a url change mid-fetch must discard the whole stale result, and
# the generic PUT path must recompute normalized_url/ats_* atomically. ---

def test_url_change_during_fetch_discards_stale_result(client, monkeypatch):
    root = client.application.config['VAULT_PATH']
    release = threading.Event()

    def slow_fetch(url):
        release.wait(timeout=5)
        return '<title>Tenant A Title</title><p>Remote. Tenant A describes this role in great detail.</p>'
    monkeypatch.setattr(intake, 'fetch_url', slow_fetch)

    outcome = {}
    def run():
        outcome['response'] = client.post('/api/jobs/intake', json={'url': 'https://a.recruitee.com/o/role'})
    worker = threading.Thread(target=run)
    worker.start()
    try:
        stub = _wait_for_stub(root, 'https://a.recruitee.com/o/role')
        edited = client.put('/api/jobs/' + stub['id'], json={'url': 'https://b.recruitee.com/o/other-role'})
        assert edited.status_code == 200
        assert edited.json['normalized_url'] == 'https://b.recruitee.com/o/other-role'
    finally:
        release.set()
        worker.join(timeout=5)
    assert outcome['response'].status_code == 201
    assert outcome['response'].json.get('company') is None

    final = vault.load_job(root, stub['id'])
    # None of tenant A's stale fetch result landed on the edited record.
    assert final['title'] != 'Tenant A Title'
    assert 'Tenant A' not in (final.get('description') or '')
    assert final['url'] == 'https://b.recruitee.com/o/other-role'
    assert final['normalized_url'] == 'https://b.recruitee.com/o/other-role'
    assert final['ats_tenant'] == 'b'
    assert final['ats_posting_id'] == 'other-role'
    assert stub['id'] not in client.application.config['LLM_THREADS']
    assert final['ingest_state'] == 'extract_failed'
    assert final['ingest_error']['reason'] == 'source_url_changed'

    # Re-adding the OLD url must not falsely report a duplicate: its
    # identity was discarded, not resurrected onto the edited record.
    again = client.post('/api/jobs/intake', json={'url': 'https://a.recruitee.com/o/role'})
    assert again.status_code == 201
    assert 'duplicate' not in again.json


def test_put_url_change_recomputes_normalized_url_and_ats_atomically(client):
    root = client.application.config['VAULT_PATH']
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://fiction.example/old',
                                'normalized_url': 'https://fiction.example/old'})
    updated = client.put('/api/jobs/' + job['id'], json={'url': 'https://b.recruitee.com/o/some-role'})
    assert updated.status_code == 200
    assert updated.json['normalized_url'] == 'https://b.recruitee.com/o/some-role'
    assert updated.json['ats_provider'] == 'recruitee'
    assert updated.json['ats_tenant'] == 'b'
    assert updated.json['ats_posting_id'] == 'some-role'
    assert updated.json['field_provenance']['url'] == 'user'


# --- N3: a failure stage must not contradict the failure state it rides
# alongside. ---

@pytest.mark.parametrize('payload', [
    {'ingest_state': 'fetch_failed', 'ingest_error': {'stage': 'extract', 'reason': 'x', 'at': '2026-01-01T00:00:00Z'}},
    {'ingest_state': 'extract_failed', 'ingest_error': {'stage': 'fetch', 'reason': 'x', 'at': '2026-01-01T00:00:00Z'}},
])
def test_ingest_error_stage_must_match_failure_state(client, payload):
    assert client.put('/api/jobs/JOB-001', json=payload).status_code == 400


# --- O4: the m8 dismissal fix is behaviorally correct but was only tested
# via source-string assertions; drive the real extracted JS instead. The
# test gracefully skips where Node is unavailable rather than faking a
# server-level substitute for a client-only control-flow guarantee. ------

NODE = shutil.which('node')

_DUP_RESPONSE = {
    'duplicate': True, 'basis': 'same_url',
    'existing': {'id': 'JOB-EXISTING', 'title': 'Existing Role', 'in_pipeline': False},
    'actions': ['promote', 'open_existing', 'add_anyway'],
}

_DIALOG_HARNESS = r"""
'use strict';
const calls = [];
const location = { href: '' };
const elements = new Map();
function makeGeneric(id){
  return {
    id, dataset: {}, classList: { toggle(){}, add(){}, contains(){ return false; } },
    style: {}, children: [], hidden: false, textContent: '', value: '',
    onclick: null, onclose: null, onchange: null, onsubmit: null,
    addEventListener(){}, removeEventListener(){},
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    setAttribute(){}, getAttribute(){ return null; }, append(){}, replaceChildren(){},
  };
}
function byId(id){
  if (!elements.has(id)) elements.set(id, makeGeneric(id));
  return elements.get(id);
}
const document = {
  getElementById: byId,
  querySelector(){ return null; },
  querySelectorAll(){ return []; },
  addEventListener(){},
  hidden: false,
  activeElement: null,
};
const window = { addEventListener(){} };
const localStorage = { getItem(){ return null; }, setItem(){} };
class DOMParser { parseFromString(){ return { getElementById(){ return { children: [] }; } }; } }

const DUP_RESPONSE = __DUP_RESPONSE__;
async function fetch(url, opts) {
  calls.push({ url, method: opts && opts.method, body: opts && opts.body });
  if (url === '/jobs') return { ok: true, text: async () => '<div id="cards"></div>' };
  if (/\/promote$/.test(url)) return { ok: true, json: async () => ({ id: 'JOB-EXISTING', in_pipeline: true }) };
  if (url === '/api/jobs/intake') {
    const body = JSON.parse((opts && opts.body) || '{}');
    if (!body.force) return { ok: true, json: async () => DUP_RESPONSE };
    return { ok: true, json: async () => ({ job: { id: 'JOB-NEW' }, company: null }) };
  }
  return { ok: true, json: async () => ({}) };
}

__UI_JS__

__JOBS_JS__

{
const postingInput = byId('posting');
postingInput.value = 'https://example.test/role';
const intakeButton = makeGeneric('intake-button');
const intakeForm = byId('intake');
intakeForm.querySelector = (sel) => (sel === 'button' ? intakeButton : null);

const dupDialog = byId('duplicate-warning');
dupDialog.open = false;
dupDialog.showModal = function(){ dupDialog.open = true; };
dupDialog.close = function(){ dupDialog.open = false; };
const dupOpenExisting = byId('duplicate-open-existing');
const dupPromote = byId('duplicate-promote');
const dupAddAnyway = byId('duplicate-add-anyway');
const dupCancel = byId('duplicate-cancel');

(async () => {
  const fakeEvent = { preventDefault(){}, target: intakeForm };
  const formPromise = intakeForm.onsubmit(fakeEvent);
  for (let i = 0; i < 200 && dupCancel.onclick === null; i++) {
    await new Promise(r => setTimeout(r, 0));
  }
  if (dupCancel.onclick === null) throw new Error('dialog never opened');
  const scenario = __SCENARIO__;
  if (scenario === 'cancel') dupCancel.onclick();
  else if (scenario === 'escape') dupDialog.onclose();
  else if (scenario === 'add_anyway') dupAddAnyway.onclick();
  else if (scenario === 'open_existing') dupOpenExisting.onclick();
  else if (scenario === 'promote') dupPromote.onclick();
  else throw new Error('unknown scenario: ' + scenario);
  await formPromise;
  console.log(JSON.stringify({ calls, locationHref: location.href }));
})().then(() => process.exit(0)).catch(e => { console.error((e && e.stack) || e); process.exit(1); });
}
"""


def _inline_script(html):
    match = re.search(r'<script>(.*?)</script>', html, re.S)
    assert match, 'no inline <script> block found'
    return match.group(1)


def _run_dialog_scenario(jobs_js, scenario):
    harness = (_DIALOG_HARNESS
               .replace('__DUP_RESPONSE__', json.dumps(_DUP_RESPONSE))
               .replace('__UI_JS__', _inline_script(UI_JS))
               .replace('__JOBS_JS__', jobs_js)
               .replace('__SCENARIO__', json.dumps(scenario)))
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as handle:
        handle.write(harness)
        path = handle.name
    try:
        result = subprocess.run([NODE, path], capture_output=True, text=True, timeout=10)
    finally:
        Path(path).unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _assert_dialog_record_count(client, result, expected_delta):
    url = 'https://example.test/role'
    root = client.application.config['VAULT_PATH']
    if not any(j.get('url') == url for j in vault.list_jobs(root)):
        vault.save_job(root, {'title': 'Existing Role', 'url': url, 'normalized_url': url})
    before = len(vault.list_jobs(root))
    for call in result['calls']:
        if call['url'] == '/api/jobs/intake':
            response = client.post(call['url'], json=json.loads(call['body']))
            assert response.status_code in (200, 201)
    assert len(vault.list_jobs(root)) == before + expected_delta


@pytest.mark.skipif(NODE is None, reason='Node is required to execute the real dialog JS.')
def test_duplicate_dialog_cancel_and_escape_create_nothing(client):
    jobs_js = re.findall(r'<script>(.*?)</script>', client.get('/jobs').text, re.S)[-1]
    for scenario in ('cancel', 'escape'):
        result = _run_dialog_scenario(jobs_js, scenario)
        intake_calls = [c for c in result['calls'] if c['url'] == '/api/jobs/intake']
        assert len(intake_calls) == 1, f'{scenario}: must not re-call intake'
        assert all(not json.loads(c['body'] or '{}').get('force') for c in intake_calls)
        assert result['locationHref'] == ''
        _assert_dialog_record_count(client, result, 0)


@pytest.mark.skipif(NODE is None, reason='Node is required to execute the real dialog JS.')
def test_duplicate_dialog_add_anyway_creates_second_record(client):
    jobs_js = re.findall(r'<script>(.*?)</script>', client.get('/jobs').text, re.S)[-1]
    result = _run_dialog_scenario(jobs_js, 'add_anyway')
    intake_calls = [c for c in result['calls'] if c['url'] == '/api/jobs/intake']
    assert len(intake_calls) == 2
    forced = [c for c in intake_calls if json.loads(c['body'] or '{}').get('force')]
    assert len(forced) == 1, 'add_anyway must send exactly one force:true creation request'
    _assert_dialog_record_count(client, result, 1)


@pytest.mark.skipif(NODE is None, reason='Node is required to execute the real dialog JS.')
def test_duplicate_dialog_open_existing_navigates_and_creates_nothing(client):
    jobs_js = re.findall(r'<script>(.*?)</script>', client.get('/jobs').text, re.S)[-1]
    result = _run_dialog_scenario(jobs_js, 'open_existing')
    intake_calls = [c for c in result['calls'] if c['url'] == '/api/jobs/intake']
    assert len(intake_calls) == 1, 'open_existing must not create anything'
    assert result['locationHref'] == '/jobs/JOB-EXISTING'
    _assert_dialog_record_count(client, result, 0)


@pytest.mark.skipif(NODE is None, reason='Node is required to execute the real dialog JS.')
def test_duplicate_dialog_promote_creates_nothing(client):
    jobs_js = re.findall(r'<script>(.*?)</script>', client.get('/jobs').text, re.S)[-1]
    result = _run_dialog_scenario(jobs_js, 'promote')
    intake_calls = [c for c in result['calls'] if c['url'] == '/api/jobs/intake']
    assert len(intake_calls) == 1, 'promote must not create a second job'
    assert any(c['url'] == '/api/jobs/JOB-EXISTING/promote' for c in result['calls'])


def test_saved_owner_provenance_blocks_fetch_and_callback(client, monkeypatch):
    root = client.application.config['VAULT_PATH']
    callbacks = []
    def fetch(url):
        stub = next(j for j in vault.list_jobs(root) if j['url'] == url)
        saved = vault.save_job(root, {'location': '', 'field_provenance': {'location': 'user'}}, stub['id'])
        assert saved['field_provenance'] == {'location': 'user'}
        return '<title>Role</title><p>Location: London</p>'
    monkeypatch.setattr(intake, 'fetch_url', fetch)
    monkeypatch.setattr(ingest, 'extract_async', lambda text, callback, **kw: callbacks.append(callback) or Mock(is_alive=lambda: True))
    job = client.post('/api/jobs/intake', json={'url': 'https://saved.example/role'}).json['job']
    assert job['location'] == ''
    callbacks[0]({'location': 'LLM Location', 'seniority': 'senior'})
    final = vault.load_job(root, job['id'])
    assert final['location'] == ''
    assert final['field_provenance']['location'] == 'user'
    assert final['seniority'] == 'senior'


def test_metadata_only_none_callback_is_terminal(client, monkeypatch):
    callbacks = []
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<meta property="og:title" content="Role">')
    monkeypatch.setattr(ingest, 'extract_async', lambda text, callback, **kw: callbacks.append(callback) or Mock(is_alive=lambda: True))
    job = client.post('/api/jobs/intake', json={'url': 'https://meta.example/role'}).json['job']
    callbacks[0](None)
    final = client.get('/api/jobs/' + job['id']).json
    assert final['ingest_state'] == 'extract_failed'
    assert final['ingest_error']['reason'] == 'empty_content'
    assert final['history'][-1]['event'] == 'extract_failed'
    assert final['llm_pending'] is False


def test_retry_error_retained_until_successful_handoff(client, monkeypatch):
    root = client.application.config['VAULT_PATH']
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://handoff.example/role',
        'ingest_state': 'extract_failed', 'ingest_error': {'stage': 'extract', 'reason': 'previous', 'at': vault.timestamp()}})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Build things.</main>')
    def start(text, callback, **kwargs):
        current = vault.load_job(root, job['id'])
        assert current['ingest_state'] == 'extract_failed'
        assert current['ingest_error']['reason'] == 'previous'
        return Mock(is_alive=lambda: True)
    monkeypatch.setattr(ingest, 'extract_async', start)
    response = client.post('/api/jobs/' + job['id'] + '/extract')
    assert response.status_code == 202 and response.json['accepted'] is True
    client.application.config['REFRESH_THREADS'][job['id']].join(2)
    final = vault.load_job(root, job['id'])
    assert final['ingest_state'] == 'fetched' and final['ingest_error'] is None


def test_refresh_worker_start_failure_is_terminal(client, monkeypatch):
    from careeros import server
    monkeypatch.setattr(server.Thread, 'start', Mock(side_effect=RuntimeError('start failed')))
    response = client.post('/api/jobs/JOB-001/extract')
    assert response.status_code == 503 and response.json['error']
    final = client.get('/api/jobs/JOB-001').json
    assert final['ingest_state'] == 'extract_failed'
    assert final['ingest_error']['reason'] == 'refresh_worker_start_failed'
    assert final['history'][-1]['event'] == 'extract_failed'
    assert final['llm_pending'] is False


def test_url_change_before_callback_discards_completion(client, monkeypatch):
    callbacks = []
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Old page content.</main>')
    monkeypatch.setattr(ingest, 'extract_async', lambda text, callback, **kw: callbacks.append(callback) or Mock(is_alive=lambda: True))
    job = client.post('/api/jobs/intake', json={'url': 'https://a.recruitee.com/o/role'}).json['job']
    edited = client.put('/api/jobs/' + job['id'], json={'url': 'https://b.recruitee.com/o/other'}).json
    callbacks[0]({'title': 'Stale LLM Title'})
    final = client.get('/api/jobs/' + job['id']).json
    assert final['title'] == edited['title']
    assert final['ingest_state'] == 'extract_failed'
    assert final['ats_tenant'] == 'b'
    assert final['ingest_error']['reason'] == 'source_url_changed'


def test_refresh_worker_exception_persists_failure(client, monkeypatch):
    root = client.application.config['VAULT_PATH']
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Build things.</main>')
    save = vault.save_job
    def fail_refresh(root, data, *args, **kwargs):
        if 'refresh' in data:
            raise RuntimeError('refresh save failed')
        return save(root, data, *args, **kwargs)
    monkeypatch.setattr(vault, 'save_job', fail_refresh)
    response = client.post('/api/jobs/JOB-001/extract')
    assert response.status_code == 202 and response.json['accepted'] is True
    client.application.config['REFRESH_THREADS']['JOB-001'].join(2)
    final = vault.load_job(root, 'JOB-001')
    assert final['ingest_state'] == 'extract_failed'
    assert final['ingest_error']['reason'] == 'RuntimeError'
    assert final['history'][-1]['event'] == 'extract_failed'
    assert not client.application.config['LLM_PENDING']
