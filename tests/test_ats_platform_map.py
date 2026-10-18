"""The ATS platform map: which company uses which platform, and how
sure we are.

Owner ruling 2026-10-17, priority b. These tests pin the thing the map
would be useless without: four evidence levels that are never mixed, a
"not fetched" that is not folded into "no Zurich office", and a tracked
file that stays small while the full list keeps everything.
"""
import yaml

from careeros.feeds import platform_map
from careeros.feeds import store as store_module
from careeros.feeds.platform_map import CONFIRMED_LIVE, DEAD, INDEXED, RECORDED


def tenant(**overrides):
    entry = {'tenant': 'acme', 'host': 'boards.greenhouse.io',
             'discovered_via': 'common_crawl:CC-MAIN-2026-39',
             'evidence': 'https://boards.greenhouse.io/acme', 'how': 'board_url',
             'first_seen': '2026-10-17', 'status': 'candidate',
             'also_discovered_via': []}
    entry.update(overrides)
    return entry


def store_with(tmp_path, provider, tenants, *, meta=None, states=None):
    store = store_module.Store(tmp_path / provider, provider=provider)
    store.save_tenants({entry['tenant']: entry for entry in tenants}, meta=meta or {})
    for name, state in (states or {}).items():
        store.save_state({'tenant': name, 'provider': provider, 'postings': state})
    return store


def build(tmp_path, **stores):
    return platform_map.build(stores)


# --- the four confidence levels ----------------------------------------------

def test_a_fetched_feed_is_confirmed_live_and_a_404_is_dead(tmp_path):
    store = store_with(tmp_path, 'greenhouse', [
        tenant(tenant='live', last_fetch_status='ok', last_fetch_run='r1',
               postings_seen=3, zurich_postings_seen=2, municipalities=['261']),
        tenant(tenant='gone', last_fetch_status='not_found', last_fetch_run='r1',
               last_fetch_error='HTTP 404'),
    ])
    rows = {row['tenant']: row for row in platform_map.company_rows(store)}
    assert rows['live']['confidence'] == CONFIRMED_LIVE
    assert rows['live']['zurich'] == 'yes'
    assert rows['gone']['confidence'] == DEAD
    assert rows['gone']['last_fetch_error'] == 'HTTP 404'
    assert 'fetched and parsed' in rows['live']['confidence_means']


def test_a_vault_route_is_recorded_and_a_crawl_hit_is_only_observed(tmp_path):
    store = store_with(tmp_path, 'greenhouse', [
        tenant(tenant='stored', discovered_via='vault_identifier', how='stored_identifier'),
        tenant(tenant='linked', discovered_via='company_website', how='board_url'),
        tenant(tenant='indexed'),
    ])
    rows = {row['tenant']: row for row in platform_map.company_rows(store)}
    assert rows['stored']['confidence'] == RECORDED
    assert rows['linked']['confidence'] == RECORDED
    assert rows['indexed']['confidence'] == INDEXED
    assert 'Crawl index' in rows['indexed']['confidence_means']


def test_a_second_route_does_not_weaken_a_tenants_evidence(tmp_path):
    store = store_with(tmp_path, 'greenhouse', [
        tenant(tenant='both', discovered_via='common_crawl:CC-MAIN-2026-39',
               also_discovered_via=['vault_job']),
    ])
    row = platform_map.company_rows(store)[0]
    assert row['confidence'] == RECORDED, 'the strongest route a tenant has is what it is'
    assert row['also_discovered_via'] == ['vault_job']


def test_a_tenant_nobody_fetched_has_no_zurich_answer_at_all(tmp_path):
    """Folding "not fetched" into "no Zurich office" would make every
    undiscovered tenant look like a tenant without one, which is exactly
    the number the owner is trying to estimate."""
    store = store_with(tmp_path, 'greenhouse', [
        tenant(tenant='unasked'),
        tenant(tenant='asked', last_fetch_status='ok', postings_seen=4,
               zurich_postings_seen=0),
    ])
    rows = {row['tenant']: row for row in platform_map.company_rows(store)}
    assert rows['unasked']['zurich'] == 'not_fetched'
    assert rows['asked']['zurich'] == 'no'


def test_the_zurich_posting_count_comes_from_the_posting_state(tmp_path):
    store = store_with(tmp_path, 'lever', [tenant(tenant='acme', last_fetch_status='ok')],
                       states={'acme': {
                           'lever:acme:1': {'status': 'open', 'canton': '1'},
                           'lever:acme:2': {'status': 'suspected_closing', 'canton': '1'},
                           'lever:acme:3': {'status': 'closed', 'canton': '1'},
                           'lever:acme:4': {'status': 'open', 'canton': '2'}}})
    row = platform_map.company_rows(store)[0]
    assert row['zurich'] == 'yes'
    assert row['zurich_postings'] == 3, 'a closed Zurich posting still happened here'
    assert row['postings_open'] == 3, 'suspected closing is still open'


# --- the map as a whole ------------------------------------------------------

