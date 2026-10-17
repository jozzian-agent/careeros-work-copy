"""Protects scripts/seed_zefix_zurich.py: pagination stops at the cap,
dedupe keys on UID before name, the staging file has the shape the
founder accepts from, the rate limit really waits, and the vault is only
ever read.

Every Zefix response here is a recorded fixture; no test reaches the
network. The suite's `offline` fixture also blocks `build_opener`, so a
test that accidentally called the real transport would fail rather than
fetch.
"""
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs

import pytest
import yaml

from careeros import vault

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'seed_zefix_zurich.py'


@pytest.fixture(scope='module')
def script():
    spec = importlib.util.spec_from_file_location('seed_zefix_zurich', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def binding(**fields):
    return {name: {'type': 'literal', 'value': value} for name, value in fields.items()}


def zefix_row(number, name, *, uid=None, form='0106', label='Aktiengesellschaft', seat='Zürich'):
    """One row in the shape the LINDAS SPARQL endpoint really returns,
    copied from a live response on 2026-10-17."""
    return binding(
        company=f'https://register.ld.admin.ch/zefix/company/{number}',
        uid=uid or f'CHE{number:0>9}',
        legalName=name, legalFormCode=form, legalFormLabel=label,
        seat=seat, locality=seat)


def flat_row(*args, **kwargs):
    """The same row already flattened, the way parse_sparql_rows hands it
    to row_to_company."""
    return {name: cell['value'] for name, cell in zefix_row(*args, **kwargs).items()}


def sparql(rows):
    return {'head': {'vars': ['company', 'uid', 'legalName', 'legalFormCode',
                              'legalFormLabel', 'seat', 'locality']},
            'results': {'bindings': list(rows)}}


class FakeTransport:
    """Stands in for polite_http.request_text, answering SPARQL pages out
    of a recorded list and recording every query it was asked."""

    def __init__(self, pages, *, count=None):
        self.pages = list(pages)
        self.count = count
        self.queries = []

    def __call__(self, url, *, data=None, headers=None, timeout=None, max_body=None, limiter=None):
        if limiter is not None:
            limiter.wait()
        # The real transport is handed a urlencoded form body; decode it
        # so an assertion can read the SPARQL the script actually sent.
        query = parse_qs((data or b'').decode()).get('query', [''])[0]
        self.queries.append(query)
        if 'COUNT' in query:
            body = sparql([binding(total=str(self.count))]) if self.count is not None else sparql([])
        else:
            body = sparql(self.pages.pop(0) if self.pages else [])
        return {'ok': True, 'status': 200, 'text': json.dumps(body), 'final_url': url, 'error': None}


@pytest.fixture
def seed_vault(tmp_path):
    """A vault holding one company, so dedupe has something to match. No
    UID anywhere, which is today's live vault and the reason the UID pass
    is inert."""
    root = tmp_path / 'vault'
    (root / 'companies').mkdir(parents=True)
    (root / 'jobs').mkdir()
    (root / 'experiences').mkdir()
    vault.save_company(root, {'name': 'Hedonia AG', 'kind': 'employer'})
    return root


#
# UID formatting: one stored form, and never a guess.
#
@pytest.mark.parametrize('raw, expected', [
    ('CHE116229891', 'CHE-116.229.891'),
    ('CHE-116.229.891', 'CHE-116.229.891'),
    ('che 116 229 891', 'CHE-116.229.891'),
    ('CHE-116.229.89', None),        # eight digits is not a UID
    ('CHE1162298911', None),         # ten digits is not one either
    ('116229891', None),             # no CHE prefix
    ('', None),
    (None, None),
])
def test_format_uid(script, raw, expected):
    assert script.format_uid(raw) == expected


def test_row_to_company_shape(script):
    company, reason = script.row_to_company({
        'company': 'https://register.ld.admin.ch/zefix/company/1000004',
        'uid': 'CHE116229891', 'legalName': 'Hedonia AG', 'legalFormCode': '0106',
        'legalFormLabel': 'Aktiengesellschaft', 'seat': 'Küsnacht (ZH)',
        'locality': 'Küsnacht ZH'})
    assert reason is None
    assert company == {
        'origin': 'seeded', 'zefix_id': '1000004',
        'zefix_url': 'https://register.ld.admin.ch/zefix/company/1000004',
        'uid': 'CHE-116.229.891', 'name': 'Hedonia AG',
        'legal_form': 'Aktiengesellschaft', 'legal_form_code': '0106',
        'seat': 'Küsnacht (ZH)', 'locality': 'Küsnacht ZH', 'canton': 'ZH',
        'domain': None}


def test_a_row_without_a_usable_uid_is_dropped_with_a_reason(script):
    company, reason = script.row_to_company({'legalName': 'No UID AG', 'uid': 'nonsense'})
    assert company is None
    assert 'UID' in reason


def test_a_row_without_a_name_is_dropped_with_a_reason(script):
    company, reason = script.row_to_company({'uid': 'CHE116229891'})
    assert company is None
    assert reason == 'no legal name'


#
# Pagination: the cap is the point.
#
def test_pagination_walks_pages_until_the_cap(script):
    transport = FakeTransport([[zefix_row(i, f'Company {i}') for i in range(start, start + 10)]
                               for start in (0, 10, 20)])
    limiter = script.polite_http.RateLimiter(0)
    rows = script.fetch_rows(max_rows=25, page_size=10, limiter=limiter, transport=transport)
    assert len(rows) == 25
    assert len(transport.queries) == 3
    assert 'LIMIT 10 OFFSET 0' in transport.queries[0]
    assert 'LIMIT 10 OFFSET 10' in transport.queries[1]
    # The last page asks only for the five rows still inside the cap, so
    # a capped run never pulls rows it will throw away.
    assert 'LIMIT 5 OFFSET 20' in transport.queries[2]


def test_pagination_stops_on_a_short_page(script):
    transport = FakeTransport([[zefix_row(1, 'Only AG'), zefix_row(2, 'Other AG')]])
    rows = script.fetch_rows(max_rows=500, page_size=10,
                             limiter=script.polite_http.RateLimiter(0), transport=transport)
    assert len(rows) == 2
    assert len(transport.queries) == 1


def test_the_query_asks_for_zurich_only(script):
    transport = FakeTransport([[]])
    script.fetch_rows(max_rows=10, page_size=10,
                      limiter=script.polite_http.RateLimiter(0), transport=transport)
    assert script.CANTON_URI in transport.queries[0]
    assert script.SOURCE_GRAPH in transport.queries[0]


def test_a_failed_page_stops_the_run_rather_than_shortening_the_universe(script):
    def broken(url, **kwargs):
        return {'ok': False, 'status': 503, 'text': '', 'final_url': url, 'error': 'HTTP 503'}

    with pytest.raises(RuntimeError, match='SPARQL request failed'):
        script.fetch_rows(max_rows=10, page_size=10,
                          limiter=script.polite_http.RateLimiter(0), transport=broken)


#
# Dedupe.
#
def test_dedupe_matches_on_uid_first(script):
    records = [{'id': 'CO-001', 'name': 'Something Else AG',
                'identifiers': [{'type': 'uid', 'value': 'CHE-116.229.891'}]}]
    seeded = [script.row_to_company(flat_row(1000004, 'Hedonia AG', uid='CHE116229891'))[0]]
    fresh, duplicates = script.dedupe(seeded, records)
    assert fresh == []
    assert duplicates[0]['matched_on'] == 'uid'
    assert duplicates[0]['confident'] is True
    assert duplicates[0]['matched_company_ids'] == ['CO-001']


def test_dedupe_falls_back_to_the_normalised_name_as_a_candidate(script):
    records = [{'id': 'CO-002', 'name': 'HEDONIA, AG'}]
    seeded = [script.row_to_company(flat_row(1000004, 'Hedonia AG'))[0]]
    fresh, duplicates = script.dedupe(seeded, records)
    assert fresh == []
    # A name match is a candidate the founder confirms, never a decision:
    # PROJECT.md's rule is that ambiguity raises a flag.
    assert duplicates[0]['matched_on'] == 'name'
    assert duplicates[0]['confident'] is False
    assert duplicates[0]['matched_company_ids'] == ['CO-002']


def test_dedupe_leaves_an_unknown_company_alone(script):
    fresh, duplicates = script.dedupe(
        [script.row_to_company(flat_row(1000006, 'Pryo Consult GmbH'))[0]],
        [{'id': 'CO-003', 'name': 'Hedonia AG'}])
    assert duplicates == []
    assert [company['name'] for company in fresh] == ['Pryo Consult GmbH']


def test_two_seeded_namesakes_both_survive_and_are_counted(script):
    """Two Zefix entries with the same name are two legal entities with
    two UIDs. Collapsing them would delete a real company, so they are
    counted instead."""
    seeded = [script.row_to_company(flat_row(1, 'Meier AG'))[0],
              script.row_to_company(flat_row(2, 'MEIER, AG'))[0]]
    fresh, duplicates = script.dedupe(seeded, [])
    assert len(fresh) == 2
    assert duplicates == []
    assert script.name_collisions(fresh) == 2


def test_existing_uids_reads_both_places_a_uid_can_sit(script):
    found = script.existing_uids([
        {'id': 'CO-001', 'uid': 'CHE116229891'},
        {'id': 'CO-002', 'identifiers': [{'type': 'che_uid', 'value': 'CHE-116.229.916'}]},
        {'id': 'CO-003', 'identifiers': [{'type': 'domain', 'value': 'example.ch'}]},
    ])
    assert found == {'CHE-116.229.891': 'CO-001', 'CHE-116.229.916': 'CO-002'}


#
# The rate limit.
#
def test_the_rate_limiter_waits_between_requests(script):
    clock = {'now': 0.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock['now'] += seconds

    limiter = script.polite_http.RateLimiter(1.0, sleep=sleep, now=lambda: clock['now'])
    limiter.wait()                       # first request waits for nothing
    assert slept == []
    clock['now'] += 0.25                 # a fast response
    limiter.wait()
    assert slept == [0.75]
    clock['now'] += 5.0                  # a slow response needs no extra wait
    limiter.wait()
    assert slept == [0.75]
    assert limiter.requests == 3
    assert limiter.slept == pytest.approx(0.75)


def test_every_page_request_goes_through_the_limiter(script):
    clock = {'now': 0.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock['now'] += seconds

    limiter = script.polite_http.RateLimiter(1.0, sleep=sleep, now=lambda: clock['now'])
    transport = FakeTransport([[zefix_row(i, f'C {i}')] for i in range(3)])
    script.fetch_rows(max_rows=3, page_size=1, limiter=limiter, transport=transport)
    assert limiter.requests == 3
    assert slept == [1.0, 1.0]


#
# The file --from-file is meant to consume.
#
def test_a_csv_bulk_export_maps_onto_the_same_row_shape(script):
    rows = script.parse_csv_rows(
        'UID,Firmenname,Rechtsform,Sitz\r\n'
        'CHE-116.229.891,Hedonia AG,Aktiengesellschaft,Küsnacht (ZH)\r\n')
    company, reason = script.row_to_company(rows[0])
    assert reason is None
    assert company['uid'] == 'CHE-116.229.891'
    assert company['name'] == 'Hedonia AG'
    assert company['legal_form'] == 'Aktiengesellschaft'
    assert company['seat'] == 'Küsnacht (ZH)'


def test_parse_sparql_rows_also_takes_a_bare_list(script):
    assert script.parse_sparql_rows([{'legalName': 'Hedonia AG'}]) == [{'legalName': 'Hedonia AG'}]


#
# The staging file.
#
def test_a_run_writes_a_staging_file_and_never_the_vault(script, seed_vault, tmp_path,
                                                         monkeypatch, capsys):
    before = {path: path.read_bytes()
              for path in sorted((seed_vault / 'companies').glob('*.yaml'))}
    transport = FakeTransport([[zefix_row(1000004, 'Hedonia AG'),
                                zefix_row(1000006, 'Pryo Consult GmbH'),
                                zefix_row(1000008, 'Broken', uid='nope')]], count=138597)
    monkeypatch.setattr(script.polite_http, 'request_text', transport)
    out = tmp_path / 'seeds' / 'zefix_zurich_test.yaml'
    assert script.main(['--vault', str(seed_vault), '--max', '50', '--page-size', '50',
                        '--min-interval', '0', '--out', str(out)]) == 0

    document = yaml.safe_load(out.read_text())
    assert document['report'] == {
        'fetched': 3, 'available_in_canton': 138597, 'new': 1, 'duplicate_uid': 0,
        'duplicate_name_candidate': 1, 'dropped': 1, 'with_domain': 0, 'without_domain': 1,
        'seeded_name_collisions': 0, 'vault_companies': 1, 'vault_companies_with_uid': 0,
        'errors': []}
    assert [company['name'] for company in document['companies']] == ['Pryo Consult GmbH']
    assert all(company['origin'] == 'seeded' for company in document['companies'])
    assert all(company['domain'] is None for company in document['companies'])
    assert document['duplicates'][0]['name'] == 'Hedonia AG'
    assert document['dropped'][0]['reason'].startswith('unusable UID')
    # Provenance the licence requires travels with the data.
    assert document['run']['licence'].startswith('OGD Open use')
    assert 'EHRA' in document['run']['attribution']
    assert document['run']['vault_written'] is None
    assert document['run']['user_agent'] == 'CareerOS/0.x (+contact: owner)'
    # What a capped run is a slice of travels with it, so an accepted row
    # is never mistaken for a shortlist of employers.
    assert 'not a shortlist' in document['run']['slice_basis']
    assert 'no status predicate' in document['run']['active_basis']

    after = {path: path.read_bytes()
             for path in sorted((seed_vault / 'companies').glob('*.yaml'))}
    assert after == before, 'the seeding run must never touch an existing company record'
    assert 'STAGING ONLY' in capsys.readouterr().out


def test_an_existing_staging_file_is_not_overwritten_without_force(script, seed_vault,
                                                                   tmp_path, monkeypatch):
    monkeypatch.setattr(script.polite_http, 'request_text',
                        FakeTransport([[zefix_row(1000006, 'Pryo Consult GmbH')]]))
    out = tmp_path / 'already-there.yaml'
    out.write_text('reviewed by the founder\n')
    with pytest.raises(SystemExit, match='--force'):
        script.main(['--vault', str(seed_vault), '--min-interval', '0', '--out', str(out)])
    assert out.read_text() == 'reviewed by the founder\n'


def test_from_file_reads_a_saved_response_and_calls_no_transport(script, seed_vault,
                                                                 tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('--from-file must not touch the network')

    monkeypatch.setattr(script.polite_http, 'request_text', forbidden)
    source = tmp_path / 'export.csv'
    source.write_text('UID,Name\nCHE-116.229.916,Pryo Consult GmbH\n')
    out = tmp_path / 'from-file.yaml'
    assert script.main(['--vault', str(seed_vault), '--from-file', str(source),
                        '--out', str(out)]) == 0
    document = yaml.safe_load(out.read_text())
    assert document['run']['source'].startswith('file:csv:')
    assert document['run']['requests'] == 0
    assert [company['uid'] for company in document['companies']] == ['CHE-116.229.916']
