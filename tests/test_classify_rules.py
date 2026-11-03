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

def test_the_rules_layer_leaves_the_job_family_to_the_model():
    """CAREER-138: the keyword table read "Pizzabäcker" as
    `product-manager` and could not read "BA-Student" at all, so the
    family decision moved to the model layer. The rules layer still
    writes the record -- `unknown` with its reason, because "we looked"
    is a different fact from no record (D4) -- and that unknown is what
    makes the family an open field the model is asked about."""
    values = rules.occupation(subject(title='Senior Java-Entwickler/in'))
    assert values['occupation_family']['value'] == taxonomy.UNKNOWN
    assert values['occupation_family']['source'] == 'rule'
    assert values['occupation_family']['evidence']['rule'] == rules.FAMILY_DECIDED_BY_MODEL
    assert values['occupation_family']['confidence'] is None
    # The unit group is derived from that unknown family, so it is
    # unknown too -- until the model settles the family and the pipeline
    # re-derives it (classify.settle_isco).
    assert values['isco_unit_group']['value'] == taxonomy.UNKNOWN


def test_a_settled_family_still_derives_its_isco_group():
    """`derive_isco` is unchanged: whatever family wins the merge, the
    group is read off it."""
    record = taxonomy.make_value_record('occupation_family', 'software-developer', 'llm')
    assert rules.derive_isco(record)['value'] == '2512'


def test_an_unmapped_local_extension_yields_no_isco_code():
    """Decision 22 scopes the ISCO roll-up guarantee to ESCO-backed
    entries and decision 25 keeps the label expressible, so the family is
    settled and the unit group is honestly unknown.

    The example was `Chief Product Officer` until v2 merged that family
    into product-manager, which does carry a code; three local extensions
    are left and this is one of them."""
    record = taxonomy.make_value_record(
        'occupation_family', 'embedded-systems-security-engineer', 'llm')
    derived = rules.derive_isco(record)
    assert derived['value'] == taxonomy.UNKNOWN
    assert 'local extension' in derived['evidence']['rule']


def test_a_family_with_no_isco_reading_yet_also_yields_no_code():
    """v2's 24 new families carry no `isco4` either, for a different
    reason: not "there is no concept" but "there is no confirmed unit
    group yet" -- a 4-digit code is derived from an ESCO concept and
    these labels have none. They DO have a 3-digit home since CAREER-130
    (see `derive_minor_group` below), which is a different level and does
    not fill this one in. The family is still settled, and the unit group
    is unknown rather than guessed."""
    record = taxonomy.make_value_record('occupation_family', 'project-manager', 'llm')
    derived = rules.derive_isco(record)
    assert derived['value'] == taxonomy.UNKNOWN
    assert derived['evidence']['occupation_family'] == 'project-manager'


def test_a_family_the_current_list_does_not_carry_yields_a_reason_not_a_crash():
    """A record classified under v1 can name a family v2 merged away, and
    a re-classification pass must survive reading it (CAREER-129): no
    KeyError, and no code borrowed from a neighbouring family."""
    record = dict(taxonomy.make_value_record('occupation_family', 'product-manager', 'llm'),
                  value='chief-product-officer')
    derived = rules.derive_isco(record)
    assert derived['value'] == taxonomy.UNKNOWN
    assert rules.review_reason(derived) == rules.FAMILY_NOT_IN_TAXONOMY
    assert derived['evidence']['occupation_family'] == 'chief-product-officer'


# --- the 3-digit minor group (CAREER-130) ---------------------------------

def test_a_settled_family_derives_its_minor_group_at_the_familys_own_confidence():
    """A derived value is never surer than what it was derived from, so
    the family's confidence travels with the code rather than a new one
    being invented for it."""
    family = taxonomy.make_value_record('occupation_family', 'software-developer', 'llm',
                                        confidence=0.8)
    derived = rules.derive_minor_group(family)
    assert derived['value'] == '251'
    assert derived['confidence'] == family['confidence']
    assert derived['source'] == 'rule'
    assert derived['evidence']['occupation_family'] == 'software-developer'


