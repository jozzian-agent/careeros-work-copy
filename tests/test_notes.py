"""Notes as a list of titled notes: the migration, the CRUD, the roll-up."""
from pathlib import Path
import shutil

import pytest
import yaml

from careeros import vault
from careeros.server import create_app
from careeros.web.pages import notes as notes_page

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / 'sample/vault', tmp_path / 'vault')
    return tmp_path / 'vault'


@pytest.fixture
def client(root):
    return create_app(root).test_client()


def _stored(root, kind, identifier):
    """The record as it sits on disk, never through a loader, so a test can
    tell what was written from what was only surfaced on read."""
    for path in sorted((root / kind).glob('*.yaml')):
        data = yaml.safe_load(path.read_text())
        if data and data.get('id') == identifier:
            return path, data
    raise AssertionError(f'{identifier} not on disk')


# --- The read-time migration ---

def test_legacy_notes_string_surfaces_as_the_first_note_without_touching_the_file(root):
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://example.test/a', 'notes': 'Ask about on-call.'})
    path, before = _stored(root, 'jobs', job['id'])
    stamp = path.stat().st_mtime_ns

    view = vault.notes_view(vault.load_job(root, job['id']))
    assert [(n['title'], n['body']) for n in view] == [('Note', 'Ask about on-call.')]
    # No write-time to invent, so none is invented.
    assert view[0]['created'] is None and view[0]['updated'] is None

    _, after = _stored(root, 'jobs', job['id'])
    assert after == before
    assert path.stat().st_mtime_ns == stamp


def test_an_unrelated_save_keeps_the_legacy_string_and_does_not_migrate_it(root):
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://example.test/b', 'notes': 'Keep me.'})
    vault.save_job(root, {'status': 'applied'}, job['id'])
    _, stored = _stored(root, 'jobs', job['id'])
    assert stored['notes'] == 'Keep me.'
    assert stored['note_list'] == []
    assert vault.notes_view(stored)[0]['body'] == 'Keep me.'


def test_the_first_note_write_persists_the_migrated_note_and_clears_the_string(client, root):
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://example.test/c', 'notes': 'Legacy text.'})
    response = client.post(f'/api/jobs/{job["id"]}/notes',
                           json={'title': 'Second', 'body': 'New body.'})
    assert response.status_code == 201

    _, stored = _stored(root, 'jobs', job['id'])
    assert stored['notes'] == ''
    assert [(n['title'], n['body']) for n in stored['note_list']] == [
        ('Note', 'Legacy text.'), ('Second', 'New body.')]
    # The legacy note keeps its stable id, so a link to it still resolves.
    assert stored['note_list'][0]['id'] == 'legacy'


def test_an_empty_note_list_never_shadows_the_legacy_string(root):
    """A save of any kind writes note_list: [], since every save writes the
    full schema. An empty list must therefore mean "not migrated yet", not
    "this record has no notes"."""
    assert vault.notes_view({'notes': 'Still here.', 'note_list': []})[0]['body'] == 'Still here.'
    assert vault.notes_view({'notes': 'Hidden.', 'note_list': [
        {'id': 'a', 'title': 'T', 'body': 'B', 'created': None, 'updated': None}]}) == [
        {'id': 'a', 'title': 'T', 'body': 'B', 'created': None, 'updated': None}]


def test_a_company_migrates_the_same_way(client, root):
    company = vault.save_company(root, {'name': 'Fictional Co', 'notes': 'Legacy company text.'})
    client.post(f'/api/companies/{company["id"]}/notes', json={'title': 'Call notes', 'body': ''})
    _, stored = _stored(root, 'companies', company['id'])
    assert stored['notes'] == ''
    assert [n['title'] for n in stored['note_list']] == ['Note', 'Call notes']


# --- The note shape ---

