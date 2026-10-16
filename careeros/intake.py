"""Layered ATS posting extraction; guarded fetching is a replaceable hook."""
from html.parser import HTMLParser
import re
import json
from urllib.parse import urljoin, urlsplit, unquote, parse_qsl
from urllib import request
import ipaddress
import socket
import time
from queue import Queue, Empty
from threading import Thread
from datetime import date


FETCH_BUDGET = 15


def check_url_format(url):
    """Structural check only (scheme + host). No DNS. Safe for save-time validation."""
    if not isinstance(url, str) or urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).hostname:
        raise ValueError('Provide an HTTP or HTTPS posting URL.')
    return url

def is_unsafe_ip(ip):
    """A single place naming every non-public address category this project
    refuses to fetch from: private, loopback, link-local, multicast,
    reserved, or unspecified."""
    return any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified))


def check_url(url):
    check_url_format(url)
    parsed = urlsplit(url)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    except OSError as error:
        raise ValueError('Posting host must resolve to a public IP address.') from error
    if not addresses:
        raise ValueError('Posting host must resolve to a public IP address.')
    for address in addresses:
        if is_unsafe_ip(ipaddress.ip_address(address[4][0])):
            raise ValueError('Posting host must resolve only to public IP addresses.')
    return url


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirects are disabled for posting intake.')


MAX_REDIRECT_HOPS = 5
MAX_REDIRECT_BODY = 65536


class SafeRedirect(request.HTTPRedirectHandler):
    """Redirect handler for company-website lookups: follows redirects like
    a normal browser would, but re-runs the full safety check (public-IP-only
    DNS, http/https scheme) on EVERY hop, so a public site cannot bounce the
    fetcher onto a private/internal address, and caps the hop count so a
    redirect loop cannot burn the whole fetch budget. Posting intake keeps
    using NoRedirect; this handler is only wired into fetch_url_follow.

    One instance per opener (one opener per fetch), so the hop counter on
    the instance never spans unrelated requests.

    The stock handler drains each intermediate redirect body with an
    unbounded fp.read() before following the hop. Here that read is bounded
    (MAX_REDIRECT_BODY) and the intermediate response is always closed, on
    both the validation-failure and the success path. before_hop, when
    given, runs before each hop is followed and may raise (e.g. the
    caller's deadline check) to abort the fetch."""

    def __init__(self, max_hops=MAX_REDIRECT_HOPS, before_hop=None):
        super().__init__()
        self.max_hops = max_hops
        self.hops = 0
        self.before_hop = before_hop

    def http_error_302(self, req, fp, code, msg, headers):
        try:
            fp.read(MAX_REDIRECT_BODY)
        finally:
            fp.close()
        if self.before_hop is not None:
            self.before_hop()
        # A closed HTTPResponse safely returns b'' from the base handler's
        # own drain, so passing the closed fp through is deliberate.
        return super().http_error_302(req, fp, code, msg, headers)

    # 308 (Permanent Redirect, method-preserving) matters here: the stock
    # handler aliases it to its unbounded 302 implementation, so omitting it
    # from this alias line would let 308 hops bypass the bounded drain, the
    # forced close, and the before_hop deadline check entirely.
    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.hops >= self.max_hops:
            raise ValueError('Too many redirects while fetching a company website.')
        self.hops += 1
        target = urljoin(req.full_url, newurl)
        check_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def fetch_url_follow(url, max_hops=MAX_REDIRECT_HOPS):
    """Like fetch_url, but follows up to max_hops redirects with the
    public-IP safety check re-applied on every hop. Same deadline budget,
    same 2 MB body cap, same proxy-blocking. Used ONLY for the company
    website JSON-LD signal, where a homepage 301 to /en/home.html is the
    common case; posting intake deliberately stays redirect-free."""
    deadline = time.monotonic() + FETCH_BUDGET
    result = Queue(maxsize=1)

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError('Company website fetch deadline exceeded.')
        return seconds

    def fetch():
        try:
            check_url(url)
            opener = request.build_opener(request.ProxyHandler({}),
                                          SafeRedirect(max_hops, before_hop=remaining))
            req = request.Request(url, headers={'User-Agent': 'CareerOS/3 company-lookup'})
            with opener.open(req, timeout=min(10, remaining())) as response:
                chunks, size = [], 0
                while size < 2_000_000:
                    remaining()
                    chunk = response.read1(min(65536, 2_000_000 - size))
                    remaining()
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                result.put((True, b''.join(chunks).decode('utf-8', errors='replace')))
        except Exception as error:
            result.put((False, error))

    Thread(target=fetch, daemon=True).start()
    try:
        success, value = result.get(timeout=remaining())
    except Empty as error:
        raise TimeoutError('Company website fetch deadline exceeded.') from error
    if not success:
        raise value
    return value


