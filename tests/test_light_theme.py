"""The server-rendered pages carry the same light brand as the React app.

CAREER-115. The four pages a person reaches without a session -- the login
fallback, forgot-password, accept-invite and choose-a-new-password -- are
server-rendered HTML built from ``careeros/web/theme.py``, while the React
app reads ``frontend/src/design/tokens.css``. Two files, one brand, so the
question this module answers is whether they still agree.

Three things are held here:

* the MAPPED_COLOURS table below, one entry per token pair, asserted in both
  directions -- a colour in theme.py with no token behind it fails just as
  loudly as a token that moved without theme.py following;
* WCAG AA contrast, computed from the palette itself rather than from
  numbers typed into an assertion, for every text-on-ground pair these pages
  actually paint;
* what a browser receives: the light values present, the dark ones gone, the
  vendored font declared, and not one request to a third party.
"""

from pathlib import Path
import re

import pytest

from careeros.server import create_app
from careeros.web import theme

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / 'frontend' / 'src' / 'design' / 'tokens.css'

#: tokens.css var name -> theme.py var name, one row per mapped pair. The
#: left side is the brand's word for the colour and the right side is the
#: name theme.py's CSS already consumes; several rows share a left side
#: because one brand colour can serve more than one role in the shell (the
#: card ground is both the dialog surface and the card surface; the brand
#: green is both the primary action and the success signal).
#:
#: Two right-hand names are historical and no longer describe their value:
#: `--accent-indigo` is the primary action colour and `--accent-violet` the
#: default anchor colour. This table is where that is written down.
MAPPED_COLOURS = (
    ('--color-background-page', '--bg-page'),
    ('--color-background-card', '--bg-panel'),
    ('--color-background-card', '--card-bg'),
    ('--color-background-secondary-base', '--bg-elevated'),
    ('--color-brand-wash', '--card-bg-elevated'),
    ('--color-text-default', '--text-primary'),
    ('--color-text-neutral', '--text-secondary'),
    ('--color-text-subtle', '--text-muted'),
    ('--color-text-subtle', '--text-faint'),
    ('--color-text-link', '--accent-violet'),
    ('--color-brand-on-color', '--text-on-accent'),
    ('--color-brand-primary', '--accent-indigo'),
    ('--color-brand-primary', '--status-success'),
    ('--color-brand-primary-strong', '--accent-indigo-strong'),
    ('--color-text-error', '--status-fail'),
    ('--color-text-warning', '--status-warn'),
    ('--color-border-container', '--border-standard'),
    ('--color-border-default', '--border-control'),
    ('--color-border-focus', '--border-focus'),
)

#: The same table for the two mapped values that are not colours: the
#: control rounding and the font stack. Compared with whitespace collapsed,
#: because tokens.css wraps the font stack over two lines.
MAPPED_VALUES = (
    ('--rounding-400', '--radius-control'),
    ('--font-sans', '--font-sans'),
)

#: Text-on-ground pairs these pages paint, as (foreground, background) var
#: names. Every one must clear WCAG AA for body text.
AA_PAIRS = (
    ('--text-muted', '--bg-page'),
    ('--text-muted', '--card-bg'),
    ('--text-secondary', '--bg-page'),
    ('--text-secondary', '--card-bg'),
    ('--text-faint', '--bg-page'),
    ('--text-faint', '--card-bg'),
    ('--accent-violet', '--bg-page'),
    ('--accent-violet', '--card-bg'),
    ('--text-on-accent', '--accent-indigo'),
    ('--text-primary', '--bg-elevated'),
    ('--text-secondary', '--bg-elevated'),
    ('--status-fail', '--card-bg'),
    ('--status-fail', '--bg-page'),
    ('--link-external', '--card-bg'),
)

AA_THRESHOLD = 4.5

#: The light block only: the dark block's selector is `:root[data-theme=...`,
#: which this pattern cannot match, and the server pages are light only.
_ROOT_BLOCK = re.compile(r'^:root\s*\{(.*?)^\}', re.S | re.M)
_TOKEN_DECL = re.compile(r'^(--[a-z0-9-]+)\s*:\s*(.+?)\s*!important$', re.S)
_THEME_DECL = re.compile(r'^(--[a-z0-9-]+)\s*:\s*(.+)$', re.S)
_HEX = re.compile(r'^#[0-9a-f]{6}$')


