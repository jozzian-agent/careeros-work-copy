"""The pipeline's own rules (CAREER-57): that precedence decides who wins
a field, that a human's value is never displaced by a machine's, that
`unknown` is stored as a real value, and that a stored job and a feed
posting both become the same kind of subject."""
import pytest

from careeros import classify, taxonomy, vault
from careeros.classify import rules


def record(dimension, value, source, **fields):
    return taxonomy.make_value_record(dimension, value, source, **fields)


# --- precedence -----------------------------------------------------------

@pytest.mark.parametrize('weaker,stronger', [
    ('user', 'admin'), ('feed', 'user'), ('rule', 'feed'), ('llm', 'rule'),
])
def test_a_stronger_source_replaces_a_weaker_one(weaker, stronger):
    kept = classify.merge({'contract': record('contract', 'permanent', weaker)},
                          {'contract': record('contract', 'internship', stronger)})
    assert kept['contract']['value'] == 'internship'


@pytest.mark.parametrize('weaker,stronger', [
    ('user', 'admin'), ('feed', 'user'), ('rule', 'feed'), ('llm', 'rule'),
])
def test_a_weaker_source_never_overwrites_a_real_value(weaker, stronger):
    """The data-side half of "human edits always win"."""
    kept = classify.merge({'contract': record('contract', 'permanent', stronger)},
                          {'contract': record('contract', 'internship', weaker)})
    assert kept['contract']['value'] == 'permanent'
    assert kept['contract']['source'] == stronger


def test_the_same_source_leaves_the_stored_value_alone():
    """Which is what makes re-running a layer idempotent."""
    kept = classify.merge({'contract': record('contract', 'permanent', 'rule')},
                          {'contract': record('contract', 'internship', 'rule')})
    assert kept['contract']['value'] == 'permanent'


def test_a_weaker_source_may_fill_a_stronger_sources_unknown():
    """An ATS that carries no contract field stores `unknown` with the
    reason "the feed states no contract". That says the feed was asked
    and had nothing, not that the question is closed."""
    kept = classify.merge({'contract': record('contract', taxonomy.UNKNOWN, 'feed')},
                          {'contract': record('contract', 'internship', 'rule')})
    assert kept['contract']['value'] == 'internship'
    assert kept['contract']['source'] == 'rule'
    assert kept['contract']['evidence']['filled_unknown_from'] == 'feed'


def test_an_unknown_never_displaces_a_value():
    kept = classify.merge({'contract': record('contract', 'permanent', 'feed')},
                          {'contract': record('contract', taxonomy.UNKNOWN, 'rule')})
    assert kept['contract']['value'] == 'permanent'


def test_an_admin_value_survives_every_layer():
    stored = {'seniority': record('seniority', 's5', 'admin')}
    merged = classify.merge(stored, rules.classify(
        classify.subject(title='Junior Software Engineer')))
    assert merged['seniority']['value'] == 's5'
    assert merged['seniority']['source'] == 'admin'


# --- subjects -------------------------------------------------------------

def test_a_feed_posting_keeps_the_value_records_its_adapter_made():
    """The brief's own rule: feed-coded values are consumed, not
    re-derived."""
    stated = record('contract', 'internship', 'feed', evidence={'employmentType': 'INTERN'})
    subject = classify.from_feed_posting(
        {'key': 'k', 'title': 'Praktikum', 'tenant': 'Acme', 'description': 'text',
         'offices': ['8001 Zürich'], 'values': {'contract': stated}})
    result = classify.classify(subject)
    assert result['values']['contract'] == stated


def test_a_feed_unknown_is_filled_by_the_rules_layer():
    subject = classify.from_feed_posting({
        'key': 'k', 'title': 'Praktikum Marketing 100%', 'tenant': 'Acme',
        'description': 'Wir bieten ein spannendes Praktikum.', 'offices': ['8001 Zürich'],
        'values': {'contract': record('contract', taxonomy.UNKNOWN, 'feed')}})
    result = classify.classify(subject)
    assert result['values']['contract']['value'] == 'internship'


def test_an_owner_written_free_text_field_becomes_a_user_sourced_record():
    job = {'id': 'JOB-001', 'title': 'Junior Developer', 'seniority': 'director',
           'field_provenance': {'seniority': 'user'}}
    subject = classify.from_vault_job(job)
    assert subject['values']['seniority']['source'] == 'user'
    assert subject['values']['seniority']['value'] == 's5'
    result = classify.classify(subject)
    assert result['values']['seniority']['value'] == 's5'


