"""Section 4 (Job Function Taxonomy). Mocked LLM client only; no network
access and no real model/provider is named. Some fixtures use real posting
titles from the owner's vault on purpose: they are the golden-set rows the
vocabulary has to express."""
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
from tests.conftest import post_ai

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


# The function vocabulary, pinned in one place the same way
# `vault.STOPPED_REASONS` is pinned in tests/test_board_d7.py: the seed
# file is data an owner edits, and a value leaving the list is a decision,
# never a diff nobody noticed. In seed-file order, which is the order the
# facet and the extraction prompt receive.
FUNCTION_IDS = (
    'ict-product-manager', 'software-developer', 'ict-service-manager', 'software-architect',
    'ict-system-administrator', 'ict-security-manager', 'embedded-systems-security-engineer',
    'ict-project-manager', 'ict-business-analyst', 'ict-business-analysis-manager',
    'ict-consultant', 'data-scientist', 'data-engineer', 'data-analyst',
    'product-manager', 'chief-product-officer',
    'user-experience-analyst', 'user-interface-designer',
    'marketing-manager', 'digital-marketing-manager',
    'sales-manager', 'technical-sales-representative',
    'financial-investment-adviser', 'banking-products-manager',
    'financial-analyst', 'accountant', 'financial-manager',
    'risk-manager', 'compliance-officer',
    'human-resources-manager', 'recruitment-consultant', 'management-consultant',
    'business-consultant', 'business-development-manager',
    'innovation-manager', 'innovation-officer', 'digital-transformation-manager',
    'supply-chain-manager', 'operations-manager', 'customer-service-manager',
)

# The ESCO identity of every entry that claims one, pinned beside the id
# list for the same reason: these are citations, each one fetched from
# https://ec.europa.eu/esco/api/resource/occupation?uri=<uri>&language=en
# on 2026-10-16, where the concept's preferred label matched the entry's
# label and its `code` began with the four digits recorded as `isco`. A
# diff here is either a new verification or a fabrication, and the point
# of the golden set (5 of its 15 URIs were invented by the labelling
# model and 404) is that the two must never be confused.
ESCO_BACKED = {
    'ict-product-manager': ('a79170ad-0b7b-4697-864f-1748359aa10a', '1330'),
    'software-developer': ('f2b15a0e-e65a-438a-affb-29b9d50b77d1', '2512'),
    'ict-project-manager': ('8b6388a4-4904-471b-9331-d3b1211f5525', '1330'),
    'ict-business-analysis-manager': ('4b3201cb-ffc5-4f61-9fc3-5c0f0038fa5f', '2511'),
    'ict-consultant': ('b1c80369-067e-4041-84c8-dbe65640a5d8', '2511'),
    'product-manager': ('9f508305-80ce-4111-8722-f2c9b4a44890', '1223'),
    'marketing-manager': ('6fcf4638-e7c7-4978-9302-9a7b63a3d57c', '1221'),
    'sales-manager': ('a7594892-ff23-4e2a-aedf-2f967ebca15c', '1221'),
    'banking-products-manager': ('c530b0ee-46f8-40fb-818c-d9b44b891cb9', '1221'),
    'business-consultant': ('6a29d804-f775-446c-bec7-35fc4e28ac97', '2421'),
}

# The owner labels the golden set uses that have no ESCO concept at all:
# every one of their URIs 404s against the live API, so decision 25 keeps
# them as owner-governed local extensions with a visible marker and no
# ISCO code to roll up (decision 22 scopes that guarantee to ESCO-backed
# entries). They must stay expressible on their own; being absorbed into
# an ESCO entry whose unit group says something else is the failure this
# list exists to prevent.
LOCAL_EXTENSIONS = ('embedded-systems-security-engineer', 'chief-product-officer',
                    'digital-marketing-manager', 'innovation-officer',
                    'digital-transformation-manager')


def test_the_seed_is_the_pinned_vocabulary():
    """M0-1/CAREER-29: four occupations could not give most postings a
    function at all, so the seed is the owner's own market (Zurich
    white-collar work). Ids are unique and ordered, since the facet is
    keyed by id (a duplicate would make the seed order decide which label
    wins) and the prompt is handed the list as it stands."""
    ids = [entry['id'] for entry in seed_file_occupations()]
    assert tuple(ids) == FUNCTION_IDS
    assert len(ids) == len(set(ids))


