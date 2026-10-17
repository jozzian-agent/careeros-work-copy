"""The taxonomy code lists and the D4 value-record factory: that the
shipped files stay loadable and honest about themselves, that a value
record cannot be built in a shape the owner did not decide, and that the
three places which used to hold their own size vocabulary now agree."""
from datetime import datetime
from pathlib import Path
import logging

import pytest
import yaml

from careeros import enrich, taxonomy, vault
from org_intake import classify

ESCO_SEED = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / 'careeros/data/esco_occupations.yaml').read_text())


# --- The files, and what they promise about themselves --------------------

def test_every_dimension_carries_its_standard_and_version():
    """A code list with no version and no date is one nothing can reason
    about later: a stored value record names the taxonomy_version it was
    classified under, so every dimension has to have one."""
    assert taxonomy.DIMENSIONS
    for dimension in taxonomy.DIMENSIONS:
        meta = taxonomy.dimension_meta(dimension)
        assert meta['standard'] and meta['standard_version'] and meta['changed_at']
        taxonomy._version_key(meta['taxonomy_version'])
    taxonomy._version_key(taxonomy.TAXONOMY_VERSION)


def test_a_complete_dimension_has_codes_and_an_empty_one_says_it_is_incomplete():
    """The honesty rule the stubs depend on. CH-ISCO-19's 5-digit list,
    the BFS municipalities and the NOGA divisions ship empty, and a
    caller is only safe reading `valid_code` as "invalid" when the
    dimension says it is complete."""
    for dimension in taxonomy.DIMENSIONS:
        meta = taxonomy.dimension_meta(dimension)
        if meta['complete']:
            assert taxonomy.codes(dimension), dimension
        else:
            assert meta['todo'], dimension


def test_an_incomplete_dimension_names_where_the_rest_comes_from():
    """A stub with no source is a dead end. Every incomplete list's todo
    has to say what is missing, and the file it sits in has to carry a
    source_url."""
    for dimension in taxonomy.DIMENSIONS:
        meta = taxonomy.dimension_meta(dimension)
        if meta['complete']:
            continue
        document = taxonomy.document(meta['file'].removesuffix('.yaml'))
        assert document.get('source_url') or meta['todo'], dimension


def test_code_lists_are_frozen():
    """Reference data read once at import: a caller that could mutate what
    it was handed would change the taxonomy for the whole process."""
    with pytest.raises(TypeError):
        taxonomy.entries('company_size')[0]['label'] = 'Tiny'
    with pytest.raises(TypeError):
        taxonomy.labels('company_size')['micro'] = 'Tiny'
    with pytest.raises(TypeError):
        taxonomy.document('company_size')['standard'] = 'made up'


def test_an_unknown_dimension_is_a_key_error_naming_the_known_ones():
    with pytest.raises(KeyError, match='company_size'):
        taxonomy.valid_code('company_sizes', 'micro')
    with pytest.raises(KeyError):
        taxonomy.document('no_such_file')


def test_valid_code_and_the_unknown_value():
    assert taxonomy.valid_code('company_size', 'xl')
    assert not taxonomy.valid_code('company_size', 'huge')
    # D4: `unknown` is a real value for every dimension, and part of none
    # (except permit_requirement, where the posting's silence IS the code).
    for dimension in taxonomy.DIMENSIONS:
        assert taxonomy.valid_code(dimension, taxonomy.UNKNOWN), dimension
    assert taxonomy.UNKNOWN not in taxonomy.codes('company_size')


def test_codes_keep_file_order_because_the_order_is_meaningful():
    assert taxonomy.codes('company_size') == ('micro', 'small', 'medium', 'large', 'xl')
    assert taxonomy.codes('seniority') == ('s0', 's1', 's2', 's3', 's4', 's5')


# --- One size vocabulary, in three places that used to disagree ----------

def test_the_size_vocabulary_is_one_list():
    """It used to be three: a tuple in vault, SIZE_CLASS_ORDER in the
    taxonomy page, and the capability's own constant. Two of them are now
    the data file; the capability keeps its own (it imports nothing from
    the product), so this pins them against each other."""
    assert vault.SIZE_CLASSES == taxonomy.codes('company_size')
    assert tuple(classify.SIZE_CLASSES) == taxonomy.codes('company_size')


@pytest.mark.parametrize('code,count_in,count_above', [
    ('micro', 1, 10), ('micro', 9, 10),
    ('small', 10, 50), ('small', 49, 50),
    ('medium', 50, 250), ('medium', 249, 250),
    ('large', 250, 1000), ('large', 999, 1000),
])
def test_the_data_file_bounds_and_the_capability_thresholds_say_the_same_thing(code, count_in, count_above):
    """D3: the BFS boundaries. The class bounds written in
    company_size.yaml and the thresholds `classify.size_class_for` applies
    are two statements of one decision, so a count at either edge has to
    land where the file says."""
    entry = taxonomy.entry('company_size', code)
    assert entry['min'] <= count_in <= entry['max']
    assert classify.size_class_for(count_in) == code
    assert classify.size_class_for(count_above) != code


