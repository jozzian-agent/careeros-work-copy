"""Pinned JSON page contracts against an isolated fixture vault."""

PAGE_SHAPE = {'data': {'avoid': ['str'],
          'must_haves': ['str'],
          'nice_to_haves': ['str'],
          'notes': 'str',
          'roles': ['str'],
          'updated': 'str'},
 'empty': 'str',
 'sections': [['str']]}

def test_page_contract(api_client, assert_json_shape):
    response = api_client.get('/api/search?view=page')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), PAGE_SHAPE)


CRITERIA_SHAPE = {'avoid': ['str'],
 'must_haves': ['str'],
 'nice_to_haves': ['str'],
 'notes': 'str',
 'roles': ['str'],
 'updated': 'str'}

def test_criteria_contract(api_client, assert_json_shape):
    response = api_client.get('/api/search')
    assert response.status_code == 200
    assert response.is_json
    assert_json_shape(response.get_json(), CRITERIA_SHAPE)


def test_save_criteria_and_empty_page(api_client, assert_json_shape):
    data = {'roles': ['Builder'], 'must_haves': ['Flexible'],
            'nice_to_haves': [], 'avoid': [], 'notes': 'Owner criteria'}
    response = api_client.post('/api/search', json=data)
    assert response.status_code == 200
    assert_json_shape(response.get_json(), CRITERIA_SHAPE)
    assert {k: v for k, v in response.get_json().items() if k != 'updated'} == data
    assert api_client.get('/api/search?view=page').get_json()['data'] == response.get_json()
    (api_client.application.config['VAULT_PATH'] / 'search.yaml').unlink()
    assert api_client.get('/api/search').get_json() is None
    page = api_client.get('/api/search?view=page').get_json()
    assert page['data'] is None
    assert page['sections'] == [['roles', 'Roles'], ['must_haves', 'Must-haves'],
                                ['nice_to_haves', 'Nice-to-haves'], ['avoid', 'Avoid']]
    assert type(page['empty']) is str
