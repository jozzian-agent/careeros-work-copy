"""The adapter contract: what no provider adapter is allowed to skip.

CAREER-54's first deliverable is that provider specifics live behind one
contract. These tests are what makes that a contract rather than a
convention: they run over EVERY registered adapter, so a seventh
provider cannot half-exist, and they pin the one rule the owner asked
for by name -- a posting with no source chain does not reach the store.
"""
import pytest

from careeros.feeds import base, fetch as fetch_module, geocode, personio, registry
from careeros.feeds import store as store_module

PROVIDERS = list(registry.PROVIDERS)


@pytest.fixture
def store(tmp_path):
    return store_module.Store(tmp_path / 'ats', provider='greenhouse')


# --- the contract itself -----------------------------------------------------

@pytest.mark.parametrize('provider', PROVIDERS)
def test_every_registered_adapter_satisfies_the_contract(provider):
    """`base.check_adapter` is the list; this is the assertion. A new
    adapter that forgets its documentation URL, its tenant pattern or
    its crawl patterns fails here before anything is fetched through
    it."""
    assert base.check_adapter(registry.adapter(provider)) == []


@pytest.mark.parametrize('provider', PROVIDERS)
def test_every_adapter_cites_the_documentation_it_was_built_from(provider):
    """Owner ruling 2026-10-17: a stored posting carries its whole source
    chain, and which documented endpoint it came from is part of it."""
    adapter = registry.adapter(provider)
    assert adapter.DOC_URL.startswith('https://')
    assert adapter.DOC_ACCESSED == '2026-10-17', 'the day the endpoint docs were read'


@pytest.mark.parametrize('provider', PROVIDERS)
def test_every_adapter_builds_at_least_one_variant_with_a_url_and_a_slug(provider):
    adapter = registry.adapter(provider)
    variants = adapter.feed_variants('acme')
    assert variants, 'a tenant has to be reachable through at least one request'
    for variant in variants:
        assert variant.url.startswith('https://')
        assert variant.slug and '/' not in variant.slug
        assert variant.key


@pytest.mark.parametrize('provider', PROVIDERS)
def test_an_adapter_refuses_a_tenant_id_it_did_not_issue(provider):
    """No tenant-id guessing anywhere, and no URL built out of whatever a
    caller passed: a slug that is not shaped like the provider's own is a
    ValueError, not a request."""
    adapter = registry.adapter(provider)
    with pytest.raises(ValueError):
        adapter.feed_variants('not a tenant/../etc')


@pytest.mark.parametrize('provider', PROVIDERS)
def test_a_provider_recognises_its_own_board_url_and_declines_a_lookalike(provider):
    adapter = registry.adapter(provider)
    variant = adapter.feed_variants('acme')[0]
    assert adapter.tenant_from_url(f'https://evil.example.com/?x={variant.host}') is None
    assert adapter.tenant_from_url('') is None
    assert adapter.tenant_from_url(None) is None


@pytest.mark.parametrize('url,provider,tenant', [
    ('https://acme.jobs.personio.de/job/1', 'personio', 'acme'),
    ('https://boards.greenhouse.io/acme', 'greenhouse', 'acme'),
    ('https://job-boards.greenhouse.io/acme/jobs/44', 'greenhouse', 'acme'),
    ('https://boards.greenhouse.io/embed/job_board?for=acme', 'greenhouse', 'acme'),
    ('https://jobs.lever.co/acme', 'lever', 'acme'),
    ('https://jobs.eu.lever.co/acme/abc-def', 'lever', 'acme'),
    ('https://jobs.ashbyhq.com/acme/uuid-1', 'ashby', 'acme'),
    ('https://acme.recruitee.com/o/engineer', 'recruitee', 'acme'),
    ('https://jobs.smartrecruiters.com/Acme/7440001-engineer', 'smartrecruiters', 'Acme'),
])
def test_the_registry_answers_which_platform_a_url_names(url, provider, tenant):
    """What the ATS platform map runs over a crawl index and over a
    careers page: one URL, one platform, one tenant."""
    assert registry.identify(url) == {**registry.identify(url),
                                      'provider': provider, 'tenant': tenant}


