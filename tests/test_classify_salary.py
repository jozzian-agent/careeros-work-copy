"""Salary normalisation (CAREER-57): that the three formulas in
salary_rules.yaml are applied as written, that every assumption is
visible on the record, that a range stays a range, and that a number
which is not a salary is not read as one."""
import pytest

from careeros.classify import salary


def read(text, **fields):
    return salary.read(text, **fields)


# --- reading --------------------------------------------------------------

def test_an_annual_range_keeps_both_bounds():
    """A salary range is two numbers the employer means; nothing picks a
    midpoint."""
    reading = read("Wir bieten einen Jahreslohn von CHF 110'000 bis 130'000.")
    assert (reading['min'], reading['max']) == (110000.0, 130000.0)
    assert reading['period_stated'] == 'year'


def test_a_single_figure_is_a_range_of_one():
    reading = read("Bruttomonatsgehalt: CHF 6'500 pro Monat.")
    assert (reading['min'], reading['max']) == (6500.0, 6500.0)


def test_an_amount_with_no_pay_word_near_it_is_not_a_salary():
    assert read('Backed by over CHF 650 000 000 per year in funding.') is None


def test_an_amount_with_no_stated_period_is_not_read():
    """An unlabelled 85 000 is annual and an unlabelled 45 is not a
    salary; the honest answer is no reading."""
    assert read("Unser Lohnsystem ist transparent: CHF 85'000.") is None


def test_an_implausible_figure_is_refused_rather_than_normalised():
    assert read('Our salary budget is CHF 50 000 000 per year.') is None


@pytest.mark.parametrize('written,expected', [
    ("110'000", 110000.0), ('110 000', 110000.0), ('6500.50', 6500.5), ('6500,50', 6500.5),
])
def test_swiss_and_english_number_forms_are_read(written, expected):
    assert salary._number(written) == expected


# --- the formulas ---------------------------------------------------------

def test_a_monthly_figure_is_multiplied_by_thirteen_and_says_so():
    """x13_default: a Swiss salary is usually paid in thirteen
    instalments, and the derived value carries the `assumed_13` flag so
    nothing presents it as stated."""
    block = salary.normalise(read("Monatslohn CHF 6'000 pro Monat."))
    assert block['annual_gross_chf_min'] == 78000.0
    assert block['months_assumed'] == 13
    assert block['flags'] == ['assumed_13']
    assert block['rules'] == ['x13_default']


def test_a_posting_that_states_its_payment_count_raises_no_flag():
    block = salary.normalise(read('Gehalt CHF 8000 pro Monat, 12 Monatslöhne.'))
    assert (block['months_assumed'], block['annual_gross_chf_min']) == (12, 96000.0)
    assert block['flags'] == []


def test_an_hourly_rate_uses_the_forty_hour_fifty_two_week_convention():
    block = salary.normalise(read('Stundenlohn CHF 25.00 pro Stunde.'))
    assert block['annual_gross_chf_min'] == 25 * 40 * 52
    assert block['rules'] == ['hourly_to_annual']


def test_an_hourly_rate_is_never_scaled_by_a_pensum():
    """`hourly * 40 * 52` is already the annual at 100%: the rate is per
    hour worked. Dividing it by a 55% Pensum again would invent half a
    salary (found on a live pool posting)."""
    block = salary.normalise(read('Stundenlohn ab CHF 25.25 brutto pro Stunde.'),
                             pensum=(55, 55))
    assert block['annual_gross_chf_min'] == round(25.25 * 40 * 52, 2)
    assert 'pensum_scaling' not in block['rules']
    assert block['pensum_stated'] == [55, 55]


def test_a_monthly_figure_for_a_part_time_post_is_scaled_to_a_full_one():
    block = salary.normalise(read('Monatslohn CHF 4000 pro Monat.'), pensum=(50, 50))
    assert block['annual_gross_chf_min'] == 104000.0
    assert 'pensum_scaling' in block['rules']


def test_a_pensum_range_is_scaled_by_its_maximum_and_keeps_the_range():
    """salary_rules.yaml: when the posting does not say which bound the
    money is for, the maximum is used and the stated Pensum stays on the
    record, so the choice is visible."""
    block = salary.normalise(read('Jahreslohn CHF 80 000 pro Jahr.'), pensum=(80, 100))
    assert block['annual_gross_chf_min'] == 80000.0
    assert block['pensum_stated'] == [80, 100]


def test_a_foreign_currency_is_kept_and_not_converted():
    block = salary.normalise(read('Salary EUR 90 000 per year.'))
    assert block['currency'] == 'EUR'
    assert block['annual_gross_chf_min'] is None
    assert 'no conversion rule' in block['needs_review']


def test_no_salary_statement_means_no_block_at_all():
    """The common case, and not a zero."""
    assert salary.normalise(read('Wir bieten eine spannende Aufgabe.')) is None


def test_the_block_names_the_target_it_was_normalised_onto():
    block = salary.normalise(read('Jahreslohn CHF 120 000 pro Jahr.'))
    assert block['target'] == 'annual gross, CHF, at 100% Pensum'
    assert block['source'] == 'rule'


def test_a_posting_is_scaled_by_the_pensum_the_workload_rule_read():
    """One Pensum reading for the whole posting, so a job saying
    "80-100%" and "CHF 90 000" is not normalised twice."""
    block = salary.classify({'title': 'Controller 50%',
                             'text': 'Pensum 50%. Monatslohn CHF 4000 pro Monat.'})
    assert block['pensum_stated'] == [50, 50]
    assert block['annual_gross_chf_min'] == 104000.0
