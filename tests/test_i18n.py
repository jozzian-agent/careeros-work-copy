"""Protects the rules of `careeros/i18n.py`: the real catalog loads and is
cached, `server.*` keys render with their placeholders filled, keys OUTSIDE
the namespace are refused rather than rendered, a missing variable raises
and names its key rather than returning the raw pattern, and a `server.*`
key that is not in the catalog logs a warning and comes back as itself so
a typo cannot fail a mail send.

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
    assert i18n.load_catalog()['server.mail.greeting'] == \
        'Hello {name}, your Career OS digest is ready'


def test_the_catalog_is_parsed_once_per_path():
    assert i18n.load_catalog() is i18n.load_catalog()


def test_a_catalog_cannot_be_edited_through_what_the_loader_returns():
    with pytest.raises(TypeError):
        i18n.load_catalog()['server.mail.greeting'] = 'Leave'


def test_load_catalog_holds_only_server_keys():
    catalog = i18n.load_catalog()
    assert all(key.startswith('server.') for key in catalog)
    # the client example key is in the file but not in the server view
    assert 'shell.logOut' not in catalog
    assert 'shell.logOut' in i18n.load_raw_catalog()


def test_a_plain_server_key_comes_back_as_its_string(catalog):
    catalog({'server.pages.title': 'Dashboard'})
    assert i18n.tr('server.pages.title') == 'Dashboard'


def test_placeholders_are_substituted(catalog):
    catalog({'server.mail.greeting': 'Hello {name}, you have {count} invites'})
    assert i18n.tr('server.mail.greeting', name='Jo', count=2) == \
        'Hello Jo, you have 2 invites'


def test_the_same_placeholder_twice_is_filled_twice(catalog):
    catalog({'server.mail.repeat': '{name}, really, {name}'})
    assert i18n.tr('server.mail.repeat', name='Jo') == 'Jo, really, Jo'


def test_a_key_outside_the_server_namespace_is_refused(catalog):
    catalog({'shell.logOut': 'Log out'})
    with pytest.raises(i18n.CatalogError) as raised:
        i18n.tr('shell.logOut')
    assert 'shell.logOut' in str(raised.value)
    assert 'server.' in str(raised.value)


def test_an_icu_client_key_is_refused_even_though_it_loads_raw(catalog):
    catalog({'board.count': '{n, plural, one {# job} other {# jobs}}'})
    with pytest.raises(i18n.CatalogError):
        i18n.tr('board.count', n=2)


def test_a_non_string_key_is_refused():
    with pytest.raises(i18n.CatalogError):
        i18n.tr(None)


def test_a_missing_variable_raises_and_names_the_key(catalog):
    catalog({'server.mail.greeting': 'Hello {name}'})
    with pytest.raises(i18n.CatalogError) as raised:
        i18n.tr('server.mail.greeting')
    message = str(raised.value)
    assert 'server.mail.greeting' in message
    assert "'name'" in message
    assert 'Variables given: none' in message


def test_an_unfillable_pattern_raises_rather_than_returning_itself(catalog):
    catalog({'server.mail.broken': 'Hello {'})
    with pytest.raises(i18n.CatalogError) as raised:
        i18n.tr('server.mail.broken', name='Jo')
    assert 'server.mail.broken' in str(raised.value)


def test_a_positional_placeholder_raises(catalog):
    catalog({'server.mail.positional': 'Hello {0}'})
    with pytest.raises(i18n.CatalogError):
        i18n.tr('server.mail.positional', name='Jo')


def test_a_missing_server_key_returns_the_key_and_logs_a_warning(catalog, caplog):
    catalog({'server.pages.title': 'Dashboard'})
    with caplog.at_level(logging.WARNING):
        assert i18n.tr('server.pages.subtitle') == 'server.pages.subtitle'
    assert any('server.pages.subtitle' in record.getMessage() for record in caplog.records)


def test_an_extra_variable_is_ignored(catalog):
    catalog({'server.pages.title': 'Dashboard'})
    assert i18n.tr('server.pages.title', name='Jo') == 'Dashboard'


def test_a_catalog_that_is_not_an_object_is_refused(tmp_path):
    path = tmp_path / 'en.json'
    path.write_text('["server.pages.title"]', encoding='utf-8')
    with pytest.raises(ValueError, match='JSON object'):
        i18n.load_raw_catalog(path)


def test_a_value_that_is_not_a_string_is_refused(tmp_path):
    path = tmp_path / 'en.json'
    path.write_text('{"server.mail.count": 3}', encoding='utf-8')
    with pytest.raises(ValueError, match='server.mail.count'):
        i18n.load_raw_catalog(path)


def test_load_raw_sees_every_key(catalog):
    catalog({'server.pages.title': 'Dashboard', 'shell.logOut': 'Log out'})
    raw = i18n.load_raw_catalog()
    assert set(raw) == {'server.pages.title', 'shell.logOut'}
