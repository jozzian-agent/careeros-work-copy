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


@pytest.mark.parametrize('url', [
    'https://m.refline.ch/792841/11410/pub/1/index.html',
    'https://apply.refline.ch/792841/11410/pub/1',
    'https://www.refline.ch/792841/11410/pub/1/',
    'https://refline.ch/792841/11410/pub/1',
    'https://careers.refline.ch/792841/11410/pub/1/index.html/',
])
def test_refline_detection_acceptance_and_host_variants(url):
    assert url_normalize.detect_ats(url) == url_normalize.AtsMatch(
        'refline', '792841', '11410/pub/1')


@pytest.mark.parametrize('url', [
    'https://refline.ch.attacker.example/792841/11410/pub/1',
    'https://notrefline.ch/792841/11410/pub/1',
    'https://m.refline.ch.attacker.example/792841/11410/pub/1',
])
def test_refline_rejects_lookalike_hosts(url):
    assert url_normalize.detect_ats(url) is None


@pytest.mark.parametrize('path', [
    '/', '/about', '/about/product/pub/1', '/792841',
    '/792841/11410', '/792841/pub/1', '/792841/11410/pub',
    '/792841/11410/pub/index.html',
])
def test_refline_unrelated_paths_have_no_identity(path):
    assert url_normalize.detect_ats('https://refline.ch' + path) is None


def test_refline_cross_subdomain_hard_duplicate(tmp_path):
    from careeros import vault
    from careeros.server import create_app

    client = create_app(tmp_path).test_client()
    first = client.post('/api/jobs/intake', json={
        'url': 'https://m.refline.ch/792841/11410/pub/1/index.html'})
    assert first.status_code == 201
    second = client.post('/api/jobs/intake', json={
        'url': 'https://apply.refline.ch/792841/11410/pub/1'})
    assert second.status_code == 200
    assert second.json['duplicate'] is True
    assert second.json['basis'] == 'same_ats_posting_id'
    assert second.json['existing']['id'] == first.json['job']['id']
    assert second.json['actions'] == ['open_existing', 'add_anyway']
    assert len(vault.list_jobs(tmp_path)) == 1


def test_refline_same_posting_different_tenant_is_not_duplicate(tmp_path):
    from careeros import vault
    from careeros.server import create_app

    client = create_app(tmp_path).test_client()
    first = client.post('/api/jobs/intake', json={
        'url': 'https://m.refline.ch/792841/11410/pub/1/index.html'})
    second = client.post('/api/jobs/intake', json={
        'url': 'https://apply.refline.ch/792842/11410/pub/1'})
    assert first.status_code == second.status_code == 201
    assert second.json.get('duplicate') is not True
    assert second.json['job']['id'] != first.json['job']['id']
    assert len(vault.list_jobs(tmp_path)) == 2


@pytest.mark.parametrize('missing_fields', [False, True])
def test_refline_startup_migration_backfills_identity(tmp_path, missing_fields):
    import yaml
    from careeros import dedupe, vault
    from careeros.server import create_app

    job = vault.save_job(tmp_path, {
        'title': 'Fixture role',
        'url': 'https://m.refline.ch/792841/11410/pub/1/index.html',
    })
    keys = ('ats_provider', 'ats_tenant', 'ats_posting_id')
    assert all(job[key] is None for key in keys)
    if missing_fields:
        path = next((tmp_path / 'jobs').glob('*.yaml'))
        data = yaml.safe_load(path.read_text())
        for key in keys:
            data.pop(key)
        path.write_text(yaml.safe_dump(data))

    create_app(tmp_path)
    migrated = vault.load_job(tmp_path, job['id'])
    assert tuple(migrated[key] for key in keys) == ('refline', '792841', '11410/pub/1')
    alternate = 'https://apply.refline.ch/792841/11410/pub/1'
    existing, basis = dedupe.find_duplicate(
        tmp_path, url_normalize.normalize(alternate), url_normalize.detect_ats(alternate))
    assert existing['id'] == job['id']
    assert basis == 'same_ats_posting_id'
    assert vault.migrate_job_fields(tmp_path) == []
