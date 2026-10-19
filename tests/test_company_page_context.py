"""The company detail page context: where each classification value came
from, which records are linked, and that no company surface asks for
"Needs your input" any more.

`company_context` is pure, so the cases below are record snapshots; the
absence pin also runs through the pinned API fixture.
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


# --- B5: nothing on a company surface asks for input ----------------------
#
# Owner decision 2026-10-19: the chip, the card and the directory filter
# are gone, and so is the `needs_input` ask that decided when to show
# them, with the nine tests that pinned its precedence and its "tried"
# list. A missing value is Unknown in the Classification section, beside
# Edit classification and the existing retry.

def test_the_page_makes_no_needs_input_ask_at_all():
    """An absence pin: the key is gone for every record shape that used
    to raise it -- an exhausted empty field, and a review flag against
    one."""
    exhausted = context(events('size', ('jsonld', 'empty')) | {'sectors': ['J']})
    flagged = context({'review_flags': ['sector-ambiguous', 'size-inconsistent']})
    for result in (exhausted, flagged):
        assert 'needs_input' not in result
    assert flagged['classification'] == {'sector': {'value': None, 'source': None},
                                         'size': {'value': None, 'source': None}}


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


def test_fixture_company_with_a_review_flag_asks_for_nothing(api_client):
    """The same absence pin over the real route, on the record shape that
    used to raise the ask: a company carrying a review flag."""
    page = api_client.get('/api/companies/CO-001?view=page').get_json()
    assert page['company']['review_flags'] == ['sector-ambiguous']
    assert 'needs_input' not in page
    assert page['classification']['sector']['value'] == 'Information and communication'
    assert page['jobs'] == [{'id': 'JOB-001', 'title': 'Contract Builder', 'status': 'new'}]
