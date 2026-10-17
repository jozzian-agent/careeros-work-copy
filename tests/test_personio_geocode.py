"""The Zurich filter: office text -> BFS municipality number.

The register these tests rest on is the one
`scripts/load_bfs_municipalities.py` loaded from the BFS register through
LINDAS on 2026-10-17: 2 110 municipalities, all 26 cantons, 160 of them
in canton Zurich. No network: `careeros.taxonomy` reads the shipped YAML.
"""
import pytest

from careeros import taxonomy
from careeros.feeds import geocode


# --- the register itself -----------------------------------------------------

def test_the_municipality_register_is_loaded_and_canton_zurich_is_whole():
    """CAREER-55 shipped this dimension as an empty stub with the
    register named as its source; CAREER-53 needed it and loaded it."""
    codes = taxonomy.codes('municipality')
    assert len(codes) > 2000
    zurich = [entry for entry in taxonomy.entries('municipality') if entry['canton'] == '1']
    assert len(zurich) == 160, 'canton Zurich has 160 municipalities in this register revision'
    assert taxonomy.entry('municipality', '261')['label'] == 'Zürich'
    assert taxonomy.entry('municipality', '230')['label'] == 'Winterthur'


def test_the_register_stays_incomplete_because_it_moves():
    """Mergers change it several times a year, so a code missing from it
    may be a real municipality created after the load. `is_complete` is
    what tells a caller that, and `make_value_record` reads it."""
    assert taxonomy.is_complete('municipality') is False
    assert 'LOADED, NOT FROZEN' in taxonomy.dimension_meta('municipality')['todo']
    assert taxonomy.is_complete('canton') is True


def test_every_municipality_sits_in_a_canton_the_canton_list_knows():
    cantons = set(taxonomy.codes('canton'))
    assert {entry['canton'] for entry in taxonomy.entries('municipality')} <= cantons
    assert len({entry['canton'] for entry in taxonomy.entries('municipality')}) == 26


def test_postal_codes_came_with_the_register():
    assert '8004' in taxonomy.entry('municipality', '261')['postal_codes']
    assert all(taxonomy.entry('municipality', code)['postal_codes']
               for code in taxonomy.codes('municipality')[:50])


# --- the shapes a real feed uses ---------------------------------------------

@pytest.mark.parametrize('office,municipality', [
    ('CH - Zürich', '261'),          # bring-labs, live
    ('Zürich', '261'),               # isolutions, live
    ('Zurich', '261'),               # the owner's own stored postings write it both ways
    ('ZÜRICH', '261'),
    ('8004 Zürich', '261'),
    ('Zürich-Oerlikon', '261'),
    ('Zürich, Schweiz', '261'),
    ('Zürich (HQ)', '261'),
    ('Remote / Zürich', '261'),
    ('CH-Winterthur', '230'),
    ('8600 Dübendorf', '191'),
    ('8600 Dübendorf ZH', '191'),
    ('Illnau-Effretikon', '296'),
    ('Uster', '198'),
])
def test_the_office_shapes_a_zurich_feed_actually_uses_all_resolve(office, municipality):
    answer = geocode.geocode_office(office)
    assert answer['municipality'] == municipality, answer['reason']
    assert answer['canton'] == geocode.ZURICH_CANTON
    assert answer['status'] == geocode.IN_AREA
    assert answer['confidence'] >= 0.8


def test_a_postal_code_and_a_name_that_agree_are_the_most_confident_answer():
    assert geocode.geocode_office('8004 Zürich')['confidence'] == 0.95
    assert geocode.geocode_office('Zürich')['confidence'] == 0.85


# --- out of area -------------------------------------------------------------

@pytest.mark.parametrize('office', ['DE - Berlin', 'DE - 10115 Berlin', 'AT - Wien'])
def test_a_foreign_country_prefix_is_out_of_area_and_needs_no_human(office):
    answer = geocode.geocode_office(office)
    assert answer['status'] == geocode.OUT_OF_AREA
    assert answer['method'] == 'country_prefix'
    assert answer['municipality'] is None


@pytest.mark.parametrize('office,canton', [
    ('CH - Basel', '12'), ('CH - Zug', '9'), ('Genève', '25'), ('BE - Bern', '2')])
