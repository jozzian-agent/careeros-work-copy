"""JOZ-266: company resolution ladder, identifiers/sources, and migration.

Fixtures are synthetic throughout (acme.example, globex.example, ...);
no intake test here reaches the network (tests/conftest.py's offline
fixture blocks it process-wide).
"""
from pathlib import Path
from unittest.mock import Mock
import shutil
import threading

import pytest

from careeros import ingest, intake, server, vault
from org_intake import enrich as company_lookup, identity
from careeros.org_store import VaultOrganisationStore
from careeros.server import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path):
    shutil.copytree(ROOT / 'sample/vault', tmp_path / 'vault')
    return create_app(tmp_path / 'vault').test_client()


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / 'sample/vault', tmp_path / 'vault')
    return tmp_path / 'vault'


def schema_html(name, body='<p>Great opportunity for an experienced builder.</p>'):
    return ('<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
            f'"hiringOrganization":{{"name":"{name}"}}}}</script>') + body


# --- Rung 1: ats_tenant ------------------------------------------------------

def test_rung1_ats_tenant_refline(client, monkeypatch):
    """Refline is in rung 1 like every other provider (owner decision,
    2026-10-08): the second posting under the same numeric tenant links
    instantly, at stub time, purely from the identifier -- before its own
    (empty-signal) fetch even runs."""
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Refline Robotics'))
    first = client.post('/api/jobs/intake', json={
        'url': 'https://m.refline.ch/792841/11410/pub/1/index.html'}).json
    assert first['job']['company_link_state'] == 'linked'
    assert first['job']['company_link_reason'] == 'new_company'
    company_id = first['job']['company_id']
    assert company_id is not None
    company = client.get('/api/companies/' + company_id).json
    assert {'type': 'ats_tenant', 'value': 'refline:792841', 'provenance': 'scrape'} in company['identifiers']
    assert any(s['kind'] == 'ats_feed' and s['ats_provider'] == 'refline' for s in company['sources'])

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Second posting</title>')
    second = client.post('/api/jobs/intake', json={
        'url': 'https://m.refline.ch/792841/22222/pub/1/index.html'}).json
    # Rung 1 resolves at stub time -- immediately, from the identifier
    # alone, with no employer-name signal needed at all.
    assert second['job']['company_id'] == company_id
    assert second['job']['company_link_state'] == 'linked'
    assert second['job']['company_link_reason'] == 'ats_tenant'


# --- Rung 2: domain -----------------------------------------------------