@pytest.mark.parametrize('url', [
    'https://www.recruitee.com/de/kundenerfolgsgeschichten/shopware',
    'https://app.recruitee.com/login',
    'https://boards.greenhouse.io/embed/job_board',
    'https://example.com/jobs/1',
])
def test_a_providers_own_marketing_and_platform_urls_are_not_tenants(url):
    """Measured on the live index: one Common Crawl page for
    `recruitee.com` returned 585 subdomains, and a handful of them are
    Recruitee's own infrastructure rather than customers."""
    assert registry.identify(url) is None


@pytest.mark.parametrize('provider', PROVIDERS)
def test_an_adapter_declares_only_dimensions_the_taxonomy_has(provider):
    """`MAPPED_DIMENSIONS` is what a provider's API can state. A name
    outside the taxonomy would be a value record nothing can validate."""
    adapter = registry.adapter(provider)
    assert adapter.MAPPED_DIMENSIONS
    assert base.check_adapter(adapter) == []


# --- provenance: the one thing the store refuses -----------------------------

def mapped_posting(tenant='acme', posting_id='1', *, office='CH - 8001 Zürich'):
    """A Greenhouse posting as its adapter maps one, with the fetch half
    of its provenance attached the way `fetch._absorb` attaches it."""
    adapter = registry.adapter('greenhouse')
    raw = {'id': posting_id, 'title': 'Engineer 80-100%', 'language': 'en',
           'company_name': 'Acme AG', 'offices': [{'name': office}],
           'location': {'name': office}, 'content': '&lt;p&gt;Hello&lt;/p&gt;',
           'first_published': '2026-10-01T00:00:00Z'}
    variant = adapter.feed_variants(tenant)[0]
    posting = adapter.map_posting(raw, tenant=tenant, variant=variant)
    base.attach_fetch_provenance(posting, variant=variant, run='r1',
                                 feed_snapshot=f'snapshots/feeds/{tenant}/r1-jobs.json.gz',
                                 at='2026-10-17T06:00:00+00:00')
    return fetch_module.locate(posting)


def test_a_mapped_posting_carries_its_whole_source_chain():
    posting = mapped_posting()
    assert base.check_provenance(posting) == []
    provenance = posting['provenance']
    assert provenance['provider'] == 'greenhouse'
    assert provenance['tenant'] == 'acme'
    assert provenance['posting_id'] == '1'
    assert provenance['url'] == 'https://job-boards.greenhouse.io/acme/jobs/1'
    assert provenance['feed_url'].startswith('https://boards-api.greenhouse.io/v1/boards/acme')
    assert provenance['feed_snapshot'].endswith('.json.gz')
    assert provenance['content_hash'] == posting['content_hash']
    assert provenance['api_doc_url'] and provenance['api_doc_accessed'] == '2026-10-17'
    assert provenance['run_id'] == 'r1' and provenance['fetched_at']


@pytest.mark.parametrize('missing', list(base.PROVENANCE_FIELDS))
def test_the_store_rejects_a_posting_missing_any_part_of_its_source_chain(store, missing):
    """Owner ruling 2026-10-17, priority a, as a contract no adapter can
    skip: the store refuses the posting rather than storing an orphan."""
    posting = mapped_posting()
    posting['provenance'].pop(missing)
    with pytest.raises(base.ProvenanceError, match=missing):
        store.write_posting_snapshot(posting, run='r1')
    assert not list(store.root.rglob('*.yaml')), 'nothing was written'


def test_the_store_rejects_a_posting_with_no_provenance_block_at_all(store):
    posting = mapped_posting()
    posting.pop('provenance')
    with pytest.raises(base.ProvenanceError, match='no provenance block'):
        store.write_posting_snapshot(posting, run='r1')


