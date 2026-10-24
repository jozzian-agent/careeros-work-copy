"""ISIC Rev.4 section matching and EU-threshold size derivation. Pure,
offline, deterministic logic; no network I/O.

Ported from careeros tests/test_sectors.py's pure classify.py-equivalent
cases (sectors_cascade/external_sectors network-backed cases live in
test_enrich.py instead).

Rule coverage: rule 7 (keyword matching with ambiguity refusal), rule 8
(size_class, the one size scale, derived from one count).
"""
import pytest

from org_intake import classify


# --- Rule 7: keyword-match function with ambiguity refusal -----------------

@pytest.mark.parametrize('text,expected', [
    ('Software and IT services', ['J']),
    ('Banking and insurance', ['K']),
    ('Logistics and warehousing', ['H']),
    ('Technology', []),  # genuinely ambiguous between J and M: refuse, do not guess
    ('Nonsense industry label', []),  # no match: refuse
    ('', []),
])
def test_match_sectors_confidence_and_ambiguity(text, expected):
    assert classify.match_sectors(text) == expected


@pytest.mark.parametrize('text,expected', [
    ('technology industry', ['J']),  # longer, specific keyword outranks the
    ('information technology', ['J']),  # generic "technology" word M also has
    ('pharmaceutical industry', ['C']),
    ('automotive industry', ['C']),  # manufacturing (ISIC div. 29), not G
    ('cryptocurrency', ['K']),
    ('fintech', ['K']),
    ('electrical engineering', ['C']),
    ('cloud computing', ['J']),
])
def test_match_sectors_widened_vocabulary_classes(text, expected):
    assert classify.match_sectors(text) == expected


def test_specificity_tie_break_resolves_generic_vs_specific_restatement_only():
    # The tie-break must only resolve generic-vs-specific restatements of
    # the SAME phrase, never independent keywords from unrelated activities
    # that merely happen to co-occur in one text.
    assert classify.all_matched_sections('electrical engineering') == ['C']
    assert classify.all_matched_sections('cloud computing') == ['J']
    assert classify.match_sectors('Technology') == []
    assert classify.match_sectors('software and retail') == []


def test_match_sectors_bare_technology_still_ambiguous_after_vocabulary_widening():
    assert classify.match_sectors('Technology') == []
    assert classify.all_matched_sections('Technology') == ['J', 'M']


@pytest.mark.parametrize('text', ['software and retail', 'mining and manufacturing'])
def test_match_sectors_independent_keywords_stay_ambiguous(text):
    assert classify.match_sectors(text) == []


def test_all_matched_sections_independent_keywords_returns_both_unresolved():
    assert classify.all_matched_sections('software and retail') == ['G', 'J']
    assert classify.all_matched_sections('mining and manufacturing') == ['B', 'C']


def test_known_section_codes_are_isic_sections():
    assert classify.known_section_codes() == {s['code'] for s in classify.load_isic_sections()}
    assert len(classify.known_section_codes()) == 21


# --- Rule 8: the EU class is the one size this module derives -------------

@pytest.mark.parametrize('count,size_class', [
    # Rule 8's classes, each boundary count being the LOWER edge of the
    # class above (2026-10-17): micro 1-9, small 10-49, medium 50-249,
    # large 250-999, xl 1000+. The 10/50/250 cases are the off-by-one this
    # replaced: they used to answer micro/small/medium.
    (1, 'micro'), (9, 'micro'),
    (10, 'small'), (49, 'small'),
    (50, 'medium'), (249, 'medium'),
    (250, 'large'), (999, 'large'),
    (1000, 'xl'), (1001, 'xl'),
])
def test_derive_size_boundary_values(count, size_class):
    assert classify.derive_size(count) == {'size_class': size_class}


