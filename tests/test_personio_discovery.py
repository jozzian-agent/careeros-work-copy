"""Tenant discovery: the four routes, the index parse, the dedupe.

No live calls: every fetch here is a transport the test supplies, which
is the whole reason `careeros.feeds.discovery` takes one.
"""
import json

import pytest

from careeros.feeds import discovery


def transport(answers, *, record=None):
    """A `polite_http.request_text` stand-in answering out of a dict.

    `answers` maps a URL to a response dict, or to a LIST of them for a
    URL that is asked more than once -- which is what the retry tests
    need, because the real CDX API 504s and then succeeds.
    """
    def fetch(url, *, limiter=None, headers=None, timeout=None, max_body=None):
        if record is not None:
            record.append(url)
        answer = answers.get(url, {'ok': False, 'status': 404, 'text': '',
                                   'error': 'HTTP 404', 'headers': {}})
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        return {'final_url': url, 'headers': {}, **answer}
    return fetch


def ok(text):
    return {'ok': True, 'status': 200, 'text': text, 'error': None}


# --- reading a tenant out of a URL -------------------------------------------

def test_a_posting_url_is_the_confident_reading_and_reuses_detect_ats():
    """`org_intake.ats.detect_ats` already recognises Personio and
    already extracts the tenant, so nothing here re-implements it."""
    match = discovery.tenant_from_url(
        'https://bring-labs.jobs.personio.de/job/2726475?language=en')
    assert match == {'tenant': 'bring-labs', 'host': 'jobs.personio.de',
                     'how': 'posting_url'}


def test_a_bare_career_site_link_is_read_from_the_host():
    """`detect_ats` wants a posting-shaped URL on purpose, so route 2's
    "a careers page links to *.jobs.personio.de" needs the host reading."""
    assert discovery.tenant_from_url('https://acme.jobs.personio.de/') == \
        {'tenant': 'acme', 'host': 'jobs.personio.de', 'how': 'host_pattern'}
    assert discovery.tenant_from_url('https://acme.jobs.personio.com/job/1')['how'] == \
        'posting_url'


@pytest.mark.parametrize('url', [
    'https://careers.acme.jobs.personio.de/',   # a nested label is not a tenant id
    'https://evil.example.com/?x=jobs.personio.de',
    'https://jobs.personio.de/',                # the vendor's own host, no tenant
    'https://boards.greenhouse.io/acme/jobs/1',
    'not a url', '', None,
])
def test_anything_that_is_not_a_personio_tenant_url_gives_nothing(url):
    assert discovery.tenant_from_url(url) is None


def test_a_list_of_urls_becomes_one_entry_per_tenant_with_its_evidence():
    found = discovery.tenants_from_urls(
        ['https://acme.jobs.personio.de/job/1', 'https://acme.jobs.personio.de/job/2',
         'https://brue.jobs.personio.de/', 'https://example.com'],
        discovered_via='company_website', company='Acme AG')
    assert sorted(found) == ['acme', 'brue']
    assert found['acme']['evidence'] == 'https://acme.jobs.personio.de/job/1'
    assert found['acme']['company_name'] == 'Acme AG'
    assert found['acme']['discovered_via'] == 'company_website'


# --- route 1: the existing universe ------------------------------------------

def test_a_stored_ats_identifier_and_a_stored_website_both_name_a_tenant():
    companies = [
        {'name': 'Acme AG', 'website': 'https://acme.jobs.personio.de/job/9',
         'identifiers': [{'type': 'ats_tenant', 'value': 'personio:acme'}]},
        {'name': 'Brue GmbH', 'website': 'https://brue.example.com',
         'identifiers': [{'type': 'ats_tenant', 'value': 'personio:brue'}]},
        {'name': 'Other', 'website': 'https://other.example.com', 'identifiers': []},
    ]
    found = discovery.tenants_from_vault(companies)
    assert sorted(found) == ['acme', 'brue']
    assert found['brue']['how'] == 'stored_identifier'
    assert found['brue']['company_name'] == 'Brue GmbH'


def test_a_stored_personio_job_names_its_tenant():
    """The live vault's own `head-of-product` job carries
    `ats_provider: personio` and `ats_tenant: bring-labs`."""
    jobs = [{'ats_provider': 'personio', 'ats_tenant': 'bring-labs',
             'url': 'https://bring-labs.jobs.personio.de/job/2726475?language=en'},
            {'ats_provider': 'greenhouse', 'ats_tenant': 'other', 'url': 'https://x/'}]
    found = discovery.tenants_from_vault([], jobs)
    assert sorted(found) == ['bring-labs']
    assert found['bring-labs']['discovered_via'] == 'vault_job'


def test_a_tenant_id_that_is_not_shaped_like_one_is_not_taken_from_a_record():
    companies = [{'name': 'X', 'identifiers': [{'type': 'ats_tenant',
                                                'value': 'personio:Not A Tenant'}]}]
    assert discovery.tenants_from_vault(companies) == {}