def test_the_store_rejects_a_posting_whose_provenance_contradicts_it(store):
    posting = mapped_posting()
    posting['provenance']['tenant'] = 'someone-else'
    with pytest.raises(base.ProvenanceError, match='disagrees'):
        store.write_posting_snapshot(posting, run='r1')


def test_the_store_rejects_a_posting_with_no_feed_sourced_value_record(store):
    """"Every mapped field is a D4 value record with source=feed" is half
    the rule; the other half is that a posting whose records all came
    from somewhere else cannot claim the feed said so."""
    posting = mapped_posting()
    for record in posting['values'].values():
        record['source'] = 'llm'
    with pytest.raises(base.ProvenanceError, match="source='feed'"):
        store.write_posting_snapshot(posting, run='r1')


def test_the_store_rejects_a_value_that_is_not_a_d4_record(store):
    posting = mapped_posting()
    posting['values']['language'] = 'en'
    with pytest.raises(base.ProvenanceError, match='not a D4 value record'):
        store.write_posting_snapshot(posting, run='r1')


def test_an_adapter_that_maps_no_value_record_cannot_finalize_a_posting():
    """The other end of the same rule: an absent field is an `unknown`
    record, so a posting with no records at all is a bug in the adapter
    and says so at mapping time rather than at storing time."""
    with pytest.raises(base.ProvenanceError, match='no value records'):
        base.finalize({'provider': 'x', 'tenant': 'acme', 'posting_id': '1',
                       'url': 'https://x/', 'values': {}}, adapter=personio)


#: The two dimensions a provider states without the posting saying
#: anything, so an empty posting still carries a real value for them.
#: Personio's language is the feed VARIANT's language (the tenant
#: publishes a German feed), and SmartRecruiters sets its remote and
#: hybrid flags explicitly, so neither flag set is read as on site.
#: Both are documented in their adapters; listed here so a third one
#: cannot appear quietly.
STATED_WITHOUT_A_FIELD = {('personio', 'language'), ('smartrecruiters', 'work_model')}


@pytest.mark.parametrize('provider', PROVIDERS)
def test_a_posting_states_every_dimension_its_adapter_claims(provider):
    """No silent drops: `MAPPED_DIMENSIONS` is the adapter's own promise
    and `unknown` is how it keeps that promise for a field the feed left
    empty."""
    adapter = registry.adapter(provider)
    minimal = {'personio': {'id': '1'},
               'greenhouse': {'id': '1'},
               'lever': {'id': '1'},
               'ashby': {'id': '1'},
               'recruitee': {'id': '1'},
               'smartrecruiters': {'id': '1'}}[provider]
    posting = adapter.map_posting(minimal, tenant='acme',
                                  variant=adapter.feed_variants('acme')[0])
    assert base.check_mapped_dimensions(adapter, posting) == []
    for dimension in adapter.MAPPED_DIMENSIONS:
        record = posting['values'][dimension]
        assert record['source'] == 'feed'
        assert record['evidence'], f'{dimension} must say what it read'
        if (provider, dimension) in STATED_WITHOUT_A_FIELD:
            assert record['value'] != 'unknown', 'this one is stated by the feed itself'
            continue
        assert record['value'] == 'unknown', f'{dimension}: an empty posting states nothing'


# --- the geocoder reads the country a provider states ------------------------

@pytest.mark.parametrize('country', ['CH', 'ch', 'CHE', 'Switzerland', 'Schweiz', 'Suisse',
                                     'Svizzera'])
def test_a_stated_swiss_country_corroborates_a_bare_municipality_name(country):
    """CAREER-53's geocoder could not tell a Swiss place from a foreign
    one that shares its name, and said so. Four of the six adapters
    state a country field, which is the evidence it was missing."""
    answer = geocode.geocode_office('Lindau', country=country)
    assert answer['status'] == geocode.IN_AREA
    assert answer['municipality'] == '176', 'Lindau in canton Zurich'
    assert answer['corroborated'] is True, 'the country says Switzerland outright'
    assert 'stated_country' in answer['method']


