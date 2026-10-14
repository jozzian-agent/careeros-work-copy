"""Pinned JSON page contracts against an isolated fixture vault."""

DIRECTORY_SHAPE = {'counts': {'CO-001': 'int'},
 'empty': 'str',
 'entries': [{'contact_email': 'str',
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
              'website': 'NoneType'}],
 'isic_sections': [{'code': 'str', 'keywords': ['str'], 'label': 'str', 'label_de': 'str'}],
 'sector_labels': {'CO-001': ['str']},
 'size_classes': ['str']}

def test_directory_contract(api_client, assert_json_shape):
    response = api_client.get('/api/companies?view=page')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), DIRECTORY_SHAPE)


DETAIL_SHAPE = {'classification': {'sector': {'source': 'NoneType', 'value': 'str'},
                    'size': {'source': 'NoneType', 'value': 'str'}},
 'companies': {'CO-001': {'contact_email': 'str',
                          'custom': {},
                          'enrichment': {'hiring_activity': {'count': 'int',
                                                             'most_recent_posted_date': 'NoneType'},
                                         'locations_seen': ['str'],
                                         'remote_friendly': 'bool',
                                         'sectors': [],
                                         'seniority_range': {'max': 'NoneType',
                                                             'min': 'NoneType'},
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
                          'website': 'NoneType'}},
 'company': {'contact_email': 'str',
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
 'entries': [{'added': 'str',
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
              'needs_attention': 'bool',
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
              'valid_through': 'str'}],
 'experiences': [{'id': 'str', 'status': 'str', 'title': 'str'}],
 'isic_sections': [{'code': 'str', 'keywords': ['str'], 'label': 'str', 'label_de': 'str'}],
 'jobs': [{'id': 'str', 'status': 'str', 'title': 'str'}],
 'kinds': ['str'],
 'needs_input': 'NoneType',
 # Same migrated-view shape, and the same null timestamps, as the
 # job detail contract's notes key.
 'notes': [{'body': 'str', 'created': 'NoneType', 'id': 'str',
           'title': 'str', 'updated': 'NoneType'}],
 'sector_labels': ['str'],
 'size_classes': ['str']}

def test_detail_contract(api_client, assert_json_shape):
    response = api_client.get('/api/companies/CO-001?view=page')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), DETAIL_SHAPE)


def test_linked_records_and_raw_contract(api_client, assert_json_shape):
    route = '/api/companies/CO-001'
    data = api_client.get(route + '?view=page').get_json()
    assert [job['id'] for job in data['entries']] == ['JOB-001']
    assert data['entries'][0]['needs_attention'] is True
    assert [exp['id'] for exp in data['experiences']] == ['EXP-001']
    assert data['company']['notes'] == 'Owner notes'
    assert data['company']['review_flags'] == ['sector-ambiguous']
    assert data['sector_labels'] == ['Information and communication']
    assert_json_shape(api_client.get(route).get_json(), DETAIL_SHAPE['company'])
    assert_json_shape(api_client.get('/api/companies').get_json(), [DETAIL_SHAPE['company']])
    assert api_client.get('/api/companies?view=page').get_json()['counts'] == {'CO-001': 1}
    assert api_client.put(route, json={'notes': 'Edited'}).get_json()['notes'] == 'Edited'
    assert api_client.delete(route).status_code == 409
    api_client.delete('/api/jobs/JOB-001')
    api_client.delete('/api/experiences/EXP-001')
    assert api_client.delete(route).get_json() == {'deleted': 'CO-001'}
    assert api_client.get('/api/companies?view=page').get_json()['entries'] == []
    assert api_client.get(route + '?view=page').status_code == 404
