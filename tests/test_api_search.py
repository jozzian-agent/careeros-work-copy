"""Pinned JSON page contracts against an isolated fixture vault."""
from careeros import vault


PAGE_SHAPE = {'data': {'avoid': ['str'],
          'must_haves': ['str'],
          'nice_to_haves': ['str'],
          'notes': 'str',
          'owner_id': 'str',
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
 'owner_id': 'str',
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
    # `owner_id` is the session's answer, not the payload's: the POST
    # above never sent one (per-user criteria, 2026-10-27).
    assert {k: v for k, v in response.get_json().items()
            if k not in ('updated', vault.OWNER_FIELD)} == data
    assert response.get_json()[vault.OWNER_FIELD] == 'USER-001'
    assert api_client.get('/api/search?view=page').get_json()['data'] == response.get_json()
    # The empty state. Criteria live one file per user now, so clearing
    # them means this reader's own file -- and the legacy shared file the
    # sample vault still carries, which `vault.load_search` would
    # otherwise copy into it on the next read.
    root = api_client.application.config['VAULT_PATH']
    for path in (root / vault.SEARCH_DIR).glob('*.yaml'):
        path.unlink()
    (root / vault.LEGACY_SEARCH_FILE).unlink()
    assert api_client.get('/api/search').get_json() is None
    page = api_client.get('/api/search?view=page').get_json()
    assert page['data'] is None
    assert page['sections'] == [['roles', 'Roles'], ['must_haves', 'Must-haves'],
                                ['nice_to_haves', 'Nice-to-haves'], ['avoid', 'Avoid']]
    assert type(page['empty']) is str
