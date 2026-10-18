"""The five new adapters, against recorded real feeds.

One test file for the five because they answer the same questions and
the interesting part is where their answers differ: which field a
provider states, which vocabulary word it uses, and what this
repository refuses to read into it.

Every body under `tests/fixtures/ats/` is a real response, recorded
2026-10-17; `tests/fixtures/ats/README.md` says how and what the terms
observation was. Nothing here opens a socket (`tests/conftest.py`'s
`offline` fixture blocks it for the whole suite).
"""
import json
from pathlib import Path

import pytest

from careeros import taxonomy
from careeros.feeds import ashby, base, greenhouse, lever, recruitee, smartrecruiters

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'ats'


def body(name):
    return (FIXTURES / name).read_text()


def parsed(adapter, name):
    return adapter.parse_feed(body(name))


def mapped(adapter, name, index=0, *, tenant='acme', **options):
    raw = parsed(adapter, name)[index]
    return adapter.map_posting(raw, tenant=tenant,
                               variant=adapter.feed_variants(tenant)[0], **options)


def value(posting, dimension):
    return posting['values'][dimension]


# --- Greenhouse --------------------------------------------------------------

def test_greenhouse_parses_its_job_list_and_refuses_anything_else():
    jobs = parsed(greenhouse, 'greenhouse/figma_jobs_trimmed.json')
    assert len(jobs) == 2
    assert jobs[0]['id'] == 5426468004
    with pytest.raises(ValueError, match='no "jobs" list'):
        greenhouse.parse_feed('{"postings": []}')
    with pytest.raises(json.JSONDecodeError):
        greenhouse.parse_feed('<html>maintenance</html>')


def test_greenhouse_maps_the_identity_and_prefers_the_boards_own_link():
    posting = mapped(greenhouse, 'greenhouse/figma_jobs_trimmed.json', tenant='figma')
    assert posting['key'] == 'greenhouse:figma:5426468004'
    assert posting['title'] == 'Account Executive, Enterprise'
    assert posting['employer_name'] == 'Figma'
    assert posting['department'] == 'Sales'
    assert posting['requisition_id'] == '1451'
    assert posting['published_at'] == '2025-01-28T18:57:29-05:00'
    assert posting['url'].startswith('https://boards.greenhouse.io/figma/jobs/5426468004'), \
        "the API's own absolute_url, which carries the board's host and its gh_jid"


def test_greenhouse_unescapes_its_content_before_reading_it_as_html():
    """`content` is entity-escaped HTML (`&lt;div class=&quot;...`), not
    HTML. Feeding it in raw would store the markup as if it were prose."""
    posting = mapped(greenhouse, 'greenhouse/figma_jobs_trimmed.json', tenant='figma')
    assert posting['has_description'] is True
    assert '&lt;' not in posting['description']
    assert '<div' not in posting['description']
    assert 'Figma is growing our team' in posting['description']


def test_greenhouse_hands_the_geocoder_every_place_the_board_names():
    """The location is free text and often several places joined with a
    bullet, so each part is tried on its own -- which is how "in scope
    when ONE office is in canton Zurich" already works."""
    posting = mapped(greenhouse, 'greenhouse/figma_jobs_trimmed.json', tenant='figma')
    assert posting['offices'][0] == 'US', "the board's own office list comes first"
    assert 'San Francisco, CA • New York, NY • United States' in posting['offices']
    assert 'San Francisco, CA' in posting['offices']
    assert 'New York, NY' in posting['offices']


def test_greenhouse_states_a_language_and_admits_it_has_no_other_field():
    """The board API has no employment type, no seniority and no
    workload. `MAPPED_DIMENSIONS` says so rather than this module
    inventing a crosswalk from a board's own metadata questions."""
    posting = mapped(greenhouse, 'greenhouse/figma_jobs_trimmed.json', tenant='figma')
    assert greenhouse.MAPPED_DIMENSIONS == ('language', 'workload_min', 'workload_max')
    assert value(posting, 'language')['value'] == 'en'
    assert value(posting, 'language')['evidence']['language'] == 'en'
    assert value(posting, 'workload_min')['value'] == taxonomy.UNKNOWN
    assert 'states no workload' in value(posting, 'workload_min')['evidence']['rule']
    assert posting['metadata_raw'] == [], 'kept raw, mapped onto nothing'


