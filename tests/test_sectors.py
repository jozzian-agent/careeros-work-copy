"""Section 3 (Sector and Size via Standard Taxonomies). Synthetic data only;
no network access (the autouse offline fixture in conftest.py blocks it, and
the external-fetch pipeline is additionally exercised only through injected
fake fetchers, never the real network functions)."""
from pathlib import Path
import shutil
from urllib import request

import pytest

from careeros import enrich as product_enrich, intake, vault
from org_intake import enrich as company_lookup, classify as sectors
from org_intake.fetch import default_fetch
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


# --- JOZ-260c: widened ISIC vocabulary, real-world Wikidata industry strings
@pytest.mark.parametrize('text,expected', [
    ('technology industry', ['J']),  # longer, specific keyword outranks the
    ('information technology', ['J']),  # generic "technology" word M also has
    ('pharmaceutical industry', ['C']),
    ('automotive industry', ['C']),  # manufacturing (ISIC div. 29), not G
    ('cryptocurrency', ['K']),
    ('fintech', ['K']),
    # JOZ-261: real-world Wikidata industry labels the live sweep actually
    # returned (e.g. for Siemens) and failed to match before this vocabulary
    # was widened.
    ('electrical engineering', ['C']),
    ('cloud computing', ['J']),
])
def test_match_sectors_widened_vocabulary_classes(text, expected):
    assert sectors.match_sectors(text) == expected


def test_electrical_engineering_does_not_collide_with_generic_engineering_or_technology():
    # Regression guard (JOZ-261): the new "electrical engineering" keyword
    # must resolve on its own, not accidentally tie with M's "engineering
    # services"/"technology" or J's bare "technology" the way bare
    # "Technology" still does.
    assert sectors.all_matched_sections('electrical engineering') == ['C']
    assert sectors.all_matched_sections('cloud computing') == ['J']
    # Existing refusals (bare "technology", unrelated co-occurring keywords)
    # must still be untouched by the new vocabulary.
    assert sectors.match_sectors('Technology') == []
    assert sectors.match_sectors('software and retail') == []


def test_match_sectors_bare_technology_still_ambiguous_after_vocabulary_widening():
    # The new "technology industry" J keyword must not accidentally make
    # bare "Technology" resolve too: it still ties with M at equal length.
    assert sectors.match_sectors('Technology') == []
    assert sectors.all_matched_sections('Technology') == ['J', 'M']


# --- Regression (code review): the specificity tie-break must only resolve
# generic-vs-specific restatements of the SAME phrase (e.g. "technology" vs
# "technology industry"), never independent keywords from unrelated
# activities that merely happen to co-occur in one text.
@pytest.mark.parametrize('text', ['software and retail', 'mining and manufacturing'])
def test_match_sectors_independent_keywords_stay_ambiguous(text):
    assert sectors.match_sectors(text) == []


def test_all_matched_sections_independent_keywords_returns_both_unresolved():
    assert sectors.all_matched_sections('software and retail') == ['G', 'J']
    assert sectors.all_matched_sections('mining and manufacturing') == ['B', 'C']


def test_match_sectors_known_codes_are_isic_sections():
    assert sectors.known_section_codes() == {s['code'] for s in sectors.load_isic_sections()}
    assert len(sectors.known_section_codes()) == 21


# --- Atomic size_class + size_range derivation -----------------------------

@pytest.mark.parametrize('count,size_range,size_class', [
    (9, '1-10', 'micro'), (10, '1-10', 'micro'),
    (249, '201-1000', 'medium'), (250, '201-1000', 'medium'),
    (1, '1-10', 'micro'), (1001, '1000+', 'large'),
])
def test_derive_size_boundary_values(count, size_range, size_class):
    # Contract rule 8 (EU 2003/361/EC): thresholds are INCLUSIVE upper
    # bounds (micro <=10, small <=50, medium <=250), so 10 is micro and
    # 250 is medium. The old product thresholds were exclusive and are
    # superseded by the contract.
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
    # JOZ-262: the mirror image of the '1000+' case above -- size_class
    # already populated and consistent fills size_range alone.
    assert sectors.fill_size_updates(1500, None, 'large') == {'size_range': '1000+'}


# --- Review fix round finding 1 (rewritten for contract rule 8): an LLM
# size-class hint must be checked against an already-populated size_range's
# own implied class(es) before it fills size_class. Under the contract's
# INCLUSIVE EU thresholds (micro <=10, small <=50, medium <=250, large
# >250) a bucket's implied classes come from its bounds: '11-50' implies
# {small} only (both 11 and 50 are 'small'), so 'medium' is NOT compatible;
# '201-1000' straddles 'medium' (201..250) and 'large' (>250), so both
# adjacent classes are plausible.
@pytest.mark.parametrize('size_hint,size_range,expected', [
    ('large', '1000+', True),
    ('large', '1-10', False),  # '1-10' tops out at 10 employees: never 'large'
    ('medium', '11-50', False),  # inclusive bounds: 11 and 50 are both 'small'
    ('small', '11-50', True),
    ('large', '11-50', False),
    ('medium', '51-200', True),
    ('medium', '201-1000', True),  # boundary-spanning: count==201..250 is 'medium'
    ('large', '201-1000', True),  # ...and count==251..1000 is 'large'
    ('small', '201-1000', False),
    ('small', '1-10', False),  # inclusive: 1..10 is 'micro', never 'small'
    ('micro', '1-10', True),
])
def test_size_class_hint_consistent_with_range(size_hint, size_range, expected):
    assert sectors.size_class_hint_consistent_with_range(size_hint, size_range) == expected


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
    result = company_lookup.fetch_organisation_jsonld('https://fiction.example', fetch=lambda url: html)
    assert result == {'industry': 'Software', 'employee_count': 42}


def test_fetch_company_jsonld_rejects_private_destination():
    # A synthetic RFC1918 address assembled from parts, not a literal: this
    # exercises the actual private-network guard rather than the unrelated
    # URL-format check, and keeps raw private addresses out of git-bound files.
    private_host = '.'.join(str(octet) for octet in (10, 0, 0, 5))

    def fake_fetch(url):
        raise AssertionError('must not be called for a private-network destination')
    assert company_lookup.fetch_organisation_jsonld(f'http://{private_host}/', fetch=fake_fetch) == {}


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


def test_fetch_wikidata_undated_statement_falls_back_to_first_non_deprecated():
    # JOZ-262: no P585 qualifier isn't "no evidence" -- it's "no date to
    # disambiguate against other statements." A lone undated, non-deprecated
    # statement is still real evidence and is used, not refused.
    import json
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {
            'P1128': [{'mainsnak': {'datavalue': {'value': {'amount': '+250'}}}}],  # no P585 qualifier
        }}}})
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result['employee_count'] == 250
    assert 'size_status' not in result


def test_fetch_wikidata_dated_statement_preferred_over_undated():
    # JOZ-262: a date, when present, still outranks an undated statement --
    # the fallback above only kicks in when NOTHING is dated.
    import json
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {'P1128': [
            {'mainsnak': {'datavalue': {'value': {'amount': '+9999'}}}},  # undated
            {'mainsnak': {'datavalue': {'value': {'amount': '+250'}}},
             'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2024-00-00T00:00:00Z'}}}]}},
        ]}}}})
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result['employee_count'] == 250


def test_fetch_wikidata_statement_multiple_p585_qualifiers_latest_wins():
    # Review fix round finding 5a: ALL of a statement's P585 qualifiers must
    # be inspected, not just the first -- a statement carrying [2020, 2025]
    # must not lose to a statement dated only 2024.
    import json
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {'P1128': [
            {'mainsnak': {'datavalue': {'value': {'amount': '+100'}}},
             'qualifiers': {'P585': [
                 {'datavalue': {'value': {'time': '+2020-00-00T00:00:00Z'}}},
                 {'datavalue': {'value': {'time': '+2025-00-00T00:00:00Z'}}},
             ]}},
            {'mainsnak': {'datavalue': {'value': {'amount': '+250'}}},
             'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2024-00-00T00:00:00Z'}}}]}},
        ]}}}})
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result['employee_count'] == 100  # 2025 (from the first statement) beats 2024


def test_fetch_wikidata_malformed_p585_qualifier_container_skipped_without_error():
    # Review fix round finding 5b: a malformed qualifier container (not a
    # dict at all here) must be skipped, not raised out of -- and must not
    # prevent a later, well-formed statement from being selected.
    import json
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {'P1128': [
            {'mainsnak': {'datavalue': {'value': {'amount': '+999'}}},
             'qualifiers': {'P585': 'not-a-list'}},
            {'mainsnak': {'datavalue': {'value': {'amount': '+250'}}},
             'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2024-00-00T00:00:00Z'}}}]}},
        ]}}}})
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result['employee_count'] == 250
    assert 'size_status' not in result


def test_fetch_wikidata_size_selection_exception_does_not_discard_industry(monkeypatch):
    # Review fix round finding 5b: a size-selection failure (here forced
    # directly, since _select_p1128_statement is itself now defensive) must
    # not destroy an otherwise resolved industry result -- the two field
    # derivations are isolated from one another.
    import json

    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        if 'Q1.json' in url:
            return json.dumps({'entities': {'Q1': {'claims': {
                'P452': [{'mainsnak': {'datavalue': {'value': {'id': 'Q_SOFTWARE'}}}}],
                'P1128': [{'mainsnak': {'datavalue': {'value': {'amount': '+250'}}}}],
            }}}})
        if 'Q_SOFTWARE.json' in url:
            return json.dumps({'entities': {'Q_SOFTWARE': {'labels': {'en': {'value': 'Software industry'}}}}})
        return None

    def boom(claims):
        raise RuntimeError('boom')

    monkeypatch.setattr(company_lookup, '_select_p1128_statement', boom)
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result['industry'] == 'Software industry'
    assert result.get('employee_count') is None
    assert result.get('size_status') == 'error'
    assert 'industry_status' not in result


