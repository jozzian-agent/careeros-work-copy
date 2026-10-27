"""Write docs/as-built/routes.md from the app itself, so the route doc cannot
drift from the routes.

    python scripts/gen_docs.py

The output is fully deterministic: every list is sorted, nothing carries a
timestamp, a line number or an absolute path, and the file names only paths
that are inside this repository. Running the generator twice produces a
byte-identical file, which is what lets CI (the `docs-fresh` job) fail on any
diff.

## What it reads

  * `frontend/src/App.jsx` for the React routes and the page component each
    one renders, and `frontend/src/nav.js` for the main-nav entries.
  * the `frontend/src` modules each page imports, transitively, for the API
    paths that page's code can call.
  * `careeros.server`: the Flask url map of an app built on a throwaway
    vault, and the source of each handler the map points at.

The vault is a fresh `tempfile.mkdtemp()`, never the developer's own: it is
read for nothing, and `create_app` writing a session secret key into it is
why it has to be writable. The React build directory is a throwaway too (one
empty `index.html`), so the generator reports the same routes whether or not
`frontend/dist` has been built.

## How each derived column is derived

**Served when.** The server registers a different `/jobs` renderer depending
on `CAREEROS_REACT_UI` and on whether a React build is present
(`careeros/server.py create_app`), so there is no single url map to read.
The table is the union of both configurations, and the column says which one
a rule needs: `always`, `React UI on`, or `React UI off`.

**Auth level.** `public` when the endpoint is in `careeros.server
PUBLIC_ENDPOINTS`, which is the set the request gate lets through without a
session; `login` otherwise. `login + admin` when the handler's source
(`inspect.getsource`) references `may_edit_shared` or `shared_denied`, the
two readings that decide whether a request may change a company or the tag
vocabulary. The marker says the handler consults the admin rule somewhere,
not that every method on the route is admin-only: a route that reads for
everybody and writes for the admin alone carries it too.

**Response kind.** Read off the same handler source by token. `jsonify`
means JSON; `page_shell`, `render_template`, `send_from_directory` or
`index.html` mean HTML; both groups together mean `HTML + JSON`, which is
the honest answer for a handler that branches on what the caller asked for.
Neither group means `not derived`, and that is where this method stops: a
handler that renders through a helper (`careeros.web.ui.page`, or the mailed
link pages) names none of the tokens in its own source, so it says
`not derived` rather than a guess. `send_from_directory` is counted as HTML
because it is how the single-page shell is served; the rule reads tokens and
not the file that is served, so the two routes that serve build assets
report HTML as well.

**API paths each page names.** For each page component, the generator walks
the relative imports of its module and of every `frontend/src` module those
reach, then collects the string literals that open with `/api/`. A literal
is counted only where the source opens a string with it (`'/api/...'` or a
template literal), which is how every call site in `frontend/src/api` is
written, so prose in a comment and an import specifier contribute nothing.
An interpolated segment is written as the name of the interpolated
expression, for instance `/api/<kind>/<recordId>/notes`: that is the literal
as the source has it, which is why one placeholder can be a record kind
rather than an identifier.

The result is the paths a page has the code to reach, which is an upper bound
on the calls it makes, and the output says so rather than claiming more. A
module is read whole, because the alternative is deciding which exported
function a literal belongs to, and in `frontend/src/api/notes.js` it belongs
to none of them: the path is built in a module-level helper the exported
functions call. So a page that imports one function from
`frontend/src/api/jobs.js` is listed with every path that module names, and a
path reached through a shared component is listed for every page that imports
the component. In the other direction the method has one blind spot, also
stated in the output: a path assembled from pieces rather than written as one
literal is not seen at all.

## Why the parsers abort instead of reporting less

A generated doc that quietly lists nine of eleven routes is worse than no
doc, because nothing says which two are missing. So the JSX and nav parsers
account for every entry: the number of routes parsed out of App.jsx has to
equal the raw count of `<Route` occurrences in it, the number of nav entries
parsed has to equal the raw count of pair literals in nav.js, and every nav
entry has to land on a route that exists. Any shortfall exits non-zero,
naming both counts, or the entry that landed nowhere.
"""
import inspect
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from careeros import server  # noqa: E402

