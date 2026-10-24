"""URL normalization. Pure functions, no network.

Ported from careeros tests/test_url_normalize.py's normalize() cases.
Rule coverage: supports rule 1 (loose input never rejected) by never
raising; underlies identity.py's domain-identifier rung (rule 3).
"""
import pytest

from org_intake import url


@pytest.mark.parametrize('input_url,expected', [
    ('https://Example.com/Role/', 'https://example.com/Role'),
    ('http://example.com', 'http://example.com/'),
    ('https://example.com:443/role', 'https://example.com/role'),
    ('http://example.com:80/role', 'http://example.com/role'),
    ('https://example.com:8080/role', 'https://example.com:8080/role'),
])
def test_scheme_host_and_slash_normalization(input_url, expected):
    assert url.normalize_url(input_url) == expected


def test_fragment_is_stripped():
    assert url.normalize_url('https://example.com/role#apply-section') == 'https://example.com/role'


@pytest.mark.parametrize('param', ['utm_source', 'utm_campaign', 'utm_medium', 'gclid', 'fbclid',
                                   'msclkid', 'igshid', 'mc_cid', 'ref', '_ga'])
def test_tracking_params_are_stripped(param):
    normalized = url.normalize_url(f'https://example.com/role?{param}=abc123')
    assert normalized == 'https://example.com/role'


@pytest.mark.parametrize('param', ['gh_jid', 'jobId', 'posting_id', 'jvi'])
def test_non_tracking_params_are_preserved(param):
    normalized = url.normalize_url(f'https://example.com/role?{param}=4242')
    assert normalized == f'https://example.com/role?{param}=4242'


def test_param_sort_is_stable_regardless_of_input_order():
    first = url.normalize_url('https://example.com/role?b=2&a=1&utm_source=x')
    second = url.normalize_url('https://example.com/role?utm_source=y&a=1&b=2')
    assert first == second == 'https://example.com/role?a=1&b=2'


def test_posting_id_param_survives_alongside_tracking_params():
    normalized = url.normalize_url(
        'https://boards.greenhouse.io/embed/job_app?for=acme&gh_jid=1234&utm_source=linkedin')
    assert 'gh_jid=1234' in normalized and 'utm_source' not in normalized


def test_empty_url_normalizes_to_empty_string():
    # Rule 1: loose input is never rejected, never raises.
    assert url.normalize_url('') == ''
    assert url.normalize_url(None) == ''


def test_domain_never_raises_on_structurally_malformed_url():
    # 'https://[broken' raises ValueError out of urlsplit itself (an
    # unparseable IPv6 host literal) - domain() must degrade to '', never
    # raise (M8).
    assert url.domain('https://[broken') == ''


@pytest.mark.parametrize('input_url,expected', [
    ('https://boards.greenhouse.io/acme/jobs/123456', 'greenhouse.io'),
    ('https://dune-logistics.example/careers/role-a', 'dune-logistics.example'),
    ('https://careers.acme.co.uk/jobs/1', 'acme.co.uk'),
])
def test_domain_extracts_registrable_domain(input_url, expected):
    assert url.domain(input_url) == expected
