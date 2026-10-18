"""The deterministic layer (CAREER-57 layer 1): that every dimension is
read from the posting's own words, that the longest phrase wins, that an
ambiguity is recorded as one rather than guessed at, and that a value
found only in a long description is flagged instead of trusted."""
import pytest

from careeros import taxonomy
from careeros.classify import rules


def subject(**fields):
    base = {'title': '', 'department': '', 'text': '', 'employer_name': '', 'location_text': ''}
    return base | fields


# --- the matcher ----------------------------------------------------------

def test_the_longest_phrase_wins():
    """The BFS title-assignment idea: a title goes to the most specific
    entry whose wording it carries, not the first that overlaps."""
    table = rules.Table([('general', ('manager',)), ('specific', ('product manager',))])
    code, phrase, _ = table.match('Senior Product Manager')
    assert (code, phrase) == ('specific', 'product manager')


def test_a_phrase_only_matches_whole_words():
    table = rules.Table([('ict', ('ag',))])
    assert table.match('agile delivery') is None
    assert table.match('Beispiel AG') is not None


def test_two_codes_claiming_the_same_phrase_is_not_a_match():
    table = rules.Table([('one', ('head of product',)), ('two', ('head of product',))])
    assert table.match('Head of Product') is None
    best, _ = table.candidates('Head of Product')
    assert sorted(best) == ['one', 'two']


# --- occupation -----------------------------------------------------------

def test_a_title_settles_the_job_family_and_its_isco_group():
    values = rules.occupation(subject(title='Senior Java-Entwickler/in'))
    assert values['occupation_family']['value'] == 'software-developer'
    assert values['isco_unit_group']['value'] == '2512'
    assert values['occupation_family']['source'] == 'rule'
    assert values['occupation_family']['evidence']['phrase'] == 'entwickler'


def test_an_unmapped_local_extension_yields_no_isco_code():
    """Decision 22 scopes the ISCO roll-up guarantee to ESCO-backed
    entries and decision 25 keeps the label expressible, so the family is
    settled and the unit group is honestly unknown."""
    values = rules.occupation(subject(title='Chief Product Officer'))
    assert values['occupation_family']['value'] == 'chief-product-officer'
    assert values['isco_unit_group']['value'] == taxonomy.UNKNOWN
    assert 'local extension' in values['isco_unit_group']['evidence']['rule']


def test_a_phrase_two_families_share_is_recorded_as_ambiguous():
    """`head of product` anchors both ICT product manager and chief
    product officer on purpose. With nothing else to go on, the layer
    refuses rather than letting seed order decide."""
    values = rules.occupation(subject(title='Head of Product'))
    assert values['occupation_family']['value'] == taxonomy.UNKNOWN
    assert rules.review_reason(values['occupation_family']) == 'ambiguous'
    assert values['occupation_family']['evidence']['candidates'] == [
        'chief-product-officer', 'ict-product-manager']


def test_a_tie_is_broken_by_how_much_of_each_vocabulary_the_posting_carries():
    values = rules.occupation(subject(
        title='Head of Product',
        text='Sie leiten unser Produktmanagement und arbeiten mit Product Ownern zusammen.'))
    assert values['occupation_family']['value'] == 'ict-product-manager'


def test_a_family_read_only_from_the_description_is_flagged():
    values = rules.occupation(subject(
        title='Spannende Aufgabe in Zürich',
        text='Sie arbeiten eng mit unserem Data Scientist Team zusammen.'))
    assert values['occupation_family']['value'] == 'data-scientist'
    assert rules.review_reason(values['occupation_family']) == rules.WEAK_IN_TEXT
    assert rules.review_reason(values['isco_unit_group']) == rules.WEAK_IN_TEXT


def test_a_posting_no_keyword_reaches_is_unknown_with_a_reason():
    values = rules.occupation(subject(title='Careers and jobs'))
    assert values['occupation_family']['value'] == taxonomy.UNKNOWN
    assert values['occupation_family']['evidence']['rule']
    assert values['occupation_family']['confidence'] is None


# --- language -------------------------------------------------------------

@pytest.mark.parametrize('text,expected', [
    ('Wir suchen eine Persönlichkeit, die mit uns die Zukunft gestaltet und Erfahrung '
     'mitbringt. Die Aufgaben sind vielfältig und werden von Ihnen verantwortet.', 'de'),
    ('We are looking for a person who will join our team and own this role with us. '
     'You will have the experience that this role is about.', 'en'),
    ('Nous recherchons une personne pour notre équipe, vous travaillez avec nous dans '
     'les projets qui sont importants pour votre avenir.', 'fr'),
])
def test_the_written_language_is_read_from_its_function_words(text, expected):
    record = rules.language(subject(text=text))
    assert record['value'] == expected
    assert record['source'] == 'rule'


def test_a_text_too_short_to_read_is_unknown_rather_than_guessed():
    record = rules.language(subject(title='Barista'))
    assert record['value'] == taxonomy.UNKNOWN
    assert record['confidence'] is None


# --- workload -------------------------------------------------------------

def test_a_pensum_in_the_title_becomes_a_pair_on_the_steps_of_ten():
    values = rules.workload(subject(title='Projektleiter:in 80-100%'))
    assert (values['workload_min']['value'], values['workload_max']['value']) == ('80', '100')


def test_a_pensum_rounds_so_the_range_never_overstates_what_is_asked():
    """workload.yaml: a minimum rounds down and a maximum rounds up."""
    values = rules.workload(subject(title='Sachbearbeiter 85-95%'))
    assert (values['workload_min']['value'], values['workload_max']['value']) == ('80', '100')


