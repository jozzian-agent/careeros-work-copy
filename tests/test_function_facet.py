"""Section 4 (Job Function Taxonomy). Synthetic fixtures and a mocked LLM
client only; no network access and no real model/provider is named."""
from pathlib import Path
from unittest.mock import Mock
import json
import logging
import shutil

import pytest
import yaml

from careeros import ingest, vault
from org_intake import classify as sectors
from careeros.server import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / 'sample/vault', tmp_path / 'vault')
    return tmp_path / 'vault'


@pytest.fixture
def client(root):
    return create_app(root).test_client()


def seed_function_facet(root):
    tags = vault.load_tags(root)
    tags['facets']['function']['values'] = [
        {'id': 'ict-product-manager', 'label': 'ICT product manager', 'label_de': 'ICT-Produktmanager',
         'isco': '1330', 'esco_uri': 'http://data.europa.eu/esco/occupation/example'},
        {'id': 'financial-product-manager', 'label': 'Financial product manager',
         'isco': None, 'esco_uri': None, 'source': 'local-extension'},
    ]
    return vault.save_tags(root, tags)


# --- esco_occupations.yaml: curated import source, not a runtime registry -

def seed_file_occupations():
    return yaml.safe_load((ROOT / 'careeros/data/esco_occupations.yaml').read_text())['occupations']


def test_esco_occupations_yaml_is_a_curated_import_source():
    data = yaml.safe_load((ROOT / 'careeros/data/esco_occupations.yaml').read_text())
    assert data['occupations']
    for entry in data['occupations']:
        assert {'id', 'label', 'isco', 'esco_uri', 'keywords'} <= set(entry)
    # The corrected ISCO code from the design doc: ICT product manager is
    # 1330 (ICT service managers), not 2512 (software developers).
    ict_pm = next(e for e in data['occupations'] if e['id'] == 'ict-product-manager')
    assert ict_pm['isco'] == '1330'


def test_the_seed_covers_the_market_the_owner_searches_in():
    """M0-1: four occupations could not give most postings a function at
    all, so the seed is widened to the owner's own market (Zurich
    white-collar work). Ids are unique, since the facet is keyed by id and
    a duplicate would make the seed order decide which label wins."""
    entries = seed_file_occupations()
    ids = [entry['id'] for entry in entries]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 20
    # Each of the owner's named fields has at least one entry, matched by
    # id so a rename cannot quietly empty a field.
    for expected in ('software-developer', 'data-scientist', 'ict-product-manager',
                     'user-interface-designer', 'marketing-manager', 'financial-analyst',
                     'operations-manager', 'human-resources-manager',
                     'technical-sales-representative', 'management-consultant'):
        assert expected in ids


# --- Engineering items 1/3: seed tags.yaml's function facet from the ------
# --- curated esco_occupations.yaml bulk-export ----------------------------

def test_seed_function_facet_marks_unverified_entries_as_local_extension(root):
    added = vault.seed_function_facet(root)
    assert set(added) == {entry['id'] for entry in seed_file_occupations()}
    values = {v['id']: v for v in vault.load_tags(root)['facets']['function']['values']}
    # esco_uri is present for this one: a verified ESCO-backed entry.
    assert values['ict-product-manager']['esco_uri']
    assert values['ict-product-manager']['isco'] == '1330'
    assert values['ict-product-manager'].get('source') != 'local-extension'
    # esco_uri is null for this one in the curated seed file: not yet
    # verifiable, so it is added as a local extension instead, with isco
    # cleared rather than implying a roll-up guarantee it has not earned.
    assert values['software-developer']['source'] == 'local-extension'
    assert values['software-developer']['isco'] is None
    assert values['software-developer']['esco_uri'] is None


def test_a_seeded_vault_knows_every_proposed_id(root):
    """M0-1, the path end to end on a fixture vault: an empty function
    facet is why no job can carry a function, and one explicit seed run is
    what fills it. Every id in the curated file lands in tags.yaml and is
    then a known id, which is the only thing a stored function value or an
    extraction is ever checked against."""
    proposed = {entry['id'] for entry in seed_file_occupations()}
    assert vault.known_function_ids(root) == set()  # the state the live vault is in
    vault.seed_function_facet(root)
    facet = vault.load_tags(root)['facets']['function']
    assert {value['id'] for value in facet['values']} == proposed
    assert vault.known_function_ids(root) == proposed


