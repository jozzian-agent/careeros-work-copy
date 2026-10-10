"""Shell contracts using synthetic vaults exclusively."""

from pathlib import Path
import re

import pytest
import yaml

from careeros.server import create_app
from careeros.web import theme, ui
from careeros.web.pages import companies, experiences, jobs, search

ROOT = Path(__file__).resolve().parents[1]
PAGES = (search, experiences, jobs, companies)


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    app.config['TESTING'] = True
    return app.test_client()


@pytest.mark.parametrize('route,module', [('/', search)] + [(f'/{m.__name__.split(".")[-1]}', m) for m in PAGES])
def test_routes(client, route, module):
    response = client.get(route)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    slug = module.__name__.split('.')[-1]
    assert module.EMPTY_STATE in html
    assert f"href='/{slug}' class='active' aria-current='page'" in html
    assert 'CareerOS' in html
    assert html.count("aria-current='page'") == 1
    assert [html.index(f"href='/{s}'", html.index('<nav')) for s, _ in theme.NAV_PAGES] == sorted(html.index(f"href='/{s}'", html.index('<nav')) for s, _ in theme.NAV_PAGES)


def test_not_found(client):
    response = client.get('/missing')
    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert 'Page not found' in html
    assert 'CareerOS' in html and "<nav class='page-nav'" in html
    assert "aria-current='page'" not in html


@pytest.mark.parametrize('exists', [True, False])
def test_empty_or_missing_vault(tmp_path, exists):
    vault = tmp_path / 'synthetic-vault'
    if exists:
        vault.mkdir()
    app = create_app(vault)
    for route in ['/', '/search', '/experiences', '/jobs', '/companies']:
        assert app.test_client().get(route).status_code == 200
    assert list(vault.iterdir()) == [] if exists else not vault.exists()
    assert app.config['VAULT_PATH'] == vault


def test_theme_is_domain_free():
    source = Path(theme.__file__).read_text()
    assert not re.search(r'(?:from|import)\s+dashboard\b|HRV|TrendBadge|Sphere|Topic|WATCH_ICON|PENCIL_ICON', source)
    assert '--bg-page: #08090a;' in theme.CSS_VARS
    assert '--accent-indigo: #5e6ad2;' in theme.CSS_VARS
    assert 'font-weight: 700' not in theme.BASE_CSS


def test_external_link_token_and_no_hardcoded_colors():
    assert '--link-external' in theme.CSS_VARS
    assert re.search(r'a\.external\s*\{[^}]*color:\s*var\(--link-external\)', theme.BASE_CSS)
    assert '::after' in theme.BASE_CSS
    link_rules = re.findall(r'a(?:\.external)?\s*\{[^}]*\}', theme.BASE_CSS)
    assert link_rules
    assert not any(re.search(r'#[0-9a-fA-F]{3,6}', rule) for rule in link_rules)


def test_viewport_meta_tag_present(client):
    response = client.get('/jobs')
    html = response.get_data(as_text=True)
    assert "<meta name='viewport' content='width=device-width, initial-scale=1'>" in html


def test_mobile_breakpoint_css_in_served_stylesheet(client):
    response = client.get('/companies')
    html = response.get_data(as_text=True)
    assert f'@media (max-width: {theme.MOBILE_BREAKPOINT}px)' in html
    assert f'@media(max-width:{theme.MOBILE_BREAKPOINT}px)' in html
    assert '.grid {grid-template-columns:1fr;}' in html


def test_no_hardcoded_colors_in_mobile_css():
    for sheet in (theme.BASE_CSS, ui.CSS):
        assert not re.search(r'#[0-9a-fA-F]{3,6}', sheet)


def test_synthetic_sample():
    criteria = yaml.safe_load((ROOT / 'sample/vault/search.yaml').read_text())
    assert criteria['roles'] == ['Platform engineering lead', 'Developer tools manager']
    entries = sorted((ROOT / 'sample/vault/experiences').glob('*.yaml'))
    assert len(entries) == 3
    summaries = {yaml.safe_load(p.read_text())['summary'] for p in entries}
    assert len(summaries) == 3, 'sample experiences must not be copy-paste clones'
    for path in entries:
        data = yaml.safe_load(path.read_text())
        assert data['salary'] is None
        assert 'invented' not in data['location'].lower()
