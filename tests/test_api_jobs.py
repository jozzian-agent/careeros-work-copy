"""Pinned JSON page contracts against an isolated fixture vault."""

BOARD_SHAPE = {'companies': {'CO-001': {'industry': 'str', 'name': 'str', 'size_class': 'str'}},
 'empty': 'str',
 'entries': [{'added': 'str',
              'ats_posting_id': 'NoneType',
              'ats_provider': 'NoneType',
              'ats_tenant': 'NoneType',
              'background': 'str',
              'certifications': [],
              'closed': 'bool',
              'closed_at': 'NoneType',
              'closed_reviewed_at': 'NoneType',
              'company': 'str',
              'company_id': 'str',
              'company_industry': 'str',
              'company_link_reason': 'NoneType',
              'company_link_state': 'str',
              'company_name': 'str',
              'company_review': 'NoneType',
              'company_size_class': 'str',
              'contact_email': 'str',
              'custom': {},
              'description': 'str',
              'description_structured': 'NoneType',
              'employee_count': 'NoneType',
              'employer_named_in_posting': 'NoneType',
              'employment_type': 'str',
              'end_reason': 'NoneType',
              'enriched': 'bool',
              'field_provenance': {},
              'field_status': {},
              'field_status_reason': {},
              'function': ['str'],
              'history': [{'detail': 'str', 'event': 'str', 'ts': 'str'}],
              'id': 'str',
              'in_pipeline': 'bool',
              'industries': [],
              'industry': 'NoneType',
              'ingest_error': {'at': 'str', 'reason': 'str', 'stage': 'str'},
              'ingest_source': 'str',
              'ingest_state': 'str',
              'keywords': [],
              'location': 'str',
              'needs_attention': 'bool',
              'normalized_url': 'NoneType',
              'note_list': [],
              'notes': 'str',
              'occupation_code': 'NoneType',
              'origin': 'str',
              'original_url': 'NoneType',
              'pending': 'bool',
              'posted_date': 'NoneType',
              'posting_quality': 'NoneType',
              'refresh': 'str',
              'remote_ok': 'NoneType',
              'requirement_groups': [],
              'responsibilities': [],
              'salary_info': 'bool',
              'salary_note': 'str',
              'sector': 'NoneType',
              'sectors': [],
              'seniority': 'str',
              'skill_codes': 'NoneType',
              'skills': [],
              'source': 'str',
              'source_id': 'NoneType',
              'status': 'str',
              'summary': 'str',
              'summary_source': 'str',
              'tags': ['str'],
              'title': 'str',
              'url': 'str',
              'valid_through': 'str'}],
 'function_options': [['str']],
 # The one company-size scale, which the board's Company size facet reads
 # instead of bucketing employee counts of its own.
 'size_classes': ['str'],
 # D7's status vocabulary as the board reads it: the ordered list, the
 # words for each one, which of them end a job, and the open/ended split
 # the filter bar shows.
 'statuses': ['str'],
 'status_labels': {'new': 'str', 'interested': 'str', 'applied': 'str', 'interviewing': 'str',
                   'offer': 'str', 'won': 'str', 'rejected': 'str', 'stopped': 'str'},
 'ended_statuses': ['str'],
 'counts': {'open': 'int', 'ended': 'int'},
 # The ending-reason suggestions, and the title the free text beside them
 # is saved under as a note on the job.
 'end_reasons': {'stopped': ['str'], 'rejected': ['str']},
 'end_note_title': 'str',
 # Empty for this fixture, whose one job has no closed posting. A row is
 # {id, closed_at, days_closed}; tests/test_board_d7.py pins that.
 'closed_review': [],
 # top_stopped_reason is absent while no stopped job carries a reason,
 # which is this fixture.
 'search_so_far': {'applied_to': 'int', 'interviews': 'int', 'offers': 'int'}}

def test_board_contract(api_client, assert_json_shape):
    response = api_client.get('/api/jobs?view=board')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), BOARD_SHAPE)