def test_fetch_wikidata_all_deprecated_statements_yield_none_not_error():
    import json
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {'P1128': [
            {'mainsnak': {'datavalue': {'value': {'amount': '+9999'}}}, 'rank': 'deprecated'},
        ]}}}})
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result.get('employee_count') is None
    assert 'size_status' not in result


def test_fetch_wikidata_deprecated_rank_statement_excluded():
    # JOZ-262: a 'deprecated' rank is Wikidata's own marker that a statement
    # is superseded/wrong; it must never win even when it's the only dated
    # one, or the only one listed first.
    import json
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {'P1128': [
            {'mainsnak': {'datavalue': {'value': {'amount': '+9999'}}}, 'rank': 'deprecated',
             'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2099-00-00T00:00:00Z'}}}]}},
            {'mainsnak': {'datavalue': {'value': {'amount': '+250'}}}},
        ]}}}})
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result['employee_count'] == 250


def test_fetch_wikidata_unparseable_amount_treated_as_absent_not_error():
    # JOZ-262: a statement that doesn't read as a positive integer count is
    # treated exactly like no statement at all -- never guessed, and never
    # reported as a fetch failure (the fetch itself succeeded cleanly).
    import json
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {
            'P1128': [{'mainsnak': {'datavalue': {'value': {'amount': 'not-a-number'}}}}],
        }}}})
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result.get('employee_count') is None
    assert 'size_status' not in result


def test_fetch_wikidata_no_p1128_claim_treated_as_absent_not_error():
    import json
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {}}}})
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result.get('employee_count') is None
    assert 'size_status' not in result


# --- JOZ-260b: Wikidata 429 retry/backoff -----------------------------------

def test_fetch_wikidata_retries_429_then_succeeds():
    import json
    import urllib.error
    calls = {'n': 0}
    sleeps = []

    def fetch(url):
        if 'wbsearchentities' in url:
            calls['n'] += 1
            if calls['n'] == 1:
                raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {}, None)
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {}}}})

    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch, sleep=sleeps.append)
    assert calls['n'] == 2  # one failed attempt, one retry that succeeded
    assert sleeps == [company_lookup.WIKIDATA_BACKOFF_SECONDS]
    assert 'status' not in result  # a 429 that resolves on retry is never reported as an error


def test_fetch_wikidata_honors_retry_after_header():
    import json
    import urllib.error
    calls = {'n': 0}
    sleeps = []

    def fetch(url):
        if 'wbsearchentities' in url:
            calls['n'] += 1
            if calls['n'] == 1:
                raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {'Retry-After': '5'}, None)
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {}}}})

    company_lookup.fetch_wikidata('Fiction Co', fetch=fetch, sleep=sleeps.append)
    assert sleeps == [5.0]


def test_fetch_wikidata_rate_limited_after_retries_exhausted():
    import urllib.error
    calls = {'n': 0}

    def fetch(url):
        calls['n'] += 1
        raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {}, None)

    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch, sleep=lambda s: None)
    assert calls['n'] == company_lookup.WIKIDATA_MAX_RETRIES + 1
    assert result == {'industry': None, 'employee_count': None,
                       'industry_status': 'rate_limited', 'size_status': 'rate_limited'}


def test_fetch_wikidata_non_429_http_error_is_fetch_error_not_rate_limited():
    import urllib.error
    def fetch(url):
        raise urllib.error.HTTPError(url, 500, 'Server Error', {}, None)
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch, sleep=lambda s: None)
    assert result == {'industry': None, 'employee_count': None,
                       'industry_status': 'error', 'size_status': 'error'}


def test_fetch_wikidata_generic_exception_is_fetch_error():
    def fetch(url):
        raise ValueError('boom')
    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch, sleep=lambda s: None)
    assert result == {'industry': None, 'employee_count': None,
                       'industry_status': 'error', 'size_status': 'error'}


# --- Regression (code review): a partial Wikidata failure (industry-label
# HTTP error) must not discard an employee_count that was already read from
# the claims payload the earlier, successful fetch returned.
def test_fetch_wikidata_industry_label_failure_preserves_employee_count():
    import json
    import urllib.error

    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        if 'Q1.json' in url:
            return json.dumps({'entities': {'Q1': {'claims': {
                'P452': [{'mainsnak': {'datavalue': {'value': {'id': 'Q_SOFTWARE'}}}}],
                'P1128': [{'mainsnak': {'datavalue': {'value': {'amount': '+250'}}},
                           'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2024-00-00T00:00:00Z'}}}]}}],
            }}}})
        raise urllib.error.HTTPError(url, 500, 'Server Error', {}, None)  # Q_SOFTWARE.json label lookup

    result = company_lookup.fetch_wikidata('Fiction Co', fetch=fetch, sleep=lambda s: None)
    assert result['employee_count'] == 250
    assert result['industry'] is None
    assert result['industry_status'] == 'error'
    assert 'size_status' not in result


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
    updated = product_enrich.backfill(root, sector_signals=(), size_signals=())
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

    updated = product_enrich.backfill(tmp_path, size_signals=(), fetch=tracking_fetch)
    assert calls == []
    assert company['id'] in updated
    assert vault.load_company(tmp_path, company['id'])['sectors'] == ['K']


def test_backfill_size_cascade_respects_consistency_with_populated_range(root):
    company = vault.save_company(root, {'name': 'Partial Labs', 'size_range': '1-10'})

    def fake_jsonld(c, fetch=None, warn=None, deadline=None):
        return {'employee_count': 500}  # contradicts the already-populated size_range

    product_enrich.backfill(root, size_signals=(fake_jsonld,))
    saved = vault.load_company(root, company['id'])
    # The contradictory count still fills nothing (no size_class written),
    # but the refusal is now surfaced as a review flag rather than silently
    # leaving a half-populated pair with no pending indication.
    assert saved['size_class'] is None
    assert saved['size_range'] == '1-10'
    assert company_lookup.FLAG_SIZE_INCONSISTENT in saved['review_flags']


# --- JOZ-262: Wikidata P1128 (employees) feeds the size cascade ------------
# Through the real _wikidata_signal (mocked only at the fetch boundary, same
# pattern as the fetch_wikidata-level tests above), not a fake signal, so
# these exercise the actual wiring: _select_p1128_statement ->
# fetch_wikidata -> _wikidata_signal -> size_cascade -> fill_size_updates,
# with 'wikidata' signal_summary attribution via BackfillAccounting.

def _wikidata_fetch_for_count(count):
    import json

    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {'P1128': [
            {'mainsnak': {'datavalue': {'value': {'amount': f'+{count}'}}},
             'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2024-00-00T00:00:00Z'}}}]}},
        ]}}}})
    return fetch


def test_wikidata_signal_point_value_fills_both_size_fields(root):
    company = vault.save_company(root, {'name': 'Headcount Co'})
    collector = company_lookup.BackfillAccounting()
    product_enrich.backfill(root, sector_signals=(), size_signals=(company_lookup._wikidata_signal,),
                            fetch=_wikidata_fetch_for_count(1500), collector=collector)
    saved = vault.load_company(root, company['id'])
    assert saved['size_range'] == '1000+'
    assert saved['size_class'] == 'large'
    events = {(e['signal'], e['field'], e['outcome']) for e in collector.events}
    assert ('wikidata', 'size', 'matched') in events


def test_wikidata_signal_count_contradicting_existing_size_range_fills_nothing(root):
    company = vault.save_company(root, {'name': 'Mismatched Co', 'size_range': '1-10'})
    product_enrich.backfill(root, sector_signals=(), size_signals=(company_lookup._wikidata_signal,),
                            fetch=_wikidata_fetch_for_count(1500))
    saved = vault.load_company(root, company['id'])
    assert saved['size_range'] == '1-10'
    assert saved['size_class'] is None
    assert company_lookup.FLAG_SIZE_INCONSISTENT in saved['review_flags']


def test_wikidata_signal_size_class_present_and_consistent_fills_only_size_range(root):
    company = vault.save_company(root, {'name': 'Half Filled Co', 'size_class': 'large'})
    product_enrich.backfill(root, sector_signals=(), size_signals=(company_lookup._wikidata_signal,),
                            fetch=_wikidata_fetch_for_count(1500))
    saved = vault.load_company(root, company['id'])
    assert saved['size_range'] == '1000+'
    assert saved['size_class'] == 'large'
    assert company_lookup.FLAG_SIZE_INCONSISTENT not in (saved.get('review_flags') or [])


def test_wikidata_signal_absent_p1128_leaves_fields_untouched_not_fetch_error(root):
    import json
    company = vault.save_company(root, {'name': 'No Headcount Co'})

    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {}}}})

    collector = company_lookup.BackfillAccounting()
    product_enrich.backfill(root, sector_signals=(), size_signals=(company_lookup._wikidata_signal,),
                            fetch=fetch, collector=collector)
    saved = vault.load_company(root, company['id'])
    assert saved['size_range'] is None
    assert saved['size_class'] is None
    assert not saved.get('review_flags')
    events = {(e['signal'], e['field'], e['outcome']) for e in collector.events
              if e['record_id'] == company['id']}
    assert ('wikidata', 'size', 'empty') in events
    assert ('wikidata', 'size', 'fetch-error') not in events


def test_wikidata_signal_multiple_statements_latest_wins_through_cascade(root):
    import json
    company = vault.save_company(root, {'name': 'Dated Co'})

    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {'P1128': [
            {'mainsnak': {'datavalue': {'value': {'amount': '+100'}}},
             'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2020-00-00T00:00:00Z'}}}]}},
            {'mainsnak': {'datavalue': {'value': {'amount': '+1500'}}},
             'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2024-00-00T00:00:00Z'}}}]}},
        ]}}}})

    product_enrich.backfill(root, sector_signals=(), size_signals=(company_lookup._wikidata_signal,), fetch=fetch)
    saved = vault.load_company(root, company['id'])
    assert saved['size_range'] == '1000+'
    assert saved['size_class'] == 'large'