def test_xl_is_the_open_ended_class_and_marked_as_a_local_addition():
    xl = taxonomy.entry('company_size', 'xl')
    assert xl['min'] == 1000 and xl['max'] is None and xl['local'] is True
    assert classify.size_class_for(1000) == 'xl'


# --- The D4 value record -------------------------------------------------

def test_make_value_record_is_the_d4_shape_with_the_dimensions_own_versions():
    record = taxonomy.make_value_record('company_size', 'medium', 'feed',
                                        confidence=0.8, evidence={'job_id': 'JOB-001'},
                                        classified_at='2026-10-17T09:00:00+00:00')
    assert record == {
        'value': 'medium',
        'source': 'feed',
        'confidence': 0.8,
        'evidence': {'job_id': 'JOB-001'},
        'taxonomy_version': taxonomy.dimension_meta('company_size')['taxonomy_version'],
        'standard_version': taxonomy.dimension_meta('company_size')['standard_version'],
        'classified_at': '2026-10-17T09:00:00+00:00',
        'flags': [],
        'guide_version': None,
    }


def test_make_value_record_defaults_classified_at_to_now():
    record = taxonomy.make_value_record('company_size', taxonomy.UNKNOWN, 'llm')
    assert record['classified_at'].startswith('20')
    assert datetime.fromisoformat(record['classified_at'])


@pytest.mark.parametrize('kwargs,message', [
    ({'value': 'huge'}, 'not a valid company_size code'),
    ({'value': ''}, 'non-empty code'),
    ({'value': None}, 'non-empty code'),
    ({'source': 'guess'}, 'unknown source'),
    ({'confidence': 1.5}, 'between 0 and 1'),
    ({'confidence': True}, 'between 0 and 1'),
    ({'confidence': 'high'}, 'between 0 and 1'),
    ({'evidence': ''}, 'evidence must be'),
    ({'evidence': 7}, 'evidence must be'),
    ({'classified_at': 'last tuesday'}, 'not an ISO-8601 timestamp'),
    ({'classified_at': 20261017}, 'ISO-8601 timestamp string'),
    ({'flags': ['typo']}, 'unknown flag'),
    ({'flags': ['unsure']}, 'need the guide_version'),
])
def test_make_value_record_refuses_a_field_it_cannot_stand_behind(kwargs, message):
    arguments = {'dimension': 'company_size', 'value': 'medium', 'source': 'llm'} | kwargs
    with pytest.raises(ValueError, match=message):
        taxonomy.make_value_record(**arguments)


def test_flags_are_deduplicated_and_sorted_and_carry_their_guide_version():
    record = taxonomy.make_value_record('company_size', 'small', 'llm',
                                        flags=['unsure', 'implicit', 'unsure'],
                                        guide_version='labelling-guide-1')
    assert record['flags'] == ['implicit', 'unsure']
    assert record['guide_version'] == 'labelling-guide-1'


def test_a_code_outside_an_incomplete_list_is_kept_and_logged(caplog):
    """An incomplete list must not reject a real value. The municipality
    register was loaded in CAREER-53 but stays incomplete, because it
    changes several times a year through mergers: a number the register
    gains after the load date has to be recorded rather than refused, and
    the LIST is what the log line says needs extending.

    `'261'` (Zürich) was the example here while the list was an empty
    stub; it is in the list now, so the example is a number the register
    does not issue."""
    assert taxonomy.valid_code('municipality', '261'), 'the register load is what this rests on'
    with caplog.at_level(logging.WARNING, logger='careeros.taxonomy'):
        record = taxonomy.make_value_record('municipality', '99999', 'feed')
    assert record['value'] == '99999'
    assert 'location.yaml' in caplog.text and '99999' in caplog.text


def test_source_precedence_is_the_data_side_of_human_edits_win():
    assert taxonomy.SOURCE_PRECEDENCE == ('admin', 'user', 'feed', 'rule', 'llm')
    assert taxonomy.source_wins('admin', 'llm') is True
    assert taxonomy.source_wins('llm', 'admin') is False
    assert taxonomy.source_wins('feed', 'feed') is False  # a tie leaves the stored value alone
    assert taxonomy.source_wins('llm', None) is True  # nothing stored yet
    with pytest.raises(ValueError, match='unknown source'):
        taxonomy.source_wins('guess', 'llm')


def test_the_labelling_guide_flags_are_the_ones_the_decision_sheet_lists():
    assert set(taxonomy.FLAGS) == {'implicit', 'new_skill', 'multi_role', 'gsw_understand',
                                   'gsw_speak', 'assumed_13', 'via_agency', 'sure', 'unsure'}


