"""Write docs/as-built/ from the app itself, so the docs cannot drift from the
code: routes.md from the routes, data.md from the data model, llm.md from the
places that send text to a language model.

    python scripts/gen_docs.py

The output is fully deterministic: every list is sorted, nothing carries a
timestamp, a line number or an absolute path, and the file names only paths
that are inside this repository. Running the generator twice produces
byte-identical files, which is what lets CI (the `docs-fresh` job) fail on any
diff.

## What it reads

  * `frontend/src/App.jsx` for the React routes and the page component each
    one renders, and `frontend/src/Nav.jsx` for the main-nav entries. A nav
    entry names its label by catalog key (CAREER-116), so the word itself is
    read out of `frontend/src/i18n/en.json`.
  * the `frontend/src` modules each page imports, transitively, for the API
    paths that page's code can call.
  * `careeros.server`: the Flask url map of an app built on a throwaway
    vault, and the source of each handler the map points at.
  * `careeros.llm_registry`: the list of the places that send text to a
    language model, and -- for every claim that list makes -- the syntax tree
    of the prompt builder, the sender and the endpoint config function it
    names, plus a canary run of each prompt builder.

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
not the file that is served, so the three asset routes report HTML as well --
including `/fonts/<filename>`, which serves a woff2.

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

## The data model page

docs/as-built/data.md answers a different question off the same app: what the
vault stores, who may read and write each kind of record, and how the kinds
link. It reads `careeros.vault`, `careeros.history`, `careeros.users`,
`careeros.invites`, `careeros.password_reset`, `careeros.ratelimit` and
`careeros.mail`, plus the same url map and handler sources routes.md is built
from, and it derives every column rather than restating a doc.

**Where a kind is stored.** Read out of the function that writes it. The
directory of a numbered kind is a key of `vault.ID_PREFIXES`; the filename is
the f-string the save path builds it with, unparsed from the source and
printed as the expression it is; a single-file kind's name is the operand of
the `Path(root) / ...` expression in its own reader, which resolves a constant
(`vault.ID_COUNTER_FILE`, `ratelimit.STATE_FILE`) to its value.

**Which fields a kind allows.** The allowlist in code, never the fields a
stored record happens to carry: `vault.job_field_names` and
`vault.company_field_names` for the two record kinds that have them, and for
everything else the keys of the `defaults` dict or the record literal its
validator or writer builds, read off the syntax tree. A kind whose writer
checks no field list at all says so. Beside it, where the writer assigns a key
no payload can reach, those fields are listed as the vault's own: a job's
`history` is the clearest case, because it is a stored field that is not in
the write allowlist at all.

**Who may read and write.** One row per route and record kind, over the same
url map routes.md reads. `public` is an endpoint in
`careeros.server PUBLIC_ENDPOINTS`, which the request gate lets through
without a session, with the further gate each of those routes does apply
named beside it (a one-time token, the rate limiter). Everything else needs a
session. For a kind that carries an owner (`vault.OWNER_FIELD`) or an author
(`author_id`), `owner only` is the answer when the handler builds the
ownership scope itself (`session_owner()` or `users.owner(...)`), which is
what every record read is filtered through; a handler that reaches such a
kind without building one would be a route this method cannot classify, and
the generator aborts instead of guessing. For a shared kind the read is every
logged-in user's, and the write is `admin only` when the handler consults the
admin rule (`may_edit_shared`, `shared_denied`) and every logged-in user's
when it does not.

**Which kinds a route touches.** The handler, and every `careeros` function
it reaches through its own globals and closure, resolved name by name off the
syntax tree. That walk is an upper bound in two directions, and the page says
so: a function reached on one branch counts as reached, and a save of one kind
reaches another inside the storage layer (saving a job appends a history
event, can register a proposed tag value, and regenerates the linked company
rollup when `enrich.contributes_to_shared` allows it). The access columns
describe what the gate and the admin rule let through on that route, not that
the route takes a payload for every kind on it. The one blind spot in the
other direction is a call the walk cannot resolve to a function, which is why
the storage symbols behind each row are printed as the row's evidence.

**The status flow.** `vault.STATUSES` is a membership check and nothing more:
`vault._save_record` refuses a status outside the tuple and allows every move
inside it, and the optional ending reason is checked against
`vault.END_REASON_VALUES`, the union of both vocabularies, rather than
against the status the job is in. So there is no transition table to draw.
The diagram draws what the code does enforce -- the status a new record
starts in, and the open/ended split `vault.ENDED_STATUSES` defines -- and the
page states in words that any status may follow any other.

## How the model page is derived

`careeros.llm_registry` lists the call sites; everything the page prints
about one is read out of the code it names, and a disagreement is an abort.

**Fields placed in the prompt.** Two readings, held against each other. The
first walks the prompt builder's syntax tree and collects every string-literal
key it reads off each of its own parameters, following the taint through
assignment, iteration, `or`, the f-strings and joins a prompt is built with,
and into a call to another function of the same module (both product builders
delegate a stretch of the prompt to one). A key read off a parameter that the
registry does not list is an abort. The second CALLS the builder, once per
field of the stored kind it is handed, with a canary record whose every value
is a sentinel naming its own key -- so which stored fields reach a prompt is
read off the rendered prompt itself, through the real adapter
(`careeros.classify.from_vault_job`), including the fields that only arrive
when another is empty. One call site has no record parameter at all: job
extraction is handed a string by five different routes, so its stored field is
the registry's own claim, and what the generator checks there is that the
builder reads no key off that parameter -- nothing but the text it is given
can enter.

**Fields never sent.** The allowlists of the stored kinds
`llm_registry.USER_DATA_KINDS` names, minus every field the readings above
found in any prompt. Each one is then shown absent rather than assumed
absent: a field of a kind a call site is handed must have its sentinel
missing from that call site's own canary run, and a kind no call site is
handed cannot contribute a field to one. A field that can be shown neither
way is an abort.

**Trigger.** The routes are the url map routes.md reads, filtered by the same
call-graph walk the data-model page's kinds column uses: a rule is a trigger
when its handler reaches the call site's marker function. The scripts are
`scripts/*.py` (never this generator, which imports the app in order to read
it), filtered twice over: the script has to reach the sender AND name the
module the sender lives in. The second half is what separates
`scripts/run_classification.py`, which imports `careeros.classify.llm` and
has a `--layer llm` for it, from `scripts/classification_report.py`, which
reaches the same function through `classify.classify` but names only
`careeros.classify` and passes `layer='rules'`. A shell script in `scripts/`
or `deploy/` that names a triggering script is reported too; whether a cron
entry runs that shell script is not a fact in this repository.

**Size limit.** The slices the prompt builder and the senders really apply:
an `ast.Slice` whose upper bound is a module constant, printed with the value
that constant holds on this run. No slice means no limit, and the page says
so.

**Gate flag and endpoint variables.** Both read as environment reads: every
`get` on a name that is, or was assigned from, something ending in `environ`,
inside the function the registry names and the functions of its own module it
calls. The gate function of a call site with no gate has to read no variable
at all. A variable the scan finds that the registry does not list, or the
other way round, is an abort.

**Leaves the server.** Derived from the default the config function falls back
to for the one variable that decides the address. Where there is a default,
its host is parsed and tested with `ipaddress`: a private address is
`no (LAN) unless <variable> points elsewhere`, a public one says so and names
it. Where the code has NO default -- `careeros.llm_client.get_llm_client`
raises instead -- the endpoint cannot be determined from the code at all, so
the page names the variable that decides it and says the value is whatever
that variable is configured to. The one thing on the page that is not read out
of the code is the parenthesis naming what the owner has configured that
variable to, and the page labels it as owner-supplied.

## Why the parsers abort instead of reporting less

A generated doc that quietly lists nine of eleven routes is worse than no
doc, because nothing says which two are missing. So the JSX and nav parsers
account for every entry: the number of routes parsed out of App.jsx has to
equal the raw count of `<Route` occurrences in it, the number of nav entries
parsed has to equal the raw count of pair literals in Nav.jsx, every nav
label has to be a key the catalog answers, and every nav entry has to land on
a route that exists. Any shortfall exits non-zero, naming both counts, the
key nothing answered, or the entry that landed nowhere.

The data model page is held to the same rule, over the lists a reader could
check by counting: the number of history event types parsed has to equal the
raw count of the registry's own keys, the number of job statuses parsed has
to equal the raw count of items in the tuple literal, and the permissions
matrix has to account for every rule in the url map routes.md reports. Any
shortfall exits non-zero, naming both counts.
"""
import ast
import importlib
import inspect
import ipaddress
import json
import os
import re
import sys
import tempfile
import textwrap
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from careeros import server  # noqa: E402
from careeros import history, invites, mail, password_reset, ratelimit, users, vault  # noqa: E402
from careeros import llm_registry  # noqa: E402
from careeros import tokens as link_tokens  # noqa: E402

FRONTEND = ROOT / 'frontend' / 'src'
APP_JSX = FRONTEND / 'App.jsx'
NAV_JSX = FRONTEND / 'Nav.jsx'
CATALOG = FRONTEND / 'i18n' / 'en.json'
OUT = ROOT / 'docs' / 'as-built' / 'routes.md'
DATA_OUT = ROOT / 'docs' / 'as-built' / 'data.md'
LLM_OUT = ROOT / 'docs' / 'as-built' / 'llm.md'

SOURCES = ('frontend/src/App.jsx, frontend/src/Nav.jsx, frontend/src/i18n/en.json, the '
           'frontend/src modules each page imports, and the url map and handler sources '
           'of careeros.server')
HEADER = (f'GENERATED by scripts/gen_docs.py from {SOURCES}. Do not edit. '
          'Regenerate with python scripts/gen_docs.py.')

# The modules the data model page is read out of, named here once so the
# header cannot name a module the generator does not open.
DATA_MODULES = (vault, history, users, invites, password_reset, link_tokens, ratelimit, mail)
DATA_SOURCES = (', '.join(module.__name__ for module in DATA_MODULES)
                + ', and the url map and handler sources of careeros.server')
DATA_HEADER = (f'GENERATED by scripts/gen_docs.py from {DATA_SOURCES}. Do not edit. '
               'Regenerate with python scripts/gen_docs.py.')

LLM_SOURCES = ('careeros.llm_registry, the syntax trees of the prompt builders, senders and '
               'endpoint config functions it names, a canary run of each of those prompt '
               'builders, the stored field allowlists data.md is read out of, the url map and '
               'handler sources of careeros.server, and the scripts in scripts/ and deploy/')