def test_a_machine_written_free_text_field_is_not_carried_across():
    """Pinning an old model's answer in place as though a person had
    made it is what the precedence order exists to prevent."""
    job = {'id': 'JOB-001', 'title': 'Junior Developer', 'seniority': 'director',
           'field_provenance': {'seniority': 'llm'}}
    subject = classify.from_vault_job(job)
    assert 'seniority' not in subject['values']
    assert classify.classify(subject)['values']['seniority']['value'] == 's1'


def test_the_stored_function_facet_is_not_read_back_as_a_rule():
    """`function` is a previous LLM classification. Feeding it in would
    launder an `llm` value into a `rule` one."""
    job = {'id': 'JOB-001', 'title': 'Spannende Stelle', 'function': ['ict-product-manager']}
    subject = classify.from_vault_job(job)
    assert subject['department'] == ''
    assert classify.classify(subject)['values']['occupation_family']['value'] \
        == taxonomy.UNKNOWN


# --- what a run carries ---------------------------------------------------

def test_unknown_is_stored_as_a_value_and_not_as_a_gap():
    result = classify.classify(classify.subject(title='Careers and jobs'))
    assert set(result['values']) == set(rules.FIELDS)
    assert result['values']['contract']['value'] == taxonomy.UNKNOWN


def test_the_review_queue_is_read_off_the_records_themselves():
    result = classify.classify(classify.subject(title='Head of Product'))
    assert result['review']['occupation_family'] == 'ambiguous'
    assert result['values']['occupation_family']['evidence']['needs_review'] == 'ambiguous'


def test_only_the_unsettled_fields_are_open_to_a_later_layer():
    """`llm` is last in the precedence order, so asking it about a field
    a table settled would spend tokens on a value that cannot win."""
    values = rules.classify(classify.subject(title='Senior Java-Entwickler 80%'))
    assert 'occupation_family' not in classify.open_fields(values)
    assert 'contract' in classify.open_fields(values)


def test_asking_for_the_llm_layer_without_a_client_is_refused():
    with pytest.raises(ValueError, match='needs a client'):
        classify.classify(classify.subject(title='x'), layer='all')


def test_an_unknown_layer_name_is_refused():
    with pytest.raises(ValueError, match='unknown layer'):
        classify.classify(classify.subject(title='x'), layer='magic')


def test_coverage_counts_settled_unknown_and_review_per_field():
    results = [classify.classify(classify.subject(title='Senior Java-Entwickler/in')),
               classify.classify(classify.subject(title='Head of Product'))]
    table = classify.coverage(results)
    assert table['occupation_family'] == {'settled': 1, 'unknown': 1, 'needs_review': 1,
                                          'by_source': {'rule': 1}}


# --- the vault holds the shape -------------------------------------------

def test_a_job_stores_its_value_records_and_reads_them_back(tmp_path):
    (tmp_path / 'jobs').mkdir()
    job = vault.save_job(tmp_path, {'title': 'Senior Product Owner 80%',
                                    'url': 'https://example.test/a'})
    result = classify.classify(classify.from_vault_job(job))
    saved = vault.save_job(tmp_path, {'values': result['values'], 'salary': result['salary']},
                           job['id'])
    assert saved['values']['seniority']['value'] == 's3'
    assert vault.load_job(tmp_path, job['id'])['values'] == saved['values']


def test_a_value_record_the_factory_did_not_build_is_refused(tmp_path):
    (tmp_path / 'jobs').mkdir()
    job = vault.save_job(tmp_path, {'title': 'A job', 'url': 'https://example.test/a'})
    with pytest.raises(ValueError, match='make_value_record'):
        vault.save_job(tmp_path, {'values': {'contract': {'value': 'permanent'}}}, job['id'])


def test_field_provenance_keeps_its_shape(tmp_path):
    """The coded values live in `values`; `field_provenance` is still a
    mapping of field name to one word about the free-text half."""
    (tmp_path / 'jobs').mkdir()
    job = vault.save_job(tmp_path, {'title': 'A job', 'url': 'https://example.test/a',
                                    'field_provenance': {'seniority': 'user'}})
    assert job['field_provenance'] == {'seniority': 'user'}
    with pytest.raises(ValueError, match='field_provenance'):
        vault.save_job(tmp_path, {'field_provenance': {'seniority': {'source': 'user'}}},
                       job['id'])