FRONTEND = ROOT / 'frontend' / 'src'
APP_JSX = FRONTEND / 'App.jsx'
NAV_JS = FRONTEND / 'nav.js'
OUT = ROOT / 'docs' / 'as-built' / 'routes.md'

SOURCES = ('frontend/src/App.jsx, frontend/src/nav.js, the frontend/src modules each '
           'page imports, and the url map and handler sources of careeros.server')
HEADER = (f'GENERATED by scripts/gen_docs.py from {SOURCES}. Do not edit. '
          'Regenerate with python scripts/gen_docs.py.')

# The Search tab's page lives at "/", unlike every other tab, whose slug is
# its own URL segment. Mirrored from frontend/src/Nav.jsx, which builds the
# hrefs; nav_routes() below refuses to write a doc where the mirror has gone
# stale, so this is a checked copy rather than a hopeful one.
NAV_ROOT_SLUG = 'search'

JSON_TOKEN = 'jsonify'
HTML_TOKENS = ('page_shell', 'render_template', 'send_from_directory', 'index.html')
ADMIN_TOKENS = ('may_edit_shared', 'shared_denied')

PAGE_IMPORT = re.compile(r"^import\s+([A-Za-z0-9_]+)\s+from\s+'(\./pages/[^']+)';", re.MULTILINE)
# A route tag opening, which the word boundary is the whole point of: the
# `<Routes>` element that wraps them all starts with the same six characters
# and is not a route. Counting the raw text alone would say twelve where
# there are eleven.
ROUTE_TAG = re.compile(r'<Route\b')
ROUTE_PATH = re.compile(r'\bpath="([^"]*)"')
ELEMENT_NAME = re.compile(r'<([A-Z][A-Za-z0-9_]*)')
NAV_PAIR_RAW = re.compile(r"\['[^']*',\s*'[^']*'\],")
NAV_PAIR = re.compile(r"\[\s*'([^']*)'\s*,\s*'([^']*)'\s*\],")
RELATIVE_IMPORT = re.compile(r"from\s+'(\.[^']+)'")
API_LITERAL = re.compile(r"""['"`](/api/(?:\$\{[^{}'"`]*\}|[A-Za-z0-9_\-./?=&<>])*)""")
INTERPOLATION = re.compile(r'\$\{[^{}]*\}')
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def fail(message):
    """Stop with a message and a non-zero exit, which is the only answer to a
    source shape the parsers cannot account for."""
    raise SystemExit(f'gen_docs: {message}')


def route_tags(source):
    """The source text of every `<Route .../>` tag in App.jsx.

    The tag is read by walking it rather than by one regular expression,
    because `element={<Page ...><JobsBoard /></Page>}` holds `/>` of its own:
    the walk closes the tag on the first `/>` that is outside every brace.
    """
    tags, match = [], ROUTE_TAG.search(source)
    while match is not None:
        depth, position, end = 0, match.end(), None
        while position < len(source):
            character = source[position]
            if character == '{':
                depth += 1
            elif character == '}':
                depth -= 1
            elif character == '/' and depth == 0 and source[position + 1:position + 2] == '>':
                end = position + 2
                break
            position += 1
        if end is None:
            fail('a <Route tag in frontend/src/App.jsx is never closed by /> outside a brace')
        tags.append(source[match.start():end])
        match = ROUTE_TAG.search(source, end)
    return tags


def page_modules():
    """The page component modules App.jsx imports, by component name.

    The import statement is also where the page's own file comes from, rather
    than from a guess at its name, which is what the API paths below are
    collected out of.
    """
    modules = {}
    for name, target in PAGE_IMPORT.findall(APP_JSX.read_text()):
        path = (APP_JSX.parent / target).resolve()
        if not path.is_file():
            fail(f'frontend/src/App.jsx imports {name} from {target}, which is not a file')
        modules[name] = path
    return modules


