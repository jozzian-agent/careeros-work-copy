"""Protects the login gate: no page, endpoint or record is reachable
without a session, and no password or hash leaves the users area."""

import logging
from pathlib import Path

import pytest
import yaml

from careeros import i18n, server, users

PASSWORD = 'correct horse battery staple'
OTHER_PASSWORD = 'a second phrase entirely'
JOB_TITLE = 'Confidential Platform Lead'
COMPANY_NAME = 'Quiet Holdings'

# Every API surface the app answers on, read-only, so one list covers the
# "any endpoint" half of the gate rather than one test per endpoint.
API_PATHS = (
    '/api/jobs',
    '/api/jobs?view=board',
    '/api/companies',
    '/api/companies?view=page',
    '/api/experiences',
    '/api/experiences?view=page',
    '/api/search',
    '/api/search?view=page',
    '/api/notes',
    '/api/taxonomy',
    '/api/me',
)

# The pages that exist with the React build absent, plus a path that does
# not exist at all: a stranger must not be able to tell those apart.
PAGE_PATHS = ('/jobs', '/experiences/new', '/missing')


@pytest.fixture
def vault_root(tmp_path):
    """A vault holding one job, one company and one experience, so a leak
    has something to leak."""
    from careeros import vault

    root = tmp_path / 'vault'
    root.mkdir()
    vault.save_job(root, {'title': JOB_TITLE, 'location': 'Zurich',
                          'url': 'https://example.test/jobs/1'})
    vault.save_company(root, {'name': COMPANY_NAME})
    vault.save_experience(root, {'title': 'Earlier Lead', 'company': COMPANY_NAME,
                                 'start': '2020-01', 'end': 'present'})
    return root


@pytest.fixture
def admin(vault_root):
    return users.create_user(vault_root, email='Owner@Example.Test', name='Owner',
                             role='admin', password=PASSWORD)


@pytest.fixture
def app(vault_root, raw_session):
    """An app whose gate is the real one, over the vault above."""
    built = server.create_app(vault_root)
    built.config['TESTING'] = True
    return built


@pytest.fixture
def raw_client(app):
    """A client with no session, for the tests about the closed door."""
    return app.test_client()


def log_in(client, email=None, password=PASSWORD):
    return client.post('/login', json={'email': email or 'owner@example.test',
                                       'password': password})


# --- T1 ------------------------------------------------------------------

@pytest.mark.parametrize('path', API_PATHS)
def test_api_without_a_session_is_401_and_carries_no_record(raw_client, admin, path):
    response = raw_client.get(path)
    assert response.status_code == 401
    assert response.get_json() == {'error': 'login required'}
    body = response.get_data(as_text=True)
    assert JOB_TITLE not in body and COMPANY_NAME not in body


def test_api_write_without_a_session_is_401_and_writes_nothing(raw_client, admin, vault_root):
    from careeros import vault

    job = vault.list_jobs(vault_root)[0]
    response = raw_client.put(f'/api/jobs/{job["id"]}', json={'title': 'Renamed by a stranger'})
    assert response.status_code == 401
    assert response.get_json() == {'error': 'login required'}
    assert vault.load_job(vault_root, job['id'])['title'] == JOB_TITLE


@pytest.mark.parametrize('path', PAGE_PATHS)
def test_page_without_a_session_redirects_to_login(raw_client, admin, path):
    response = raw_client.get(path)
    assert response.status_code == 302
    assert response.headers['Location'] == '/login'
    assert JOB_TITLE not in response.get_data(as_text=True)


def test_the_login_page_itself_is_reachable(raw_client, admin):
    response = raw_client.get('/login')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "name='email'" in html and "name='password'" in html
    # Nothing about the vault, and no offer to end a session nobody has.
    assert JOB_TITLE not in html and 'Log out' not in html
    # No navigation either: every link it could show leads back here until
    # there is a session, so the fallback carries no more chrome than the
    # React rendering of the same page does.
    # ('page-nav' alone would match the shared stylesheet, which every
    # page carries whether or not it renders a nav.)
    assert '<nav' not in html and "class='page-nav'" not in html


def test_a_signed_in_page_offers_to_log_out(app, admin):
    client = app.test_client()
    log_in(client)
    assert 'Log out' in client.get('/jobs').get_data(as_text=True)


