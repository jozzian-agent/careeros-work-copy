"""B2: a PUT stamps owner provenance only for keys the vault persists.

The job and company PUTs mark every field an owner edit sets as
`user`-provenance so later automation never overwrites it. A payload key
the vault whitelist drops sets nothing, so marking it would protect a
field that has no owner value behind it -- `fit` is the live example: the
frontend sends it, the vault has no such field, and before this fix the
record came back claiming the owner had set it.

F-NEW-1 pins the other half of the same rule, the one Edit job shapes its
payload around: a key the payload leaves out is a field the owner did not
edit, so its provenance and its status come out of the PUT exactly as
they went in.
"""
from careeros import server, vault


def _client(tmp_path):
    root = tmp_path / 'vault'
    app = server.create_app(root)
    return app.test_client(), root


def test_put_job_ignores_keys_the_vault_drops(tmp_path):
    client, root = _client(tmp_path)
    job = vault.save_job(root, {'title': 'Builder', 'url': 'https://example.com/jobs/1'})
    before = vault.load_job(root, job['id'])['field_provenance']

    response = client.put(f'/api/jobs/{job["id"]}', json={'fit': None, 'bogus_key': 1})

    assert response.status_code == 200
    assert response.get_json()['field_provenance'] == before
    assert vault.load_job(root, job['id'])['field_provenance'] == before
    assert 'fit' not in response.get_json()


def test_put_job_marks_keys_the_vault_keeps(tmp_path):
    client, root = _client(tmp_path)
    job = vault.save_job(root, {'title': 'Builder', 'url': 'https://example.com/jobs/1'})

    response = client.put(f'/api/jobs/{job["id"]}', json={'notes': 'x'})

    assert response.status_code == 200
    assert response.get_json()['field_provenance']['notes'] == 'user'
    assert vault.load_job(root, job['id'])['notes'] == 'x'


def test_put_job_mixed_payload_marks_only_the_accepted_key(tmp_path):
    client, root = _client(tmp_path)
    job = vault.save_job(root, {'title': 'Builder', 'url': 'https://example.com/jobs/1'})

    response = client.put(f'/api/jobs/{job["id"]}',
                          json={'notes': 'x', 'fit': None, 'bogus_key': 1})

    assert response.status_code == 200
    assert response.get_json()['field_provenance'] == {'notes': 'user'}


def _read_job(tmp_path):
    """A job as a first reading leaves it: a title a model read, and a
    location the posting did not support."""
    client, root = _client(tmp_path)
    job = vault.save_job(root, {
        'title': 'Builder', 'url': 'https://example.com/jobs/1',
        'summary': 'Read from the posting.',
        'field_provenance': {'title': 'llm', 'summary': 'llm'},
        'field_status': {'title': 'done', 'location': 'not_evidenced'},
    })
    return client, root, job


def test_put_job_leaves_a_key_the_payload_omits_alone(tmp_path):
    client, root, job = _read_job(tmp_path)

    response = client.put(f'/api/jobs/{job["id"]}', json={'summary': 'In my own words.'})

    assert response.status_code == 200
    stored = vault.load_job(root, job['id'])
    assert stored['summary'] == 'In my own words.'
    assert stored['field_provenance']['summary'] == 'user'
    # The title keeps the reader it had, and the location keeps saying the
    # posting did not yield it, so its row still offers a setter.
    assert stored['field_provenance'].get('title') == 'llm'
    assert stored['field_status']['location'] == 'not_evidenced'
    assert stored['location'] == ''


def test_put_job_marks_the_key_the_payload_carries(tmp_path):
    client, root, job = _read_job(tmp_path)

    response = client.put(f'/api/jobs/{job["id"]}', json={'title': 'Platform Builder'})

    assert response.status_code == 200
    stored = vault.load_job(root, job['id'])
    assert stored['title'] == 'Platform Builder'
    assert stored['field_provenance']['title'] == 'user'
    assert stored['field_status']['title'] == 'done'
    # And the save says nothing about the fields it did not carry.
    assert stored['field_provenance']['summary'] == 'llm'
    assert stored['field_status']['location'] == 'not_evidenced'


def test_put_company_ignores_keys_the_vault_drops(tmp_path):
    client, root = _client(tmp_path)
    company = vault.save_company(root, {'name': 'Studio'})
    before = vault.load_company(root, company['id'])['field_provenance']

    response = client.put(f'/api/companies/{company["id"]}',
                          json={'fit': None, 'bogus_key': 1})

    assert response.status_code == 200
    # name_source is set by the PUT itself, not by the owner payload, and
    # is not a content field the marking protects.
    assert response.get_json()['field_provenance'] == before


def test_put_company_marks_keys_the_vault_keeps(tmp_path):
    client, root = _client(tmp_path)
    company = vault.save_company(root, {'name': 'Studio'})

    response = client.put(f'/api/companies/{company["id"]}',
                          json={'notes': 'x', 'bogus_key': 1})

    assert response.status_code == 200
    assert response.get_json()['field_provenance'] == {'notes': 'user'}


def test_field_name_sets_come_from_the_save_whitelist(tmp_path):
    """The exposed sets are derived, not a second hand-kept copy: a field
    the vault stores must appear, and a field it drops must not."""
    assert {'notes', 'description', 'status', 'sector'} <= vault.job_field_names()
    assert 'fit' not in vault.job_field_names()
    assert {'notes', 'sector', 'size'} <= vault.company_field_names()
    assert 'fit' not in vault.company_field_names()
    # Job-only and company-only fields do not leak across kinds.
    assert 'ingest_state' not in vault.company_field_names()
    assert 'review_flags' not in vault.job_field_names()