def test_a_seeded_vault_gives_the_prompt_a_real_option_list(root):
    """The prompt section only exists when the facet has values, so an
    unseeded vault asks the model for a function and offers it nothing to
    answer with. After the seed the ids and both labels are in the
    prompt."""
    assert ingest._function_options_text(vault.function_facet_options(root)) == ''
    vault.seed_function_facet(root)
    options = vault.function_facet_options(root)
    text = ingest._function_options_text(options)
    assert 'KNOWN FUNCTION IDS' in text
    for entry in options:
        assert entry['id'] in text
    assert 'Softwarearchitekt' in text  # the German label reaches the prompt too
    assert 'KNOWN FUNCTION IDS' in ingest.build_prompt('Role text', options)[1]['content']


def test_a_seeded_id_survives_the_extraction_write(client, root, monkeypatch):
    """The other half of the same path: an id the seed contains is no
    longer dropped on the way into a job record, and it leaves no
    not-evidenced reason behind either."""
    from careeros import intake
    vault.seed_function_facet(root)
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<meta property="og:title" content="Role">')

    def start(description, callback, **kwargs):
        callback({'function': ['data-scientist'], 'summary': 'A role.'})
        return Mock(is_alive=lambda: False)

    monkeypatch.setattr(ingest, 'extract_async', start)
    created = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/job'}).json
    job = vault.load_job(root, created['job']['id'])
    assert job['function'] == ['data-scientist']
    assert job['field_status']['function'] == 'done'
    assert job['field_status_reason'] == {}


def test_seed_function_facet_is_idempotent_and_never_duplicates(root):
    first = vault.seed_function_facet(root)
    second = vault.seed_function_facet(root)
    assert first and second == []
    ids = [v['id'] for v in vault.load_tags(root)['facets']['function']['values']]
    assert len(ids) == len(set(ids))


def test_seed_function_facet_never_overwrites_an_existing_entry(root):
    vault.seed_function_facet(root)
    tags = vault.load_tags(root)
    for value in tags['facets']['function']['values']:
        if value['id'] == 'software-developer':
            value['label'] = 'Owner-edited label'
    vault.save_tags(root, tags)
    vault.seed_function_facet(root)  # re-running must not clobber the edit
    values = {v['id']: v for v in vault.load_tags(root)['facets']['function']['values']}
    assert values['software-developer']['label'] == 'Owner-edited label'


# --- Function field: list-valued, validated against tags.yaml -------------

def test_job_function_must_be_list_of_known_ids(root):
    seed_function_facet(root)
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://fiction.example/job',
                                'function': ['ict-product-manager']})
    assert job['function'] == ['ict-product-manager']


def test_job_function_rejects_unknown_id_for_direct_owner_edit(root, client):
    seed_function_facet(root)
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://fiction.example/job'})
    response = client.put('/api/jobs/' + job['id'], json={'function': ['typo-id']})
    assert response.status_code == 400
    assert 'Unknown function id' in response.json['error']


def test_job_function_defaults_to_empty_list_for_legacy_records(root):
    path = next((root / 'jobs').glob('*.yaml'))
    data = yaml.safe_load(path.read_text())
    data.pop('function', None)
    path.write_text(yaml.safe_dump(data))
    assert vault.load_job(root, data['id'])['function'] == []


# --- LLM-sourced writes drop unknown ids rather than rejecting outright ---

def test_apply_llm_update_drops_unknown_function_ids(client, root, monkeypatch):
    from careeros import intake
    seed_function_facet(root)
    html = '<meta property="og:title" content="Role"><meta property="og:site_name" content="Fiction Co">'
    monkeypatch.setattr(intake, 'fetch_url', lambda url: html)

    def start(description, callback, **kwargs):
        callback({'function': ['ict-product-manager', 'hallucinated-id'], 'summary': 'A role.'})
        return Mock(is_alive=lambda: False)

    monkeypatch.setattr(ingest, 'extract_async', start)
    created = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/job'}).json
    job = client.get('/api/jobs/' + created['job']['id']).json
    assert job['function'] == ['ict-product-manager']


def test_enrich_job_drops_unknown_function_ids(client, root, monkeypatch):
    from careeros import intake
    from tests.test_jobs import schema_html
    seed_function_facet(root)

    def fake_extract(description, client=None, model=None, function_options=None):
        return {'function': ['ict-product-manager', 'hallucinated-id'], 'ingest_source': 'llm', 'summary_source': ''}

    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html())
    monkeypatch.setattr(ingest, 'extract', fake_extract)
    result = client.post('/api/jobs/JOB-001/enrich')
    assert result.status_code == 200
    assert result.json['function'] == ['ict-product-manager']


# --- M0-2: a dropped id is a visible state with a reason, never silent ----

