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


def test_no_host_path_in_implementation():
    forbidden = '/root/' + 'career-os'
    for folder in ('careeros','tests','scripts','sample'):
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and path.suffix in ('.py','.html','.yaml'):
                if path == ROOT/'careeros/server.py':
                    assert path.read_text().count(forbidden) == 1
                else:
                    assert forbidden not in path.read_text(), path
