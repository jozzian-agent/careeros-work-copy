"""Pinned JSON page contracts against an isolated fixture vault."""

JOB_SHAPE = {'company': {'contact_email': 'str',
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
 'function_options': [['str']],
 'isic_labels': {'A': 'str',
                 'B': 'str',
                 'C': 'str',
                 'D': 'str',
                 'E': 'str',
                 'F': 'str',
                 'G': 'str',
                 'H': 'str',
                 'I': 'str',
                 'J': 'str',
                 'K': 'str',
                 'L': 'str',
                 'M': 'str',
                 'N': 'str',
                 'O': 'str',
                 'P': 'str',
                 'Q': 'str',
                 'R': 'str',
                 'S': 'str',
                 'T': 'str',
                 'U': 'str'},
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
 'tag_labels': {'experience-type:employment': {'label': 'str', 'local': 'bool'},
                'experience-type:guest-lecture': {'label': 'str', 'local': 'bool'},
                'experience-type:volunteer': {'label': 'str', 'local': 'bool'},
                'function:builder': {'label': 'str', 'local': 'bool'}},
 'tag_registry': {'facets': {'experience-type': {'label': 'str',
                                                 'values': [{'id': 'str', 'label': 'str'}]},
                             'function': {'label': 'str',
                                          'values': [{'id': 'str',
                                                      'label': 'str',
                                                      'source': 'str'}]},
                             'skill/capability': {'label': 'str', 'values': []},
                             'skill/domain': {'label': 'str', 'values': []},
                             'tool': {'label': 'str', 'values': []}},
                  'updated': 'str'},
 'tags': ['str']}

def test_job_contract(api_client, assert_json_shape):
    response = api_client.get('/api/jobs/JOB-001/taxonomy')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), JOB_SHAPE)


COMPANY_SHAPE = {'company': {'contact_email': 'str',
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
 'isic_sections': [{'code': 'str', 'keywords': ['str'], 'label': 'str', 'label_de': 'str'}],
 'kinds': ['str'],
 'size_classes': ['str']}

def test_company_contract(api_client, assert_json_shape):
    response = api_client.get('/api/companies/CO-001/taxonomy')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), COMPANY_SHAPE)


def test_taxonomy_values(api_client):
    job = api_client.get('/api/jobs/JOB-001/taxonomy').get_json()
    assert job['function_options'] == [['builder', 'Builder']]
    assert job['function_labels'] == {'builder': {'label': 'Builder', 'local': True}}
    assert job['tags'] == ['function:builder']
    assert job['company']['sectors'] == ['J']
    assert job['isic_labels']['J'] == 'Information and communication'
    company = api_client.get('/api/companies/CO-001/taxonomy').get_json()
    assert company['kinds'] == ['employer', 'institution']
    assert company['size_classes'] == ['micro', 'small', 'medium', 'large']
    assert company['company']['review_flags'] == ['sector-ambiguous']


def test_missing_records_are_json(api_client):
    for path in ('/api/jobs/missing?view=page', '/api/companies/missing?view=page',
                 '/api/experiences/missing?view=page', '/api/jobs/missing/taxonomy',
                 '/api/companies/missing/taxonomy', '/api/experiences/missing/edit'):
        response = api_client.get(path)
        assert response.status_code == 404
        assert sorted(response.get_json()) == ['error']
        assert type(response.get_json()['error']) is str
