"""The Personio mapper, against the feeds recorded on 2026-10-17.

Every input here is a real response (see tests/fixtures/personio/README.md
for what each file is and how it was recorded). Nothing in this file
opens a socket: the suite's `offline` fixture blocks DNS and the opener
for every test, and the mapper takes no fetcher.
"""
from pathlib import Path

import pytest

from careeros import taxonomy
from careeros.feeds import personio

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'personio'


def feed(name):
    return (FIXTURES / f'{name}.xml').read_text()


def positions(name):
    return personio.parse_feed(feed(name))


def mapped(name, index=0, *, language='de', tenant='bring-labs', host=personio.HOSTS[0]):
    return personio.map_posting(positions(name)[index], tenant=tenant, language=language,
                                host=host)


# --- the URL shape, which the live check settled -----------------------------

def test_the_feed_url_is_xml_with_the_language_as_a_query_parameter():
    """Checked live 2026-10-17: /xml answers 200 and /de/xml answers 404,
    so the language is a parameter and not a path segment."""
    assert personio.feed_url('acme') == 'https://acme.jobs.personio.de/xml?language=de'
    assert personio.feed_url('acme', language='en') == \
        'https://acme.jobs.personio.de/xml?language=en'
    assert personio.feed_url('acme', host='jobs.personio.com') == \
        'https://acme.jobs.personio.com/xml?language=de'


def test_the_feed_url_refuses_a_tenant_a_language_or_a_host_it_does_not_know():
    for bad in ('Acme', 'a b', '', 'acme.jobs.personio.de', '-acme'):
        with pytest.raises(ValueError, match='not a Personio tenant'):
            personio.feed_url(bad)
    with pytest.raises(ValueError, match='Personio serves'):
        personio.feed_url('acme', language='gsw')
    with pytest.raises(ValueError, match='unknown Personio host'):
        personio.feed_url('acme', host='jobs.example.com')


def test_every_host_and_language_pair_is_offered_de_first():
    urls = personio.feed_urls('acme')
    assert [(host, language) for host, language, _ in urls] == [
        ('jobs.personio.de', 'de'), ('jobs.personio.de', 'en'),
        ('jobs.personio.com', 'de'), ('jobs.personio.com', 'en')]


def test_the_posting_url_and_the_stable_key_are_the_specs_own_shapes():
    assert personio.posting_url('acme', '42') == 'https://acme.jobs.personio.de/job/42'
    assert personio.posting_key('acme', '42') == 'personio:acme:42'


# --- parsing -----------------------------------------------------------------

def test_a_real_feed_parses_into_its_positions():
    assert len(positions('isolutions_de_trimmed')) == 3
    assert len(positions('bring_labs_de_trimmed')) == 3


def test_an_empty_feed_is_valid_and_has_no_positions():
    """The spec: "a tenant with an empty feed stays valid; it just has no
    open jobs." `mapegy` served exactly that, 72 bytes of it."""
    assert positions('mapegy_de_empty') == []


def test_a_body_that_is_not_xml_and_xml_that_is_not_a_feed_fail_differently():
    """The spec counts parse success per feed, so "this is not XML" and
    "this is XML for something else" have to be distinguishable from a
    tenant that simply does not exist (an HTTP 404)."""
    from xml.etree import ElementTree
    with pytest.raises(ElementTree.ParseError):
        personio.parse_feed('<html><body>not a feed')
    with pytest.raises(ValueError, match='not a Personio feed'):
        personio.parse_feed('<jobs><position><id>1</id></position></jobs>')


def test_the_root_element_is_personios_own_codename():
    assert feed('bring_labs_de_trimmed').count('<workzag-jobs>') == 1
    assert personio.ROOT_TAG == 'workzag-jobs'


def test_an_absent_field_is_an_absent_key_and_never_an_empty_value():
    """The spec says treat every field as optional. `bring-labs`'s talent
    pool posting has no `subcompany` at all, and the record has to say
    "the feed did not state one" rather than "the feed stated nothing"."""
    talent_pool = next(raw for raw in positions('bring_labs_fr_unsupported')
                       if raw['id'] == '409227')
    assert 'subcompany' not in talent_pool
    assert personio.map_posting(talent_pool, tenant='bring-labs',
                                language='de')['employer_name'] is None