# --- T2 ------------------------------------------------------------------

def test_a_wrong_password_signs_nobody_in(raw_client, admin):
    response = log_in(raw_client, password='not the password')
    assert response.status_code == 401
    assert response.get_json() == {'error': 'Wrong email or password.'}
    assert raw_client.get('/api/jobs').status_code == 401


def test_an_unknown_email_is_answered_exactly_like_a_wrong_password(raw_client, admin):
    unknown = log_in(raw_client, email='stranger@example.test')
    wrong = log_in(raw_client, password='not the password')
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.get_json() == wrong.get_json()


def test_a_disabled_user_cannot_sign_in_and_is_told_nothing_extra(raw_client, admin, vault_root):
    users.set_disabled(vault_root, admin['id'], True)
    response = log_in(raw_client)
    assert response.status_code == 401
    assert response.get_json() == {'error': 'Wrong email or password.'}


def test_every_attempt_runs_the_hash_check_so_the_clock_says_nothing(
        vault_root, admin, monkeypatch):
    """Hashing is the slow part of a sign-in. An unknown email and a
    disabled account skipping it would answer measurably faster than a
    wrong password, which is the one message leaking through the clock."""
    checked = []
    real = users.check_password_hash
    monkeypatch.setattr(users, 'check_password_hash',
                        lambda stored, given: checked.append(stored) or real(stored, given))
    assert users.authenticate(vault_root, 'owner@example.test', PASSWORD)['id'] == admin['id']
    assert users.authenticate(vault_root, 'stranger@example.test', PASSWORD) is None
    users.set_disabled(vault_root, admin['id'], True)
    assert users.authenticate(vault_root, 'owner@example.test', PASSWORD) is None
    # One check per attempt, and the two with no account to check against
    # used the throwaway hash rather than returning early.
    assert checked == [admin['password_hash'], users._ABSENT_HASH, users._ABSENT_HASH]


# --- T3 ------------------------------------------------------------------

def test_the_right_credentials_open_the_gate(app, admin):
    client = app.test_client()
    response = log_in(client)
    assert response.status_code == 200
    assert response.get_json() == {'ok': True, 'next': '/jobs'}
    # A later request on the same cookie passes the gate.
    assert client.get('/api/jobs').status_code == 200
    assert client.get('/jobs').status_code == 200


def test_the_cookie_carries_an_id_and_nothing_a_client_could_forge(app, admin):
    client = app.test_client()
    log_in(client)
    cookie = client.get_cookie('session')
    assert cookie is not None
    assert PASSWORD not in cookie.value
    assert admin['password_hash'] not in cookie.value
    # The role is read off the record on every request, so the cookie does
    # not carry it and a client rewriting the cookie cannot become admin.
    assert 'admin' not in cookie.value and 'tester' not in cookie.value
    with client.session_transaction() as stored:
        # The session epoch joined the id when the password reset arrived:
        # the cookie carries the generation of sessions it belongs to, and a
        # reset of the record's epoch ends it (users.bump_session_epoch).
        assert dict(stored) == {'user_id': admin['id'], 'session_epoch': 0,
                                '_permanent': True}


@pytest.mark.parametrize('setting, secure', [('1', True), (None, False)])
def test_whether_the_cookie_is_flagged_secure_is_the_environment_s_call(
        vault_root, admin, raw_session, monkeypatch, setting, secure):
    """CAREEROS_SESSION_COOKIE_SECURE, read in create_app. Both halves
    matter. Unset has to stay the behaviour it has always been, because a
    local run reaches the app over plain HTTP and a browser will not send
    a Secure cookie back over that -- a default that flipped would sign
    every local session straight back out. (The post-deploy smoke test is
    not affected: curl replays a Secure cookie over the loopback, which
    deploy/RUNBOOK.md, "Known gaps", 3, records as checked.) Set to 1,
    the flag has to reach the real Set-Cookie header and not only the
    config, because the header is the only part a browser reads."""
    if setting is None:
        monkeypatch.delenv('CAREEROS_SESSION_COOKIE_SECURE', raising=False)
    else:
        monkeypatch.setenv('CAREEROS_SESSION_COOKIE_SECURE', setting)
    built = server.create_app(vault_root)
    built.config['TESTING'] = True
    assert built.config['SESSION_COOKIE_SECURE'] is secure
    response = log_in(built.test_client())
    assert response.status_code == 200
    stored = [header for header in response.headers.get_all('Set-Cookie')
              if header.startswith('session=')]
    assert len(stored) == 1, stored
    assert ('; Secure' in stored[0]) is secure, stored[0]
    # The two flags that do not depend on the environment, so this reads
    # the whole header rather than one attribute of it.
    assert '; HttpOnly' in stored[0] and '; SameSite=Lax' in stored[0]