def test_every_esco_backed_entry_carries_its_verified_uri_and_unit_group():
    """CAREER-29 follow-up: the 10 ESCO concepts the golden set of
    2026-10-16 verified against the live API are the seed's citations. The
    URI is what makes an entry ESCO-backed (`seed_function_facet` seeds
    anything else as a local extension), so a URI that drifts, or an isco
    that stops being the unit group of the cited concept, is a silent
    claim about a standard."""
    entries = {entry['id']: entry for entry in seed_file_occupations()}
    cited = {}
    for identifier, entry in entries.items():
        if entry.get('esco_uri'):
            cited[identifier] = (entry['esco_uri'].rsplit('/', 1)[-1], entry['isco'])
    assert cited == ESCO_BACKED
    for identifier in ESCO_BACKED:
        assert entries[identifier]['esco_uri'].startswith(
            'http://data.europa.eu/esco/occupation/'), identifier
        assert not entries[identifier].get('local'), identifier


def test_an_entry_carries_an_isco_unit_group_unless_it_has_no_esco_parent():
    """Draft choice 22 derives ISCO from the concept rather than storing a
    hand-picked code, so the code recorded is the finest level ISCO-08
    has: the four-digit unit group. A coarser roll-up is a prefix of it,
    while a three-digit code would have lost the finest level for good.

    A local extension is the one kind of entry with no code: it has no
    ESCO concept to derive one from, and choice 22 limits the roll-up
    guarantee to ESCO-backed entries for exactly that reason. Writing the
    owner's own ISCO reading in would be the hand-picked code choice 22
    refuses -- it lives in the golden set, with its confidence, instead."""
    for entry in seed_file_occupations():
        if entry.get('local'):
            assert entry['isco'] is None, entry['id']
            assert entry['esco_uri'] is None, entry['id']
            continue
        assert isinstance(entry['isco'], str), entry['id']
        assert len(entry['isco']) == 4 and entry['isco'].isdigit(), entry['id']


def test_every_label_with_no_esco_concept_is_marked_local():
    """The 5 labels whose golden-set URIs 404 are present, marked, and
    unmapped. `local: true` and not merely a null esco_uri, because the
    two mean different things: a null URI is "not verified yet" (the
    proposed entries), while the marker is "there is nothing to verify",
    which is what stops a later round filling in a code by hand."""
    marked = tuple(entry['id'] for entry in seed_file_occupations() if entry.get('local'))
    assert marked == LOCAL_EXTENSIONS


@pytest.mark.parametrize('title,expected', [
    # One line per shape the owner's own stored postings take, so a
    # keyword edit that stops answering for a real posting fails here
    # rather than on the next reading. Titles and expectations follow the
    # golden set of 2026-10-16; where a title genuinely reads two ways,
    # both homes are listed, because the keyword list is prompt context
    # rather than a matcher and the posting's own text is what decides.
    ('Staff Product Manager', 'ict-product-manager'),
    ('Head of Product (Mail)', 'ict-product-manager'),
    # Same phrase, the other golden reading: the top product role, which
    # has no ESCO concept and used to be absorbed into 1330 for want of an
    # entry of its own.
    ('Head of Product', 'chief-product-officer'),
    ('Product Owner AI Portfolio & Delivery', 'ict-product-manager'),
    ('Engagierte Persönlichkeit für Produktportfolioentwicklung', 'product-manager'),
    ('Product Manager TMS (m/w/d) 100%', 'product-manager'),
    ('Head Product Management Funds', 'banking-products-manager'),
    ('Senior Java-Entwickler/in mit technischer Verantwortung', 'software-developer'),
    ('Digitalisierungs- und Innovationsprojektleiter', 'ict-project-manager'),
    ('Digitalisierungs- und Innovationsprojektleiter', 'digital-transformation-manager'),
    ('Projektleiter*in Digitales Ökosystem in Zürich', 'digital-transformation-manager'),
    ('Lead Business & Technology Engineering (w/m/d)', 'ict-business-analysis-manager'),
    ('M365 Digital Workplace Consultant', 'ict-consultant'),
    ('AI Tech Consultant (all genders)', 'ict-consultant'),
    ('Ökosystem & Strategie Manager 80-100%', 'business-development-manager'),
    ('Innovation Management Professional', 'innovation-manager'),
    ('Innovation Management Professional', 'innovation-officer'),
    ('Senior Growth Marketing Manager (100%)', 'marketing-manager'),
    ('Senior Growth Marketing Manager (100%)', 'digital-marketing-manager'),
    ('CHANNEL MANAGER', 'sales-manager'),
    # Was pinned to ict-security-manager (1330) until 2026-10-16, which
    # the golden set reads as 2529: product and device security, not ICT
    # security management.
    ('Product & Solution Security Expert 80-100%', 'embedded-systems-security-engineer'),
    ('Senior Manager, Global Trade Control (GTC)', 'compliance-officer'),
    ('Senior Manager, Global Trade Control (GTC), Digital Enablement',
     'digital-transformation-manager'),
])
def test_a_posting_the_owner_stores_has_an_id_to_land_in(title, expected):
    entry = next(e for e in seed_file_occupations() if e['id'] == expected)
    lowered = title.casefold()
    assert any(keyword in lowered for keyword in entry['keywords']), (title, expected)