LLM_HEADER = (f'GENERATED by scripts/gen_docs.py from {LLM_SOURCES}. Do not edit. '
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
# A nav pair in Nav.jsx: the slug, then the <FormattedMessage> that renders
# its label. The id is matched out of the element rather than the element
# being parsed, which is all this doc needs and all a regex should attempt.
NAV_PAIR_RAW = re.compile(r"\['[^']*',\s*<FormattedMessage\b[^>]*/>\],")
NAV_PAIR = re.compile(r"\[\s*'([^']*)'\s*,\s*<FormattedMessage\b[^>]*\bid=\"([^\"]*)\"[^>]*/>\s*\],")
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
    """The NAV_PAGES entries of Nav.jsx, as (slug, label), in file order.

    Nav.jsx names a label by catalog key, so the word a reader sees comes out
    of frontend/src/i18n/en.json. A key the catalog does not answer aborts:
    the tab would render its own id in the browser too, and a doc quietly
    printing the id instead of the word is the silent miss this generator
    exists to refuse.
    """
    source = NAV_JSX.read_text()
    opening = 'const NAV_PAGES = ['
    start = source.find(opening)
    if start == -1:
        fail(f'frontend/src/Nav.jsx does not hold "{opening}"')
    end = source.find('];', start)
    if end == -1:
        fail('the NAV_PAGES array literal in frontend/src/Nav.jsx is never closed by ];')
    pairs = NAV_PAIR.findall(source[start + len(opening):end])
    raw = len(NAV_PAIR_RAW.findall(source))
    if len(pairs) != raw:
        fail(f'frontend/src/Nav.jsx holds {raw} nav pair literals but the parser '
             f'accounted for {len(pairs)} inside NAV_PAGES')
    catalog = json.loads(CATALOG.read_text())
    entries = []
    for slug, key in pairs:
        if key not in catalog:
            fail(f'nav entry "{slug}" labels itself {key!r}, which '
                 'frontend/src/i18n/en.json does not hold')
        entries.append((slug, catalog[key]))
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
            # The handler itself, which the data model page walks for the
            # record kinds the route can reach; routes.md prints its name.
            'function': entry['handler'],
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
    under /api is the JSON API, anything that serves a file from disk is an
    asset, and the auth group is every public endpoint left over plus
    /logout, which ends a session it does not need to be public to end.
    """
    if rule['path'].startswith('/api/'):
        return 'api'
    if rule['endpoint'] in ('static', 'react_assets', 'fonts'):
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
        'the ones with a label, in the order frontend/src/Nav.jsx NAV_PAGES gives; the rest '
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
        'is how the single-page shell is served, so the three asset routes say HTML as well, '
        'including the one that serves a woff2.',
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
    ('assets', 'Flask asset routes'),
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


# --- The data model page -------------------------------------------------

#: Every storage symbol the route walk recognises, as the record kind it
#: touches and whether the touch is a read or a write. This is the map that
#: turns "the handler can reach this function" into "the route can read that
#: kind", so a storage function missing from it would be a kind missing from
#: the matrix: `check_storage_map` below refuses to write a doc where one of
#: the vault's or the accounts module's own load/save/list/delete functions
#: is not named here.
STORAGE_SYMBOLS = {
    'careeros.vault.list_jobs': ('jobs', 'read'),
    'careeros.vault.list_owned_jobs': ('jobs', 'read'),
    'careeros.vault.list_universe_jobs': ('jobs', 'read'),
    'careeros.vault.load_job': ('jobs', 'read'),
    'careeros.vault.load_universe_job': ('jobs', 'read'),
    'careeros.vault.save_job': ('jobs', 'write'),
    'careeros.vault.delete_job': ('jobs', 'write'),
    'careeros.vault.add_job_to_board': ('jobs', 'write'),
    'careeros.vault.save_watch_result': ('jobs', 'write'),
    'careeros.vault.list_companies': ('companies', 'read'),
    'careeros.vault.visible_companies': ('companies', 'read'),
    'careeros.vault.reader_company': ('companies', 'read'),
    'careeros.vault.may_see_company': ('companies', 'read'),
    'careeros.vault.load_company': ('companies', 'read'),
    'careeros.vault.linkable_company': ('companies', 'read'),
    'careeros.vault.save_company': ('companies', 'write'),
    'careeros.vault.delete_company': ('companies', 'write'),
    'careeros.vault.retire_company': ('companies', 'write'),
    'careeros.vault.list_experiences': ('experiences', 'read'),
    'careeros.vault.load_experience': ('experiences', 'read'),
    'careeros.vault.save_experience': ('experiences', 'write'),
    'careeros.vault.delete_experience': ('experiences', 'write'),
    'careeros.vault.notes_view': ('notes', 'read'),
    'careeros.vault.notes_payload': ('notes', 'read'),
    'careeros.vault.has_notes': ('notes', 'read'),
    'careeros.vault.new_note': ('notes', 'write'),
    'careeros.vault.edit_note': ('notes', 'write'),
    'careeros.history.resolve': ('history events', 'read'),
    'careeros.history.label_for': ('history events', 'read'),
    'careeros.vault.append_event': ('history events', 'write'),
    'careeros.vault.load_search': ('search criteria', 'read'),
    'careeros.vault.save_search': ('search criteria', 'write'),
    'careeros.vault.load_tags': ('tags', 'read'),
    'careeros.vault.known_function_ids': ('tags', 'read'),
    'careeros.vault.function_facet_options': ('tags', 'read'),
    'careeros.vault.function_label_map': ('tags', 'read'),
    'careeros.vault.tag_label_map': ('tags', 'read'),
    'careeros.vault.unregistered_tags': ('tags', 'read'),
    'careeros.vault.save_tags': ('tags', 'write'),
    'careeros.vault.validate_tags': ('tags', 'write'),
    'careeros.vault.seed_function_facet': ('tags', 'write'),
    'careeros.users.find_by_email': ('users', 'read'),
    'careeros.users.load_user': ('users', 'read'),
    'careeros.users.list_users': ('users', 'read'),
    'careeros.users.admins': ('users', 'read'),
    'careeros.users.authenticate': ('users', 'read'),
    'careeros.users.save_user': ('users', 'write'),
    'careeros.users.create_user': ('users', 'write'),
    'careeros.users.set_password': ('users', 'write'),
    'careeros.users.set_disabled': ('users', 'write'),
    'careeros.users.bump_session_epoch': ('users', 'write'),
    'careeros.users.secret_key': ('session signing key', 'write'),
    # The allocator, by the functions a caller outside it uses. Its two
    # internal readers (`_highest_allocated`, and `is_reserved`, which every
    # record read goes through to skip a tombstone) are deliberately absent:
    # they would put an id-counter read on nearly every route in the matrix
    # and say nothing a reader of this page can act on.
    'careeros.vault.next_job_id': ('id counters', 'read'),
    'careeros.vault.next_company_id': ('id counters', 'read'),
    'careeros.vault.next_id': ('id counters', 'read'),
    'careeros.vault._allocate': ('id counters', 'write'),
    'careeros.vault.retain_id_high_water': ('id counters', 'write'),
    'careeros.vault.initialize_id_counters': ('id counters', 'write'),
    'careeros.vault.reserve_id': ('id reservations', 'write'),
    'careeros.invites.load': ('invites', 'read'),
    'careeros.invites.create_invite': ('invites', 'write'),
    'careeros.invites.accept': ('invites', 'write'),
    'careeros.password_reset.load': ('password resets', 'read'),
    'careeros.password_reset.request_reset': ('password resets', 'write'),
    'careeros.password_reset.complete_reset': ('password resets', 'write'),
    'careeros.ratelimit.check': ('rate-limit windows', 'read'),
    'careeros.ratelimit.allowed': ('rate-limit windows', 'read'),
    'careeros.ratelimit.hit': ('rate-limit windows', 'write'),
    'careeros.ratelimit.register': ('rate-limit windows', 'write'),
    'careeros.mail.sent_today': ('mail send count', 'read'),
    'careeros.mail.send': ('mail send count', 'write'),
}

#: The three readings of the signed-in user that are the request gate. The
#: walk neither enters them nor records what they read: every route that is
#: not public reads the session user's own record (`careeros.server
#: require_login`), and saying that once on the page is worth more than the
#: same row on all 44 of them.
GATE_SYMBOLS = ('careeros.users.session_user', 'careeros.users.owner',
                'careeros.users.is_admin')

#: What building the ownership scope looks like in a handler: `users.owner`
#: itself, and the `session_owner` helper every API route in create_app calls
#: it through. Matched by name, and checked against the code below, which is
#: what keeps this a read of the two helpers rather than a hopeful list.
OWNER_SCOPE_NAMES = ('owner', 'session_owner')

#: Whose note one is (CAREER-41). Mirrored from the field vault.Owner reads,
#: and checked against that method's source.
AUTHOR_FIELD = 'author_id'

#: The modules whose functions count as the route's own code rather than as
#: the storage layer underneath it, which is the line the ownership-scope
#: reading is taken on.
ROUTE_LAYER = ('careeros.server', 'careeros.web')

#: The kinds that live inside another kind's field rather than in a file of
#: their own, as (container, contained, field). Checked below against the
#: functions that read and write the field.
CONTAINED_KINDS = (('jobs', 'notes', 'note_list'),
                   ('companies', 'notes', 'note_list'),
                   ('jobs', 'history events', 'history'))

#: A link field whose name does not carry the kind it points at. All three
#: hold a user record id: `vault.OWNER_FIELD`, the `author_id` that
#: `vault.Owner.owns_note` compares, and the `user_id` a reset record names
#: its account by. Each is checked against the code that reads it below.
NAMED_LINKS = {vault.OWNER_FIELD: 'users', AUTHOR_FIELD: 'users', 'user_id': 'users'}

_TREES = {}
#: Parsed definitions and resolved references, per function. The walk below
#: visits the same storage function from every route that reaches it, and
#: the parse is the expensive part: without these two caches the generator
#: re-parses careeros/server.py some twelve thousand times.
_NODES = {}
_REFERENCES = {}


def module_tree(filename):
    """The parsed source of one module, once per run."""
    tree = _TREES.get(filename)
    if tree is None:
        tree = _TREES[filename] = ast.parse(Path(filename).read_text())
    return tree


def function_key(function):
    return f'{getattr(function, "__module__", "?")}.{getattr(function, "__qualname__", "?")}'


def definition_key(function):
    """Where a function is defined, which is what tells two of them apart.

    The qualified name does not: every lambda in `create_app` is called
    `create_app.<locals>.<lambda>`, and the react page renderers and the
    notes table's loaders are all lambdas there. Keying the walk and its
    caches on the definition site is what keeps one lambda's references
    from being answered with another's.
    """
    return (function.__code__.co_filename, function.__code__.co_firstlineno)


def short_name(key):
    """A storage symbol as the page prints it: `vault.load_job`."""
    return key.removeprefix('careeros.')


def nodes_of(function):
    """The definition nodes of one function, found by the line it starts on.

    The module is parsed rather than the function's own source, because a
    lambda inside a dict literal has no source of its own that parses, and
    the two notes endpoints read their loader out of exactly such a table
    (`careeros.server NOTE_KINDS`). A line that holds more than one
    definition yields all of them, which is a superset of the one asked for
    and never a wrong pick.
    """
    line = function.__code__.co_firstlineno
    cached = _NODES.get(definition_key(function))
    if cached is not None:
        return cached
    nodes = []
    for node in ast.walk(module_tree(function.__code__.co_filename)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        starts = [node.lineno] + [item.lineno for item in getattr(node, 'decorator_list', [])]
        if line in starts:
            nodes.append(node)
    if not nodes:
        fail(f'{function_key(function)} starts on a line of '
             f'{Path(function.__code__.co_filename).name} that holds no definition')
    _NODES[definition_key(function)] = nodes
    return nodes


def dotted_name(node):
    """The dotted name an expression reads, or None when it is not one."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f'{base}.{node.attr}' if base else None
    return None


def scope_of(function):
    """The names one function can resolve: its module's globals, plus the
    closure it was built in, which is where every create_app handler finds
    the gate helpers and the notes table."""
    scope = dict(getattr(function, '__globals__', {}))
    try:
        scope.update(inspect.getclosurevars(function).nonlocals)
    except TypeError:
        pass
    return scope


def resolve(scope, name):
    """What one dotted name is, or None when this run cannot say.

    A name that cannot be read outside a request answers None rather than
    raising: Flask's `request` is a proxy that asks for a live request on
    every attribute, and a handler names it constantly.
    """
    parts = name.split('.')
    if parts[0] not in scope:
        return None
    value = scope[parts[0]]
    for part in parts[1:]:
        try:
            value = getattr(value, part, None)
        except Exception:
            return None
        if value is None:
            return None
    return value


def functions_in(value):
    """The careeros functions one resolved name holds.

    A name can be the function itself, or a container of them: the notes
    endpoints reach their loader and their saver through a dict of tuples,
    and a table like that is the only place some storage symbols are named.
    """
    if inspect.isfunction(value):
        module = getattr(value, '__module__', '') or ''
        return [value] if module.split('.')[0] == 'careeros' else []
    if isinstance(value, (tuple, list, frozenset, set)):
        return [found for item in value for found in functions_in(item)]
    if isinstance(value, dict):
        return [found for item in value.values() for found in functions_in(item)]
    return []


def imported_names(node):
    """The names one function imports inside its own body.

    Several modules import the vault from inside a function rather than at
    the top of the file (`careeros.enrich` does it six times, and
    `vault._save_record` reaches the watcher and the company rollup the same
    way), so a walk that read only module globals would stop at exactly the
    functions that write the most.
    """
    names = {}
    for child in ast.walk(node):
        if isinstance(child, ast.ImportFrom) and child.module:
            module = import_module(child.module)
            for alias in child.names:
                value = (getattr(module, alias.name, None)
                         or import_module(f'{child.module}.{alias.name}'))
                if value is not None:
                    names[alias.asname or alias.name] = value
        elif isinstance(child, ast.Import):
            for alias in child.names:
                value = import_module(alias.name)
                if value is not None:
                    names[alias.asname or alias.name.split('.')[0]] = value
    return names


def import_module(name):
    """One module, or None when this run cannot import it."""
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def references(function):
    """Every careeros function one function names, by resolving each dotted
    name in its source against what that function can see."""
    cached = _REFERENCES.get(definition_key(function))
    if cached is not None:
        return cached
    scope = scope_of(function)
    found = {}
    for node in nodes_of(function):
        scope = dict(scope, **imported_names(node))
        for child in ast.walk(node):
            if isinstance(child, (ast.Name, ast.Attribute)):
                name = dotted_name(child)
            elif isinstance(child, ast.Subscript):
                name = dotted_name(child.value)
            else:
                continue
            if not name:
                continue
            for reached in functions_in(resolve(scope, name)):
                # By definition site, not by name: the notes table holds two
                # lambdas that share one qualified name, and one of them
                # would otherwise take the other's place here.
                found[definition_key(reached)] = reached
    resolved = [found[key] for key in sorted(found)]
    _REFERENCES[definition_key(function)] = resolved
    return resolved


def layer_of(function):
    """Whether a function is the route's own code or the storage layer."""
    module = getattr(function, '__module__', '') or ''
    return 'route code' if module.startswith(ROUTE_LAYER) else 'storage layer'


def builds_owner_scope(function):
    """Whether this function builds the ownership scope a private read is
    filtered through (`users.owner`, or create_app's `session_owner`)."""
    for node in nodes_of(function):
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = dotted_name(child.func)
                if name and name.split('.')[-1] in OWNER_SCOPE_NAMES:
                    return True
    return False


def route_touches(handler):
    """What one route reaches: the record kinds, and whether it scopes.

    Returns the kinds touched (each with the storage symbols behind the
    touch and whether they were reached from the route's own code or from
    the storage layer), the set of every function key reached, and whether
    the route's own code builds the ownership scope.
    """
    seen, queue, kinds, reached, scoped = set(), [handler], {}, set(), False
    while queue:
        function = queue.pop()
        key = definition_key(function)
        if key in seen:
            continue
        seen.add(key)
        layer = layer_of(function)
        if layer == 'route code' and builds_owner_scope(function):
            scoped = True
        for target in references(function):
            target_key = function_key(target)
            reached.add(target_key)
            entry = STORAGE_SYMBOLS.get(target_key)
            if entry is not None:
                kind, access = entry
                touch = kinds.setdefault(kind, {'read': set(), 'write': set(), 'layers': set()})
                touch[access].add(short_name(target_key))
                touch['layers'].add(layer)
            if target_key not in GATE_SYMBOLS:
                queue.append(target)
    return kinds, reached, scoped


def check_storage_map():
    """Refuse to write the page when the map above has gone stale.

    Both directions. Every symbol named in it has to exist, so a renamed
    function is an abort rather than a kind that quietly stops being
    reported; and every load/save/list/delete function of the two storage
    modules has to be named in it or be part of the request gate, so a new
    one cannot arrive without a decision about which kind it touches.
    """
    for key in sorted(STORAGE_SYMBOLS):
        module_name, _, name = key.rpartition('.')
        module = sys.modules.get(module_name)
        if module is None or not callable(getattr(module, name, None)):
            fail(f'STORAGE_SYMBOLS names {key}, which is not a function of {module_name}')
    known = set(STORAGE_SYMBOLS) | set(GATE_SYMBOLS)
    for module in (vault, users):
        for name in sorted(dir(module)):
            if not re.match(r'^(load|save|list|delete)_', name):
                continue
            if not callable(getattr(module, name)):
                continue
            key = f'{module.__name__}.{name}'
            if key not in known:
                fail(f'{key} stores or reads records and is named in neither '
                     'STORAGE_SYMBOLS nor GATE_SYMBOLS')


def check_token(description, function, token, present=True):
    """Hold one sentence of the page against the code it claims to read.

    The page says a handful of things no list in the code states outright:
    that a note lives under `note_list`, that a status move is not what
    allows an ending reason. Each is a token that has to be in (or out of)
    one function's source, and a mismatch is an abort, so the sentence is a
    checked reading and not a hopeful one.
    """
    source = inspect.getsource(function)
    if (token in source) is not present:
        where = 'no longer names' if present else 'now names'
        fail(f'{function_key(function)} {where} {token}, so the page can no longer '
             f'say: {description}')


def constant_value(function, node):
    """A literal, or the value of a module constant the source names."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return getattr(sys.modules[function.__module__], node.id, None)
    return None


def vault_file(function):
    """The vault-relative file one single-file kind lives in, read off the
    `Path(root) / ...` expression in the function that opens it."""
    for node in nodes_of(function):
        for child in ast.walk(node):
            if (isinstance(child, ast.BinOp) and isinstance(child.op, ast.Div)
                    and ast.unparse(child.left) == 'Path(root)'):
                value = constant_value(function, child.right)
                if isinstance(value, str):
                    return value
    fail(f'{function_key(function)} holds no Path(root) / "..." expression to '
         'read a storage location out of')


def yaml_filename(function):
    """The f-string one writer names a .yaml file with, as the source has it.

    Printed as the expression rather than as a shape somebody retyped: the
    filename of a record is `slugify` of its title or name and its own id,
    and that is exactly what the reader of this page should see.
    """
    found = set()
    for node in nodes_of(function):
        for child in ast.walk(node):
            if isinstance(child, ast.JoinedStr):
                text = ast.unparse(child)
                if text.endswith(('.yaml"', ".yaml'")):
                    found.add(text)
    if len(found) != 1:
        fail(f'{function_key(function)} builds {len(found)} .yaml filenames, '
             'expected exactly one')
    return found.pop()


def dict_keys(function, variable=None):
    """The keys of the dict a validator or a writer builds.

    Either the one assigned to `variable` (a validator's `defaults`), or
    every dict literal in the function when the dict is handed straight to
    the vault (a token record, the mail tally). Both `{'a': 1}` and
    `dict(a=1)` are read, and a key the source writes as a constant name is
    resolved to its value.
    """
    found = []
    for node in nodes_of(function):
        for child in ast.walk(node):
            if isinstance(child, (ast.Assign, ast.AnnAssign)) and variable is not None:
                # An annotated assignment (`defaults: dict = dict(...)`) carries
                # one target rather than a list of them, and users.validate_user
                # writes its allowlist that way.
                targets = ([child.target] if isinstance(child, ast.AnnAssign)
                           else child.targets)
                if [target.id for target in targets
                        if isinstance(target, ast.Name)] != [variable]:
                    continue
                found.extend(literal_keys(function, child.value))
            elif variable is None and isinstance(child, (ast.Dict, ast.Call)):
                found.extend(literal_keys(function, child))
    keys = sorted(set(found))
    if not keys:
        fail(f'{function_key(function)} builds no dict this parser can read keys '
             f'out of (variable {variable})')
    return keys


def literal_keys(function, node):
    """The keys of one dict literal or one dict(...) call."""
    if isinstance(node, ast.Dict):
        return [value for value in (constant_value(function, key) for key in node.keys)
                if isinstance(value, str)]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'dict'):
        return [keyword.arg for keyword in node.keywords if keyword.arg]
    return []


def assigned_keys(function, variable, branch=None):
    """The keys one function assigns on a dict variable, by constant key.

    These are the fields no payload can set, because the writer sets them
    itself: a job's `history` and `status_changed`, a record's own `id`.

    `branch` reads the one writer that does two kinds. `vault._save_record`
    saves jobs and companies in one function, so an assignment inside
    `if job:` belongs to the job half, one inside `if not job:` to the
    company half, and one outside both to either; anything nested deeper
    carries the tests it sits under, so a condition inside the job branch
    is still the job branch.
    """
    found = {}

    def record(statement, tests):
        for target in getattr(statement, 'targets', ()):
            if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                    and target.value.id == variable):
                key = constant_value(function, target.slice)
                if isinstance(key, str):
                    found.setdefault(key, tests)

    def walk(statements, tests):
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(statement, ast.If):
                test = ast.unparse(statement.test)
                walk(statement.body, tests + (test,))
                walk(statement.orelse, tests + (f'not ({test})',))
                continue
            record(statement, tests)
            for name in ('body', 'orelse', 'finalbody'):
                nested = getattr(statement, name, None)
                if isinstance(nested, list):
                    walk([item for item in nested if isinstance(item, ast.stmt)], tests)
            for item in getattr(statement, 'handlers', ()):
                walk(item.body, tests)

    for node in nodes_of(function):
        walk(node.body if isinstance(node.body, list) else [], ())
    # `if job:` reads as "job" and `if not job:` as either "not job" or
    # "not (job)", depending on whether the branch is an elif of the first
    # one, so both spellings are compared without their spaces and brackets.
    plain = {key: {test.replace(' ', '').replace('(', '').replace(')', '')
                   for test in tests} for key, tests in found.items()}
    if branch == 'job':
        return sorted(key for key in found if 'notjob' not in plain[key])
    if branch == 'company':
        return sorted(key for key in found if 'job' not in plain[key])
    return sorted(found)


def raw_tuple_count(module, name):
    """How many quoted items a tuple literal holds, counted in the raw text.

    The count the parsed tuple is held against: a vocabulary that grows by
    one while this doc reports the old length is exactly the silent miss
    the generator exists to refuse.
    """
    match = re.search(rf'^{name} = \((.*?)\)', inspect.getsource(module), re.S | re.M)
    if match is None:
        fail(f'{module.__name__} holds no "{name} = (" tuple literal')
    return len(re.findall(r"'[^']*'", match.group(1)))


def raw_registry_count():
    """The raw count of the history registry's own top-level keys."""
    source = inspect.getsource(history)
    start = source.find('REGISTRY = {')
    end = source.find('\n}', start)
    if start == -1 or end == -1:
        fail('careeros.history holds no REGISTRY = { ... } literal')
    return len(re.findall(r"^    '[a-z_]+':", source[start:end], re.M))


def check_count(what, parsed, raw):
    if parsed != raw:
        fail(f'{what}: the parser accounted for {parsed} but the source holds {raw}')


def kind_fields():
    """Every field each record kind allows, from the allowlist in code.

    The job and company allowlists are the two the vault publishes
    (`job_field_names`, `company_field_names`, which both read
    `_record_defaults`). Everything else is the `defaults` dict or the
    record literal its own validator or writer builds, read off the syntax
    tree. Two kinds have no field list in code at all and say so with an
    empty tuple: the tag vocabulary, whose writer checks one key and stores
    the object it was given, and the signing key, which is not a mapping.
    """
    user_fields = set(dict_keys(users.validate_user, 'defaults'))
    user_fields.update(assigned_keys(users.validate_user, 'defaults'))
    return {
        'jobs': tuple(sorted(vault.job_field_names())),
        'companies': tuple(sorted(vault.company_field_names())),
        'experiences': tuple(dict_keys(vault.validate_experience, 'defaults')),
        'notes': tuple(sorted(vault.NOTE_FIELDS)),
        'history events': tuple(dict_keys(vault.append_event, 'entry')),
        'search criteria': tuple(sorted(vault.blank_search())),
        'tags': (),
        'users': tuple(sorted(user_fields)),
        'invites': tuple(sorted(set(dict_keys(invites.create_invite, 'record'))
                                | set(assigned_keys(link_tokens.consume, 'record')))),
        'password resets': tuple(sorted(set(dict_keys(password_reset.request_reset, 'record'))
                                        | set(assigned_keys(link_tokens.consume, 'record')))),
        'rate-limit windows': tuple(dict_keys(ratelimit.hit)),
        'mail send count': tuple(dict_keys(mail._record_sent)),
        'id counters': tuple(sorted(vault.ID_PREFIXES)),
        'id reservations': tuple(dict_keys(vault.reserve_id)),
        'session signing key': (),
    }


FIELD_SOURCES = {
    'jobs': 'vault.job_field_names',
    'companies': 'vault.company_field_names',
    'experiences': 'vault.validate_experience defaults',
    'notes': 'vault.NOTE_FIELDS',
    'history events': 'vault.append_event entry',
    'search criteria': 'vault.blank_search',
    'tags': 'no allowlist found in code: vault.save_tags requires a facets object '
            'and stores what it is given',
    'users': 'users.validate_user defaults',
    'invites': 'invites.create_invite record, plus tokens.consume',
    'password resets': 'password_reset.request_reset record, plus tokens.consume',
    'rate-limit windows': 'ratelimit.hit',
    'mail send count': 'mail._record_sent',
    'id counters': 'vault.ID_PREFIXES',
    'id reservations': 'vault.reserve_id',
    'session signing key': 'not a mapping: users.secret_key writes one value',
}


def kind_locations():
    """Where each kind is stored, read off the function that writes it."""
    numbered = {kind: f'`{kind}/`, one file per record, named '
                      f'`{yaml_filename(writer)}`'
                for kind, writer in (('jobs', vault._save_record),
                                     ('companies', vault._save_record),
                                     ('experiences', vault.save_experience),
                                     ('users', users.save_user))}
    for kind in numbered:
        if kind not in vault.ID_PREFIXES:
            fail(f'{kind} is not a key of vault.ID_PREFIXES')
    cap = re.search(r'\[-(\d+):\]', inspect.getsource(vault.append_event))
    if cap is None:
        fail('vault.append_event no longer caps the history list, so the page '
             'cannot say how many entries a job keeps')
    return numbered | {
        'notes': 'inside `note_list` on a job or a company record',
        'history events': f'inside `history` on a job record, the latest '
                          f'{cap.group(1)} entries',
        'search criteria': f'`{vault_file(vault.load_search)}`',
        'tags': f'`{vault_file(vault.load_tags)}`',
        'invites': f'`{invites.FOLDER}/`, one file per token, named '
                   f'`{yaml_filename(link_tokens.storage_path)}`',
        'password resets': f'`{password_reset.FOLDER}/`, one file per token, named '
                           f'`{yaml_filename(link_tokens.storage_path)}`',
        'rate-limit windows': f'`{vault_file(ratelimit.hit)}`',
        'mail send count': f'`{vault_file(mail._record_sent)}`',
        'id counters': f'`{vault_file(vault._allocate)}`',
        'id reservations': 'the record directory of the kind the number belongs to, '
                           f'named `{yaml_filename(vault.reserve_id)}`',
        'session signing key': f'`{vault_file(users.secret_key)}`, mode '
                               f'{oct(users.SECRET_KEY_MODE)}',
    }


LOCATION_SOURCES = {
    'jobs': 'vault._save_record',
    'companies': 'vault._save_record',
    'experiences': 'vault.save_experience',
    'users': 'users.save_user',
    'notes': 'vault.notes_view, vault.notes_payload',
    'history events': 'vault.append_event',
    'search criteria': 'vault.load_search',
    'tags': 'vault.load_tags',
    'invites': 'invites.FOLDER, tokens.storage_path',
    'password resets': 'password_reset.FOLDER, tokens.storage_path',
    'rate-limit windows': 'ratelimit.hit',
    'mail send count': 'mail._record_sent',
    'id counters': 'vault._allocate',
    'id reservations': 'vault.reserve_id',
    'session signing key': 'users.secret_key',
}


def owner_scoped_kinds(fields):
    """The kinds whose records belong to one person.

    By the field that says so -- `vault.OWNER_FIELD` on a job or an
    experience, `author_id` on a note -- and by containment: a history event
    lives inside a job record, so whose the job is, is whose the event is.
    """
    owned = {kind for kind, names in fields.items()
             if vault.OWNER_FIELD in names or AUTHOR_FIELD in names}
    for container, contained, _ in CONTAINED_KINDS:
        if container in owned:
            owned.add(contained)
    return owned


def containers_of(kind):
    return sorted({container for container, contained, _ in CONTAINED_KINDS
                   if contained == kind})


def scope_of_kind(kind, fields, rows):
    """How a kind is scoped, in the words the page uses.

    Read off three things and nothing else: the field that says whose
    record it is, the record a contained kind lives inside, and -- for a
    kind with neither -- who the permissions matrix says may write it.
    """
    if vault.OWNER_FIELD in fields:
        return f'per user, by `{vault.OWNER_FIELD}`'
    if AUTHOR_FIELD in fields:
        return f'per author, by `{AUTHOR_FIELD}`'
    containers = containers_of(kind)
    if containers:
        return (f'whatever the record holding it is scoped to ({", ".join(containers)}), '
                'because it is a field of that record and not a record of its own')
    readers = sorted({row['read'] for row in rows if row['kind'] == kind
                      and row['read'] != 'no read on this route'})
    writers = sorted({row['write'] for row in rows if row['kind'] == kind
                      and row['write'] != 'no write on this route'})
    return ('no owner or author field in its allowlist, so nothing in the record says '
            'whose it is. '
            + (f'Read on routes whose read access reads: {"; ".join(readers)}. '
               if readers else 'No Flask route reads it. ')
            + (f'Written on routes whose write access reads: {"; ".join(writers)}'
               if writers else 'No Flask route writes it: the vault keeps it for the host'))


def permission_rows(rules, owned):
    """One row per route and record kind, with the access each one runs under.

    A route that reaches no record kind keeps a row of its own, so the
    matrix accounts for every rule in the url map rather than for the
    interesting ones.
    """
    rows = []
    for rule in rules:
        handler = rule['function']
        kinds, reached, scoped = route_touches(handler)
        public = rule['endpoint'] in server.PUBLIC_ENDPOINTS
        gate = 'public' if public else 'any logged-in user'
        if public:
            # The further gate a public route does apply, where the code
            # says so: a token in the rule itself, spent against the records
            # careeros.tokens keeps, and the rate limiter it registers with.
            if '<token>' in rule['path'] and any(key.startswith('careeros.tokens.')
                                                 for key in reached):
                gate += ', one-time token'
            if any(key.startswith('careeros.ratelimit.') for key in reached):
                gate += ', rate limited'
        admin = any(token in handler_source(handler) for token in ADMIN_TOKENS)
        if not kinds:
            rows.append({'path': rule['path'], 'methods': rule['methods'],
                         'endpoint': rule['endpoint'], 'kind': 'none',
                         'read': 'no record kind on this route',
                         'write': 'no write on this route', 'via': '', 'layers': ''})
            continue
        for kind in sorted(kinds):
            touch = kinds[kind]
            if (kind in owned and not public and not scoped
                    and 'route code' in touch['layers']):
                # The route's own code names a private kind's storage symbol
                # and builds no scope to read it under, which is the one
                # shape this method cannot classify. A kind reached only
                # underneath a save is a different case: it is the record
                # holding it that decides, and that record's own rule is
                # what the row then reports.
                fail(f'{rule["endpoint"]} reaches {kind}, which is private to one '
                     'user, and its own code builds no ownership scope, so this '
                     'generator cannot say who may read it')
            if public:
                read, write = gate, gate
            elif kind in owned:
                read = write = 'owner only'
            else:
                read = 'any logged-in user'
                write = 'admin only' if admin else 'any logged-in user'
            if not touch['read']:
                read = 'no read on this route'
            if not touch['write']:
                write = 'no write on this route'
            rows.append({
                'path': rule['path'], 'methods': rule['methods'],
                'endpoint': rule['endpoint'], 'kind': kind, 'read': read, 'write': write,
                'via': ', '.join(code(name) for name in
                                 sorted(touch['read'] | touch['write'])),
                'layers': ', '.join(sorted(touch['layers'])),
            })
    check_count('the permissions matrix', len({(row['path'], row['endpoint']) for row in rows}),
                len({(rule['path'], rule['endpoint']) for rule in rules}))
    return rows


def kinds_section(fields, locations, rows, owned):
    lines = [
        '## Record kinds',
        '',
        'Everything this app stores in a vault, one block per kind. The storage location '
        'is read off the function that writes the kind: the filename of a numbered record '
        'is printed as the expression that builds it, and a single-file kind is named by '
        'the `Path(root) / ...` expression in its own reader. The allowed fields are the '
        'allowlist in code and never the fields a stored record happens to carry, so a '
        'field an older record holds and no writer accepts any more is absent here, which '
        'is the honest answer: a write would drop it. A kind whose writer checks no field '
        'list at all says so. The scope is read off the field that says whose record it is '
        '(`vault.OWNER_FIELD` for a job or an experience, `author_id` for a note), off the '
        'record a contained kind lives inside, and for a kind with none of those off the '
        'permissions matrix below.',
        '',
        'Beside the allowlist, a block lists the fields the writer sets itself. Those sit '
        'outside the allowlist, which is what makes them the vault\'s own: no payload can '
        'set them, and a job\'s `history` is the clearest case, a stored field a client can '
        'neither write nor edit. A save also reaches past its own kind inside the storage '
        'layer: saving a job appends a history event, can register a proposed tag value '
        'through `vault.validate_tags`, and regenerates the linked company rollup through '
        '`enrich.regenerate_company` when `enrich.contributes_to_shared` allows it.',
        '',
    ]
    check_token('saving a job appends a history event', vault._save_record, 'append_event')
    check_token('saving a job can register a proposed tag value',
                vault._save_record, 'validate_tags')
    check_token('saving a job regenerates the linked company rollup',
                vault.save_job, 'regenerate_company')
    check_token('the company rollup is regenerated only when the job may write the '
                'shared half', vault.save_job, 'contributes_to_shared')
    written = {'jobs': assigned_keys(vault._save_record, 'result', branch='job')
                       + assigned_keys(vault.append_event, 'job'),
               'companies': assigned_keys(vault._save_record, 'result', branch='company'),
               'experiences': assigned_keys(vault.save_experience, 'result'),
               'users': assigned_keys(users.save_user, 'result')}
    for kind in sorted(fields):
        names = fields[kind]
        extra = sorted(set(written.get(kind, ())) - set(names))
        lines.extend([
            f'### {kind}',
            '',
            f'* Stored at: {locations[kind]} ({LOCATION_SOURCES[kind]}).',
            f'* Allowed fields ({FIELD_SOURCES[kind]}): '
            + (', '.join(code(name) for name in names) if names else 'none listed in code')
            + '.',
        ])
        if extra:
            lines.append('* Fields the writer sets itself, outside the allowlist: '
                         + ', '.join(code(name) for name in extra) + '.')
        lines.extend([
            f'* Scope: {scope_of_kind(kind, names, rows)}.'
            + (' Read through `vault.Owner`, which answers for somebody else\'s record '
               'exactly as it answers for one that does not exist.' if kind in owned else ''),
            '',
        ])
    return lines[:-1]


def matrix_section(rows):
    lines = [
        '## Permissions matrix',
        '',
        'One row per Flask rule and record kind, over the same url map routes.md reads. '
        'The kinds are what the route can reach: the handler, and every careeros function '
        'it names through its own globals or closure, resolved name by name. Read that as '
        'an upper bound in two directions. A function reached on one branch counts as '
        'reached, and a save of one kind reaches another inside the storage layer, which '
        'is what the `Reached from` column is for: `route code` means the symbol is named '
        'by the handler or by a careeros.server or careeros.web helper it calls, and '
        '`storage layer` means it was reached underneath that, so the route does not '
        'necessarily take a payload for that kind. The one blind spot in the other '
        'direction is a call this walk cannot resolve to a function, which is why the '
        'symbols behind every row are printed as its evidence.',
        '',
        'The access columns say what the request gate and the admin rule let through on '
        'that route. `public` is an endpoint in `careeros.server PUBLIC_ENDPOINTS`, which '
        'the gate lets through without a session, and the further gate such a route does '
        'apply is named beside it. `owner only` is a kind that carries an owner or an '
        'author, on a route whose own code builds the ownership scope every private read '
        'is filtered through; a route that reached such a kind without building one in '
        'its own code would abort this generator rather than appear here with a guess, '
        'and a kind reached only underneath a save carries the rule of the record that '
        'holds it. `admin only` is a shared write on a route whose handler consults the '
        'admin rule (`may_edit_shared`, `shared_denied`), which is the same reading '
        'routes.md takes, and it carries the same caveat: it says the handler applies '
        'that rule to the shared write it makes, not that every kind on the row and '
        'every method on the route is the admin\'s. A delete is the clearest case, '
        'because taking an id out of circulation (`id counters`, `id reservations`) '
        'happens on the same route and no admin rule guards it. A shared write with no '
        'such reading anywhere in the handler is every logged-in user\'s, which is the '
        'true answer for a company note. Every row that is not public also reads the '
        'signed-in user\'s own record, because the gate does (`careeros.server '
        'require_login`); that read is stated here once instead of on every row that '
        'needs it.',
        '',
    ]
    columns = ('Path', 'Methods', 'Endpoint', 'Record kind', 'Read access', 'Write access',
               'Reached from', 'Storage symbols')
    table_rows = [(code(row['path']), ', '.join(row['methods']), code(row['endpoint']),
                   row['kind'], row['read'], row['write'], row['layers'] or '', row['via'] or '')
                  for row in rows]
    return lines + table(columns, table_rows)


def status_section():
    """The status vocabulary, and the lifecycle the code actually enforces."""
    check_count('the job statuses', len(vault.STATUSES), raw_tuple_count(vault, 'STATUSES'))
    check_token('an ending reason is checked against the union of both vocabularies',
                vault._save_record, 'END_REASON_VALUES')
    check_token('no status gates an ending reason',
                vault._save_record, 'ENDED_STATUSES', present=False)
    default = vault._record_defaults('jobs')['status']
    if default not in vault.STATUSES:
        fail(f'a new job starts in status {default}, which is not in vault.STATUSES')
    lines = [
        '## Job status flow',
        '',
        'There is no transition table in the code. `vault._save_record` checks that a '
        'status is a member of `vault.STATUSES` and allows every move inside it, so any '
        'status may follow any other, an ended status included: nothing in the vault '
        'makes '
        + ', '.join(code(status) for status in vault.ENDED_STATUSES)
        + ' terminal, and a job moved back out of one '
        'is watched again (`vault._save_record` drops a `gone` watch verdict for a status '
        'in `watcher.WATCH_STATUSES`). The optional ending reason is not a gate either: '
        'it is checked against `vault.END_REASON_VALUES`, the union of both reason '
        'vocabularies, rather than against the status the job is in, which is what lets a '
        'job dragged from Stopped to Rejected keep the reason it was given. So the '
        'diagram draws what the code does enforce, which is the status a new record '
        f'starts in ({code(default)}, from `vault._record_defaults`) and the open/ended '
        'split `vault.ENDED_STATUSES` defines.',
        '',
        '```mermaid',
        'stateDiagram-v2',
    ]
    for group, title, statuses in (
            ('open', 'Open (vault.OPEN_STATUSES)', vault.OPEN_STATUSES),
            ('ended', 'Ended (vault.ENDED_STATUSES)', vault.ENDED_STATUSES)):
        lines.append(f'    state "{title}" as {group} {{')
        lines.extend(f'        state "{vault.STATUS_LABELS[status]}" as {status}'
                     for status in statuses)
        lines.append('    }')
    lines.extend([
        f'    [*] --> {default} : a new job (vault._record_defaults)',
        '    open --> ended : any status may be set',
        '    ended --> open : no transition table in code',
        '    open --> open',
        '    ended --> ended',
        '```',
        '',
        'Every status, with the words a surface shows (`vault.STATUS_LABELS`) and whether '
        'it ends the job. The ending reasons are the ones `vault.END_REASONS` offers for '
        'the statuses that have them, and a reason is always optional.',
        '',
    ])
    rows = [(code(status), vault.STATUS_LABELS[status],
             'ended' if status in vault.ENDED_STATUSES else 'open',
             ', '.join(vault.END_REASONS.get(status, ())) or 'none')
            for status in vault.STATUSES]
    return lines + table(('Status', 'Label', 'Open or ended', 'Ending reasons offered'), rows)


def registry_section():
    """Every history event type the vault can write."""
    check_count('the history event registry', len(history.REGISTRY), raw_registry_count())
    widths = sorted({len(entry) for entry in history.REGISTRY.values()})
    if widths != [2]:
        fail(f'careeros.history REGISTRY entries carry {widths} attributes, and this '
             'page is written for exactly two (label, visible)')
    lines = [
        '## History event registry',
        '',
        'Every event type a record\'s `history` may carry, from `careeros.history '
        'REGISTRY`. Each entry holds exactly two attributes, which is what this table has '
        'columns for: the owner-facing label and whether the event is visible at all. An '
        'invisible event is stored and never shown; an event type the registry does not '
        'name is dropped by `history.resolve`, which is how a legacy record carrying a '
        'retired type keeps reading as it did. Two types carry no label of their own and '
        'are built from the stored detail instead (`history.DETAIL_LABELS`), and the two '
        'extraction events share one label on purpose: the posting is read once, however '
        'many pipeline stages reported it.',
        '',
    ]
    rows = []
    for event in sorted(history.REGISTRY):
        label, visible = history.REGISTRY[event]
        builder = history.DETAIL_LABELS.get(event)
        rows.append((code(event),
                     f'built from the detail by `history.{builder.__name__}`' if builder
                     else (code(label) if label else 'none'),
                     'visible' if visible else 'hidden'))
    return lines + table(('Event type', 'Label', 'Visibility'), rows)


def singular_of(kind):
    """One record of a kind, as a field name would write it: `companies`
    holds a company, so a field pointing at one is `company_id`."""
    return f'{kind[:-3]}y' if kind.endswith('ies') else kind.removesuffix('s')


def link_rows(fields):
    """Which kinds link to which, and the fields that do not resolve.

    A link is a field that holds another kind's id. The kind is read off the
    field name: the singular of a record directory (`company_id` points at
    `companies`), or one of the three names that hold a user record id
    (`vault.OWNER_FIELD`, `author_id`, `user_id`). A `*_id` field that
    matches neither is not a link this method can place, and it is reported
    rather than guessed at.
    """
    singular = {singular_of(kind): kind for kind in vault.ID_PREFIXES}
    links, unplaced = [], []
    for kind in sorted(fields):
        for name in sorted(fields[kind]):
            if not name.endswith('_id'):
                continue
            target = NAMED_LINKS.get(name) or singular.get(name[:-len('_id')])
            if target is None:
                unplaced.append((kind, name))
            elif target != kind:
                links.append((target, kind, name))
    for container, contained, field in CONTAINED_KINDS:
        links.append((container, contained, f'{field} (contained)'))
    for kind in sorted(vault.ID_PREFIXES):
        links.append(('id counters', kind, 'next number'))
        links.append(('id reservations', kind, 'number taken out'))
    return sorted(set(links)), sorted(set(unplaced))


def slug(kind):
    return kind.replace(' ', '_').replace('-', '_')


def er_section(fields):
    for container, contained, field in CONTAINED_KINDS:
        check_token(f'a {contained[:-1]} lives under {field} on a {container[:-1]} record',
                    vault.notes_view if contained == 'notes' else vault.append_event,
                    f"'{field}'")
    check_token('a note carries the id of its author',
                vault.Owner.owns_note, f"'{AUTHOR_FIELD}'")
    check_token('a reset record names the account it belongs to',
                password_reset.request_reset, "'user_id'")
    links, unplaced = link_rows(fields)
    lines = [
        '## How the kinds link',
        '',
        'An arrow is a field one kind holds that points at another, read off the field '
        'names in the allowlists above: the singular of a record directory names the kind '
        'it points at (`company_id` points at `companies`), and the three fields that '
        'hold a user record id are named in the generator and checked against the code '
        'that reads them. A kind whose records live inside another kind\'s field is drawn '
        'the same way, with the field that contains them. The `id counters` and '
        '`id reservations` arrows are the four numbered kinds of `vault.ID_PREFIXES`, '
        'which is bookkeeping about numbers rather than a reference between records.',
        '',
        'The blind spots of that method are worth stating. It sees a link only where a '
        'field name carries the kind, so an association made by something other than an '
        'id field is not here: an invite and a reset record find their account by `email` '
        'and not by id, and the job a feed posting came from is matched by '
        '`normalized_url`. In the other direction, '
        + ('a field that looks like a link and points at no record kind is reported and '
           'not guessed at: ' + ', '.join(f'{code(name)} on {kind}' for kind, name in unplaced)
           + '.' if unplaced else 'every `*_id` field resolves to a kind.'),
        '',
        '```mermaid',
        'erDiagram',
    ]
    linked = {kind for source, target, _ in links for kind in (source, target)}
    lines.extend(f'    {slug(kind)}' for kind in sorted(set(fields) - linked))
    lines.extend(f'    {slug(source)} ||--o{{ {slug(target)} : "{field}"'
                 for source, target, field in links)
    lines.append('```')
    return lines


# --- the model page -------------------------------------------------------

#: Scanned for a function that hands text to a model client. The product
#: tree, the scripts beside it, and the one vendored file that sends a
#: prompt of its own -- read, never written, which is why it is named here
#: rather than globbed with the rest of vendor/. Not `tests/`: a test that
#: drives a fake client is not a place this app sends text, and every test
#: that exercises a model call injects a client of its own.
LLM_SCAN_TREES = ('careeros', 'scripts')
LLM_SCAN_FILES = ('vendor/capa-repo/org_intake/enrich.py',)

#: What a scanned call has to look like to count as handing text to a
#: model client, by the tail of the dotted name it calls.
LLM_CALL_TAILS = ('chat.completions.create', 'completions.create',
                  'LLMClient', 'get_llm_client')

#: A name that is the process environment, by its last part. `os.environ`
#: and the `environ` parameter `Config.from_env` takes are both one, and
#: a name assigned from either is too.
ENVIRONMENT_PART = 'environ'

#: No second argument to the `get`, so the code has no default at all.
NO_DEFAULT = object()
#: A default this run cannot read (not a literal, not a module constant).
UNREADABLE_DEFAULT = object()

#: Where a shell script that runs a triggering script is looked for.
SHELL_TREES = ('scripts', 'deploy')


class Canary(str):
    """A sentinel value that survives every shape a prompt builder reads a
    record field in.

    It is a string, so an f-string and a `.strip()` keep it whole. It
    iterates as itself once rather than as its characters, so
    `' '.join(record['skills'])` -- how the classification subject folds a
    job's list fields into one text -- yields the sentinel instead of
    spelling it out letter by letter. And `.get` answers with a nested
    sentinel, so a builder that reads a mapping field keeps saying which
    field it read rather than raising.
    """

    def __iter__(self):
        return iter((str(self),))

    def get(self, key, default=None):
        return Canary(f'{self}.{key}')


def sentinel(name):
    return f'CANARY-{name}'


def canary_record(names, only=None):
    """A record whose every field is a sentinel naming itself, or -- with
    `only` -- whose one named field is, every other field being empty.

    The one-field form is what finds a field that is only placed when
    another is missing: the classification subject takes a job's `company`
    or, when that is empty, its `employer_named_in_posting`, and a record
    with both filled in would only ever show the first.
    """
    return {name: Canary(sentinel(name) if only in (None, name) else '') for name in names}


def resolve_dotted(name):
    """What one dotted name is, with whatever of it could not be resolved.

    Returns `(object, remainder)`. The remainder is the tail that named
    nothing importable or gettable, which is how a sender that is a
    closure -- `classification_options`'s `create` -- resolves to the
    function whose source holds it.
    """
    parts = name.split('.')
    module, index = None, 0
    for stop in range(len(parts), 0, -1):
        module = import_module('.'.join(parts[:stop]))
        if module is not None:
            index = stop
            break
    if module is None:
        fail(f'{name} names no module this run can import')
    value = module
    for position in range(index, len(parts)):
        found = getattr(value, parts[position], None)
        if found is None:
            return value, '.'.join(parts[position:])
        value = found
    return value, ''


def registry_function(name):
    """The function one registry entry names, which has to be one."""
    value, remainder = resolve_dotted(name)
    if remainder or not callable(value):
        fail(f'careeros.llm_registry names {name}, which is not a function of this app')
    return value


def definition_of(function):
    """The syntax tree of one function, from its own source."""
    try:
        source = textwrap.dedent(inspect.getsource(function))
    except (OSError, TypeError):
        fail(f'{function_key(function)} has no source this run can read')
    node = ast.parse(source).body[0]
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        fail(f'{function_key(function)} is not a plain function definition')
    return node


def parameter_names(definition):
    arguments = definition.args
    return [argument.arg for argument in
            arguments.posonlyargs + arguments.args + arguments.kwonlyargs]


def taint_of(node, taint):
    """Which of a function's parameters one expression's value can carry.

    An upper bound on purpose, and over exactly the expression shapes a
    prompt is built with: a `get`, an attribute, a subscript, an `or`, a
    conditional, a list, an f-string and a `+`. A call to anything else
    carries nothing, which is what keeps a constant table read with a
    tainted key -- `DIMENSION_OF[field]` -- from being read as the
    parameter's own value.
    """
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return set(taint.get(node.id, ()))
    if isinstance(node, (ast.Attribute, ast.Subscript, ast.Starred)):
        return taint_of(node.value, taint)
    if isinstance(node, ast.BoolOp):
        return set().union(*[taint_of(value, taint) for value in node.values])
    if isinstance(node, ast.IfExp):
        return taint_of(node.body, taint) | taint_of(node.orelse, taint)
    if isinstance(node, ast.BinOp):
        return taint_of(node.left, taint) | taint_of(node.right, taint)
    if isinstance(node, ast.FormattedValue):
        return taint_of(node.value, taint)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.JoinedStr)):
        children = getattr(node, 'elts', None) or getattr(node, 'values', None) or []
        return set().union(*[taint_of(child, taint) for child in children]) if children else set()
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return taint_of(node.elt, taint)
    if isinstance(node, ast.Call):
        function = node.func
        if isinstance(function, ast.Attribute) and function.attr in ('get', 'pop'):
            return taint_of(function.value, taint)
        return set()
    return set()


