"""Section 3 (Sector and Size via Standard Taxonomies). Synthetic data only;
no network access (the autouse offline fixture in conftest.py blocks it, and
the external-fetch pipeline is additionally exercised only through injected
fake fetchers, never the real network functions)."""
from pathlib import Path
import shutil

import pytest

from careeros import company_lookup, intake, sectors, vault
from careeros.server import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / 'sample/vault', tmp_path / 'vault')
    return tmp_path / 'vault'


@pytest.fixture
def client(root):
    return create_app(root).test_client()


# --- Keyword-match function with ambiguity refusal -------------------------

@pytest.mark.parametrize('text,expected', [
    ('Software and IT services', ['J']),
    ('Banking and insurance', ['K']),
    ('Logistics and warehousing', ['H']),
    ('Technology', []),  # genuinely ambiguous between J and M: refuse, don't guess
    ('Nonsense industry label', []),  # no match: refuse
    ('', []),
])
def test_match_sectors_confidence_and_ambiguity(text, expected):
    assert sectors.match_sectors(text) == expected


def test_match_sectors_known_codes_are_isic_sections():
    assert sectors.known_section_codes() == {s['code'] for s in sectors.load_isic_sections()}
    assert len(sectors.known_section_codes()) == 21


# --- Atomic size_class + size_range derivation -----------------------------

@pytest.mark.parametrize('count,size_range,size_class', [
    (9, '1-10', 'micro'), (10, '1-10', 'small'),
    (249, '201-1000', 'medium'), (250, '201-1000', 'large'),
    (1, '1-10', 'micro'), (1001, '1000+', 'large'),
])
def test_derive_size_boundary_values(count, size_range, size_class):
    assert sectors.derive_size(count) == {'size_range': size_range, 'size_class': size_class}


def test_derive_size_rejects_nonpositive_and_non_numeric():
    assert sectors.derive_size(0) is None
    assert sectors.derive_size(-5) is None
    assert sectors.derive_size(True) is None
    assert sectors.derive_size('bad') is None


def test_resolve_employee_count_range_resolves_to_upper_bound():
    assert sectors.resolve_employee_count('50-100') == 100
    assert sectors.resolve_employee_count('50 – 100') == 100
    assert sectors.resolve_employee_count(42) == 42
    assert sectors.resolve_employee_count('unknown') is None


def test_fill_size_updates_never_overwrites_populated_field():
    assert sectors.fill_size_updates(1500, '1-10', None) == {}  # contradicts size_range: refuse
    assert sectors.fill_size_updates(1500, None, 'micro') == {}  # contradicts size_class: refuse
    assert sectors.fill_size_updates(1500, None, None) == {'size_range': '1000+', 'size_class': 'large'}
    assert sectors.fill_size_updates(1500, '1000+', None) == {'size_class': 'large'}
    assert sectors.fill_size_updates(1500, '1000+', 'large') == {}


# --- Section 3 engineering item 2: raw employee_count retained in _extract -

def test_extract_retains_both_size_bucket_and_raw_employee_count():
    html = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
            '"hiringOrganization":{"name":"Rich Labs","numberOfEmployees":42}}</script>')
    result = intake.extract('https://rich.example/job', html)
    assert result['size'] == '11-50'
    assert result['employee_count'] == 42


def test_extract_resolves_employee_range_string_to_upper_bound():
    html = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
            '"hiringOrganization":{"name":"Rich Labs","numberOfEmployees":"50-100"}}</script>')
    result = intake.extract('https://rich.example/job', html)
    assert result['employee_count'] == 100
    assert result['size'] == '51-200'


# --- Company schema: sectors list replaces single sector -------------------