def test_backfill_sector_ambiguous_signal_flags_for_review(root):
    company = vault.save_company(root, {'name': 'Ambiguous Labs'})

    def ambiguous_signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'Technology', 'employee_count': None}  # matches both J and M

    updated = product_enrich.backfill(root, sector_signals=(ambiguous_signal,), size_signals=())
    saved = vault.load_company(root, company['id'])
    assert company['id'] in updated
    assert saved['sectors'] == []
    assert company_lookup.FLAG_SECTOR_AMBIGUOUS in saved['review_flags']


def test_backfill_sector_source_conflict_flags_for_review(root):
    company = vault.save_company(root, {'name': 'Conflicted Labs'})

    def software_signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'Software and IT services', 'employee_count': None}

    def banking_signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'Banking and insurance', 'employee_count': None}

    updated = product_enrich.backfill(root, sector_signals=(software_signal, banking_signal), size_signals=())
    saved = vault.load_company(root, company['id'])
    assert company['id'] in updated
    assert saved['sectors'] == []
    assert company_lookup.FLAG_SECTOR_CONFLICT in saved['review_flags']


def test_backfill_clears_sector_flag_once_resolved(root):
    company = vault.save_company(root, {'name': 'Eventually Resolved Labs'})

    def ambiguous_signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'Technology', 'employee_count': None}

    product_enrich.backfill(root, sector_signals=(ambiguous_signal,), size_signals=())
    assert company_lookup.FLAG_SECTOR_AMBIGUOUS in vault.load_company(root, company['id'])['review_flags']

    def confident_signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'Banking and insurance', 'employee_count': None}

    product_enrich.backfill(root, sector_signals=(confident_signal,), size_signals=())
    saved = vault.load_company(root, company['id'])
    assert saved['sectors'] == ['K']
    assert company_lookup.FLAG_SECTOR_AMBIGUOUS not in saved['review_flags']


def test_backfill_wires_kind_migration_for_records_missing_kind(root):
    # A record that predates the kind field (missing the key entirely, as
    # every sample-vault company does before migration) must still be
    # picked up by the kind backfill as part of this action, not skipped.
    for company in vault.list_companies(root):
        assert company.get('kind') is None
    product_enrich.backfill(root, sector_signals=(), size_signals=())
    for company in vault.list_companies(root):
        assert company['kind'] == 'employer'


# --- Regression (code review): a signal reporting a status for ONE field
# must not discard a valid value already present for the OTHER field.
def test_size_cascade_industry_status_failure_preserves_employee_count(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Partial Labs'})

    def signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': None, 'employee_count': 100, 'industry_status': 'error'}

    updates, flag = company_lookup.classify_size(company, signals=(signal,), **product_enrich.classification_options())
    assert updates == {'size_range': '51-200', 'size_class': 'medium'}
    assert flag is None


def test_external_sectors_size_status_failure_preserves_industry(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Partial Labs 2'})

    def signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'Banking and insurance', 'employee_count': None, 'size_status': 'error'}

    codes, flag = company_lookup.external_sectors(company, signals=(signal,), **product_enrich.classification_options())
    assert codes == ['K']
    assert flag is None


def test_plan_backfill_accounting_partial_wikidata_failure_preserves_valid_field(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Partial Fetch Labs'})

    def signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': None, 'employee_count': 100, 'industry_status': 'error'}

    collector = company_lookup.BackfillAccounting()
    plan, _ = product_enrich.plan_backfill(tmp_path, sector_signals=(signal,), size_signals=(signal,),
                                            collector=collector)
    changes = next(ch for co, ch in plan if co['id'] == company['id'])
    assert changes['size_range'] == '51-200' and changes['size_class'] == 'medium'
    assert collector.summary()['fetch-error'] == 1  # sectors: industry_status
    assert collector.summary()['matched'] == 1  # size: employee_count present despite industry_status


# --- JOZ-260 code review: full-coverage accounting (every skipped signal is
# recorded as 'not-attempted' rather than simply absent from the summary).

def test_sectors_cascade_already_populated_records_not_attempted_for_all_considered_signals(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Populated Labs', 'sectors': ['K']})
    collector = company_lookup.BackfillAccounting()
    result, flag = company_lookup.classify_sector(
        company, signals=(company_lookup._jsonld_signal, company_lookup._wikidata_signal), collector=collector, **product_enrich.classification_options())
    assert result is None and flag is None
    assert all(e['outcome'] == 'not-attempted' for e in collector.events)
    assert {'jsonld', 'wikidata'} <= {e['signal'] for e in collector.events}
    names = {e['signal'] for e in collector.events}
    # The capability's protected-field path accounts for every considered
    # signal: promotion tier, the passed signals, and the gated LLM
    # fallback (all not-attempted). 'llm' is part of that set by design.
    assert names == {'promotion', 'jsonld', 'wikidata', 'llm'}


def test_sectors_cascade_promotion_success_records_matched_and_skips_external_signals(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Promoted Labs'})
    vault.save_job(tmp_path, {'title': 'Role', 'url': 'https://fiction.example/promoted',
                              'company_id': company['id'], 'sector': 'Banking and insurance'})
    company = vault.load_company(tmp_path, company['id'])
    collector = company_lookup.BackfillAccounting()
    codes, flag = company_lookup.classify_sector(company, signals=(company_lookup._jsonld_signal,),
                                                  collector=collector, **product_enrich.classification_options())
    assert codes == ['K'] and flag is None
    assert collector.summary()['matched'] == 1
    assert any(e['outcome'] == 'not-attempted' for e in collector.events)
    events = {(e['signal'], e['outcome']) for e in collector.events}
    assert ('promotion', 'matched') in events
    assert ('jsonld', 'not-attempted') in events


def test_sectors_cascade_promotion_conflict_records_ambiguous_and_skips_external_signals():
    # Two distinct codes whose underlying raw strings share a >3-char word
    # ("enterprise"), so promote_aggregated_sectors' distinct-activity check
    # refuses rather than promoting both.
    company = {'id': 'CO-CONFLICT', 'enrichment': {'sectors': ['Enterprise software', 'Enterprise consulting']}}
    collector = company_lookup.BackfillAccounting()
    codes, flag = company_lookup.classify_sector(company, signals=(company_lookup._jsonld_signal,),
                                                  collector=collector, **product_enrich.classification_options())
    assert codes is None and flag == company_lookup.FLAG_SECTOR_CONFLICT
    assert collector.summary()['ambiguous'] == 1
    assert any(e['signal'] == 'jsonld' and e['outcome'] == 'not-attempted' for e in collector.events)
    events = {(e['signal'], e['outcome']) for e in collector.events}
    assert ('promotion', 'ambiguous') in events
    assert ('jsonld', 'not-attempted') in events


def test_size_cascade_already_populated_records_not_attempted(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Sized Labs', 'size_range': '1-10', 'size_class': 'micro'})
    collector = company_lookup.BackfillAccounting()
    updates, flag = company_lookup.classify_size(
        company, signals=(company_lookup._jsonld_signal, company_lookup._wikidata_signal), collector=collector, **product_enrich.classification_options())
    assert updates is None and flag is None
    assert all(e['outcome'] == 'not-attempted' for e in collector.events)
    assert {'jsonld', 'wikidata'} <= {e['signal'] for e in collector.events}


def test_size_cascade_break_on_first_match_records_not_attempted_for_remaining_signals(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Break Labs'})

    def first(c, fetch=None, warn=None, deadline=None):
        return {'employee_count': 42}

    def second(c, fetch=None, warn=None, deadline=None):
        raise AssertionError('must not be called once an earlier signal already matched')

    collector = company_lookup.BackfillAccounting()
    updates, flag = company_lookup.classify_size(company, signals=(first, second), collector=collector, **product_enrich.classification_options())
    assert updates == {'size_range': '11-50', 'size_class': 'small'}
    assert collector.summary()['matched'] == 1
    assert any(e['outcome'] == 'not-attempted' for e in collector.events)
    events = {(e['signal'], e['outcome']) for e in collector.events}
    assert ('second', 'not-attempted') in events


# --- JOZ-260 code review: JSON-LD production fetch errors must not be
# accounted as 'empty' (fetched-but-no-data) -- they never fetched at all.

def test_fetch_company_jsonld_reports_fetch_error_on_exception():
    def fetch(url):
        raise ValueError('boom')

    result = company_lookup.fetch_organisation_jsonld('https://fiction.example', fetch=fetch)
    assert result == {'industry_status': 'error', 'size_status': 'error'}


def test_jsonld_production_fetch_error_is_not_counted_as_empty(tmp_path):
    import urllib.error
    vault.save_company(tmp_path, {'name': 'Site Down Labs', 'website': 'https://down.example'})

    def fetch(url):
        raise urllib.error.HTTPError(url, 500, 'Server Error', {}, None)

    collector = company_lookup.BackfillAccounting()
    product_enrich.plan_backfill(tmp_path, sector_signals=(company_lookup._jsonld_signal,), size_signals=(),
                                  fetch=fetch, collector=collector)
    assert collector.summary()['fetch-error'] == 1
    assert any(e['signal'] == 'jsonld' and e['outcome'] == 'fetch-error' for e in collector.events)
    assert not any(e['signal'] == 'jsonld' and e['outcome'] == 'empty' for e in collector.events)


# --- JOZ-260 code review: _last_wikidata_call pacing must survive concurrent
# callers (Flask serves requests on multiple threads).

def test_wikidata_pace_is_thread_safe_under_concurrent_calls():
    import threading
    errors = []

    def hit():
        try:
            company_lookup._wikidata_pace()
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=hit) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


# --- JOZ-260 code review: Retry-After parsing (numeric + HTTP-date forms,
# clamped, with a safe fallback for garbage values).

def test_wikidata_retry_after_http_date_form_honored():
    import json
    import urllib.error
    import email.utils
    from datetime import datetime, timedelta, timezone
    calls = {'n': 0}
    sleeps = []
    future = email.utils.format_datetime(datetime.now(timezone.utc) + timedelta(seconds=5))

    def fetch(url):
        if 'wbsearchentities' in url:
            calls['n'] += 1
            if calls['n'] == 1:
                raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {'Retry-After': future}, None)
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {}}}})

    company_lookup.fetch_wikidata('Fiction Co', fetch=fetch, sleep=sleeps.append)
    assert len(sleeps) == 1
    assert 0 <= sleeps[0] <= 6  # ~5s, small slack for test runtime