def test_greenhouse_reads_a_pensum_out_of_a_swiss_title():
    posting = greenhouse.map_posting(
        {'id': 7, 'title': 'Projektleiterin 80-100%', 'language': 'de'},
        tenant='acme', variant=greenhouse.feed_variants('acme')[0])
    assert (value(posting, 'workload_min')['value'],
            value(posting, 'workload_max')['value']) == ('80', '100')
    assert value(posting, 'workload_min')['evidence']['pensum_quote'] == '80-100%'


# --- Lever -------------------------------------------------------------------

def test_lever_parses_its_bare_array_and_an_empty_board_stays_valid():
    postings = parsed(lever, 'lever/leverdemo_postings_trimmed.json')
    assert len(postings) == 2
    assert parsed(lever, 'lever/lever_empty_postings.json') == [], \
        'a tenant with no open postings is not a failure'
    with pytest.raises(ValueError, match='not a JSON list'):
        lever.parse_feed('{"jobs": []}')


def test_lever_maps_the_identity_from_the_instance_it_came_from():
    posting = mapped(lever, 'lever/leverdemo_postings_trimmed.json', tenant='leverdemo')
    assert posting['key'] == 'lever:leverdemo:ad208490-4052-4f91-a57e-433f2d1e484b'
    assert posting['title'] == 'Customer Success Manager'
    assert posting['department'] == 'Customer Success'
    assert posting['team'] == 'Customer Success Team'
    assert posting['url'] == ('https://jobs.lever.co/leverdemo/'
                              'ad208490-4052-4f91-a57e-433f2d1e484b')
    assert posting['feed_instance'] == 'global'
    assert posting['published_at'] == '2026-08-31T18:12:19+00:00', \
        'createdAt is epoch milliseconds and every other provider states a date'
    assert posting['created_at_raw'] == 1788199939703


def test_lever_fetches_both_instances_because_a_slug_is_instance_scoped():
    """Measured 2026-10-17: `leverdemo` exists on both instances with
    different boards -- 10 postings on one, 324 on the other. So unlike
    Personio's two hosts, a successful fetch of one does not end the
    tenant."""
    variants = lever.feed_variants('acme')
    assert [variant.host for variant in variants] == ['api.lever.co', 'api.eu.lever.co']
    assert [variant.stop_after_group for variant in variants] == [False, False]
    assert variants[1].url == 'https://api.eu.lever.co/v0/postings/acme?mode=json'
    posting = lever.map_posting({'id': 'x', 'text': 'Engineer'}, tenant='acme',
                                variant=variants[1])
    assert posting['url'] == 'https://jobs.eu.lever.co/acme/x'
    assert posting['feed_instance'] == 'eu'


def test_lever_reads_its_commitment_field_as_a_workload_and_not_as_a_contract():
    """"Regular Full Time (Salary)" is customer-typed text that names a
    workload. Answering `permanent` for it would be inventing a contract
    the API never stated."""
    posting = mapped(lever, 'lever/leverdemo_postings_trimmed.json', tenant='leverdemo')
    contract = value(posting, 'contract')
    assert contract['value'] == taxonomy.UNKNOWN
    assert contract['evidence']['commitment'] == 'Regular Full Time (Salary)'
    assert 'states a workload rather than a contract type' in contract['evidence']['rule']
    assert value(posting, 'workload_min')['value'] == '100'
    assert value(posting, 'workload_max')['value'] == '100'
    assert value(posting, 'workload_min')['confidence'] == 0.8, \
        'a customer-typed field is not as good as a stated percentage'


@pytest.mark.parametrize('commitment,contract,workload', [
    ('Intern', 'internship', None),
    ('Contractor', 'freelance_mandate', None),
    ('Temporary', 'temporary_assignment', None),
    ('Werkstudent (Teilzeit)', 'working_student', ('20', '90')),
    ('Part time', taxonomy.UNKNOWN, ('20', '90')),
    ('Festanstellung, unbefristet', 'permanent', None),
    ('Saisonstelle', 'seasonal', None),
    ('Mystery commitment', taxonomy.UNKNOWN, None),
    ('', taxonomy.UNKNOWN, None),
])
def test_lever_commitment_words_map_onto_one_dimension_each(commitment, contract, workload):
    posting = lever.map_posting(
        {'id': 'x', 'text': 'Role', 'categories': {'commitment': commitment}},
        tenant='acme', variant=lever.feed_variants('acme')[0])
    assert value(posting, 'contract')['value'] == contract
    if workload:
        assert (value(posting, 'workload_min')['value'],
                value(posting, 'workload_max')['value']) == workload