def test_company_sectors_defaults_to_empty_list(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Fiction Co'})
    assert company['sectors'] == []


def test_company_sectors_must_be_known_isic_codes(tmp_path):
    with pytest.raises(ValueError, match='ISIC'):
        vault.save_company(tmp_path, {'name': 'Fiction Co', 'sectors': ['ZZ']})
    assert vault.save_company(tmp_path, {'name': 'Fiction Co', 'sectors': ['J', 'K']})['sectors'] == ['J', 'K']


def test_legacy_null_sectors_load_as_empty_list(root):
    path = next((root / 'companies').glob('*.yaml'))
    import yaml
    data = yaml.safe_load(path.read_text())
    data['sectors'] = None
    path.write_text(yaml.safe_dump(data))
    assert vault.load_company(root, data['id'])['sectors'] == []


# --- Legacy sector/size -> sectors/size_range translation (decision 6) ----

def test_legacy_sector_translates_to_sectors_on_confident_match(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Fiction Co', 'sector': 'Software and IT services'})
    assert company['sectors'] == ['J']
    assert company['sector'] == 'Software and IT services'  # legacy field itself is untouched


def test_legacy_sector_ambiguous_does_not_populate_sectors(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Fiction Co', 'sector': 'Technology'})
    assert company['sectors'] == []


def test_new_shape_wins_over_legacy_when_both_sent(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Fiction Co', 'sector': 'Banking and insurance', 'sectors': ['J']})
    assert company['sectors'] == ['J']


def test_legacy_size_copies_verbatim_to_size_range_without_size_class(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Fiction Co', 'size': '50-200'})
    assert company['size_range'] == '50-200'
    assert company['size_class'] is None  # a bucket label alone cannot yield a confident size_class


def test_size_class_enum_validated(tmp_path):
    with pytest.raises(ValueError, match='size_class'):
        vault.save_company(tmp_path, {'name': 'Fiction Co', 'size_class': 'huge'})


# --- Posting-intake plumbing: employee_count reaches both job and company -

def test_job_intake_employee_count_reaches_job_and_new_company(client, monkeypatch):
    html = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
            '"hiringOrganization":{"name":"Freshly Created Labs","numberOfEmployees":42}}</script>')
    monkeypatch.setattr(intake, 'fetch_url', lambda url: html)
    data = client.post('/api/jobs/intake', json={'url': 'https://fresh.example/job'}).json
    assert data['job']['employee_count'] == 42
    assert data['company']['size_range'] == '11-50'
    assert data['company']['size_class'] == 'small'


def test_job_intake_employee_count_reaches_existing_company(client, root, monkeypatch):
    company = vault.save_company(root, {'name': 'Existing Labs'})
    html = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
            '"hiringOrganization":{"name":"Existing Labs","numberOfEmployees":600}}</script>')
    monkeypatch.setattr(intake, 'fetch_url', lambda url: html)
    data = client.post('/api/jobs/intake', json={'url': 'https://fresh.example/job'}).json
    assert data['company']['id'] == company['id']
    assert data['company']['size_range'] == '201-1000'
    assert data['company']['size_class'] == 'large'


def test_enrich_job_fills_employee_count_on_company(client, monkeypatch):
    from tests.test_jobs import schema_html
    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html(
        hiringOrganization={'name': 'Enrich Target Labs', 'numberOfEmployees': 5}))
    result = client.post('/api/jobs/JOB-001/enrich')
    assert result.status_code == 200
    company = client.get('/api/companies/' + result.json['company_id']).json
    assert company['size_range'] == '1-10' and company['size_class'] == 'micro'


# --- Section 1's enrich.py gating: kind != employer never aggregates sectors

def test_regenerate_company_gates_sector_aggregation_on_employer_kind(tmp_path):
    from careeros.enrich import regenerate_company
    company = vault.save_company(tmp_path, {'name': 'Fiction University', 'kind': 'institution'})
    vault.save_job(tmp_path, {'title': 'Guest lecture', 'url': 'https://fiction.example/job',
                              'company_id': company['id'], 'sector': 'Software'})
    regenerated = regenerate_company(tmp_path, company['id'])
    assert 'sectors' not in regenerated['enrichment']
    assert regenerated['enrichment']['hiring_activity']['count'] == 1  # non-sector rollups still included


def test_regenerate_company_strips_stale_sectors_after_rekind(tmp_path):
    from careeros.enrich import regenerate_company
    company = vault.save_company(tmp_path, {'name': 'Formerly Employer'})
    vault.save_job(tmp_path, {'title': 'Role', 'url': 'https://fiction.example/job',
                              'company_id': company['id'], 'sector': 'Software and IT services'})
    before = vault.load_company(tmp_path, company['id'])
    assert before['enrichment']['sectors'] == ['Software and IT services']
    vault.save_company(tmp_path, {'kind': 'institution', 'sectors': ['J']}, company['id'])
    after = regenerate_company(tmp_path, company['id'])
    assert 'sectors' not in after['enrichment']
    assert after['sectors'] == []


# --- External-fetch pipeline (new engineering); only ever reached through -
# --- injected fake fetchers, matching the existing intake test pattern.   -

def test_fetch_company_jsonld_extracts_industry_and_employee_count():
    html = '<script type="application/ld+json">{"industry":"Software","numberOfEmployees":42}</script>'
    result = company_lookup.fetch_company_jsonld('https://fiction.example', fetch=lambda url: html)
    assert result == {'industry': 'Software', 'employee_count': 42}


def test_fetch_company_jsonld_rejects_private_destination():
    # A synthetic RFC1918 address, not a malformed string: this exercises the
    # actual private-network guard rather than the unrelated URL-format check.
    def fake_fetch(url):
        raise AssertionError('must not be called for a private-network destination')
    assert company_lookup.fetch_company_jsonld('http://10.0.0.5/', fetch=fake_fetch) == {}


def test_fetch_wikidata_prefers_most_recent_dated_statement():
    import json
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {
            'P452': [{'mainsnak': {'datavalue': {'value': {'id': 'Q_SOFTWARE'}}}}],
            'P1128': [
                {'mainsnak': {'datavalue': {'value': {'amount': '+100'}}},
                 'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2020-00-00T00:00:00Z'}}}]}},
                {'mainsnak': {'datavalue': {'value': {'amount': '+250'}}},
                 'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2024-00-00T00:00:00Z'}}}]}},
            ],
        }}}})
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result['employee_count'] == 250


