"""ATS (applicant tracking system) detection. Pure function, no network.

Ported from careeros tests/test_url_normalize.py's detect_ats() cases,
adapted to the contract's {"provider", "tenant"} return shape (no
posting-id - the contract's "Not included" keeps that product-owned).
Rule coverage: rule 3 (rung 1/2 identifier lookups are ATS-tenant or
domain keyed).
"""
import pytest

from org_intake.ats import detect_ats


@pytest.mark.parametrize('input_url,provider,tenant', [
    ('https://boards.greenhouse.io/acme/jobs/123456', 'greenhouse', 'acme'),
    ('https://jobs.lever.co/acme/8a6e9c2e-uuid-posting', 'lever', 'acme'),
    ('https://acme.personio.de/job/987654', 'personio', 'acme'),
    ('https://acme.wd1.myworkdayjobs.com/en-US/External/job/Zurich/Software-Engineer_R-1234', 'workday', 'acme'),
    ('https://jobs.smartrecruiters.com/Acme/743999881234567-software-engineer', 'smartrecruiters', 'Acme'),
    ('https://jobs.ashbyhq.com/acme/8a6e9c2e-uuid-posting', 'ashby', 'acme'),
    ('https://acme.recruitee.com/o/software-engineer-zurich', 'recruitee', 'acme'),
    ('https://acme.teamtailor.com/jobs/123456-software-engineer', 'teamtailor', 'acme'),
    ('https://acme.join.com/jobs/123456-software-engineer', 'join', 'acme'),
])
def test_ats_detection_one_fixture_per_provider(input_url, provider, tenant):
    assert detect_ats(input_url) == {'provider': provider, 'tenant': tenant}


@pytest.mark.parametrize('input_url', [
    'https://example.com/careers/role',
    'https://careers.acme.com/jobs/123',
])
def test_ats_detection_returns_none_for_unrecognized_hosts(input_url):
    assert detect_ats(input_url) is None


# Host matching must be an exact match or a dot-prefixed suffix, never a
# bare substring; a lookalike host must never be recognized as the
# provider it merely contains as text.
@pytest.mark.parametrize('input_url', [
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
def test_ats_detection_rejects_lookalike_hosts(input_url):
    assert detect_ats(input_url) is None


@pytest.mark.parametrize('input_url,provider,tenant', [
    ('https://acme.wd1.myworkdayjobs.com/en-US/External?jobId=R-1234', 'workday', 'acme'),
    ('https://acme.personio.de/job?jobId=123', 'personio', 'acme'),
    ('https://join.com/companies/acme/123456-software-engineer', 'join', 'acme'),
])
def test_ats_detection_query_and_root_forms(input_url, provider, tenant):
    assert detect_ats(input_url) == {'provider': provider, 'tenant': tenant}


@pytest.mark.parametrize('input_url', [
    'https://acme.wd1.myworkdayjobs.com/en-US/External?ref=abc',
    'https://acme.personio.de/job?ref=abc',
    'https://join.com/companies/acme/not-a-numeric-id',
    'https://join.com/companies',
])
def test_ats_detection_query_forms_do_not_misfire_on_unrelated_params(input_url):
    assert detect_ats(input_url) is None


@pytest.mark.parametrize('input_url', [
    'https://m.refline.ch/792841/11410/pub/1/index.html',
    'https://apply.refline.ch/792841/11410/pub/1',
    'https://www.refline.ch/792841/11410/pub/1/',
    'https://refline.ch/792841/11410/pub/1',
    'https://careers.refline.ch/792841/11410/pub/1/index.html/',
])
def test_refline_detection_acceptance_and_host_variants(input_url):
    assert detect_ats(input_url) == {'provider': 'refline', 'tenant': '792841'}


@pytest.mark.parametrize('input_url', [
    'https://refline.ch.attacker.example/792841/11410/pub/1',
    'https://notrefline.ch/792841/11410/pub/1',
    'https://m.refline.ch.attacker.example/792841/11410/pub/1',
])
def test_refline_rejects_lookalike_hosts(input_url):
    assert detect_ats(input_url) is None


@pytest.mark.parametrize('path', [
    '/', '/about', '/about/product/pub/1', '/792841',
    '/792841/11410', '/792841/pub/1', '/792841/11410/pub',
    '/792841/11410/pub/index.html',
])
def test_refline_unrelated_paths_have_no_identity(path):
    assert detect_ats('https://refline.ch' + path) is None


def test_detect_ats_never_raises_on_structurally_malformed_url():
    # 'https://[broken' raises ValueError out of urlsplit itself (an
    # unparseable IPv6 host literal) - detect_ats must degrade to "no
    # match," never raise (M8).
    assert detect_ats('https://[broken') is None
