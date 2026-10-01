"""Layered ATS posting extraction; guarded fetching is a replaceable hook."""
from html.parser import HTMLParser
import re
import json
from urllib.parse import urlsplit, unquote
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
        ip = ipaddress.ip_address(address[4][0])
        if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified)):
            raise ValueError('Posting host must resolve only to public IP addresses.')
    return url


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirects are disabled for posting intake.')


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


class Posting(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.title, self.text = {}, [], []
        self.in_title = False
        self.hidden = 0
        self.json_blocks = []
        self.json_buffer = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[(attrs.get('property') or attrs.get('name') or attrs.get('itemprop') or '').lower()] = attrs.get('content', '')
        if tag == 'title':
            self.in_title = True
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.json_buffer = []
        if tag in ('script', 'style'):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag == 'script' and self.json_buffer is not None:
            self.json_blocks.append(''.join(self.json_buffer))
            self.json_buffer = None
        if tag == 'title':
            self.in_title = False
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, value):
        if self.json_buffer is not None:
            self.json_buffer.append(value)
        if self.in_title:
            self.title.append(value)
        if not self.hidden:
            self.text.append(value)


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


def extract(url, html=''):
    parser = Posting()
    parser.feed(html)
    schema = job_schema(parser, url)
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
    if not company:
        company = slug.replace('-', ' ').replace('_', ' ').title() if platform else source.split('.')[0].replace('-', ' ').title()
    website = None
    for candidate in (org.get('sameAs'), org.get('url')):
        if candidate:
            try:
                website = check_url_format(candidate)
                break
            except ValueError:
                pass
    fallback = unquote(urlsplit(url).path.rstrip('/').split('/')[-1]).replace('-', ' ').replace('_', ' ').strip() or (company or 'Job') + ' opportunity'
    title = str(schema.get('title') or meta_title or fallback)
    if not schema.get('title'):
        title = re.split(r'\s+[|–—]\s+|\s+-\s+', title)[0].strip()
        if company:
            title = re.sub(r'\s+(?:at|@)\s+' + re.escape(company) + r'$', '', title, flags=re.I)
    description = Posting()
    description.feed(str(schema.get('description') or ''))
    text = re.sub(r'\s+', ' ', ' '.join(description.text + parser.text))
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
    size = None
    try:
        count = float(employees) if not isinstance(employees, bool) else 0
        if count >= 1:
            size = next((label for limit, label in ((10, '1-10'), (50, '11-50'),
                        (200, '51-200'), (1000, '201-1000')) if count <= limit), '1000+')
    except (TypeError, ValueError):
        pass
    sector = org.get('industry')
    sector = sector if isinstance(sector, str) else None
    return dict(sector=sector, size=size, locations=list(dict.fromkeys(locations)),
                title=title or fallback, company=company, website=website, source=source,
                original_url=url if platform else None, salary_info=bool(salary), salary_note=salary,
                location=', '.join(dict.fromkeys(locations)), remote_ok=remote, posted_date=posted,
                employment_type=str(employment), valid_through=str(schema.get('validThrough') or ''))