def test_fetch_wikidata_resolves_industry_entity_to_label_text():
    # P452 (industry) points at another Wikidata item id (an opaque id, not
    # free text), so the keyword matcher must receive that item's resolved
    # label, not the id itself.
    import json
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        if 'Q1.json' in url:
            return json.dumps({'entities': {'Q1': {'claims': {
                'P452': [{'mainsnak': {'datavalue': {'value': {'id': 'Q_SOFTWARE'}}}}],
            }}}})
        if 'Q_SOFTWARE.json' in url:
            return json.dumps({'entities': {'Q_SOFTWARE': {'labels': {
                'en': {'value': 'Software industry'}}}}})
        return None
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result['industry'] == 'Software industry'


def test_fetch_wikidata_refuses_undated_statement():
    import json
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {
            'P1128': [{'mainsnak': {'datavalue': {'value': {'amount': '+250'}}}}],  # no P585 qualifier
        }}}})
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result.get('employee_count') is None


def test_fetch_osm_matches_shop_only_result():
    # office=* is not the only occupied-building tag; a shop=* result with
    # no office tag at all must not be excluded.
    import json
    def fetch(url):
        return json.dumps({'elements': [{'tags': {'shop': 'books'}}]})
    result = company_lookup.fetch_osm('Fiction Books', fetch=fetch)
    assert result['industry'] == 'books'


# --- Backfill action (decision 27) -----------------------------------------

def test_backfill_scoped_to_employer_kind_only(root):
    institution = vault.save_company(root, {'name': 'Fiction University', 'kind': 'institution'})
    updated = company_lookup.backfill(root, sector_signals=(), size_signals=())
    assert institution['id'] not in updated


def test_backfill_promotes_from_job_aggregation_before_external_fetch(tmp_path):
    # An isolated vault (not the sample fixture's other companies) so the
    # call tracking below is unambiguous about which company it covers.
    company = vault.save_company(tmp_path, {'name': 'Promotable Labs'})
    vault.save_job(tmp_path, {'title': 'Role', 'url': 'https://fiction.example/promotable',
                              'company_id': company['id'], 'sector': 'Banking and insurance'})

    # Track calls directly rather than raising from inside the injected
    # fetcher: _safe_fetch's broad except would otherwise swallow that
    # exception before this test ever saw it, masking a real network call.
    calls = []

    def tracking_fetch(url):
        calls.append(url)
        return None

    updated = company_lookup.backfill(tmp_path, size_signals=(), fetch=tracking_fetch)
    assert calls == []
    assert company['id'] in updated
    assert vault.load_company(tmp_path, company['id'])['sectors'] == ['K']


def test_backfill_size_cascade_respects_consistency_with_populated_range(root):
    company = vault.save_company(root, {'name': 'Partial Labs', 'size_range': '1-10'})

    def fake_jsonld(c, fetch=None):
        return {'employee_count': 500}  # contradicts the already-populated size_range

    company_lookup.backfill(root, size_signals=(fake_jsonld,))
    saved = vault.load_company(root, company['id'])
    # The contradictory count still fills nothing (no size_class written),
    # but the refusal is now surfaced as a review flag rather than silently
    # leaving a half-populated pair with no pending indication.
    assert saved['size_class'] is None
    assert saved['size_range'] == '1-10'
    assert company_lookup.FLAG_SIZE_INCONSISTENT in saved['review_flags']


