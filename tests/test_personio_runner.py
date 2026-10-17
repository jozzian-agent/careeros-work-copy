"""The fetch pass and the golden-set export, end to end over real feeds.

Everything here runs through `careeros.feeds.fetch.fetch_tenant` with a
transport that answers out of the recorded fixtures, so the whole path --
request, retry, conditional request, snapshot, parse, map, geocode,
closure, export -- is exercised against bodies Personio actually served
on 2026-10-17, with no network.
"""
from pathlib import Path

import pytest
import yaml

from careeros.feeds import export, fetch as fetch_module, geocode, personio
from careeros.feeds import store as store_module

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'personio'


def body(name):
    return (FIXTURES / f'{name}.xml').read_text()


#: The feeds the fake Personio serves, by (tenant, language). Taken
#: straight from the recorded fixtures.
FEEDS = {
    ('isolutions', 'de'): 'isolutions_de_trimmed',
    ('isolutions', 'en'): 'isolutions_en_trimmed',       # same postings, no English text
    ('bring-labs', 'de'): 'bring_labs_de_trimmed',
    ('bring-labs', 'en'): 'bring_labs_en_trimmed',
    ('knott', 'de'): 'knott_de_trimmed',
    ('mapegy', 'de'): 'mapegy_de_empty',
}


class FakePersonio:
    """A Personio that serves the recorded fixtures, counts requests and
    can be told to fail, to 304 or to answer something broken."""

    def __init__(self, feeds=None, *, etags=None, fail=None, bodies=None):
        self.feeds = dict(FEEDS if feeds is None else feeds)
        self.etags = dict(etags or {})
        self.fail = dict(fail or {})
        self.bodies = dict(bodies or {})
        self.requests = []

    def __call__(self, url, *, limiter=None, headers=None, timeout=None, max_body=None):
        self.requests.append(url)
        host, tenant, language = self._parse(url)
        key = (tenant, language)
        if key in self.fail:
            return {'ok': False, 'text': '', 'final_url': url, 'headers': {},
                    **self.fail[key]}
        if key in self.bodies:
            text = self.bodies[key]
        elif key in self.feeds:
            text = body(self.feeds[key])
        else:
            return {'ok': False, 'status': 404, 'text': '', 'error': 'HTTP 404',
                    'final_url': url, 'headers': {}}
        etag = self.etags.get(key, f'"{tenant}-{language}"')
        if headers and headers.get('If-None-Match') == etag:
            return {'ok': False, 'status': 304, 'text': '', 'error': 'HTTP 304',
                    'final_url': url, 'headers': {'etag': etag}}
        return {'ok': True, 'status': 200, 'text': text, 'error': None,
                'final_url': url, 'headers': {'etag': etag}}

    @staticmethod
    def _parse(url):
        from urllib.parse import urlsplit, parse_qs
        parts = urlsplit(url)
        tenant, _, host = (parts.hostname or '').partition('.')
        language = parse_qs(parts.query).get('language', ['de'])[0]
        return host, tenant, language

    def count(self, tenant=None):
        return len([url for url in self.requests if tenant is None or f'//{tenant}.' in url])


@pytest.fixture
def store(tmp_path):
    return store_module.Store(tmp_path / 'personio')


def fetch(store, tenant, *, server, run='20261017T060000Z', conditional=None,
          languages=('de', 'en'), at='2026-10-17T06:00:00+00:00'):
    return fetch_module.fetch_tenant(tenant, store=store, run=run, fetch=server,
                                     conditional=conditional, languages=languages, at=at,
                                     sleep=lambda seconds: None)


# --- one tenant, fetched -----------------------------------------------------

def test_a_swiss_tenant_fetches_parses_maps_and_locates(store):
    server = FakePersonio()
    result = fetch(store, 'isolutions', server=server)
    assert result['fetch_status'] == 'ok'
    assert result['host'] == 'jobs.personio.de'
    assert len(result['postings']) == 3
    assert {posting['area_status'] for posting in result['postings']} == {geocode.IN_AREA}
    assert {posting['municipality'] for posting in result['postings']} == {'261'}
    assert result['postings'][0]['municipality_label'] == 'Zürich'
    assert result['parse_failures'] == []


def test_the_location_value_records_ride_along_with_the_feeds_own(store):
    result = fetch(store, 'isolutions', server=FakePersonio())
    values = result['postings'][0]['values']
    assert set(values) == {'contract', 'seniority', 'language', 'workload_min',
                           'workload_max', 'municipality', 'canton'}
    assert values['municipality']['value'] == '261'
    assert values['municipality']['source'] == 'feed'