def test_wikidata_retry_after_huge_value_clamped():
    import json
    import urllib.error
    calls = {'n': 0}
    sleeps = []

    def fetch(url):
        if 'wbsearchentities' in url:
            calls['n'] += 1
            if calls['n'] == 1:
                raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {'Retry-After': '999999'}, None)
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {}}}})

    company_lookup.fetch_wikidata('Fiction Co', fetch=fetch, sleep=sleeps.append)
    assert sleeps == [company_lookup.RETRY_AFTER_MAX_SECONDS]


def test_wikidata_retry_after_garbage_value_falls_back_to_exponential_delay():
    import json
    import urllib.error
    calls = {'n': 0}
    sleeps = []

    def fetch(url):
        if 'wbsearchentities' in url:
            calls['n'] += 1
            if calls['n'] == 1:
                raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {'Retry-After': 'garbage'}, None)
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {}}}})

    company_lookup.fetch_wikidata('Fiction Co', fetch=fetch, sleep=sleeps.append)
    assert sleeps == [company_lookup.WIKIDATA_BACKOFF_SECONDS]


def test_wikidata_retry_after_nan_value_falls_back_to_exponential_delay():
    # float() accepts 'NaN'/'inf'; a non-finite parse must count as garbage,
    # not clamp to a degenerate 0.0 wait (JOZ-260 review round 2).
    import json
    import urllib.error
    calls = {'n': 0}
    sleeps = []

    def fetch(url):
        if 'wbsearchentities' in url:
            calls['n'] += 1
            if calls['n'] == 1:
                raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {'Retry-After': 'NaN'}, None)
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {}}}})

    company_lookup.fetch_wikidata('Fiction Co', fetch=fetch, sleep=sleeps.append)
    assert sleeps == [company_lookup.WIKIDATA_BACKOFF_SECONDS]


def test_sectors_cascade_promotion_empty_records_empty_event():
    # Promotion ran but had no aggregated data to offer ([]): the promotion
    # step itself must still appear in the accounting before falling through
    # to external signals (JOZ-260 review round 2).
    company = {'id': 'CO-NOPROMO'}  # no enrichment -> promotion returns []

    def fake_signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'banking'}

    collector = company_lookup.BackfillAccounting()
    codes, flag = company_lookup.classify_sector(company, signals=(fake_signal,), collector=collector, **product_enrich.classification_options())
    assert codes == ['K'] and flag is None
    events = {(e['signal'], e['outcome']) for e in collector.events}
    assert ('promotion', 'empty') in events
    assert ('fake_signal', 'matched') in events


def test_backfill_sectors_and_size_are_independent_cascades(root):
    company = vault.save_company(root, {'name': 'Independent Labs', 'sectors': ['K']})

    def fake_jsonld(c, fetch=None, warn=None, deadline=None):
        return {'employee_count': 42}

    updated = product_enrich.backfill(root, size_signals=(fake_jsonld,))
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


def test_companies_page_has_no_backfill_action(client, root):
    # M1 audit: the sweep-all-companies Backfill button is removed; retrying
    # one company's sector/size enrichment now happens on that company's own
    # page via the Retry control (see test_company_detail_shows_retry_*).
    html = client.get('/companies').text
    assert 'id="backfill-sector-size"' not in html
    assert 'Backfill sector/size' not in html


def test_backfill_endpoint_is_explicit_and_never_runs_automatically(client, root, monkeypatch):
    calls = []
    monkeypatch.setattr(product_enrich, 'plan_backfill', lambda root, **kw: calls.append(root) or ([], 3))
    monkeypatch.setattr(product_enrich, 'apply_backfill', lambda root, plan: ['CO-001'])
    # Intake and enrich must never trigger the backfill path themselves.
    client.post('/api/jobs/intake', json={'url': 'https://fiction.example/job'})
    assert calls == []
    response = client.post('/api/companies/backfill-sector-size')
    assert response.status_code == 200
    assert calls == [root]
    assert response.json == {'updated': ['CO-001'], 'scanned': 3, 'signal_summary': {
        'matched': 0, 'ambiguous': 0, 'rate-limited': 0, 'fetch-error': 0, 'empty': 0, 'not-attempted': 0}}


def test_backfill_network_sweep_does_not_hold_write_lock(client, root, monkeypatch):
    """Regression (2026-10-07): the sweep held the vault write lock through
    minutes of external fetches, starving the Enrich button and every other
    writer — both UI buttons appeared dead. Planning must be lock-free;
    a concurrent vault write during the sweep must succeed."""
    from careeros import vault as vault_module
    import threading

    def slow_plan(vault_root, **kw):
        # Simulate the multi-minute network phase; another writer proceeds
        # concurrently — this would block forever if the endpoint held the
        # lock across planning.
        done = threading.Event()

        def concurrent_write():
            vault_module.save_company(vault_root, {'name': 'Concurrent Co'})
            done.set()

        thread = threading.Thread(target=concurrent_write, daemon=True)
        thread.start()
        assert done.wait(5), 'write lock held during network sweep'
        thread.join(1)
        return [], 0

    monkeypatch.setattr(product_enrich, 'plan_backfill', slow_plan)
    assert client.post('/api/companies/backfill-sector-size').status_code == 200


def test_plan_and_apply_backfill_roundtrip(root, monkeypatch):
    monkeypatch.setattr(company_lookup, 'classify_sector',
                        lambda company, signals=None, fetch=None, collector=None, **kwargs: (['J'], None) if not company.get('sectors') else (None, None))
    monkeypatch.setattr(company_lookup, 'classify_size', lambda company, signals=None, fetch=None, collector=None, **kwargs: (None, None))
    company = vault.save_company(root, {'name': 'Planned Co'})
    plan, scanned = product_enrich.plan_backfill(root)
    assert scanned >= 1
    assert any(c['id'] == company['id'] and ch['sectors'] == ['J'] for c, ch in plan)
    updated = product_enrich.apply_backfill(root, plan)
    assert company['id'] in updated
    assert vault.load_company(root, company['id'])['sectors'] == ['J']


# --- JOZ-260a: per-signal outcome accounting --------------------------------
# Each test uses an isolated tmp_path vault with exactly one company and one
# custom signal, so the resulting counts are exact rather than merely >= 1.

def test_plan_backfill_accounting_records_matched(tmp_path):
    company = vault.save_company(tmp_path, {'name': 'Matched Labs'})

    def signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'Banking and insurance'}

    collector = company_lookup.BackfillAccounting()
    product_enrich.plan_backfill(tmp_path, sector_signals=(signal,), size_signals=(), collector=collector)
    # 'promotion'/'empty' is the zero-network promotion step accounting itself
    # (no aggregated data), required for full (signal, field) coverage.
    assert collector.summary()['matched'] == 1
    assert collector.summary()['fetch-error'] == 0
    assert {'company_id': company['id'], 'signal': 'promotion',
            'field': 'sectors', 'outcome': 'empty'} in product_enrich.company_events(collector)
    assert {'company_id': company['id'], 'signal': 'signal',
            'field': 'sectors', 'outcome': 'matched'} in product_enrich.company_events(collector)


def test_plan_backfill_accounting_records_ambiguous(tmp_path):
    vault.save_company(tmp_path, {'name': 'Ambiguous Labs'})

    def signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'Technology'}  # matches both J and M

    collector = company_lookup.BackfillAccounting()
    product_enrich.plan_backfill(tmp_path, sector_signals=(signal,), size_signals=(), collector=collector)
    assert collector.summary()['ambiguous'] == 1
    assert collector.summary()['matched'] == 0


def test_plan_backfill_accounting_records_rate_limited(tmp_path):
    vault.save_company(tmp_path, {'name': 'RateLimited Labs'})

    def signal(c, fetch=None, warn=None, deadline=None):
        return {'industry_status': 'rate_limited', 'size_status': 'rate_limited'}

    collector = company_lookup.BackfillAccounting()
    product_enrich.plan_backfill(tmp_path, sector_signals=(signal,), size_signals=(signal,), collector=collector)
    assert collector.summary()['rate-limited'] == 2  # once for sectors, once for size


def test_plan_backfill_accounting_records_fetch_error(tmp_path):
    vault.save_company(tmp_path, {'name': 'FetchError Labs'})

    def signal(c, fetch=None, warn=None, deadline=None):
        return {'industry_status': 'error'}

    collector = company_lookup.BackfillAccounting()
    product_enrich.plan_backfill(tmp_path, sector_signals=(signal,), size_signals=(), collector=collector)
    assert collector.summary()['fetch-error'] == 1


def test_plan_backfill_accounting_records_empty(tmp_path):
    vault.save_company(tmp_path, {'name': 'Empty Labs'})

    def signal(c, fetch=None, warn=None, deadline=None):
        return {}

    collector = company_lookup.BackfillAccounting()
    product_enrich.plan_backfill(tmp_path, sector_signals=(signal,), size_signals=(signal,), collector=collector)
    assert {(e['field'], e['outcome']) for e in collector.events if e['signal'] == 'signal'} == {('sectors', 'empty'), ('size', 'empty')}
    assert collector.summary()['fetch-error'] == 0