def test_the_email_is_matched_case_insensitively(app, admin):
    client = app.test_client()
    assert log_in(client, email='OWNER@EXAMPLE.TEST').status_code == 200
    assert client.get('/api/jobs').status_code == 200


# --- T4 ------------------------------------------------------------------

def test_a_session_survives_a_server_restart(app, admin, vault_root):
    client = app.test_client()
    log_in(client)
    carried = client.get_cookie('session').value

    # The same vault, a brand new app object: what a restarted server is.
    restarted = server.create_app(vault_root)
    restarted.config['TESTING'] = True
    after = restarted.test_client()
    after.set_cookie('session', carried)
    assert after.get('/api/jobs').status_code == 200


def test_the_signing_key_is_kept_in_the_vault_and_is_owner_only(app, vault_root):
    path = vault_root / 'secret_key'
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    key = path.read_bytes()
    # A second boot adopts the stored key rather than minting a new one,
    # which is the whole reason a session outlives the process.
    server.create_app(vault_root)
    assert path.read_bytes() == key


def test_an_unusable_signing_key_is_replaced_and_the_login_still_works(
        vault_root, admin, raw_session, capsys):
    """A truncated or emptied key file used to be a permanent 500: the
    server adopted it, and every request failed on the session it signs."""
    path = vault_root / 'secret_key'
    path.write_bytes(b'')
    built = server.create_app(vault_root)
    built.config['TESTING'] = True
    assert len(path.read_bytes().strip()) >= users.SECRET_KEY_MIN_BYTES
    assert path.stat().st_mode & 0o777 == 0o600
    # Not a quiet repair: the old key is gone, so it is said out loud.
    assert 'not a usable signing key' in capsys.readouterr().err
    client = built.test_client()
    assert log_in(client).status_code == 200
    assert client.get('/api/jobs').status_code == 200


def test_a_vault_that_does_not_exist_yet_ends_in_a_working_login(tmp_path, raw_session):
    """The first start on a fresh vault writes the key it needs, so the
    first admin can be created and can then sign in."""
    root = tmp_path / 'brand-new'
    built = server.create_app(root)
    built.config['TESTING'] = True
    assert (root / 'secret_key').is_file()
    users.create_user(root, email='fresh@example.test', name='Fresh',
                      role='admin', password=PASSWORD)
    client = built.test_client()
    assert log_in(client, email='fresh@example.test').status_code == 200
    assert client.get('/api/jobs').status_code == 200


# --- T5 ------------------------------------------------------------------

def test_disabling_a_user_ends_their_live_session(app, admin, vault_root):
    client = app.test_client()
    log_in(client)
    assert client.get('/api/jobs').status_code == 200
    users.set_disabled(vault_root, admin['id'], True)
    assert client.get('/api/jobs').status_code == 401
    assert client.get('/jobs').status_code == 302


def test_deleting_the_record_behind_a_cookie_ends_the_session(app, admin, vault_root):
    client = app.test_client()
    log_in(client)
    next(path for path, _ in users._entries(vault_root)).unlink()
    assert client.get('/api/jobs').status_code == 401


# --- T6 ------------------------------------------------------------------

def test_health_answers_without_a_session_and_says_nothing_else(raw_client, admin):
    response = raw_client.get('/api/health')
    assert response.status_code == 200
    assert response.get_json() == {'ok': True}
    body = response.get_data(as_text=True)
    assert JOB_TITLE not in body and COMPANY_NAME not in body
    assert admin['email'] not in body


# --- the logout affordance ----------------------------------------------

def test_logging_out_closes_the_gate_again(app, admin):
    client = app.test_client()
    log_in(client)
    assert client.post('/logout', json={}).get_json() == {'ok': True}
    assert client.get('/api/jobs').status_code == 401


def test_a_form_logout_lands_on_the_login_page(app, admin):
    client = app.test_client()
    log_in(client)
    response = client.post('/logout')
    assert response.status_code == 302
    assert response.headers['Location'] == '/login'