def test_additional_offices_are_read_as_the_list_they_are():
    talent_pool = next(raw for raw in positions('bring_labs_fr_unsupported')
                       if raw['id'] == '409227')
    assert talent_pool['office'] == 'CH - Zürich'
    assert talent_pool['additionalOffices'] == ['DE - Berlin', 'CH - Basel']
    record = personio.map_posting(talent_pool, tenant='bring-labs', language='de')
    assert record['offices'] == ['CH - Zürich', 'DE - Berlin', 'CH - Basel']


def test_a_position_with_no_id_cannot_be_keyed():
    with pytest.raises(ValueError, match='no id'):
        personio.map_posting({'name': 'Nameless'}, tenant='acme', language='de')


# --- the language variants ---------------------------------------------------

def test_an_unsupported_language_answers_with_structure_and_no_text():
    """The live finding that `has_descriptions` exists for: asking for a
    language the tenant does not publish is a 200 whose positions carry
    every structural field and an empty `jobDescriptions`."""
    french = positions('bring_labs_fr_unsupported')
    assert len(french) == 3
    assert all(raw['employmentType'] for raw in french)
    assert all(raw['jobDescriptions'] == [] for raw in french)
    assert personio.has_descriptions(french) is False


def test_a_language_the_tenant_does_publish_carries_text():
    assert personio.has_descriptions(positions('bring_labs_en_trimmed')) is True
    assert personio.has_descriptions(positions('isolutions_de_trimmed')) is True


def test_the_english_feed_is_the_same_postings_in_another_language():
    german = mapped('bring_labs_de_trimmed')
    english = mapped('bring_labs_en_trimmed', language='en')
    assert german['posting_id'] == english['posting_id'] == '2726475'
    assert german['title'] == 'Head of Product (m/w/x)'
    assert english['title'] == 'Head of Product (m/f/x)'
    assert 'Als Head of Product' in german['description']
    assert 'As Head of Product' in english['description']


def test_the_com_host_serves_the_same_career_site_as_the_de_host():
    """Recorded from `jobs.personio.com` and byte-identical to the `.de`
    body, same ETag. The spec asks for a `.com` fixture; this is the
    finding it produced."""
    from_com = mapped('bring_labs_com_de_trimmed', host='jobs.personio.com')
    from_de = mapped('bring_labs_de_trimmed')
    assert from_com['feed_host'] == 'jobs.personio.com'
    assert from_com['url'] == 'https://bring-labs.jobs.personio.com/job/2726475'
    assert from_com['content_hash'] == from_de['content_hash'], \
        'the two hosts serve one career site, so a posting hashes the same on both'


# --- the field mapping, field by field ---------------------------------------

def test_every_field_of_the_specs_mapping_table_is_mapped():
    record = mapped('bring_labs_de_trimmed')
    assert record['key'] == 'personio:bring-labs:2726475'
    assert record['posting_id'] == '2726475'
    assert record['title'] == 'Head of Product (m/w/x)'
    assert record['employer_name'] == 'Bring! Labs AG'
    assert record['offices'] == ['CH - Zürich']
    assert record['department'] == 'Product'
    assert record['employment_type_raw'] == 'permanent'
    assert record['schedule_raw'] == 'full-time'
    assert record['seniority_hint'] == 'experienced'
    assert record['years_of_experience'] == '5-7'
    assert record['published_at'] == '2026-07-23T17:52:24+00:00'
    assert record['url'] == 'https://bring-labs.jobs.personio.de/job/2726475'


def test_the_fields_beyond_the_documented_list_are_kept_as_what_they_are():
    """The spec's open question, answered: the feed carries
    `recruitingCategory`, `keywords` and Personio's own occupation ids,
    and the ids are what the golden-set export stratifies on."""
    record = mapped('bring_labs_de_trimmed')
    assert record['recruiting_category'] == 'Leadership Roles'
    assert record['occupation'] == 'product_management'
    assert record['occupation_category'] == 'marketing_and_product'
    account_executive = mapped('bring_labs_de_trimmed', 1)
    assert 'Account Executive' in account_executive['keywords']
    assert account_executive['occupation_category'] == 'sales_and_business_development'