def test_an_empty_feed_is_a_successful_fetch_with_no_postings(store):
    """The spec: "a tenant with an empty feed stays valid; it just has no
    open jobs." A failure here would close every posting it ever had."""
    result = fetch(store, 'mapegy', server=FakePersonio(), languages=('de',))
    assert result['fetch_status'] == 'ok'
    assert result['postings'] == []
    assert result['publishes'] == {'de': False}


def test_a_tenant_with_no_career_site_is_not_found_and_costs_one_request(store):
    """A little over 40% of the tenants Common Crawl knows about no
    longer serve a feed, so a 404 must not cost four requests."""
    server = FakePersonio()
    result = fetch(store, 'gone', server=server)
    assert result['fetch_status'] == fetch_module.FETCH_NOT_FOUND
    assert result['postings'] == []
    assert server.count('gone') == 2, 'one per host, not one per host and language'


def test_a_server_error_is_retried_with_backoff_and_then_reported(store):
    server = FakePersonio(fail={('isolutions', 'de'): {'status': 503, 'error': 'HTTP 503'},
                                ('isolutions', 'en'): {'status': 503, 'error': 'HTTP 503'}})
    result = fetch(store, 'isolutions', server=server)
    assert result['fetch_status'] == fetch_module.FETCH_HTTP_ERROR
    assert result['error'] == 'HTTP 503'
    assert server.count('isolutions') == fetch_module.ATTEMPTS * 4, \
        'both languages of both hosts, each retried to the cap'


def test_a_404_is_not_retried(store):
    server = FakePersonio(fail={('isolutions', 'de'): {'status': 404, 'error': 'HTTP 404'}})
    fetch(store, 'isolutions', server=server, languages=('de',))
    assert server.count('isolutions') == 2, 'one attempt per host; a 404 is a settled answer'


@pytest.mark.parametrize('broken,expected', [
    ('<html><body>maintenance', 'ParseError'),
    ('<html>maintenance</html>', 'not a Personio feed'),
])
def test_a_feed_that_is_not_a_feed_is_a_parse_failure_with_a_reason(store, broken, expected):
    """Two different failures, both counted against the spec's 99%
    parse-success rate and both named: "this is not XML" and "this is XML
    for something else"."""
    server = FakePersonio(bodies={('isolutions', 'de'): broken,
                                  ('isolutions', 'en'): broken})
    result = fetch(store, 'isolutions', server=server)
    assert result['fetch_status'] == fetch_module.FETCH_PARSE_ERROR
    # Both languages of both hosts: nothing parsed, so `.com` was tried
    # too, which is the spec's "try .de first, then .com".
    assert len(result['parse_failures']) == 4
    assert {failure['host'] for failure in result['parse_failures']} == set(personio.HOSTS)
    assert result['parse_failures'][0]['tenant'] == 'isolutions'
    assert expected in result['parse_failures'][0]['reason']


def test_a_body_that_hit_our_own_cap_is_truncated_and_not_a_parse_failure(store):
    """The defect the trial caught: one employer's feed is 2.2 MB and the
    shared 2 MB body cap cut it mid-element, so the XML parser reported
    "unclosed token" and blamed Personio for our own ceiling. A body that
    stops exactly at the cap now says what it is, which keeps the spec's
    parse-success rate a measurement of Personio's feeds."""
    cut = body('isolutions_de_trimmed')[:2048]
    server = FakePersonio(bodies={('big', 'de'): cut})
    attempt = fetch_module._fetch_one(
        'big', personio.HOSTS[0], 'de', mapper=personio, fetch=server, limiter=None,
        store=store, run='r1', known={}, sleep=lambda seconds: None,
        max_body=len(cut.encode()))
    assert attempt['status'] == fetch_module.FETCH_TRUNCATED
    assert 'body cap' in attempt['report']['error']
    assert attempt['positions'] == []

    # The same body under a cap it does not reach is a genuine parse
    # failure, which is the case the rate is supposed to count.
    attempt = fetch_module._fetch_one(
        'big', personio.HOSTS[0], 'de', mapper=personio, fetch=server, limiter=None,
        store=store, run='r1', known={}, sleep=lambda seconds: None,
        max_body=fetch_module.FEED_MAX_BODY)
    assert attempt['status'] == fetch_module.FETCH_PARSE_ERROR


# --- the two languages -------------------------------------------------------