def fetch_url(url):
    deadline = time.monotonic() + FETCH_BUDGET
    result = Queue(maxsize=1)

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError('Posting fetch deadline exceeded.')
        return seconds

    def fetch():
        try:
            check_url(url)
            # Ignore environment proxies and never follow redirects.
            opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
            req = request.Request(url, headers={'User-Agent': 'CareerOS/3 posting-intake'})
            with opener.open(req, timeout=min(10, remaining())) as response:
                chunks, size = [], 0
                while size < 2_000_000:
                    remaining()
                    chunk = response.read1(min(65536, 2_000_000 - size))
                    remaining()
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                result.put((True, b''.join(chunks).decode('utf-8', errors='replace')))
        except Exception as error:
            result.put((False, error))

    # Bound the caller even if DNS, headers, or a socket read is stalled.
    # The worker owns the response and closes it on completion/deadline.
    Thread(target=fetch, daemon=True).start()
    try:
        success, value = result.get(timeout=remaining())
    except Empty as error:
        raise TimeoutError('Posting fetch deadline exceeded.') from error
    if not success:
        raise value
    return value


def domain(url):
    host = urlsplit(url).hostname or ''
    parts = host.lower().split('.')
    count = 3 if '.'.join(parts[-2:]) in ('co.uk', 'com.au', 'co.nz', 'co.jp', 'com.br', 'co.in') else 2
    return '.'.join(parts[-count:])