def test_the_description_blocks_are_concatenated_in_order_under_their_names():
    """The spec's rule for `jobDescriptions`: "concatenate the named
    blocks in order, keep block names as headings"."""
    record = mapped('isolutions_de_trimmed')
    names = [block['name'] for block in record['description_blocks']]
    assert names and all(names)
    body = record['description']
    assert body.index(names[0]) < body.index(names[1]) < body.index(names[-1])
    assert '<p>' not in body and '<span' not in body, 'the CDATA HTML is reduced to text'
    assert record['has_description'] is True


def test_a_feed_variant_with_no_text_maps_to_a_record_that_says_so():
    record = mapped('bring_labs_fr_unsupported', language='fr')
    assert record['description'] == ''
    assert record['description_blocks'] == []
    assert record['has_description'] is False


# --- the value records -------------------------------------------------------

D4_KEYS = {'value', 'source', 'confidence', 'evidence', 'taxonomy_version',
           'standard_version', 'classified_at', 'flags', 'guide_version'}


def test_every_value_record_is_the_d4_shape_from_the_one_factory():
    record = mapped('bring_labs_de_trimmed')
    assert set(record['values']) == {'contract', 'seniority', 'language',
                                     'workload_min', 'workload_max'}
    for dimension, value in record['values'].items():
        assert set(value) == D4_KEYS, dimension
        assert value['source'] == 'feed'
        assert value['evidence'], f'{dimension} must say what it read'
        assert value['flags'] == []


def test_the_employment_type_maps_onto_the_taxonomys_contract_codes():
    permanent = mapped('bring_labs_de_trimmed')['values']['contract']
    assert permanent['value'] == 'permanent'
    assert permanent['confidence'] == 0.9
    trainee = mapped('knott_de_trimmed', 1)['values']['contract']
    assert trainee['value'] == 'trainee_programme'
    assert trainee['evidence']['employmentType'] == 'trainee'
    assert taxonomy.valid_code('contract', trainee['value'])


def test_an_employment_type_outside_the_mapping_is_unknown_and_not_a_guess(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger='careeros.feeds.personio'):
        record = personio.map_posting({'id': '1', 'employmentType': 'zivildienst'},
                                      tenant='acme', language='de')
    contract = record['values']['contract']
    assert contract['value'] == taxonomy.UNKNOWN
    assert contract['confidence'] is None
    assert contract['evidence']['employmentType'] == 'zivildienst'
    assert 'zivildienst' in caplog.text


def test_a_missing_employment_type_says_the_feed_stated_none():
    contract = personio.map_posting({'id': '1'}, tenant='acme',
                                    language='de')['values']['contract']
    assert contract['value'] == taxonomy.UNKNOWN
    assert contract['evidence']['employmentType'] is None
    assert 'states no employment type' in contract['evidence']['rule']


def test_full_time_is_a_hundred_percent_on_both_ends_of_the_range():
    record = mapped('bring_labs_de_trimmed')
    assert record['values']['workload_min']['value'] == '100'
    assert record['values']['workload_max']['value'] == '100'
    assert record['values']['workload_min']['confidence'] == 0.9


def test_part_time_is_the_specs_wide_range_at_low_confidence():
    record = personio.map_posting({'id': '1', 'schedule': 'part-time'},
                                  tenant='acme', language='de')
    assert record['values']['workload_min']['value'] == '20'
    assert record['values']['workload_max']['value'] == '90'
    assert record['values']['workload_min']['confidence'] == 0.2, \
        "the spec calls this low confidence, and the number has to say so"


@pytest.mark.parametrize('title,text,expected', [
    ('Projektleiter 80-100%', '', ('80', '100')),
    ('Sachbearbeiterin (60 %)', '', ('60', '60')),
    ('Pflegefachperson', 'Pensum 80 – 100 %', ('80', '100')),
    ('Mitarbeiter 85%', '', ('80', '90')),
    ('Teamlead', 'bis zu 150% Einsatz', ('20', '90')),
])
def test_a_percentage_in_the_title_or_the_text_beats_the_part_time_range(title, text, expected):
    """The spec: part-time is 20-90 "unless the title or text states a
    percentage". 85% rounds to 80-90, the way workload.yaml says a
    minimum rounds down and a maximum rounds up; 150% is not a Pensum
    and is ignored rather than clamped."""
    record = personio.map_posting(
        {'id': '1', 'schedule': 'part-time', 'name': title,
         'jobDescriptions': [{'name': 'Aufgaben', 'value': text}]},
        tenant='acme', language='de')
    assert (record['values']['workload_min']['value'],
            record['values']['workload_max']['value']) == expected