def test_backfill_sector_ambiguous_signal_flags_for_review(root):
    company = vault.save_company(root, {'name': 'Ambiguous Labs'})

    def ambiguous_signal(c, fetch=None):
        return {'industry': 'Technology', 'employee_count': None}  # matches both J and M

    updated = company_lookup.backfill(root, sector_signals=(ambiguous_signal,), size_signals=())
    saved = vault.load_company(root, company['id'])
    assert company['id'] in updated
    assert saved['sectors'] == []
    assert company_lookup.FLAG_SECTOR_AMBIGUOUS in saved['review_flags']


def test_backfill_sector_source_conflict_flags_for_review(root):
    company = vault.save_company(root, {'name': 'Conflicted Labs'})

    def software_signal(c, fetch=None):
        return {'industry': 'Software and IT services', 'employee_count': None}

    def banking_signal(c, fetch=None):
        return {'industry': 'Banking and insurance', 'employee_count': None}

    updated = company_lookup.backfill(root, sector_signals=(software_signal, banking_signal), size_signals=())
    saved = vault.load_company(root, company['id'])
    assert company['id'] in updated
    assert saved['sectors'] == []
    assert company_lookup.FLAG_SECTOR_CONFLICT in saved['review_flags']


def test_backfill_clears_sector_flag_once_resolved(root):
    company = vault.save_company(root, {'name': 'Eventually Resolved Labs'})

    def ambiguous_signal(c, fetch=None):
        return {'industry': 'Technology', 'employee_count': None}

    company_lookup.backfill(root, sector_signals=(ambiguous_signal,), size_signals=())
    assert company_lookup.FLAG_SECTOR_AMBIGUOUS in vault.load_company(root, company['id'])['review_flags']

    def confident_signal(c, fetch=None):
        return {'industry': 'Banking and insurance', 'employee_count': None}

    company_lookup.backfill(root, sector_signals=(confident_signal,), size_signals=())
    saved = vault.load_company(root, company['id'])
    assert saved['sectors'] == ['K']
    assert company_lookup.FLAG_SECTOR_AMBIGUOUS not in saved['review_flags']


def test_backfill_wires_kind_migration_for_records_missing_kind(root):
    # A record that predates the kind field (missing the key entirely, as
    # every sample-vault company does before migration) must still be
    # picked up by the kind backfill as part of this action, not skipped.
    for company in vault.list_companies(root):
        assert company.get('kind') is None
    company_lookup.backfill(root, sector_signals=(), size_signals=())
    for company in vault.list_companies(root):
        assert company['kind'] == 'employer'


def test_backfill_sectors_and_size_are_independent_cascades(root):
    company = vault.save_company(root, {'name': 'Independent Labs', 'sectors': ['K']})

    def fake_jsonld(c, fetch=None):
        return {'employee_count': 42}

    updated = company_lookup.backfill(root, size_signals=(fake_jsonld,))
    saved = vault.load_company(root, company['id'])
    assert company['id'] in updated
    assert saved['sectors'] == ['K']  # untouched: already populated
    assert saved['size_range'] == '11-50' and saved['size_class'] == 'small'


# --- Companies page: sector/size filter controls (engineering item 8) -----

def test_companies_page_renders_sector_and_size_filter_controls(client, root):
    vault.save_company(root, {'name': 'Filterable Labs', 'sectors': ['J'], 'size_class': 'small'})
    html = client.get('/companies').text
    assert 'id="sector-filter"' in html and 'id="size-filter"' in html
    assert 'value="J"' in html  # ISIC section option present
    assert 'data-sectors="J"' in html and 'data-size-class="small"' in html


def test_companies_page_card_shows_sector_label_not_bare_code(client, root):
    vault.save_company(root, {'name': 'Labeled Labs', 'sectors': ['J']})
    html = client.get('/companies').text
    assert 'Information and communication' in html  # the ISIC label for J, not the bare code "J"


def test_companies_page_has_backfill_action(client, root):
    html = client.get('/companies').text
    assert 'id="backfill-sector-size"' in html


def test_backfill_endpoint_is_explicit_and_never_runs_automatically(client, root, monkeypatch):
    calls = []
    monkeypatch.setattr(company_lookup, 'backfill', lambda root, **kw: calls.append(root) or [])
    # Intake and enrich must never trigger the backfill path themselves.
    client.post('/api/jobs/intake', json={'url': 'https://fiction.example/job'})
    assert calls == []
    response = client.post('/api/companies/backfill-sector-size')
    assert response.status_code == 200
    assert calls == [root]