def test_a_stated_foreign_country_settles_the_office_before_any_name_is_matched():
    """"Gebäudetechnik, Lindau" in Baden-Wurttemberg put two German
    postings in canton Zurich on the Personio trial. This is the fix."""
    answer = geocode.geocode_office('Lindau', country='Germany')
    assert answer['status'] == geocode.OUT_OF_AREA
    assert answer['municipality'] is None
    assert answer['method'] == 'stated_country'
    assert 'not Switzerland' in answer['reason']
    assert answer['swiss_evidence'] is False, 'it needs no human either'


def test_a_bare_name_with_no_stated_country_still_resolves_uncorroborated():
    """Personio states no country, so its behaviour must not change."""
    answer = geocode.geocode_office('Lindau')
    assert answer['status'] == geocode.IN_AREA
    assert answer['municipality'] == '176'
    assert answer['corroborated'] is False, 'a name alone is still a name alone'


@pytest.mark.parametrize('office', [
    'Zurich, Switzerland',                          # Greenhouse's own location field
    'Zürich, Schweiz',
    'New York City, US; Zurich, CH; Budapest, HU',  # a multi-site Greenhouse board
])
def test_an_office_line_that_says_switzerland_itself_corroborates_the_name(office):
    """Found on the first Zurich postings the Greenhouse adapter ever
    returned: the location field says "Zurich, Switzerland", and reading
    that as a bare name match would throw away the corroboration the
    tenant typed. `CH` counts too, even though a short all-upper token
    is otherwise treated as a site code."""
    answer = geocode.geocode_office(office)
    assert answer['status'] == geocode.IN_AREA
    assert answer['municipality'] == '261'
    assert answer['corroborated'] is True
    assert 'stated_country' in answer['method']


@pytest.mark.parametrize('office,country', [
    ('Lindau, Germany', 'Germany'),
    ('Lindau (DE)', 'DE'),
    ('Baden, Austria', 'Austria'),
])
def test_an_office_line_that_names_a_neighbour_country_is_out_of_area(office, country):
    """The other side of the same question. Lindau, Baden, Freiburg,
    Rheinfelden and Wald all exist on both sides of a border, so a line
    that names the other side has settled it -- without a table of the
    world's countries, which this module refuses to invent."""
    answer = geocode.geocode_office(office)
    assert answer['status'] == geocode.OUT_OF_AREA
    assert answer['municipality'] is None
    assert answer['reason'] == f'the office names {country}, not Switzerland'


def test_a_swiss_postal_code_outweighs_a_country_word_in_the_same_line():
    """Only when nothing Swiss backs the name: a postal code is a code,
    not a spelling, so it wins over a stray country word."""
    answer = geocode.geocode_office('8001 Zürich, Germany')
    assert answer['status'] == geocode.IN_AREA
    assert answer['municipality'] == '261'


def test_an_office_can_be_a_string_or_a_stated_pair():
    """Adapters that state a country pass the pair; Personio passes the
    line. One posting can carry both kinds."""
    _, summary = geocode.geocode_offices([{'text': 'Lindau', 'country': 'DE'},
                                          'CH - 8001 Zürich'])
    assert summary['status'] == geocode.IN_AREA
    assert summary['municipality'] == '261'


# --- the shared pipeline, over every provider --------------------------------

class FakeFeed:
    """A transport that answers one tenant's feed and 404s everything
    else, with an ETag so conditional requests can be exercised."""

    def __init__(self, bodies, etag='"tag"'):
        self.bodies = bodies
        self.etag = etag
        self.requests = []

    def __call__(self, url, *, limiter=None, headers=None, **options):
        self.requests.append(url)
        body = self.bodies.get(url)
        if body is None:
            return {'ok': False, 'status': 404, 'text': '', 'error': 'HTTP 404',
                    'final_url': url, 'headers': {}}
        if headers and headers.get('If-None-Match') == self.etag:
            return {'ok': False, 'status': 304, 'text': '', 'error': 'HTTP 304',
                    'final_url': url, 'headers': {'etag': self.etag}}
        return {'ok': True, 'status': 200, 'text': body, 'error': None,
                'final_url': url, 'headers': {'etag': self.etag}}