def test_a_swiss_office_outside_canton_zurich_is_out_of_area_but_geocoded(office, canton):
    """The spec keeps these: "keep all other postings in storage, flagged
    out_of_scope, since other cantons come later"."""
    answer = geocode.geocode_office(office)
    assert answer['status'] == geocode.OUT_OF_AREA
    assert answer['canton'] == canton
    assert answer['municipality'] is not None


# --- ambiguity, which is refused rather than resolved ------------------------

def test_a_name_several_municipalities_share_is_ambiguous_and_not_the_zurich_one():
    """35 register names collide once the canton suffix is dropped.
    PROJECT.md: only confident matches fill anything."""
    answer = geocode.geocode_office('Buchs')
    assert answer['municipality'] is None
    assert answer['canton'] is None
    assert answer['status'] == geocode.NEEDS_REVIEW
    assert len(answer['candidates']) == 3
    assert answer['swiss_evidence'] is True, 'it names a Swiss place, so a human can settle it'


def test_a_canton_prefix_that_agrees_with_the_name_settles_it():
    answer = geocode.geocode_office('ZH - Buchs')
    assert answer['municipality'] == '83'
    assert taxonomy.entry('municipality', '83')['label'] == 'Buchs (ZH)'
    assert 'canton_prefix' in answer['method']


def test_the_registers_own_suffix_is_matched_as_part_of_the_name():
    assert geocode.geocode_office('Buchs (ZH)')['municipality'] == '83'
    assert geocode.geocode_office('Wiler (Lötschen)')['municipality'] == '6202'


def test_a_postal_code_shared_inside_one_canton_settles_the_canton_only():
    answer = geocode.geocode_office('8910')
    assert answer['municipality'] is None
    assert answer['canton'] == geocode.ZURICH_CANTON
    assert answer['status'] == geocode.IN_AREA, 'in scope, and on the review list for its number'
    assert answer['confidence'] == 0.70


def test_a_swiss_postal_code_beside_a_place_that_is_not_its_own_is_refused():
    """1010 is Lausanne's postal code and Vienna's district code. A
    postal code alone would have answered confidently about a city in
    another country."""
    answer = geocode.geocode_office('1010 Wien')
    assert answer['municipality'] is None
    assert answer['method'] == 'postal_code_vs_name_conflict'
    assert answer['status'] == geocode.NEEDS_REVIEW


def test_a_short_capitalised_code_in_brackets_is_not_a_place():
    """The defect the trial run caught: `knott`'s offices read "Eggstätt
    (EGG)" and "Regenstauf (ZNR)", and splitting on the parenthesis made
    EGG match the Zurich municipality Egg -- eleven German postings filed
    in canton Zurich."""
    for office in ('Eggstätt (EGG)', 'Regenstauf (ZNR)', 'Natzing (NAT)'):
        answer = geocode.geocode_office(office)
        assert answer['municipality'] is None, f'{office} resolved to {answer["municipality"]}'
        assert answer['status'] == geocode.NEEDS_REVIEW
        assert answer['swiss_evidence'] is False, 'nothing Swiss here, so no human is owed'
    assert geocode.geocode_office('Egg')['municipality'] == '192', \
        'the municipality Egg itself still resolves'


@pytest.mark.parametrize('office', ['Remote', 'Home Office', 'remote work', 'Schweiz', ''])
def test_a_non_place_is_answered_rather_than_matched(office):
    answer = geocode.geocode_office(office)
    assert answer['municipality'] is None
    assert answer['status'] == geocode.NEEDS_REVIEW


def test_an_unresolvable_foreign_city_is_separated_from_a_real_review_case():
    """A review list holding every foreign city would be read by nobody.
    Both are excluded from the pool; only one is worth a person's time."""
    assert geocode.geocode_office('Barcelona')['swiss_evidence'] is False
    assert geocode.geocode_office('CH-Bronschhofen')['swiss_evidence'] is True


# --- the posting-level filter ------------------------------------------------

def test_one_zurich_office_among_several_puts_the_posting_in_scope():
    """The spec: "a posting is in scope when at least one of its offices
    geocodes to a municipality in the canton of Zurich"."""
    _, summary = geocode.geocode_offices(['CH - Zürich', 'DE - Berlin', 'CH - Basel'])
    assert summary['status'] == geocode.IN_AREA
    assert summary['municipality'] == '261'
    assert summary['office'] == 'CH - Zürich'


def test_a_posting_with_no_zurich_office_still_says_where_it_is():
    _, summary = geocode.geocode_offices(['DE - Berlin', 'CH - Basel'])
    assert summary['status'] == geocode.OUT_OF_AREA
    assert summary['municipality'] == '2701'