# --- Dimensions whose content is a decision, not a standard --------------

def test_the_seniority_crosswalk_covers_every_retired_ordinal_value():
    """D6 retires `enrich.SENIORITY`, and the crosswalk is what makes a
    stored seniority recomputable on the s-scale. A value with no mapping
    would be a record nothing can convert."""
    crosswalk = taxonomy.seniority_crosswalk()
    for level in enrich.SENIORITY:
        assert level in crosswalk, level
    for alias in enrich.ALIASES:
        assert alias in crosswalk, alias
    for old, mapped in crosswalk.items():
        assert taxonomy.valid_code('seniority', mapped['seniority']), old
        for flag in mapped['flags']:
            assert taxonomy.valid_code('seniority_flag', flag), (old, flag)


def test_a_qualification_level_is_nullable_and_otherwise_inside_the_nqr():
    """D7: bm, gym, cas/das/mas and cert have no NQR level. A zero or a
    guessed level would make them comparable to a Bachelor by accident."""
    levelless = {'bm', 'gym', 'cas', 'das', 'mas', 'cert'}
    for entry in taxonomy.entries('qualification_type'):
        level = entry['nqr_level']
        if entry['code'] in levelless:
            assert level is None, entry['code']
        else:
            assert isinstance(level, int) and 1 <= level <= 8, entry['code']


def test_workload_codes_are_the_pensum_steps_the_range_declares():
    workload = taxonomy.document('workload')['range']
    expected = tuple(str(step) for step in
                     range(workload['min'], workload['max'] + 1, workload['step']))
    assert taxonomy.codes('workload') == expected


def test_language_codes_look_like_iso_639_1_and_swiss_german_is_not_one():
    codes = taxonomy.codes('language')
    assert {'de', 'fr', 'it', 'rm', 'en'} <= set(codes)
    assert all(len(code) == 2 and code.isalpha() and code.islower() for code in codes)
    # Swiss German has no ISO 639-1 code at all, which is why it is a
    # flag: coining one would be the fabrication this taxonomy forbids.
    assert 'gsw' not in codes
    assert {'gsw_understand', 'gsw_speak'} <= set(taxonomy.FLAGS)


def test_the_job_side_permit_rule_treats_silence_as_its_own_answer():
    assert taxonomy.codes('permit_requirement') == ('open', 'permit_required', 'sponsorship', 'unknown')


def test_noga_ships_every_section_and_derives_them_from_division_ranges():
    sections = taxonomy.codes('noga_section')
    assert len(sections) == 21
    ranges = taxonomy.document('industry_noga')['derivation']['section_of_division']
    assert tuple(ranges) == sections
    # Inclusive, ordered, non-overlapping: a division belongs to one
    # section or the derivation is not a derivation.
    bounds = [(int(low), int(high)) for low, high in ranges.values()]
    assert all(low <= high for low, high in bounds)
    assert all(previous[1] < nxt[0] for previous, nxt in zip(bounds, bounds[1:]))


# --- The family layer, against the seed it is drawn from -----------------

def test_every_family_isco_code_is_a_unit_group_this_taxonomy_knows():
    """The "clean" half of D1: a family may be unmapped, but it may not
    point at a four-digit group that is not in the ISCO list, because
    grading and the roll-up both read that code."""
    for entry in taxonomy.entries('occupation_family'):
        if entry['isco4'] is not None:
            assert taxonomy.valid_code('isco_unit_group', entry['isco4']), entry['code']


def test_the_family_layer_and_the_extraction_seed_cannot_drift():
    """The two files hold the same 40 ids on purpose (the seed carries
    keywords and citations, this layer carries the mapping and its
    status). Keeping them in step is this test's job, not a comment's."""
    seed = {entry['id']: entry for entry in ESCO_SEED['occupations']}
    families = {entry['code']: entry for entry in taxonomy.entries('occupation_family')}
    assert set(families) == set(seed)
    for code, family in families.items():
        source = seed[code]
        assert family['label'] == source['label']
        assert family['label_de'] == source['label_de']
        assert taxonomy.valid_code('occupation_family_status', family['status'])
        if source.get('esco_uri'):
            assert family['status'] == 'verified'
            assert family['esco_uri'] == source['esco_uri']
            assert family['isco4'] == source['isco']
        elif source.get('local'):
            # D1: the five local labels stay unmapped, with a flag.
            assert family['status'] == 'unmapped'
            assert family['isco4'] is None and family['review'] == 'unmapped_local_extension'
        else:
            assert family['status'] == 'proposed'
            assert family['isco4'] == source['isco']


def test_the_family_status_split_is_the_one_the_owner_ruling_names():
    statuses = [entry['status'] for entry in taxonomy.entries('occupation_family')]
    assert len(statuses) == 40
    assert statuses.count('verified') == 10
    assert statuses.count('proposed') == 25
    assert statuses.count('unmapped') == 5