def test_lever_workplace_type_is_a_closed_vocabulary_the_taxonomy_shares():
    first = mapped(lever, 'lever/leverdemo_postings_trimmed.json', tenant='leverdemo')
    second = mapped(lever, 'lever/leverdemo_postings_trimmed.json', 1, tenant='leverdemo')
    assert value(first, 'work_model')['value'] == 'hybrid'
    assert value(second, 'work_model')['value'] == 'onsite'
    assert value(first, 'work_model')['evidence']['workplaceType'] == 'hybrid'


def test_lever_keeps_the_apis_own_plain_text_and_its_list_blocks():
    posting = mapped(lever, 'lever/leverdemo_postings_trimmed.json', tenant='leverdemo')
    names = [block['name'] for block in posting['description_blocks']]
    assert None in names, "the API's own descriptionPlain"
    assert 'Skill Set:' in names, 'a lists[] block, the one rich field with no plain twin'
    assert '<li>' not in posting['description']
    assert posting['salary_raw'] == {'min': 85000, 'max': 175000, 'currency': 'USD',
                                     'interval': 'per-year-salary'}


# --- Ashby -------------------------------------------------------------------

def test_ashby_parses_its_job_board_and_refuses_anything_else():
    jobs = parsed(ashby, 'ashby/ashby_job_board_trimmed.json')
    assert len(jobs) == 2
    with pytest.raises(ValueError, match='no "jobs" list'):
        ashby.parse_feed('{"postings": []}')


def test_ashby_maps_the_identity_and_keeps_an_unlisted_posting_visible():
    posting = mapped(ashby, 'ashby/ashby_job_board_trimmed.json', tenant='ashby')
    assert posting['key'] == 'ashby:ashby:7458d4e9-da2e-47bd-98cb-adfda43d42b2'
    assert posting['title'] == 'Engineering Manager - EU'
    assert posting['department'] == 'Engineering'
    assert posting['team'] == 'EMEA Engineering'
    assert posting['is_listed'] is True
    assert posting['url'].startswith('https://jobs.ashbyhq.com/ashby/')
    assert posting['published_at'] == '2024-03-04T14:29:08.532+00:00'
    unlisted = ashby.map_posting({'id': 'x', 'title': 'Hidden', 'isListed': False},
                                 tenant='acme', variant=ashby.feed_variants('acme')[0])
    assert unlisted['is_listed'] is False, 'recorded as a status, not dropped'


def test_ashby_hands_the_geocoder_the_country_each_address_states():
    """The best location evidence of any provider here: a postal code, a
    locality and a country per location, which is what finally rules out
    a foreign town sharing a Swiss municipality name."""
    posting = ashby.map_posting(
        {'id': 'x', 'title': 'Engineer', 'location': 'Lindau',
         'address': {'postalAddress': {'postalCode': '88131', 'addressLocality': 'Lindau',
                                       'addressCountry': 'Germany'}}},
        tenant='acme', variant=ashby.feed_variants('acme')[0])
    assert posting['offices_stated'][0] == {'text': 'Lindau', 'country': 'Germany'}
    assert posting['country_raw'] == 'Germany'
    assert '88131 Lindau' in posting['offices']


def test_ashby_secondary_locations_are_offices_too():
    posting = mapped(ashby, 'ashby/ashby_job_board_trimmed.json', tenant='ashby')
    assert posting['offices'][0] == 'Remote - European Union'
    assert 'Switzerland' in posting['offices'], 'a secondary location is an office'
    countries = {office['country'] for office in posting['offices_stated']}
    assert 'Switzerland' in countries


