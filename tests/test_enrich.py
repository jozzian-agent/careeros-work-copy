"""Company facts use disposable vaults and never need network access."""
from copy import deepcopy
from datetime import date
import socket

import pytest
import yaml

from careeros import vault
from careeros.enrich import enrich_company, regenerate_company
from careeros.server import create_app


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Network access during company enrichment')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr('careeros.ingest.extract', forbidden)


def test_aggregation():
    jobs = [
        dict(sectors=['Health', 'Software'], industry='Research', location='Berlin',
             remote_ok=False, seniority='junior', keywords=['Python', 'python', 'SQL'],
             posted_date='2025-01-01'),
        dict(sector='Software', industries=['Finance'], location='Paris', remote_ok=True,
             seniority='principal', keywords=['PYTHON', 'Cloud'], posted_date=date(2025, 2, 1)),
        dict(location='Berlin', remote_ok=None, seniority='senior', keywords=['SQL']),
    ]
    original = deepcopy(jobs)
    assert enrich_company(iter(jobs)) == dict(
        sectors=['Finance', 'Health', 'Research', 'Software'], locations_seen=['Berlin', 'Paris'],
        remote_friendly=True, seniority_range={'min': 'junior', 'max': 'principal'},
        hiring_activity={'count': 3, 'most_recent_posted_date': '2025-02-01'},
        top_keywords=['python', 'sql', 'cloud'])
    assert jobs == original


def test_empty_and_legacy_values():
    empty = enrich_company([])
    assert empty == dict(sectors=[], locations_seen=[], remote_friendly=False,
                         seniority_range={'min': None, 'max': None},
                         hiring_activity={'count': 0, 'most_recent_posted_date': None}, top_keywords=[])
    result = enrich_company([dict(sectors=42, location=None, keywords=[None, ' '],
                                  remote_ok='true', seniority='unknown', posted_date='invalid')])
    assert result == empty | {'hiring_activity': {'count': 1, 'most_recent_posted_date': None}}


def test_keyword_cap_and_ties():
    words = [f'word{i:02}' for i in range(15)]
    assert enrich_company([{'keywords': words[::-1]}])['top_keywords'] == words[:10]
    assert enrich_company([{'seniority': 'Entry-Level'}, {'seniority': 'Senior'}])['seniority_range'] == {'min': 'entry', 'max': 'senior'}


def test_regeneration_lifecycle_preserves_owner_fields(tmp_path):
    company = vault.save_company(tmp_path, dict(name='Example', sector='Owner sector',
        locations=['Owner location'], notes='Owner notes', custom={'keep': True}))
    path = next((tmp_path / 'companies').glob('*.yaml'))
    data = yaml.safe_load(path.read_text()) | {'owner_extension': {'keep': 1},
        'enrichment': {'future': 7, 'hiring_activity': {'future': 8}}}
    path.write_text(yaml.safe_dump(data))
    first = vault.save_job(tmp_path, dict(title='First', url='https://example.com/first', company_id=company['id'],
        sector='Software', remote_ok=True, seniority='senior', posted_date='2025-01-01'))
    second = vault.save_job(tmp_path, dict(title='Second', url='https://example.com/second', company_id=company['id'],
        industries=['Research'], location='Paris', posted_date='2025-02-01'))
    saved = vault.load_company(tmp_path, company['id'])
    assert {k: v for k, v in saved.items() if k != 'enrichment'} == {k: v for k, v in data.items() if k != 'enrichment'}
    assert saved['enrichment']['future'] == 7
    assert saved['enrichment']['hiring_activity'] == {'count': 2, 'most_recent_posted_date': '2025-02-01', 'future': 8}
    vault.delete_job(tmp_path, second['id'])
    saved = vault.load_company(tmp_path, company['id'])['enrichment']
    assert saved['sectors'] == ['Software']
    assert saved['hiring_activity']['count'] == 1
    assert saved['hiring_activity']['most_recent_posted_date'] == '2025-01-01'
    other = vault.save_company(tmp_path, {'name': 'Other'})
    vault.save_job(tmp_path, {'company_id': other['id'], 'remote_ok': False}, first['id'])
    assert vault.load_company(tmp_path, company['id'])['enrichment']['hiring_activity']['count'] == 0
    destination = vault.load_company(tmp_path, other['id'])['enrichment']
    assert destination['remote_friendly'] is False
    assert destination['hiring_activity']['count'] == 1
    assert destination['sectors'] == ['Software']
    assert destination['hiring_activity']['most_recent_posted_date'] == '2025-01-01'
    vault.delete_job(tmp_path, first['id'])
    assert vault.load_company(tmp_path, other['id'])['enrichment'] == enrich_company([])
    assert regenerate_company(tmp_path, 'missing') is None