def literal_key(node):
    """The string a node is, or None when it is not one."""
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def same_module_call(node, module):
    """The function of `module` one call names, or None."""
    if not isinstance(node.func, ast.Name):
        return None
    target = getattr(module, node.func.id, None)
    if inspect.isfunction(target) and inspect.getmodule(target) is module:
        return target
    return None


def prompt_reads(function, taint=None, seen=None):
    """Which literal keys a prompt builder reads off each of its parameters.

    `{parameter: {key, ...}}`, with an empty set for a parameter whose
    whole value is placed. See the module docstring: this is the first of
    the two readings the fields column is held against.
    """
    module = inspect.getmodule(function)
    seen = set() if seen is None else seen
    if function in seen:
        return {}
    seen = seen | {function}
    definition = definition_of(function)
    names = parameter_names(definition)
    taint = {name: {name} for name in names} if taint is None else dict(taint)
    found = {}

    def bind(target, roots):
        if isinstance(target, ast.Name) and roots:
            taint[target.id] = set(taint.get(target.id, ())) | roots
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                bind(item, roots)

    # Two passes: the taint of every local first, so a key read above the
    # assignment that tainted it is still attributed. A prompt builder is
    # a dozen lines and reads top to bottom, so one pass would do; two
    # cost nothing and cannot be fooled by the order.
    for node in ast.walk(definition):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                bind(target, taint_of(node.value, taint))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            bind(node.target, taint_of(node.value, taint))
        elif isinstance(node, (ast.For, ast.comprehension)):
            bind(node.target, taint_of(node.iter, taint))

    def record(roots, keys):
        for root in roots:
            found.setdefault(root, set()).update(keys)

    for node in ast.walk(definition):
        if isinstance(node, ast.Subscript):
            key = literal_key(node.slice)
            if key is not None:
                record(taint_of(node.value, taint), {key})
        elif isinstance(node, ast.Call):
            call = node.func
            if isinstance(call, ast.Attribute) and call.attr in ('get', 'pop') and node.args:
                key = literal_key(node.args[0])
                if key is not None:
                    record(taint_of(call.value, taint), {key})
                    continue
            target = same_module_call(node, module)
            if target is None:
                continue
            inner = parameter_names(definition_of(target))
            passed = {}
            for position, argument in enumerate(node.args):
                if position < len(inner):
                    passed.setdefault(inner[position], set()).update(taint_of(argument, taint))
            for keyword in node.keywords:
                if keyword.arg:
                    passed.setdefault(keyword.arg, set()).update(taint_of(keyword.value, taint))
            if not any(passed.values()):
                continue
            deeper = prompt_reads(target, {name: {name} for name in inner}, seen)
            for parameter, keys in deeper.items():
                record(passed.get(parameter, ()), keys)
    return {name: found.get(name, set()) for name in names}