@pytest.mark.parametrize('employment,contract,workload', [
    ('FullTime', taxonomy.UNKNOWN, ('100', '100')),
    ('PartTime', taxonomy.UNKNOWN, ('20', '90')),
    ('Intern', 'internship', None),
    ('Contract', 'freelance_mandate', None),
    ('Temporary', 'temporary_assignment', None),
    ('', taxonomy.UNKNOWN, None),
])
def test_ashby_employment_type_splits_into_contract_and_workload(employment, contract,
                                                                 workload):
    """`FullTime` names a workload and `Intern` names a contract, and the
    same field carries both -- so each lands on the dimension it is
    about and the other stays `unknown` with the field in the evidence."""
    posting = ashby.map_posting({'id': 'x', 'title': 'Role', 'employmentType': employment},
                                tenant='acme', variant=ashby.feed_variants('acme')[0])
    assert value(posting, 'contract')['value'] == contract
    if workload:
        assert (value(posting, 'workload_min')['value'],
                value(posting, 'workload_max')['value']) == workload


def test_ashby_prefers_the_apis_own_plain_description():
    posting = mapped(ashby, 'ashby/ashby_job_board_trimmed.json', tenant='ashby')
    assert posting['has_description'] is True
    assert '<p' not in posting['description']
    assert posting['compensation_raw'], 'includeCompensation=true is why it is one request'


def test_a_percentage_in_a_long_english_description_is_not_a_pensum():
    """The defect the first live Ashby run found: a bare "30%" inside a
    20 000-character description was read as a workload of 30. A text
    match now needs a Pensum word beside it; a title match does not."""
    posting = ashby.map_posting(
        {'id': 'x', 'title': 'Engineering Manager',
         'descriptionPlain': 'Our revenue grew 30% last year and churn fell 15%.'},
        tenant='acme', variant=ashby.feed_variants('acme')[0])
    assert value(posting, 'workload_min')['value'] == taxonomy.UNKNOWN
    with_word = ashby.map_posting(
        {'id': 'x', 'title': 'Pflegefachperson',
         'descriptionPlain': 'Arbeitszeit: 60 % im Schichtbetrieb.'},
        tenant='acme', variant=ashby.feed_variants('acme')[0])
    assert value(with_word, 'workload_min')['value'] == '60'


# --- Recruitee ---------------------------------------------------------------

def test_recruitee_parses_its_offers_and_refuses_anything_else():
    offers = parsed(recruitee, 'recruitee/accso_offers_trimmed.json')
    assert len(offers) == 2
    with pytest.raises(ValueError, match='no "offers" list'):
        recruitee.parse_feed('{"jobs": []}')


def test_recruitee_maps_the_identity_and_prefers_the_readable_careers_url():
    posting = mapped(recruitee, 'recruitee/accso_offers_trimmed.json', tenant='accso')
    assert posting['key'] == 'recruitee:accso:2786549'
    assert posting['title'] == 'Lead Frontend Architekt*'
    assert posting['employer_name'] == 'Accso – Accelerated Solutions GmbH'
    assert posting['slug'] == 'lead-frontend-architekt'
    assert posting['url'] == 'https://accso.recruitee.com/o/lead-frontend-architekt'
    assert posting['category_raw'] == 'internet'
    assert posting['salary_raw']['currency'] == 'EUR'


def test_recruitee_never_stores_the_offers_mailbox_address():
    """`mailbox_email` is an address and nothing here needs it, so it
    stays in the raw snapshot and reaches no record and no export."""
    raw = parsed(recruitee, 'recruitee/accso_offers_trimmed.json')[0]
    assert raw['mailbox_email'], 'the feed does carry one'
    posting = mapped(recruitee, 'recruitee/accso_offers_trimmed.json', tenant='accso')
    assert 'mailbox_email' not in posting
    assert raw['mailbox_email'] not in json.dumps(posting, default=str)


