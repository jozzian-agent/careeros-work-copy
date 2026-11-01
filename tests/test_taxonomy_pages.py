"""Classification: both standalone taxonomy pages are retired, and the
JSON the popups that replaced them read is still answered and still
persists. Synthetic fixtures only; never touches a real vault.

The company page went with B6 and the job page on 2026-11-01, each one
orphaned by the Edit classification popup on the React detail page. What
the removals leave behind is pinned here as two 404s; the save
round-trips below are unchanged, because they always went through the
JSON API rather than through either page's own markup."""
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


def test_job_taxonomy_page_is_retired(client, root):
    # 2026-11-01: the standalone job classification page is gone, flag on
    # or off, like the company one below. Nothing in the React app linked
    # to it -- the Job detail page's Edit classification popup is what
    # edits a job's classification -- and the JSON endpoint it shared its
    # context with stays, which is the next assertion.
    job = vault.save_job(root, {'title': 'AI PM', 'url': 'https://fiction.example/pm'})
    assert client.get(f'/jobs/{job["id"]}/taxonomy').status_code == 404
    data = client.get(f'/api/jobs/{job["id"]}/taxonomy').json
    assert [key for key in ('job', 'function_options', 'tags', 'tag_registry')
            if key not in data] == []


def test_company_taxonomy_page_is_retired(client, root):
    # B6: the standalone company classification page and the JSON API
    # behind it are gone; the company detail context carries the same
    # classification data (tests/test_company_page_context.py) and the
    # detail page edits it in a popup.
    company = vault.save_company(root, {'name': 'Fiction Co'})
    assert client.get(f'/api/companies/{company["id"]}/taxonomy').status_code == 404
    assert client.get(f'/companies/{company["id"]}/taxonomy').status_code == 404


def test_job_taxonomy_api_unknown_id_404(client):
    assert client.get('/api/jobs/JOZ-999999/taxonomy').status_code == 404


def test_job_detail_reads_its_classification_from_the_api(client, root):
    # JOZ-280: the React Job detail page's "Edit classification" opens the
    # popup inline (approved Phase A wireframe) rather than navigating to
    # the standalone /jobs/<id>/taxonomy page the old Jinja detail.html
    # linked to. That page is gone as of 2026-11-01; this is the endpoint
    # the popup reads instead.
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