def environment_reads(function, seen=None):
    """Every environment variable one function reads, with its default.

    `{variable: default}`, where the default is the second argument to the
    `get` as this run can read it, `NO_DEFAULT` when there is none and
    `UNREADABLE_DEFAULT` when it is neither a literal nor a constant of
    the function's own module. Follows a call to another function of the
    same module, which is how `get_llm_client` is found to read the model
    name as well as the address.
    """
    module = inspect.getmodule(function)
    seen = set() if seen is None else seen
    if function in seen:
        return {}
    seen = seen | {function}
    definition = definition_of(function)
    environment = {name for name in parameter_names(definition) if name == ENVIRONMENT_PART}
    found = {}

    def is_environment(node):
        name = dotted_name(node)
        if name is None:
            return False
        return name.split('.')[-1] == ENVIRONMENT_PART or name in environment

    for node in ast.walk(definition):
        if isinstance(node, ast.Assign):
            if any(is_environment(child) for child in ast.walk(node.value)):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        environment.add(target.id)

    def default_of(node, position):
        if len(node.args) > position:
            argument = node.args[position]
            if isinstance(argument, ast.Constant):
                return argument.value
            if isinstance(argument, ast.Name):
                value = getattr(module, argument.id, None)
                return value if value is not None else UNREADABLE_DEFAULT
            return UNREADABLE_DEFAULT
        return NO_DEFAULT

    for node in ast.walk(definition):
        if not isinstance(node, ast.Call):
            continue
        call = node.func
        if isinstance(call, ast.Attribute) and call.attr == 'getenv':
            variable = literal_key(node.args[0]) if node.args else None
            if variable is not None:
                found[variable] = default_of(node, 1)
            continue
        if (isinstance(call, ast.Attribute) and call.attr == 'get'
                and node.args and is_environment(call.value)):
            variable = literal_key(node.args[0])
            if variable is not None:
                found[variable] = default_of(node, 1)
            continue
        target = same_module_call(node, module)
        if target is not None:
            found.update(environment_reads(target, seen))
    return found