def react_routes():
    """One entry per React route: path and page component.

    The page component of a route is the one element in the tag that App.jsx
    imported from ./pages/. A tag that names no page, or two, is a shape this
    parser does not understand, so it aborts instead of picking one.
    """
    source = APP_JSX.read_text()
    pages = page_modules()
    routes = []
    for tag in route_tags(source):
        paths = ROUTE_PATH.findall(tag)
        if len(paths) != 1:
            fail(f'a <Route tag in frontend/src/App.jsx has {len(paths)} path attributes: {tag}')
        named = [name for name in ELEMENT_NAME.findall(tag)[1:] if name in pages]
        if len(named) != 1:
            fail(f'the <Route tag for {paths[0]} in frontend/src/App.jsx names '
                 f'{len(named)} page components, expected exactly one: {tag}')
        routes.append((paths[0], named[0]))
    raw = len(ROUTE_TAG.findall(source))
    if len(routes) != raw:
        fail(f'frontend/src/App.jsx holds {raw} <Route occurrences but the parser '
             f'accounted for {len(routes)}')
    return sorted(routes)


def nav_entries():
    """The NAV_PAGES entries of nav.js, as (slug, label), in file order."""
    source = NAV_JS.read_text()
    opening = 'export const NAV_PAGES = ['
    start = source.find(opening)
    if start == -1:
        fail(f'frontend/src/nav.js does not hold "{opening}"')
    end = source.find('];', start)
    if end == -1:
        fail('the NAV_PAGES array literal in frontend/src/nav.js is never closed by ];')
    entries = NAV_PAIR.findall(source[start + len(opening):end])
    raw = len(NAV_PAIR_RAW.findall(source))
    if len(entries) != raw:
        fail(f'frontend/src/nav.js holds {raw} nav pair literals but the parser '
             f'accounted for {len(entries)} inside NAV_PAGES')
    return entries


def nav_routes(routes):
    """The nav label of every route that is a main-nav entry, by path.

    Every nav entry has to land on a route that exists: a nav tab whose page
    this doc cannot point at is exactly the kind of silent miss the doc would
    otherwise hide.
    """
    paths = {path for path, _ in routes}
    labels = {}
    for slug, label in nav_entries():
        href = '/' if slug == NAV_ROOT_SLUG else f'/{slug}'
        if href not in paths:
            fail(f'nav entry "{slug}" points at {href}, which no <Route in '
                 'frontend/src/App.jsx answers')
        labels[href] = label
    return labels


def module_graph(entry):
    """Every file under frontend/src that one page module reaches by import."""
    seen, queue = set(), [entry]
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        for target in RELATIVE_IMPORT.findall(path.read_text()):
            resolved = (path.parent / target).resolve()
            for candidate in (resolved, resolved.with_suffix('.js'), resolved.with_suffix('.jsx')):
                if candidate.is_file() and FRONTEND in candidate.parents:
                    queue.append(candidate)
                    break
    return sorted(seen)


def placeholder(match):
    """An interpolated segment, written as the name of what is interpolated.

    The last identifier in the interpolation is the name worth printing:
    `${encodeURIComponent(recordId)}` carries `recordId`, and `${kind}`
    carries `kind`, which is a record kind and not an identifier at all.
    """
    names = IDENTIFIER.findall(match.group(0))
    return f'<{names[-1]}>' if names else '<...>'


def api_paths(page_path):
    """The `/api/...` string literals the page's module graph opens."""
    found = set()
    for path in module_graph(page_path):
        for literal in API_LITERAL.findall(path.read_text()):
            found.add(INTERPOLATION.sub(placeholder, literal))
    return sorted(found)


def flask_rules():
    """Every Flask rule, with the configuration it needs, as a sorted list.

    Two apps, because `/jobs` has two renderers and no single url map holds
    both: the union says which configuration each rule belongs to. Both are
    built on their own throwaway vault, and on a throwaway React build
    directory, so the answer does not depend on the developer's vault, on
    their environment, or on whether frontend/dist exists.
    """
    distribution = Path(tempfile.mkdtemp())
    (distribution / 'index.html').write_text('')
    os.environ['CAREEROS_REACT_DIST'] = str(distribution)
    found = {}
    for flag in ('1', '0'):
        os.environ['CAREEROS_REACT_UI'] = flag
        app = server.create_app(tempfile.mkdtemp())
        for rule in app.url_map.iter_rules():
            entry = found.setdefault((rule.rule, rule.endpoint), {
                'methods': sorted(rule.methods - {'HEAD', 'OPTIONS'}),
                'handler': app.view_functions[rule.endpoint],
                'flags': set(),
            })
            entry['flags'].add(flag)
    rules = []
    for (path, endpoint), entry in sorted(found.items()):
        source = handler_source(entry['handler'])
        rules.append({
            'path': path,
            'endpoint': endpoint,
            'methods': entry['methods'],
            'handler': qualified_name(entry['handler']),
            'served': served_when(entry['flags']),
            'auth': auth_level(endpoint, source),
            'response': response_kind(source),
        })
    return rules


