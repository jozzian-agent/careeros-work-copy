"""Protects the gate in `scripts/check_i18n.py`: the real catalog passes,
and every forbidden shape of value fails with exit 1 and a message naming
the key that broke.

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
    assert 'placeholders only, OK' in result.stdout


def test_a_clean_catalog_passes(tmp_path):
    result = check(tmp_path, {
        'shell.logOut': 'Log out',
        'mail.greeting': 'Hello {name}, and hello again {name}',
        'board.empty': 'Nothing here yet',
    })
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('value', [
    '{count, plural, one {# job} other {# jobs}}',
    '{gender, select, male {he} female {she} other {they}}',
    '{place, selectordinal, one {#st} other {#th}}',
    '{count, number}',
    '{when, date, short}',
    '{name,}',
])
def test_an_icu_construct_fails(tmp_path, value):
    result = check(tmp_path, {'board.count': value})
    assert result.returncode == 1
    assert 'board.count' in result.stderr
    assert 'ICU' in result.stderr


def test_an_unbalanced_opening_brace_fails(tmp_path):
    result = check(tmp_path, {'mail.greeting': 'Hello {name'})
    assert result.returncode == 1
    assert 'mail.greeting' in result.stderr
    assert 'unbalanced opening brace' in result.stderr


def test_an_unbalanced_closing_brace_fails(tmp_path):
    result = check(tmp_path, {'mail.greeting': 'Hello name}'})
    assert result.returncode == 1
    assert 'unbalanced closing brace' in result.stderr


def test_a_doubled_brace_fails(tmp_path):
    result = check(tmp_path, {'mail.literal': 'Use {{name}} like this'})
    assert result.returncode == 1
    assert 'doubled brace' in result.stderr


def test_an_empty_value_fails(tmp_path):
    result = check(tmp_path, {'shell.logOut': ''})
    assert result.returncode == 1
    assert 'shell.logOut' in result.stderr
    assert 'empty' in result.stderr


@pytest.mark.parametrize('value', [
    'Hello {first name}',
    'Hello {first-name}',
    'Hello {2nd}',
    'Hello {}',
    'Hello {name.first}',
])
def test_a_placeholder_that_is_not_an_identifier_fails(tmp_path, value):
    result = check(tmp_path, {'mail.greeting': value})
    assert result.returncode == 1
    assert 'identifier' in result.stderr


def test_a_key_with_surrounding_whitespace_fails(tmp_path):
    result = check(tmp_path, {' shell.logOut ': 'Log out'})
    assert result.returncode == 1
    assert 'whitespace' in result.stderr


def test_every_broken_key_is_named_in_one_run(tmp_path):
    result = check(tmp_path, {
        'a.plural': '{n, plural, one {#} other {#}}',
        'b.empty': '',
        'c.fine': 'Fine',
    })
    assert result.returncode == 1
    assert 'a.plural' in result.stderr
    assert 'b.empty' in result.stderr
    assert 'c.fine' not in result.stderr


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