def slice_caps(function):
    """The upper bounds of the slices one function applies, as the page
    prints them: `{what it is called: how long it is}`."""
    module = inspect.getmodule(function)
    caps = {}
    for node in ast.walk(definition_of(function)):
        if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Slice):
            continue
        upper = node.slice.upper
        if isinstance(upper, ast.Name):
            value = getattr(module, upper.id, None)
            if isinstance(value, int):
                caps[f'{module.__name__}.{upper.id}'] = value
        elif isinstance(upper, ast.Constant) and isinstance(upper.value, int):
            caps[f'a literal in {function_key(function)}'] = upper.value
    return caps


def scan_files():
    """Every file the model-client scan reads, repo-relative and sorted."""
    paths = [path for tree in LLM_SCAN_TREES
             for path in (ROOT / tree).rglob('*.py')]
    for name in LLM_SCAN_FILES:
        path = ROOT / name
        if not path.exists():
            fail(f'{name} is named by the model-client scan and does not exist')
        paths.append(path)
    return sorted(set(paths))


def module_name_of(path):
    """The dotted name a scanned file is reported under."""
    relative = path.relative_to(ROOT)
    parts = list(relative.with_suffix('').parts)
    if parts[:2] == ['vendor', 'capa-repo']:
        parts = parts[2:]
    return '.'.join(parts)