def test_a_percentage_in_prose_is_not_a_pensum():
    """The lesson a live Ashby run taught `base.pensum`: "...grew 30%..."
    is a statistic."""
    values = rules.workload(subject(title='Engineering Manager',
                                    text='Our revenue grew 30% last year.'))
    assert values['workload_min']['value'] == taxonomy.UNKNOWN


def test_a_full_position_stated_in_words_is_a_hundred_percent():
    values = rules.workload(subject(title='Buchhalter', text='Vollzeit, unbefristet.'))
    assert (values['workload_min']['value'], values['workload_max']['value']) == ('100', '100')


def test_part_time_without_a_figure_states_no_pensum():
    values = rules.workload(subject(title='Assistenz', text='Teilzeit in unserem Büro.'))
    assert values['workload_min']['value'] == taxonomy.UNKNOWN
    assert rules.review_reason(values['workload_min']) == 'ambiguous'


# --- contract -------------------------------------------------------------

@pytest.mark.parametrize('title,expected', [
    ('Praktikum Marketing 100%', 'internship'),
    ('Lehrstelle als Zeichner:in', 'apprenticeship'),
    ('Working Student Data Engineering', 'working_student'),
    ('Trainee Programme Finance', 'trainee_programme'),
])
def test_a_contract_type_in_the_title_is_read(title, expected):
    assert rules.contract(subject(title=title))['value'] == expected


def test_a_contract_read_only_from_the_description_is_flagged():
    """The same rule as the job family, and the one the pool measurement
    earned: a word in a long description is usually about something
    else."""
    record = rules.contract(subject(title='Software Engineer',
                                    text='Die Stelle ist unbefristet.'))
    assert record['value'] == 'permanent'
    assert rules.review_reason(record) == rules.WEAK_IN_TEXT


def test_nothing_defaults_to_permanent():
    """The most common answer is not evidence for this one."""
    record = rules.contract(subject(title='Software Engineer', text='Join our team.'))
    assert record['value'] == taxonomy.UNKNOWN


def test_a_qualification_code_is_not_a_contract_type():
    """Measured over the pool: "Ausbildung als Informatiker/in EFZ" in a
    requirements list made five postings apprenticeships."""
    record = rules.contract(subject(
        title='Workplace Engineer',
        text='Abgeschlossene Ausbildung als Informatiker/in EFZ oder vergleichbar.'))
    assert record['value'] == taxonomy.UNKNOWN


def test_an_agency_posting_carries_the_flag_and_keeps_its_contract_code():
    record = rules.contract(subject(
        title='Projektleiter unbefristet',
        text='Im Auftrag unseres Kunden suchen wir eine Persönlichkeit.'))
    assert record['value'] == 'permanent'
    assert record['flags'] == ['via_agency']
    assert record['guide_version']


# --- work model, seniority, employer type ---------------------------------

@pytest.mark.parametrize('text,expected', [
    ('Bis zu 2-3 Tage Homeoffice pro Woche.', 'hybrid'),
    ('We are a remote-first company.', 'remote'),
    ('Die Arbeit findet vor Ort in Zürich statt.', 'onsite'),
])
def test_the_work_model_is_read_from_the_posting(text, expected):
    assert rules.work_model(subject(text=text))['value'] == expected


@pytest.mark.parametrize('title,expected', [
    ('Praktikant:in Controlling', 's0'),
    ('Junior Software Engineer', 's1'),
    ('Senior Product Manager', 's3'),
    ('Head of Engineering', 's4'),
    ('Chief Financial Officer', 's5'),
])
def test_the_seniority_scale_is_read_from_the_title(title, expected):
    assert rules.seniority(subject(title=title))['value'] == expected


def test_manager_alone_is_not_a_seniority_step():
    """"Product Manager" is a job family, not a rank, whatever the
    retired ordinal's crosswalk says about the word `manager`."""
    assert rules.seniority(subject(title='Product Manager'))['value'] == taxonomy.UNKNOWN


@pytest.mark.parametrize('name,expected', [
    ('Zürcher Kantonalbank', 'public_enterprise'),
    ('Stadt Zürich', 'public'),
    ('Beispiel AG', 'private'),
    ('Stiftung Kinderdorf', 'nonprofit'),
    ('Beispiel Personalberatung', 'agency'),
])
def test_the_employer_type_is_read_from_the_name(name, expected):
    assert rules.employer_type(subject(employer_name=name))['value'] == expected


def test_a_longer_name_phrase_beats_a_legal_form_suffix():
    """A cantonal bank is an AG too."""
    assert rules.employer_type(subject(employer_name='Zürcher Kantonalbank AG'))['value'] \
        == 'public_enterprise'


# --- location -------------------------------------------------------------

def test_a_typed_place_is_coded_through_the_shared_geocoder():
    values = rules.location(subject(location_text='8001 Zürich'))
    assert values['municipality']['value'] == '261'
    assert values['canton']['value'] == '1'
    assert values['municipality']['source'] == 'rule'


def test_no_place_is_two_unknown_records_rather_than_no_records():
    values = rules.location(subject())
    assert set(values) == {'municipality', 'canton'}
    assert all(record['value'] == taxonomy.UNKNOWN for record in values.values())


# --- the whole layer ------------------------------------------------------

def test_every_field_gets_a_record_even_when_nothing_matched():
    """D4: `unknown` is a real value. "We looked and found nothing" is a
    different fact from no record at all."""
    values = rules.classify(subject(title='x'))
    assert set(values) == set(rules.FIELDS)
    assert all(record['taxonomy_version'] and record['classified_at']
               for record in values.values())


def test_every_record_names_its_source_and_its_taxonomy_version():
    values = rules.classify(subject(title='Senior Product Owner 80%',
                                    employer_name='Beispiel AG'))
    for field, record in values.items():
        assert record['source'] == 'rule', field
        assert record['standard_version'], field