def handler_source(handler):
    """The handler's own source, or nothing when it has none to read."""
    try:
        return inspect.getsource(handler)
    except (OSError, TypeError):
        return ''


def qualified_name(handler):
    module = getattr(handler, '__module__', None) or '?'
    return f'{module}.{getattr(handler, "__name__", "?")}'


def served_when(flags):
    if len(flags) == 2:
        return 'always'
    return 'React UI on' if '1' in flags else 'React UI off'


def auth_level(endpoint, source):
    level = 'public' if endpoint in server.PUBLIC_ENDPOINTS else 'login'
    if any(token in source for token in ADMIN_TOKENS):
        return f'{level} + admin'
    return level


def response_kind(source):
    kinds = []
    if any(token in source for token in HTML_TOKENS):
        kinds.append('HTML')
    if JSON_TOKEN in source:
        kinds.append('JSON')
    return ' + '.join(kinds) if kinds else 'not derived'


def group_of(rule):
    """Which sitemap group a Flask rule belongs to.

    Read off the rule rather than off a list that could go stale: anything
    under /api is the JSON API, anything that serves a file from disk is a
    build asset, and the auth group is every public endpoint left over plus
    /logout, which ends a session it does not need to be public to end.
    """
    if rule['path'].startswith('/api/'):
        return 'api'
    if rule['endpoint'] in ('static', 'react_assets'):
        return 'assets'
    if rule['endpoint'] == 'logout' or rule['endpoint'] in server.PUBLIC_ENDPOINTS:
        return 'auth'
    return 'pages'


def shape(path):
    """A route path with its parameters blanked, so a React path and the
    Flask path that answers it compare equal: /jobs/:id and
    /jobs/<identifier> are both /jobs/{}."""
    return re.sub(r':[A-Za-z0-9_]+|<[^>]+>', '{}', path)


def mermaid_label(text):
    """Text as a Mermaid node label. Angle brackets become Mermaid's own
    numeric entity codes, so a dynamic segment is not read as markup and
    dropped from the rendered diagram."""
    return text.replace('<', '#60;').replace('>', '#62;')


def code(text):
    return f'`{text}`'


def table(columns, rows):
    header = [f'| {" | ".join(columns)} |', f'|{"---|" * len(columns)}']
    return header + [f'| {" | ".join(row)} |' for row in rows]


def react_section(routes, nav):
    lines = [
        '## React routes',
        '',
        'The single-page app owns these paths (frontend/src/App.jsx). The main nav shows '
        'the ones with a label, in the order frontend/src/nav.js NAV_PAGES gives; the rest '
        'are reachable only by a link, a redirect or a typed URL.',
        '',
    ]
    rows = [(code(path), code(component), nav.get(path, 'reachable only'))
            for path, component in routes]
    return lines + table(('Path', 'Page component', 'Main nav'), rows)


def flask_section(rules):
    lines = [
        '## Flask routes',
        '',
        'Every rule the server registers, read from the url map of an app built on a '
        'throwaway vault. HEAD and OPTIONS are left out: Flask adds them to every rule. '
        'The last three columns are derived, by the method the scripts/gen_docs.py '
        'docstring sets out, and read as follows. `always` means the rule is registered '
        'in both configurations of CAREEROS_REACT_UI, and the other two values name the '
        'one configuration that registers it. `login + admin` means the handler consults '
        'the admin rule somewhere, not that every method on the route is admin-only. '
        '`not derived` means the handler names none of the tokens the response rule reads, '
        'which is the answer for a handler that renders through a helper; it does not mean '
        'the route answers nothing. Serving a file from disk counts as HTML, because that '
        'is how the single-page shell is served, so the two asset routes say HTML as well.',
        '',
    ]
    rows = [(code(rule['path']), ', '.join(rule['methods']), code(rule['endpoint']),
             code(rule['handler']), rule['served'], rule['auth'], rule['response'])
            for rule in rules]
    columns = ('Path', 'Methods', 'Endpoint', 'Handler', 'Served when', 'Auth', 'Response')
    return lines + table(columns, rows)


