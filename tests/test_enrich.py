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
        top_keywords=['python', 'sql', 'cloud'],
        # No posting here states a headcount, so there is no size evidence
        # to carry (owner decision 2026-10-16); the keys are still present,
        # because an absent key and a null one would read the same to the
        # promotion tier while only one of them clears a stale value.
        employee_count=None, employee_count_evidence=None)
    assert jobs == original


def test_empty_and_legacy_values():
    empty = enrich_company([])
    assert empty == dict(sectors=[], locations_seen=[], remote_friendly=False,
                         seniority_range={'min': None, 'max': None},
                         hiring_activity={'count': 0, 'most_recent_posted_date': None}, top_keywords=[],
                         employee_count=None, employee_count_evidence=None)
    result = enrich_company([dict(sectors=42, location=None, keywords=[None, ' '],
                                  remote_ok='true', seniority='unknown', posted_date='invalid',
                                  employee_count='many')])
    assert result == empty | {'hiring_activity': {'count': 1, 'most_recent_posted_date': None}}


# --- Posting headcount as company size evidence (owner decision 2026-10-16)

def test_a_posting_headcount_becomes_company_size_evidence():
    """The count a posting states used to be read once, at intake, and
    then be nothing to the company: the job kept it and no size signal
    ever saw it again. It is evidence toward `size_class`, so it is
    aggregated onto the company where the capability's zero-network
    promotion tier reads it (`enrichment['employee_count']`), with the
    posting that stated it recorded beside it."""
    result = enrich_company([
        dict(id='JOB-001', employee_count=40, posted_date='2025-01-01'),
        dict(id='JOB-002', employee_count=120, posted_date='2025-02-01'),
    ])
    assert result['employee_count'] == 120  # the most recently posted one
    assert result['employee_count_evidence'] == {
        'count': 120, 'job_id': 'JOB-002', 'posted_date': '2025-02-01'}


def test_an_undated_posting_headcount_is_evidence_when_no_dated_one_is():
    """The rule the enrichment-evidence decision already settled for
    Wikidata statements: prefer the latest usable date, otherwise take the
    first statement. Refusing an undated count outright was the draft
    proposal that decision superseded."""
    assert enrich_company([dict(id='JOB-009', employee_count=7)])['employee_count'] == 7
    both = enrich_company([dict(id='JOB-009', employee_count=7),
                           dict(id='JOB-010', employee_count=900, posted_date='2025-03-01')])
    assert both['employee_count'] == 900


@pytest.mark.parametrize('count', [None, 0, -5, True, 'many', 12.5])
def test_an_unreadable_posting_headcount_is_absent_evidence(count):
    """Absent evidence, never a zero: a count nothing can read must not
    become a number a size class gets derived from, and must not displace
    a count another posting does state."""
    assert enrich_company([dict(id='JOB-001', employee_count=count)])['employee_count'] is None
    with_real = enrich_company([dict(id='JOB-001', employee_count=count),
                                dict(id='JOB-002', employee_count=120)])
    assert with_real['employee_count'] == 120


def test_a_posting_headcount_leaves_the_retired_size_scales_alone(tmp_path):
    """The evidence feeds the class and only the class. The numeric
    `size_range` and the legacy `size` string are the two scales the
    2026-10-15 decision retired, and a headcount arriving by a new route
    must not be how either comes back."""
    company = vault.save_company(tmp_path, {'name': 'Headcount Co'})
    vault.save_job(tmp_path, {'title': 'Role', 'url': 'https://headcount.example/one',
                              'company_id': company['id'], 'employee_count': 120})
    saved = vault.load_company(tmp_path, company['id'])
    assert saved['enrichment']['employee_count'] == 120
    assert saved['size_range'] is None and saved['size'] is None
    # And the class itself is not written behind the cascade's back: this
    # is evidence a size run can use, not a value this aggregation sets.
    assert saved['size_class'] is None


def test_a_non_employer_keeps_no_posting_headcount_evidence(tmp_path):
    """Section 1's field-group matrix gives an institution no size at all,
    and the re-kind path has to actively delete what an earlier
    regeneration stored rather than merely stop deriving it -- the same
    rule the nested `enrichment.sectors` rollup already follows."""
    company = vault.save_company(tmp_path, {'name': 'Example University'})
    vault.save_job(tmp_path, {'title': 'Role', 'url': 'https://example.edu/one',
                              'company_id': company['id'], 'employee_count': 4000,
                              'sector': 'Software'})
    assert vault.load_company(tmp_path, company['id'])['enrichment']['employee_count'] == 4000

    vault.save_company(tmp_path, {'kind': 'institution'}, company['id'])
    regenerate_company(tmp_path, company['id'])

    enrichment = vault.load_company(tmp_path, company['id'])['enrichment']
    assert 'employee_count' not in enrichment
    assert 'employee_count_evidence' not in enrichment
    assert 'sectors' not in enrichment


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
    {'hiring_activity': {'most_recent_posted_date': 123}},
    # Size evidence from the company's own postings: a count a class could
    # be derived from has to be a real headcount, and the record of which
    # posting stated it has to be an object.
    {'employee_count': 0}, {'employee_count': -2}, {'employee_count': True},
    {'employee_count': '120'}, {'employee_count_evidence': 'JOB-001'},
    {'employee_count_evidence': []}])
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
