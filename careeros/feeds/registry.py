"""Which provider adapters exist, and the two ways to ask for one.

Kept apart from `careeros.feeds.__init__` on purpose: the adapters import
`careeros.feeds.base`, so a package `__init__` that imported them would
import itself halfway through. The package docstring is documentation and
this module is the list.

`ADAPTED` are the six providers CareerOS can actually read a feed from.
`COUNTED_ONLY` are the ones the ATS platform map counts from the Common
Crawl index without being able to fetch anything -- Workday above all,
whose share is the input to the owner's "Workday: build or skip"
decision, plus the three smaller ones `org_intake.ats.detect_ats`
already recognises. They are listed here rather than in the platform-map
script because "which providers do we know about" is one fact.
"""
import re
from urllib.parse import urlsplit

from careeros.feeds import (ashby, greenhouse, lever, personio, recruitee,
                            smartrecruiters)

from org_intake.ats import detect_ats

#: Provider id -> adapter module, in the order they were built.
ADAPTED = {
    personio.PROVIDER: personio,
    greenhouse.PROVIDER: greenhouse,
    lever.PROVIDER: lever,
    ashby.PROVIDER: ashby,
    recruitee.PROVIDER: recruitee,
    smartrecruiters.PROVIDER: smartrecruiters,
}

PROVIDERS = tuple(ADAPTED)

#: provider -> ((cdx url, matchType), ...) for a provider with no adapter.
#: The tenant is read out of the indexed URL by `detect_ats` or by the
#: host pattern below; nothing is ever fetched from these hosts.
COUNTED_ONLY = {
    'workday': (('myworkdayjobs.com', 'domain'),),
    'teamtailor': (('teamtailor.com', 'domain'),),
    'join': (('join.com', 'domain'),),
    'refline': (('refline.ch', 'domain'),),
}

#: Providers whose tenant is a PATH segment and never a subdomain.
#: Refline gives every customer a numeric id under one host, so reading
#: its subdomain label as a tenant invents one: the first live probe
#: returned `m` from `m.refline.ch`, which is Refline's mobile host and
#: not a customer.
COUNTED_PATH_ONLY = frozenset({'refline'})

#: The subdomain label of a counted-only provider's URL is the tenant,
#: except for these platform hosts. Same reasoning as an adapter's own
#: `PLATFORM_LABELS`: `www.teamtailor.com` is not a customer.
COUNTED_PLATFORM_LABELS = frozenset({
    'www', 'app', 'api', 'auth', 'cdn', 'assets', 'static', 'help', 'support', 'blog',
    'docs', 'status', 'mail', 'go', 'links', 'wd1', 'wd2', 'wd3', 'wd5', 'wd10', 'wd12',
    'wd101', 'wd103', 'impl', 'impl-services1',
})


class CountedProvider:
    """A provider with no adapter, as much of the contract as discovery
    needs: an id, the crawl patterns to query, and a way to read a tenant
    out of an indexed URL.

    It is deliberately NOT a full adapter and would fail
    `base.check_adapter`: there is no feed to fetch, no mapping and no
    posting. It exists so `discovery.cdx_tenants` can count Workday's
    tenants with the same code path -- and therefore the same paging,
    the same truncation guard and the same terms note -- as the six that
    can be fetched. The owner's "Workday: build or skip" decision needs
    that count to be comparable, not approximate.
    """

    def __init__(self, provider, patterns):
        self.PROVIDER = provider
        self.CDX_PATTERNS = patterns
        self.TENANT_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}')

    def tenant_from_url(self, url):
        """`detect_ats` first, then the subdomain label, then a numeric
        first path segment (which is how Refline names a tenant)."""
        match = detect_ats(url or '')
        parts = urlsplit(url or '')
        host = (parts.hostname or '').casefold()
        if match and match['provider'] == self.PROVIDER:
            return {'tenant': match['tenant'], 'host': host, 'how': 'posting_url'}
        for domain, _ in self.CDX_PATTERNS:
            if host == domain or (self.PROVIDER in COUNTED_PATH_ONLY
                                  and host.endswith('.' + domain)):
                segments = [item for item in (parts.path or '').split('/') if item]
                if segments and re.fullmatch(r'\d+', segments[0]):
                    return {'tenant': segments[0], 'host': host, 'how': 'path_pattern'}
                return None
            if host.endswith('.' + domain):
                label = host[:-(len(domain) + 1)].split('.')[0]
                if label and label not in COUNTED_PLATFORM_LABELS \
                        and re.fullmatch(self.TENANT_ID, label):
                    return {'tenant': label, 'host': host, 'how': 'host_pattern'}
        return None


def counted(provider):
    """The discovery-only shim for a provider with no adapter."""
    if provider not in COUNTED_ONLY:
        raise KeyError(f'{provider!r} is not a counted-only provider; known: '
                       f'{", ".join(sorted(COUNTED_ONLY))}')
    return CountedProvider(provider, COUNTED_ONLY[provider])


def discoverable(provider):
    """The adapter for a provider that has one, else its counting shim.
    What the discovery command takes, so one command covers all ten."""
    return ADAPTED[provider] if provider in ADAPTED else counted(provider)


def adapter(provider):
    """One adapter module by provider id."""
    if provider not in ADAPTED:
        raise KeyError(f'no adapter for {provider!r}; known: {", ".join(PROVIDERS)}')
    return ADAPTED[provider]


def adapters(providers=None):
    """Several adapters by id, or every one of them."""
    return [adapter(name) for name in (providers or PROVIDERS)]


def identify(url):
    """Which adapted provider and tenant a URL names, or None.

    Every adapter is asked, in registry order, and the first answer wins.
    This is what the ATS platform map runs over a crawl index and over a
    company's careers page, and what makes "which platform does this
    company use" a question with one answer rather than six.
    """
    for module in ADAPTED.values():
        match = module.tenant_from_url(url)
        if match:
            return {**match, 'provider': module.PROVIDER}
    return None