def _declarations(body, pattern, where):
    """Parse ``--name: value`` declarations out of one CSS block.

    Strict on purpose: a declaration this cannot read aborts the test
    instead of being skipped, because a silently skipped row is exactly
    how a drift guard stops guarding.
    """
    found = {}
    for chunk in body.split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = pattern.match(chunk)
        assert match, f'{where}: cannot read declaration {chunk!r}'
        name, value = match.group(1), ' '.join(match.group(2).split())
        assert name not in found, f'{where}: {name} declared twice'
        found[name] = value
    assert found, f'{where}: no declarations found'
    return found


def _block(text, where):
    match = _ROOT_BLOCK.search(text)
    assert match, f'{where}: no :root block found'
    return match.group(1)


def light_tokens():
    """The :root light block of tokens.css, as name -> value."""
    text = TOKENS.read_text()
    tokens = _declarations(_block(text, 'tokens.css'), _TOKEN_DECL, 'tokens.css')
    # A sanity floor: the handoff block is ~40 declarations. A parser that
    # started returning two of them would otherwise pass every row below.
    assert len(tokens) > 30, f'tokens.css: only {len(tokens)} declarations parsed'
    return tokens


def theme_vars(resolve=True):
    """theme.CSS_VARS as name -> value.

    With ``resolve`` on, a `var(--x)` alias is replaced by the value it
    points at, which is what a browser paints and so what the contrast
    pairs need. With it off, the declarations are returned as written,
    which is what tells a literal colour apart from an alias.
    """
    values = _declarations(_block(theme.CSS_VARS, 'theme.CSS_VARS'),
                           _THEME_DECL, 'theme.CSS_VARS')
    if not resolve:
        return values
    for name, value in list(values.items()):
        alias = re.fullmatch(r'var\((--[a-z0-9-]+)\)', value)
        if alias:
            assert alias.group(1) in values, f'theme.CSS_VARS: {name} aliases an unknown var'
            values[name] = values[alias.group(1)]
    return values


# --- the drift guard ------------------------------------------------------

def test_every_mapped_colour_matches_tokens_css():
    tokens, shell = light_tokens(), theme_vars()
    for token_name, theme_name in MAPPED_COLOURS:
        assert token_name in tokens, f'tokens.css no longer declares {token_name}'
        assert theme_name in shell, f'theme.CSS_VARS no longer declares {theme_name}'
        # Lower case on purpose: both files write hex that way, and an
        # equality check that tolerated case would pass on two spellings
        # of one colour while reporting them as agreeing.
        assert _HEX.match(tokens[token_name]), (
            f'{token_name} is {tokens[token_name]!r}, not a lower-case '
            f'six-digit hex')
        assert shell[theme_name] == tokens[token_name], (
            f'{theme_name} is {shell[theme_name]} but {token_name} is '
            f'{tokens[token_name]}: careeros/web/theme.py and '
            f'frontend/src/design/tokens.css have drifted apart')


def test_every_colour_in_the_shell_palette_comes_from_a_token():
    """The other direction. A hex typed straight into theme.py -- the way a
    palette starts drifting -- has no row in the table and fails here."""
    shell = theme_vars(resolve=False)
    coloured = {name for name, value in shell.items() if value.startswith('#')}
    assert coloured == {theme_name for _, theme_name in MAPPED_COLOURS}


def test_mapped_values_that_are_not_colours_match_tokens_css():
    tokens, shell = light_tokens(), theme_vars()
    for token_name, theme_name in MAPPED_VALUES:
        assert token_name in tokens, f'tokens.css no longer declares {token_name}'
        assert shell[theme_name] == tokens[token_name], (
            f'{theme_name} is {shell[theme_name]!r} but {token_name} is '
            f'{tokens[token_name]!r}')


def test_the_parser_refuses_malformed_input():
    with pytest.raises(AssertionError, match='no :root block found'):
        _block('body { color: red; }', 'scratch')
    with pytest.raises(AssertionError, match='cannot read declaration'):
        _declarations('color: red;', _TOKEN_DECL, 'scratch')
    with pytest.raises(AssertionError, match='declared twice'):
        _declarations('--a: #fff !important; --a: #000 !important;',
                      _TOKEN_DECL, 'scratch')


# --- contrast -------------------------------------------------------------