@pytest.mark.parametrize('code,contract,workload', [
    ('fulltime_permanent', 'permanent', ('100', '100')),
    ('parttime_permanent', 'permanent', ('20', '90')),
    ('fulltime_temporary', 'fixed_term', ('100', '100')),
    ('internship', 'internship', None),
    ('freelance', 'freelance_mandate', None),
    ('apprenticeship', 'apprenticeship', None),
    ('volunteer', taxonomy.UNKNOWN, None),
    ('', taxonomy.UNKNOWN, None),
])
def test_recruitees_compound_employment_code_splits_into_two_dimensions(code, contract,
                                                                        workload):
    """`fulltime_permanent` is one token for the workload and one for the
    contract, and each half lands on its own dimension with the whole
    original value as its evidence."""
    posting = recruitee.map_posting({'id': 1, 'title': 'Role', 'employment_type_code': code},
                                    tenant='acme',
                                    variant=recruitee.feed_variants('acme')[0])
    assert value(posting, 'contract')['value'] == contract
    assert value(posting, 'contract')['evidence']['employment_type_code'] == (code or None), \
        'the evidence is the field as the API stated it, not the half that was looked up'
    if workload:
        assert (value(posting, 'workload_min')['value'],
                value(posting, 'workload_max')['value']) == workload


def test_recruitee_hours_a_week_are_kept_raw_and_never_converted():
    """32 hours is a Pensum only against a full-time basis the API never
    states -- 42 in Switzerland, 40 in the Netherlands. Converting it
    would be an invented number."""
    posting = recruitee.map_posting(
        {'id': 1, 'title': 'Role', 'min_hours': 32, 'max_hours': 40},
        tenant='acme', variant=recruitee.feed_variants('acme')[0])
    assert posting['hours_per_week_raw'] == {'min_hours': 32, 'max_hours': 40}
    assert value(posting, 'workload_min')['value'] == taxonomy.UNKNOWN
    assert 'full-time basis the API does not state' in \
        value(posting, 'workload_min')['evidence']['rule']


def test_recruitees_three_location_flags_are_one_work_model():
    posting = mapped(recruitee, 'recruitee/accso_offers_trimmed.json', tenant='accso')
    record = value(posting, 'work_model')
    assert record['value'] == 'hybrid'
    assert record['evidence']['remote_hybrid_on_site'] == {'remote': False, 'hybrid': True,
                                                           'on_site': False}
    none_set = recruitee.map_posting({'id': 1, 'title': 'Role'}, tenant='acme',
                                     variant=recruitee.feed_variants('acme')[0])
    assert value(none_set, 'work_model')['value'] == taxonomy.UNKNOWN


def test_recruitees_experience_code_pins_a_step_only_when_it_names_one():
    posting = mapped(recruitee, 'recruitee/accso_offers_trimmed.json', tenant='accso')
    seniority = value(posting, 'seniority')
    assert posting['experience_raw'] == 'experienced'
    assert seniority['value'] == taxonomy.UNKNOWN, '"experienced" is a span, not a step'
    assert seniority['evidence']['experience_code'] == 'experienced'
    senior = recruitee.map_posting({'id': 1, 'title': 'Role', 'experience_code': 'senior'},
                                   tenant='acme',
                                   variant=recruitee.feed_variants('acme')[0])
    assert value(senior, 'seniority')['value'] == 's3'


def test_recruitee_reads_its_language_off_the_translations_it_carries():
    posting = mapped(recruitee, 'recruitee/accso_offers_trimmed.json', tenant='accso')
    assert value(posting, 'language')['value'] == 'de'
    both = recruitee.map_posting({'id': 1, 'title': 'Role',
                                  'translations': {'de': {}, 'en': {}}},
                                 tenant='acme',
                                 variant=recruitee.feed_variants('acme')[0])
    assert value(both, 'language')['value'] == taxonomy.UNKNOWN
    assert 'which is primary' in value(both, 'language')['evidence']['rule']


def test_recruitee_reads_its_description_and_requirements_as_blocks():
    posting = mapped(recruitee, 'recruitee/accso_offers_trimmed.json', tenant='accso')
    assert [block['name'] for block in posting['description_blocks']] == ['Description']
    assert '<p' not in posting['description']
    assert posting['has_description'] is True


def test_recruitee_declines_its_own_platform_subdomains():
    assert recruitee.tenant_from_url('https://app.recruitee.com/login') is None
    assert recruitee.tenant_from_url('https://www.recruitee.com/de/x') is None
    assert recruitee.tenant_from_url('https://accso.recruitee.com/') == {
        'tenant': 'accso', 'host': 'accso.recruitee.com', 'how': 'host_pattern'}