@pytest.mark.parametrize('title,absorbed_into', [
    # The two absorptions the golden set caught, each one a keyword that
    # made an ESCO entry the only home for a posting whose own label has
    # no ESCO concept and a different ISCO unit group. Both labels now
    # have their own entry (above), so the keyword must no longer reach
    # the wrong one at all -- a shared phrase is fine between two
    # defensible homes, and not between a right and a wrong one.
    ('Product & Solution Security Expert 80-100%', 'ict-security-manager'),
])
def test_a_label_with_no_esco_concept_is_not_absorbed_into_a_wrong_unit_group(title, absorbed_into):
    entry = next(e for e in seed_file_occupations() if e['id'] == absorbed_into)
    lowered = title.casefold()
    assert not [keyword for keyword in entry['keywords'] if keyword in lowered], (title, absorbed_into)


def test_every_golden_set_label_is_expressible():
    """The golden set of 2026-10-16 is the record of what the owner's own
    postings are, so every label in it needs somewhere to land: a label
    with no id is a label the extraction can never return, and the
    coverage measurement would score it as a miss that is really a gap in
    the vocabulary. Two golden rows are 'unclassifiable' (a careers
    landing page and a job-board page, neither of them a posting), which
    is not a function and deliberately has no id."""
    labels = {entry['label'].casefold() for entry in seed_file_occupations()}
    golden = ('ICT project manager', 'ICT consultant', 'sales manager', 'ICT product manager',
              'product manager', 'marketing manager', 'banking products manager',
              'business consultant', 'ICT business analysis manager', 'software developer',
              'chief product officer', 'digital marketing manager',
              'digital transformation manager', 'embedded systems security engineer',
              'innovation officer')
    assert [label for label in golden if label.casefold() not in labels] == []


# --- Engineering items 1/3: seed tags.yaml's function facet from the ------
# --- curated esco_occupations.yaml bulk-export ----------------------------

def test_seed_function_facet_marks_unverified_entries_as_local_extension(root):
    added, updated = vault.seed_function_facet(root)
    assert set(added) == {entry['id'] for entry in seed_file_occupations()}
    assert updated == []  # nothing was there to bring up to date
    values = {v['id']: v for v in vault.load_tags(root)['facets']['function']['values']}
    # esco_uri is present for this one: a verified ESCO-backed entry.
    assert values['ict-product-manager']['esco_uri']
    assert values['ict-product-manager']['isco'] == '1330'
    assert values['ict-product-manager'].get('source') != 'local-extension'
    # esco_uri is null for this one in the curated seed file: not yet
    # verifiable, so it is added as a local extension instead, with isco
    # cleared rather than implying a roll-up guarantee it has not earned.
    assert values['ict-service-manager']['source'] == 'local-extension'
    assert values['ict-service-manager']['isco'] is None
    assert values['ict-service-manager']['esco_uri'] is None
    # And this one has no ESCO concept at all to verify (decision 25), so
    # it is marked the same way and the seed file says so itself.
    assert values['chief-product-officer']['source'] == 'local-extension'
    assert values['chief-product-officer']['isco'] is None
    assert values['chief-product-officer']['esco_uri'] is None


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
    assert first.added and not first.updated
    assert (second.added, second.updated) == ([], [])
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


# --- Re-running the seed: confirming an entry has to reach the vault -------

def test_re_running_the_seed_fills_in_a_confirmed_esco_uri_and_unit_group(root):
    """CAREER-29 follow-up, the reviewer's own finding: the documented way
    to confirm an entry is to fill in its esco_uri in the import source
    and run the seed again, and until 2026-10-16 that second run skipped
    every id the facet already held, so the confirmation reached no vault
    and the entry stayed a local extension for good. A re-run now makes
    the ESCO identity in the import source true of the vault."""
    tags = vault.load_tags(root)
    tags['facets']['function']['values'] = [
        {'id': 'product-manager', 'label': 'Product manager', 'isco': None,
         'esco_uri': None, 'source': 'local-extension'},
    ]
    vault.save_tags(root, tags)

    added, updated = vault.seed_function_facet(root)

    assert 'product-manager' not in added and 'product-manager' in updated
    stored = {v['id']: v for v in vault.load_tags(root)['facets']['function']['values']}
    assert stored['product-manager']['esco_uri'] == (
        'http://data.europa.eu/esco/occupation/9f508305-80ce-4111-8722-f2c9b4a44890')
    assert stored['product-manager']['isco'] == '1223'
    # The marker goes with the code it was standing in for: an entry that
    # now cites a concept is not a local extension any more.
    assert 'source' not in stored['product-manager']
    assert vault.function_label_map(root)['product-manager']['local'] is False