def relative_luminance(hex_colour):
    """WCAG 2.1 relative luminance of a `#rrggbb` colour."""
    assert _HEX.match(hex_colour), hex_colour
    channels = []
    for offset in (1, 3, 5):
        raw = int(hex_colour[offset:offset + 2], 16) / 255
        channels.append(raw / 12.92 if raw <= 0.03928
                        else ((raw + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(one, other):
    """WCAG 2.1 contrast ratio between two `#rrggbb` colours."""
    first, second = relative_luminance(one), relative_luminance(other)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def test_the_contrast_helper_agrees_with_the_known_extremes():
    assert round(contrast_ratio('#000000', '#ffffff'), 2) == 21.0
    assert round(contrast_ratio('#ffffff', '#ffffff'), 2) == 1.0


@pytest.mark.parametrize('foreground,background', AA_PAIRS)
def test_every_painted_text_pair_clears_aa(foreground, background):
    shell = theme_vars()
    ratio = contrast_ratio(shell[foreground], shell[background])
    assert ratio >= AA_THRESHOLD, (
        f'{foreground} ({shell[foreground]}) on {background} '
        f'({shell[background]}) is {ratio:.2f}:1, under {AA_THRESHOLD}:1')


# --- what the browser receives --------------------------------------------

#: The dark palette CAREER-115 replaced. No served page may carry either
#: value again.
RETIRED_DARK = ('#08090a', '#5e6ad2')

#: Anything that would make a page fetch from somewhere else. The two
#: schemes cover every third-party origin at once, so a font CDN added
#: later fails here without this list having to name it. Asserted over the
#: <head> -- the stylesheet, the @font-face rules and every asset reference
#: the shell owns -- and not over the body, because a page's own copy may
#: legitimately print a URL as text (the Add-a-job field's placeholder
#: shows one, and the postings a board holds are external links by
#: definition).
OFF_SITE = ('http://', 'https://', '//fonts.')


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    app.config['TESTING'] = True
    return app.test_client()


@pytest.fixture
def signed_out_client(tmp_path, raw_session):
    """A client the real gate answers, for the page served without a
    session. `raw_session` (tests/conftest.py) puts the real session
    loader back, which the suite otherwise replaces with a signed-in one;
    GET /login redirects a signed-in caller to the board."""
    app = create_app(tmp_path)
    app.config['TESTING'] = True
    return app.test_client()


def _head(html):
    start, end = html.index('<head>'), html.index('</head>')
    assert end > start, 'the page has no head'
    return html[start:end]


def _assert_light_brand(html):
    for retired in RETIRED_DARK:
        assert retired not in html, f'the retired dark value {retired} is still served'
    assert '#008753' in html, 'the brand green is missing'
    assert '#f6fdf5' in html, 'the page ground is missing'
    head = _head(html)
    for off_site in OFF_SITE:
        assert off_site not in head, f'the shell reaches off site: {off_site}'


def test_the_login_fallback_page_is_light_and_self_contained(signed_out_client):
    """The page a person reaches with no session and no React build."""
    response = signed_out_client.get('/login')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    _assert_light_brand(html)
    # The whole page, not only the head: this one has no record on it and
    # nothing it prints may send a browser anywhere but back here.
    for off_site in OFF_SITE:
        assert off_site not in html, f'the login page reaches off site: {off_site}'
    assert html.count('@font-face') == 2, 'both vendored faces must be declared'
    assert "url('/fonts/atkinson-hyperlegible-latin-400-normal.woff2')" in html
    assert "url('/fonts/atkinson-hyperlegible-latin-700-normal.woff2')" in html
    assert 'Atkinson Hyperlegible' in html


#: The other three pages a person reaches without a session, with the paths
#: that need no live token: an unknown token lands on the shared dead-link
#: page, which is the same shell.
MAILED_LINK_PATHS = ('/forgot-password', '/accept-invite/nosuchtoken',
                     '/reset-password/nosuchtoken')


@pytest.mark.parametrize('path', MAILED_LINK_PATHS)
def test_each_mailed_link_page_is_light_and_self_contained(signed_out_client, path):
    response = signed_out_client.get(path)
    assert response.status_code == 200, path
    html = response.get_data(as_text=True)
    _assert_light_brand(html)
    for off_site in OFF_SITE:
        assert off_site not in html, f'{path} reaches off site: {off_site}'


def test_a_jinja_page_behind_the_gate_is_light_too(client):
    """CSS_VARS is shared, so replacing it relit every server-rendered
    page and not only the four reachable without a session."""
    response = client.get('/jobs')
    assert response.status_code == 200
    _assert_light_brand(response.get_data(as_text=True))


def test_every_var_the_served_stylesheet_names_is_declared(client):
    """A misspelled token is silent in CSS -- the declaration is simply
    dropped and the element falls back to black on transparent. The /jobs
    page carries the shell, the shared controls and its own page CSS, so
    it names more tokens than any other."""
    html = client.get('/jobs').get_data(as_text=True)
    style = html[html.index('<style>'):html.index('</style>')]
    used = set(re.findall(r'var\((--[a-z0-9-]+)\)', style))
    assert used, 'the stylesheet names no tokens at all'
    assert used <= set(theme_vars()), sorted(used - set(theme_vars()))


def test_no_dark_mode_overlay_survives_in_the_served_stylesheet(client):
    """The dark palette washed its surfaces with white at low alpha. On a
    light ground such a wash is invisible, so every one had to be
    re-derived; none may come back."""
    html = client.get('/jobs').get_data(as_text=True)
    style = html[html.index('<style>'):html.index('</style>')]
    assert 'rgba(255,255,255' not in style.replace(' ', '')


def test_the_font_route_serves_both_faces_and_nothing_else(client):
    for name in ('atkinson-hyperlegible-latin-400-normal.woff2',
                 'atkinson-hyperlegible-latin-700-normal.woff2'):
        response = client.get(f'/fonts/{name}')
        assert response.status_code == 200, name
        assert response.get_data()[:4] == b'wOF2', f'{name} is not a woff2 file'
        assert response.mimetype == 'font/woff2', name
        assert 'max-age=31536000' in response.headers.get('Cache-Control', ''), name
        assert 'immutable' in response.headers.get('Cache-Control', ''), name
    # Everything else is a 404 — names that do not exist, traversal shapes,
    # encoded variants, and files that DO exist on disk but are not on the
    # allowlist. The route answers from an exact two-name allowlist before
    # any filesystem lookup happens.
    for path in ('/fonts/missing.woff2', '/fonts/../server.py',
                 '/fonts/..%2F..%2Fcareeros%2Fserver.py',
                 '/fonts/..%252F..%252Fcareeros%252Fserver.py',
                 '/fonts/%2e%2e%2fserver.py',
                 '/fonts/atkinson-hyperlegible-latin-400-normal.woff2%00',
                 '/fonts/',
                 '/fonts/..',
                 '/fonts/README.md',
                 '/fonts/atkinson-hyperlegible-latin-400-normal.woff'):
        response = client.get(path)
        assert response.status_code == 404, path
        assert b'def create_app' not in response.get_data(), path


def test_the_font_route_serves_only_the_allowlisted_vendored_files():
    """A file dropped into the fonts directory is NOT served unless it is
    named in the allowlist — the route serves the two vendored faces and
    nothing else, whatever else the directory happens to hold."""
    from careeros import server
    assert server.FONT_FILES == frozenset({
        'atkinson-hyperlegible-latin-400-normal.woff2',
        'atkinson-hyperlegible-latin-700-normal.woff2',
    })


def test_fonts_is_the_only_addition_to_public_endpoints():
    """The CAREER-115 font route is the sole new entry in
    PUBLIC_ENDPOINTS relative to the pre-change gate set. Any further
    addition must be a deliberate, reviewed change to this test."""
    from careeros import server
    assert server.PUBLIC_ENDPOINTS == frozenset({
        'login', 'health', 'static', 'react_assets',
        'accept_invite', 'forgot_password', 'reset_password',
    }) | {'fonts'}


def test_the_font_route_is_reachable_without_a_session():
    """It is the login page's own asset. A gated font route would leave
    the one page a stranger must be able to read in a fallback face."""
    from careeros import server
    assert 'fonts' in server.PUBLIC_ENDPOINTS


def test_buttons_and_fields_carry_the_sixteen_pixel_rounding():
    from careeros.web import ui
    assert '--radius-control: 16px;' in theme.CSS_VARS
    assert 'border-radius:var(--radius-control);' in ui.CSS
    assert 'border-radius: var(--radius-control);' in theme.BASE_CSS


def test_links_are_the_link_colour_and_underlined():
    assert re.search(r'\na \{[^}]*color: var\(--accent-violet\)[^}]*'
                     r'text-decoration: underline', theme.BASE_CSS)
    assert theme_vars()['--accent-violet'] == '#000000'


def test_focus_rings_use_the_brand_focus_colour():
    from careeros.web import ui
    assert 'outline: 2px solid var(--border-focus)' in theme.BASE_CSS
    assert 'outline:2px solid var(--border-focus)' in ui.CSS
    assert 'var(--accent-indigo); outline-offset' not in theme.BASE_CSS