def test_a_note_needs_a_title_and_ids_are_generated_here(root):
    with pytest.raises(ValueError, match='needs a title'):
        vault.new_note('  ', 'body')
    with pytest.raises(ValueError, match='must be text'):
        vault.new_note('Title', None)
    first, second = vault.new_note('A', ''), vault.new_note('A', '')
    assert first['id'] != second['id']
    assert first['created'] == first['updated']


def test_a_malformed_note_list_is_refused(root):
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://example.test/e'})
    for bad in ([{'id': 'a', 'title': 'T'}],
                [{'id': '', 'title': 'T', 'body': '', 'created': None, 'updated': None}],
                [{'id': 'a', 'title': ' ', 'body': '', 'created': None, 'updated': None}],
                [{'id': 'a', 'title': 'T', 'body': 1, 'created': None, 'updated': None}],
                'notalist'):
        with pytest.raises(ValueError):
            vault.save_job(root, {'note_list': bad}, job['id'])


def test_two_notes_cannot_share_an_id(root):
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://example.test/f'})
    twin = {'id': 'same', 'title': 'T', 'body': '', 'created': None, 'updated': None}
    with pytest.raises(ValueError, match='unique'):
        vault.save_job(root, {'note_list': [twin, dict(twin)]}, job['id'])


def test_the_first_note_is_history_once_whichever_shape_it_arrives_in(client, root):
    fresh = vault.save_job(root, {'title': 'Role', 'url': 'https://example.test/g'})
    client.post(f'/api/jobs/{fresh["id"]}/notes', json={'title': 'First', 'body': ''})
    events = [e['event'] for e in vault.load_job(root, fresh['id'])['history']]
    assert events.count('note_added') == 1

    legacy = vault.save_job(root, {'title': 'Other', 'url': 'https://example.test/h', 'notes': 'Already noted.'})
    assert [e['event'] for e in legacy['history']].count('note_added') == 1
    client.post(f'/api/jobs/{legacy["id"]}/notes', json={'title': 'Second', 'body': ''})
    later = [e['event'] for e in vault.load_job(root, legacy['id'])['history']]
    assert later.count('note_added') == 1


# --- The endpoints ---

@pytest.mark.parametrize('kind,fields', [
    ('jobs', {'title': 'Role', 'url': 'https://example.test/d'}),
    ('companies', {'name': 'Fictional Co'}),
])
def test_note_crud_round_trip(client, root, kind, fields):
    save = vault.save_job if kind == 'jobs' else vault.save_company
    record = save(root, fields)
    base = f'/api/{kind}/{record["id"]}/notes'

    created = client.post(base, json={'title': 'Interview prep', 'body': 'Ask about the rota.'})
    assert created.status_code == 201
    note = created.get_json()
    assert sorted(note) == sorted(vault.NOTE_FIELDS)

    reread = client.get(f'/api/{kind}/{record["id"]}?view=page').get_json()['notes']
    assert reread == [note]

    patched = client.patch(f'{base}/{note["id"]}', json={'body': 'Ask about the rota and on-call.'})
    assert patched.status_code == 200
    assert patched.get_json()['title'] == 'Interview prep'
    assert patched.get_json()['body'] == 'Ask about the rota and on-call.'
    assert patched.get_json()['created'] == note['created']
    assert patched.get_json()['updated'] >= note['updated']

    assert client.delete(f'{base}/{note["id"]}').get_json() == {'deleted': note['id']}
    assert client.get(f'/api/{kind}/{record["id"]}?view=page').get_json()['notes'] == []


def test_a_note_body_may_be_empty_but_a_title_may_not(client, root):
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://example.test/i'})
    base = f'/api/jobs/{job["id"]}/notes'
    assert client.post(base, json={'title': 'Headline only'}).status_code == 201
    assert client.post(base, json={'title': '   ', 'body': 'orphan'}).status_code == 400
    assert client.post(base, json={'body': 'no title'}).status_code == 400
    note = client.get(f'/api/jobs/{job["id"]}?view=page').get_json()['notes'][0]
    assert client.patch(f'{base}/{note["id"]}', json={'title': ''}).status_code == 400


