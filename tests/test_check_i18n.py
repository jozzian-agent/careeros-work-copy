"""Protects the gate in `scripts/check_i18n.py`: the real catalog passes,
ICU is allowed in client keys but fails in `server.*` keys, and the basic
validity rules (balanced braces, no empty values, no padded keys) hold for
every key in either namespace.

Run through a subprocess, the way CI and a person run it, so the exit code
under test is the one the CI step reads. Each case feeds a synthetic
catalog through `--catalog`, so nothing here depends on, or touches, what
is in the real file.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'check_i18n.py'


def run(*arguments):
    return subprocess.run([sys.executable, str(SCRIPT), *arguments],
                          cwd=ROOT, capture_output=True, text=True, check=False)


def check(tmp_path, entries):
    """Run the gate over one synthetic catalog."""
    path = tmp_path / 'en.json'
    path.write_text(json.dumps(entries), encoding='utf-8')
    return run('--catalog', str(path))


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


def test_the_gate_runs_in_ci():
    workflow = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
    assert 'python scripts/check_i18n.py' in workflow
