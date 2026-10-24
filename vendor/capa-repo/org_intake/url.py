"""URL normalization for organisation/posting URLs.

Pure function, no network I/O. Ported from careeros/url_normalize.py
(normalize) and careeros/intake.py (domain). Lowercases scheme and host,
strips the fragment, strips tracking query parameters, normalizes the
trailing slash, and sorts the remaining query parameters for stable
comparison. Anything not on the tracking denylist is preserved as-is,
including ATS posting-id query parameters, since those are identity, not
tracking.
"""
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING_PARAM_NAMES = frozenset({
    'gclid', 'gclsrc', 'dclid', 'msclkid', 'yclid', 'fbclid', 'igshid',
    'mc_cid', 'mc_eid', 'ref', 'ref_src', 'ref_', '_ga', '_gl',
    'mkt_tok', 'vero_id', 'vero_conv', 'trk', 'trk_campaign',
    'wt_mc_id', 'spm', 's_kwcid', 'icid', 'cmpid',
})

# co.uk-shaped second-level domains where the registrable domain needs three
# labels instead of two, so normalize_url's domain() helper does not treat
# "example" as the organisation's domain for "example.co.uk".
_TWO_LABEL_SUFFIXES = frozenset({'co.uk', 'com.au', 'co.nz', 'co.jp', 'com.br', 'co.in'})


def _is_tracking_param(name):
    lowered = name.casefold()
    return lowered.startswith('utm_') or lowered in TRACKING_PARAM_NAMES


def normalize_url(url):
    """Return the normalized form of url, or '' for a falsy input.

    normalize_url("HTTPS://Example.com/jobs/?utm_source=x&b=1&a=2")
    => "https://example.com/jobs?a=2&b=1"
    """
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


def domain(url):
    """Registrable-ish domain of url's host: the last two labels, or three
    for a known two-label public suffix (co.uk and similar). A
    structurally malformed url (e.g. an unparseable IPv6 host literal)
    never raises; it is simply treated as having no domain (rule 1)."""
    try:
        host = urlsplit(url).hostname or ''
    except ValueError:
        return ''
    parts = host.lower().split('.')
    count = 3 if '.'.join(parts[-2:]) in _TWO_LABEL_SUFFIXES else 2
    return '.'.join(parts[-count:])