def test_the_map_totals_add_up_per_provider_and_over_all_of_them(tmp_path):
    built = build(
        tmp_path,
        greenhouse=store_with(tmp_path, 'greenhouse', [
            tenant(tenant='live', last_fetch_status='ok', zurich_postings_seen=2),
            tenant(tenant='dead', last_fetch_status='not_found'),
            tenant(tenant='indexed')]),
        workday=store_with(tmp_path, 'workday', [
            tenant(tenant='acme', host='acme.wd3.myworkdayjobs.com',
                   discovered_via='common_crawl:CC-MAIN-2026-39')],
            meta={'fetchable': False}))
    assert built['totals'] == {
        'companies': 4, 'providers': 2, 'confirmed_live': 1, 'dead': 1, 'recorded': 0,
        'indexed_only': 2, 'zurich_tenants': 1, 'zurich_postings': 2}
    assert built['providers']['greenhouse']['tenants'] == 3
    assert built['providers']['greenhouse']['fetchable'] is True
    assert built['providers']['workday']['fetchable'] is False, \
        'counted from the index, never fetched'
    assert built['providers']['workday']['confirmed_live'] == 0


def test_the_map_says_how_much_of_the_index_it_actually_read(tmp_path):
    """A share computed over a capped sweep is not a census, and the
    report has to be able to say so."""
    store = store_with(tmp_path, 'greenhouse', [tenant()], meta={'discovery_routes': {
        'common_crawl': {'crawls': ['CC-MAIN-2026-39'], 'urls': 1200, 'failed_pages': 1,
                         'per_crawl': [{'pages': [{'domain': 'boards.greenhouse.io',
                                                   'available': 6, 'queried': 2}]}]},
        'vault': {'tenants': 2}}})
    discovery = platform_map.build({'greenhouse': store})['providers']['greenhouse']['discovery']
    assert discovery['index_pages_available'] == 6
    assert discovery['index_pages_read'] == 2
    assert discovery['index_pages_lost'] == 1
    assert discovery['indexed_urls_read'] == 1200
    assert discovery['from_vault'] == 2
    assert sorted(discovery['routes']) == ['common_crawl', 'vault']


def test_the_vault_probe_file_names_the_company_behind_a_tenant(tmp_path):
    probe = tmp_path / 'probe.yaml'
    store_module.write_yaml(probe, {
        'probed_at': '2026-10-17T12:00:00+00:00',
        'from_websites': {'ashby': [{'tenant': 'kraken.com', 'company_name': 'Kraken',
                                     'evidence': 'https://jobs.ashbyhq.com/kraken.com'}]}})
    store = store_with(tmp_path, 'ashby', [tenant(tenant='kraken.com')])
    built = platform_map.build({'ashby': store}, probe_file=probe)
    row = built['companies'][0]
    assert row['vault_company'] == 'Kraken'
    assert row['company_name'] == 'Kraken'


# --- the two files and the report --------------------------------------------

def test_the_tracked_file_keeps_the_evidence_and_samples_the_rest(tmp_path):
    """The tracked map has to stay small: a crawl sweep names tens of
    thousands of tenants and the owner reads this file."""
    store = store_with(tmp_path, 'greenhouse',
                       [tenant(tenant='live', last_fetch_status='ok')]
                       + [tenant(tenant=f'indexed-{index:03d}') for index in range(40)])
    built = platform_map.build({'greenhouse': store})
    small = platform_map.tracked(built, sample=5)
    assert len(built['companies']) == 41
    assert len(small['companies']) == 6, 'the fetched one plus five sampled'
    assert small['totals']['companies'] == 41, 'the totals still count everything'
    assert sum(1 for row in small['companies'] if row.get('sampled')) == 5
    assert 'full list' in small['tracked_note']


def test_writing_the_map_leaves_three_files_and_a_readable_report(tmp_path):
    store = store_with(tmp_path, 'greenhouse', [
        tenant(tenant='live', last_fetch_status='ok', zurich_postings_seen=2,
               municipalities=['261'], company_name='Acme AG'),
        tenant(tenant='indexed')])
    built = platform_map.build({'greenhouse': store}, day='2026-10-17')
    paths = platform_map.write(built, map_path=tmp_path / 'map.yaml',
                               full=tmp_path / 'full.yaml',
                               report=tmp_path / 'report.md')
    stored = yaml.safe_load(paths['map'].read_text())
    assert stored['day'] == '2026-10-17'
    assert stored['totals']['companies'] == 2
    assert set(stored['confidence_levels']) == {CONFIRMED_LIVE, DEAD, RECORDED, INDEXED}
    assert yaml.safe_load(paths['full'].read_text())['companies']

    report = paths['report'].read_text()
    assert '# ATS platform map, 2026-10-17' in report
    assert 'CAREER-52' in report, 'it supersedes the old vault-domain probe and says so'
    assert '| greenhouse' in report
    assert 'Acme AG' in report
    assert 'observed_in_crawl_index' in report
    assert 'a tenant nobody fetched has no Zurich' in report.replace('\n', ' ')


def test_the_report_says_so_when_no_tenant_has_a_zurich_posting(tmp_path):
    store = store_with(tmp_path, 'join', [tenant(tenant='acme', host='acme.join.com')])
    report = platform_map.render(platform_map.build({'join': store}, day='2026-10-17'))
    assert 'No tenant has a confirmed Zurich posting yet.' in report
    assert 'No vault company resolved to a tenant in this run.' in report
