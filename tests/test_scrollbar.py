"""Section 5 (Reusable Modern Scrollbar). Scoped selectors plus an opt-in
.scroll-thin class, rather than a blanket "*" override."""
import re

from careeros.server import create_app
from careeros.web import theme


def test_scrollbar_css_is_scoped_not_global():
    assert '*::-webkit-scrollbar' not in theme.SCROLLBAR_CSS
    assert '.scroll-thin' in theme.SCROLLBAR_CSS
    assert '.kanban' in theme.SCROLLBAR_CSS
    assert 'table' in theme.SCROLLBAR_CSS


def test_scrollbar_css_reuses_existing_tokens_only():
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b', theme.SCROLLBAR_CSS)
    assert 'var(--border-standard)' in theme.SCROLLBAR_CSS


def test_kanban_picks_up_scrollbar_styling_with_no_markup_change(tmp_path):
    client = create_app(tmp_path).test_client()
    html = client.get('/jobs').text
    styles = ''.join(re.findall(r'<style>(.*?)</style>', html, re.S))
    assert theme.SCROLLBAR_CSS in styles
    assert '.kanban' in html  # the existing .kanban markup is untouched


def test_mobile_table_overflow_rule_picks_up_scrollbar_styling(tmp_path):
    client = create_app(tmp_path).test_client()
    html = client.get('/jobs').text
    styles = ''.join(re.findall(r'<style>(.*?)</style>', html, re.S))
    assert 'table { display: block; max-width: 100%; overflow-x: auto; }' in styles
    assert theme.SCROLLBAR_CSS in styles


def test_page_shell_concatenates_scrollbar_css_after_base_css():
    html = theme.page_shell('Title', 'search', '<p>body</p>')
    assert theme.CSS_VARS + theme.BASE_CSS + theme.SCROLLBAR_CSS in html
