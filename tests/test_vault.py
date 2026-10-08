"""Chunk 1 contracts use only synthetic, disposable vaults."""
from datetime import date
from pathlib import Path
import shutil
import yaml
import pytest
from careeros import vault
from careeros.server import create_app
from careeros.web.markdown import render_markdown

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / 'sample/vault', tmp_path / 'vault')
    return tmp_path / 'vault'

@pytest.fixture
def client(root):
    return create_app(root).test_client()

def test_empty_roundtrip(tmp_path):
    assert vault.load_search(tmp_path) is None
    assert vault.list_experiences(tmp_path) == []
    assert vault.load_experience(tmp_path, 'EXP-001') is None
    assert vault.next_id(tmp_path) == 'EXP-001'
    assert not vault.delete_experience(tmp_path, '../escape')
    data = vault.save_search(tmp_path, {'roles': ['Invented role'], 'notes': '<text>'})
    assert data == vault.load_search(tmp_path)
    assert data['updated'] == date.today().isoformat()
    assert vault.slugify(' Example & Company / Lead! ') == 'example-company-lead'

def test_search_api(client, root):
    data = dict(roles=['Invented lead'], must_haves=['Remote'], nice_to_haves=[], avoid=[], notes='A note')
    response = client.post('/api/search', json=data)
    assert response.status_code == 200
    assert response.json == vault.load_search(root) == client.get('/api/search').json
    assert 'Invented lead' in client.get('/search').text
    assert client.post('/api/search', json={'roles': 'bad'}).status_code == 400
    assert client.post('/api/search', data='{', content_type='application/json').status_code == 400

def test_crud(client, root):
    data = vault.list_experiences(root)[0].copy()
    data.update(company='Fablefern Forge', salary=12345, custom={'Distinct field': '<script>bad</script>', 'Nested': {'a': [1,2]}})
    response = client.post('/api/experiences', json=data)
    assert response.status_code == 201
    new = response.json
    assert new['id'] == 'EXP-004' and new['salary'] is None
    assert client.get('/api/experiences/'+new['id']).json == new
    html = client.get('/experiences/'+new['id']).text
    assert 'Distinct field' in html and '&lt;script&gt;bad&lt;/script&gt;' in html
    assert '<h2>Salary' not in html
    assert client.get('/experiences/'+new['id']+'/edit').status_code == 200
    new['company'] = 'Another Invented Company'
    assert client.put('/api/experiences/'+new['id'], json=new).status_code == 200
    assert len(list((root/'experiences').glob('*.yaml'))) == 4
    assert vault.load_experience(root,new['id'])['company'] == new['company']
    assert client.post('/api/experiences/'+new['id'], json=new).status_code == 200
    assert client.delete('/api/experiences/'+new['id']).status_code == 200
    assert client.get('/api/experiences/'+new['id']).status_code == 404
    assert client.get('/experiences/'+new['id']).status_code == 404
    assert len(client.get('/api/experiences').json) == 3

@pytest.mark.parametrize('patch', [{'start':'2020-13'}, {'end':'1900-01'}, {'people_led':True}, {'people_led':-1}, {'custom':[]}, {'skills':'x'}, {'company':''}])
def test_validation(client, root, patch):
    data = vault.list_experiences(root)[0] | patch
    assert client.post('/api/experiences', json=data).status_code == 400
    assert len(vault.list_experiences(root)) == 3

def test_markdown():
    html = render_markdown('First **bold** and *italic*.\n\n- one\n- two\n\n<script>alert(1)</script>')
    assert '<p>First <strong>bold</strong> and <em>italic</em>.</p>' in html
    assert '<ul><li>one</li><li>two</li></ul>' in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html and '<script>' not in html