# --- SmartRecruiters ---------------------------------------------------------

def test_smartrecruiters_parses_its_list_and_carries_the_paging_numbers():
    postings = smartrecruiters.parse_feed(
        body('smartrecruiters/averydennison_postings_trimmed.json'))
    assert len(postings) == 2
    assert postings.paging == {'offset': 0, 'limit': 100, 'totalFound': 492}
    empty = smartrecruiters.parse_feed(
        body('smartrecruiters/smartrecruiters_empty_postings.json'))
    assert list(empty) == [] and empty.paging['totalFound'] == 0, \
        'a company with no open postings stays valid'
    with pytest.raises(ValueError, match='no "content" list'):
        smartrecruiters.parse_feed('{"jobs": []}')


def test_smartrecruiters_walks_its_pages_until_the_total_is_covered():
    postings = smartrecruiters.parse_feed(
        body('smartrecruiters/averydennison_postings_trimmed.json'))
    first = smartrecruiters.feed_variants('AveryDennison')[0]
    following = smartrecruiters.next_page(first, postings, 2)
    assert following.url.endswith('postings?limit=100&offset=100')
    assert following.page == 1
    last = smartrecruiters.parse_feed('{"offset": 400, "limit": 100, "totalFound": 492, '
                                      '"content": []}')
    assert smartrecruiters.next_page(first, last, 492) is None


def test_smartrecruiters_maps_the_list_and_says_its_text_was_not_fetched():
    posting = mapped(smartrecruiters,
                     'smartrecruiters/averydennison_postings_trimmed.json',
                     tenant='AveryDennison')
    assert posting['key'] == 'smartrecruiters:AveryDennison:744000156127779'
    assert posting['title'] == 'Officer, Graphics Automation'
    assert posting['employer_name'] == 'Avery Dennison'
    assert posting['department'] == 'Engineering Services'
    assert posting['function_raw'] == 'production'
    assert posting['industry_raw'] == 'packaging_and_containers'
    assert posting['offices'] == ['1349 Dhaka', 'Dhaka', 'Dhaka, , Bangladesh']
    assert posting['country_raw'] == 'bd'
    assert posting['has_description'] is False
    assert 'not fetched' in posting['description_status']
    assert value(posting, 'language')['value'] == 'en', \
        'the list endpoint does state a language; only the text needs the second request'


def test_smartrecruiters_folds_the_detail_in_and_gains_the_text_and_the_language():
    posting = mapped(smartrecruiters,
                     'smartrecruiters/averydennison_postings_trimmed.json',
                     tenant='AveryDennison')
    detail = smartrecruiters.parse_detail(
        body('smartrecruiters/averydennison_posting_detail.json'))
    merged = smartrecruiters.merge_detail(posting, detail, tenant='AveryDennison')
    assert merged['key'] == posting['key']
    assert merged['has_description'] is True
    assert [block['name'] for block in merged['description_blocks']][:2] == \
        ['Company Description', 'Job Description']
    assert 'Avery Dennison' in merged['description']
    assert value(merged, 'language')['value'] == 'en'
    assert merged['url'].endswith('744000156127779-officer-graphics-automation')
    assert merged['content_hash'] != posting['content_hash'], \
        'a posting with its text is not the same record as one without'
    assert merged['description_status'] == 'read from the posting detail endpoint'


def test_smartrecruiters_never_stores_the_recruiter_who_posted_it():
    detail = smartrecruiters.parse_detail(
        body('smartrecruiters/averydennison_posting_detail.json'))
    assert 'creator' in detail, 'the API does state one'
    merged = smartrecruiters.map_posting(detail, tenant='AveryDennison', detail=detail,
                                        variant=smartrecruiters.feed_variants('x')[0])
    assert 'creator' not in merged


@pytest.mark.parametrize('employment,contract', [
    ('permanent', 'permanent'),
    ('temporary', 'fixed_term'),
    ('contractor', 'freelance_mandate'),
    ('internship', 'internship'),
    ('mystery', taxonomy.UNKNOWN),
])
def test_smartrecruiters_employment_types_map_onto_contract_codes(employment, contract):
    posting = smartrecruiters.map_posting(
        {'id': '1', 'name': 'Role', 'typeOfEmployment': {'id': employment}},
        tenant='Acme', variant=smartrecruiters.feed_variants('Acme')[0])
    assert value(posting, 'contract')['value'] == contract


