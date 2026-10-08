"""URL normalization and ATS (applicant tracking system) detection.

Journey 1, Step 1: lowercase scheme and host, strip the fragment, strip
tracking query parameters, normalize the trailing slash, and sort the
remaining query parameters for stable comparison. Anything not on the
tracking denylist is preserved as-is, including ATS posting-id query
parameters, since those are identity, not tracking.

ATS detection is recognition only (provider, tenant, posting id): no
linking logic lives here, that is JOZ-266.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, unquote
import re

TRACKING_PARAM_NAMES = frozenset({
    'gclid', 'gclsrc', 'dclid', 'msclkid', 'yclid', 'fbclid', 'igshid',
    'mc_cid', 'mc_eid', 'ref', 'ref_src', 'ref_', '_ga', '_gl',
    'mkt_tok', 'vero_id', 'vero_conv', 'trk', 'trk_campaign',
    'wt_mc_id', 'spm', 's_kwcid', 'icid', 'cmpid',
})


def _is_tracking_param(name):
    lowered = name.casefold()
    return lowered.startswith('utm_') or lowered in TRACKING_PARAM_NAMES


def normalize(url):
    """Return the normalized form of url, or '' for a falsy input."""
    if not url:
        return ''
    parts = urlsplit(url)
    scheme = (parts.scheme or '').casefold()
    host = (parts.hostname or '').casefold()
    port = parts.port
    default_port = (scheme == 'http' and port == 80) or (scheme == 'https' and port == 443)
    netloc = host + ('' if port is None or default_port else f':{port}')
    path = parts.path or '/'
    if len(path) > 1 and path.endswith('/'):
        path = path.rstrip('/') or '/'
    kept = sorted(
        ((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
         if not _is_tracking_param(key)),
        key=lambda pair: (pair[0], pair[1]),
    )
    return urlunsplit((scheme, netloc, path, urlencode(kept), ''))


@dataclass(frozen=True)
class AtsMatch:
    provider: str
    tenant: str
    posting_id: str


def _segments(path):
    return [unquote(segment) for segment in path.split('/') if segment]


def detect_ats(url):
    """Return an AtsMatch for a recognized provider, or None.

    Every host check below is an exact match or a dot-prefixed suffix
    (`host.endswith('.' + provider_domain)`), never a bare substring: a
    lookalike host like `a.myworkdayjobs.com.attacker.example` must never
    be recognized just because the provider's domain appears somewhere in
    it. Prefer no detected identity over an unreliable one (JOZ-265 fix
    round, finding M4)."""
    parts = urlsplit(url)
    host = (parts.hostname or '').casefold()
    segments = _segments(parts.path)
    query = dict(parse_qsl(parts.query))

    if host == 'refline.ch' or host.endswith('.refline.ch'):
        # Numeric tenant, then posting path with /pub/ and a publication
        # suffix. Keep the whole posting path, excluding terminal index.html.
        posting = segments[1:]
        if posting and posting[-1] == 'index.html':
            posting = posting[:-1]
        if segments and re.fullmatch(r'[0-9]+', segments[0]) \
                and 'pub' in posting[1:-1] \
                and all('/' not in segment for segment in segments):
            return AtsMatch('refline', segments[0], '/'.join(posting))

    if host in ('boards.greenhouse.io', 'job-boards.greenhouse.io') \
            and len(segments) >= 3 and segments[1] == 'jobs':
        return AtsMatch('greenhouse', segments[0], segments[2])

    if host == 'jobs.lever.co' and len(segments) >= 2:
        return AtsMatch('lever', segments[0], segments[1])

    if host.endswith('.personio.de') or host.endswith('.personio.com'):
        tenant = host.split('.')[0]
        if len(segments) >= 2 and segments[0] == 'job':
            return AtsMatch('personio', tenant, segments[1])
        if query.get('jobId'):
            return AtsMatch('personio', tenant, query['jobId'])

    if host.endswith('.myworkdayjobs.com'):
        tenant = host.split('.')[0]
        if segments:
            match = re.search(r'_([A-Za-z0-9-]+)$', segments[-1])
            if match:
                return AtsMatch('workday', tenant, match.group(1))
        if query.get('jobId'):
            return AtsMatch('workday', tenant, query['jobId'])

    if host == 'jobs.smartrecruiters.com' and len(segments) >= 2:
        match = re.match(r'(\d+)', segments[1])
        if match:
            return AtsMatch('smartrecruiters', segments[0], match.group(1))

    if host == 'jobs.ashbyhq.com' and len(segments) >= 2:
        return AtsMatch('ashby', segments[0], segments[1])

    if host.endswith('.recruitee.com') and len(segments) >= 2 and segments[0] == 'o':
        return AtsMatch('recruitee', host.split('.')[0], segments[1])

    # The brief names this provider "Teamtail"; the real ATS at this
    # domain is Teamtailor. Treated as the same provider (see BUILD_NOTES).
    if host.endswith('.teamtailor.com') and len(segments) >= 2 and segments[0] == 'jobs':
        match = re.match(r'(\d+)', segments[1])
        if match:
            return AtsMatch('teamtailor', host.split('.')[0], match.group(1))

    if host.endswith('.join.com') and len(segments) >= 2 and segments[0] == 'jobs':
        match = re.match(r'(\d+)', segments[1])
        return AtsMatch('join', host.split('.')[0], match.group(1) if match else segments[1])

    # join.com also serves postings from its own root domain (no tenant
    # subdomain): /companies/<tenant>/<id>-<slug>.
    if host == 'join.com' and len(segments) >= 3 and segments[0] == 'companies':
        match = re.match(r'(\d+)', segments[2])
        if match:
            return AtsMatch('join', segments[1], match.group(1))

    return None