def test_empty_ui_and_env(tmp_path, monkeypatch):
    monkeypatch.setenv('CAREEROS_VAULT', str(tmp_path/'missing'))
    app = create_app()
    assert app.config['VAULT_PATH'] == tmp_path/'missing'
    client = app.test_client()
    assert 'Create criteria' in client.get('/search').text
    assert 'No positions yet — add your first one' in client.get('/experiences').text
    assert client.get('/experiences/new').status_code == 200
    assert create_app(tmp_path).config['VAULT_PATH'] == tmp_path

def test_samples_and_sort(root, client):
    entries = vault.list_experiences(root)
    assert len(entries) == 3 and entries[0]['end'] == 'present'
    for entry in entries:
        assert entry['salary'] is None
        html = client.get('/experiences/'+entry['id']).text
        assert '<h2>Salary' not in html and '🔒' not in html
    assert entries[0]['start'] > entries[1]['start'] > entries[2]['start']

def test_file_only_salary(root, client):
    path = next((root/'experiences').glob('*.yaml'))
    data = yaml.safe_load(path.read_text()); data['salary'] = '42 fictional credits'
    path.write_text(yaml.safe_dump(data))
    assert '🔒 private' in client.get('/experiences/'+data['id']).text
    assert client.put('/api/experiences/'+data['id'], json=data | {'salary':None}).json['salary'] == '42 fictional credits'

def test_corrupt_and_nonmapping_yaml_never_crash(root, client):
    """One bad file must not take down a listing, a page, or the search route."""
    # syntactically invalid YAML
    (root / 'experiences' / 'broken-exp-999.yaml').write_text('company: [unclosed\n  - bad')
    # valid YAML but not a mapping
    (root / 'experiences' / 'list-exp-998.yaml').write_text('- alpha\n- beta\n')
    # a corrupt search.yaml
    (root / 'search.yaml').write_text('roles: [unclosed\n')
    # listings and pages still serve, ignoring the poison files
    assert client.get('/experiences').status_code == 200
    listed = client.get('/api/experiences').get_json()
    assert len(listed) == 3, 'corrupt/non-mapping files must be skipped, not fatal'
    assert client.get('/search').status_code == 200
    assert client.get('/api/search').status_code == 200
    # the good entries are all still individually reachable
    for entry in listed:
        assert client.get('/experiences/' + entry['id']).status_code == 200


def test_migrate_job_fields_backfills_every_missing_key(root):
    from careeros import url_normalize
    for job in vault.list_jobs(root):
        assert job.get('normalized_url') is None
    migrated = vault.migrate_job_fields(root)
    assert set(migrated) == {j['id'] for j in vault.list_jobs(root)}
    for job in vault.list_jobs(root):
        assert job['normalized_url'] == url_normalize.normalize(job['url'])
        assert job['in_pipeline'] is True
        assert job['origin'] == 'manual'
        assert job['ingest_state'] == 'complete'
        assert job['ingest_error'] is None
        assert job['source_id'] is None
        assert job['field_provenance'] == {}
        # m6: migration also detects ATS identity for legacy URLs, so a
        # sample job whose URL is a real ATS posting (the Personio one)
        # must come out detected, not stuck at None for every job.
        expected = url_normalize.detect_ats(job['url'])
        assert job['ats_provider'] == (expected.provider if expected else None)
        assert job['ats_tenant'] == (expected.tenant if expected else None)
        assert job['ats_posting_id'] == (expected.posting_id if expected else None)


def test_migrate_job_fields_personio_fixture_detected_independent_of_detector(root):
    # H1 (hardening item from the verification round): the generic loop
    # above computes its own "expected" value by calling the very same
    # url_normalize.detect_ats the migration itself calls, so a shared bug
    # in that function would never be caught by that assertion. This test
    # hard-codes the real, independently-known shape of the one sample job
    # that is a genuine Personio posting (sample/vault/jobs/
    # infrastructure-engineer-job-005.yaml), with no detector call at all.
    vault.migrate_job_fields(root)
    job = vault.load_job(root, 'JOB-005')
    assert job['url'] == 'https://lanternpeak.jobs.personio.de/job/10001'
    assert job['ats_provider'] == 'personio'
    assert job['ats_tenant'] == 'lanternpeak'
    assert job['ats_posting_id'] == '10001'