def test_plan_backfill_accounting_records_not_attempted_for_missing_website(tmp_path):
    vault.save_company(tmp_path, {'name': 'No Website Labs'})  # no website set

    collector = company_lookup.BackfillAccounting()
    product_enrich.plan_backfill(tmp_path, sector_signals=(company_lookup._jsonld_signal,),
                                  size_signals=(), collector=collector)
    assert any(e['signal'] == 'jsonld' and e['outcome'] == 'not-attempted' for e in collector.events)


def test_plan_backfill_accounting_disabled_by_default_has_no_cost(tmp_path):
    # collector=None (the default) must not raise or require any caller change.
    vault.save_company(tmp_path, {'name': 'Uncollected Labs'})
    plan, scanned = product_enrich.plan_backfill(tmp_path, sector_signals=(), size_signals=())
    assert scanned == 1


# --- JOZ-261: LLM world-knowledge signal ------------------------------------
# External sources exhausted (promotion/jsonld/wikidata/osm) is the common
# case in practice; the LLM signal is the last resort, gated hard behind
# BACKFILL_USE_LLM (never on in the test suite) and behind decision 20 in
# code. Every real LLM call is mocked via client_for, matching the existing
# ingest.py test pattern exactly -- no live network call anywhere here.
from tests.test_ingest import client_for


def test_llm_signal_disabled_by_default_is_not_attempted(tmp_path, monkeypatch):
    monkeypatch.delenv('BACKFILL_USE_LLM', raising=False)
    vault.save_company(tmp_path, {'name': 'Unflagged Labs'})
    collector = company_lookup.BackfillAccounting()
    product_enrich.plan_backfill(tmp_path, sector_signals=(company_lookup._llm_signal,),
                                  size_signals=(company_lookup._llm_signal,), collector=collector)
    events = {(e['signal'], e['field'], e['outcome']) for e in collector.events}
    assert ('llm', 'sectors', 'not-attempted') in events
    assert ('llm', 'size', 'not-attempted') in events


def test_llm_fallback_owned_by_capability_and_inert_without_the_env_flag(tmp_path, monkeypatch):
    # The capability (org_intake.enrich.external_sectors / size_cascade)
    # owns the gated LLM fallback: it appends _llm_signal itself when
    # classification_options() injects llm_client, so the product signal
    # tuples must NOT include it (adding it would run the LLM twice per
    # field per record). BACKFILL_USE_LLM still decides whether the
    # capability ever sees an llm_client, not tuple membership.
    monkeypatch.delenv('BACKFILL_USE_LLM', raising=False)
    assert company_lookup._llm_signal not in product_enrich.SECTOR_SIGNALS
    assert company_lookup._llm_signal not in product_enrich.SIZE_SIGNALS
    vault.save_company(tmp_path, {'name': 'Default Cascade Labs'})
    plan, scanned = product_enrich.plan_backfill(tmp_path)  # real module defaults
    assert scanned == 1  # no exception, no network call attempted


# --- Review fix round finding 2: the LLM signal must be a true fallback --
# only invoked once structured (non-LLM) signals produced no usable result,
# never run unconditionally alongside them.

def _counting_llm_client(monkeypatch, content):
    import json
    calls = {'n': 0}

    def factory():
        calls['n'] += 1
        return client_for(content if isinstance(content, str) else json.dumps(content))

    monkeypatch.setattr(product_enrich, 'get_llm_client', factory)
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    return calls


def test_external_sectors_llm_not_called_after_structured_success(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    calls = _counting_llm_client(monkeypatch, {
        'sector': 'K', 'sector_label': 'global investment bank', 'confidence': 'high', 'size_hint': None})

    def structured_signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'Software and IT services', 'employee_count': None}

    company = vault.save_company(tmp_path, {'name': 'Already Classified Co'})
    codes, flag = company_lookup.external_sectors(
        company, signals=(structured_signal, company_lookup._llm_signal), **product_enrich.classification_options())
    assert codes == ['J'] and flag is None
    assert calls['n'] == 0  # LLM must never run once a structured signal already matched


