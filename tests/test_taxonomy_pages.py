"""Taxonomy sub-pages (approved wireframe 2026-10-07): job and company
classification pages render, link from detail pages, and persist through
the existing APIs. Synthetic fixtures only; never touches a real vault."""
from pathlib import Path
import shutil

import pytest

from careeros import vault
from careeros.server import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / 'sample/vault', tmp_path / 'vault')
    vault.seed_function_facet(tmp_path / 'vault')
    return tmp_path / 'vault'


@pytest.fixture
def client(root):
    return create_app(root).test_client()


def test_job_taxonomy_page_renders(client, root):
    job = vault.save_job(root, {'title': 'AI PM', 'url': 'https://fiction.example/pm'})
    html = client.get(f'/jobs/{job["id"]}/taxonomy').text
    assert 'Function (ESCO)' in html
    assert 'Sector' in html and 'belongs to the company' in html
    assert 'Tags' in html


def test_company_taxonomy_page_is_retired(client, root):
    # B6: the standalone company classification page and the JSON API
    # behind it are gone; the company detail context carries the same
    # classification data (tests/test_company_page_context.py) and the
    # detail page edits it in a popup.
    company = vault.save_company(root, {'name': 'Fiction Co'})
    assert client.get(f'/api/companies/{company["id"]}/taxonomy').status_code == 404
    assert client.get(f'/companies/{company["id"]}/taxonomy').status_code == 404


def test_job_taxonomy_unknown_id_404(client):
    assert client.get('/jobs/JOZ-999999/taxonomy').status_code == 404


def test_job_detail_omits_standalone_taxonomy_link(client, root):
    # JOZ-280: the React Job detail page's "Edit classification" opens the
    # Edit criteria popup inline (approved Phase A wireframe), rather than
    # navigating to the standalone /jobs/<id>/taxonomy page the old Jinja
    # detail.html linked to; that page itself is untouched and still
    # reachable directly, just no longer linked from the job detail header.
    # Classification data for the popup comes from the unchanged JSON API.
    job = vault.save_job(root, {'title': 'AI PM', 'url': 'https://fiction.example/pm2'})
    data = client.get(f'/api/jobs/{job["id"]}/taxonomy').json
    assert data['job']['id'] == job['id']


def test_job_taxonomy_save_roundtrip(client, root):
    vault.save_tags(root, {'facets': {'tool': {'label': 'Tool', 'values': [{'id': 'python', 'label': 'Python'}]}}})
    job = vault.save_job(root, {'title': 'AI PM', 'url': 'https://fiction.example/pm3'})
    response = client.put(f'/api/jobs/{job["id"]}', json={'tags': ['tool:python']})
    assert response.status_code == 200
    assert response.json['tags'] == ['tool:python']
    # Persisted in the vault, not just echoed back.
    assert vault.load_job(root, job['id'])['tags'] == ['tool:python']


def test_job_taxonomy_rejects_unproposed_tag(client, root):
    job = vault.save_job(root, {'title': 'AI PM', 'url': 'https://fiction.example/pm4'})
    response = client.put(f'/api/jobs/{job["id"]}', json={'tags': ['tool:unknown-tool']})
    assert response.status_code == 400


def test_job_taxonomy_accepts_proposed_tag(client, root):
    job = vault.save_job(root, {'title': 'AI PM', 'url': 'https://fiction.example/pm5'})
    response = client.put(f'/api/jobs/{job["id"]}',
                          json={'tags': ['tool:mlops'], 'proposed_tags': ['tool:mlops']})
    assert response.status_code == 200
    assert response.json['tags'] == ['tool:mlops']
    registry = vault.load_tags(root)
    assert any(v['id'] == 'mlops' for v in registry['facets']['tool']['values'])


def test_company_taxonomy_save_roundtrip(client, root):
    company = vault.save_company(root, {'name': 'Fiction Co', 'sectors': ['C']})
    response = client.put(f'/api/companies/{company["id"]}',
                          json={'sectors': ['C', 'J'], 'size_class': 'medium', 'kind': 'employer'})
    assert response.status_code == 200
    assert response.json['sectors'] == ['C', 'J']
    assert response.json['size_class'] == 'medium'