def test_re_running_the_seed_merges_new_keywords_into_an_existing_entry(root):
    """The other half of the same no-op: the extraction prompt is built
    from the facet (`vault.function_facet_options`), never from the import
    source, so a keyword added to an entry the vault already holds reached
    no reading either. Merged rather than replaced, so an anchor the owner
    added by hand is still there afterwards."""
    tags = vault.load_tags(root)
    tags['facets']['function']['values'] = [
        {'id': 'ict-consultant', 'label': 'ICT consultant', 'isco': None, 'esco_uri': None,
         'source': 'local-extension', 'keywords': ['it consultant', 'owner-added anchor']},
    ]
    vault.save_tags(root, tags)

    vault.seed_function_facet(root)

    stored = {v['id']: v for v in vault.load_tags(root)['facets']['function']['values']}
    keywords = stored['ict-consultant']['keywords']
    assert 'owner-added anchor' in keywords            # never removed
    assert 'digital workplace consultant' in keywords  # and the new one arrived
    assert keywords.count('it consultant') == 1        # and nothing is doubled
    text = ingest._function_options_text(vault.function_facet_options(root))
    assert 'digital workplace consultant' in text


def test_re_running_the_seed_unmaps_an_entry_the_source_marks_local(root):
    """A label that loses its ESCO concept must not keep the code: the
    golden set found 5 URIs the labelling model had invented, and an entry
    seeded from one of those before it was checked carries a code it never
    earned. The import source marking the entry `local: true` is what says
    so, and the re-run is what makes it true of the vault."""
    tags = vault.load_tags(root)
    tags['facets']['function']['values'] = [
        {'id': 'chief-product-officer', 'label': 'Chief product officer', 'isco': '1223',
         'esco_uri': 'http://data.europa.eu/esco/occupation/8a0afc76-4a09-449a-9e7b-a33495889f95'},
    ]
    vault.save_tags(root, tags)

    _added, updated = vault.seed_function_facet(root)

    assert updated == ['chief-product-officer']
    stored = {v['id']: v for v in vault.load_tags(root)['facets']['function']['values']}
    assert stored['chief-product-officer']['esco_uri'] is None
    assert stored['chief-product-officer']['isco'] is None
    assert stored['chief-product-officer']['source'] == 'local-extension'


def test_re_running_the_seed_leaves_a_vault_only_confirmation_alone(root):
    """The import source is authoritative about the entries it makes a
    statement about, and silent about the rest. An entry whose source row
    is still unverified -- no esco_uri, and not marked local -- but which
    carries one in the vault was confirmed by someone working in the
    vault itself, and the seed has nothing better to say."""
    tags = vault.load_tags(root)
    tags['facets']['function']['values'] = [
        {'id': 'ict-service-manager', 'label': 'ICT service manager', 'isco': '1330',
         'esco_uri': 'http://data.europa.eu/esco/occupation/confirmed-in-the-vault'},
    ]
    vault.save_tags(root, tags)

    vault.seed_function_facet(root)

    stored = {v['id']: v for v in vault.load_tags(root)['facets']['function']['values']}
    assert stored['ict-service-manager']['esco_uri'].endswith('confirmed-in-the-vault')
    assert stored['ict-service-manager']['isco'] == '1330'


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
    assert post_ai(client, '/api/jobs/JOB-001/enrich').status_code == 202
    assert client.get('/api/jobs/JOB-001').json['function'] == ['ict-product-manager']


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


def test_two_drop_sites_on_one_write_both_leave_their_reason(
        client, root, monkeypatch):
    """One reading can trip two drop sites at once: ids the registry
    refused AND a value redaction emptied. The reason map has to carry
    both -- before, the redaction reporter rebased on the stored record
    and clobbered the function reason the first call had just added,
    leaving a not_evidenced with nothing to explain it."""
    from careeros import intake
    seed_function_facet(root)
    html = '<meta property="og:title" content="Role"><meta property="og:site_name" content="Fiction Co">'
    monkeypatch.setattr(intake, 'fetch_url', lambda url: html)

    def start(description, callback, **kwargs):
        callback({'function': ['hallucinated-id'], 'seniority': 'Lead, 192.168' + '.5.9',
                  'summary': 'A role.'})
        return Mock(is_alive=lambda: False)
    monkeypatch.setattr(ingest, 'extract_async', start)
    created = client.post('/api/jobs/intake', json={'url': 'https://fiction.example/job'}).json
    job = vault.load_job(root, created['job']['id'])

    assert job['field_status']['function'] == 'not_evidenced'
    assert job['field_status']['seniority'] == 'not_evidenced'
    assert 'hallucinated-id' in job['field_status_reason']['function']
    assert 'private network details' in job['field_status_reason']['seniority']


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