def llm_client_calls():
    """Every function in the scanned files that hands text to a model
    client: `{qualified name: repo-relative file}`.

    The accounting the page and the suite are held to. A function that
    calls a model client and is neither a registered sender nor named in
    `llm_registry.CLIENT_PLUMBING` is a call site nobody wrote down, and
    the generator refuses to write a page that does not mention it.
    """
    found = {}
    for path in scan_files():
        if path == Path(__file__).resolve():
            continue
        module = module_name_of(path)
        scope = []

        def walk(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    scope.append(child.name)
                    walk(child)
                    scope.pop()
                    continue
                if isinstance(child, ast.Call):
                    name = dotted_name(child.func) or ''
                    if any(name.endswith(tail) for tail in LLM_CALL_TAILS) and scope:
                        found['.'.join([module] + scope)] = str(path.relative_to(ROOT))
                walk(child)

        walk(ast.parse(path.read_text()))
    return found


def check_call_site_accounting():
    """Refuse to write the page while a model call is unaccounted for.

    Both directions, like the storage map: a scanned function has to be a
    registered sender or declared plumbing, and every registered sender
    has to still be found by the scan. Plumbing is held to existing rather
    than to being found, because the transport itself calls no client.
    """
    found = llm_client_calls()
    known = {name for entry in llm_registry.CALL_SITES for name in entry.senders}
    for name in sorted(set(found) - known - set(llm_registry.CLIENT_PLUMBING)):
        fail(f'{name} ({found[name]}) hands text to a model client and is in no '
             'careeros.llm_registry entry: add it to the registry, or to '
             'CLIENT_PLUMBING with the reason it sends no prompt')
    for name in sorted(known - set(found)):
        fail(f'careeros.llm_registry registers {name} as a sender and the scan of '
             'the product tree no longer finds a model call in it')
    for name in sorted(llm_registry.CLIENT_PLUMBING):
        _value, remainder = resolve_dotted(name)
        if remainder:
            fail(f'careeros.llm_registry CLIENT_PLUMBING names {name}, which no longer exists')
    return found


def check_prompt_parts(entry):
    """Hold one entry's parts against the builder's own syntax tree."""
    builder = registry_function(entry.prompt_builder)
    reads = prompt_reads(builder)
    declared = {}
    for part in entry.parts:
        if part.parameter:
            declared.setdefault(part.parameter, set()).update(part.keys)
    for parameter in sorted(set(reads) | set(declared)):
        if parameter not in reads:
            fail(f'{entry.name}: careeros.llm_registry names the prompt parameter '
                 f'{parameter!r}, which {entry.prompt_builder} does not take')
        if parameter not in declared:
            if reads[parameter]:
                fail(f'{entry.name}: {entry.prompt_builder} reads '
                     f'{sorted(reads[parameter])} off {parameter!r}, which no part of '
                     'the careeros.llm_registry entry claims')
            continue
        if reads[parameter] != declared[parameter]:
            fail(f'{entry.name}: {entry.prompt_builder} reads '
                 f'{sorted(reads[parameter])} off {parameter!r} and '
                 f'careeros.llm_registry says {sorted(declared[parameter])}')
    return reads


def prompt_arguments(entry, record):
    """What to call one prompt builder with, from the registry's own
    description of its parameters."""
    builder = registry_function(entry.prompt_builder)
    arguments = {}
    for parameter in parameter_names(definition_of(builder)):
        if parameter not in entry.canary:
            fail(f'{entry.name}: {entry.prompt_builder} takes {parameter!r} and '
                 'careeros.llm_registry does not say what to call it with')
        wanted = entry.canary[parameter]
        if isinstance(wanted, llm_registry.Literal):
            arguments[parameter] = wanted.value
        elif wanted == llm_registry.CANARY_RECORD:
            arguments[parameter] = record
        elif wanted == llm_registry.CANARY_RECORD_LIST:
            arguments[parameter] = [record]
        elif wanted == llm_registry.CANARY_TEXT:
            arguments[parameter] = Canary(sentinel(parameter))
        else:
            fail(f'{entry.name}: careeros.llm_registry asks for {wanted!r} for the '
                 f'{parameter!r} parameter, which is not a canary this generator has')
    return builder, arguments


def rendered_prompt(entry, record):
    """One prompt as one text, so what it carries can be read off it."""
    builder, arguments = prompt_arguments(entry, record)
    try:
        messages = builder(**arguments)
    except Exception as error:
        fail(f'{entry.name}: {entry.prompt_builder} raised {type(error).__name__} on a '
             f'canary record, so this run cannot read what its prompt carries: {error}')
    if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
        fail(f'{entry.name}: {entry.prompt_builder} no longer returns a list of messages')
    return '\n'.join(str(message.get('content') or '') for message in messages)


def reaching_fields(entry, fields):
    """Which stored fields of one kind a canary run finds in the prompt.

    One run per field with that field alone filled in, plus one with all of
    them, and the union of what came through. The per-field runs are what
    find a field that is only placed when another is empty; the whole-record
    run is what finds one that is only placed when another is not.
    """
    names = list(fields)
    adapter = registry_function(entry.adapter) if entry.adapter else None
    reached = set()
    for only in [None] + names:
        record = canary_record(names, only=only)
        subject = adapter(record) if adapter is not None else record
        text = rendered_prompt(entry, subject)
        squeezed = re.sub(r'\s+', '', text)
        for name in names:
            if sentinel(name) in text or sentinel(name) in squeezed:
                reached.add(name)
    return reached


def prompt_fields(entry, universe):
    """The stored fields one call site's prompt carries, and the sentence
    that says how this run knows the rest are absent."""
    declared = {}
    for part in entry.parts:
        if part.vault_kind:
            declared.setdefault(part.vault_kind, set()).update(part.vault_fields)
    for kind, named in declared.items():
        if kind not in universe:
            fail(f'{entry.name}: careeros.llm_registry names the stored kind {kind!r}, '
                 'which the data model page does not have')
        for name in sorted(named - set(universe[kind])):
            fail(f'{entry.name}: careeros.llm_registry says the prompt carries the '
                 f'{kind} field {name!r}, which is not in that kind\'s allowlist')
    if not entry.canary_kind:
        # No record parameter: the value arrives as a plain argument from
        # several callers, so the registry's claim stands and what this run
        # checks is that nothing else can come in with it.
        for part in entry.parts:
            if part.vault_kind and not part.declared:
                fail(f'{entry.name}: the {part.vault_kind} fields of the '
                     f'{part.label!r} part are neither derived from a canary run nor '
                     'marked declared in careeros.llm_registry')
            if part.vault_kind and part.keys:
                fail(f'{entry.name}: the {part.label!r} part claims stored fields and '
                     'reads keys off its parameter, so a canary run has to derive them')
        parameters = sorted({part.parameter for part in entry.parts if part.vault_kind})
        evidence = ('the builder reads no key off ' + ', '.join(f'`{name}`' for name in parameters)
                    + ', so nothing but the text it is handed can enter')
        return declared, evidence
    kind = entry.canary_kind
    if kind not in universe:
        fail(f'{entry.name}: careeros.llm_registry runs its canary over {kind!r}, '
             'which the data model page does not have')
    reached = reaching_fields(entry, universe[kind])
    if reached != declared.get(kind, set()):
        fail(f'{entry.name}: a canary run finds the {kind} fields {sorted(reached)} in the '
             f'prompt and careeros.llm_registry says {sorted(declared.get(kind, set()))}')
    evidence = (f'a canary run over all {len(universe[kind])} fields of {kind} finds these '
                'in the rendered prompt and no other')
    return declared, evidence


def route_triggers(entry, rules):
    """The rules whose handler can reach one call site."""
    found = []
    for rule in rules:
        _kinds, reached, _scoped = route_touches(rule['function'])
        if reached & set(entry.reach_markers):
            found.append(f"{', '.join(rule['methods'])} {rule['path']}")
    return sorted(set(found))


def reached_from(function):
    """Every careeros function one function can reach, by name."""
    seen, queue, reached = set(), [function], {function_key(function)}
    while queue:
        current = queue.pop()
        key = definition_key(current)
        if key in seen:
            continue
        seen.add(key)
        for target in references(current):
            reached.add(function_key(target))
            queue.append(target)
    return reached


def script_scope(tree, module_names):
    """What a script's careeros imports bind, and which modules it names.

    Only the careeros side is resolved: the point is to find what app
    function a script can call, not to import the script itself, which
    would run whatever sits at its top level.
    """
    scope, named = {}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] == 'careeros':
            module = import_module(node.module)
            for alias in node.names:
                value = (getattr(module, alias.name, None)
                         or import_module(f'{node.module}.{alias.name}'))
                if value is not None:
                    scope[alias.asname or alias.name] = value
                named.add(node.module)
                named.add(f'{node.module}.{alias.name}')
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] != 'careeros':
                    continue
                value = import_module(alias.name)
                if value is not None:
                    scope[alias.asname or alias.name.split('.')[0]] = value
                named.add(alias.name)
    return scope, named & module_names