def test_migrate_job_fields_backfills_present_but_none_ats_triple(root):
    # O3 (was m6, reopened): save_job always writes the full schema, so a
    # legacy ATS posting that went through any unrelated save (e.g. the
    # pre-this-fix migration itself, or a watcher write) ends up with
    # ats_provider/tenant/posting_id present on disk but null -- a shape
    # the old `key not in data` gate treated as "already handled" and
    # never detected, permanently.
    job = vault.load_job(root, 'JOB-005')
    assert job['url'] == 'https://lanternpeak.jobs.personio.de/job/10001'
    path = next(p for p in (root / 'jobs').glob('*.yaml') if yaml.safe_load(p.read_text())['id'] == 'JOB-005')
    data = yaml.safe_load(path.read_text())
    data['normalized_url'] = job['url']
    data['ats_provider'] = None
    data['ats_tenant'] = None
    data['ats_posting_id'] = None
    path.write_text(yaml.safe_dump(data))

    migrated = vault.migrate_job_fields(root)

    assert 'JOB-005' in migrated
    updated = vault.load_job(root, 'JOB-005')
    assert updated['ats_provider'] == 'personio'
    assert updated['ats_tenant'] == 'lanternpeak'
    assert updated['ats_posting_id'] == '10001'


def test_migrate_job_fields_preserves_explicit_non_null_ats_values(root):
    # The other half of O3: a present-but-None triple is backfilled, but an
    # explicit non-null value already on disk (a real prior detection) must
    # never be clobbered by a fresh detection result, even a different one.
    path = next(p for p in (root / 'jobs').glob('*.yaml') if yaml.safe_load(p.read_text())['id'] == 'JOB-005')
    data = yaml.safe_load(path.read_text())
    data['normalized_url'] = data['url']
    data['ats_provider'] = 'custom-provider'
    data['ats_tenant'] = None
    data['ats_posting_id'] = None
    path.write_text(yaml.safe_dump(data))

    migrated = vault.migrate_job_fields(root)

    assert 'JOB-005' in migrated
    updated = vault.load_job(root, 'JOB-005')
    assert updated['ats_provider'] == 'custom-provider'
    assert updated['ats_tenant'] == 'lanternpeak'
    assert updated['ats_posting_id'] == '10001'


def test_migrate_job_fields_backfilled_ats_identity_matches_as_duplicate(root):
    # H2 (pairs with O3): once the present-but-None triple is backfilled by
    # migration, a re-add of an alternate-form URL for the same posting
    # must be caught by the hard duplicate check, not slip through as a
    # second record because the stored identity was never detected.
    from careeros import dedupe, url_normalize
    path = next(p for p in (root / 'jobs').glob('*.yaml') if yaml.safe_load(p.read_text())['id'] == 'JOB-005')
    data = yaml.safe_load(path.read_text())
    data['normalized_url'] = data['url']
    data['ats_provider'] = None
    data['ats_tenant'] = None
    data['ats_posting_id'] = None
    path.write_text(yaml.safe_dump(data))
    vault.migrate_job_fields(root)

    # A different host form (.com instead of .de) of the same tenant's
    # posting: normalized_url differs (so the same_url check cannot match),
    # but the ATS identity (provider, tenant, posting id) is identical,
    # exercising the same_ats_posting_id path specifically.
    alternate_url = 'https://lanternpeak.jobs.personio.com/job/10001'
    ats_match = url_normalize.detect_ats(alternate_url)
    existing, basis = dedupe.find_duplicate(root, url_normalize.normalize(alternate_url), ats_match)
    assert existing is not None and existing['id'] == 'JOB-005'
    assert basis == 'same_ats_posting_id'