def test_german_wins_the_record_and_english_is_kept_beside_it(store):
    """The spec asks for German first. The English text is not thrown
    away: the posting carries it as a translation."""
    result = fetch(store, 'bring-labs', server=FakePersonio())
    head_of_product = next(posting for posting in result['postings']
                           if posting['posting_id'] == '2726475')
    assert head_of_product['feed_language'] == 'de'
    assert head_of_product['title'] == 'Head of Product (m/w/x)'
    assert head_of_product['translations']['en']['title'] == 'Head of Product (m/f/x)'
    assert 'As Head of Product' in head_of_product['translations']['en']['description']


def test_a_language_with_text_beats_a_language_without(store):
    """A tenant that publishes only English still answers the German
    feed with 200 and empty descriptions, and a golden-set posting with
    no text is useless."""
    server = FakePersonio(feeds={('t', 'de'): 'bring_labs_fr_unsupported',
                                 ('t', 'en'): 'bring_labs_en_trimmed'})
    result = fetch(store, 't', server=server)
    head_of_product = next(posting for posting in result['postings']
                           if posting['posting_id'] == '2726475')
    assert head_of_product['feed_language'] == 'en'
    assert head_of_product['has_description'] is True
    assert head_of_product['translations']['de']['has_description'] is False


def test_a_tenant_that_publishes_no_english_is_not_asked_again(store):
    """The spec: "a second call with language=en only if the tenant
    publishes English postings." The first run is what finds out,
    because an unsupported language answers 200 -- which is exactly what
    `isolutions`'s English feed does for these three postings."""
    server = FakePersonio()
    first = fetch(store, 'isolutions', server=server)
    assert first['publishes'] == {'de': True, 'en': False}
    before = server.count('isolutions')
    second = fetch(store, 'isolutions', server=server, run='r2',
                   conditional={'de': {}, **first['etags']})
    assert second['fetch_status'] == 'ok'
    assert server.count('isolutions') == before + 1, 'German only on the second run'
    skipped = second['languages']['jobs.personio.de:en']
    assert 'publishes no en postings' in skipped['skipped']


def test_a_tenant_that_does_publish_english_keeps_being_asked(store):
    server = FakePersonio()
    first = fetch(store, 'bring-labs', server=server)
    assert first['publishes'] == {'de': True, 'en': True}
    before = server.count('bring-labs')
    fetch(store, 'bring-labs', server=server, run='r2', conditional=first['etags'])
    assert server.count('bring-labs') == before + 2


# --- conditional requests ----------------------------------------------------

def test_an_unchanged_feed_answers_304_and_is_replayed_from_its_snapshot(store):
    """A 304 carries no body, so the postings it implies come from the
    last raw snapshot. That keeps closure correct: a 304 is a successful
    fetch that saw every posting it saw last time."""
    server = FakePersonio()
    first = fetch(store, 'isolutions', server=server, languages=('de',))
    second = fetch(store, 'isolutions', server=server, run='r2', languages=('de',),
                   conditional=first['etags'])
    assert second['fetch_status'] == 'ok'
    assert len(second['postings']) == 3
    report = second['languages']['jobs.personio.de:de']
    assert report['conditional'] is True
    assert report['replayed'] is True
    assert report['status'] == 304


def test_a_304_whose_snapshot_is_gone_is_fetched_again_rather_than_guessed(store):
    server = FakePersonio()
    first = fetch(store, 'isolutions', server=server, languages=('de',))
    snapshot = store.root / first['etags']['de']['snapshot']
    snapshot.unlink()
    second = fetch(store, 'isolutions', server=server, run='r2', languages=('de',),
                   conditional=first['etags'])
    assert second['fetch_status'] == 'ok'
    assert len(second['postings']) == 3
    assert second['languages']['jobs.personio.de:de']['status'] == 200


def test_a_changed_etag_means_a_full_body(store):
    server = FakePersonio()
    first = fetch(store, 'isolutions', server=server, languages=('de',))
    server.etags[('isolutions', 'de')] = '"something-else"'
    second = fetch(store, 'isolutions', server=server, run='r2', languages=('de',),
                   conditional=first['etags'])
    assert second['languages']['jobs.personio.de:de']['status'] == 200
    assert second['etags']['de']['etag'] == '"something-else"'


# --- snapshots written by a fetch --------------------------------------------

def test_a_fetch_freezes_the_raw_body_and_every_posting(store):
    run_id = '20261017T060000Z'
    result = fetch(store, 'isolutions', server=FakePersonio(), run=run_id, languages=('de',))
    raw = store.feed_snapshot_path('isolutions', run_id, 'de')
    assert raw.exists(), 'the raw body is frozen by the fetch itself'
    assert personio.decompress(raw.read_bytes()) == body('isolutions_de_trimmed')
    # The posting snapshots are written when the run is recorded, which
    # is the step that also decides new/changed/closed.
    store_module.record_run(store, run=run_id, at='2026-10-17T06:00:00+00:00',
                            tenant_results={'isolutions': result})
    for posting in result['postings']:
        snapshot = store.read_posting_snapshot('isolutions', posting['posting_id'],
                                               posting['content_hash'])
        assert snapshot['posting']['title'] == posting['title']