def script_triggers(entry):
    """The scripts that can turn one call site on.

    Reaching the sender is not enough, and the module docstring says why:
    the accuracy report reaches the classification model layer through
    `classify.classify` and never asks for it. A script has to name the
    module the sender lives in as well.
    """
    senders = set(entry.senders)
    modules = {name.rsplit('.', 1)[0] for name in senders}
    found = []
    for path in sorted((ROOT / 'scripts').glob('*.py')):
        if path == Path(__file__).resolve():
            continue
        tree = ast.parse(path.read_text())
        scope, named = script_scope(tree, modules)
        if not named:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Name, ast.Attribute)):
                continue
            name = dotted_name(node)
            if not name:
                continue
            for function in functions_in(resolve(scope, name)):
                if reached_from(function) & senders:
                    found.append(str(path.relative_to(ROOT)))
    return sorted(set(found))


def shell_triggers(scripts):
    """The shell scripts that run one of those scripts."""
    found = []
    for tree in SHELL_TREES:
        for path in sorted((ROOT / tree).glob('*.sh')):
            text = path.read_text()
            if any(script in text for script in scripts):
                found.append(str(path.relative_to(ROOT)))
    return sorted(set(found))


def leaves_the_server(entry):
    """Whether one call site's request stays on this machine, read off the
    default its config function falls back to for the address."""
    endpoint = entry.endpoint
    reads = environment_reads(registry_function(endpoint.config_function))
    if set(reads) != set(endpoint.env_vars):
        fail(f'{entry.name}: {endpoint.config_function} reads {sorted(reads)} out of the '
             f'environment and careeros.llm_registry says {sorted(endpoint.env_vars)}')
    if endpoint.base_url_var not in reads:
        fail(f'{entry.name}: careeros.llm_registry says {endpoint.base_url_var} decides the '
             f'address and {endpoint.config_function} does not read it')
    default = reads[endpoint.base_url_var]
    if default in (NO_DEFAULT, UNREADABLE_DEFAULT) or not default:
        note = f' ({endpoint.owner_note})' if endpoint.owner_note else ''
        return (f'conditional: whatever {endpoint.base_url_var} is configured to{note}',
                f'no default in code: `{endpoint.config_function}` raises when '
                f'`{endpoint.base_url_var}` is unset, so the endpoint cannot be determined '
                f'from the code at all -- `{endpoint.base_url_var}` is the variable that '
                'decides it')
    host = urlsplit(str(default)).hostname
    if not host:
        fail(f'{entry.name}: the default {endpoint.base_url_var} of '
             f'{endpoint.config_function} is {default!r}, which names no host')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return (f'cannot be told from code: the default {endpoint.base_url_var} names the '
                f'host `{host}`, not an address',
                f'the default in code is `{default}`, whose host is a name this run cannot '
                'resolve to a private or a public address')
    if address.is_private:
        return (f'no (LAN) unless {endpoint.base_url_var} points elsewhere',
                f'the default in code is `{default}`, and `{host}` is a private address')
    return (f'yes: the default {endpoint.base_url_var} is the public address `{host}`, '
            f'unless {endpoint.base_url_var} points elsewhere',
            f'the default in code is `{default}`, and `{host}` is a public address')