def test_a_form_login_lands_on_the_board(app, admin):
    client = app.test_client()
    response = client.post('/login', data={'email': 'owner@example.test',
                                           'password': PASSWORD})
    assert response.status_code == 302
    assert response.headers['Location'] == '/jobs'
    assert client.get('/api/jobs').status_code == 200


def test_a_failed_form_login_shows_the_one_message(raw_client, admin):
    response = raw_client.post('/login', data={'email': 'owner@example.test',
                                               'password': 'wrong'})
    assert response.status_code == 401
    html = response.get_data(as_text=True)
    assert 'Wrong email or password.' in html
    assert PASSWORD not in html and admin['password_hash'] not in html


def test_the_login_page_sends_a_signed_in_person_to_the_board(app, admin):
    client = app.test_client()
    log_in(client)
    response = client.get('/login')
    assert response.status_code == 302
    assert response.headers['Location'] == '/jobs'


# --- T7, the accounts command line ---------------------------------------

def test_the_command_line_creates_an_admin(vault_root, capsys):
    users.main(['--vault', str(vault_root), 'create', '--email', 'Admin@Example.Test',
                '--name', 'First Admin', '--role', 'admin', '--password', PASSWORD])
    printed = capsys.readouterr()
    assert 'Created USER-001 admin admin@example.test (First Admin).' in printed.out
    stored = users.find_by_email(vault_root, 'admin@example.test')
    assert stored['role'] == 'admin' and stored['disabled'] is False
    assert PASSWORD not in yaml.safe_dump(stored)
    assert users.authenticate(vault_root, 'admin@example.test', PASSWORD)['id'] == stored['id']


def test_the_command_line_refuses_a_duplicate_email(vault_root, admin, capsys):
    with pytest.raises(SystemExit) as refused:
        users.main(['--vault', str(vault_root), 'create', '--email', 'OWNER@example.test',
                    '--name', 'Impostor', '--role', 'tester', '--password', OTHER_PASSWORD])
    assert 'already exists' in str(refused.value)
    assert len(users.list_users(vault_root)) == 1


def test_the_command_line_resets_a_password(vault_root, admin, capsys):
    users.main(['--vault', str(vault_root), 'reset-password',
                '--email', 'owner@example.test', '--password', OTHER_PASSWORD])
    assert 'no longer works' in capsys.readouterr().out
    assert users.authenticate(vault_root, 'owner@example.test', PASSWORD) is None
    assert users.authenticate(vault_root, 'owner@example.test', OTHER_PASSWORD) is not None


def test_a_reset_password_is_what_the_login_page_accepts(app, admin, vault_root):
    users.main(['--vault', str(vault_root), 'reset-password',
                '--email', 'owner@example.test', '--password', OTHER_PASSWORD])
    client = app.test_client()
    assert log_in(client, password=PASSWORD).status_code == 401
    assert log_in(client, password=OTHER_PASSWORD).status_code == 200


def test_the_command_line_disables_and_enables(vault_root, admin, capsys):
    users.main(['--vault', str(vault_root), 'disable', '--email', 'owner@example.test'])
    assert users.find_by_email(vault_root, 'owner@example.test')['disabled'] is True
    assert users.authenticate(vault_root, 'owner@example.test', PASSWORD) is None
    users.main(['--vault', str(vault_root), 'enable', '--email', 'owner@example.test'])
    assert users.find_by_email(vault_root, 'owner@example.test')['disabled'] is False
    assert users.authenticate(vault_root, 'owner@example.test', PASSWORD) is not None


def test_the_command_line_warns_about_a_second_admin_rather_than_complying_quietly(
        vault_root, admin, capsys):
    users.main(['--vault', str(vault_root), 'create', '--email', 'second@example.test',
                '--name', 'Second Admin', '--role', 'admin', '--password', OTHER_PASSWORD])
    printed = capsys.readouterr()
    assert 'an admin already exists' in printed.err
    assert len(users.admins(vault_root)) == 2


def test_a_tester_is_what_the_command_line_makes_without_being_asked(vault_root, capsys):
    users.main(['--vault', str(vault_root), 'create', '--email', 'tester@example.test',
                '--name', 'Tester', '--password', PASSWORD])
    assert users.find_by_email(vault_root, 'tester@example.test')['role'] == 'tester'
    assert capsys.readouterr().err == ''