def test_rung2_domain(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Dune Logistics'))
    first = client.post('/api/jobs/intake', json={'url': 'https://dune-logistics.example/careers/role-a'}).json
    company_id = first['job']['company_id']
    assert company_id is not None
    company = client.get('/api/companies/' + company_id).json
    assert {'type': 'domain', 'value': 'dune-logistics.example', 'provenance': 'scrape'} in company['identifiers']

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Second posting</title>')
    second = client.post('/api/jobs/intake', json={'url': 'https://dune-logistics.example/careers/role-b'}).json
    assert second['job']['company_id'] == company_id
    assert second['job']['company_link_state'] == 'linked'
    assert second['job']['company_link_reason'] == 'domain'


# --- Rung 3: name_exact and fuzzy_name ------------------------------------

def test_rung3_exact_name_match_case_and_punctuation_insensitive(client, monkeypatch):
    company = vault.save_company(client.application.config['VAULT_PATH'], {'name': 'Globex Corp'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('GLOBEX, CORP.'))
    data = client.post('/api/jobs/intake', json={'url': 'https://unrelated.example/role'}).json
    assert data['job']['company_id'] == company['id']
    assert data['job']['company_link_state'] == 'linked'
    assert data['job']['company_link_reason'] == 'name_exact'


def test_rung3_fuzzy_name_refuses_auto_link_and_stores_candidates(client, monkeypatch):
    company = vault.save_company(client.application.config['VAULT_PATH'], {'name': 'Acme GmbH'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme'))
    data = client.post('/api/jobs/intake', json={'url': 'https://unrelated.example/acme-role'}).json
    job = data['job']
    assert job['company_id'] is None
    assert job['company_link_state'] == 'needs_review'
    assert job['company_link_reason'] == 'fuzzy_name'
    assert job['employer_named_in_posting'] == 'Acme'
    candidates = job['company_review']['candidates']
    assert candidates and candidates[0]['company_id'] == company['id']
    assert 0 < candidates[0]['score'] < 1.0


# --- Rung 4: new_company ------------------------------------------------

def test_rung4_nothing_matches_creates_company_and_links(client, monkeypatch):
    before = len(client.get('/api/companies').json)
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Zyphyrion Holdings'))
    data = client.post('/api/jobs/intake', json={'url': 'https://zyphyrion-holdings.example/careers/role'}).json
    job, company = data['job'], data['company']
    assert company is not None and company['name'] == 'Zyphyrion Holdings'
    assert job['company_id'] == company['id']
    assert job['company_link_state'] == 'linked'
    assert job['company_link_reason'] == 'new_company'
    assert len(client.get('/api/companies').json) == before + 1
    assert {'type': 'domain', 'value': 'zyphyrion-holdings.example', 'provenance': 'scrape'} in company['identifiers']


# --- Rung 5: flags, never guessed ----------------------------------------

def test_rung5_employer_differs_from_tenant(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme Robotics'))
    first = client.post('/api/jobs/intake', json={
        'url': 'https://boards.greenhouse.io/acmerobotics/jobs/111'}).json
    tenant_company_id = first['job']['company_id']
    assert first['job']['company_link_state'] == 'linked'

    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Totally Unrelated Corp'))
    second = client.post('/api/jobs/intake', json={
        'url': 'https://boards.greenhouse.io/acmerobotics/jobs/222'}).json
    job = second['job']
    # Still (tentatively) linked to the tenant's owner, but flagged -- never
    # silently relinked and never silently left alone (global rule 2).
    assert job['company_id'] == tenant_company_id
    assert job['company_link_state'] == 'needs_review'
    assert job['company_link_reason'] == 'employer_differs_from_tenant'
    assert job['employer_named_in_posting'] == 'Totally Unrelated Corp'


def test_rung5_shared_tenant(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme Robotics'))
    first = client.post('/api/jobs/intake', json={
        'url': 'https://boards.greenhouse.io/sharedtenant/jobs/111'}).json
    tenant_company_id = first['job']['company_id']

    other = vault.save_company(client.application.config['VAULT_PATH'], {'name': 'Globex Staffing'})

    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Globex Staffing'))
    second = client.post('/api/jobs/intake', json={
        'url': 'https://boards.greenhouse.io/sharedtenant/jobs/222'}).json
    job = second['job']
    assert job['company_id'] == tenant_company_id
    assert job['company_link_state'] == 'needs_review'
    assert job['company_link_reason'] == 'shared_tenant'
    candidates = job['company_review']['candidates']
    assert candidates and candidates[0]['company_id'] == other['id']


# --- Teaching: owner decision 3.A ----------------------------------------

def test_name_variant_teaching_persists_and_short_circuits_repeat(client, monkeypatch):
    company = vault.save_company(client.application.config['VAULT_PATH'], {'name': 'Acme GmbH'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme'))
    first = client.post('/api/jobs/intake', json={'url': 'https://unrelated.example/first-acme-role'}).json
    assert first['job']['company_link_state'] == 'needs_review'

    review = client.post('/api/jobs/' + first['job']['id'] + '/resolve-review',
                         json={'company_id': company['id'], 'review_token': first['job']['company_review']['token']})
    assert review.status_code == 200
    resolved = review.json
    assert resolved['company_id'] == company['id']
    assert resolved['company_link_state'] == 'linked'
    assert resolved['company_link_reason'] == 'manual'
    assert resolved['company_review'] is None
    assert resolved['field_provenance']['company_id'] == 'user'

    updated_company = client.get('/api/companies/' + company['id']).json
    assert {'type': 'name_variant', 'value': 'Acme', 'provenance': 'user'} in updated_company['identifiers']

    # Second ingest of the same fuzzy employer text auto-links via the
    # taught identifier -- no review raised this time.
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme'))
    second = client.post('/api/jobs/intake', json={'url': 'https://unrelated.example/second-acme-role'}).json
    assert second['job']['company_id'] == company['id']
    assert second['job']['company_link_state'] == 'linked'
    assert second['job']['company_link_reason'] == 'name_exact'
    assert second['job']['company_review'] is None


def test_resolve_review_create_new_company(client, monkeypatch):
    # Keep this review-choice test independent of asynchronous extraction callbacks.
    monkeypatch.setattr(ingest, 'extract_async', lambda *a, **k: Mock(is_alive=lambda: False))
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Nimbus Freight'))
    first = client.post('/api/jobs/intake', json={'url': 'https://unrelated.example/nimbus-role'}).json
    vault.save_company(client.application.config['VAULT_PATH'], {'name': 'Nimbus Freightlines'})
    # Create a real fuzzy review before submitting the owner's choice.
    root = client.application.config['VAULT_PATH']
    job = first['job']
    resolution = server.resolve_company(root, url='', employer_name='Nimbus Freightlines Group')
    job = vault.save_job(root, resolution, job['id'])
    review = client.post('/api/jobs/' + first['job']['id'] + '/resolve-review',
                         json={'create': {'name': 'Nimbus Freight Group'}, 'review_token': job['company_review']['token']})
    assert review.status_code == 200
    assert review.json['company_link_state'] == 'linked'
    assert review.json['company_link_reason'] == 'manual'
    created = client.get('/api/companies/' + review.json['company_id']).json
    assert created['name'] == 'Nimbus Freight Group'


# --- PUT bypass (bug class 9) and owner-edit-wins -------------------------

def test_put_setting_company_id_sets_linked_state_and_clears_review(client):
    root = client.application.config['VAULT_PATH']
    other = vault.save_company(root, {'name': 'Ad-hoc Linked Co'})
    job = vault.list_jobs(root)[0]
    response = client.put('/api/jobs/' + job['id'], json={'company_id': other['id']})
    assert response.status_code == 200
    data = response.json
    assert data['company_id'] == other['id']
    assert data['company_link_state'] == 'linked'
    assert data['company_link_reason'] == 'manual'
    assert data['company_review'] is None
    assert data['field_provenance']['company_id'] == 'user'


def test_put_clearing_company_id_reverts_to_pending(client):
    root = client.application.config['VAULT_PATH']
    job = next(j for j in vault.list_jobs(root) if j.get('company_id'))
    response = client.put('/api/jobs/' + job['id'], json={'company_id': None})
    assert response.status_code == 200
    data = response.json
    assert data['company_id'] is None
    assert data['company_link_state'] == 'pending'
    assert data['company_link_reason'] is None


def test_rerun_resolution_never_overwrites_owner_set_company_id(client, monkeypatch):
    root = client.application.config['VAULT_PATH']
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme'))
    company = vault.save_company(root, {'name': 'Acme GmbH'})
    data = client.post('/api/jobs/intake', json={'url': 'https://unrelated.example/owner-wins-role'}).json
    job_id = data['job']['id']
    assert data['job']['company_link_state'] == 'needs_review'

    other = vault.save_company(root, {'name': 'Owner Chosen Co'})
    client.put('/api/jobs/' + job_id, json={'company_id': other['id']})

    rerun = client.post('/api/jobs/' + job_id + '/resolve')
    assert rerun.status_code == 200
    assert rerun.json['company_id'] == other['id']
    assert rerun.json['company_link_state'] == 'linked'
    assert rerun.json['company_link_reason'] == 'manual'


def test_rerun_resolution_resolves_a_pending_job_without_refetch(client):
    """A job created directly at stub-shape (company_link_state: pending,
    no employer_named_in_posting yet -- e.g. Phase B has not run) resolves
    once a matching identifier exists, without any fetch at all: /resolve
    only ever reads the job's already-stored url/employer_named_in_posting
    (global rule 5)."""
    root = client.application.config['VAULT_PATH']
    job = vault.save_job(root, {
        'title': 'Pending role', 'url': 'https://still-pending.example/role',
        'company_link_state': 'pending', 'employer_named_in_posting': None, 'company': ''})
    company = vault.save_company(root, {'name': 'Still Pending Co'})
    identity.add_identifier(VaultOrganisationStore(root), company, 'domain', 'still-pending.example', 'scrape')

    rerun = client.post('/api/jobs/' + job['id'] + '/resolve')
    assert rerun.json['company_id'] == company['id']
    assert rerun.json['company_link_state'] == 'linked'
    assert rerun.json['company_link_reason'] == 'domain'


# --- Migration -------------------------------------------------------------

def test_migrate_company_fields_derives_domain_identifier_from_website(root):
    for company in vault.list_companies(root):
        assert 'identifiers' not in _raw(root, company['id'])
    migrated = vault.migrate_company_fields(root)
    assert set(migrated) == {c['id'] for c in vault.list_companies(root)}
    for company in vault.list_companies(root):
        assert isinstance(company['identifiers'], list)
        assert company['sources'] == []
        if company.get('website'):
            assert any(i['type'] == 'domain' and i['provenance'] == 'derived' for i in company['identifiers'])


def test_migrate_company_fields_second_run_is_a_no_op(root):
    first = vault.migrate_company_fields(root)
    assert first
    second = vault.migrate_company_fields(root)
    assert second == []


def test_migrate_job_fields_derives_company_link_state_for_legacy_shapes(root):
    vault.migrate_job_fields(root)
    for job in vault.list_jobs(root):
        assert job['company_link_state'] == ('linked' if job.get('company_id') else 'pending')
        assert job['company_link_reason'] is None
        assert job['employer_named_in_posting'] is None
        assert job['company_review'] is None


def test_migrate_job_fields_second_run_is_a_no_op_for_joz266_fields(root):
    vault.migrate_job_fields(root)
    second = vault.migrate_job_fields(root)
    assert second == []


def _raw(root, identifier):
    import yaml
    for path in (Path(root) / 'companies').glob('*.yaml'):
        data = yaml.safe_load(path.read_text())
        if data and data.get('id') == identifier:
            return data
    return {}


# --- M2: LLM extraction feeds ladder rung 3 --------------------------------

def test_llm_extraction_feeds_ladder_and_demotes_fuzzy_guess(client, monkeypatch):
    company = vault.save_company(client.application.config['VAULT_PATH'], {'name': 'Acme GmbH'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Role</title><p>No employer named here.</p>')
    callbacks = []
    def start(description, callback, **kwargs):
        callbacks.append(callback)
        return Mock(is_alive=lambda: False)
    monkeypatch.setattr(ingest, 'extract_async', start)
    data = client.post('/api/jobs/intake', json={'url': 'https://unrelated.example/m2-role'}).json
    job = data['job']
    assert job['employer_named_in_posting'] is None
    assert job['company_link_reason'] == 'new_company'

    callbacks[0]({'company': 'Acme'})
    final = client.get('/api/jobs/' + job['id']).json
    assert final['employer_named_in_posting'] == 'Acme'
    assert final['company_link_state'] == 'needs_review'
    assert final['company_link_reason'] == 'fuzzy_name'
    candidates = final['company_review']['candidates']
    assert candidates and candidates[0]['company_id'] == company['id']


# --- M3: /enrich uses the shared ladder -------------------------------------

def test_enrich_uses_shared_ladder_no_duplicate_company(client, monkeypatch):
    root = client.application.config['VAULT_PATH']
    company = vault.save_company(root, {'name': 'Acme GmbH'})
    job = vault.save_job(root, {'title': 'Unresolved role', 'url': 'https://unresolved.example/role'})
    before = len(client.get('/api/companies').json)
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Role</title><p>Remote.</p>')
    extracted = dict(
        title='Role', location='', source='', posted_date=None, employment_type='', valid_through='',
        description='Remote.', company='Acme', website=None, seniority='', summary='', summary_source='',
        keywords=[], ingest_source='llm', remote_ok=None, sector=None, background='', skills=[],
        certifications=[], responsibilities=[], employee_count=None, function=[], salary_info=False,
        salary_note='', contact_email='', employer_named_in_posting='Acme')
    monkeypatch.setattr(intake, 'ingest_posting', lambda url, html, function_options=None: dict(extracted))
    result = client.post('/api/jobs/' + job['id'] + '/enrich')
    assert result.status_code == 200
    data = result.json
    assert data['company_link_state'] == 'needs_review'
    assert data['company_link_reason'] == 'fuzzy_name'
    candidates = data['company_review']['candidates']
    assert candidates and candidates[0]['company_id'] == company['id']
    assert len(client.get('/api/companies').json) == before


# --- M4: legacy website matching can no longer manufacture a tenant -------

def test_cross_tenant_refline_website_not_promoted_to_ats_link(client, monkeypatch):
    root = client.application.config['VAULT_PATH']
    acme = vault.save_company(root, {'name': 'Acme GmbH', 'website': 'https://m.refline.ch/111111'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme'))
    data = client.post('/api/jobs/intake', json={
        'url': 'https://m.refline.ch/999999/22222/pub/1/index.html'}).json
    job = data['job']
    assert job['company_link_state'] == 'needs_review'
    assert job['company_link_reason'] == 'fuzzy_name'
    candidates = job['company_review']['candidates']
    assert candidates and candidates[0]['company_id'] == acme['id']
    updated_acme = client.get('/api/companies/' + acme['id']).json
    assert {'type': 'ats_tenant', 'value': 'refline:999999', 'provenance': 'scrape'} not in updated_acme['identifiers']


# --- M5: stale review submissions / ambiguous exact match -----------------

def test_resolve_review_rejects_stale_concurrent_submission(client, monkeypatch):
    root = client.application.config['VAULT_PATH']
    company = vault.save_company(root, {'name': 'Acme GmbH'})
    other = vault.save_company(root, {'name': 'Acme Robotics'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme'))
    data = client.post('/api/jobs/intake', json={'url': 'https://unrelated.example/m5-role'}).json
    job_id = data['job']['id']
    token = data['job']['company_review']['token']

    release = threading.Event()
    entered = threading.Event()
    original = identity.apply_review
    def slow_apply(*args, **kwargs):
        entered.set()
        release.wait(timeout=5)
        return original(*args, **kwargs)
    monkeypatch.setattr(identity, 'apply_review', slow_apply)

    results = {}
    def first_request():
        results['first'] = client.post('/api/jobs/' + job_id + '/resolve-review',
                                       json={'company_id': company['id'], 'review_token': token})
    worker = threading.Thread(target=first_request)
    worker.start()
    entered.wait(timeout=5)
    second = client.post('/api/jobs/' + job_id + '/resolve-review',
                         json={'company_id': other['id'], 'review_token': token})
    release.set()
    worker.join(timeout=5)

    statuses = sorted([results['first'].status_code, second.status_code])
    assert statuses == [200, 409]
    final = vault.load_job(root, job_id)
    assert final['company_id'] in (company['id'], other['id'])
    variant_owners = [c['id'] for c in vault.list_companies(root)
                      if any(i.get('type') == 'name_variant' and i.get('value') == 'Acme'
                             for i in c.get('identifiers', []))]
    assert len(variant_owners) == 1
    # Deterministic subsequent resolution: exactly one owner taught "Acme".
    rerun = server.resolve_company(root, url='https://unrelated.example/m5-rerun-role', employer_name='Acme')
    assert rerun['company_id'] == final['company_id']
    assert rerun['company_link_reason'] == 'name_exact'


@pytest.mark.parametrize('employer_evidenced', [True, False])
def test_ambiguous_exact_name_match_needs_review(client, monkeypatch, employer_evidenced):
    root = client.application.config['VAULT_PATH']
    first = vault.save_company(root, {'name': 'Acme Holdings'})
    second = vault.save_company(root, {'name': 'Acme Holdings'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme Holdings'))
    if not employer_evidenced:
        original = intake.ingest_posting
        def fallback_only(*args, **kwargs):
            result = original(*args, **kwargs)
            result['employer_named_in_posting'] = None
            return result
        monkeypatch.setattr(intake, 'ingest_posting', fallback_only)
    data = client.post('/api/jobs/intake', json={'url': 'https://unrelated.example/m5-ambiguous-role'}).json
    job = data['job']
    assert job['company_id'] is None
    assert job['company_link_state'] == 'needs_review'
    assert job['company_link_reason'] == 'ambiguous_exact'
    candidate_ids = {c['company_id'] for c in job['company_review']['candidates']}
    assert candidate_ids == {first['id'], second['id']}


# --- M6: shared_tenant consults observed tenant history --------------------

def test_shared_tenant_consults_tenant_history_for_null_employer(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme Robotics'))
    first = client.post('/api/jobs/intake', json={
        'url': 'https://boards.greenhouse.io/m6shared/jobs/111'}).json
    tenant_company_id = first['job']['company_id']

    vault.save_company(client.application.config['VAULT_PATH'], {'name': 'Globex Staffing'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Globex Staffing'))
    second = client.post('/api/jobs/intake', json={
        'url': 'https://boards.greenhouse.io/m6shared/jobs/222'}).json
    assert second['job']['company_link_state'] == 'needs_review'
    assert second['job']['company_link_reason'] == 'shared_tenant'

    # KNOWN_SHARED_NULL: a third posting on the same tenant with NO
    # employer evidence at all must not silently auto-link to the tenant
    # owner either -- the tenant is now known (from a real stored posting,
    # not mere registry membership) to be shared.
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>No employer named</title>')
    third = client.post('/api/jobs/intake', json={
        'url': 'https://boards.greenhouse.io/m6shared/jobs/333'}).json
    job = third['job']
    assert job['employer_named_in_posting'] is None
    assert job['company_id'] == tenant_company_id
    assert job['company_link_state'] == 'needs_review'
    assert job['company_link_reason'] == 'shared_tenant'


# --- M7: new-company creation triggers the enrichment cascade --------------

def test_new_company_schedules_enrichment_cascade(client, monkeypatch):
    monkeypatch.setattr(server, 'AUTO_CASCADE_ENABLED', True)
    calls = {'sectors': 0, 'size': 0}
    def fake_sectors_cascade(company, *args, **kwargs):
        calls['sectors'] += 1
        return None, None
    def fake_size_cascade(company, *args, **kwargs):
        calls['size'] += 1
        return None, None
    monkeypatch.setattr(company_lookup, 'classify_sector', fake_sectors_cascade)
    monkeypatch.setattr(company_lookup, 'classify_size', fake_size_cascade)
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Nimbus Robotics'))
    data = client.post('/api/jobs/intake', json={'url': 'https://nimbus-robotics.example/role'}).json
    company_id = data['company']['id']
    thread = client.application.config['CASCADE_THREADS'].get(company_id)
    if thread is not None:  # A completed worker may already be pruned at teardown.
        thread.join(timeout=5)
    assert calls['sectors'] >= 1
    assert calls['size'] >= 1


# --- M8: review create-new preserves discovered identifiers/sources -------

def test_resolve_review_create_new_preserves_discovered_identifiers_and_sources(client, monkeypatch):
    # Keep this review-choice test independent of asynchronous extraction callbacks.
    monkeypatch.setattr(ingest, 'extract_async', lambda *a, **k: Mock(is_alive=lambda: False))
    vault.save_company(client.application.config['VAULT_PATH'], {'name': 'Acme GmbH'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme'))
    first = client.post('/api/jobs/intake', json={'url': 'https://unknown.example/m8-role'}).json
    job_id = first['job']['id']
    review_token = (first['job']['company_review'] or {}).get('token')
    review = client.post('/api/jobs/' + job_id + '/resolve-review',
                         json={'create': {'name': 'Acme Holdings'}, 'review_token': review_token})
    assert review.status_code == 200
    created = client.get('/api/companies/' + review.json['company_id']).json
    assert {'type': 'domain', 'value': 'unknown.example', 'provenance': 'scrape'} in created['identifiers']
    assert any(s['kind'] == 'careers_page' and s['url'] == 'https://unknown.example/m8-role'
               for s in created['sources'])


# --- m11: ATS sources store the canonical tenant feed, deduped -------------

def test_ats_feed_source_dedupes_to_canonical_tenant_url(client, monkeypatch):
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme Robotics'))
    first = client.post('/api/jobs/intake', json={
        'url': 'https://boards.greenhouse.io/m11acme/jobs/111'}).json
    company_id = first['job']['company_id']
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<title>Second posting</title>')
    client.post('/api/jobs/intake', json={'url': 'https://boards.greenhouse.io/m11acme/jobs/222'})
    company = client.get('/api/companies/' + company_id).json
    feed_sources = [s for s in company['sources'] if s['kind'] == 'ats_feed']
    assert len(feed_sources) == 1
    assert feed_sources[0]['url'] == 'https://boards.greenhouse.io/m11acme'

# JOZ-266 round 2: independent, offline regression probes.
@pytest.mark.parametrize('edit', ['owner', 'owner_empty', 'automation'])
def test_r1_owner_edit_mid_cascade_survives(client, monkeypatch, edit):
    root = client.application.config['VAULT_PATH']
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(server, 'AUTO_CASCADE_ENABLED', True)
    def sectors(company, collector, **kwargs):
        entered.set()
        assert release.wait(5)
        return ['J'], None
    monkeypatch.setattr(company_lookup, 'classify_sector', sectors)
    monkeypatch.setattr(company_lookup, 'classify_size', lambda *a, **k:
                        ({'size_range': '10-49', 'size_class': 'small'}, None))
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Cascade Probe'))
    result = client.post('/api/jobs/intake', json={'url': 'https://cascade.example/job'}).json
    cid = result['job']['company_id']
    thread = client.application.config['CASCADE_THREADS'][cid]
    try:
        assert entered.wait(2)
        expected = (None, None) if edit == 'owner_empty' else ('250+', 'large')
        values = dict(zip(('size_range', 'size_class'), expected))
        if edit == 'automation':
            vault.save_company(root, values, cid)
        else:
            assert client.put('/api/companies/' + cid, json=values).status_code == 200
    finally:
        release.set()
        thread.join(5)
    company = vault.load_company(root, cid)
    assert (company['size_range'], company['size_class']) == expected
    assert company['sectors'] == ['J']


def test_r2_legacy_review_migrate_save_render(client):
    root = client.application.config['VAULT_PATH']
    job = vault.save_job(root, {'title': 'Legacy review', 'url': 'https://probe.example/job', 'company_link_state': 'needs_review'})
    path = next(p for p, record in vault._records(root, 'jobs') if record['id'] == job['id'])
    job['company_review'] = {'candidates': [], 'at': vault.timestamp()}
    vault._write(path, job)
    # Even before migration, an old review serves safely with no token.
    response = client.get('/api/jobs/' + job['id'] + '?view=page')
    assert response.status_code == 200
    assert response.json['job']['company_review'].get('token') is None
    vault.migrate_job_fields(root)
    token = vault.load_job(root, job['id'])['company_review']['token']
    assert token
    vault.migrate_job_fields(root)
    assert vault.load_job(root, job['id'])['company_review']['token'] == token
    assert client.put('/api/jobs/' + job['id'], json={'notes': 'saved'}).status_code == 200
    assert client.get('/api/jobs/' + job['id'] + '?view=page').status_code == 200


def test_r3_tokenless_and_double_pick(client):
    root = client.application.config['VAULT_PATH']
    first = vault.save_company(root, {'name': 'Acme GmbH'})
    second = vault.save_company(root, {'name': 'Acme Inc'})
    resolution = server.resolve_company(root, url='', employer_name='Acme')
    job = vault.save_job(root, {'title': 'Review', 'url': 'https://probe.example/job', 'employer_named_in_posting': 'Acme', **resolution})
    url = '/api/jobs/' + job['id'] + '/resolve-review'
    assert client.post(url, json={'company_id': first['id']}).status_code == 409
    token = job['company_review']['token']
    assert [client.post(url, json={'company_id': c['id'], 'review_token': token}).status_code
            for c in (first, second)] == [200, 409]
    assert not any(i['value'] == 'Acme' for i in vault.load_company(root, second['id'])['identifiers'])


def test_r4_domain_fuzzy_includes_current_and_exact_reason(root):
    company = vault.save_company(root, {'name': 'Acme GmbH', 'identifiers': [
        {'type': 'domain', 'value': 'acme.example', 'provenance': 'scrape'}]})
    result = server.resolve_company(root, url='https://acme.example/job', employer_name='Acme')
    assert result['company_link_state'] == 'needs_review'
    current = next(c for c in result['company_review']['candidates'] if c['company_id'] == company['id'])
    assert current['current'] is True
    assert .6 <= current['score'] < 1
    vault.save_company(root, {'name': 'Acme'})
    result = server.resolve_company(root, url='https://acme.example/job', employer_name='Acme')
    assert result['company_link_reason'] == 'ambiguous_exact'


def test_r5_llm_only_enrich_fuzzy_no_duplicate(client, monkeypatch):
    root = client.application.config['VAULT_PATH']
    company = vault.save_company(root, {'name': 'Acme GmbH'})
    job = vault.save_job(root, {'title': 'Engineer', 'url': 'https://unknown.example/job'})
    before = len(vault.list_companies(root))
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Build services for our customers.</main>')
    monkeypatch.setattr(ingest, 'extract', lambda *a, **k: {'company': 'Acme', 'ingest_source': 'llm'})
    response = client.post('/api/jobs/' + job['id'] + '/enrich')
    assert response.status_code == 200
    assert response.json['company_link_state'] == 'needs_review'
    assert response.json['employer_named_in_posting'] == 'Acme'
    assert response.json['field_provenance']['employer_named_in_posting'] == 'llm'
    assert any(c['company_id'] == company['id'] for c in response.json['company_review']['candidates'])
    assert len(vault.list_companies(root)) == before


def test_r6_staffing_create_keeps_single_tenant_owner(client):
    root = client.application.config['VAULT_PATH']
    owner = vault.save_company(root, {'name': 'Acme', 'identifiers': [
        {'type': 'ats_tenant', 'value': 'greenhouse:acme', 'provenance': 'scrape'}]})
    url = 'https://boards.greenhouse.io/acme/jobs/999'
    result = server.resolve_company(root, url=url, employer_name='Globex')
    assert result['company_link_reason'] == 'employer_differs_from_tenant'
    assert result['company_review']['candidates'] == []
    job = vault.save_job(root, {'title': 'Staffing', 'url': url, 'employer_named_in_posting': 'Globex', **result})
    response = client.post('/api/jobs/' + job['id'] + '/resolve-review', json={
        'create': {'name': 'Globex'}, 'review_token': job['company_review']['token']})
    assert response.status_code == 200
    created = vault.load_company(root, response.json['company_id'])
    assert any(s['kind'] == 'ats_feed' for s in created['sources'])
    owners = [c['id'] for c in vault.list_companies(root) if any(
        i['type'] == 'ats_tenant' and i['value'] == 'greenhouse:acme' for i in c['identifiers'])]
    assert owners == [owner['id']]
    identity.add_identifier(VaultOrganisationStore(root), created, 'ats_tenant', 'greenhouse:acme', 'scrape')
    assert not any(i['type'] == 'ats_tenant' for i in vault.load_company(root, created['id'])['identifiers'])


def test_r7_unresolved_globex_email_held_until_review(client):
    root = client.application.config['VAULT_PATH']
    acme = vault.save_company(root, {'name': 'Acme'})
    globex = vault.save_company(root, {'name': 'Globex'})
    result = server.resolve_company(root, url='', employer_name='Globex', existing=(acme['id'], 'domain'))
    job = vault.save_job(root, {'title': 'Correction', 'url': 'https://probe.example/job', 'contact_email': 'jobs@globex.example', **result})
    assert vault.load_company(root, acme['id'])['contact_email'] == ''
    assert job['contact_email'] == 'jobs@globex.example'
    response = client.post('/api/jobs/' + job['id'] + '/resolve-review', json={
        'company_id': globex['id'], 'review_token': job['company_review']['token']})
    assert response.status_code == 200
    assert vault.load_company(root, globex['id'])['contact_email'] == 'jobs@globex.example'
    assert vault.load_company(root, acme['id'])['contact_email'] == ''


def test_r8_fuzzy_history_not_shared_tenant(root):
    company = vault.save_company(root, {'name': 'Acme GmbH', 'identifiers': [
        {'type': 'ats_tenant', 'value': 'greenhouse:acme', 'provenance': 'scrape'}]})
    vault.save_job(root, {'title': 'Observed', 'url': 'https://boards.greenhouse.io/acme/jobs/100',
                         'ats_provider': 'greenhouse', 'ats_tenant': 'acme',
                         'company_id': company['id'], 'employer_named_in_posting': 'Acme'})
    result = server.resolve_company(root, url='https://boards.greenhouse.io/acme/jobs/101')
    assert result['company_link_state'] == 'linked'
    assert result['company_link_reason'] == 'ats_tenant'


def test_r9_empty_cascade_persists_exhausted_and_r10_prunes(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    root = client.application.config['VAULT_PATH']
    monkeypatch.setattr(server, 'AUTO_CASCADE_ENABLED', True)
    def empty(company, collector, **kwargs):
        entered.set()
        assert release.wait(5)
        collector.record(company['id'], empty, 'sectors', 'empty')
        return None, None
    monkeypatch.setattr(company_lookup, 'classify_sector', empty)
    monkeypatch.setattr(company_lookup, 'classify_size', lambda *a, **k: (None, None))
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Empty Cascade'))
    result = client.post('/api/jobs/intake', json={'url': 'https://empty.example/job'}).json
    cid = result['job']['company_id']
    thread = client.application.config['CASCADE_THREADS'][cid]
    assert thread.daemon
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    block = vault.load_company(root, cid)['enrichment']
    assert block['attempted_at']
    assert block['summary']['empty'] == 1
    for field in ('sectors', 'size'):
        assert block['field_states'][field]['state'] == 'exhausted'
        assert block['field_states'][field]['attempted_at']
    with client.application.app_context():
        pass
    assert cid not in client.application.config['CASCADE_THREADS']

@pytest.mark.parametrize('manual', [False, True])
def test_r5_extract_retry_and_manual_text_persist_llm_employer(client, monkeypatch, manual):
    root = client.application.config['VAULT_PATH']
    company = vault.save_company(root, {'name': 'Acme GmbH'})
    job = vault.save_job(root, {'title': 'Retry', 'ingest_state': 'extract_failed',
                               'ingest_error': {'stage': 'extract', 'reason': 'unavailable', 'at': vault.timestamp()},
                               'url': 'https://unknown.example/retry'})
    if manual:
        assert client.put('/api/jobs/' + job['id'], json={
            'description': 'Build services for Acme.'}).status_code == 200
    def fetch(url):
        if manual:
            raise ValueError('Unavailable; use pasted text')
        return '<main>Build services for Acme.</main>'
    monkeypatch.setattr(intake, 'fetch_url', fetch)
    captured = {}
    def extract_async(description, callback, **kwargs):
        captured['callback'] = callback
        captured['description'] = description
        return True
    monkeypatch.setattr(ingest, 'extract_async', extract_async)
    before = len(vault.list_companies(root))
    assert client.post('/api/jobs/' + job['id'] + '/extract').status_code == 202
    client.application.config['REFRESH_THREADS'][job['id']].join(5)
    assert 'Build services' in captured['description']
    captured['callback']({'company': 'Acme'})
    result = vault.load_job(root, job['id'])
    assert result['employer_named_in_posting'] == 'Acme'
    assert result['field_provenance']['employer_named_in_posting'] == 'llm'
    assert result['company_link_state'] == 'needs_review'
    assert any(c['company_id'] == company['id'] for c in result['company_review']['candidates'])
    assert len(vault.list_companies(root)) == before