def test_a_dropped_function_id_leaves_a_trace_on_the_job_and_in_the_log(
        client, root, monkeypatch, caplog):
    """The reader answered for function and none of its ids could be
    stored. Before this the field simply read not_evidenced, which says
    the posting did not support a function -- indistinguishable from an
    unseeded registry, and the ids themselves were gone. The product rule
    is that failures and unknowns are visible states with a reason."""
    from careeros import intake
    seed_function_facet(root)
    html = '<meta property="og:title" content="Role"><meta property="og:site_name" content="Fiction Co">'
    monkeypatch.setattr(intake, 'fetch_url', lambda url: html)

    def start(description, callback, **kwargs):
        callback({'function': ['hallucinated-id', 'invented-id'], 'summary': 'A role.'})
        return Mock(is_alive=lambda: False)

    monkeypatch.setattr(ingest, 'extract_async', start)
    with caplog.at_level(logging.WARNING):
        created = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/job'}).json
    job = vault.load_job(root, created['job']['id'])

    assert job['function'] == []
    assert job['field_status']['function'] == 'not_evidenced'
    reason = job['field_status_reason']['function']
    assert 'hallucinated-id' in reason and 'invented-id' in reason
    assert any('2 function id' in record.getMessage() for record in caplog.records)


def test_a_reason_never_outlives_the_state_it_explains(client, root, monkeypatch):
    """The owner setting the function themselves settles the field, so the
    reason for the reading's dropped ids goes with it rather than hanging
    off a field that now has a value."""
    from careeros import intake
    seed_function_facet(root)
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<meta property="og:title" content="Role">')

    def start(description, callback, **kwargs):
        callback({'function': ['hallucinated-id'], 'summary': 'A role.'})
        return Mock(is_alive=lambda: False)

    monkeypatch.setattr(ingest, 'extract_async', start)
    created = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/job'}).json
    job_id = created['job']['id']
    assert vault.load_job(root, job_id)['field_status_reason']['function']

    client.put('/api/jobs/' + job_id, json={'function': ['ict-product-manager']})
    settled = vault.load_job(root, job_id)
    assert settled['field_status']['function'] == 'done'
    assert 'function' not in settled['field_status_reason']


def test_an_id_the_reading_gets_right_records_no_reason(client, root, monkeypatch):
    """A surviving id means the field has a value, so there is nothing to
    explain: the extra ids the registry refused are logged and that is
    all."""
    from careeros import intake
    seed_function_facet(root)
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<meta property="og:title" content="Role">')

    def start(description, callback, **kwargs):
        callback({'function': ['ict-product-manager', 'hallucinated-id'], 'summary': 'A role.'})
        return Mock(is_alive=lambda: False)

    monkeypatch.setattr(ingest, 'extract_async', start)
    created = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/job'}).json
    job = vault.load_job(root, created['job']['id'])
    assert job['field_status']['function'] == 'done'
    assert job['field_status_reason'] == {}


# --- build_prompt / LIST_FIELDS extension (offline, mocked-client) --------

def test_list_fields_includes_function():
    assert 'function' in ingest.LIST_FIELDS


def test_build_prompt_includes_known_function_ids_and_labels():
    options = [{'id': 'ict-product-manager', 'label': 'ICT product manager', 'label_de': 'ICT-Produktmanager'}]
    content = ingest.build_prompt('Role text', options)[1]['content']
    assert 'ict-product-manager' in content
    assert 'ICT product manager' in content and 'ICT-Produktmanager' in content


def test_build_prompt_without_function_options_omits_the_section():
    content = ingest.build_prompt('Role text')[1]['content']
    assert 'KNOWN FUNCTION IDS' not in content


def test_build_prompt_includes_function_keywords():
    options = [{'id': 'ict-product-manager', 'label': 'ICT product manager',
               'keywords': ['product manager', 'produktmanager']}]
    content = ingest.build_prompt('Role text', options)[1]['content']
    assert 'product manager' in content and 'produktmanager' in content


def test_parse_response_validates_function_as_list_field():
    content = json.dumps({'function': ['ict-product-manager', 'ict-product-manager', None]})
    parsed = ingest.parse_response(content)
    assert parsed['function'] == ['ict-product-manager']


# --- Heuristic fallback: no function guess ---------------------------------

def test_heuristic_extract_never_guesses_function():
    result = ingest.heuristic_extract('Product Manager at Example Bank\nBuild great products.')
    assert 'function' not in result


# --- Job detail page renders function tags ---------------------------------

def test_job_detail_renders_function_tags(client, root):
    # The canonical registry label ("Financial product manager") must be
    # served verbatim, not a title-cased reformatting of the id slug, and
    # the local-extension marker must be present since this entry has no
    # ESCO concept (decision 25).
    seed_function_facet(root)
    vault.save_job(root, {'function': ['financial-product-manager']}, 'JOB-001')
    page = client.get('/api/jobs/JOB-001?view=page').json
    assert page['job']['function'] == ['financial-product-manager']
    entry = page['function_labels']['financial-product-manager']
    assert entry['label'] == 'Financial product manager'
    assert entry['local'] is True