#: One minimal, provider-shaped body per adapter, with one posting whose
#: office is in Zurich. Written by hand on purpose: these are not the
#: recorded-feed fixtures (those live in `tests/fixtures/ats/` and
#: `test_ats_adapters.py` reads them) but the smallest body each parser
#: accepts, so the SHARED machinery can be exercised over six providers
#: without six large files.
MINIMAL = {
    'personio': ('<?xml version="1.0"?><workzag-jobs><position><id>1</id>'
                 '<name>Engineer</name><office>CH - 8001 Zürich</office>'
                 '<employmentType>permanent</employmentType><schedule>full-time</schedule>'
                 '<jobDescriptions><jobDescription><name>Aufgaben</name>'
                 '<value><![CDATA[<p>Hallo</p>]]></value></jobDescription></jobDescriptions>'
                 '</position></workzag-jobs>'),
    'greenhouse': ('{"jobs": [{"id": 1, "title": "Engineer", "language": "en", '
                   '"company_name": "Acme AG", "offices": [{"name": "Zurich"}], '
                   '"location": {"name": "8001 Zürich"}, "content": "&lt;p&gt;Hi&lt;/p&gt;"}]}'),
    'lever': ('[{"id": "uuid-1", "text": "Engineer", "country": "CH", '
              '"workplaceType": "hybrid", "categories": {"location": "Zurich", '
              '"commitment": "Full time", "department": "Eng"}, '
              '"descriptionPlain": "Hi", "createdAt": 1760000000000}]'),
    'ashby': ('{"jobs": [{"id": "uuid-1", "title": "Engineer", "employmentType": "FullTime", '
              '"workplaceType": "Hybrid", "location": "Zurich", '
              '"address": {"postalAddress": {"postalCode": "8001", '
              '"addressLocality": "Zürich", "addressCountry": "Switzerland"}}, '
              '"descriptionPlain": "Hi", "publishedAt": "2026-10-01T00:00:00Z"}]}'),
    'recruitee': ('{"offers": [{"id": 1, "title": "Engineer", "slug": "engineer", '
                  '"company_name": "Acme AG", "city": "Zürich", "postal_code": "8001", '
                  '"country_code": "CH", "employment_type_code": "fulltime_permanent", '
                  '"experience_code": "senior", "remote": false, "hybrid": true, '
                  '"on_site": false, "description": "<p>Hi</p>", '
                  '"translations": {"de": {}}, "published_at": "2026-10-01 00:00:00 UTC"}]}'),
    'smartrecruiters': ('{"offset": 0, "limit": 100, "totalFound": 1, "content": [{"id": "1", '
                        '"name": "Engineer", "company": {"name": "Acme AG"}, '
                        '"location": {"city": "Zürich", "country": "ch", '
                        '"postalCode": "8001", "remote": false, "hybrid": false}, '
                        '"typeOfEmployment": {"id": "permanent"}, '
                        '"experienceLevel": {"id": "senior"}, '
                        '"releasedDate": "2026-10-01T00:00:00Z"}]}'),
}

#: SmartRecruiters' detail endpoint, which the Zurich filter triggers.
MINIMAL_DETAIL = ('{"id": "1", "name": "Engineer", "company": {"name": "Acme AG"}, '
                  '"location": {"city": "Zürich", "country": "ch", "postalCode": "8001"}, '
                  '"language": {"code": "en"}, "typeOfEmployment": {"id": "permanent"}, '
                  '"experienceLevel": {"id": "senior"}, "postingUrl": '
                  '"https://jobs.smartrecruiters.com/Acme/1-engineer", '
                  '"jobAd": {"sections": {"jobDescription": {"title": "Job", '
                  '"text": "<p>Hi</p>"}}}}')