# Structural chrome: suppressed exactly like script/style, their text never
# reaches parser.text or regions.
HIDDEN_TAGS = ('script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'noscript')
# Void elements never get a matching handle_endtag call; excluding them from
# the suppress stack keeps start/end bookkeeping balanced.
VOID_TAGS = frozenset(('br', 'img', 'input', 'hr', 'meta', 'link', 'area', 'base',
                      'col', 'embed', 'param', 'source', 'track', 'wbr'))
BLOCK_TAGS = frozenset(('p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'section'))
def is_chrome(attrs):
    for value in (attrs.get('class') or '', attrs.get('id') or ''):
        for name in value.lower().split():
            tokens = set(filter(None, re.split(r'[^a-z0-9]+', name)))
            if tokens & {'cookie', 'cookies', 'consent', 'gdpr', 'modal', 'dialog', 'breadcrumb', 'pagination'}:
                return True
            if name in {'header', 'footer', 'sidebar'}:
                return True
            if tokens & {'share', 'social', 'related', 'menu', 'nav', 'navigation', 'privacy', 'header', 'footer', 'job'} and tokens & {'banner', 'widget', 'bar', 'buttons', 'links', 'jobs', 'list', 'alert', 'icon'}:
                return True
    return False


class Posting(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.title, self.text = {}, [], []
        self.regions = {tag: [] for tag in ('main', 'article', 'body')}
        self.region_depth = dict.fromkeys(self.regions, 0)
        self.in_title = False
        self.hidden = 0
        self.suppress_stack = []
        self.json_blocks = []
        self.json_buffer = None

    def handle_starttag(self, tag, attrs):
        if tag in self.region_depth:
            self.region_depth[tag] += 1
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[(attrs.get('property') or attrs.get('name') or attrs.get('itemprop') or '').lower()] = attrs.get('content', '')
        if tag == 'title':
            self.in_title = True
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.json_buffer = []
        suppress = tag not in VOID_TAGS and (tag in HIDDEN_TAGS or is_chrome(attrs))
        if suppress:
            self.hidden += 1
        if tag not in VOID_TAGS:
            self.suppress_stack.append((tag, suppress))
        if tag in BLOCK_TAGS and not self.hidden:
            self.text.append('\n')
            for region, depth in self.region_depth.items():
                if depth:
                    self.regions[region].append('\n')

    def handle_endtag(self, tag):
        match = next((i for i in range(len(self.suppress_stack) - 1, -1, -1)
                      if self.suppress_stack[i][0] == tag), None)
        if match is None:
            return
        closed = self.suppress_stack[match:]
        del self.suppress_stack[match:]
        for opened, suppressed in closed:
            self.hidden -= int(suppressed)
            if opened in self.region_depth:
                self.region_depth[opened] = max(0, self.region_depth[opened] - 1)
            if opened == 'script' and self.json_buffer is not None:
                self.json_blocks.append(''.join(self.json_buffer))
                self.json_buffer = None
            if opened == 'title':
                self.in_title = False
        if any(opened in BLOCK_TAGS for opened, _ in closed) and not self.hidden:
            self.text.append('\n')
            for region, depth in self.region_depth.items():
                if depth:
                    self.regions[region].append('\n')

    def handle_data(self, value):
        if self.json_buffer is not None:
            self.json_buffer.append(value)
        if self.in_title:
            self.title.append(value)
        if not self.hidden:
            self.text.append(value)
            for tag, depth in self.region_depth.items():
                if depth:
                    self.regions[tag].append(value)


def ats(url):
    host = (urlsplit(url).hostname or '').lower()
    parts = [unquote(p) for p in urlsplit(url).path.split('/') if p]
    first = parts[0] if parts else ''
    for suffix, label in [('personio.de', 'Personio'), ('personio.com', 'Personio'),
                          ('workable.com', 'Workable'), ('smartrecruiters.com', 'SmartRecruiters'),
                          ('bamboohr.com', 'BambooHR'), ('monday.com', 'Monday')]:
        if host == suffix or host.endswith('.' + suffix):
            prefix = host[:-len(suffix)].rstrip('.').split('.')[0]
            slug = first if prefix in ('jobs', 'apply', 'careers') else prefix
            if prefix == 'forms':
                slug = ''
            return label, slug
    for host_name, label in [('boards.greenhouse.io', 'Greenhouse'), ('job-boards.greenhouse.io', 'Greenhouse'),
                             ('jobs.lever.co', 'Lever'), ('jobs.ashbyhq.com', 'Ashby')]:
        if host == host_name:
            return label, first
    return ('jobs.ch', '') if host == 'jobs.ch' or host.endswith('.jobs.ch') else ('', '')


def job_schema(parser, url):
    def nodes(value):
        if isinstance(value, list):
            for item in value:
                yield from nodes(item)
        elif isinstance(value, dict):
            yield value
            yield from nodes(value.get('@graph', []))
    postings = []
    for block in parser.json_blocks:
        try:
            for node in nodes(json.loads(block)):
                types = node.get('@type', [])
                if 'JobPosting' in (types if isinstance(types, list) else [types]) or (node.get('title') and node.get('hiringOrganization')):
                    postings.append(node)
        except (ValueError, TypeError):
            continue
    for node in postings:
        for candidate in (node.get('url'), node.get('mainEntityOfPage')):
            if isinstance(candidate, dict):
                candidate = candidate.get('@id') or candidate.get('url')
            if isinstance(candidate, str):
                try:
                    if candidate == url or urlsplit(candidate).path == urlsplit(url).path:
                        return node
                except ValueError:
                    pass
    return postings[0] if postings else {}


MAILTO_RE = re.compile(r'mailto:([^"\'\s<>?&]+)', re.I)


def find_mailto(html):
    """Pull the first plausible recruiting address out of raw markup.

    mailto: hrefs never reach the rendered text that heuristic_extract sees,
    so this scans the untouched HTML instead.
    """
    from careeros import ingest
    for match in MAILTO_RE.finditer(html or ''):
        candidate = ingest.redact(unquote(match.group(1)))
        if ingest.is_valid_contact_email(candidate):
            return candidate
    return ''


def extract(url, html=''):
    parser = Posting()
    parser.feed(html)
    schema = job_schema(parser, url)
    from careeros.ingest import redact
    return redact(_extract(url, parser, schema))


# Trailing/leading-line chrome that slips past structural suppression (e.g. a
# consent banner with no recognizable class/id). Only trimmed from the edges
# of the body fallback, never from schema-supplied description text.
EDGE_CHROME_RE = re.compile(r'cookie|all rights reserved|follow us|subscribe|imprint|'
                            r'datenschutz|privacy policy|privacy notice|\bagb\b|apply now|'
                            r'^select how often .*alert|^create alert$|^(?:menu|skip to content)$', re.I)


def _collapse_lines(parts):
    """Join fragments, collapsing in-line whitespace while keeping the block
    newlines Posting() inserts between paragraphs as real line breaks."""
    lines = (re.sub(r'[ \t]+', ' ', line).strip() for line in ''.join(parts).split('\n'))
    return [line for line in lines if line]


def _strip_chrome_edges(lines):
    start, end = 0, len(lines)
    while start < end and EDGE_CHROME_RE.search(lines[start]):
        start += 1
    while end > start and EDGE_CHROME_RE.search(lines[end - 1]):
        end -= 1
    return lines[start:end]


# Careers-page chrome that sites use as <title>/og:title on listing pages
# (e.g. rivia.com/careers). Never a real posting title; fall back instead so
# the LLM enrichment pass (or the owner) supplies the actual role name.
GENERIC_TITLE_RE = re.compile(
    r'^(?:careers?|jobs?|openings?|opportunities?|join (?:us|our team)|work (?:with|for) us|'
    r'apply(?: now)?|current openings|we are hiring|hiring)(?:\s+(?:at|@|-|–|—|\|)\s+.*)?$', re.I)


def _extract(url, parser, schema):
    platform, slug = ats(url)
    source = platform or domain(url)
    org = schema.get('hiringOrganization', {})
    if not isinstance(org, dict):
        org = {}
    meta_title = parser.meta.get('og:title') or parser.meta.get('twitter:title') or ''.join(parser.title)
    company = str(org.get('name') or parser.meta.get('og:site_name') or '').strip()
    if company.casefold() in ('jobs.ch', platform.casefold()) or company.casefold() == domain(url) and platform:
        company = ''
    if platform == 'jobs.ch' and not company:
        match = re.search(r'\s+at\s+(.+?)(?:\s+[|–—]\s+|$)', meta_title, re.I)
        if not match:
            match = re.search(r'(?:Company|Employer|Firma|Unternehmen)(?:\s*:\s*|\s*\n\s*)([^\n]+)', '\n'.join(parser.text), re.I)
        company = match.group(1).strip() if match else ''
    # JOZ-266: the employer name a job actually links against must never be
    # a guess (spec global rule 2). company itself keeps its pre-existing
    # slug/domain fallback below for the unrelated company-text display
    # field; employer_named_in_posting captures only the evidenced value,
    # before that fallback runs, staying null when the posting offered
    # nothing (not_evidenced, not a guess).
    employer_named_in_posting = company or None
    if not company:
        company = slug.replace('-', ' ').replace('_', ' ').title() if platform else source.split('.')[0].replace('-', ' ').title()
    website = None
    from careeros.ingest import redact
    for candidate in (org.get('sameAs'), org.get('url')):
        if candidate:
            try:
                website = check_url_format(redact(candidate))
                break
            except ValueError:
                pass
    fallback = unquote(urlsplit(url).path.rstrip('/').split('/')[-1]).replace('-', ' ').replace('_', ' ').strip() or (company or 'Job') + ' opportunity'
    if GENERIC_TITLE_RE.match(fallback):
        # The URL's last segment is careers-page chrome too (e.g.
        # rivia.com/careers?ashby_jid=...): no role name anywhere on the page,
        # so use a clearly provisional title for the owner/LLM to correct.
        fallback = (company or 'Job') + ' opportunity'
    title = str(schema.get('title') or meta_title or fallback)
    if not schema.get('title'):
        title = re.split(r'\s+[|–—]\s+|\s+-\s+', title)[0].strip()
        if company:
            title = re.sub(r'\s+(?:at|@)\s+' + re.escape(company) + r'$', '', title, flags=re.I)
    if not schema.get('title') and GENERIC_TITLE_RE.match(title or ''):
        # <title>/og:title was careers-page chrome, not a posting title.
        title = fallback
    schema_description = Posting()
    schema_description.feed(str(schema.get('description') or ''))
    text = re.sub(r'\s+', ' ', ' '.join(schema_description.text + parser.text))
    currency = r"(?:CHF|USD|EUR|[$€])"
    number = r"\d[\d,.'’]*(?:\s*[kK])?"
    amount = (rf"{currency}\s*{number}(?:\s*[-–]\s*(?:{currency}\s*)?{number})?"
              rf"|{number}(?:\s*[-–]\s*{number})?\s*{currency}")
    salary = next((text[max(0,m.start()-55):min(len(text),m.end()+55)].strip() for m in re.finditer(amount, text, re.I) if re.search(r'salary|compensation|CHF|\d\s*[kK]\s*[-–]\s*\d+\s*[kK]\s*USD', text[max(0,m.start()-90):m.end()+90], re.I)), '')
    locations = []
    places = schema.get('jobLocation', [])
    for place in places if isinstance(places, list) else [places]:
        address = place.get('address', {}) if isinstance(place, dict) else {}
        if isinstance(address, dict):
            for key in ('addressLocality', 'addressRegion', 'addressCountry'):
                value = address.get(key)
                if isinstance(value, dict):
                    value = value.get('name')
                if isinstance(value, str) and value:
                    locations.append(value)
    if not locations:
        locations = [x.title() for x in re.findall(r'\b(?:remote|hybrid|Zurich|Zürich|London|Berlin|Paris|New York|San Francisco|Geneva|Basel)\b', text, re.I)]
    remote = True if re.search(r'\bremote\b', text, re.I) else False if re.search(r'\bon[- ]site\b', text, re.I) else None
    if re.search(r'\b(?:no remote|not remote)\b', text, re.I):
        remote = False
    posted = None
    for value in [schema.get('datePosted')] + [parser.meta.get(key) for key in ('datepublished', 'date', 'article:published_time', 'date_published')]:
        try:
            posted = date.fromisoformat(str(value)[:10]).isoformat()
            break
        except ValueError:
            pass
    employment = schema.get('employmentType') or ''
    if isinstance(employment, list):
        employment = ', '.join(str(x) for x in employment)
    employees = org.get('numberOfEmployees')
    if isinstance(employees, dict):
        employees = employees.get('value')
    # The raw count and nothing derived from it. A posting's headcount used
    # to be bucketed here into a `size` string as well, which the company
    # write then stored in the legacy `size` field beside the class derived
    # from the same count -- the two coexisting scales the owner retired
    # (decision 2026-10-15), rebuilt from one signal under the old field's
    # name (CAREER-33). The class is derived from the count where every
    # other size signal is, in `fill_company_metadata`.
    from org_intake.classify import resolve_employee_count
    employee_count = resolve_employee_count(employees)
    sector = org.get('industry')
    sector = sector if isinstance(sector, str) else None
    visible = next((parser.regions[tag] for tag in ('main', 'article', 'body')
                    if any(value.strip() for value in parser.regions[tag])), parser.text)
    schema_lines = _collapse_lines(schema_description.text)
    body_lines = schema_lines if schema_lines else _strip_chrome_edges(_collapse_lines(visible))
    return dict(description='\n'.join(body_lines).strip(),
                sector=sector, employee_count=employee_count, locations=list(dict.fromkeys(locations)),
                title=title or fallback, company=company, website=website, source=source,
                original_url=url if platform else None, salary_info=bool(salary), salary_note=salary,
                location=', '.join(dict.fromkeys(locations)), remote_ok=remote, posted_date=posted,
                employment_type=str(employment), valid_through=str(schema.get('validThrough') or ''),
                employer_named_in_posting=employer_named_in_posting)


def _merge_extracted(data, fields, schema, parser):
    org = schema.get('hiringOrganization')
    protected = {
        'title': schema.get('title') or parser.meta.get('og:title') or
                 parser.meta.get('twitter:title') or parser.title,
        'company': (org.get('name') if isinstance(org, dict) else None) or
                   parser.meta.get('og:site_name'),
        'location': schema.get('jobLocation'),
        'employment_type': schema.get('employmentType'),
    }
    for key, value in fields.items():
        if key in ('title', 'company', 'location', 'employment_type', 'remote_ok'):
            # Keep explicit posting metadata when the offline rules are used.
            if fields['ingest_source'] == 'heuristic' and protected.get(key) and data.get(key) not in (None, ''):
                continue
            if value in (None, ''):
                continue
            # A model that echoes careers-page chrome ('Careers', 'Jobs',
            # 'Join us') has not found the role title; keep what we have.
            if key == 'title' and GENERIC_TITLE_RE.match(str(value)) and data.get('title'):
                continue
        data[key] = value
        if key == 'company' and value and fields.get('ingest_source') == 'llm':
            data['employer_named_in_posting'] = value
            data['field_provenance'] = {**data.get('field_provenance', {}),
                                        'employer_named_in_posting': 'llm'}
    from careeros.ingest import redact
    return redact(data)


def heuristic_posting(url, html):
    """Posting metadata plus an instant offline pass; never calls the LLM.

    Used by the intake route so the response never waits on the slow model;
    callers queue ingest.extract_async separately to fill richer fields later.
    """
    from careeros import ingest
    parser = Posting()
    parser.feed(html)
    schema = job_schema(parser, url)
    data = _extract(url, parser, schema)
    fields = ingest.heuristic_extract(data['description']) | {'ingest_source': 'heuristic'}
    data = _merge_extracted(data, fields, schema, parser)
    mailto = find_mailto(html)
    if mailto:
        data['contact_email'] = mailto
    from careeros.ingest import redact
    return redact(data)


def ingest_posting(url, html, function_options=None):
    """Combine posting metadata with description extraction after a fetch."""
    from careeros import ingest
    parser = Posting()
    parser.feed(html)
    schema = job_schema(parser, url)
    data = _extract(url, parser, schema)
    fields = ingest.extract(data['description'], function_options=function_options)
    data = _merge_extracted(data, fields, schema, parser)
    mailto = find_mailto(html)
    if mailto:
        data['contact_email'] = mailto
    from careeros.ingest import redact
    return redact(data)


def posting_ats(url):
    """Combine capability tenant recognition with product-owned posting IDs."""
    from types import SimpleNamespace
    from org_intake.ats import detect_ats
    match = detect_ats(url)
    if match is None:
        return None
    parts = urlsplit(url)
    segments = [unquote(s) for s in parts.path.split('/') if s]
    query = dict(parse_qsl(parts.query))
    provider = match['provider']
    if provider == 'refline':
        posting = segments[1:]
        if posting[-1] == 'index.html':
            posting = posting[:-1]
        posting_id = '/'.join(posting)
    elif provider == 'greenhouse':
        posting_id = segments[2]
    elif provider == 'personio':
        posting_id = segments[1] if len(segments) >= 2 and segments[0] == 'job' else query['jobId']
    elif provider == 'workday':
        suffix = re.search(r'_([A-Za-z0-9-]+)$', segments[-1]) if segments else None
        posting_id = suffix.group(1) if suffix else query['jobId']
    elif provider in ('smartrecruiters', 'teamtailor', 'join'):
        segment = segments[2] if provider == 'join' and parts.hostname == 'join.com' else segments[1]
        number = re.match(r'(\d+)', segment)
        posting_id = number.group(1) if number else segment
    else:
        posting_id = segments[1]
    return SimpleNamespace(**match, posting_id=posting_id)