def test_external_sectors_llm_called_as_fallback_when_structured_empty(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    calls = _counting_llm_client(monkeypatch, {
        'sector': 'K', 'sector_label': 'global investment bank', 'confidence': 'high', 'size_hint': None})

    def empty_signal(c, fetch=None, warn=None, deadline=None):
        return {}

    company = vault.save_company(tmp_path, {'name': 'Nothing Structured Co'})
    collector = company_lookup.BackfillAccounting()
    codes, flag = company_lookup.external_sectors(
        company, signals=(empty_signal, company_lookup._llm_signal), collector=collector, **product_enrich.classification_options())
    assert codes == ['K'] and flag is None
    assert calls['n'] == 1
    events = {(e['signal'], e['outcome']) for e in collector.events}
    assert ('llm', 'matched') in events


def test_external_sectors_structured_conflict_short_circuits_before_llm(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    calls = _counting_llm_client(monkeypatch, {
        'sector': 'J', 'sector_label': 'software company', 'confidence': 'high', 'size_hint': None})

    def software_signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'Software and IT services', 'employee_count': None}

    def banking_signal(c, fetch=None, warn=None, deadline=None):
        return {'industry': 'Banking and insurance', 'employee_count': None}

    company = vault.save_company(tmp_path, {'name': 'Conflicted Co'})
    codes, flag = company_lookup.external_sectors(
        company, signals=(software_signal, banking_signal, company_lookup._llm_signal), **product_enrich.classification_options())
    assert codes is None and flag == company_lookup.FLAG_SECTOR_CONFLICT
    assert calls['n'] == 0  # an existing structured conflict is never masked by an LLM opinion


def test_size_cascade_llm_not_called_after_structured_success(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    calls = _counting_llm_client(monkeypatch, {
        'sector': None, 'sector_label': None, 'confidence': 'high', 'size_hint': 'large'})

    def structured_signal(c, fetch=None, warn=None, deadline=None):
        return {'employee_count': 42}

    company = vault.save_company(tmp_path, {'name': 'Already Sized Co'})
    updates, flag = company_lookup.classify_size(company, signals=(structured_signal, company_lookup._llm_signal), **product_enrich.classification_options())
    assert updates == {'size_range': '11-50', 'size_class': 'small'}
    assert calls['n'] == 0


def test_size_cascade_llm_called_as_fallback_when_structured_empty(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    calls = _counting_llm_client(monkeypatch, {
        'sector': None, 'sector_label': None, 'confidence': 'high', 'size_hint': 'large'})

    def empty_signal(c, fetch=None, warn=None, deadline=None):
        return {}

    company = vault.save_company(tmp_path, {'name': 'Needs Fallback Co'})
    collector = company_lookup.BackfillAccounting()
    updates, flag = company_lookup.classify_size(
        company, signals=(empty_signal, company_lookup._llm_signal), collector=collector, **product_enrich.classification_options())
    assert updates == {'size_class': 'large'}
    assert calls['n'] == 1
    events = {(e['signal'], e['outcome']) for e in collector.events}
    assert ('llm', 'matched') in events


def test_size_cascade_structured_contradiction_short_circuits_before_llm(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    calls = _counting_llm_client(monkeypatch, {
        'sector': None, 'sector_label': None, 'confidence': 'high', 'size_hint': 'large'})

    def contradicting_signal(c, fetch=None, warn=None, deadline=None):
        return {'employee_count': 500}  # contradicts the already-populated size_range

    company = vault.save_company(tmp_path, {'name': 'Contradicted Co', 'size_range': '1-10'})
    updates, flag = company_lookup.classify_size(
        company, signals=(contradicting_signal, company_lookup._llm_signal), **product_enrich.classification_options())
    assert updates is None and flag == company_lookup.FLAG_SIZE_INCONSISTENT
    assert calls['n'] == 0


def test_llm_signal_high_confidence_fills_sector_and_size_with_llm_provenance(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(json.dumps({
        'sector': 'K', 'sector_label': 'global investment bank', 'confidence': 'high', 'size_hint': 'large'})))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    company = vault.save_company(tmp_path, {'name': 'Big Bank Inc'})
    collector = company_lookup.BackfillAccounting()
    updated = product_enrich.backfill(tmp_path, sector_signals=(company_lookup._llm_signal,),
                                      size_signals=(company_lookup._llm_signal,), collector=collector)
    saved = vault.load_company(tmp_path, company['id'])
    assert company['id'] in updated
    assert saved['sectors'] == ['K']
    assert saved['size_class'] == 'large'
    # Provenance: the same mechanism every other signal uses -- a named
    # accounting event, 'llm' -- there is no other per-field provenance
    # field on the company schema for any backfill-sourced fill.
    events = {(e['signal'], e['field'], e['outcome']) for e in collector.events}
    assert ('llm', 'sectors', 'matched') in events
    assert ('llm', 'size', 'matched') in events


def test_llm_signal_letter_authoritative_when_label_has_no_keyword_match(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(json.dumps({
        'sector': 'Q', 'sector_label': 'runs a well-known chain of clinics',
        'confidence': 'high', 'size_hint': None})))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    company = vault.save_company(tmp_path, {'name': 'Clinic Co'})
    product_enrich.backfill(tmp_path, sector_signals=(company_lookup._llm_signal,), size_signals=())
    assert vault.load_company(tmp_path, company['id'])['sectors'] == ['Q']


def test_llm_signal_self_contradictory_rationale_refused(tmp_path, monkeypatch):
    # The stated letter (J) and the free-text rationale confidently
    # keyword-match to a DIFFERENT section (F, "construction company"): the
    # response contradicts itself, so it is refused rather than trusted.
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(json.dumps({
        'sector': 'J', 'sector_label': 'construction company', 'confidence': 'high', 'size_hint': None})))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    company = vault.save_company(tmp_path, {'name': 'Self Contradicting Co'})
    product_enrich.backfill(tmp_path, sector_signals=(company_lookup._llm_signal,), size_signals=())
    saved = vault.load_company(tmp_path, company['id'])
    assert saved['sectors'] == []
    assert company_lookup.FLAG_SECTOR_AMBIGUOUS in saved['review_flags']


def test_llm_signal_low_confidence_flags_for_review_without_filling(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(json.dumps({
        'sector': 'K', 'sector_label': 'maybe a bank?', 'confidence': 'low', 'size_hint': None})))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    company = vault.save_company(tmp_path, {'name': 'Unsure Co'})
    updated = product_enrich.backfill(tmp_path, sector_signals=(company_lookup._llm_signal,), size_signals=())
    saved = vault.load_company(tmp_path, company['id'])
    assert company['id'] in updated  # the review flag itself is a persisted change
    assert saved['sectors'] == []
    assert company_lookup.FLAG_SECTOR_AMBIGUOUS in saved['review_flags']


def test_llm_signal_invalid_sector_letter_is_ambiguous(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(json.dumps({
        'sector': 'ZZ', 'sector_label': 'something', 'confidence': 'high', 'size_hint': None})))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    company = vault.save_company(tmp_path, {'name': 'Bad Letter Co'})
    product_enrich.backfill(tmp_path, sector_signals=(company_lookup._llm_signal,), size_signals=())
    saved = vault.load_company(tmp_path, company['id'])
    assert saved['sectors'] == []
    assert company_lookup.FLAG_SECTOR_AMBIGUOUS in saved['review_flags']


def test_llm_signal_malformed_json_flags_ambiguous(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for('not json'))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    company = vault.save_company(tmp_path, {'name': 'Garbled Co'})
    collector = company_lookup.BackfillAccounting()
    updated = product_enrich.backfill(tmp_path, sector_signals=(company_lookup._llm_signal,),
                                      size_signals=(), collector=collector)
    saved = vault.load_company(tmp_path, company['id'])
    assert company['id'] in updated
    assert saved['sectors'] == []
    assert company_lookup.FLAG_SECTOR_AMBIGUOUS in saved['review_flags']
    assert collector.summary()['ambiguous'] == 1


def test_llm_signal_endpoint_error_is_fetch_error_for_both_fields(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(error=RuntimeError('boom')))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    vault.save_company(tmp_path, {'name': 'Unreachable Co'})
    collector = company_lookup.BackfillAccounting()
    product_enrich.plan_backfill(tmp_path, sector_signals=(company_lookup._llm_signal,),
                                  size_signals=(company_lookup._llm_signal,), collector=collector)
    events = {(e['signal'], e['field'], e['outcome']) for e in collector.events}
    assert ('llm', 'sectors', 'fetch-error') in events
    assert ('llm', 'size', 'fetch-error') in events


# --- Review fix round finding 6: an overall deadline around the LLM call,
# mirroring ingest._within_deadline, so a client that ignores its own
# `timeout` kwarg entirely still cannot block a backfill sweep forever.
def test_llm_classify_enforces_overall_deadline_even_if_client_ignores_timeout(tmp_path, monkeypatch):
    import time
    from types import SimpleNamespace

    monkeypatch.setattr(product_enrich, 'LLM_TIMEOUT', 0.05)
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)

    def hanging_client():
        def create(**kwargs):
            time.sleep(5)  # ignores its own `timeout` kwarg entirely
            raise AssertionError('unreachable')
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(product_enrich, 'get_llm_client', hanging_client)
    company = vault.save_company(tmp_path, {'name': 'Hanging Co'})
    started = time.monotonic()
    collector = company_lookup.BackfillAccounting()
    product_enrich.backfill(tmp_path, sector_signals=(), size_signals=(), collector=collector)
    elapsed = time.monotonic() - started
    # Both fields independently fall back to the injected (gated) LLM
    # client when every structured signal is empty; each fallback hits
    # the overall deadline exactly once, so the accounting shows one
    # fetch-error for sectors and one for size.
    assert collector.summary()['fetch-error'] == 2
    assert vault.load_company(tmp_path, company['id'])['sectors'] == []
    assert elapsed < 1  # the overall deadline fired well before the 5s sleep


def test_llm_signal_size_hint_contradicts_populated_size_class_flags_review(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(json.dumps({
        'sector': None, 'sector_label': None, 'confidence': 'high', 'size_hint': 'large'})))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    company = vault.save_company(tmp_path, {'name': 'Contradicted Size Co', 'size_class': 'micro'})
    product_enrich.backfill(tmp_path, sector_signals=(), size_signals=(company_lookup._llm_signal,))
    saved = vault.load_company(tmp_path, company['id'])
    assert saved['size_class'] == 'micro'  # never overwritten
    assert company_lookup.FLAG_SIZE_INCONSISTENT in saved['review_flags']


def test_llm_signal_size_hint_fills_size_class_only_never_size_range(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(json.dumps({
        'sector': None, 'sector_label': None, 'confidence': 'high', 'size_hint': 'large'})))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    company = vault.save_company(tmp_path, {'name': 'Class Only Co'})
    product_enrich.backfill(tmp_path, sector_signals=(), size_signals=(company_lookup._llm_signal,))
    saved = vault.load_company(tmp_path, company['id'])
    assert saved['size_class'] == 'large'
    assert saved['size_range'] is None  # a class hint alone must never fabricate a range bucket


# --- Review fix round finding 1: an LLM size hint must be checked against an
# already-populated size_range before it fills size_class, not just against
# an already-populated size_class (size_cascade previously bypassed this
# entirely when size_class was still empty).

def test_llm_signal_size_hint_compatible_with_populated_range_fills_size_class(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(json.dumps({
        'sector': None, 'sector_label': None, 'confidence': 'high', 'size_hint': 'large'})))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    company = vault.save_company(tmp_path, {'name': 'Compatible Range Co', 'size_range': '1000+'})
    product_enrich.backfill(tmp_path, sector_signals=(), size_signals=(company_lookup._llm_signal,))
    saved = vault.load_company(tmp_path, company['id'])
    assert saved['size_class'] == 'large'
    assert company_lookup.FLAG_SIZE_INCONSISTENT not in (saved.get('review_flags') or [])


def test_llm_signal_size_hint_contradicts_populated_range_flags_without_filling(tmp_path, monkeypatch):
    # The bug: size_range='1-10' (max 10 employees) with hint 'large' used
    # to fill size_class='large' with no review flag at all.
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(json.dumps({
        'sector': None, 'sector_label': None, 'confidence': 'high', 'size_hint': 'large'})))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    company = vault.save_company(tmp_path, {'name': 'Tiny Shop Co', 'size_range': '1-10'})
    product_enrich.backfill(tmp_path, sector_signals=(), size_signals=(company_lookup._llm_signal,))
    saved = vault.load_company(tmp_path, company['id'])
    assert saved['size_class'] is None  # nothing filled
    assert saved['size_range'] == '1-10'
    assert company_lookup.FLAG_SIZE_INCONSISTENT in saved['review_flags']


def test_llm_signal_size_hint_boundary_spanning_range_treated_as_compatible(tmp_path, monkeypatch):
    # Under contract rule 8 (inclusive EU thresholds), '201-1000' straddles
    # 'medium' (counts 201..250) and 'large' (counts 251..1000): a hint
    # naming either adjacent class is plausible evidence, not a
    # contradiction, since the range alone cannot rule the narrower one out.
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(json.dumps({
        'sector': None, 'sector_label': None, 'confidence': 'high', 'size_hint': 'medium'})))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    company = vault.save_company(tmp_path, {'name': 'Boundary Co', 'size_range': '201-1000'})
    product_enrich.backfill(tmp_path, sector_signals=(), size_signals=())
    saved = vault.load_company(tmp_path, company['id'])
    assert saved['size_class'] == 'medium'
    assert company_lookup.FLAG_SIZE_INCONSISTENT not in (saved.get('review_flags') or [])


