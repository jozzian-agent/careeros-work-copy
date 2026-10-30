"""Protects the gate in `scripts/check_i18n.py`: the real catalog passes,
ICU is allowed in client keys but fails in `server.*` keys, the basic
validity rules (balanced braces, no empty values, no padded keys) hold for
every key in either namespace, and the catalog stays in sync with the code
both ways -- no key nothing reads, no id no key answers.

Mostly run through a subprocess, the way CI and a person run it, so the
exit code under test is the one the CI step reads. A validity case feeds a
synthetic catalog through `--catalog` alone, which runs the validity rules
and nothing else; a sync case builds a whole little tree under tmp_path and
points `--root` at it. Nothing here depends on, or touches, the real file,
apart from the one test that says the real file passes.

The last section calls the scanning functions directly rather than through
the process, because what they answer -- which keys this text mentions --
is worth pinning down one tree at a time.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'check_i18n.py'

sys.path.insert(0, str(ROOT / 'scripts'))

import check_i18n  # noqa: E402


def run(*arguments):
    return subprocess.run([sys.executable, str(SCRIPT), *arguments],
                          cwd=ROOT, capture_output=True, text=True, check=False)


def check(tmp_path, entries):
    """Run the gate over one synthetic catalog."""
    path = tmp_path / 'en.json'
    path.write_text(json.dumps(entries), encoding='utf-8')
    return run('--catalog', str(path))


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


@pytest.fixture
def tree(tmp_path):
    """Build a tree shaped like this repo and run the whole gate over it.

    `client` and `server` are {path relative to frontend/src or careeros:
    file text}, which is enough to say what reads which key without a
    checkout of anything.
    """
    def build(catalog, client=None, server=None):
        root = tmp_path / 'tree'
        write(root, Path('frontend') / 'src' / 'i18n' / 'en.json', json.dumps(catalog))
        for relative, text in (client or {}).items():
            write(root, Path('frontend') / 'src' / relative, text)
        for relative, text in (server or {}).items():
            write(root, Path('careeros') / relative, text)
        return run('--root', str(root))
    return build


def test_the_real_catalog_passes():
    result = run()
    assert result.returncode == 0, result.stderr
    assert 'OK' in result.stdout


def test_a_clean_catalog_passes(tmp_path):
    result = check(tmp_path, {
        'server.mail.greeting': 'Hello {name}, and hello again {name}',
        'shell.logOut': 'Log out',
        'board.empty': 'Nothing here yet',
    })
    assert result.returncode == 0, result.stderr


# ---- client keys may use full ICU ----

@pytest.mark.parametrize('value', [
    '{count, plural, one {# job} other {# jobs}}',
    '{gender, select, male {he} female {she} other {they}}',
    '{place, selectordinal, one {#st} other {#th}}',
    '{count, number}',
    '{when, date, short}',
    '{literal, select, other {a brace}}',
])
def test_an_icu_construct_is_allowed_in_a_client_key(tmp_path, value):
    result = check(tmp_path, {'board.count': value})
    assert result.returncode == 0, result.stderr


def test_apostrophe_quoting_is_allowed_in_a_client_key(tmp_path):
    result = check(tmp_path, {'board.quote': "It''s {n, plural, one {a job} other {# jobs}}"})
    assert result.returncode == 0, result.stderr


# ---- server.* keys are strict: placeholders only ----

@pytest.mark.parametrize('value', [
    '{count, plural, one {# job} other {# jobs}}',
    '{gender, select, male {he} female {she} other {they}}',
    '{place, selectordinal, one {#st} other {#th}}',
    '{count, number}',
    '{when, date, short}',
    '{name,}',
])
def test_an_icu_construct_fails_in_a_server_key(tmp_path, value):
    result = check(tmp_path, {'server.mail.count': value})
    assert result.returncode == 1
    assert 'server.mail.count' in result.stderr
    assert 'ICU' in result.stderr


def test_a_doubled_brace_fails_in_a_server_key(tmp_path):
    result = check(tmp_path, {'server.mail.literal': 'Use {{name}} like this'})
    assert result.returncode == 1
    assert 'doubled brace' in result.stderr


@pytest.mark.parametrize('value', [
    'Hello {first name}',
    'Hello {first-name}',
    'Hello {2nd}',
    'Hello {}',
    'Hello {name.first}',
])
def test_a_server_placeholder_that_is_not_an_identifier_fails(tmp_path, value):
    result = check(tmp_path, {'server.mail.greeting': value})
    assert result.returncode == 1
    assert 'identifier' in result.stderr


def test_a_nested_brace_in_a_server_placeholder_fails(tmp_path):
    result = check(tmp_path, {'server.mail.greeting': 'Hello {name {x}}'})
    assert result.returncode == 1
    assert 'server.mail.greeting' in result.stderr


# ---- basic validity holds for every key ----

@pytest.mark.parametrize('key', ['shell.logOut', 'server.mail.greeting'])
def test_an_unbalanced_opening_brace_fails_in_either_namespace(tmp_path, key):
    result = check(tmp_path, {key: 'Hello {name'})
    assert result.returncode == 1
    assert key in result.stderr
    assert 'unbalanced opening brace' in result.stderr


@pytest.mark.parametrize('key', ['shell.logOut', 'server.mail.greeting'])
def test_an_unbalanced_closing_brace_fails_in_either_namespace(tmp_path, key):
    result = check(tmp_path, {key: 'Hello name}'})
    assert result.returncode == 1
    assert 'unbalanced closing brace' in result.stderr


@pytest.mark.parametrize('key', ['shell.logOut', 'server.mail.greeting'])
def test_an_empty_value_fails_in_either_namespace(tmp_path, key):
    result = check(tmp_path, {key: ''})
    assert result.returncode == 1
    assert key in result.stderr
    assert 'empty' in result.stderr


@pytest.mark.parametrize('key', [' shell.logOut ', ' server.mail.greeting '])
def test_a_key_with_surrounding_whitespace_fails_in_either_namespace(tmp_path, key):
    result = check(tmp_path, {key: 'Log out'})
    assert result.returncode == 1
    assert 'whitespace' in result.stderr


def test_every_broken_key_is_named_in_one_run(tmp_path):
    result = check(tmp_path, {
        'server.a.plural': '{n, plural, one {#} other {#}}',
        'b.empty': '',
        'c.fine': 'Fine',
        'd.plural.fine': '{n, plural, one {#} other {#}}',
    })
    assert result.returncode == 1
    assert 'server.a.plural' in result.stderr
    assert 'b.empty' in result.stderr
    assert 'c.fine' not in result.stderr
    # the client plural is legal and must not be named as broken
    assert 'd.plural.fine' not in result.stderr


def test_a_missing_catalog_fails_without_a_traceback(tmp_path):
    result = run('--catalog', str(tmp_path / 'nope.json'))
    assert result.returncode == 1
    assert 'unreadable string catalog' in result.stderr
    assert 'Traceback' not in result.stderr


def test_a_catalog_that_is_not_json_fails_without_a_traceback(tmp_path):
    path = tmp_path / 'en.json'
    path.write_text('{not json', encoding='utf-8')
    result = run('--catalog', str(path))
    assert result.returncode == 1
    assert 'unreadable string catalog' in result.stderr
    assert 'Traceback' not in result.stderr


# ---- the sync rule: the catalog and the code name the same keys ----

def test_a_key_the_code_reads_passes(tree):
    result = tree(
        {'board.title': 'My Jobs'},
        client={'pages/JobsBoard.jsx': "<PageLayout title={<FormattedMessage id=\"board.title\" />} />"},
    )
    assert result.returncode == 0, result.stderr
    assert 'all used' in result.stdout


def test_a_client_key_nothing_reads_fails(tree):
    result = tree(
        {'board.title': 'My Jobs', 'board.ghost': 'Nobody renders me'},
        client={'pages/JobsBoard.jsx': "<FormattedMessage id='board.title' />"},
    )
    assert result.returncode == 1
    assert 'board.ghost' in result.stderr
    assert 'nothing reads this key' in result.stderr
    # the key that IS read must not be named as broken
    assert 'board.title:' not in result.stderr


def test_an_id_the_catalog_does_not_hold_fails(tree):
    result = tree(
        {'board.title': 'My Jobs'},
        client={'pages/JobsBoard.jsx': '<FormattedMessage id="board.ttile" />\n'
                                       "<FormattedMessage id='board.title' />"},
    )
    assert result.returncode == 1
    assert 'board.ttile' in result.stderr
    assert 'no such key' in result.stderr
    assert 'JobsBoard.jsx' in result.stderr


def test_a_server_key_a_tr_call_reads_passes(tree):
    result = tree(
        {'server.mail.greeting': 'Hello {name}'},
        server={'mail.py': "body = tr('server.mail.greeting', name=who)"},
    )
    assert result.returncode == 0, result.stderr


def test_a_server_key_no_tr_call_reads_fails(tree):
    result = tree(
        {'server.mail.greeting': 'Hello {name}', 'server.mail.ghost': 'Nobody sends me'},
        server={'mail.py': 'body = tr("server.mail.greeting", name=who)'},
    )
    assert result.returncode == 1
    assert 'server.mail.ghost' in result.stderr
    assert 'tr(' in result.stderr


def test_a_server_key_is_not_satisfied_by_a_client_mention(tree):
    """The two namespaces are read by two runtimes, and so by two scans."""
    result = tree(
        {'server.mail.greeting': 'Hello {name}'},
        client={'pages/Mail.jsx': "const key = 'server.mail.greeting';"},
    )
    assert result.returncode == 1
    assert 'server.mail.greeting' in result.stderr


def test_a_nested_python_module_is_found(tree):
    result = tree(
        {'server.pages.title': 'Dashboard'},
        server={'web/theme.py': "heading = tr('server.pages.title')"},
    )
    assert result.returncode == 0, result.stderr


def test_a_catalog_given_on_its_own_is_only_checked_for_validity(tmp_path):
    """A file from elsewhere has no tree to be in sync with.

    This is what lets every validity case above feed the gate a synthetic
    catalog whose keys no code reads. CI passes neither flag, so it gets
    both gates.
    """
    result = check(tmp_path, {'nothing.reads.me': 'Still fine'})
    assert result.returncode == 0, result.stderr
    assert 'sync rules skipped' in result.stdout


def test_the_real_repo_passes_the_sync_rule():
    result = run()
    assert result.returncode == 0, result.stderr
    assert 'all used' in result.stdout


# ---- the scanning functions, one tree at a time ----

def test_used_client_keys_reads_js_and_jsx_and_skips_the_catalog(tmp_path):
    write(tmp_path, 'Nav.jsx', "formatMessage({ id: 'shell.logOut' })")
    write(tmp_path, 'nested/deep/filters.js', "const k = 'board.title';")
    write(tmp_path, 'i18n/en.json', json.dumps({'board.ghost': 'x'}))
    write(tmp_path, 'notes.md', "'board.fromADoc'")
    assert check_i18n.used_client_keys(tmp_path) >= {'shell.logOut', 'board.title'}
    # the catalog quotes every key it holds, so reading it would make the
    # rule vacuous; a file that is not JavaScript is not code either
    assert 'board.ghost' not in check_i18n.used_client_keys(tmp_path)
    assert 'board.fromADoc' not in check_i18n.used_client_keys(tmp_path)


def test_used_client_keys_wants_a_dot_and_no_whitespace(tmp_path):
    write(tmp_path, 'Nav.jsx', "const a = 'nodot'; const b = 'two words.here';")
    assert check_i18n.used_client_keys(tmp_path) == set()


def test_used_client_keys_on_a_missing_directory_is_empty(tmp_path):
    assert check_i18n.used_client_keys(tmp_path / 'nope') == set()


def test_asked_client_ids_reads_both_quoting_styles(tmp_path):
    write(tmp_path, 'Nav.jsx', '<FormattedMessage id="shell.nav.jobs" />\n'
                               "formatMessage({ id: 'shell.logOut' })")
    assert {key for key, _path in check_i18n.asked_client_ids(tmp_path)} == \
        {'shell.nav.jobs', 'shell.logOut'}


def test_asked_client_ids_names_the_file_that_asks(tmp_path):
    write(tmp_path, 'pages/Login.jsx', '<FormattedMessage id="login.title" />')
    (key, path), = check_i18n.asked_client_ids(tmp_path)
    assert key == 'login.title'
    assert path.name == 'Login.jsx'


def test_asked_client_ids_leaves_a_dom_id_alone(tmp_path):
    write(tmp_path, 'pages/Login.jsx', '<TextField id="login-email" />\n'
                                       '<Box data-testid="company-card.1" />\n'
                                       '<SelectList id="job-sort" />')
    assert check_i18n.asked_client_ids(tmp_path) == []


def test_used_server_keys_reads_tr_calls_recursively(tmp_path):
    write(tmp_path, 'mail.py', "tr('server.mail.greeting', name=who)")
    write(tmp_path, 'web/theme.py', 'tr("server.pages.title")')
    write(tmp_path, 'web/notes.md', "tr('server.fromADoc')")
    assert check_i18n.used_server_keys(tmp_path) == \
        {'server.mail.greeting', 'server.pages.title'}


def test_used_server_keys_ignores_another_call_with_the_same_argument(tmp_path):
    write(tmp_path, 'mail.py', "render('server.mail.greeting')")
    assert check_i18n.used_server_keys(tmp_path) == set()


def test_missing_from_catalog_names_only_what_is_missing(tmp_path):
    asked = [('board.title', tmp_path / 'a.jsx'), ('board.ttile', tmp_path / 'b.jsx')]
    missing = check_i18n.missing_from_catalog({'board.title': 'My Jobs'}, asked)
    assert [key for key, _message in missing] == ['board.ttile']


def test_unused_problems_splits_the_two_namespaces(tmp_path):
    catalog = {'board.used': 'a', 'board.dead': 'b',
               'server.used': 'c', 'server.dead': 'd'}
    problems = check_i18n.unused_problems(catalog, {'board.used'}, {'server.used'})
    assert [key for key, _message in problems] == ['board.dead', 'server.dead']


def test_the_gate_runs_in_ci():
    workflow = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
    assert 'python scripts/check_i18n.py' in workflow
