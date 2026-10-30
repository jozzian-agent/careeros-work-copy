"""Protects the rules of `careeros/i18n.py`: the real catalog loads and is
cached, a filled pattern comes back filled, a missing variable raises and
names its key rather than returning the raw pattern, and a key that is not
in the catalog logs a warning and comes back as itself so a typo cannot
fail a mail send.

Every test that needs a catalog of its own writes one under tmp_path and
points `CATALOG_PATH` at it. The real `frontend/src/i18n/en.json` is read
but never written.
"""

import json
import logging
from pathlib import Path

import pytest

from careeros import i18n

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def fresh_cache():
    """No catalog parsed by one test is visible to the next."""
    i18n.clear_cache()
    yield
    i18n.clear_cache()


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """Write a catalog and make it the one `tr` reads."""
    def write(entries):
        path = tmp_path / 'en.json'
        path.write_text(json.dumps(entries), encoding='utf-8')
        monkeypatch.setattr(i18n, 'CATALOG_PATH', path)
        return path
    return write


def test_the_real_catalog_is_the_one_the_front_end_owns():
    assert i18n.CATALOG_PATH == ROOT / 'frontend' / 'src' / 'i18n' / 'en.json'
    assert i18n.load_catalog()['shell.logOut'] == 'Log out'


def test_the_catalog_is_parsed_once_per_path():
    assert i18n.load_catalog() is i18n.load_catalog()


def test_a_catalog_cannot_be_edited_through_what_the_loader_returns():
    with pytest.raises(TypeError):
        i18n.load_catalog()['shell.logOut'] = 'Leave'


def test_a_plain_key_comes_back_as_its_string(catalog):
    catalog({'shell.logOut': 'Log out'})
    assert i18n.tr('shell.logOut') == 'Log out'


def test_placeholders_are_substituted(catalog):
    catalog({'mail.greeting': 'Hello {name}, you have {count} invites'})
    assert i18n.tr('mail.greeting', name='Jo', count=2) == 'Hello Jo, you have 2 invites'


def test_the_same_placeholder_twice_is_filled_twice(catalog):
    catalog({'mail.repeat': '{name}, really, {name}'})
    assert i18n.tr('mail.repeat', name='Jo') == 'Jo, really, Jo'


def test_a_missing_variable_raises_and_names_the_key(catalog):
    catalog({'mail.greeting': 'Hello {name}'})
    with pytest.raises(i18n.CatalogError) as raised:
        i18n.tr('mail.greeting')
    message = str(raised.value)
    assert 'mail.greeting' in message
    assert "'name'" in message
    assert 'Variables given: none' in message


def test_an_unfillable_pattern_raises_rather_than_returning_itself(catalog):
    catalog({'mail.broken': 'Hello {'})
    with pytest.raises(i18n.CatalogError) as raised:
        i18n.tr('mail.broken', name='Jo')
    assert 'mail.broken' in str(raised.value)


def test_a_positional_placeholder_raises(catalog):
    catalog({'mail.positional': 'Hello {0}'})
    with pytest.raises(i18n.CatalogError):
        i18n.tr('mail.positional', name='Jo')


def test_a_missing_key_returns_the_key_and_logs_a_warning(catalog, caplog):
    catalog({'shell.logOut': 'Log out'})
    with caplog.at_level(logging.WARNING):
        assert i18n.tr('shell.logIn') == 'shell.logIn'
    assert any('shell.logIn' in record.getMessage() for record in caplog.records)


def test_an_extra_variable_is_ignored(catalog):
    catalog({'shell.logOut': 'Log out'})
    assert i18n.tr('shell.logOut', name='Jo') == 'Log out'


def test_a_catalog_that_is_not_an_object_is_refused(tmp_path):
    path = tmp_path / 'en.json'
    path.write_text('["shell.logOut"]', encoding='utf-8')
    with pytest.raises(ValueError, match='JSON object'):
        i18n.load_catalog(path)


def test_a_value_that_is_not_a_string_is_refused(tmp_path):
    path = tmp_path / 'en.json'
    path.write_text('{"shell.count": 3}', encoding='utf-8')
    with pytest.raises(ValueError, match='shell.count'):
        i18n.load_catalog(path)