def test_a_missing_record_or_note_is_a_404(client, root):
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://example.test/j'})
    assert client.post('/api/jobs/JOB-404/notes', json={'title': 'T'}).status_code == 404
    assert client.post('/api/companies/CO-404/notes', json={'title': 'T'}).status_code == 404
    assert client.patch(f'/api/jobs/{job["id"]}/notes/nope', json={'title': 'T'}).status_code == 404
    assert client.delete(f'/api/jobs/{job["id"]}/notes/nope').status_code == 404


def test_a_note_belongs_to_exactly_one_record(client, root):
    """Association is containment: the note lives in one record's file, so
    the same id on another record addresses nothing."""
    first = vault.save_job(root, {'title': 'First role', 'url': 'https://example.test/k'})
    second = vault.save_job(root, {'title': 'Second role', 'url': 'https://example.test/l'})
    note = client.post(f'/api/jobs/{first["id"]}/notes', json={'title': 'Mine'}).get_json()
    assert client.patch(f'/api/jobs/{second["id"]}/notes/{note["id"]}',
                        json={'title': 'Theirs'}).status_code == 404
    assert client.get(f'/api/jobs/{second["id"]}?view=page').get_json()['notes'] == []


# --- GET /api/notes ---

def test_notes_roll_up_names_each_record_and_puts_the_newest_first(client, root):
    company = vault.save_company(root, {'name': 'Fictional Co'})
    job = vault.save_job(root, {'title': 'Role', 'url': 'https://example.test/m', 'company_id': company['id']})
    client.post(f'/api/companies/{company["id"]}/notes', json={'title': 'Older', 'body': 'a'})
    client.post(f'/api/jobs/{job["id"]}/notes', json={'title': 'Newer', 'body': 'b'})

    data = client.get('/api/notes').get_json()
    rows = [row for row in data['notes'] if row['title'] in ('Older', 'Newer')]
    assert [row['title'] for row in rows] == ['Newer', 'Older']
    assert (rows[0]['job_id'], rows[0]['job_title']) == (job['id'], 'Role')
    assert (rows[0]['company_id'], rows[0]['company_name']) == (None, None)
    assert (rows[1]['company_id'], rows[1]['company_name']) == (company['id'], 'Fictional Co')
    assert (rows[1]['job_id'], rows[1]['job_title']) == (None, None)
    assert rows[0]['body_preview'] == 'b'
    assert data['empty'] == notes_page.EMPTY_STATE


def test_the_roll_up_is_empty_with_its_own_message_when_nothing_has_notes():
    assert notes_page.notes_context([], []) == {'notes': [], 'empty': notes_page.EMPTY_STATE}


def test_a_preview_is_one_shortened_line():
    assert notes_page.body_preview('') == ''
    assert notes_page.body_preview('\n\n  first  \nsecond') == 'first'
    long = 'word ' * 60
    preview = notes_page.body_preview(long)
    assert preview.endswith('…') and len(preview) <= notes_page.PREVIEW_LIMIT + 1


def test_a_migrated_note_sorts_last_and_still_names_its_record(client, root):
    job = vault.save_job(root, {'title': 'Legacy role', 'url': 'https://example.test/n', 'notes': 'Written long ago.'})
    other = vault.save_job(root, {'title': 'Fresh role', 'url': 'https://example.test/o'})
    client.post(f'/api/jobs/{other["id"]}/notes', json={'title': 'Today', 'body': ''})
    rows = client.get('/api/notes').get_json()['notes']
    migrated = next(row for row in rows if row['job_id'] == job['id'])
    assert migrated['title'] == 'Note'
    assert migrated['created'] is None
    assert rows.index(migrated) > rows.index(next(r for r in rows if r['title'] == 'Today'))