def size_limit(entry):
    """How much text one call site sends, read off the slices it applies."""
    functions = [registry_function(entry.prompt_builder)]
    for name in entry.senders:
        value, _remainder = resolve_dotted(name)
        if callable(value):
            functions.append(value)
    caps = {}
    for function in functions:
        caps.update(slice_caps(function))
    declared = entry.size_limit
    if declared and declared not in caps:
        fail(f'{entry.name}: careeros.llm_registry says {declared} caps the text and no '
             f'slice of its prompt builder or senders applies it (found {sorted(caps)})')
    if not declared and caps:
        fail(f'{entry.name}: careeros.llm_registry says nothing caps the text and '
             f'{sorted(caps)} is applied to it')
    if not declared:
        return 'none'
    return f'{caps[declared]:,} characters (`{declared}`)'.replace(',', ' ')


def gate_flag(entry):
    """The environment flag one call site is off without, or that it has
    none, read off the function the registry names for it."""
    if not entry.gate_function:
        fail(f'{entry.name}: careeros.llm_registry names no function to read the gate off; '
             'name the sender itself for a call site that has no gate')
    reads = environment_reads(registry_function(entry.gate_function))
    if set(reads) != set(entry.gate_reads):
        fail(f'{entry.name}: {entry.gate_function} reads {sorted(reads)} out of the '
             f'environment and careeros.llm_registry says {sorted(entry.gate_reads)}')
    if entry.gate_var and entry.gate_var not in reads:
        fail(f'{entry.name}: careeros.llm_registry says {entry.gate_var} gates the call and '
             f'{entry.gate_function} does not read it')
    others = sorted(set(reads) - {entry.gate_var})
    beside = (' (the sender also reads ' + ', '.join(f'`{name}`' for name in others)
              + ', which bounds the call rather than gating it)') if others else ''
    if not entry.gate_var:
        return 'none' + beside
    return f'only with `{entry.gate_var}=1`' + beside


def part_cell(part):
    """One prompt part in the table: what it is, and the stored fields it
    carries. Which keys the builder reads to get them, and where they come
    from, are the detail table below."""
    text = f'{part.label} ({part.kind})'
    if part.vault_fields:
        return (f'{text}: {part.vault_kind} '
                + ', '.join(f'`{name}`' for name in sorted(part.vault_fields)))
    if part.keys:
        return text + ': ' + ', '.join(f'`{key}`' for key in sorted(part.keys))
    return text


def source_file(function):
    """Where one function is defined, repo-relative."""
    path = inspect.getsourcefile(function)
    if path is None:
        fail(f'{function_key(function)} has no source file')
    return str(Path(path).resolve().relative_to(ROOT))


def llm_rows(rules, universe):
    """One row per call site, and the evidence each row rests on."""
    rows, evidence = [], []
    for entry in llm_registry.CALL_SITES:
        builder = registry_function(entry.prompt_builder)
        reads = check_prompt_parts(entry)
        carried, absence = prompt_fields(entry, universe)
        scripts = script_triggers(entry)
        routes = route_triggers(entry, rules)
        shells = shell_triggers(scripts)
        triggers = ['`' + route + '`' for route in routes]
        triggers += [f'`{name}`' for name in scripts + shells]
        if not triggers:
            triggers = ['nothing in this repository reaches it']
        elif not routes:
            triggers = ['no Flask route reaches it'] + triggers
        if entry.trigger_note:
            triggers.append(entry.trigger_note)
        leaves, how = leaves_the_server(entry)
        rows.append((
            f'**{entry.name}**<br>`{entry.prompt_builder}`<br>{source_file(builder)}',
            '<br>'.join(triggers),
            '<br>'.join(part_cell(part) for part in entry.parts),
            size_limit(entry),
            gate_flag(entry),
            ', '.join(f'`{name}`' for name in sorted(entry.endpoint.env_vars)),
            leaves,
        ))
        evidence.append({'entry': entry, 'carried': carried, 'absence': absence,
                         'endpoint': how, 'reads': reads})
    return rows, evidence


def llm_never_sent(universe, evidence):
    """The stored fields no prompt carries, and how this run knows.

    The allowlists of every kind named in `llm_registry.USER_DATA_KINDS`,
    minus the fields the readings above found in a prompt. A kind that
    reaches no call site contributes all of its fields; a kind that
    reaches one has to have shown the rest absent.
    """
    carried, shown = {}, {}
    for found in evidence:
        for kind, names in found['carried'].items():
            carried.setdefault(kind, set()).update(names)
            shown.setdefault(kind, []).append(f"{found['entry'].name}: {found['absence']}")
    handed = ' and '.join(sorted(carried)) or 'nothing'
    never = {}
    for kind in llm_registry.USER_DATA_KINDS:
        if kind not in universe:
            fail(f'careeros.llm_registry USER_DATA_KINDS names {kind!r}, which is not a '
                 'record kind of the data model page')
        if not universe[kind]:
            fail(f'careeros.llm_registry USER_DATA_KINDS names {kind!r}, which has no field '
                 'allowlist in code, so this page cannot say what a prompt does not carry')
        missing = sorted(set(universe[kind]) - carried.get(kind, set()))
        if kind in carried and kind not in shown:
            fail(f'{kind} reaches a prompt and no run has shown which of its fields do not')
        never[kind] = (missing, shown.get(kind, [
            f'no prompt builder is handed a record of this kind: the only stored records '
            f'the three take are {handed}, so no field of this one can enter a prompt']))
    return never


def llm_never_sent_section(never):
    lines = [
        '## What no prompt carries',
        '',
        'Every field of every stored kind that holds what a person typed, minus the fields '
        'the table below places in a prompt. Nothing here is a list somebody kept up to '
        'date: it is the allowlists in code minus the prompts in code, and the generator '
        'aborts rather than print a field it cannot show absent. The way it is shown is '
        'printed with each kind.',
        '',
    ]
    for kind in llm_registry.USER_DATA_KINDS:
        missing, shown = never[kind]
        lines.append(f'**{kind}** ({len(missing)} of them): '
                     + (', '.join(f'`{name}`' for name in missing) or 'none') + '.')
        lines.append('')
        for line in shown:
            lines.append(f'  * {line}')
        lines.append('')
    return lines[:-1]


def llm_table_section(rows):
    lines = [
        '## Where text goes to a model',
        '',
        'One row per place this app sends text to a language model. Every column is read '
        'out of the sources the first line names, by the method the scripts/gen_docs.py '
        'docstring sets out; the only thing on this page that is not is the parenthesis '
        'naming what the owner has configured an address variable to, which is labelled '
        'as owner-supplied where it appears. A trigger is what the call graph of this '
        'repository can reach the call site from, which is an upper bound: a route on a '
        'row sends text when that run gets as far as the model, not on every request. '
        '`Endpoint variables` is every variable the config function reads, which is more '
        'than the one that decides the address.',
        '',
    ]
    columns = ('Call site', 'Trigger', 'What the prompt carries', 'Size limit', 'Gate flag',
               'Endpoint variables', 'Leaves the server')
    return lines + table(columns, rows)


def llm_parts_section(evidence):
    lines = [
        '## What each part of each prompt is',
        '',
        'One row per part of one prompt. `Read off` is the keys the prompt builder reads '
        'off that parameter, as its own syntax tree has them -- `the whole value` for a '
        'part that is placed as it arrives. `Stored fields` is what a canary run of the '
        'builder finds reaches the part, and is empty for a part that carries no stored '
        'record. A key the builder reads that no row here claims stops the generator.',
        '',
    ]
    rows = []
    for found in evidence:
        entry = found['entry']
        for part in entry.parts:
            keys = (', '.join(f'`{key}`' for key in sorted(part.keys)) if part.keys
                    else ('the whole value' if part.parameter else 'the builder\'s own text'))
            rows.append((entry.name, part.label, part.kind,
                         f'`{part.parameter}`' if part.parameter else 'none',
                         keys,
                         ', '.join(f'`{name}`' for name in sorted(part.vault_fields)) or 'none',
                         part.origin))
    return lines + table(('Call site', 'Part', 'Kind', 'Parameter', 'Read off',
                          'Stored fields', 'Where it comes from'), rows)


def llm_endpoint_section(evidence):
    lines = [
        '## How the last column was read',
        '',
        'The address each call site sends to, and what the code says about it.',
        '',
    ]
    rows = [(found['entry'].name, f"`{found['entry'].endpoint.config_function}`",
             f"`{found['entry'].endpoint.base_url_var}`", found['endpoint'])
            for found in evidence]
    return lines + table(('Call site', 'Config function', 'Address variable',
                          'What the code has'), rows)


def llm_accounting_section(found):
    lines = [
        '## Every function that touches a model client',
        '',
        'The scan the page is held to: every function in `careeros/`, `scripts/` and the '
        'one vendored file that sends a prompt of its own, that calls a model client. A '
        'function here that is in no registry entry stops the generator, so this list and '
        'the table above cannot come apart.',
        '',
    ]
    senders = {name: entry for entry in llm_registry.CALL_SITES for name in entry.senders}
    rows = []
    for name in sorted(set(found) | set(llm_registry.CLIENT_PLUMBING)):
        if name in senders:
            rows.append((f'`{name}`', f'sends the prompt of: {senders[name].name}'))
        else:
            rows.append((f'`{name}`', llm_registry.CLIENT_PLUMBING[name]))
    return lines + table(('Function', 'What it is'), rows)


def llm_document(rules, universe):
    found = check_call_site_accounting()
    rows, evidence = llm_rows(rules, universe)
    never = llm_never_sent(universe, evidence)
    sections = [
        [LLM_HEADER],
        ['# As-built: what this app sends to a language model', '',
         'Three places in this app put text in front of a model, and this page is all three '
         'of them: what each one sends, what turns it on, how much of a posting it carries '
         'and whether the request leaves this machine. Every table is read out of the '
         'sources named in the first line, which is why the file is generated rather than '
         'written: a prompt that starts carrying one more field, a config function that '
         'starts reading one more variable, or a fourth call site shows up here on the next '
         'run, and the `docs-fresh` CI job fails until it does.'],
        llm_never_sent_section(never),
        llm_table_section(rows),
        llm_parts_section(evidence),
        llm_endpoint_section(evidence),
        llm_accounting_section(found),
    ]
    return '\n\n'.join('\n'.join(section) for section in sections) + '\n', rows


def data_document(rules):
    check_storage_map()
    check_token('a handler builds the ownership scope through session_owner',
                server.create_app, 'def session_owner')
    fields = kind_fields()
    locations = kind_locations()
    owned = owner_scoped_kinds(fields)
    rows = permission_rows(rules, owned)
    sections = [
        [DATA_HEADER],
        ['# As-built data model', '',
         'What this app stores, who may read and write it, and how the kinds link. Every '
         'table, every diagram and every count on this page is read out of the sources '
         'named in the first line, which is why the file is generated rather than '
         'written: a field, a status, an event type or a route that is added, moved or '
         'removed shows up here on the next run. Where a fact cannot be read out of the '
         'code, the page says so rather than filling the gap.'],
        kinds_section(fields, locations, rows, owned),
        matrix_section(rows),
        status_section(),
        registry_section(),
        er_section(fields),
    ]
    return '\n\n'.join('\n'.join(section) for section in sections) + '\n', fields, rows


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
    # The same rules, so the matrix is held against the url map routes.md
    # reports rather than against a second reading of it.
    data, kinds, rows = data_document(rules)
    DATA_OUT.write_text(data, newline='\n')
    print(f'{DATA_OUT.relative_to(ROOT)}: {len(kinds)} record kinds, '
          f'{len(rows)} permission rows')
    # The same kinds, so what a prompt does not carry is computed against
    # the allowlists the data model page prints rather than a second
    # reading of them, and the same rules, for the trigger column.
    text, sites = llm_document(rules, kinds)
    LLM_OUT.write_text(text, newline='\n')
    print(f'{LLM_OUT.relative_to(ROOT)}: {len(sites)} model call sites')


if __name__ == '__main__':
    main()