def test_the_command_line_listing_never_prints_a_hash(vault_root, admin, capsys):
    users.main(['--vault', str(vault_root), 'list'])
    printed = capsys.readouterr().out
    assert 'owner@example.test' in printed and 'admin' in printed and 'active' in printed
    assert admin['password_hash'] not in printed
    assert PASSWORD not in printed


def test_the_command_line_says_so_when_there_is_nobody_to_find(vault_root, capsys):
    users.main(['--vault', str(vault_root), 'list'])
    assert 'No users yet.' in capsys.readouterr().out
    with pytest.raises(SystemExit) as missing:
        users.main(['--vault', str(vault_root), 'disable', '--email', 'nobody@example.test'])
    assert 'No user with the email nobody@example.test.' in str(missing.value)


# --- T9 ------------------------------------------------------------------

def test_an_error_body_for_a_bad_login_carries_neither_password_nor_hash(raw_client, admin):
    response = raw_client.post('/login', json={'email': 'owner@example.test',
                                               'password': PASSWORD + ' not quite'})
    body = response.get_data(as_text=True)
    assert PASSWORD not in body
    assert admin['password_hash'] not in body
    assert 'password_hash' not in body


def test_nothing_logs_a_password_or_a_hash(vault_root, caplog):
    with caplog.at_level(logging.DEBUG):
        created = users.create_user(vault_root, email='logged@example.test', name='Logged',
                                    role='tester', password=PASSWORD)
        users.authenticate(vault_root, 'logged@example.test', PASSWORD)
        users.authenticate(vault_root, 'logged@example.test', 'wrong')
        users.set_password(vault_root, created['id'], OTHER_PASSWORD)
    written = '\n'.join(record.getMessage() for record in caplog.records)
    for secret in (PASSWORD, OTHER_PASSWORD, created['password_hash']):
        assert secret not in written


def test_no_record_outside_the_users_area_holds_a_password(vault_root, admin):
    for path in Path(vault_root).rglob('*.yaml'):
        text = path.read_text()
        assert PASSWORD not in text
        if path.parent.name == 'users':
            continue
        assert 'password_hash' not in text and admin['password_hash'] not in text


def test_a_user_record_refuses_a_plain_password_field(vault_root):
    with pytest.raises(ValueError, match='never stores a plain password'):
        users.save_user(vault_root, {'email': 'a@example.test', 'name': 'A',
                                     'role': 'tester', 'password': PASSWORD})
    with pytest.raises(ValueError, match='werkzeug password hash'):
        users.save_user(vault_root, {'email': 'a@example.test', 'name': 'A',
                                     'role': 'tester', 'password_hash': PASSWORD})


def test_a_password_added_to_a_user_file_by_hand_is_dropped_on_the_next_save(
        vault_root, admin):
    """The allowlist filters the stored record, not only the payload, so a
    key nothing in the app can write cannot survive by never being
    mentioned in a payload again."""
    path = next(path for path, _ in users._entries(vault_root))
    planted = yaml.safe_load(path.read_text()) | {'password': PASSWORD}
    path.write_text(yaml.safe_dump(planted, sort_keys=False))
    assert 'password:' in path.read_text()

    users.main(['--vault', str(vault_root), 'disable', '--email', 'owner@example.test'])

    stored = yaml.safe_load(path.read_text())
    assert 'password' not in stored
    assert PASSWORD not in path.read_text()
    # The save it came through still did what it was asked.
    assert stored['id'] == admin['id'] and stored['disabled'] is True


def test_a_stored_user_holds_exactly_the_recorded_fields(vault_root, admin):
    # `locale` joined the list with CAREER-116: the field is defaulted on
    # save, so every record written from now on carries it.
    assert sorted(admin) == ['created_at', 'disabled', 'email', 'id', 'locale',
                             'name', 'password_hash', 'role']
    path = next(path for path, _ in users._entries(vault_root))
    assert sorted(yaml.safe_load(path.read_text())) == sorted(admin)