GROUP_TITLES = (
    ('react', 'React routes (frontend/src/App.jsx)'),
    ('pages', 'Flask page routes'),
    ('api', 'Flask JSON API'),
    ('auth', 'Flask auth routes'),
    ('assets', 'Flask build assets'),
)


def sitemap_section(routes, nav, rules):
    """The React routes and the Flask rules as one diagram, with an edge from
    each React route to the Flask rule that answers that path."""
    identifiers, nodes = {}, {key: [] for key, _ in GROUP_TITLES}
    # Node names are the row number in the tables above, zero-padded, so that
    # sorting the edges by name puts them in the order the tables are in.
    for index, (path, component) in enumerate(routes):
        identifiers[('react', path)] = name = f'r{index:02d}'
        tab = f'nav: {nav[path]}' if path in nav else 'reachable only'
        nodes['react'].append(f'    {name}["{mermaid_label(path)} ({tab})"]')
    for index, rule in enumerate(rules):
        identifiers[('flask', rule['path'], rule['endpoint'])] = name = f'f{index:02d}'
        nodes[group_of(rule)].append(
            f'    {name}["{mermaid_label(rule["path"])} ({rule["endpoint"]})"]')
    edges = set()
    for path, _ in routes:
        for rule in rules:
            if shape(rule['path']) == shape(path):
                edges.add((identifiers[('react', path)],
                           identifiers[('flask', rule['path'], rule['endpoint'])]))
    lines = [
        '## Sitemap',
        '',
        'The same two tables as one picture. An arrow is a React route and the Flask rule '
        'that answers requests for that path, matched by path with the parameters blanked, '
        'so `/jobs/:id` meets `/jobs/<identifier>`. A React route with two arrows has a '
        'renderer in each configuration of CAREEROS_REACT_UI.',
        '',
        '```mermaid',
        'flowchart LR',
    ]
    for key, title in GROUP_TITLES:
        lines.append(f'  subgraph {key}["{title}"]')
        lines.extend(nodes[key])
        lines.append('  end')
    lines.extend(f'  {source} --> {target}' for source, target in sorted(edges))
    lines.append('```')
    return lines


def api_section(routes, modules):
    lines = [
        '## API paths the sources behind each React page name',
        '',
        'The `/api/...` string literals in a page component and in every frontend/src '
        'module it imports, directly or through another module. A placeholder carries the '
        'name of the interpolated expression, so `<kind>` is a record kind and '
        '`<recordId>` an identifier. Read this as the paths a page has the code to reach, '
        'not as the calls it makes: a module is read whole, so a page that imports one '
        'function from frontend/src/api/jobs.js is listed with every path that module '
        'names. In the other direction there is one blind spot: a path assembled from '
        'pieces rather than written as one literal is not seen here at all. A page that '
        'opens no such literal anywhere in that graph says so on its row: it reaches the '
        'server by another path, or not at all.',
        '',
    ]
    rows = []
    for component in sorted({component for _, component in routes}):
        paths = api_paths(modules[component])
        if not paths:
            rows.append((code(component), 'no /api path found'))
        rows.extend((code(component), code(path)) for path in paths)
    return lines + table(('Page component', 'API path'), rows)


def document():
    routes = react_routes()
    nav = nav_routes(routes)
    rules = flask_rules()
    modules = page_modules()
    sections = [
        [HEADER],
        ['# As-built routes', '',
         'Every address this app answers on, as the code has it. Each table and the '
         'diagram are read out of the sources named in the first line, which is why this '
         'file is generated rather than written: a route that is added, moved or removed '
         'shows up here on the next run and nowhere else needs editing.'],
        react_section(routes, nav),
        flask_section(rules),
        sitemap_section(routes, nav, rules),
        api_section(routes, modules),
    ]
    return '\n\n'.join('\n'.join(section) for section in sections) + '\n', routes, rules


def main():
    text, routes, rules = document()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, newline='\n')
    print(f'{OUT.relative_to(ROOT)}: {len(routes)} React routes, {len(rules)} Flask rules')


if __name__ == '__main__':
    main()
