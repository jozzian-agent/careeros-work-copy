"""Applicant tracking system (ATS) detection.

Pure function, no network I/O. Ported from careeros/url_normalize.py's
detect_ats/AtsMatch. Recognition only (provider, tenant): no posting-id
and no linking logic lives here (see the contract's "Not included" -
the product parses any posting-id out of the URL itself; see identity.py
for linking).
"""
from urllib.parse import urlsplit, parse_qsl, unquote
import re


def _segments(path):
    return [unquote(segment) for segment in path.split('/') if segment]


def detect_ats(url):
    """Return {"provider": str, "tenant": str} for a recognized provider,
    or None.

    detect_ats("https://boards.greenhouse.io/northwind/jobs/9981")
    => {"provider": "greenhouse", "tenant": "northwind"}

    Every host check below is an exact match or a dot-prefixed suffix
    (host.endswith('.' + provider_domain)), never a bare substring: a
    lookalike host like a.myworkdayjobs.com.attacker.example must never be
    recognized just because the provider's domain appears somewhere in it.
    Prefer no detected identity over an unreliable one. A posting-id-shaped
    final path segment or query parameter is still checked where the
    provider's URL shape requires one to tell a real posting URL from an
    unrelated page on the same host; the id itself is not returned.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        # A structurally malformed URL (e.g. an unparseable IPv6 host
        # literal) is no ATS evidence, never a raise (rule 1).
        return None
    host = (parts.hostname or '').casefold()
    segments = _segments(parts.path)
    query = dict(parse_qsl(parts.query))

    if host == 'refline.ch' or host.endswith('.refline.ch'):
        # Numeric tenant, then posting path with /pub/ and a publication
        # suffix. The whole posting path (excluding terminal index.html)
        # must shape-check even though only the tenant is returned.
        posting = segments[1:]
        if posting and posting[-1] == 'index.html':
            posting = posting[:-1]
        if segments and re.fullmatch(r'[0-9]+', segments[0]) \
                and 'pub' in posting[1:-1] \
                and all('/' not in segment for segment in segments):
            return {'provider': 'refline', 'tenant': segments[0]}

    if host in ('boards.greenhouse.io', 'job-boards.greenhouse.io') \
            and len(segments) >= 3 and segments[1] == 'jobs':
        return {'provider': 'greenhouse', 'tenant': segments[0]}

    if host == 'jobs.lever.co' and len(segments) >= 2:
        return {'provider': 'lever', 'tenant': segments[0]}

    if host.endswith('.personio.de') or host.endswith('.personio.com'):
        tenant = host.split('.')[0]
        if len(segments) >= 2 and segments[0] == 'job':
            return {'provider': 'personio', 'tenant': tenant}
        if query.get('jobId'):
            return {'provider': 'personio', 'tenant': tenant}

    if host.endswith('.myworkdayjobs.com'):
        tenant = host.split('.')[0]
        if segments and re.search(r'_([A-Za-z0-9-]+)$', segments[-1]):
            return {'provider': 'workday', 'tenant': tenant}
        if query.get('jobId'):
            return {'provider': 'workday', 'tenant': tenant}

    if host == 'jobs.smartrecruiters.com' and len(segments) >= 2 and re.match(r'\d+', segments[1]):
        return {'provider': 'smartrecruiters', 'tenant': segments[0]}

    if host == 'jobs.ashbyhq.com' and len(segments) >= 2:
        return {'provider': 'ashby', 'tenant': segments[0]}

    if host.endswith('.recruitee.com') and len(segments) >= 2 and segments[0] == 'o':
        return {'provider': 'recruitee', 'tenant': host.split('.')[0]}

    if host.endswith('.teamtailor.com') and len(segments) >= 2 and segments[0] == 'jobs' \
            and re.match(r'\d+', segments[1]):
        return {'provider': 'teamtailor', 'tenant': host.split('.')[0]}

    if host.endswith('.join.com') and len(segments) >= 2 and segments[0] == 'jobs':
        return {'provider': 'join', 'tenant': host.split('.')[0]}

    # join.com also serves postings from its own root domain (no tenant
    # subdomain): /companies/<tenant>/<id>-<slug>.
    if host == 'join.com' and len(segments) >= 3 and segments[0] == 'companies' \
            and re.match(r'\d+', segments[2]):
        return {'provider': 'join', 'tenant': segments[1]}

    return None
