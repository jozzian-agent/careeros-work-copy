"""Pinned JSON page contracts against an isolated fixture vault."""

LIBRARY_SHAPE = {'companies': {'CO-001': {'contact_email': 'str',
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
 'empty': 'str',
 'entries': [{'company': 'str',
              'company_id': 'str',
              'custom': {},
              'detail': 'str',
              'end': 'str',
              'highlights': ['str'],
              'id': 'str',
              'location': 'str',
              'people_led': 'NoneType',
              'salary': 'NoneType',
              'skills': [],
              'start': 'str',
              'summary': 'str',
              'tags': ['str'],
              'title': 'str'}],
 'labels': {'EXP-001': 'str'},
 'tag_labels': {'experience-type:employment': {'label': 'str', 'local': 'bool'},
                'experience-type:guest-lecture': {'label': 'str', 'local': 'bool'},
                'experience-type:volunteer': {'label': 'str', 'local': 'bool'},
                'function:builder': {'label': 'str', 'local': 'bool'}}}

def test_library_contract(api_client, assert_json_shape):
    response = api_client.get('/api/experiences?view=page')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), LIBRARY_SHAPE)


DETAIL_SHAPE = {'companies': {'CO-001': {'contact_email': 'str',
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
 'exp': {'company': 'str',
         'company_id': 'str',
         'custom': {},
         'detail': 'str',
         'end': 'str',
         'highlights': ['str'],
         'id': 'str',
         'location': 'str',
         'people_led': 'NoneType',
         'salary': 'NoneType',
         'skills': [],
         'start': 'str',
         'summary': 'str',
         'tags': ['str'],
         'title': 'str'},
 'label': 'str',
 'markdown': 'str',
 'tag_labels': {'experience-type:employment': {'label': 'str', 'local': 'bool'},
                'experience-type:guest-lecture': {'label': 'str', 'local': 'bool'},
                'experience-type:volunteer': {'label': 'str', 'local': 'bool'},
                'function:builder': {'label': 'str', 'local': 'bool'}}}

def test_detail_contract(api_client, assert_json_shape):
    response = api_client.get('/api/experiences/EXP-001?view=page')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), DETAIL_SHAPE)


NEW_SHAPE = {'companies': [{'contact_email': 'str',
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
 'exp': {},
 'tags': {'facets': {'experience-type': {'label': 'str',
                                         'values': [{'id': 'str', 'label': 'str'}]},
                     'function': {'label': 'str',
                                  'values': [{'id': 'str', 'label': 'str', 'source': 'str'}]},
                     'skill/capability': {'label': 'str', 'values': []},
                     'skill/domain': {'label': 'str', 'values': []},
                     'tool': {'label': 'str', 'values': []}},
          'updated': 'str'}}

def test_new_contract(api_client, assert_json_shape):
    response = api_client.get('/api/experiences/new')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), NEW_SHAPE)


EDIT_SHAPE = {'companies': [{'contact_email': 'str',
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
 'exp': {'company': 'str',
         'company_id': 'str',
         'custom': {},
         'detail': 'str',
         'end': 'str',
         'highlights': ['str'],
         'id': 'str',
         'location': 'str',
         'people_led': 'NoneType',
         'salary': 'NoneType',
         'skills': [],
         'start': 'str',
         'summary': 'str',
         'tags': ['str'],
         'title': 'str'},
 'tags': {'facets': {'experience-type': {'label': 'str',
                                         'values': [{'id': 'str', 'label': 'str'}]},
                     'function': {'label': 'str',
                                  'values': [{'id': 'str', 'label': 'str', 'source': 'str'}]},
                     'skill/capability': {'label': 'str', 'values': []},
                     'skill/domain': {'label': 'str', 'values': []},
                     'tool': {'label': 'str', 'values': []}},
          'updated': 'str'}}

def test_edit_contract(api_client, assert_json_shape):
    response = api_client.get('/api/experiences/EXP-001/edit')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), EDIT_SHAPE)


def test_live_company_label_and_raw_contracts(api_client, assert_json_shape):
    from careeros import vault
    root = api_client.application.config['VAULT_PATH']
    vault.save_company(root, {'name': 'Renamed Studio'}, 'CO-001')
    route = '/api/experiences/EXP-001'
    detail = api_client.get(route + '?view=page').get_json()
    assert detail['label'] == 'Renamed Studio'
    assert detail['exp']['company'] == 'Frozen label'
    assert detail['exp']['company_id'] == 'CO-001'
    assert '<strong>Career story</strong>' in detail['markdown']
    assert api_client.get('/api/experiences?view=page').get_json()['labels'] == {'EXP-001': 'Renamed Studio'}
    assert api_client.get(route + '/edit').get_json()['companies'][0]['name'] == 'Renamed Studio'
    assert_json_shape(api_client.get(route).get_json(), DETAIL_SHAPE['exp'])
    assert_json_shape(api_client.get('/api/experiences').get_json(), [DETAIL_SHAPE['exp']])
    updated = api_client.put(route, json={'summary': 'Owner update'})
    assert updated.status_code == 200
    assert updated.get_json()['summary'] == 'Owner update'
    assert api_client.delete(route).get_json() == {'deleted': 'EXP-001'}
    assert api_client.get(route + '?view=page').status_code == 404
    assert api_client.get('/api/experiences?view=page').get_json()['entries'] == []