def feed_for(provider, tenant='acme'):
    """A transport answering every variant of one tenant with the
    provider's minimal body."""
    adapter = registry.adapter(provider)
    bodies = {variant.url: MINIMAL[provider]
              for variant in adapter.feed_variants(tenant)}
    if provider == 'smartrecruiters':
        bodies[adapter.detail_url(tenant, '1')] = MINIMAL_DETAIL
    return FakeFeed(bodies)


def fetch_one(provider, tmp_path, *, tenant='acme', run='r1', conditional=None, server=None):
    adapter = registry.adapter(provider)
    store = store_module.Store(tmp_path / provider, provider=provider)
    server = server or feed_for(provider, tenant)
    result = fetch_module.fetch_tenant(
        tenant, store=store, run=run, fetch=server, adapter=adapter,
        conditional=conditional or {}, at='2026-10-17T06:00:00+00:00',
        sleep=lambda seconds: None)
    return store, result, server


@pytest.mark.parametrize('provider', PROVIDERS)
def test_one_pipeline_fetches_maps_locates_and_freezes_every_provider(provider, tmp_path):
    """The whole point of the refactor: six providers, one fetch, one
    geocoder, one snapshot store, one closure rule."""
    store, result, _ = fetch_one(provider, tmp_path)
    assert result['fetch_status'] == 'ok'
    assert len(result['postings']) == 1
    posting = result['postings'][0]
    assert posting['provider'] == provider
    assert posting['key'].startswith(f'{provider}:acme:')
    assert posting['area_status'] == geocode.IN_AREA
    assert posting['municipality'] == '261', 'Zürich, from the BFS register'
    assert posting['canton'] == '1'
    assert base.check_provenance(posting) == []
    changes = store_module.record_run(store, run='r1', at='2026-10-17T06:00:00+00:00',
                                      tenant_results={'acme': result})
    assert changes['acme']['new'] == [posting['key']]
    assert store.load_state('acme')['provider'] == provider


@pytest.mark.parametrize('provider', PROVIDERS)
def test_the_raw_response_is_frozen_once_per_provider(provider, tmp_path):
    adapter = registry.adapter(provider)
    store, result, _ = fetch_one(provider, tmp_path)
    slug = adapter.feed_variants('acme')[0].slug
    snapshots = sorted((store.root / 'snapshots' / 'feeds' / 'acme').glob(f'*-{slug}.*'))
    assert snapshots, 'the raw response is the evidence'
    assert str(snapshots[0]).endswith(f'.{adapter.SNAPSHOT_SUFFIX}.gz')
    assert adapter.decompress(snapshots[0].read_bytes()) == MINIMAL[provider]


@pytest.mark.parametrize('provider', PROVIDERS)
def test_a_posting_missing_from_two_successful_fetches_closes_for_every_provider(provider,
                                                                                tmp_path):
    """Closure is shared machinery, so it is tested over every provider
    rather than once for Personio and hoped for elsewhere."""
    store, result, _ = fetch_one(provider, tmp_path)
    key = result['postings'][0]['key']
    for run in ('r1', 'r2', 'r3'):
        store.append_run({'run_id': run, 'at': f'2026-10-{run[-1]}'})
        store_module.record_run(
            store, run=run, at=f'2026-10-1{run[-1]}T06:00:00+00:00',
            tenant_results={'acme': result if run == 'r1'
                            else {'fetch_status': 'ok', 'postings': []}})
        entry = store.load_state('acme')['postings'][key]
        assert entry['status'] == {'r1': 'open', 'r2': 'suspected_closing',
                                   'r3': 'closed'}[run]
    assert store.load_state('acme')['postings'][key]['snapshots'], 'snapshots are never deleted'