def test_a_user_record_refuses_an_unknown_role_and_a_bad_email(vault_root):
    for payload, message in (
            ({'role': 'owner'}, 'Role must be one of'),
            ({'email': 'not-an-address'}, 'Email must be an address'),
            ({'name': '  '}, 'Name is required'),
    ):
        base = {'email': 'b@example.test', 'name': 'B', 'role': 'tester',
                'password_hash': 'scrypt:1:1:1$salt$hash'}
        with pytest.raises(ValueError, match=message):
            users.save_user(vault_root, base | payload)


# --- The language on the record, and GET /api/me (CAREER-116) ------------
#
# Which languages exist is the catalog's answer (`i18n.available_locales`
# reads `frontend/src/i18n/*.json`), so today the allowed set is `en`
# alone and a record may say nothing else. Nothing sets the field yet:
# /api/me is the read, and the UI that changes it is a later PR.

def test_a_new_account_is_stored_with_the_catalog_s_own_language(vault_root, admin):
    assert admin['locale'] == 'en'
    path = next(path for path, _ in users._entries(vault_root))
    assert yaml.safe_load(path.read_text())['locale'] == 'en'


def test_a_user_record_refuses_a_language_the_catalog_does_not_ship(vault_root, admin):
    """`de` is a real language and not one this app has strings for, so a
    record that claimed it would promise a page we cannot render."""
    with pytest.raises(ValueError, match='Locale must be one of en.'):
        users.save_user(vault_root, {'locale': 'de'}, admin['id'])
    # The refused write changed nothing on disk.
    path = next(path for path, _ in users._entries(vault_root))
    assert yaml.safe_load(path.read_text())['locale'] == 'en'

    with pytest.raises(ValueError, match='Locale must be one of en.'):
        users.save_user(vault_root, {'email': 'dee@example.test', 'name': 'Dee',
                                     'role': 'tester', 'locale': 'de',
                                     'password_hash': 'scrypt:1:1:1$salt$hash'})
    assert users.find_by_email(vault_root, 'dee@example.test') is None

    with pytest.raises(ValueError, match='locale must be text'):
        users.save_user(vault_root, {'locale': ['en']}, admin['id'])


def test_a_translation_the_catalog_gains_needs_no_change_to_the_record(
        vault_root, admin, tmp_path, monkeypatch):
    """The allowed set is derived, which is the point of deriving it: the
    day `de.json` lands beside `en.json`, a record may say `de`."""
    catalog = tmp_path / 'i18n'
    catalog.mkdir()
    for locale in ('en', 'de'):
        (catalog / f'{locale}.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(i18n, 'CATALOG_PATH', catalog / 'en.json')
    assert i18n.available_locales() == ('de', 'en')

    stored = users.save_user(vault_root, {'locale': 'de'}, admin['id'])
    assert stored['locale'] == 'de'
    assert users.locale(users.load_user(vault_root, admin['id'])) == 'de'


def test_a_record_written_before_the_field_existed_reads_as_english(vault_root, admin, app):
    """Every account created before CAREER-116 is a stored record with no
    `locale` line, and it reads as the catalog's language through the same
    path /api/me uses -- not only after something saves it again."""
    path = next(path for path, _ in users._entries(vault_root))
    stored = yaml.safe_load(path.read_text())
    del stored['locale']
    path.write_text(yaml.safe_dump(stored, sort_keys=False))
    assert 'locale' not in path.read_text()

    assert users.locale(users.load_user(vault_root, admin['id'])) == 'en'

    client = app.test_client()
    log_in(client)
    assert client.get('/api/me').get_json()['locale'] == 'en'
    # Still unsaved: a read does not rewrite the record it read.
    assert 'locale' not in path.read_text()


def test_api_me_carries_the_safe_subset_of_the_signed_in_user(app, admin):
    client = app.test_client()
    log_in(client)
    response = client.get('/api/me')
    assert response.status_code == 200
    assert response.get_json() == {'id': admin['id'], 'name': 'Owner',
                                   'email': 'owner@example.test', 'role': 'admin',
                                   'locale': 'en'}
    # Neither the credential nor the session machinery, by name or by value.
    body = response.get_data(as_text=True)
    assert 'password_hash' not in body and admin['password_hash'] not in body
    assert users.SESSION_EPOCH_FIELD not in body and 'disabled' not in body


def test_api_me_answers_reads_only(app, admin):
    client = app.test_client()
    log_in(client)
    for method in (client.post, client.put):
        assert method('/api/me', json={'locale': 'de'}).status_code == 405