DETAIL_SHAPE = {'company': {'contact_email': 'str',
             'custom': {},
             'enrichment': {'hiring_activity': {'count': 'int',
                                                'most_recent_posted_date': 'NoneType'},
                            'locations_seen': ['str'],
                            'remote_friendly': 'bool',
                            'sectors': [],
                            'seniority_range': {'max': 'NoneType', 'min': 'NoneType'},
                            'top_keywords': []},
             'field_provenance': {},
             'id': 'str',
             'identifiers': [],
             'kind': 'str',
             'locations': ['str'],
             'name': 'str',
             'name_source': 'str',
             'note_list': [],
             'notes': 'str',
             'review_flags': ['str'],
             'sector': 'NoneType',
             'sectors': ['str'],
             'size': 'NoneType',
             'size_class': 'str',
             'size_range': 'NoneType',
             'sources': [],
             'website': 'NoneType'},
 'classification': {'function': ['str'],
                    'sector': {'source': 'str', 'value': 'str'},
                    'tags': ['str']},
 'fit': 'NoneType',
 'fit_placeholder': 'str',
 'function_labels': {'builder': {'label': 'str', 'local': 'bool'}},
 'has_description': 'bool',
 'history': [{'detail': 'str', 'label': 'str', 'ts': 'str'}],
 'job': {'added': 'str',
         'ats_posting_id': 'NoneType',
         'ats_provider': 'NoneType',
         'ats_tenant': 'NoneType',
         'background': 'str',
         'certifications': [],
         'closed': 'bool',
         'closed_at': 'NoneType',
         'closed_reviewed_at': 'NoneType',
         'company': 'str',
         'company_id': 'str',
         'company_link_reason': 'NoneType',
         'company_link_state': 'str',
         'company_review': 'NoneType',
         'contact_email': 'str',
         'custom': {},
         'description': 'str',
         'description_structured': 'NoneType',
         'employee_count': 'NoneType',
         'employer_named_in_posting': 'NoneType',
         'employment_type': 'str',
         'end_reason': 'NoneType',
         'enriched': 'bool',
         'field_provenance': {},
         'field_status': {},
         'field_status_reason': {},
         'function': ['str'],
         'history': [{'detail': 'str', 'event': 'str', 'ts': 'str'}],
         'id': 'str',
         'in_pipeline': 'bool',
         'industries': [],
         'industry': 'NoneType',
         'ingest_error': {'at': 'str', 'reason': 'str', 'stage': 'str'},
         'ingest_source': 'str',
         'ingest_state': 'str',
         'keywords': [],
         'location': 'str',
         'normalized_url': 'NoneType',
         'note_list': [],
         'notes': 'str',
         'occupation_code': 'NoneType',
         'origin': 'str',
         'original_url': 'NoneType',
         'posted_date': 'NoneType',
         'posting_quality': 'NoneType',
         'refresh': 'str',
         'remote_ok': 'NoneType',
         'requirement_groups': [],
         'responsibilities': [],
         'salary_info': 'bool',
         'salary_note': 'str',
         'sector': 'NoneType',
         'sectors': [],
         'seniority': 'str',
         'skill_codes': 'NoneType',
         'skills': [],
         'source': 'str',
         'source_id': 'NoneType',
         'status': 'str',
         'summary': 'str',
         'summary_source': 'str',
         'tags': ['str'],
         'title': 'str',
         'url': 'str',
         'valid_through': 'str'},
 'llm_pending': 'bool',
 # The owner's notes as the migrated list. The fixture job still
 # holds them as the legacy free-text string, which carries no
 # write-time, so the one note it surfaces has null timestamps.
 'notes': [{'body': 'str', 'created': 'NoneType', 'id': 'str',
           'title': 'str', 'updated': 'NoneType'}],
 'needs_input': {'kind': 'str', 'review': 'NoneType'},
 'reading': 'bool',
 'show_remote_chip': 'bool',
 'statuses': ['str'],
 'status_labels': {'new': 'str', 'interested': 'str', 'applied': 'str', 'interviewing': 'str',
                    'offer': 'str', 'won': 'str', 'rejected': 'str', 'stopped': 'str'},
 'summary_effective': 'str',
 'watch_eligible': 'bool',
 'watch_reason': 'str'}

def test_detail_contract(api_client, assert_json_shape):
    response = api_client.get('/api/jobs/JOB-001?view=page')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), DETAIL_SHAPE)


def test_board_values_and_default_collection(api_client, assert_json_shape):
    board = api_client.get('/api/jobs?view=board').get_json()
    job = board['entries'][0]
    assert board['companies'] == {'CO-001': {'name': 'Contract Studio', 'industry': 'Information and communication',
                                              'size_class': 'small'}}
    assert board['function_options'] == [['builder', 'Builder']]
    assert job['company_name'] == 'Contract Studio'
    assert job['company_industry'] == 'Information and communication'
    assert job['company_size_class'] == 'small'
    assert job['needs_attention'] is True
    assert job['pending'] is True
    raw = api_client.get('/api/jobs').get_json()
    assert_json_shape(raw, [DETAIL_SHAPE['job']])
    assert raw[0] == {k: v for k, v in job.items()
                      if k not in ('company_name', 'company_industry', 'company_size_class',
                                   'needs_attention', 'pending')}


def test_detail_values_pending_and_mutations(api_client, assert_json_shape):
    route = '/api/jobs/JOB-001'
    api_client.application.config['LLM_PENDING']['JOB-001'] = 'token'
    data = api_client.get(route + '?view=page').get_json()
    assert data['llm_pending'] is True
    assert data['has_description'] is True
    assert data['job']['description'] == 'Original source text'
    assert data['job']['summary_source'] == 'ai'
    assert data['job']['ingest_error']['reason'] == 'empty_content'
    # The fixture job's link is needs_review with no review block stored,
    # which is the company ask all the same: the link state alone decides
    # it, ahead of the read failure its ingest_error would otherwise raise.
    assert data['needs_input'] == {'kind': 'company', 'review': None}
    assert data['notes'] == [{'id': 'legacy', 'title': 'Note', 'body': '**Owner notes**',
                              'created': None, 'updated': None}]
    assert_json_shape(api_client.get(route).get_json(), DETAIL_SHAPE['job'] | {'llm_pending': 'bool'})
    response = api_client.put(route, json={'summary': 'Owner summary', 'notes': 'Edited'})
    assert response.status_code == 200
    assert response.get_json()['summary_source'] == ''
    assert response.get_json()['notes'] == 'Edited'
    assert api_client.delete(route).get_json() == {'deleted': 'JOB-001'}
    assert api_client.get(route + '?view=page').status_code == 404


def test_board_empty_and_unlinked(api_client):
    from careeros import vault
    root = api_client.application.config['VAULT_PATH']
    vault.save_job(root, {'company_id': None, 'company_link_state': 'pending',
                          'enriched': True, 'ingest_state': 'complete', 'ingest_error': None}, 'JOB-001')
    data = api_client.get('/api/jobs?view=board').get_json()['entries'][0]
    assert data['company_name'] is None
    assert data['company_industry'] is None
    assert data['company_size_class'] is None
    assert data['pending'] is False
    assert data['needs_attention'] is False
    vault.delete_job(root, 'JOB-001')
    data = api_client.get('/api/jobs?view=board').get_json()
    assert data['entries'] == []
    assert data['empty'] == 'No jobs yet — paste a posting link to get started.'