def test_two_runs_of_an_unchanged_feed_write_one_posting_snapshot_each(store):
    server = FakePersonio()
    store_module.record_run(store, run='r1', at='2026-10-17T06:00:00+00:00', tenant_results={
        'isolutions': fetch(store, 'isolutions', server=server, run='r1', languages=('de',))})
    store_module.record_run(store, run='r2', at='2026-10-18T06:00:00+00:00', tenant_results={
        'isolutions': fetch(store, 'isolutions', server=server, run='r2', languages=('de',))})
    directory = store.root / 'snapshots' / 'postings' / 'isolutions'
    assert sum(len(list(path.glob('*.yaml'))) for path in directory.iterdir()) == 3
    assert len(list((store.root / 'snapshots' / 'feeds' / 'isolutions').glob('*'))) == 2, \
        'the raw body is kept per run; the posting snapshot is kept per content hash'


# --- the export --------------------------------------------------------------

def pool(store, server=None, *, tenants=('isolutions', 'bring-labs', 'knott', 'mapegy'),
         run='20261017T060000Z'):
    server = server or FakePersonio()
    results = {tenant: fetch(store, tenant, server=server, run=run) for tenant in tenants}
    store.append_run({'run_id': run, 'at': '2026-10-17T06:00:00+00:00'})
    store_module.record_run(store, run=run, at='2026-10-17T06:00:00+00:00',
                            tenant_results=results)
    return export.build_pool(store)


def test_the_pool_holds_the_zurich_postings_and_says_why_it_dropped_the_rest(store):
    rows, skipped = pool(store)
    assert {row['tenant'] for row in rows} == {'isolutions', 'bring-labs'}
    assert len(rows) == 5, ('three isolutions postings, plus bring-labs\'s Zurich posting '
                            'and its all-locations talent pool, which has a Zurich office')
    reasons = {item['reason'] for item in skipped}
    assert reasons == {geocode.OUT_OF_AREA, geocode.NEEDS_REVIEW}
    assert all(row['canton'] == '1' for row in rows)


def test_every_field_the_spec_asks_the_export_to_carry_is_there(store):
    rows, _ = pool(store)
    row = next(row for row in rows if row['tenant'] == 'bring-labs')
    assert row['snapshot_id'].startswith('personio:bring-labs:2726475@')
    assert row['tenant'] == 'bring-labs'
    assert row['company'] == 'Bring! Labs AG'
    assert row['title'] == 'Head of Product (m/w/x)'
    assert row['language'] == 'de'
    assert row['municipality'] == '261'
    assert row['municipality_label'] == 'Zürich'
    assert row['contract'] == 'permanent'
    assert row['workload_min'] == '100' and row['workload_max'] == '100'
    assert row['schedule_raw'] == 'full-time'
    assert row['has_salary'] in (True, False)
    assert row['url'] == 'https://bring-labs.jobs.personio.de/job/2726475'
    assert row['content_hash'] and row['feed_snapshot']


def test_the_stratification_keys_are_personios_own_occupation_ids(store):
    """The brief forbids classifying occupations here (CAREER-57 owns
    that), and the feed states its own ids, which need no model."""
    rows, _ = pool(store)
    row = next(row for row in rows if row['tenant'] == 'bring-labs')
    assert row['stratum_occupation'] == 'product_management'
    assert row['stratum_occupation_category'] == 'marketing_and_product'
    assert row['job_family'] is None
    assert 'CAREER-57' in row['job_family_status']


def test_the_summary_counts_breadth_and_refuses_to_claim_a_job_family_number(store):
    rows, _ = pool(store)
    summary = export.summarise(rows)
    assert summary['postings'] == len(rows)
    assert summary['tenants'] == 2
    assert summary['geocoded_to_municipality'] == len(rows)
    assert summary['occupation_categories'] >= 2
    assert summary['job_families'] is None
    assert 'CAREER-57' in summary['job_family_note']
    assert summary['by_language']['de'] == len(rows)