def test_a_vault_with_nothing_personio_in_it_discovers_nothing():
    assert discovery.tenants_from_vault([{'name': 'X', 'website': 'https://x.example'}]) == {}


# --- route 3: the Common Crawl index -----------------------------------------

def cdx_lines(*urls):
    return '\n'.join(json.dumps({'url': url}) for url in urls)


def test_the_index_lines_become_tenants():
    tenants, stats = discovery.tenants_from_cdx_lines(
        cdx_lines('https://acme.jobs.personio.de/job/1',
                  'https://acme.jobs.personio.de/',
                  'https://brue.jobs.personio.de/jobs',
                  'https://not-personio.example.com/').splitlines(),
        discovered_via='common_crawl:CC-MAIN-2026-39')
    assert sorted(tenants) == ['acme', 'brue']
    assert stats == {'urls': 4, 'malformed': 0, 'truncated': False}
    assert tenants['acme']['discovered_via'] == 'common_crawl:CC-MAIN-2026-39'


def test_a_body_cut_mid_object_is_reported_as_truncated():
    """Measured on the live trial: one index page came back short, and a
    page that ends mid-object would silently drop every tenant after the
    cut if nobody looked."""
    text = cdx_lines('https://acme.jobs.personio.de/job/1',
                     'https://brue.jobs.personio.de/job/2') + '\n{"url": "https://cut.jobs.pe'
    tenants, stats = discovery.tenants_from_cdx_lines(text.splitlines(),
                                                      discovered_via='x')
    assert sorted(tenants) == ['acme', 'brue'], 'the tenants that did arrive are kept'
    assert stats['truncated'] is True
    assert stats['malformed'] == 1


def test_a_malformed_line_in_the_middle_is_counted_but_not_a_truncation():
    text = '\n'.join(['{"url": "https://acme.jobs.personio.de/job/1"}', 'nonsense',
                      '{"url": "https://brue.jobs.personio.de/job/2"}'])
    tenants, stats = discovery.tenants_from_cdx_lines(text.splitlines(), discovered_via='x')
    assert sorted(tenants) == ['acme', 'brue']
    assert stats == {'urls': 2, 'malformed': 1, 'truncated': False}


def test_the_index_is_queried_page_by_page_and_the_tenants_are_merged():
    answers = {}
    for domain in discovery.CDX_DOMAINS:
        answers[discovery._cdx_query('CC', domain, showNumPages='true')] = \
            ok(json.dumps({'pages': 2, 'pageSize': 5, 'blocks': 3}))
    answers[discovery._cdx_query('CC', 'jobs.personio.de', fl='url', page='0')] = \
        ok(cdx_lines('https://acme.jobs.personio.de/job/1'))
    answers[discovery._cdx_query('CC', 'jobs.personio.de', fl='url', page='1')] = \
        ok(cdx_lines('https://brue.jobs.personio.de/job/2'))
    answers[discovery._cdx_query('CC', 'jobs.personio.com', fl='url', page='0')] = \
        ok(cdx_lines('https://cee.jobs.personio.com/job/3'))
    answers[discovery._cdx_query('CC', 'jobs.personio.com', fl='url', page='1')] = ok('')
    tenants, report = discovery.cdx_tenants('CC', fetch=transport(answers),
                                            sleep=lambda seconds: None)
    assert sorted(tenants) == ['acme', 'brue', 'cee']
    assert report['urls'] == 3
    assert report['failed_pages'] == 0
    assert report['crawl'] == 'CC'
    assert report['terms'] == discovery.CDX_TERMS


def test_a_page_that_never_comes_back_is_counted_as_lost_and_not_as_empty():
    """The spec's open question is how many tenants the query returns,
    and a number with unknown gaps in it is not an answer."""
    answers = {discovery._cdx_query('CC', domain, showNumPages='true'):
               ok(json.dumps({'pages': 1})) for domain in discovery.CDX_DOMAINS}
    answers[discovery._cdx_query('CC', 'jobs.personio.de', fl='url', page='0')] = \
        {'ok': False, 'status': 504, 'text': '', 'error': 'HTTP 504'}
    answers[discovery._cdx_query('CC', 'jobs.personio.com', fl='url', page='0')] = \
        ok(cdx_lines('https://cee.jobs.personio.com/job/3'))
    tenants, report = discovery.cdx_tenants('CC', fetch=transport(answers),
                                            sleep=lambda seconds: None)
    assert sorted(tenants) == ['cee']
    assert report['failed_pages'] == 1


def test_a_504_then_a_200_is_retried_with_backoff():
    """The API 504s often enough that a single attempt is not a
    measurement. The spec also says retries must back off exponentially."""
    url = discovery._cdx_query('CC', 'jobs.personio.de', fl='url', page='0')
    answers = {url: [{'ok': False, 'status': 504, 'text': '', 'error': 'HTTP 504'},
                     ok(cdx_lines('https://acme.jobs.personio.de/job/1'))]}
    slept = []
    result = discovery._with_retry(url, fetch=transport(answers), sleep=slept.append)
    assert result['ok'] is True
    assert result['attempts'] == 2
    assert slept == [discovery.CDX_BACKOFF]