def test_migrate_job_fields_second_run_is_a_no_op(root):
    first = vault.migrate_job_fields(root)
    assert first
    before = vault.list_jobs(root)
    second = vault.migrate_job_fields(root)
    assert second == []
    assert vault.list_jobs(root) == before


def test_migrate_job_fields_never_overwrites_user_set_values(root):
    sample_id = vault.list_jobs(root)[0]['id']
    vault.save_job(root, {'in_pipeline': False, 'origin': 'discovered'}, sample_id)
    migrated = vault.migrate_job_fields(root)
    assert sample_id in migrated
    updated = vault.load_job(root, sample_id)
    assert updated['in_pipeline'] is False
    assert updated['origin'] == 'discovered'
    assert updated['normalized_url']


def test_migrate_job_fields_tolerates_legacy_record_with_blank_url(root):
    # Written directly, bypassing save_job's validation, the same way a
    # pre-validation legacy record or a watcher-only write can exist on disk.
    path = root / 'jobs' / 'blank-url-job-999.yaml'
    path.write_text('id: JOB-999\ntitle: Blank URL job\nurl: \'\'\n')
    migrated = vault.migrate_job_fields(root)
    assert 'JOB-999' in migrated
    assert vault.load_job(root, 'JOB-999')['normalized_url'] == ''


def test_migrate_job_fields_isolates_one_malformed_url_record(root, capsys):
    # M5: a single record whose url cannot be normalized (an invalid port,
    # the same shape that raises ValueError from urlsplit().port) must not
    # abort the whole sweep; it is left byte-for-byte untouched and
    # reported, while every other record still migrates normally.
    path = root / 'jobs' / 'malformed-job-999.yaml'
    original_text = "id: JOB-999\ntitle: Malformed URL job\nurl: 'https://example.com:bad/x'\n"
    path.write_text(original_text)
    good_ids = {j['id'] for j in vault.list_jobs(root)} - {'JOB-999'}

    migrated = vault.migrate_job_fields(root)

    assert path.read_text() == original_text, 'the malformed record must be left completely unchanged'
    assert 'JOB-999' not in migrated
    assert good_ids <= set(migrated)
    assert vault.load_job(root, 'JOB-999').get('normalized_url') is None
    assert 'JOB-999' in capsys.readouterr().err


def test_app_startup_survives_one_malformed_url_record(root):
    # The migration runs under the write lock at create_app startup
    # (server.py); one bad legacy record must not take the whole app down.
    (root / 'jobs' / 'malformed-job-998.yaml').write_text(
        "id: JOB-998\ntitle: Malformed URL job\nurl: 'https://example.com:bad/x'\n")
    app = create_app(root)
    assert app.test_client().get('/api/jobs').status_code == 200


def test_no_host_path_in_implementation():
    forbidden = '/root/' + 'career-os'
    for folder in ('careeros','tests','scripts','sample'):
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and path.suffix in ('.py','.html','.yaml'):
                if path == ROOT/'careeros/server.py':
                    assert path.read_text().count(forbidden) == 1
                else:
                    assert forbidden not in path.read_text(), path


def test_migrate_null_greenhouse_identity_matches_alternate_form(root):
    from careeros import dedupe, url_normalize
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://boards.greenhouse.io/fixture/jobs/7654'})
    assert all(job[key] is None for key in ('ats_provider', 'ats_tenant', 'ats_posting_id'))
    vault.migrate_job_fields(root)
    migrated = vault.load_job(root, job['id'])
    assert (migrated['ats_provider'], migrated['ats_tenant'], migrated['ats_posting_id']) == ('greenhouse', 'fixture', '7654')
    alternate = 'https://job-boards.greenhouse.io/fixture/jobs/7654'
    match, basis = dedupe.find_duplicate(root, url_normalize.normalize(alternate), url_normalize.detect_ats(alternate))
    assert match['id'] == job['id']
    assert basis == 'same_ats_posting_id'