def test_a_schedule_the_taxonomy_cannot_read_is_unknown_on_both_ends():
    record = personio.map_posting({'id': '1', 'schedule': 'shift-work'},
                                  tenant='acme', language='de')
    assert record['values']['workload_min']['value'] == taxonomy.UNKNOWN
    assert record['values']['workload_max']['value'] == taxonomy.UNKNOWN


def test_the_seniority_hint_follows_d6_and_keeps_the_feeds_own_word():
    """The one place this adapter departs from the spec's table, and the
    module docstring records it: the spec maps `entry-level` to s0, D6
    calls s0 "Student or intern" and s1 "Entry" and its own crosswalk
    maps entry-level to s1."""
    entry = mapped('knott_de_trimmed', 1)
    assert entry['seniority_hint'] == 'entry-level'
    assert entry['values']['seniority']['value'] == 's1'
    assert 'D6' in entry['values']['seniority']['evidence']['rule']


def test_an_ambiguous_seniority_hint_is_unknown_with_the_word_kept():
    """The spec leaves `experienced` to the classifier ("s1 or s2"). A
    value record holds one code, so the honest answer is `unknown` --
    which under D4 means classified-and-came-up-empty -- with the feed's
    word preserved for CAREER-57."""
    record = mapped('bring_labs_de_trimmed')
    assert record['seniority_hint'] == 'experienced'
    assert record['values']['seniority']['value'] == taxonomy.UNKNOWN
    assert record['values']['seniority']['evidence']['seniority'] == 'experienced'


def test_the_language_record_says_it_is_the_feed_variant_not_a_detection():
    record = mapped('bring_labs_en_trimmed', language='en')
    language = record['values']['language']
    assert language['value'] == 'en'
    assert language['confidence'] == 0.9
    assert 'rather than a detection' in language['evidence']['rule']


def test_a_value_record_carries_the_version_of_its_own_dimension():
    record = mapped('bring_labs_de_trimmed')
    for dimension, stored in (('contract', 'contract'), ('seniority', 'seniority'),
                              ('workload', 'workload_min')):
        meta = taxonomy.dimension_meta(dimension)
        assert record['values'][stored]['taxonomy_version'] == meta['taxonomy_version']
        assert record['values'][stored]['standard_version'] == meta['standard_version']


# --- the content hash --------------------------------------------------------

def test_the_same_feed_mapped_twice_hashes_the_same():
    """The spec's "snapshots stable" criterion rests on this: re-fetching
    an unchanged posting must produce the same hash."""
    assert mapped('isolutions_de_trimmed')['content_hash'] == \
        mapped('isolutions_de_trimmed')['content_hash']


def test_the_hash_covers_what_the_feed_states_and_not_when_we_read_it():
    """A value record carries `classified_at` and a taxonomy version, so
    hashing the records would make every snapshot new after a taxonomy
    bump even though no posting had changed."""
    first = mapped('isolutions_de_trimmed')
    second = mapped('isolutions_de_trimmed')
    second['values']['contract']['classified_at'] = '2030-01-01T00:00:00+00:00'
    second['fetched_at'] = '2030-01-01T00:00:00+00:00'
    second['run_id'] = 'later'
    assert personio.content_hash(second) == first['content_hash']


@pytest.mark.parametrize('field,value', [
    ('title', 'Something else'),
    ('department', 'Another department'),
    ('offices', ['CH - Winterthur']),
    ('employment_type_raw', 'intern'),
    ('published_at', '2026-01-01T00:00:00+00:00'),
])
def test_a_change_to_anything_the_feed_states_changes_the_hash(field, value):
    record = mapped('isolutions_de_trimmed')
    changed = {**record, field: value}
    assert personio.content_hash(changed) != record['content_hash']


def test_a_description_change_changes_the_hash():
    record = mapped('isolutions_de_trimmed')
    changed = {**record, 'description_blocks': [{'name': 'Aufgaben', 'text': 'new text'}]}
    assert personio.content_hash(changed) != record['content_hash']


# --- the raw snapshot bytes --------------------------------------------------

def test_compression_is_deterministic_so_two_identical_feeds_are_identical_bytes():
    body = feed('isolutions_de_trimmed')
    assert personio.compress(body) == personio.compress(body)
    assert personio.decompress(personio.compress(body)) == body
