"""Section 1 (Company Unification): kind, company_id linking, merge-on-save
semantics, deletion guard, link-company endpoint, live label resolution.
Synthetic fixtures only; never touches a real vault."""
from pathlib import Path
import shutil

import pytest

from careeros import vault
from careeros.server import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / 'sample/vault', tmp_path / 'vault')
    return tmp_path / 'vault'


@pytest.fixture
def client(root):
    return create_app(root).test_client()


# --- Engineering item 1: kind field + backfill -----------------------------

def test_new_company_defaults_to_employer_kind(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Fiction Co'})
    assert company['kind'] == 'employer'


def test_backfill_assigns_kind_to_every_existing_company(root):
    for company in vault.list_companies(root):
        assert company.get('kind') is None
    updated = vault.backfill_company_kind(root)
    assert set(updated) == {c['id'] for c in vault.list_companies(root)}
    for company in vault.list_companies(root):
        assert company['kind'] == 'employer'


def test_invalid_kind_rejected(tmp_path):
    with pytest.raises(ValueError, match='kind'):
        vault.save_company(tmp_path, {'name': 'Fiction Co', 'kind': 'bogus'})


def test_institution_kind_accepted_and_aggregate_removed(tmp_path):
    # Owner decision 2026-10-07: the aggregate kind never applied to a real
    # record and was removed from the vocabulary.
    institution = vault.save_company(tmp_path, {'name': 'Fiction University', 'kind': 'institution'})
    assert institution['kind'] == 'institution'
    with pytest.raises(ValueError, match='kind'):
        vault.save_company(tmp_path, {'name': 'Early Career', 'kind': 'aggregate'})


# --- Engineering item 2: company_id on experiences + existence check ------

def test_experience_company_id_must_reference_real_company(tmp_path):
    vault.save_experience(tmp_path, {'company': 'Freelance', 'title': 'Builder', 'start': '2020-01', 'end': 'present'})
    with pytest.raises(ValueError, match='Company not found'):
        vault.save_experience(tmp_path, {'company': 'Freelance', 'title': 'Builder',
                                         'start': '2020-01', 'end': 'present', 'company_id': 'CO-999'})


def test_experience_company_id_links_to_real_company(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Fiction Co'})
    exp = vault.save_experience(tmp_path, {'company': 'Fiction Co', 'title': 'Builder',
                                           'start': '2020-01', 'end': 'present', 'company_id': company['id']})
    assert exp['company_id'] == company['id']


# --- Engineering item 3: save_experience merges onto the existing record --

def test_experience_save_merges_absent_keys_unchanged(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Fiction Co'})
    exp = vault.save_experience(tmp_path, {'company': 'Fiction Co', 'title': 'Builder', 'start': '2020-01',
                                           'end': 'present', 'company_id': company['id'], 'tags': [],
                                           'highlights': ['Shipped it']})
    updated = vault.save_experience(tmp_path, {'title': 'Senior Builder'}, exp['id'])
    assert updated['company_id'] == company['id']
    assert updated['highlights'] == ['Shipped it']
    assert updated['title'] == 'Senior Builder'


def test_experience_put_missing_company_id_and_tags_unchanged(client, root):
    company = vault.save_company(root, {'name': 'Fiction Co'})
    created = client.post('/api/experiences', json={'company': 'Fiction Co', 'title': 'Builder',
                                                     'start': '2020-01', 'end': 'present',
                                                     'company_id': company['id'], 'tags': ['tool:python'],
                                                     'proposed_tags': ['tool:python']}).json
    response = client.put('/api/experiences/' + created['id'], json={'title': 'Updated title'})
    assert response.status_code == 200
    assert response.json['company_id'] == company['id']
    assert response.json['tags'] == ['tool:python']


# --- Engineering item 4: deletion guard extended to experiences -----------

def test_delete_company_blocked_by_linked_experience_only(client, root):
    company = vault.save_company(root, {'name': 'Fiction Co'})
    vault.save_experience(root, {'company': 'Fiction Co', 'title': 'Builder', 'start': '2020-01',
                                 'end': 'present', 'company_id': company['id']})
    response = client.delete('/api/companies/' + company['id'])
    assert response.status_code == 409
    assert response.json == {'error': 'Still linked to 1 experiences', 'count': 1}


def test_delete_company_blocked_by_both_jobs_and_experiences(client, root):
    company = vault.save_company(root, {'name': 'Fiction Co'})
    vault.save_job(root, {'title': 'Role', 'url': 'https://fiction.example/job', 'company_id': company['id']})
    vault.save_experience(root, {'company': 'Fiction Co', 'title': 'Builder', 'start': '2020-01',
                                 'end': 'present', 'company_id': company['id']})
    response = client.delete('/api/companies/' + company['id'])
    assert response.status_code == 409
    assert response.json == {'error': 'Still linked to 1 jobs and 1 experiences', 'count': 2}


def test_delete_company_unblocked_once_unlinked(client, root):
    company = vault.save_company(root, {'name': 'Fiction Co'})
    exp = vault.save_experience(root, {'company': 'Fiction Co', 'title': 'Builder', 'start': '2020-01',
                                       'end': 'present', 'company_id': company['id']})
    vault.save_experience(root, {'company_id': None}, exp['id'])
    assert client.delete('/api/companies/' + company['id']).json == {'deleted': company['id']}


# --- Engineering item 5: link-company endpoint -----------------------------

def test_link_company_to_existing(client, root):
    exp = vault.save_experience(root, {'company': 'Freelance', 'title': 'Builder', 'start': '2020-01', 'end': 'present'})
    company = vault.save_company(root, {'name': 'Fiction Co'})
    response = client.post('/api/experiences/' + exp['id'] + '/link-company', json={'company_id': company['id']})
    assert response.status_code == 200
    assert response.json['company_id'] == company['id']


def test_link_company_missing_company_id_404(client, root):
    exp = vault.save_experience(root, {'company': 'Freelance', 'title': 'Builder', 'start': '2020-01', 'end': 'present'})
    response = client.post('/api/experiences/' + exp['id'] + '/link-company', json={'company_id': 'CO-999'})
    assert response.status_code == 404


def test_link_company_create_new_path(client, root):
    exp = vault.save_experience(root, {'company': 'Brand New Startup', 'title': 'Builder',
                                       'start': '2020-01', 'end': 'present'})
    response = client.post('/api/experiences/' + exp['id'] + '/link-company',
                           json={'create': {'name': 'Brand New Startup', 'kind': 'employer'}})
    assert response.status_code == 201
    updated = response.json
    assert updated['company_id'] is not None
    company = vault.load_company(root, updated['company_id'])
    assert company['name'] == 'Brand New Startup' and company['kind'] == 'employer'


def test_link_company_create_dedupe_suggestion_path(client, root):
    existing = vault.save_company(root, {'name': 'Acme AG'})
    before = len(vault.list_companies(root))
    exp = vault.save_experience(root, {'company': 'Acme', 'title': 'Builder', 'start': '2020-01', 'end': 'present'})
    response = client.post('/api/experiences/' + exp['id'] + '/link-company', json={'create': {'name': 'Acme'}})
    assert response.status_code == 200
    assert response.json['suggestion']['id'] == existing['id']
    # The suggestion must not have silently linked or created anything.
    assert vault.load_experience(root, exp['id'])['company_id'] is None
    assert len(vault.list_companies(root)) == before


def test_link_company_confirm_create_bypasses_suggestion(client, root):
    vault.save_company(root, {'name': 'Acme AG'})
    before = len(vault.list_companies(root))
    exp = vault.save_experience(root, {'company': 'Acme', 'title': 'Builder', 'start': '2020-01', 'end': 'present'})
    response = client.post('/api/experiences/' + exp['id'] + '/link-company',
                           json={'create': {'name': 'Acme'}, 'confirm_create': True})
    assert response.status_code == 201
    assert len(vault.list_companies(root)) == before + 1


def test_link_company_unlink_freezes_label(client, root):
    company = vault.save_company(root, {'name': 'Fiction Co'})
    exp = vault.save_experience(root, {'company': 'Stale text', 'title': 'Builder', 'start': '2020-01',
                                       'end': 'present', 'company_id': company['id']})
    response = client.post('/api/experiences/' + exp['id'] + '/link-company', json={'unlink': True})
    assert response.status_code == 200
    assert response.json['company_id'] is None
    assert response.json['company'] == 'Fiction Co'


# --- Engineering item 6: company detail page Experience section -----------

def test_company_detail_page_lists_linked_experience(client, root):
    company = vault.save_company(root, {'name': 'Fiction Co'})
    vault.save_experience(root, {'company': 'Fiction Co', 'title': 'Distinct Builder Role', 'start': '2020-01',
                                 'end': 'present', 'company_id': company['id']})
    page = client.get('/api/companies/' + company['id'] + '?view=page').json
    assert [exp['title'] for exp in page['experiences']] == ['Distinct Builder Role']


def test_company_detail_page_shows_empty_experience_state(client, root):
    company = vault.save_company(root, {'name': 'Fiction Co'})
    page = client.get('/api/companies/' + company['id'] + '?view=page').json
    assert page['experiences'] == []


# --- Engineering item 8: live label resolution -----------------------------

def test_experience_card_label_updates_on_company_rename_without_experience_write(client, root):
    company = vault.save_company(root, {'name': 'Original Name'})
    exp = vault.save_experience(root, {'company': 'Original Name', 'title': 'Builder', 'start': '2020-01',
                                       'end': 'present', 'company_id': company['id']})
    before = vault.load_experience(root, exp['id'])
    vault.save_company(root, {'name': 'Renamed Co'}, company['id'])
    after = vault.load_experience(root, exp['id'])
    assert before == after  # the stored experience record itself never changes
    library = client.get('/api/experiences?view=page').json
    assert library['labels'][exp['id']] == 'Renamed Co'
    page = client.get('/api/experiences/' + exp['id'] + '?view=page').json
    assert page['label'] == 'Renamed Co'


def test_unlinked_experience_falls_back_to_cached_company_text(client, root):
    exp = vault.save_experience(root, {'company': 'Cached Text Co', 'title': 'Builder', 'start': '2020-01', 'end': 'present'})
    library = client.get('/api/experiences?view=page').json
    assert library['labels'][exp['id']] == 'Cached Text Co'


# --- Engineering item 7: experience form company combobox + create-inline -

def test_experience_form_renders_company_combobox_and_create_inline(client, root):
    vault.save_company(root, {'name': 'Fiction Co'})
    html = client.get('/experiences/new').text
    assert 'id="company-input"' in html and 'list="company-options"' in html
    assert 'id="company-id-field"' in html
    assert 'id="create-company-btn"' in html
    assert '<option value="Fiction Co">' in html
    # The old direct-select bypass of the link-company endpoint is gone.
    assert 'Link to company record' not in html