def test_a_family_with_no_four_digit_code_still_has_a_three_digit_home():
    """The whole point of CAREER-130: `project-manager` has no `isco4`
    and the minor group is NOT a prefix of one, so it is read from the
    owner-approved `isco3` instead. Deriving it by slicing would have
    left exactly these families empty."""
    record = taxonomy.make_value_record('occupation_family', 'project-manager', 'llm')
    assert rules.derive_isco(record)['value'] == taxonomy.UNKNOWN
    derived = rules.derive_minor_group(record)
    assert derived['value'] == '121'
    assert derived['evidence']['alternates'] == ['242', '133', '132']


def test_a_family_with_one_home_carries_no_alternates_key():
    record = taxonomy.make_value_record('occupation_family', 'accountant', 'llm')
    derived = rules.derive_minor_group(record)
    assert derived['value'] == '241'
    assert 'alternates' not in derived['evidence']


def test_an_unsettled_family_derives_an_unknown_minor_group_with_its_reason():
    values = rules.occupation(subject(title='Head of Product'))
    derived = rules.derive_minor_group(values['occupation_family'])
    assert derived['value'] == taxonomy.UNKNOWN
    assert 'unsettled' in derived['evidence']['rule']


def test_a_flagged_family_hands_its_flag_to_the_minor_group():
    """A family a human is owed a second look on hands its doubt to the
    derived group rather than the group looking settled."""
    family = taxonomy.make_value_record(
        'occupation_family', 'data-scientist', 'llm',
        evidence={'needs_review': rules.WEAK_IN_TEXT})
    derived = rules.derive_minor_group(family)
    assert derived['value'] == '251'
    assert rules.review_reason(derived) == rules.WEAK_IN_TEXT


def test_a_family_the_current_list_does_not_carry_has_no_minor_group_either():
    """Total on a stored record, like `derive_isco`: no KeyError, and no
    code borrowed from a neighbouring family."""
    record = dict(taxonomy.make_value_record('occupation_family', 'product-manager', 'llm'),
                  value='chief-product-officer')
    derived = rules.derive_minor_group(record)
    assert derived['value'] == taxonomy.UNKNOWN
    assert rules.review_reason(derived) == rules.FAMILY_NOT_IN_TAXONOMY


def test_deriving_the_minor_group_twice_says_the_same_thing():
    record = taxonomy.make_value_record('occupation_family', 'legal', 'llm')
    at = '2026-11-02T09:00:00+00:00'
    assert rules.derive_minor_group(record, at=at) == rules.derive_minor_group(record, at=at)


def test_the_rules_layer_does_not_write_the_minor_group_itself():
    """It is derived after every layer and not inside this one
    (`classify.settle_minor_group`), so the group follows the family that
    won the merge rather than the one a table proposed."""
    assert 'isco_minor_group' not in rules.occupation(subject(title='Senior Java-Entwickler/in'))
    assert 'isco_minor_group' not in rules.classify(subject(title='Senior Java-Entwickler/in'))


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
    different fact from no record at all.

    Every field except `isco_minor_group`, which this layer does not
    write at all: the 3-digit group is derived from the SETTLED family
    after every layer has spoken (`classify.settle_minor_group`,
    CAREER-130), and deriving it here too would pin the rules layer's
    family on a posting only the model can settle -- the bug CAREER-125
    found at four digits."""
    values = rules.classify(subject(title='x'))
    assert set(values) == set(rules.FIELDS) - {'isco_minor_group'}
    assert all(record['taxonomy_version'] and record['classified_at']
               for record in values.values())


def test_every_record_names_its_source_and_its_taxonomy_version():
    values = rules.classify(subject(title='Senior Product Owner 80%',
                                    employer_name='Beispiel AG'))
    for field, record in values.items():
        assert record['source'] == 'rule', field
        assert record['standard_version'], field