def test_a_posting_with_no_office_at_all_is_a_review_case():
    results, summary = geocode.geocode_offices([])
    assert results == []
    assert summary['status'] == geocode.NEEDS_REVIEW
    assert summary['reason'] == 'the posting names no office'


def test_a_zurich_office_with_a_municipality_speaks_for_the_posting():
    """Two Zurich offices, one resolved to a number and one only to the
    canton: the number is what the posting records."""
    _, summary = geocode.geocode_offices(['8910', '8004 Zürich'])
    assert summary['municipality'] == '261'
    assert summary['confidence'] == 0.95


# --- the value records -------------------------------------------------------

def test_the_location_is_stored_as_two_value_records():
    _, summary = geocode.geocode_offices(['8004 Zürich'])
    records = geocode.location_value_records(summary)
    assert records['municipality']['value'] == '261'
    assert records['canton']['value'] == '1'
    for record in records.values():
        assert record['source'] == 'feed'
        assert record['confidence'] == 0.95
        assert record['evidence']['office'] == '8004 Zürich'
        assert record['evidence']['method']
        assert record['taxonomy_version'] == \
            taxonomy.dimension_meta('municipality')['taxonomy_version']


def test_an_unresolved_office_is_recorded_as_unknown_and_not_as_silence():
    """D4: `unknown` is a real value. "We looked and found nothing" is a
    different fact from no record at all."""
    _, summary = geocode.geocode_offices(['Remote'])
    records = geocode.location_value_records(summary)
    assert records['municipality']['value'] == taxonomy.UNKNOWN
    assert records['canton']['value'] == taxonomy.UNKNOWN
    assert records['municipality']['confidence'] is None
    assert records['municipality']['evidence']['reason']


def test_a_canton_only_answer_records_the_canton_and_an_unknown_municipality():
    _, summary = geocode.geocode_offices(['8910'])
    records = geocode.location_value_records(summary)
    assert records['canton']['value'] == '1'
    assert records['municipality']['value'] == taxonomy.UNKNOWN


def test_the_municipality_label_is_the_registers_own_name():
    assert geocode.municipality_label('261') == 'Zürich'
    assert geocode.municipality_label('83') == 'Buchs (ZH)'
    assert geocode.municipality_label('99999') is None


# --- corroboration: the false positive this module cannot rule out -----------

@pytest.mark.parametrize('office,corroborated', [
    ('8004 Zürich', True),       # a postal code is a code, not a spelling
    ('CH - Zürich', True),       # the office says Switzerland outright
    ('ZH - Buchs', True),        # a canton prefix that agrees with the name
    ('Zürich', False),           # a bare name and nothing else
    ('Zurich (ZRH)', False),
    ('Gebäudetechnik, Lindau', False),
])
def test_an_answer_says_whether_anything_backs_the_name(office, corroborated):
    """A bare name cannot tell a Swiss place from a foreign one that
    shares it: Lindau is a Zurich village and a German town on the
    Bodensee. The trial run found exactly that -- a German company's
    "Gebäudetechnik, Lindau" office put two postings in canton Zurich --
    so the answer says which kind of evidence it has rather than
    guessing."""
    answer = geocode.geocode_office(office)
    assert answer['municipality'] is not None
    assert answer['corroborated'] is corroborated


def test_a_ch_prefix_raises_the_confidence_of_a_name_match():
    bare = geocode.geocode_office('Zürich')
    stated = geocode.geocode_office('CH - Zürich')
    assert stated['municipality'] == bare['municipality'] == '261'
    assert stated['confidence'] > bare['confidence']
    assert stated['method'] == 'name+country_prefix'


def test_a_corroborated_zurich_office_speaks_for_the_posting_over_a_bare_one():
    _, summary = geocode.geocode_offices(['Zürich', '8004 Zürich'])
    assert summary['corroborated'] is True
    assert summary['office'] == '8004 Zürich'
    _, summary = geocode.geocode_offices(['Zürich', 'Winterthur'])
    assert summary['corroborated'] is False


def test_the_location_value_record_carries_the_corroboration():
    _, summary = geocode.geocode_offices(['Gebäudetechnik, Lindau'])
    records = geocode.location_value_records(summary)
    assert records['municipality']['value'] == '176'
    assert records['municipality']['evidence']['corroborated'] is False