@pytest.mark.parametrize('level,seniority', [
    ('entry_level', 's1'),
    ('student', 's0'),
    ('executive', 's5'),
    ('mid_senior_level', taxonomy.UNKNOWN),
    ('associate', taxonomy.UNKNOWN),
])
def test_smartrecruiters_experience_levels_pin_a_step_only_when_they_name_one(level,
                                                                             seniority):
    posting = smartrecruiters.map_posting(
        {'id': '1', 'name': 'Role', 'experienceLevel': {'id': level}},
        tenant='Acme', variant=smartrecruiters.feed_variants('Acme')[0])
    assert value(posting, 'seniority')['value'] == seniority


def test_smartrecruiters_keeps_the_employers_own_custom_fields():
    posting = mapped(smartrecruiters,
                     'smartrecruiters/averydennison_postings_trimmed.json',
                     tenant='AveryDennison')
    labels = [field['label'] for field in posting['custom_fields_raw']]
    assert 'Country of vacancy' in labels
    assert all(set(field) == {'label', 'value'} for field in posting['custom_fields_raw'])


def test_a_company_identifier_keeps_its_case():
    """`AveryDennison` and `smartrecruiters` are both real identifiers and
    the path segment is what the API keys on."""
    assert smartrecruiters.feed_variants('AveryDennison')[0].url.endswith(
        'companies/AveryDennison/postings?limit=100&offset=0')
    assert smartrecruiters.tenant_from_url(
        'https://jobs.smartrecruiters.com/AveryDennison/744000156127779-officer')['tenant'] \
        == 'AveryDennison'


# --- the four JSON providers share one shape ---------------------------------

@pytest.mark.parametrize('adapter,fixture,tenant', [
    (greenhouse, 'greenhouse/figma_jobs_trimmed.json', 'figma'),
    (lever, 'lever/leverdemo_postings_trimmed.json', 'leverdemo'),
    (ashby, 'ashby/ashby_job_board_trimmed.json', 'ashby'),
    (recruitee, 'recruitee/accso_offers_trimmed.json', 'accso'),
    (smartrecruiters, 'smartrecruiters/averydennison_postings_trimmed.json',
     'AveryDennison'),
])
def test_every_value_record_is_the_d4_shape_from_the_one_factory(adapter, fixture, tenant):
    posting = mapped(adapter, fixture, tenant=tenant)
    assert set(posting['values']) == set(adapter.MAPPED_DIMENSIONS)
    for dimension, record in posting['values'].items():
        assert set(record) == {'value', 'source', 'confidence', 'evidence',
                               'taxonomy_version', 'standard_version', 'classified_at',
                               'flags', 'guide_version'}, dimension
        assert record['source'] == 'feed'
        assert record['evidence'], f'{dimension} must say what it read'
        assert record['flags'] == []
        stored = dimension.replace('_min', '').replace('_max', '')
        assert taxonomy.valid_code(stored, record['value']), f'{dimension}={record["value"]}'


@pytest.mark.parametrize('adapter,fixture,tenant', [
    (greenhouse, 'greenhouse/figma_jobs_trimmed.json', 'figma'),
    (lever, 'lever/leverdemo_postings_trimmed.json', 'leverdemo'),
    (ashby, 'ashby/ashby_job_board_trimmed.json', 'ashby'),
    (recruitee, 'recruitee/accso_offers_trimmed.json', 'accso'),
    (smartrecruiters, 'smartrecruiters/averydennison_postings_trimmed.json',
     'AveryDennison'),
])
def test_the_same_feed_mapped_twice_hashes_the_same(adapter, fixture, tenant):
    """Or the snapshot store would grow a new snapshot every day."""
    first = mapped(adapter, fixture, tenant=tenant)
    second = mapped(adapter, fixture, tenant=tenant)
    assert first['content_hash'] == second['content_hash']
    changed = dict(first, title='Something else')
    assert base.content_hash(changed, adapter.HASHED_FIELDS) != first['content_hash']