def test_the_pool_reads_its_location_from_the_live_state_and_its_text_from_the_snapshot(store):
    """So an improved geocoder corrects a row on the next fetch without
    rewriting a single immutable snapshot."""
    rows, _ = pool(store, tenants=('isolutions',))
    assert all(row['municipality'] == '261' for row in rows)
    state = store.load_state('isolutions')
    for entry in state['postings'].values():
        entry['municipality'] = '230'
        entry['municipality_label'] = 'Winterthur'
        entry['location']['municipality'] = '230'
    store.save_state(state)
    rows, _ = export.build_pool(store, tenants=['isolutions'])
    assert all(row['municipality'] == '230' for row in rows)
    assert all(row['title'] for row in rows), 'the text still comes from the snapshot'


def test_a_closed_posting_leaves_the_pool_and_a_suspected_one_does_not(store):
    server = FakePersonio()
    pool(store, server, tenants=('isolutions',), run='r1')
    empty = {'isolutions': {'fetch_status': 'ok', 'postings': []}}
    store.append_run({'run_id': 'r2', 'at': 'x'})
    store_module.record_run(store, run='r2', at='2026-10-18T06:00:00+00:00',
                            tenant_results=empty)
    rows, _ = export.build_pool(store)
    assert len(rows) == 3, 'missing from one fetch is suspected_closing, which is still live'
    store.append_run({'run_id': 'r3', 'at': 'x'})
    store_module.record_run(store, run='r3', at='2026-10-19T06:00:00+00:00',
                            tenant_results=empty)
    assert export.build_pool(store)[0] == []


def test_out_of_area_postings_can_be_counted_without_being_sampled(store):
    rows, _ = pool(store)
    with_others, skipped = export.build_pool(store, include_out_of_area=True)
    assert len(with_others) > len(rows)
    assert skipped == []
    assert {row['canton'] for row in with_others} > {'1'}


def test_the_pool_file_carries_its_summary_and_its_taxonomy_versions(store):
    rows, _ = pool(store)
    path = export.write_pool(store, rows, day='2026-10-17', meta={'trial': True})
    data = yaml.safe_load(path.read_text())
    assert data['day'] == '2026-10-17'
    assert data['trial'] is True
    assert data['summary']['postings'] == len(rows)
    assert len(data['postings']) == len(rows)
    assert data['postings'][0]['key'] < data['postings'][-1]['key'], 'sorted by key'


def test_a_posting_whose_snapshot_is_missing_is_skipped_with_a_reason(store):
    pool(store, tenants=('isolutions',))
    for path in (store.root / 'snapshots' / 'postings' / 'isolutions').rglob('*.yaml'):
        path.unlink()
    rows, skipped = export.build_pool(store)
    assert rows == []
    assert all('snapshot' in item['reason'] for item in skipped)


# --- the salary flag ---------------------------------------------------------

@pytest.mark.parametrize('text,expected,rule', [
    ("Wir bieten ein Jahresgehalt von CHF 95'000 bis 110'000.", True, 'word+amount'),
    ('Salary range: 80k - 100k', True, 'word+amount'),
    ("Lohn nach Vereinbarung", True, 'word'),
    ("CHF 95'000", True, 'amount'),
    ('Wir suchen eine Fachperson mit 5 Jahren Erfahrung, 100% Pensum.', False, None),
    ('', False, None),
])
def test_the_salary_flag_is_a_stated_rule_with_its_match_recorded(text, expected, rule):
    """A deterministic rule, not a model and not a parse of an amount: it
    answers "is there a salary statement in here at all", which is what a
    stratified sample needs."""
    signal = export.salary_signal(text)
    assert signal['has_salary'] is expected
    assert signal['rule'] == rule
    assert (signal['quote'] is not None) is expected


def test_a_position_that_cannot_be_mapped_is_not_counted_as_a_broken_feed(store):
    """The spec's parse-success rate is counted over FEEDS. Folding a
    position that could not be mapped into the feed failures would make
    one bad position look like a broken feed -- or several of them look
    like more broken feeds than were fetched."""
    feed = ('<?xml version="1.0" encoding="UTF-8"?>\n<workzag-jobs>\n'
            '<position><name>No id at all</name></position>\n'
            '<position><name>Also no id</name></position>\n'
            '<position><id>7</id><name>Fine</name><office>CH - Zürich</office></position>\n'
            '</workzag-jobs>\n')
    server = FakePersonio(bodies={('acme', 'de'): feed})
    result = fetch(store, 'acme', server=server, languages=('de',))
    assert result['fetch_status'] == 'ok', 'the feed itself parsed'
    assert result['parse_failures'] == []
    assert len(result['posting_failures']) == 2
    assert all('no id' in failure['reason'] for failure in result['posting_failures'])
    assert [posting['posting_id'] for posting in result['postings']] == ['7']