@pytest.mark.parametrize('block', [None, [], {'sectors': 'bad'}, {'locations_seen': [2]},
    {'top_keywords': [False]}, {'remote_friendly': 1}, {'seniority_range': []},
    {'seniority_range': {'min': 1}}, {'seniority_range': {'max': []}},
    {'hiring_activity': []}, {'hiring_activity': {'count': True}},
    {'hiring_activity': {'count': -1}}, {'hiring_activity': {'most_recent_posted_date': 'bad'}},
    {'hiring_activity': {'most_recent_posted_date': 123}}])
def test_enrichment_validation(tmp_path, block):
    with pytest.raises(ValueError):
        vault.save_company(tmp_path, {'name': 'Example', 'enrichment': block})
    assert vault.list_companies(tmp_path) == []


def test_refresh_route(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Example', 'enrichment': {'future': 1}})
    client = create_app(tmp_path).test_client()
    response = client.post(f"/api/companies/{company['id']}/enrich")
    assert response.status_code == 200
    assert response.json['enrichment'] == enrich_company([]) | {'future': 1}
    assert response.json == vault.load_company(tmp_path, company['id'])
    assert client.post('/api/companies/missing/enrich').status_code == 404


def test_updates_unlink_and_watcher_persistence(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Example'})
    job = vault.save_job(tmp_path, dict(title='Role', url='https://example.com/job',
                                      company_id=company['id'], keywords=['Old']))
    job = vault.save_job(tmp_path, {'keywords': ['New'], 'remote_ok': True}, job['id'])
    assert vault.load_company(tmp_path, company['id'])['enrichment']['top_keywords'] == ['new']
    assert vault.load_company(tmp_path, company['id'])['enrichment']['remote_friendly'] is True
    vault.save_company(tmp_path, {'enrichment': {}}, company['id'])
    with vault.WriteLock(tmp_path):
        vault.save_watch_result(tmp_path, job)
    assert vault.load_company(tmp_path, company['id'])['enrichment']['hiring_activity']['count'] == 1
    vault.save_job(tmp_path, {'company_id': None}, job['id'])
    assert vault.load_company(tmp_path, company['id'])['enrichment'] == enrich_company([])
    assert vault.delete_job(tmp_path, job['id']) is True
    assert vault.delete_job(tmp_path, job['id']) is False


def test_refresh_legacy_postings(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Example'})
    (tmp_path / 'jobs').mkdir()
    (tmp_path / 'jobs' / 'legacy.yaml').write_text(yaml.safe_dump(dict(
        id='JOB-001', company_id=company['id'], sector='Research',
        location='Paris', seniority='senior', keywords=['Python'])))
    client = create_app(tmp_path).test_client()
    result = client.post(f"/api/companies/{company['id']}/enrich")
    assert result.status_code == 200
    assert result.json['enrichment']['sectors'] == ['Research']
    assert result.json['enrichment']['top_keywords'] == ['python']
    assert result.json['enrichment']['hiring_activity']['count'] == 1


def test_delete_succeeds_when_regeneration_fails(tmp_path, monkeypatch):
    company = vault.save_company(tmp_path, {'name': 'Example'})
    job = vault.save_job(tmp_path, {'title': 'Role', 'url': 'https://example.com/job', 'company_id': company['id']})

    def fail(*args):
        raise OSError('Derived write failed')

    monkeypatch.setattr('careeros.enrich.regenerate_company', fail)
    assert vault.delete_job(tmp_path, job['id']) is True
    assert vault.load_job(tmp_path, job['id']) is None


def test_save_regenerates_other_company_after_failure(tmp_path, monkeypatch):
    source = vault.save_company(tmp_path, {'name': 'Source'})
    destination = vault.save_company(tmp_path, {'name': 'Destination'})
    job = vault.save_job(tmp_path, {'title': 'Role', 'url': 'https://example.com/job', 'company_id': source['id'],
                                    'sector': 'Research'})
    calls = []

    def fail_source(root, identifier):
        calls.append(identifier)
        if identifier == source['id']:
            raise OSError('Derived write failed')
        return regenerate_company(root, identifier)

    monkeypatch.setattr('careeros.enrich.regenerate_company', fail_source)
    saved = vault.save_job(tmp_path, {'company_id': destination['id']}, job['id'])
    assert saved == vault.load_job(tmp_path, job['id'])
    assert saved['company_id'] == destination['id']
    assert calls == [source['id'], destination['id']]
    block = vault.load_company(tmp_path, destination['id'])['enrichment']
    assert block['hiring_activity']['count'] == 1
    assert block['sectors'] == ['Research']


@pytest.mark.parametrize('block', [{'remote_friendly': 'yes'}, {'hiring_activity': []}, 'bad'])
def test_corrupt_enrichment_allows_unrelated_save_and_self_heals(tmp_path, block):
    company = vault.save_company(tmp_path, {'name': 'Example'})
    job = vault.save_job(tmp_path, {'title': 'Role', 'url': 'https://example.com/job', 'company_id': company['id']})
    path = next((tmp_path / 'companies').glob('*.yaml'))
    data = yaml.safe_load(path.read_text())
    data['enrichment'] = block
    path.write_text(yaml.safe_dump(data))
    saved = vault.save_company(tmp_path, {'notes': 'Owner note'}, company['id'])
    assert saved['notes'] == 'Owner note'
    vault.save_job(tmp_path, {'notes': 'Job note'}, job['id'])
    healed = vault.load_company(tmp_path, company['id'])
    assert healed['enrichment'] == enrich_company(vault.list_jobs(tmp_path))
    assert healed['notes'] == 'Owner note'


def test_job_edit_reuses_existing_lookup(tmp_path, monkeypatch):
    job = vault.save_job(tmp_path, {'title': 'Role', 'url': 'https://example.com/job'})
    records = vault._records
    scans = []

    def counted(root, kind):
        scans.append(kind)
        yield from records(root, kind)

    monkeypatch.setattr(vault, '_records', counted)
    saved = vault.save_job(tmp_path, {'notes': 'Updated'}, job['id'])
    assert saved['notes'] == 'Updated'
    assert scans == ['jobs']


@pytest.mark.parametrize('field', ['sectors', 'industries'])
def test_legacy_null_lists_load_and_save(tmp_path, field):
    job = vault.save_job(tmp_path, {'title': 'Role', 'url': 'https://example.com/job'})
    path = next((tmp_path / 'jobs').glob('*.yaml'))
    data = yaml.safe_load(path.read_text())
    data[field] = None
    path.write_text(yaml.safe_dump(data))
    assert vault.load_job(tmp_path, job['id'])[field] == []
    assert vault.list_jobs(tmp_path)[0][field] == []
    saved = vault.save_job(tmp_path, {'notes': 'Updated'}, job['id'])
    assert saved[field] == []
    assert yaml.safe_load(path.read_text())[field] == []
    assert vault.save_job(tmp_path, {field: None}, job['id'])[field] == []