def test_derive_size_never_hands_back_the_retired_numeric_scale():
    """Rule 8 as of 2026-10-15: one scale, so one key. A derivation that
    kept returning `size_range` beside the class invited every caller to
    persist the retired scale again, which is what eroded it. The bucket
    labels themselves stay available as a read helper."""
    assert classify.derive_size(1500) == {'size_class': 'xl'}
    assert classify.size_range_bucket(1500) == '1000+'


def test_derive_size_rejects_nonpositive_and_non_numeric():
    assert classify.derive_size(0) is None
    assert classify.derive_size(-5) is None
    assert classify.derive_size(True) is None
    assert classify.derive_size('bad') is None


def test_resolve_employee_count_range_resolves_to_upper_bound():
    assert classify.resolve_employee_count('50-100') == 100
    assert classify.resolve_employee_count('50 – 100') == 100
    assert classify.resolve_employee_count(42) == 42
    assert classify.resolve_employee_count('unknown') is None


# --- Rule 11: fill-empty-only, never overwrites a populated field ----------

def test_fill_size_updates_never_overwrites_populated_field():
    assert classify.fill_size_updates(1500, '1-10', None) == {}  # contradicts size_range: refuse
    assert classify.fill_size_updates(1500, None, 'micro') == {}  # contradicts size_class: refuse
    assert classify.fill_size_updates(1500, None, None) == {'size_class': 'xl'}
    assert classify.fill_size_updates(1500, '1000+', None) == {'size_class': 'xl'}
    assert classify.fill_size_updates(1500, '1000+', 'xl') == {}
    # A stored class settles size, so a consistent count has nothing left
    # to fill: the numeric scale it used to complete here is retired.
    assert classify.fill_size_updates(1500, None, 'xl') == {}
    # 'large' tops out at 999 since 2026-10-17, so a 1500-person count no
    # longer agrees with it: that is a contradiction to flag, not a fill.
    assert classify.fill_size_updates(1500, None, 'large') == {}


def test_count_conflicts_with_stored_size_separates_agreement_from_contradiction():
    """Rule 11, asked on its own. "Nothing to fill" and "this evidence
    contradicts the record" stopped being the same answer once the class
    became the only field anything fills, and a caller that read an empty
    fill as a conflict would flag every company whose stored class the
    evidence simply confirms."""
    assert classify.count_conflicts_with_stored_size(1500, None, 'xl') is False  # agrees
    assert classify.count_conflicts_with_stored_size(1500, None, 'micro') is True
    # 'large' is 250-999 since 2026-10-17, so 1500 contradicts it too.
    assert classify.count_conflicts_with_stored_size(1500, None, 'large') is True
    assert classify.count_conflicts_with_stored_size(1500, '1-10', None) is True  # the retired scale is still read
    assert classify.count_conflicts_with_stored_size(1500, '1000+', 'xl') is False
    assert classify.count_conflicts_with_stored_size(None, None, 'large') is False  # no evidence
    assert classify.count_conflicts_with_stored_size('bad', None, 'large') is False  # unreadable: not evidence


@pytest.mark.parametrize('size_hint,size_range,expected', [
    ('xl', '1000+', True),
    ('large', '1000+', False),  # every count in '1000+' is xl since 2026-10-17
    ('large', '1-10', False),  # '1-10' tops out at 10 employees: never 'large'
    ('micro', '1-10', True),
    ('small', '1-10', True),  # the bucket straddles the 9/10 class edge
    ('medium', '11-50', True),  # count==50 is 'medium' now, so the bucket straddles small/medium
    ('small', '11-50', True),
    ('large', '11-50', False),
    ('medium', '51-200', True),
    ('medium', '201-1000', True),
    # '201-1000' spans medium (201-249), large (250-999) and xl (1000), so
    # all three are consistent with it and nothing between the bounds is
    # skipped.
    ('large', '201-1000', True),
    ('xl', '201-1000', True),
    ('small', '201-1000', False),
])
def test_size_class_hint_consistent_with_range(size_hint, size_range, expected):
    assert classify.size_class_hint_consistent_with_range(size_hint, size_range) == expected