@pytest.mark.parametrize('provider', PROVIDERS)
def test_a_failed_fetch_closes_nothing_for_every_provider(provider, tmp_path):
    store, result, _ = fetch_one(provider, tmp_path)
    key = result['postings'][0]['key']
    store_module.record_run(store, run='r1', at='2026-10-17T06:00:00+00:00',
                            tenant_results={'acme': result})
    store_module.record_run(store, run='r2', at='2026-10-18T06:00:00+00:00',
                            tenant_results={'acme': {'fetch_status': 'http_error',
                                                     'postings': [], 'error': 'HTTP 503'}})
    assert store.load_state('acme')['postings'][key]['status'] == 'open'


@pytest.mark.parametrize('provider', PROVIDERS)
def test_a_tenant_with_no_board_is_not_found_and_is_not_a_parse_failure(provider, tmp_path):
    store, result, server = fetch_one(provider, tmp_path, tenant='nobody',
                                      server=FakeFeed({}))
    assert result['fetch_status'] == fetch_module.FETCH_NOT_FOUND
    assert result['postings'] == []
    assert result['parse_failures'] == []
    assert len(server.requests) <= 2, 'a 404 is a settled answer, not four retries'


@pytest.mark.parametrize('provider', PROVIDERS)
def test_a_body_that_is_not_this_providers_feed_is_a_named_parse_failure(provider, tmp_path):
    adapter = registry.adapter(provider)
    bodies = {variant.url: '<html>maintenance</html>'
              for variant in adapter.feed_variants('acme')}
    _, result, _ = fetch_one(provider, tmp_path, server=FakeFeed(bodies))
    assert result['fetch_status'] == fetch_module.FETCH_PARSE_ERROR
    assert result['parse_failures'], 'counted per feed, with a reason'
    assert result['postings'] == []


@pytest.mark.parametrize('provider', PROVIDERS)
def test_an_unchanged_feed_costs_a_conditional_request_and_sees_the_same_postings(provider,
                                                                                 tmp_path):
    """A 304 is a successful fetch that saw everything it saw last time.
    Reading it as an empty feed would close a tenant's whole board."""
    store, first, _ = fetch_one(provider, tmp_path)
    conditional = {slug: {**state, 'snapshot': state['snapshot']}
                   for slug, state in first['etags'].items()}
    second = fetch_module.fetch_tenant(
        'acme', store=store, run='r2', fetch=feed_for(provider), adapter=registry.adapter(
            provider), conditional=conditional, at='2026-10-18T06:00:00+00:00',
        sleep=lambda seconds: None)
    assert second['fetch_status'] == 'ok'
    assert [posting['key'] for posting in second['postings']] == \
        [posting['key'] for posting in first['postings']]
    assert any(report.get('conditional') for report in second['languages'].values()
               if isinstance(report, dict))


def test_smartrecruiters_asks_for_a_posting_detail_only_inside_the_zurich_filter(tmp_path):
    """The one provider whose list endpoint states no description. A
    detail per posting would cost hundreds of requests for postings the
    pool excludes anyway, so the filter runs on the list's own location
    first."""
    store, result, server = fetch_one('smartrecruiters', tmp_path)
    assert result['details'] == {'requested': 1, 'ok': 1, 'failed': 0}
    posting = result['postings'][0]
    assert posting['has_description'] is True
    assert 'Hi' in posting['description']
    assert posting['provenance']['detail_url'].endswith('/postings/1')
    assert posting['provenance']['feed_url'].endswith('postings?limit=100&offset=0')

    foreign = MINIMAL['smartrecruiters'].replace('"city": "Zürich"', '"city": "Dhaka"') \
                                        .replace('"country": "ch"', '"country": "bd"')
    adapter = registry.adapter('smartrecruiters')
    bodies = {adapter.feed_variants('acme')[0].url: foreign}
    _, result, _ = fetch_one('smartrecruiters', tmp_path / 'second',
                             server=FakeFeed(bodies))
    assert result['details'] == {'requested': 0, 'ok': 0, 'failed': 0}
    assert result['postings'][0]['has_description'] is False
    assert 'not fetched' in result['postings'][0]['description_status']
