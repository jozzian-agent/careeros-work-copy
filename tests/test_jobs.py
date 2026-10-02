"""Chunk 3 contracts; no intake test is allowed to reach the network."""
from datetime import date
from pathlib import Path
import shutil
import pytest
from careeros import intake, vault
from careeros.server import create_app

ROOT = Path(__file__).resolve().parents[1]

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

@pytest.mark.parametrize('html', ['<meta property="og:title" content="Builder | Careers"><meta property="og:site_name" content="Moonbutton">','<title>Builder</title><p>Remote London</p>',None])
def test_intake(client,monkeypatch,html):
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
    assert data['company']['website'] is None
    assert client.get('/api/jobs/'+data['job']['id']).json==data['job']
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
    client.put('/api/jobs/JOB-001',json={'title':'Owner title','notes':'Owner notes','custom':{'keep':1},'status':'applied','source':'','location':'','posted_date':None,'salary_info':False,'salary_note':''})
    monkeypatch.setattr(intake,'fetch_url',lambda url:schema_html(description="CHF 95'000 - 110'000"))
    response=client.post('/api/jobs/JOB-001/enrich')
    assert response.status_code == 200
    job=response.json
    assert (job['title'],job['notes'],job['status'],job['custom']) == ('Owner title','Owner notes','applied',{'keep':1})
    assert job['location'] == 'Basel, CH' and job['posted_date'] == '2026-09-20'
    assert job['salary_info'] and job['enriched']
    assert client.get('/api/companies/'+job['company_id']).json['name'] == 'Lanternpeak Labs'
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
    monkeypatch.setattr(intake,'fetch_url',lambda url:schema_html(hiringOrganization={'name':'Exclusive Test Labs'}))
    created=client.post('/api/jobs/intake',json={'url':'https://jobs.personio.de/lanternpeak/123'}).json
    identifier=created['job']['id']
    company_id=created['company']['id']
    assert created['company']['name_source'] == 'auto'
    monkeypatch.setattr(intake,'fetch_url',lambda url:schema_html(hiringOrganization={'name':'Renamed Labs','url':'https://renamed.example'}))
    assert client.post('/api/jobs/'+identifier+'/enrich').json['company_id'] == company_id
    assert client.get('/api/companies/'+company_id).json['name'] == 'Renamed Labs'
    monkeypatch.setattr(intake,'fetch_url',lambda url:schema_html(hiringOrganization={'name':'pEbBlEoRbIt StUdIo'}))
    assert client.post('/api/jobs/'+identifier+'/enrich').json['company_id'] == 'CO-001'


def test_invalid_schema_and_website():
    html='<script type="application/ld+json">invalid</script>'+schema_html(hiringOrganization={'name':'Labs','sameAs':'javascript:bad','url':'https://labs.example'})
    assert intake.extract('https://jobs.lever.co/labs/123',html)['website'] == 'https://labs.example'


def test_enrich_preserves_shared_company(client, monkeypatch):
    before = client.get('/api/companies/CO-001').json
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html(hiringOrganization={'name':'Different Test Labs'}))
    result = client.post('/api/jobs/JOB-001/enrich')
    assert result.status_code == 200
    assert result.json['company_id'] != 'CO-001'
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
    client.put('/api/jobs/JOB-001', json={'salary_info':False, 'salary_note':''})
    first = client.post('/api/jobs/JOB-001/enrich').json
    assert first['salary_info'] and first['salary_note']
    client.put('/api/jobs/JOB-001', json={'salary_info':False, 'salary_note':'', 'location':''})
    second = client.post('/api/jobs/JOB-001/enrich').json
    assert second['salary_info'] is False and second['salary_note'] == ''
    assert second['location'] == 'Basel, CH'


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
def test_matching_auto_company_website_fill_only(client, monkeypatch, website):
    root = client.application.config['VAULT_PATH']
    company = vault.save_company(root, {'name':'Matching Auto Labs', 'name_source':'auto', 'website':website})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html(hiringOrganization={'name':'Matching Auto Labs', 'url':'https://lanternpeak.example'}))
    result = client.post('/api/jobs/JOB-001/enrich').json
    assert result['company_id'] == company['id']
    assert vault.load_company(root, company['id'])['website'] == (website or 'https://lanternpeak.example')


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
    assert data['company']['size'] == '51-200'
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
