"""B5: the company detail page context.

`company_context` is pure, so the cases below are record snapshots; the
acceptance case (a classified company carrying a stale review flag) also
runs through the pinned API fixture.
"""
from careeros.web.pages import companies

ISIC = [{'code': 'J', 'label': 'Information and communication'}]


def context(company=None, jobs=(), experiences=()):
    record = {'id': 'CO-001', 'name': 'Studio'}
    return companies.company_context(record | (company or {}), list(jobs),
                                     list(experiences), ISIC)


def events(field, *pairs):
    """One enrichment field_states block from (signal, outcome) pairs."""
    return {'enrichment': {'field_states': {field: {
        'state': 'exhausted',
        'events': [{'record_id': 'CO-001', 'signal': signal, 'field': field,
                    'outcome': outcome} for signal, outcome in pairs]}}}}


# --- needs_input ----------------------------------------------------------

def test_needs_input_null_when_the_field_has_a_value_despite_a_stale_flag():
    """Acceptance case: a company classified by an earlier run keeps a
    review flag from the ambiguity that preceded it. The flag alone used
    to raise the card, asking for a value already on the record."""
    result = context({'sectors': ['J'], 'size_class': 'small',
                      'review_flags': ['sector-ambiguous']})
    assert result['needs_input'] is None


def test_needs_input_null_when_the_field_was_never_tried():
    """Nothing to report yet: the cascade has not run, so the page does
    not ask the owner to do automation's job first."""
    result = context({'enrichment': {'field_states': {
        'sectors': {'state': 'never-tried', 'events': []}}}})
    assert result['needs_input'] is None


def test_needs_input_for_an_exhausted_empty_field():
    result = context(events('size', ('jsonld', 'empty'), ('osm', 'fetch-error'))
                     | {'sectors': ['J']})
    assert result['needs_input'] == {'field': 'size', 'tried': ['jsonld', 'osm']}


def test_needs_input_skips_signals_that_never_ran():
    result = context(events('size', ('jsonld', 'empty'), ('llm', 'not-attempted'))
                     | {'sectors': ['J']})
    assert result['needs_input']['tried'] == ['jsonld']


def test_needs_input_names_each_signal_once():
    result = context(events('size', ('wikidata', 'ambiguous'), ('wikidata', 'empty'))
                     | {'sectors': ['J']})
    assert result['needs_input']['tried'] == ['wikidata']


def test_needs_input_on_a_flag_only_when_the_field_is_empty():
    """A flag against an empty field is a real ask: a signal found
    something the record could not act on."""
    result = context({'review_flags': ['sector-ambiguous'], 'size_class': 'small'})
    assert result['needs_input'] == {'field': 'sector', 'tried': []}


def test_needs_input_asks_for_sector_before_size():
    result = context({'review_flags': ['sector-ambiguous', 'size-inconsistent']})
    assert result['needs_input']['field'] == 'sector'


def test_needs_input_counts_the_legacy_sector_text_as_a_value():
    result = context({'sector': 'Logistics software', 'size_class': 'small',
                      'review_flags': ['sector-ambiguous']})
    assert result['needs_input'] is None


def test_needs_input_counts_any_stored_size_as_a_value():
    for key, value in (('size', '200-500'), ('size_range', '200-500'), ('size_class', 'small')):
        result = context({'sectors': ['J'], key: value,
                          'review_flags': ['size-inconsistent']})
        assert result['needs_input'] is None, key


# --- classification -------------------------------------------------------

def test_classification_source_user_beats_an_enrichment_signal():
    company = (events('sectors', ('wikidata', 'matched'))
               | {'sectors': ['J'], 'field_provenance': {'sectors': 'user'}})
    assert context(company)['classification']['sector'] == {
        'value': 'Information and communication', 'source': 'user'}


def test_classification_source_is_the_last_filling_signal():
    company = events('sectors', ('jsonld', 'empty'), ('wikidata', 'matched'),
                     ('llm', 'not-attempted')) | {'sectors': ['J']}
    assert context(company)['classification']['sector']['source'] == 'wikidata'


def test_classification_source_null_when_nothing_on_the_record_says():
    company = {'sector': 'Logistics software'}
    assert context(company)['classification']['sector'] == {
        'value': 'Logistics software', 'source': None}


def test_classification_source_user_for_size_through_any_stored_key():
    company = {'size_class': 'small', 'field_provenance': {'size_class': 'user'}}
    assert context(company)['classification']['size'] == {'value': 'small', 'source': 'user'}


def test_classification_size_prefers_the_reported_range():
    company = {'size': '200-500', 'size_range': '250-500', 'size_class': 'medium'}
    assert context(company)['classification']['size']['value'] == '200-500'


def test_classification_is_empty_for_an_unclassified_company():
    result = context()['classification']
    assert result == {'sector': {'value': None, 'source': None},
                      'size': {'value': None, 'source': None}}


# --- linked records -------------------------------------------------------

def test_linked_jobs_and_experiences():
    jobs = [{'id': 'JOB-001', 'title': 'Builder', 'status': 'interested', 'company_id': 'CO-001'},
            {'id': 'JOB-002', 'title': 'Elsewhere', 'status': 'new', 'company_id': 'CO-002'}]
    experiences = [{'id': 'EXP-001', 'title': 'Earlier Builder', 'end': 'present',
                    'company_id': 'CO-001'},
                   {'id': 'EXP-002', 'title': 'Older', 'end': '2022-06', 'company_id': 'CO-001'},
                   {'id': 'EXP-003', 'title': 'Elsewhere', 'end': 'present', 'company_id': None}]

    result = context(jobs=jobs, experiences=experiences)

    assert result['jobs'] == [{'id': 'JOB-001', 'title': 'Builder', 'status': 'interested'}]
    assert result['experiences'] == [
        {'id': 'EXP-001', 'title': 'Earlier Builder', 'status': 'present'},
        {'id': 'EXP-002', 'title': 'Older', 'status': 'past'}]


def test_existing_keys_survive():
    """The board-shaped job records and header fields other surfaces read
    are still there."""
    jobs = [{'id': 'JOB-001', 'title': 'Builder', 'status': 'new', 'company_id': 'CO-001',
             'company_link_state': 'needs_review'}]
    result = context({'website': 'https://studio.example', 'locations': ['Zurich'],
                      'notes': 'Owner notes', 'sectors': ['J']}, jobs=jobs)
    assert result['entries'][0]['needs_attention'] is True
    assert result['sector_labels'] == ['Information and communication']
    assert result['company']['website'] == 'https://studio.example'
    assert result['company']['locations'] == ['Zurich']
    assert result['company']['notes'] == 'Owner notes'


def test_fixture_company_with_values_and_a_stale_flag_asks_for_nothing(api_client):
    """The same acceptance case over the real route."""
    page = api_client.get('/api/companies/CO-001?view=page').get_json()
    assert page['company']['review_flags'] == ['sector-ambiguous']
    assert page['needs_input'] is None
    assert page['classification']['sector']['value'] == 'Information and communication'
    assert page['jobs'] == [{'id': 'JOB-001', 'title': 'Contract Builder', 'status': 'new'}]
