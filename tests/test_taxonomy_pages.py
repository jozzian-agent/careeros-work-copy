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


def test_company_taxonomy_page_renders(client, root):
    company = vault.save_company(root, {'name': 'Fiction Co'})
    html = client.get(f'/companies/{company["id"]}/taxonomy').text
    assert 'Kind' in html and 'Sectors (ISIC Rev.4)' in html
    assert 'aggregate' not in html


def test_job_taxonomy_unknown_id_404(client):
    assert client.get('/jobs/JOZ-999999/taxonomy').status_code == 404


def test_detail_pages_link_to_taxonomy(client, root):
    job = vault.save_job(root, {'title': 'AI PM', 'url': 'https://fiction.example/pm2'})
    company = vault.save_company(root, {'name': 'Link Co'})
    assert f'/jobs/{job["id"]}/taxonomy' in client.get(f'/jobs/{job["id"]}').text
    assert f'/companies/{company["id"]}/taxonomy' in client.get(f'/companies/{company["id"]}').text


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
