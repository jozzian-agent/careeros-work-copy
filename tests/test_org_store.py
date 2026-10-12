"""Protect capability persistence through the existing company vault format."""
from careeros import vault
from careeros.org_store import VaultOrganisationStore
from org_intake import resolve_identity
from org_intake.identity import add_identifier


def test_store_round_trip_merges_records_and_replaces_lists(tmp_path):
    store = VaultOrganisationStore(tmp_path)
    assert store.list_organisations() == []
    assert store.load_organisation('CO-999') is None
    company = store.save_organisation({
        'name': 'Northwind Logistics', 'notes': 'Owner notes',
        'sectors': ['H'], 'size_range': '11-50', 'size_class': 'small',
        'identifiers': [{'type': 'domain', 'value': 'northwind.example',
                         'provenance': 'user'}],
        'sources': [{'id': 'SRC-1', 'kind': 'careers_page',
                     'url': 'https://northwind.example/jobs',
                     'ats_provider': None, 'active': True, 'last_polled': None}],
    })
    saved = store.save_organisation({
        'name': 'Northwind Freight', 'sectors': [], 'identifiers': [], 'sources': [],
    }, company['id'])
    assert saved['name'] == 'Northwind Freight'
    assert saved['notes'] == 'Owner notes'
    assert saved['size_range'] == '11-50'
    assert saved['size_class'] == 'small'
    assert saved['sectors'] == saved['identifiers'] == saved['sources'] == []
    assert VaultOrganisationStore(tmp_path).load_organisation(company['id']) == saved
    assert vault.load_company(tmp_path, company['id']) == saved
    assert store.list_organisations() == [saved]


def test_capability_resolves_and_teaches_identifiers_through_vault(tmp_path):
    store = VaultOrganisationStore(tmp_path)
    result = resolve_identity(store, url='https://jobs.lever.co/northwind/123',
                              employer_name='Northwind Logistics')
    assert result['link_state'] == 'linked'
    company = vault.load_company(tmp_path, result['record_id'])
    assert company['name'] == 'Northwind Logistics'
    assert company['identifiers'] == [
        {'type': 'ats_tenant', 'value': 'lever:northwind', 'provenance': 'scrape'}]
    taught = add_identifier(store, company, 'name_variant', 'Northwind Freight', 'user')
    assert len(taught['identifiers']) == 2
    assert taught['identifiers'][0] == company['identifiers'][0]
    repeated = resolve_identity(store, url='https://jobs.lever.co/northwind/456')
    assert repeated['record_id'] == company['id']
    assert len(store.list_organisations()) == 1
