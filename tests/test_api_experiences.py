"""Pinned JSON page contracts against an isolated fixture vault."""

LIBRARY_SHAPE = {'companies': {'CO-001': {'contact_email': 'str',
                          'custom': {},
                          'enrichment': {'employee_count': 'NoneType',
                                         'employee_count_evidence': 'NoneType',
                                         'hiring_activity': {'count': 'int',
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
                          'retired': 'bool',
                          'retired_at': 'NoneType',
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
              # M2 (CAREER-39): whose position it is. Null on this
              # fixture, whose records are written straight through the
              # vault; the API's own create path stamps one.
              'owner_id': 'NoneType',
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
                          'enrichment': {'employee_count': 'NoneType',
                                         'employee_count_evidence': 'NoneType',
                                         'hiring_activity': {'count': 'int',
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
                          'retired': 'bool',
                          'retired_at': 'NoneType',
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
         'owner_id': 'NoneType',
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
                'enrichment': {'employee_count': 'NoneType',
                               'employee_count_evidence': 'NoneType',
                               'hiring_activity': {'count': 'int',
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
                'retired': 'bool',
                'retired_at': 'NoneType',
                'review_flags': ['str'],
                'sector': 'NoneType',
                'sectors': ['str'],
                'size': 'NoneType',
                'size_class': 'str',
                'size_range': 'NoneType',
                'sources': [],
                'website': 'NoneType'}],
 'can_edit_shared': 'bool',
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


EDIT_SHAPE = {
 # M2 (D3): whether this reader may add a value to the shared tag
 # vocabulary, which is what gates the propose-a-new-tag control.
 'can_edit_shared': 'bool',
 'companies': [{'contact_email': 'str',
                'custom': {},
                'enrichment': {'employee_count': 'NoneType',
                               'employee_count_evidence': 'NoneType',
                               'hiring_activity': {'count': 'int',
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
                'retired': 'bool',
                'retired_at': 'NoneType',
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
         'owner_id': 'NoneType',
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


# The payload the React Add position page sends (2026-11-01). Pinned here
# because that page is the only writer of a new position and the endpoint
# it writes through is unchanged: the two things no artboard mentions and
# a create would silently drop -- the custom fields and a proposed tag --
# have to survive the one and only path that creates a position.
ADD_POSITION_PAYLOAD = {
    'title': 'Platform Lead',
    'company': 'Contract Studio',
    'company_id': None,
    'start': '2022-01',
    'end': 'present',
    'location': 'Zurich',
    'people_led': 6,
    'summary': 'Ran the platform team.',
    'highlights': ['Shipped the thing', 'Hired four people'],
    'detail': '**Bold** detail.',
    'tags': ['experience-type:employment', 'tool:terraform-cloud'],
    'proposed_tags': ['tool:terraform-cloud'],
    'custom': {'Clearance': 'None', 'Nested': {'a': [1, 2]}},
}


def test_add_position_payload_creates_a_position_with_everything_it_sent(api_client):
    from careeros import vault
    root = api_client.application.config['VAULT_PATH']
    response = api_client.post('/api/experiences', json=ADD_POSITION_PAYLOAD)
    assert response.status_code == 201
    created = response.get_json()
    stored = vault.load_experience(root, created['id'])
    for field in ('title', 'start', 'end', 'location', 'people_led', 'summary',
                  'highlights', 'detail', 'custom'):
        assert stored[field] == ADD_POSITION_PAYLOAD[field], field
    # The free-text company label is kept even with no record behind it:
    # the page creates the company through link-company afterwards.
    assert stored['company'] == 'Contract Studio' and stored['company_id'] is None
    assert stored['tags'] == ADD_POSITION_PAYLOAD['tags']
    # The proposed value joined the shared registry, which is what makes
    # the tag valid on the record at all.
    registry = vault.load_tags(root)
    assert any(value['id'] == 'terraform-cloud'
               for value in registry['facets']['tool']['values'])
    # Salary is never written by this page, and the record says so rather
    # than carrying whatever a client sent (the field is owner-only).
    assert stored['salary'] is None


def test_add_position_then_link_company_is_the_two_step_the_page_takes(api_client):
    from careeros import vault
    root = api_client.application.config['VAULT_PATH']
    created = api_client.post('/api/experiences',
                              json=dict(ADD_POSITION_PAYLOAD, company='Brand New Co')).get_json()
    linked = api_client.post(f"/api/experiences/{created['id']}/link-company",
                             json={'create': {'name': 'Brand New Co'}, 'confirm_create': True})
    assert linked.status_code == 201
    stored = vault.load_experience(root, created['id'])
    assert stored['company_id'] == linked.get_json()['company_id']
    assert vault.load_company(root, stored['company_id'])['name'] == 'Brand New Co'
