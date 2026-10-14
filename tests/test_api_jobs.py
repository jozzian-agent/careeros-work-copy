"""Pinned JSON page contracts against an isolated fixture vault."""

BOARD_SHAPE = {'companies': {'CO-001': {'industry': 'str', 'name': 'str', 'size_class': 'str'}},
 'empty': 'str',
 'entries': [{'added': 'str',
              'ats_posting_id': 'NoneType',
              'ats_provider': 'NoneType',
              'ats_tenant': 'NoneType',
              'background': 'str',
              'certifications': [],
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
              'enriched': 'bool',
              'field_provenance': {},
              'field_status': {},
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
              'notes': 'str',
              'occupation_code': 'NoneType',
              'origin': 'str',
              'original_url': 'NoneType',
              'pending': 'bool',
              'posted_date': 'NoneType',
              'posting_quality': 'NoneType',
              'refresh': 'str',
              'remote_ok': 'NoneType',
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
 'statuses': ['str']}

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
             'notes': 'str',
             'review_flags': ['str'],
             'sector': 'NoneType',
             'sectors': ['str'],
             'size': 'NoneType',
             'size_class': 'str',
             'size_range': 'NoneType',
             'sources': [],
             'website': 'NoneType'},
 'function_labels': {'builder': {'label': 'str', 'local': 'bool'}},
 'has_description': 'bool',
 'history': [{'detail': 'str', 'label': 'str', 'ts': 'str'}],
 'job': {'added': 'str',
         'ats_posting_id': 'NoneType',
         'ats_provider': 'NoneType',
         'ats_tenant': 'NoneType',
         'background': 'str',
         'certifications': [],
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
         'enriched': 'bool',
         'field_provenance': {},
         'field_status': {},
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
         'notes': 'str',
         'occupation_code': 'NoneType',
         'origin': 'str',
         'original_url': 'NoneType',
         'posted_date': 'NoneType',
         'posting_quality': 'NoneType',
         'refresh': 'str',
         'remote_ok': 'NoneType',
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
 'markdown': 'str',
 'show_remote_chip': 'bool',
 'statuses': ['str'],
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
    assert '<strong>Owner notes</strong>' in data['markdown']
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
