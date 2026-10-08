"""JOZ-265: URL normalization and ATS detection. Pure functions, no network."""
import pytest
from careeros import url_normalize


@pytest.mark.parametrize('url,expected', [
    ('https://Example.com/Role/', 'https://example.com/Role'),
    ('http://example.com', 'http://example.com/'),
    ('https://example.com:443/role', 'https://example.com/role'),
    ('http://example.com:80/role', 'http://example.com/role'),
    ('https://example.com:8080/role', 'https://example.com:8080/role'),
])
def test_scheme_host_and_slash_normalization(url, expected):
    assert url_normalize.normalize(url) == expected


def test_fragment_is_stripped():
    assert url_normalize.normalize('https://example.com/role#apply-section') == 'https://example.com/role'


@pytest.mark.parametrize('param', ['utm_source', 'utm_campaign', 'utm_medium', 'gclid', 'fbclid',
                                   'msclkid', 'igshid', 'mc_cid', 'ref', '_ga'])
def test_tracking_params_are_stripped(param):
    normalized = url_normalize.normalize(f'https://example.com/role?{param}=abc123')
    assert normalized == 'https://example.com/role'


@pytest.mark.parametrize('param', ['gh_jid', 'jobId', 'posting_id', 'jvi'])
def test_non_tracking_params_are_preserved(param):
    normalized = url_normalize.normalize(f'https://example.com/role?{param}=4242')
    assert normalized == f'https://example.com/role?{param}=4242'


def test_param_sort_is_stable_regardless_of_input_order():
    first = url_normalize.normalize('https://example.com/role?b=2&a=1&utm_source=x')
    second = url_normalize.normalize('https://example.com/role?utm_source=y&a=1&b=2')
    assert first == second == 'https://example.com/role?a=1&b=2'


def test_posting_id_param_survives_alongside_tracking_params():
    normalized = url_normalize.normalize('https://boards.greenhouse.io/embed/job_app?for=acme&gh_jid=1234&utm_source=linkedin')
    assert 'gh_jid=1234' in normalized and 'utm_source' not in normalized


def test_empty_url_normalizes_to_empty_string():
    assert url_normalize.normalize('') == ''
    assert url_normalize.normalize(None) == ''


@pytest.mark.parametrize('url,provider,tenant,posting_id', [
    ('https://boards.greenhouse.io/acme/jobs/123456', 'greenhouse', 'acme', '123456'),
    ('https://jobs.lever.co/acme/8a6e9c2e-uuid-posting', 'lever', 'acme', '8a6e9c2e-uuid-posting'),
    ('https://acme.personio.de/job/987654', 'personio', 'acme', '987654'),
    ('https://acme.wd1.myworkdayjobs.com/en-US/External/job/Zurich/Software-Engineer_R-1234', 'workday', 'acme', 'R-1234'),
    ('https://jobs.smartrecruiters.com/Acme/743999881234567-software-engineer', 'smartrecruiters', 'Acme', '743999881234567'),
    ('https://jobs.ashbyhq.com/acme/8a6e9c2e-uuid-posting', 'ashby', 'acme', '8a6e9c2e-uuid-posting'),
    ('https://acme.recruitee.com/o/software-engineer-zurich', 'recruitee', 'acme', 'software-engineer-zurich'),
    ('https://acme.teamtailor.com/jobs/123456-software-engineer', 'teamtailor', 'acme', '123456'),
    ('https://acme.join.com/jobs/123456-software-engineer', 'join', 'acme', '123456'),
])
def test_ats_detection_one_fixture_per_provider(url, provider, tenant, posting_id):
    match = url_normalize.detect_ats(url)
    assert match is not None
    assert (match.provider, match.tenant, match.posting_id) == (provider, tenant, posting_id)


@pytest.mark.parametrize('url', [
    'https://example.com/careers/role',
    'https://careers.acme.com/jobs/123',
])
def test_ats_detection_returns_none_for_unrecognized_hosts(url):
    assert url_normalize.detect_ats(url) is None


# JOZ-265 fix round, M4: host matching must be an exact match or a
# dot-prefixed suffix, never a bare substring; a lookalike host must never
# be recognized as the provider it merely contains as text.
@pytest.mark.parametrize('url', [
    'https://a.myworkdayjobs.com.attacker.example/job/Role_R123',
    'https://evil.example/a.myworkdayjobs.com/job/Role_R123',
    'https://notboards.greenhouse.io/acme/jobs/123',
    'https://notjobs.lever.co/acme/123',
    'https://notjobs.ashbyhq.com/acme/123',
    'https://notjobs.smartrecruiters.com/acme/123',
    'https://evil-personio.de/job/123',
    'https://evil-recruitee.com/o/role',
    'https://evil-teamtailor.com/jobs/123-role',
    'https://evil-join.com/jobs/123-role',
])
def test_ats_detection_rejects_lookalike_hosts(url):
    assert url_normalize.detect_ats(url) is None


@pytest.mark.parametrize('url,provider,tenant,posting_id', [
    ('https://acme.wd1.myworkdayjobs.com/en-US/External?jobId=R-1234', 'workday', 'acme', 'R-1234'),
    ('https://acme.personio.de/job?jobId=123', 'personio', 'acme', '123'),
    ('https://join.com/companies/acme/123456-software-engineer', 'join', 'acme', '123456'),
])
def test_ats_detection_query_and_root_forms(url, provider, tenant, posting_id):
    # m9: provider identity forms that live in the query string or (for
    # join.com) the bare root domain, not only the path/subdomain forms
    # already covered above.
    match = url_normalize.detect_ats(url)
    assert match is not None
    assert (match.provider, match.tenant, match.posting_id) == (provider, tenant, posting_id)


@pytest.mark.parametrize('url', [
    'https://acme.wd1.myworkdayjobs.com/en-US/External?ref=abc',
    'https://acme.personio.de/job?ref=abc',
    'https://join.com/companies/acme/not-a-numeric-id',
    'https://join.com/companies',
])
def test_ats_detection_query_forms_do_not_misfire_on_unrelated_params(url):
    # Only the documented, known provider ID query params are recognized;
    # an unrelated query param (or a missing/malformed id) must not guess.
    assert url_normalize.detect_ats(url) is None