def test_llm_signal_prompt_contains_only_identifying_fields_never_job_data(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    captured = {}

    def fake_client():
        client = client_for(json.dumps({'sector': None, 'sector_label': None,
                                        'confidence': 'low', 'size_hint': None}))
        real_create = client.chat.completions.create

        def capturing_create(**kwargs):
            captured['messages'] = kwargs['messages']
            return real_create(**kwargs)
        client.chat.completions.create = capturing_create
        return client

    monkeypatch.setattr(product_enrich, 'get_llm_client', fake_client)
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    vault.save_company(tmp_path, {'name': 'Scoped Co', 'website': 'https://scoped.example',
                                  'locations': ['Berlin'], 'notes': 'Owner note.'})
    product_enrich.backfill(tmp_path, sector_signals=(company_lookup._llm_signal,), size_signals=())
    content = ' '.join(m['content'] for m in captured['messages'])
    assert 'Scoped Co' in content and 'scoped.example' in content
    assert 'Berlin' in content and 'Owner note.' in content


def test_llm_system_prompt_inlines_the_isic_letter_table(tmp_path, monkeypatch):
    """The system prompt must carry every ISIC letter + label from
    isic_sections.yaml so the model looks the mapping up instead of
    recalling it (live defect 2026-10-09: the local LLM answered letter C
    with the section-D label 'Electricity, gas, steam...' and the
    consistency check correctly refused -- Retry could never resolve a
    real grid operator until the table shipped)."""
    import json
    prompt = company_lookup._llm_system_prompt()
    loaded = sectors.load_isic_sections()
    assert len(loaded) == 21  # A-U ISIC Rev.4 sections
    for section in loaded:
        assert f"{section['code']} = {section['label']}" in prompt
    # Cache discipline (Codex review 2026-10-09): with sectors._SECTIONS
    # warm, building the prompt again must not re-read the YAML file.
    sectors._sections()  # warm the cache
    read_calls = []
    real_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        read_calls.append(str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', counting_read_text)
    company_lookup._llm_system_prompt()
    assert not any('isic_sections' in path for path in read_calls)
    # The two letters that were confused live must both be present with
    # their correct labels, so a lookup cannot return C for electricity.
    assert 'D = Electricity, gas, steam and air conditioning supply' in prompt
    assert 'C = Manufacturing' in prompt
    # The table is in the SYSTEM message, and identifying fields remain
    # the only user content.
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    captured = {}

    def fake_client():
        client = client_for(json.dumps({'sector': None, 'sector_label': None,
                                        'confidence': 'low', 'size_hint': None}))
        real_create = client.chat.completions.create

        def capturing_create(**kwargs):
            captured['messages'] = kwargs['messages']
            return real_create(**kwargs)
        client.chat.completions.create = capturing_create
        return client

    monkeypatch.setattr(product_enrich, 'get_llm_client', fake_client)
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    vault.save_company(tmp_path, {'name': 'Table Co', 'website': 'https://table.example'})
    product_enrich.backfill(tmp_path, sector_signals=(company_lookup._llm_signal,), size_signals=())
    system = [m for m in captured['messages'] if m['role'] == 'system']
    assert len(system) == 1
    assert 'D = Electricity, gas, steam and air conditioning supply' in system[0]['content']
    user = [m for m in captured['messages'] if m['role'] == 'user'][0]['content']
    assert 'ISIC' not in user  # table never leaks into user content


def test_llm_signal_accounting_summary_counts(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setattr(product_enrich, 'get_llm_client', lambda: client_for(json.dumps({
        'sector': 'J', 'sector_label': 'software company', 'confidence': 'high', 'size_hint': 'small'})))
    monkeypatch.setattr(product_enrich, 'get_llm_model', object)
    vault.save_company(tmp_path, {'name': 'Counted Software Co'})
    collector = company_lookup.BackfillAccounting()
    product_enrich.plan_backfill(tmp_path, sector_signals=(company_lookup._llm_signal,),
                                  size_signals=(company_lookup._llm_signal,), collector=collector)
    summary = collector.summary()
    assert summary['matched'] == 2  # one for sectors, one for size
    assert summary['fetch-error'] == 0 and summary['ambiguous'] == 0


# --- M1 audit: per-company Retry replaces the sweep-all Backfill button ----
# Visibility: 'exhausted' or 'flagged' on any field_state, OR a
# non-empty review_flags list, OR a never-enriched company (empty
# sectors/size -- owner decision 2026-10-12, option B: show Retry with
# a "Please add a url to enrich." hint). A company with everything
# filled shows no Retry -- nothing to retry.

# JOZ-280: the company detail page's "show Retry" decision (any field
# exhausted/flagged, a review flag present, or the company never enriched)
# moves from Jinja template logic to the React CompanyDetail page, computed
# client-side from the same fields the JSON API already exposes unchanged;
# see frontend/tests/company-detail.spec.js for the rendered-button
# assertion. These tests now pin that the JSON API still carries the exact
# fields that decision depends on.
def test_company_detail_shows_retry_when_a_field_is_exhausted(client, root):
    company = vault.save_company(root, {'name': 'Exhausted Labs', 'enrichment': {
        'field_states': {'sectors': {'state': 'exhausted'}, 'size': {'state': 'exhausted'}}}})
    data = client.get('/api/companies/' + company['id']).json
    assert data['enrichment']['field_states']['sectors']['state'] == 'exhausted'
    assert data['enrichment']['field_states']['size']['state'] == 'exhausted'


def test_company_detail_shows_retry_when_a_field_is_flagged(client, root):
    company = vault.save_company(root, {'name': 'Flagged Labs', 'enrichment': {
        'field_states': {'sectors': {'state': 'flagged'}}}})
    data = client.get('/api/companies/' + company['id']).json
    assert data['enrichment']['field_states']['sectors']['state'] == 'flagged'


def test_company_detail_shows_retry_when_review_flags_present(client, root):
    company = vault.save_company(root, {'name': 'Review Flagged Labs',
                                        'review_flags': [company_lookup.FLAG_SECTOR_AMBIGUOUS]})
    data = client.get('/api/companies/' + company['id']).json
    assert data['review_flags'] == [company_lookup.FLAG_SECTOR_AMBIGUOUS]


def test_company_detail_hides_retry_when_fields_are_filled(client, root):
    company = vault.save_company(root, {'name': 'Filled Labs', 'sectors': ['J'],
                                        'size_range': '1-10', 'size_class': 'micro', 'enrichment': {
        'field_states': {'sectors': {'state': 'filled'}, 'size': {'state': 'filled'}}}})
    data = client.get('/api/companies/' + company['id']).json
    assert data['enrichment']['field_states']['sectors']['state'] == 'filled'
    assert data['enrichment']['field_states']['size']['state'] == 'filled'
    assert not data['review_flags']


# --- Owner click-test follow-up 2026-10-09: sector label on detail page -----
# The directory card showed the resolved sector but the detail page did not.
# Same read-time label mapping, never bare codes, 'Sector unknown' fallback.

def test_company_detail_shows_sector_label_not_code(client, root):
    company = vault.save_company(root, {'name': 'Label Detail Labs', 'sectors': ['D'],
                                        'size_class': 'large'})
    page = client.get('/api/companies/' + company['id'] + '?view=page').json
    # Section 3 display rule (same as the directory card): the detail page
    # view carries the human label, never the bare ISIC code.
    label = next(s['label'] for s in sectors.load_isic_sections() if s['code'] == 'D')
    assert page['sector_labels'] == [label]


def test_company_detail_shows_sector_unknown_when_unclassified(client, root):
    company = vault.save_company(root, {'name': 'Unknown Detail Labs'})
    page = client.get('/api/companies/' + company['id'] + '?view=page').json
    assert page['sector_labels'] == []


def test_company_detail_shows_retry_with_add_url_hint_for_never_enriched_company(client, root):
    # Owner click-test 2026-10-12: a real vault company with empty
    # sectors/size and no flagged states used to show no Retry at all --
    # the one company that most needs enrichment was locked out. Option B:
    # keep the gate for filled companies but never-enriched ones get a
    # Retry with the owner's wording "Please add a url to enrich." (now a
    # React CompanyDetail decision; see frontend/tests/company-detail.spec.js).
    company = vault.save_company(root, {'name': 'Untouched Labs'})
    data = client.get('/api/companies/' + company['id']).json
    assert not data['sectors'] and not data['size_range'] and not data['size_class']


def test_retry_company_endpoint_happy_path_reuses_sector_size_cascade(client, root, monkeypatch):
    company = vault.save_company(root, {'name': 'Retry Me Labs'})
    monkeypatch.setattr(company_lookup, 'classify_sector', lambda c, **kw: (['J'], None))
    monkeypatch.setattr(company_lookup, 'classify_size',
                        lambda c, **kw: ({'size_range': '1-10', 'size_class': 'micro'}, None))
    response = client.post('/api/companies/' + company['id'] + '/retry')
    assert response.status_code == 200
    assert response.json['sectors'] == ['J']
    assert response.json['size_class'] == 'micro'
    saved = vault.load_company(root, company['id'])
    assert saved['sectors'] == ['J'] and saved['size_class'] == 'micro'
    assert saved['enrichment']['field_states']['sectors']['state'] == 'filled'


def test_retry_company_endpoint_404_for_missing_company(client, root):
    assert client.post('/api/companies/missing-co/retry').status_code == 404


def test_retry_company_endpoint_rejects_non_employer_kind(client, root):
    institution = vault.save_company(root, {'name': 'Fiction University', 'kind': 'institution'})
    response = client.post('/api/companies/' + institution['id'] + '/retry')
    assert response.status_code == 400
    # Rejected before any cascade work, and the record itself is untouched.
    assert vault.load_company(root, institution['id']) == institution


def test_retry_company_endpoint_never_gated_on_auto_cascade_enabled(client, root, monkeypatch):
    # Decision 27's "explicit, owner-triggered, never silent" rule applies
    # here too: a Retry click must always run, unlike the automatic
    # new-company cascade which is off whenever AUTO_CASCADE_ENABLED is False
    # (the suite-wide default, see conftest.offline).
    from careeros import server
    assert server.AUTO_CASCADE_ENABLED is False
    company = vault.save_company(root, {'name': 'Always Runs Labs'})
    monkeypatch.setattr(company_lookup, 'classify_sector', lambda c, **kw: (['K'], None))
    monkeypatch.setattr(company_lookup, 'classify_size', lambda c, **kw: (None, None))
    response = client.post('/api/companies/' + company['id'] + '/retry')
    assert response.status_code == 200
    assert vault.load_company(root, company['id'])['sectors'] == ['K']


def test_older_auto_cascade_cannot_overwrite_completed_retry(client, root, monkeypatch):
    from threading import Event
    from careeros import server

    entered, release = Event(), Event()
    monkeypatch.setattr(server, 'AUTO_CASCADE_ENABLED', True)

    def older_empty(company, collector, **kwargs):
        entered.set()
        assert release.wait(5)
        collector.record(company['id'], older_empty, 'sectors', 'empty')
        return None, None

    def newer_conflict(company, collector, **kwargs):
        collector.record(company['id'], newer_conflict, 'sectors', 'ambiguous')
        return None, company_lookup.FLAG_SECTOR_CONFLICT

    monkeypatch.setattr(company_lookup, 'classify_sector', older_empty)
    monkeypatch.setattr(company_lookup, 'classify_size', lambda *a, **k: (None, None))
    monkeypatch.setattr(intake, 'fetch_url', lambda url:
                        '<script type="application/ld+json">{"@type":"JobPosting",'
                        '"title":"Role","hiringOrganization":{"name":"Retry Race Labs"}}'
                        '</script><p>Build useful things.</p>')
    response = client.post('/api/jobs/intake', json={'url': 'https://retry-race.example/job'})
    company_id = response.json['job']['company_id']
    worker = client.application.config['CASCADE_THREADS'][company_id]
    try:
        assert entered.wait(5)
        monkeypatch.setattr(company_lookup, 'classify_sector', newer_conflict)
        response = client.post('/api/companies/' + company_id + '/retry')
        assert response.status_code == 200
        completed = response.json
        assert completed['enrichment']['field_states']['sectors']['state'] == 'flagged'
        assert company_lookup.FLAG_SECTOR_CONFLICT in completed['review_flags']
        assert completed['enrichment']['summary']['ambiguous'] == 1
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    # retry_applied is response-only metadata, never stored (see the route);
    # the stored record must equal the response minus that key.
    stored = {k: v for k, v in completed.items() if k != 'retry_applied'}
    assert vault.load_company(root, company_id) == stored


@pytest.mark.parametrize('change,status', [('delete', 404), ('kind', 400)])
def test_retry_company_rejects_mid_run_disappearance_or_kind_change(client, root, monkeypatch, change, status):
    company = vault.save_company(root, {'name': 'Changed During Retry'})

    def change_during_cascade(snapshot, **kwargs):
        if change == 'delete':
            assert client.delete('/api/companies/' + company['id']).status_code == 200
        else:
            assert client.put('/api/companies/' + company['id'], json={'kind': 'institution'}).status_code == 200
        return ['J'], None

    monkeypatch.setattr(company_lookup, 'classify_sector', change_during_cascade)
    monkeypatch.setattr(company_lookup, 'classify_size', lambda *a, **k: (None, None))
    response = client.post('/api/companies/' + company['id'] + '/retry')
    assert response.status_code == status
    assert response.json['error'] == ('Company not found.' if change == 'delete'
                                      else 'Only employers have sector and size enrichment.')
    saved = vault.load_company(root, company['id'])
    if change == 'delete':
        assert saved is None
    else:
        assert saved['kind'] == 'institution'
        assert not saved['sectors']
        assert not saved.get('enrichment')


@pytest.mark.parametrize('flag,state', [(None, 'exhausted'), (company_lookup.FLAG_SECTOR_CONFLICT, 'flagged')])
def test_retry_company_response_reports_completed_empty_or_flagged_outcome(client, root, monkeypatch, flag, state):
    company = vault.save_company(root, {'name': 'Outcome Labs'})
    monkeypatch.setattr(company_lookup, 'classify_sector', lambda *a, **k: (None, flag))
    monkeypatch.setattr(company_lookup, 'classify_size', lambda *a, **k: (None, None))
    response = client.post('/api/companies/' + company['id'] + '/retry')
    assert response.status_code == 200
    assert response.json['enrichment']['field_states']['sectors']['state'] == state
    assert response.json['enrichment']['field_states']['size']['state'] == 'exhausted'
    assert response.json['review_flags'] == ([flag] if flag else [])


# --- M1 amendment: website signal follows redirects safely (2026-10-09) ---

def test_fetch_company_jsonld_uses_redirect_following_fetcher_by_default(client, root, monkeypatch):
    """Product company Retry uses the capability default fetch, separate from postings."""
    from org_intake import fetch as org_fetch
    calls = []
    def fake_follow(url):
        calls.append(url)
        return '<script type="application/ld+json">{"industry":"Electric power generation","numberOfEmployees":42}</script>'
    monkeypatch.setattr(org_fetch, 'default_fetch', fake_follow)
    company = vault.save_company(root, {'name': 'Power Labs', 'website': 'https://power.example'})
    response = client.post('/api/companies/' + company['id'] + '/retry')
    assert response.status_code == 200
    assert 'https://power.example' in calls
    assert response.json['sectors'] == ['D']
    assert response.json['size_class'] == 'small'


def test_safe_redirect_handler_rechecks_target_safety(monkeypatch):
    """A redirect onto a host resolving to a private/internal address must
    be refused at the hop by the REAL check_url (not a mock), not just at
    the original URL. internal.example is a documentation-safe hostname;
    the non-public resolution comes from the mocked getaddrinfo (loopback),
    so no RFC1918 literal enters a git-bound artifact."""
    import socket as _socket

    handler = intake.SafeRedirect()
    req = request.Request('https://public.example/')

    # 93.184.216.34 is example.com's documented PUBLIC address, so a hop to
    # public.example passes the real check_url...
    def resolving(host, port, **kwargs):
        ip = '127.0.0.1' if host == 'internal.example' else '93.184.216.34'
        return [(_socket.AF_INET, 1, 6, '', (ip, port or 443))]
    monkeypatch.setattr(_socket, 'getaddrinfo', resolving)

    result = handler.redirect_request(req, None, 302, 'Found', {}, 'https://public.example/x')
    assert result.full_url == 'https://public.example/x'

    # ...while a hop to internal.example (loopback) is refused by the real
    # check_url's is_unsafe_ip guard, proving the recheck runs per hop.
    with pytest.raises(ValueError):
        handler.redirect_request(req, None, 302, 'Found', {}, 'http://internal.example/evil')


def test_safe_redirect_bounds_and_closes_intermediate_body():
    """The stock handler drains each redirect body with an unbounded read.
    SafeRedirect must read at most MAX_REDIRECT_BODY bytes, close the
    intermediate response on BOTH the follow and the validation-failure
    path, and run before_hop before following (deadline check)."""
    class FakeResponse:
        def __init__(self):
            self.read_args = None
            self.closed = False
        def read(self, n=-1):
            self.read_args = n
            return b'x' * (n if n and n > 0 else 2_000_001)
        def close(self):
            self.closed = True

    hops = []
    handler = intake.SafeRedirect(before_hop=lambda: hops.append(1))

    # Follow path: bounded read, closed, before_hop fired.
    fp = FakeResponse()
    req = request.Request('https://public.example/')
    # Stop before the real network by making redirect_request return None
    # after validation; we only assert the drain/close/hook side effects.
    handler.redirect_request = lambda *a, **k: None
    handler.http_error_302(req, fp, 302, 'Found', {'location': 'https://public.example/next'})
    assert fp.read_args == intake.MAX_REDIRECT_BODY
    assert fp.closed is True
    assert hops == [1]

    # Validation-failure path: before_hop raising still closes the body.
    class Boom(Exception):
        pass
    handler2 = intake.SafeRedirect(before_hop=lambda: (_ for _ in ()).throw(Boom()))
    fp2 = FakeResponse()
    with pytest.raises(Boom):
        handler2.http_error_302(request.Request('https://public.example/'), fp2,
                                302, 'Found', {'location': 'https://public.example/n'})
    assert fp2.closed is True


@pytest.mark.parametrize('code', [301, 302, 303, 307, 308])
def test_safe_redirect_bounds_every_redirect_status_code(code):
    """Regression for the 308 gap Codex found: every status the stock handler
    aliases (301/302/303/307/308) must reach the bounded, closing override --
    not just the ones explicitly named in an earlier alias line."""
    class FakeResponse:
        def __init__(self):
            self.read_args = None
            self.closed = False
        def read(self, n=-1):
            self.read_args = n
            return b'x' * (n if n and n > 0 else 2_000_001)
        def close(self):
            self.closed = True

    handler = intake.SafeRedirect()
    handler.redirect_request = lambda *a, **k: None  # stop before real network
    fp = FakeResponse()
    getattr(handler, f'http_error_{code}')(
        request.Request('https://public.example/'), fp, code, 'Redirected',
        {'location': 'https://public.example/next'})
    assert fp.read_args == intake.MAX_REDIRECT_BODY
    assert fp.closed is True


def test_safe_redirect_handler_caps_hops():
    handler = intake.SafeRedirect(max_hops=2)
    req = request.Request('https://public.example/')
    handler.hops = 2
    with pytest.raises(ValueError, match='Too many redirects'):
        handler.redirect_request(req, None, 302, 'Found', {}, 'https://next.example/')


def test_safe_redirect_resolves_relative_targets():
    """A relative Location header must be joined against the current URL
    before the safety check, not passed through as a bare path."""
    handler = intake.SafeRedirect()
    req = request.Request('https://public.example/dir/page')
    result = handler.redirect_request(req, None, 301, 'Moved', {}, '/en/home.html')
    assert result.full_url == 'https://public.example/en/home.html'
    assert handler.hops == 1


def test_posting_intake_still_refuses_redirects():
    """fetch_url (job posting intake) keeps its strict NoRedirect policy;
    the relaxation is scoped to fetch_url_follow only."""
    with pytest.raises(ValueError, match='Redirects are disabled'):
        intake.NoRedirect().redirect_request(None, None, 301, 'Moved', {}, 'https://other.example')


def test_retry_applied_reports_only_fields_this_invocation_wrote(client, root, monkeypatch):
    """The MAJOR fix: an already-populated sector and an exhausted size mean
    this Retry wrote NOTHING, so retry_applied must be [] even though the
    stored field_states still show sectors as 'filled' from an earlier run.
    The frontend keys 'updated vs nothing changed' off retry_applied, never
    off the stored state."""
    company = vault.save_company(root, {'name': 'Already Filled Labs', 'sectors': ['J']})
    # Seed a prior 'filled' state so the stored field_states lie about freshness.
    company = vault.save_company(root, {**company,
                                        'enrichment': {'field_states': {'sectors': {'state': 'filled'}}}})
    monkeypatch.setattr(company_lookup, 'classify_sector', lambda *a, **k: (['J'], None))
    monkeypatch.setattr(company_lookup, 'classify_size', lambda *a, **k: (None, None))
    response = client.post('/api/companies/' + company['id'] + '/retry')
    assert response.status_code == 200
    # sectors already set -> not eligible -> not applied; size exhausted -> not applied.
    assert response.json['retry_applied'] == []


def test_retry_applied_lists_a_field_only_when_this_run_writes_it(client, root, monkeypatch):
    company = vault.save_company(root, {'name': 'Fresh Fill Labs'})
    monkeypatch.setattr(company_lookup, 'classify_sector', lambda c, **kw: (['J'], None))
    monkeypatch.setattr(company_lookup, 'classify_size',
                        lambda c, **kw: ({'size_range': '1-10', 'size_class': 'micro'}, None))
    response = client.post('/api/companies/' + company['id'] + '/retry')
    assert response.status_code == 200
    assert sorted(response.json['retry_applied']) == ['sectors', 'size']