def test_retries_are_capped_and_the_last_failure_is_what_is_reported():
    url = 'https://index.commoncrawl.org/x'
    answers = {url: [{'ok': False, 'status': 504, 'text': '', 'error': 'HTTP 504'}]}
    slept = []
    result = discovery._with_retry(url, fetch=transport(answers), sleep=slept.append)
    assert result['ok'] is False
    assert result['attempts'] == discovery.CDX_ATTEMPTS
    assert slept == [discovery.CDX_BACKOFF * 2 ** power
                     for power in range(discovery.CDX_ATTEMPTS - 1)]
    assert slept == sorted(slept), 'exponential, so never faster than the last wait'


def test_the_collection_list_is_read_from_the_one_path_robots_allows():
    answers = {discovery.CDX_COLLECTIONS: ok(json.dumps([{'id': 'CC-MAIN-2026-39'}]))}
    assert discovery.cdx_collections(fetch=transport(answers)) == [{'id': 'CC-MAIN-2026-39'}]
    with pytest.raises(RuntimeError, match='collinfo failed'):
        discovery.cdx_collections(fetch=transport({}))


# --- merging, which has to be idempotent -------------------------------------

def test_merging_the_same_discovery_twice_changes_nothing():
    found = {'acme': {'tenant': 'acme', 'host': 'jobs.personio.de',
                      'discovered_via': 'vault_job', 'evidence': 'x', 'how': 'posting_url',
                      'company_name': None}}
    first, added = discovery.merge_tenants({}, found, first_seen='2026-10-17')
    assert added == ['acme']
    assert first['acme']['status'] == discovery.CANDIDATE
    second, added_again = discovery.merge_tenants(first, found, first_seen='2026-10-18')
    assert added_again == []
    assert second['acme']['first_seen'] == '2026-10-17', 'first seen is the FIRST run'


def test_a_second_route_finding_a_tenant_is_recorded_and_never_a_downgrade():
    stored = {'acme': {'tenant': 'acme', 'discovered_via': 'vault_job',
                       'status': discovery.CONFIRMED_ZURICH, 'first_seen': '2026-10-01',
                       'company_name': None, 'also_discovered_via': []}}
    merged, added = discovery.merge_tenants(stored, {
        'acme': {'tenant': 'acme', 'host': 'jobs.personio.de',
                 'discovered_via': 'common_crawl:CC', 'evidence': 'x',
                 'how': 'host_pattern', 'company_name': 'Acme AG'}},
        first_seen='2026-10-17')
    assert added == []
    assert merged['acme']['status'] == discovery.CONFIRMED_ZURICH
    assert merged['acme']['also_discovered_via'] == ['common_crawl:CC']
    assert merged['acme']['company_name'] == 'Acme AG', 'an empty name is filled in'


# --- the Zefix dedupe, which is a candidate and never a fact ------------------

def test_a_shared_normalised_name_is_a_candidate_and_not_a_duplicate():
    """PROJECT.md's ambiguity rule, and the Zefix seeder's own note:
    "Meier AG" in Zurich is several unrelated companies."""
    matches = discovery.zefix_matches(
        {'bring-labs': {'company_name': 'Bring! Labs AG'}},
        [{'name': 'BRING LABS ag', 'uid': 'CHE-123.456.789', 'seat': 'Zürich'},
         {'name': 'Unrelated AG', 'uid': 'CHE-000', 'seat': 'Zürich'}])
    assert matches['bring-labs']['confident'] is False
    assert matches['bring-labs']['matched_on'] == 'name'
    assert matches['bring-labs']['normalized_name'] == 'bring labs ag'
    assert [item['uid'] for item in matches['bring-labs']['candidates']] == \
        ['CHE-123.456.789']


def test_several_seeded_entities_sharing_a_name_are_all_listed():
    matches = discovery.zefix_matches(
        {'meier': {'company_name': 'Meier AG'}},
        [{'name': 'Meier AG', 'uid': 'CHE-1', 'seat': 'Zürich'},
         {'name': 'MEIER AG', 'uid': 'CHE-2', 'seat': 'Winterthur'}])
    assert len(matches['meier']['candidates']) == 2
    assert matches['meier']['confident'] is False


def test_a_tenant_with_no_company_name_matches_nothing():
    assert discovery.zefix_matches({'acme': {'company_name': None}},
                                   [{'name': 'Acme AG', 'uid': 'CHE-1'}]) == {}
    assert discovery.zefix_matches({'acme': {'company_name': 'Acme AG'}}, []) == {}


def test_the_normalisation_rule_is_the_capabilitys_own():
    assert discovery._normalized_name('Acme, Inc.') == 'acme inc'
    assert discovery._normalized_name('ACME  INC') == 'acme inc'
    assert discovery._normalized_name(None) == ''
