"""The ATS adapters' runner: probe, discover, fetch, export, report, map.

CAREER-54. Everything this script does lives in `careeros.feeds`; this
file is the command line, the wiring to `polite_http` (the one thing that
touches the network) and the printing. `scripts/run_personio_fetch.py` is
the same program with Personio's defaults filled in, kept so CAREER-53's
own command line still works.

## Subcommands

  probe-vault  read the vault's companies' own websites once, for every
               provider at once, and write what they link to
  discover     find tenants for one provider and write its tenants.yaml
  fetch        fetch each tenant's feed, freeze snapshots, update closure
               state, and write a run entry to runs.yaml
  export       write the golden-set pool, over one provider or all of them
  compress     zstd-pack the posting snapshots nothing has touched for a
               month, over one provider or all of them (dry run by default)
  report       print the daily run report for the last (or a named) run
  map          build the ATS platform map and its report

Every one of them is idempotent and safe to re-run. `discover` merges
rather than replaces and never downgrades a confirmed tenant. `fetch`
writes a new snapshot only when a posting's content hash changed. A
second `export` or `map` on the same day overwrites that day's file,
which is derived and the only thing here that is not immutable.
`compress` changes how a snapshot is stored and never what it says, and
needs `--apply` to change anything at all.

## One store per provider

    data/personio/          CAREER-53's store, exactly where it was
    data/ats/<provider>/    the five CAREER-54 added
    data/ats/exports/       the multi-provider golden-set pool
    data/ats_platform_map*  the platform map and its report (tracked)

`--root` overrides the first two. Nothing writes to the vault:
`--vault` is read for discovery route 1 and route 2 and for nothing
else, the same rule `scripts/seed_zefix_zurich.py` follows.

## Politeness and robots

One global rate limiter per run, so the cap is one request a second for
the whole run and not per tenant or per provider. `robots.txt` is read
once per provider per run -- for the four providers with a central API
host that is the API host, and for the two whose feed lives on a
per-tenant subdomain (Personio, Recruitee) it is the first tenant's,
because that subdomain is the provider's own configuration rather than
the tenant's.

**A provider whose robots.txt disallows us is not fetched** unless the
run is given `--robots-exception <provider>`, which prints the robots
lines and records the exception in the run entry. That is one provider
today: SmartRecruiters allows only LinkedIn's crawler on the path its
own documentation publishes as public and unauthenticated. The reasoning,
the quote and the owner question are in
`careeros/feeds/smartrecruiters.py` and `data/ats/TRIAL_REPORT.md`.

## Daily shape (NOT installed -- the brief says do not install a cron job)

One discovery pass a week per provider and one fetch pass a day, because
tenants appear slowly and postings close quickly.

    # /etc/cron.d/careeros-ats  -- one tab-free line each
    20 6 * * *  careeros  cd /srv/careeros && .venv/bin/python \\
        scripts/run_ats_fetch.py fetch --provider greenhouse \\
        >> /var/log/careeros/ats-fetch.log 2>&1
    40 5 * * 1  careeros  cd /srv/careeros && .venv/bin/python \\
        scripts/run_ats_fetch.py discover --provider greenhouse \\
        --common-crawl >> /var/log/careeros/ats-discover.log 2>&1

As a systemd timer pair, `Persistent=true` matters: closure detection
counts SUCCESSFUL fetches, not days, so a run the machine slept through
must happen late rather than not at all. `RandomizedDelaySec` matters
too: one request a second against one vendor, started at the same second
every day, is the shape of a thing worth not being.
"""
import argparse
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import polite_http  # noqa: E402
import ats_overview  # noqa: E402  (reused: its link parser and careers-page heuristic)

from careeros import vault  # noqa: E402
from careeros.feeds import (discovery, export, fetch as fetch_module, geocode,  # noqa: E402
                            personio, platform_map, registry)
from careeros.feeds import store as store_module  # noqa: E402

#: Where a provider's store lives when `--root` says nothing. Personio's
#: is an override because CAREER-53 put it there and moving it would move
#: every snapshot it has taken.
DEFAULT_ROOT_BASE = Path('data/ats')
PROVIDER_ROOTS = {personio.PROVIDER: Path('data/personio')}

#: The newest Common Crawl index, resolved live from collinfo.json. More
#: than one index is worth querying -- a tenant that existed in March and
#: not in September is still a tenant -- and `--crawls` says how many.
DEFAULT_CRAWLS = 1

#: Every provider the command line accepts: the six with an adapter plus
#: the four the platform map only counts.
ALL_PROVIDERS = tuple(registry.PROVIDERS) + tuple(sorted(registry.COUNTED_ONLY))


def _root(args, provider=None):
    provider = provider or getattr(args, 'provider', None)
    if getattr(args, 'root', None):
        return Path(args.root)
    return PROVIDER_ROOTS.get(provider, DEFAULT_ROOT_BASE / str(provider))


def _store(args, provider=None):
    provider = provider or args.provider
    return store_module.Store(_root(args, provider), provider=provider)


def _limiter(args):
    return polite_http.RateLimiter(min_interval=args.min_interval)


def _providers(args):
    """Which providers a command runs over: `--provider`, or all the
    adapted ones when `--all-providers` is given."""
    if getattr(args, 'all_providers', False):
        return list(registry.PROVIDERS)
    return [args.provider]


# --- probe-vault ------------------------------------------------------------

def cmd_probe_vault(args):
    """Discovery route 2, once for every provider.

    One pass over the vault's companies' own websites, reading what each
    one links to for every provider at the same time. Run per provider it
    would fetch the same homepage six times; the result file is what each
    provider's `discover` then reads.

    This also absorbs CAREER-52's vault-domain probe
    (`scripts/ats_overview.py`): same route, same two-requests-per-company
    budget, same robots rule, but it records the TENANT and the evidence
    URL rather than only which provider was seen, which is what the
    platform map needs.
    """
    limiter = _limiter(args)
    companies = vault.list_companies(args.vault)
    # Every stored job, universe-only pool records included
    # (list_owned_jobs unscoped): this asks what the vault knows about an
    # ATS tenant and is not a surface anybody reads.
    jobs = vault.list_owned_jobs(args.vault)
    found, report = _probe_websites(companies, limiter=limiter, cap=args.max,
                                     probe=not args.no_probe)
    recorded = {}
    for provider in ALL_PROVIDERS:
        adapter = registry.discoverable(provider)
        route = discovery.tenants_from_vault(companies, jobs, adapter=adapter)
        for tenant, entry in route.items():
            recorded.setdefault(provider, {})[tenant] = entry
    payload = {
        'probed_at': store_module.now(),
        'vault': str(args.vault),
        'companies_read': len(companies),
        'jobs_read': len(jobs),
        'probe': report,
        'from_websites': {provider: list(entries.values())
                          for provider, entries in sorted(found.items())},
        'from_vault_records': {provider: list(entries.values())
                               for provider, entries in sorted(recorded.items())},
        'note': ('from_vault_records is what the vault already knows (a stored ats_tenant '
                 'identifier, a stored posting URL or a company website that is itself an ATS '
                 'URL) and needs no network. from_websites is what probing the company site '
                 'found. Both are evidence levels the platform map keeps apart.'),
    }
    path = Path(args.out or DEFAULT_ROOT_BASE / f'vault_probe_{date.today().isoformat()}.yaml')
    store_module.write_yaml(path, payload)
    print(f"{report['probed']} site(s) probed, {report['pages']} page(s) read, "
          f"{report['skipped']} skipped")
    for provider, entries in sorted(found.items()):
        print(f'  {provider}: {len(entries)} tenant(s) from a company website')
    for provider, entries in sorted(recorded.items()):
        print(f'  {provider}: {len(entries)} tenant(s) already in the vault')
    print(f'written to {path}')
    return 0


def _probe_websites(companies, *, limiter, cap, probe=True):
    """Fetch each company's homepage and one careers link, and read every
    provider's tenant out of the links.

    Wired to `ats_overview`'s own page reader: that script already
    fetches a homepage, finds the careers link and parses the links out
    of both, with the robots check and the rate limit in the right
    places. Reusing its `page_links` and `looks_like_careers` is the
    difference between a second implementation of link scraping and none.
    """
    report = {'probed': 0, 'pages': 0, 'skipped': 0, 'with_tenant': 0, 'companies': []}
    robots_cache, found = {}, {}
    targets = [record for record in companies if record.get('website')][:cap]
    if not probe:
        report['skipped'] = len(targets)
        return found, report
    for index, record in enumerate(targets, 1):
        start = record['website']
        row = {'name': record.get('name'), 'company_id': record.get('id'), 'website': start,
               'providers': [], 'skip_reason': None}
        allowed, reason = polite_http.robots_allows(start, cache=robots_cache, limiter=limiter)
        if not allowed:
            report['skipped'] += 1
            row['skip_reason'] = reason
            report['companies'].append(row)
            continue
        report['probed'] += 1
        home = polite_http.request_text(start, limiter=limiter)
        if not home['ok']:
            row['skip_reason'] = f"homepage: {home['error']}"
            report['companies'].append(row)
            continue
        report['pages'] += 1
        links = ats_overview.page_links(home['text'], home['final_url'])
        candidates = [home['final_url']] + links
        careers = next((link for link in links if ats_overview.looks_like_careers(link)), None)
        if careers:
            row['careers_url'] = careers
            allowed, _ = polite_http.robots_allows(careers, cache=robots_cache, limiter=limiter)
            if allowed:
                page = polite_http.request_text(careers, limiter=limiter)
                if page['ok']:
                    report['pages'] += 1
                    candidates += [page['final_url']] + ats_overview.page_links(
                        page['text'], page['final_url'])
        # Every provider, including the four with no adapter: a careers
        # page that links to Workday is exactly the evidence the "build
        # or skip" decision needs, and it is also what CAREER-52's own
        # vault probe found and this run absorbs.
        for provider in ALL_PROVIDERS:
            route = discovery.tenants_from_urls(candidates, discovered_via='company_website',
                                                company=record.get('name'),
                                                adapter=registry.discoverable(provider))
            if not route:
                continue
            row['providers'].append({'provider': provider, 'tenants': sorted(route)})
            found.setdefault(provider, {}).update(
                {key: value for key, value in route.items()
                 if key not in found.get(provider, {})})
        if row['providers']:
            report['with_tenant'] += 1
            print(f"  [{index:>3}/{len(targets)}] {record.get('name')}: "
                  + ', '.join(f"{item['provider']}:{','.join(item['tenants'])}"
                              for item in row['providers']))
        report['companies'].append(row)
    return found, report


# --- discover ---------------------------------------------------------------

def cmd_discover(args):
    adapter = registry.discoverable(args.provider)
    store = _store(args)
    limiter = _limiter(args)
    stored = store.load_tenants()
    found, routes = {}, {}

    if args.vault and args.provider in registry.PROVIDERS:
        companies = vault.list_companies(args.vault)
        # Unscoped and unfiltered, same reason as the probe above.
        jobs = vault.list_owned_jobs(args.vault)
        route = discovery.tenants_from_vault(companies, jobs, adapter=adapter)
        routes['vault'] = {'tenants': len(route), 'companies_read': len(companies),
                           'jobs_read': len(jobs)}
        found.update(route)
        print(f'vault: {len(route)} tenant(s) from {len(companies)} companies '
              f'and {len(jobs)} jobs')

        if args.probe_websites:
            route, report = _probe_websites(companies, limiter=limiter, cap=args.probe_websites)
            route = route.get(args.provider, {})
            routes['company_websites'] = report
            found.update({key: value for key, value in route.items() if key not in found})
            print(f"company websites: {len(route)} tenant(s) from {report['probed']} "
                  f"site(s) probed ({report['pages']} page(s) read)")

    if args.probe_file:
        route, report = _from_probe_file(args.probe_file, args.provider)
        routes['probe_file'] = report
        found.update({key: value for key, value in route.items() if key not in found})
        print(f"probe file: {len(route)} tenant(s) from {args.probe_file}")

    if args.common_crawl:
        route, report = _common_crawl(args, adapter=adapter, limiter=limiter)
        routes['common_crawl'] = report
        found.update({key: value for key, value in route.items() if key not in found})
        print(f"common crawl: {len(route)} tenant(s) from {report['urls']} indexed URL(s)")

    merged, added = discovery.merge_tenants(stored, found, first_seen=date.today().isoformat())
    seeded = _load_zefix(args.zefix_file)
    matches = discovery.zefix_matches(merged, seeded)
    for tenant, match in matches.items():
        merged[tenant]['zefix_match'] = match
    store.save_tenants(merged, meta={'discovery_routes': routes,
                                     'zefix_seed_file': str(args.zefix_file) if seeded else None,
                                     'zefix_candidates': len(matches),
                                     'fetchable': args.provider in registry.PROVIDERS,
                                     'sources': {'common_crawl_terms': discovery.CDX_TERMS,
                                                 'api_doc': getattr(adapter, 'DOC_URL', None),
                                                 'api_doc_accessed': getattr(
                                                     adapter, 'DOC_ACCESSED', None)}})
    print(f'{len(merged)} tenant(s) in {store.tenants_file} (+{len(added)} new); '
          f'{len(matches)} name-only Zefix candidate(s)')
    return 0


def _from_probe_file(path, provider):
    """Route 2 out of a `probe-vault` run, so the websites are read once
    for six providers instead of six times."""
    data = store_module.read_yaml(path, {}) or {}
    entries = {}
    for section in ('from_vault_records', 'from_websites'):
        for entry in (data.get(section) or {}).get(provider) or ():
            entries.setdefault(entry['tenant'], entry)
    return entries, {'file': str(path), 'tenants': len(entries),
                     'probed_at': data.get('probed_at')}


def _common_crawl(args, *, adapter, limiter):
    """Route 3, live or replayed.

    `--from-file` reads CDX JSONL exactly as the index API serves it, so
    the file a live run saves with `--save-cdx` is the file a replay
    reads: a discovery run is reproducible, and the owner who declines
    the robots.txt reasoning (see `careeros.feeds.discovery`) can run
    discovery with no live call at all.
    """
    if args.from_file:
        lines = Path(args.from_file).read_text().splitlines()
        tenants, stats = discovery.tenants_from_cdx_lines(
            lines, adapter=adapter,
            discovered_via=f'common_crawl_replay:{Path(args.from_file).name}')
        return tenants, {'replayed_from': str(args.from_file), 'urls': stats['urls'],
                         'malformed_lines': stats['malformed'],
                         'truncated': stats['truncated'], 'tenants': len(tenants)}
    collections = discovery.cdx_collections(fetch=polite_http.request_text, limiter=limiter)
    crawls = [item['id'] for item in collections[:args.crawls]]
    tenants, reports, raw = {}, [], []
    for crawl in crawls:
        print(f'  querying Common Crawl index {crawl} ...')
        route, report = discovery.cdx_tenants(crawl, fetch=polite_http.request_text,
                                              limiter=limiter, adapter=adapter,
                                              max_pages=args.max_cdx_pages,
                                              keep_lines=bool(args.save_cdx))
        raw.extend(report.pop('raw_lines', []))
        reports.append(report)
        tenants.update({key: value for key, value in route.items() if key not in tenants})
        print(f"    {report['urls']} URL(s), {report['tenants']} tenant(s), "
              f"{report['failed_pages']} page(s) lost "
              f"({report['truncated_pages']} truncated)")
    if args.save_cdx and raw:
        Path(args.save_cdx).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save_cdx).write_text('\n'.join(raw) + '\n')
        print(f'  saved {len(raw)} raw index line(s) to {args.save_cdx}')
    return tenants, {'crawls': crawls, 'urls': sum(item['urls'] for item in reports),
                     'failed_pages': sum(item['failed_pages'] for item in reports),
                     'truncated_pages': sum(item['truncated_pages'] for item in reports),
                     'per_crawl': reports, 'tenants': len(tenants),
                     'saved_cdx': str(args.save_cdx) if args.save_cdx and raw else None}


def _load_zefix(path):
    """The parked Zefix staging file, for dedupe by name only."""
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        print(f'zefix: {path} not found; dedupe skipped')
        return []
    data = store_module.read_yaml(path, {}) or {}
    return list(data.get('companies') or ())


# --- fetch ------------------------------------------------------------------

def cmd_fetch(args):
    if args.provider not in registry.PROVIDERS:
        print(f'{args.provider} has no adapter: the platform map counts its tenants from the '
              'crawl index and nothing fetches them')
        return 1
    adapter = registry.adapter(args.provider)
    store = _store(args)
    limiter = _limiter(args)
    tenants = store.load_tenants()
    if not tenants:
        print(f'no tenants in {store.tenants_file}; run discover first')
        return 1

    queue = _fetch_queue(tenants, args)
    run = store.next_run_id()
    at = store_module.now()
    print(f'run {run}: fetching {len(queue)} of {len(tenants)} {args.provider} tenant(s)')

    options = _variant_options(args, adapter)
    summaries, parse_failures, posting_failures = {}, [], []
    requests_made, robots = 0, None
    for index, tenant in enumerate(queue, 1):
        record = tenants[tenant]
        if robots is None:
            robots = _robots_gate(adapter, tenant, limiter=limiter,
                                  exceptions=args.robots_exception or ())
            if not robots['proceed']:
                print(f"  robots.txt refuses {args.provider}: {robots['reason']}\n"
                      f"  nothing was fetched. Pass --robots-exception {args.provider} to "
                      'proceed anyway, which records the exception in the run entry.')
                return 2
        try:
            result = fetch_module.fetch_tenant(
                tenant, store=store, run=run, fetch=polite_http.request_text, limiter=limiter,
                adapter=adapter, conditional=record.get('feeds') or {}, at=at,
                guide_version=args.guide_version, detail=args.detail, **options)
        except ValueError as error:
            # A stored tenant id this adapter will not build a URL for.
            # One tenant's bad id must not end a 150-tenant run, and the
            # tenant is recorded as skipped with the reason rather than
            # dropped (PROJECT.md: failures are visible states).
            result = {'tenant': tenant, 'fetch_status': 'bad_tenant_id', 'error': f'{error}',
                      'host': None, 'languages': {}, 'postings': [], 'publishes': {},
                      'parse_failures': [], 'posting_failures': [], 'requests': 0,
                      'etags': {}, 'details': {'requested': 0, 'ok': 0, 'failed': 0}}
        parse_failures.extend(result['parse_failures'])
        posting_failures.extend(result['posting_failures'])
        requests_made += result['requests']
        zurich = [posting for posting in result['postings']
                  if posting['area_status'] == geocode.IN_AREA]
        _update_tenant(record, result, run=run, at=at, zurich=zurich)
        # FOLD THIS TENANT NOW, so its postings can be released before
        # the next one is fetched (CAREER-93). Keeping every tenant's
        # result for the whole run grew with the tenant count: the
        # 2026-10-20 greenhouse run died at tenant 2294 of 2319 and the
        # kernel killed the owner's Telegram bot rather than the script.
        # `record_run` already folds one tenant at a time and touches
        # only that tenant's own state file, so a run folded per tenant
        # writes exactly what a run folded at the end wrote.
        changes = store_module.record_run(store, run=run, at=at,
                                          tenant_results={tenant: result})[tenant]
        summaries[tenant] = _tenant_summary(result, changes, zurich=len(zurich))
        print(f"  [{index:>4}/{len(queue)}] {tenant:<42} {result['fetch_status']:<12} "
              f"{len(result['postings']):>4} posting(s), {len(zurich):>3} in ZH"
              + (f" -- {result['error']}" if result['error'] else ''))
        del result, zurich, changes

    entry = _run_entry(run, at, queue, summaries, parse_failures,
                       posting_failures=posting_failures, requests_made=requests_made,
                       limiter=limiter, args=args, adapter=adapter, robots=robots)
    store.append_run(entry)
    store.save_tenants(tenants, meta={'last_fetch_run': run})
    _print_run(entry)
    return 0


def _variant_options(args, adapter):
    """The CLI options this adapter's `feed_variants` accepts.

    Only Personio has any (`languages`), and a provider with no language
    must not be handed one, so the adapter declares what it takes.
    """
    accepted = getattr(adapter, 'VARIANT_OPTIONS', ())
    options = {}
    if 'languages' in accepted and getattr(args, 'languages', None):
        options['languages'] = tuple(args.languages)
    return options


def _robots_gate(adapter, tenant, *, limiter, exceptions):
    """Read this provider's robots.txt once per run and decide.

    See the module docstring: one check per provider, against the API
    host or -- for the two providers whose feed lives on a per-tenant
    subdomain -- the first tenant's, because that subdomain is the
    provider's own configuration.
    """
    url = adapter.feed_variants(tenant)[0].url
    allowed, reason = polite_http.robots_allows(url, limiter=limiter)
    excepted = adapter.PROVIDER in (exceptions or ())
    answer = {'url': url, 'allowed': allowed, 'reason': reason, 'requests': 1,
              'exception_used': bool(not allowed and excepted),
              'proceed': bool(allowed or excepted)}
    if answer['exception_used']:
        print(f"  robots.txt disallows {adapter.PROVIDER} ({reason}); proceeding under the "
              '--robots-exception flag. The provider\'s own documentation publishes this '
              'endpoint as public and unauthenticated; the owner question is recorded in '
              'data/ats/TRIAL_REPORT.md.')
        if getattr(adapter, 'ROBOTS_TXT', None):
            for line in adapter.ROBOTS_TXT.splitlines():
                print(f'    {line}')
    return answer


def _fetch_queue(tenants, args):
    """Which tenants this run fetches, and in which order.

    Confirmed Zurich tenants first, then candidates nothing has fetched
    yet, then the rest. A capped trial run should spend its budget on the
    tenants the pool is actually made of, and a `--max-tenants` cap that
    cut off the confirmed ones would make the pool shrink every run.
    """
    if args.tenants:
        return [tenant for tenant in args.tenants if tenant in tenants]
    eligible = [tenant for tenant, record in tenants.items()
                if record.get('status') != discovery.SKIPPED or args.include_skipped]
    if args.sample:
        # A capped run is otherwise alphabetical, which is fine for
        # getting work done and useless for measuring anything: the
        # share of discovered tenants that have a Zurich office cannot
        # be estimated from the tenants whose ids start with a digit.
        # `--sample` draws from the whole queue with a stated seed, so a
        # trial number is a sample statistic and a re-run reproduces it.
        return random.Random(args.seed).sample(sorted(eligible),
                                               min(args.sample, len(eligible)))
    order = {discovery.CONFIRMED_ZURICH: 0, discovery.CANDIDATE: 1,
             discovery.NO_ZURICH_OFFICE: 2, discovery.SKIPPED: 3}
    queue = sorted(eligible,
                   key=lambda tenant: (order.get(tenants[tenant].get('status'), 9),
                                       tenants[tenant].get('last_fetch_run') or '',
                                       tenant))
    return queue[:args.max_tenants] if args.max_tenants else queue


def _update_tenant(record, result, *, run, at, zurich):
    """A tenant's own record after a fetch: status, feed state, counts.

    `confirmed_zurich` once a posting of its feed has geocoded to canton
    Zurich, and it STAYS confirmed: a tenant whose Zurich postings are
    all closed today is still a Zurich employer, and demoting it would
    drop it out of the fetch queue's front and hide its next opening.
    """
    record['last_fetch_run'] = run
    record['last_fetch_at'] = at
    record['last_fetch_status'] = result['fetch_status']
    record['last_fetch_error'] = result['error']
    record['feed_host'] = result['host'] or record.get('feed_host')
    # MERGED, not replaced: a variant this run skipped (because the
    # tenant publishes nothing in it) returns no etag entry, and
    # overwriting would lose the `publishes: False` marker -- which would
    # make the skip work only every other run.
    record['feeds'] = {**(record.get('feeds') or {}), **(result['etags'] or {})}
    record['postings_seen'] = len(result['postings'])
    record['zurich_postings_seen'] = len(zurich)
    if result['fetch_status'] != fetch_module.FETCH_OK:
        if record.get('status') == discovery.CANDIDATE:
            record['status'] = discovery.SKIPPED
            record['status_reason'] = f"feed unreadable: {result['fetch_status']}"
        return
    if not record.get('company_name'):
        names = [posting.get('employer_name') for posting in result['postings']
                 if posting.get('employer_name')]
        record['company_name'] = names[0] if names else None
    if zurich:
        record['status'] = discovery.CONFIRMED_ZURICH
        record['status_reason'] = (f"{len(zurich)} posting(s) geocode to canton Zurich, "
                                   f"e.g. {zurich[0]['location'].get('office')}")
        record['municipalities'] = sorted({posting['municipality'] for posting in zurich
                                           if posting['municipality']})
    elif record.get('status') != discovery.CONFIRMED_ZURICH:
        record['status'] = discovery.NO_ZURICH_OFFICE
        record['status_reason'] = ('the feed parsed and no office geocodes to canton Zurich'
                                   if result['postings'] else
                                   'the feed parsed and is empty, so it states no office')


def _tenant_summary(result, changes, *, zurich):
    """Everything the run entry needs about ONE tenant, in numbers.

    This is what makes the fetch loop flat in memory: the postings are
    counted here and then released, so nothing in the run holds a mapped
    posting after its own tenant was folded into the store. Every value
    is a scalar or a short list of keys -- never a posting.
    """
    postings = result['postings'] or ()
    review_swiss = [posting for posting in postings
                    if posting['area_status'] == geocode.NEEDS_REVIEW
                    and posting.get('swiss_evidence')]
    return {
        'fetch_status': result['fetch_status'],
        'error': result['error'],
        'postings': len(postings),
        'requests': result['requests'],
        'publishes': result['publishes'],
        'zurich': zurich,
        'zurich_geocoded': sum(1 for posting in postings
                               if posting['area_status'] == geocode.IN_AREA
                               and posting['municipality']),
        'zurich_corroborated': sum(1 for posting in postings
                                   if posting['area_status'] == geocode.IN_AREA
                                   and posting.get('corroborated')),
        'offices_unresolved': sum(1 for posting in postings
                                  if posting['area_status'] == geocode.NEEDS_REVIEW),
        'offices_needing_review': len(review_swiss),
        # The 20 alphabetically first office names this tenant could not
        # resolve. The run's own first 20 are among the union of its
        # tenants' first 20, so the entry carries exactly what it carried
        # when the whole run was held in memory.
        'office_examples': sorted({(posting.get('location') or {}).get('office') or ''
                                   for posting in review_swiss})[:20],
        'feeds_read': sum(1 for report in result['languages'].values()
                          if isinstance(report, dict) and report.get('positions') is not None),
        'details': {key: (result.get('details') or {}).get(key, 0)
                    for key in ('requested', 'ok', 'failed')},
        'new': len(changes['new']),
        'changed': len(changes['changed']),
        'closed': len(changes['closed']),
        'suspected': len(changes['suspected']),
        'reopened': len(changes['reopened']),
        'closed_keys': list(changes['closed']),
        'reopened_keys': list(changes['reopened']),
    }


def _total(summaries, key):
    return sum(summary[key] for summary in summaries.values())


def _run_entry(run, at, queue, summaries, parse_failures, *, posting_failures,
               requests_made, limiter, args, adapter=personio, robots=None):
    """The run's own entry in runs.yaml, added up from the per-tenant
    summaries alone (see `_tenant_summary`): same keys, same numbers and
    the same `_print_run` output as when it was added up from every
    tenant's retained postings."""
    ok = [tenant for tenant, summary in summaries.items()
          if summary['fetch_status'] == fetch_module.FETCH_OK]
    examples = set()
    for summary in summaries.values():
        examples = set(sorted(examples | set(summary['office_examples']))[:20])
    return {
        'run_id': run,
        'at': at,
        'provider': adapter.PROVIDER,
        'api_doc_url': getattr(adapter, 'DOC_URL', None),
        'api_doc_accessed': getattr(adapter, 'DOC_ACCESSED', None),
        'robots': robots,
        'tenants_queued': len(queue),
        'tenants_ok': len(ok),
        'tenants_failed': len(queue) - len(ok),
        'failures': {tenant: {'status': summary['fetch_status'], 'error': summary['error']}
                     for tenant, summary in sorted(summaries.items())
                     if summary['fetch_status'] != fetch_module.FETCH_OK},
        'failure_kinds': _tally_values([summary['fetch_status']
                                        for summary in summaries.values()]),
        'feeds_read': _total(summaries, 'feeds_read'),
        'parse_failures': parse_failures,
        'posting_failures': posting_failures,
        'postings_seen': _total(summaries, 'postings'),
        'details': {key: sum(summary['details'][key] for summary in summaries.values())
                    for key in ('requested', 'ok', 'failed')},
        'zurich_postings': _total(summaries, 'zurich'),
        'zurich_geocoded_to_municipality': _total(summaries, 'zurich_geocoded'),
        'zurich_corroborated': _total(summaries, 'zurich_corroborated'),
        'offices_unresolved': _total(summaries, 'offices_unresolved'),
        'offices_needing_review': _total(summaries, 'offices_needing_review'),
        'offices_needing_review_examples': sorted(examples),
        'new_postings': _total(summaries, 'new'),
        'changed_postings': _total(summaries, 'changed'),
        'closed_postings': _total(summaries, 'closed'),
        'suspected_closing': _total(summaries, 'suspected'),
        'reopened_postings': _total(summaries, 'reopened'),
        'closed_keys': sorted(key for summary in summaries.values()
                              for key in summary['closed_keys']),
        'reopened_keys': sorted(key for summary in summaries.values()
                                for key in summary['reopened_keys']),
        # Feed requests only. The robots.txt read is counted beside it
        # rather than in it, because `requests` is what the parse and
        # dead-rate numbers are divided by and one robots read per run
        # would skew a small trial. Both went through the same limiter,
        # so `slept_seconds` covers them together.
        'requests': requests_made,
        'robots_requests': (robots or {}).get('requests', 0),
        'rate_limit_seconds': limiter.min_interval,
        'slept_seconds': round(limiter.slept, 1),
        'user_agent': polite_http.USER_AGENT,
        'languages': list(getattr(args, 'languages', []) or []),
        'sample': {'size': args.sample, 'seed': args.seed} if getattr(args, 'sample', None)
                  else None,
        'per_tenant': {tenant: {'fetch_status': summary['fetch_status'],
                                'postings': summary['postings'],
                                'requests': summary['requests'],
                                'publishes': summary['publishes'],
                                'new': summary['new'],
                                'changed': summary['changed'],
                                'closed': summary['closed']}
                       for tenant, summary in sorted(summaries.items())},
    }


def _tally_values(values):
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def _print_run(entry):
    parse_rate = (100.0 * (entry['feeds_read'] - len(entry['parse_failures']))
                  / entry['feeds_read']) if entry['feeds_read'] else 0.0
    geocode_rate = (100.0 * entry['zurich_geocoded_to_municipality']
                    / entry['zurich_postings']) if entry['zurich_postings'] else 0.0
    print(f"\nrun {entry['run_id']} ({entry.get('provider')})")
    print(f"  tenants: {entry['tenants_ok']} ok, {entry['tenants_failed']} failed")
    print(f"  postings: {entry['postings_seen']} seen, {entry['zurich_postings']} in Zurich "
          f"({entry['zurich_geocoded_to_municipality']} with a municipality, "
          f"{geocode_rate:.1f}%)")
    print(f"  offices unresolved: {entry.get('offices_unresolved', 0)}, of which "
          f"{entry['offices_needing_review']} name something Swiss and go on the review list")
    print(f"  changes: {entry['new_postings']} new, {entry['changed_postings']} changed, "
          f"{entry['closed_postings']} closed, {entry['suspected_closing']} suspected closing, "
          f"{entry['reopened_postings']} reopened")
    print(f"  parse success: {parse_rate:.1f}% over {entry['feeds_read']} feed(s) read")
    if (entry.get('details') or {}).get('requested'):
        print(f"  posting details: {entry['details']['ok']} fetched, "
              f"{entry['details']['failed']} failed")
    print(f"  requests: {entry['requests']} at >={entry['rate_limit_seconds']}s apart")
    for tenant, failure in list(entry['failures'].items())[:10]:
        print(f"    failed: {tenant}: {failure['status']} {failure['error'] or ''}")


# --- export -----------------------------------------------------------------

def cmd_export(args):
    providers = _providers(args)
    stores = [_store(args, provider) for provider in providers
              if provider in registry.PROVIDERS]
    rows, skipped = export.build_pool(stores, include_out_of_area=args.include_out_of_area)
    summary = export.summarise(rows)
    target = (store_module.Store(DEFAULT_ROOT_BASE, provider='combined')
              if len(stores) > 1 else stores[0])
    path = export.write_pool(target, rows, day=args.day or date.today().isoformat(),
                             summary=summary,
                             meta={'skipped': len(skipped),
                                   'skipped_reasons': _tally(skipped),
                                   'include_out_of_area': args.include_out_of_area,
                                   'stores': [str(item.root) for item in stores],
                                   'taxonomy_version': _taxonomy_versions()})
    print(f"{len(rows)} posting(s) exported to {path}")
    print(f"  providers {summary['providers']}, tenants {summary['tenants']}, "
          f"companies {summary['companies']}, municipalities {summary['municipalities']}")
    for provider, counts in summary['by_provider'].items():
        print(f"    {provider:<16} {counts['postings']:>5} posting(s) from "
              f"{counts['tenants']} tenant(s), {counts['with_description']} with text")
    print(f"  with a salary signal: {summary['with_salary_signal']}")
    print(f"  skipped: {len(skipped)} ({_tally(skipped)})")
    return 0


def _tally(skipped):
    counts = {}
    for item in skipped:
        counts[item['reason']] = counts.get(item['reason'], 0) + 1
    return counts


def _taxonomy_versions():
    from careeros import taxonomy
    return {dimension: taxonomy.dimension_meta(dimension)['taxonomy_version']
            for dimension in ('municipality', 'canton', 'contract', 'workload', 'seniority',
                              'language', 'work_model')}


# --- compress ---------------------------------------------------------------

def cmd_compress(args):
    """Pack the posting snapshots that are older than `--older-than`.

    A DRY RUN unless `--apply`, like `scripts/migrate_*.py`: it prints
    which files it would pack and how much they weigh, and writes
    nothing. The snapshots are the bulk of this repo's disk use (6.1G
    under `data/ats` on a 26G root) and nothing prunes them, by design --
    they are the golden set's evidence -- so compression is the only
    lever that does not throw evidence away.
    """
    stores = [_store(args, provider) for provider in _providers(args)
              if provider in registry.PROVIDERS]
    totals = {'candidates': 0, 'bytes_before': 0, 'bytes_after': 0, 'compressed': 0,
              'failures': 0}
    for store in stores:
        report = store_module.compress_posting_snapshots(
            store, older_than_days=args.older_than, apply=args.apply)
        for key in ('bytes_before', 'bytes_after', 'compressed'):
            totals[key] += report[key]
        totals['candidates'] += len(report['candidates'])
        totals['failures'] += len(report['failures'])
        print(f"{store.provider:<16} {len(report['candidates']):>7} snapshot(s) older than "
              f"{args.older_than} day(s), {_mb(report['bytes_before'])} in {store.root}")
        for path in report['candidates'][:args.show]:
            print(f'    {path}')
        if len(report['candidates']) > args.show:
            print(f"    ... and {len(report['candidates']) - args.show} more")
        for failure in report['failures'][:10]:
            print(f"    FAILED {failure['path']}: {failure['reason']}")
    if not args.apply:
        print(f"\ndry run: {totals['candidates']} snapshot(s), {_mb(totals['bytes_before'])} "
              'would be packed. Pass --apply to do it.')
        return 0
    saved = totals['bytes_before'] - totals['bytes_after']
    print(f"\npacked {totals['compressed']} snapshot(s): {_mb(totals['bytes_before'])} -> "
          f"{_mb(totals['bytes_after'])}, {_mb(saved)} freed")
    if totals['failures']:
        print(f"{totals['failures']} snapshot(s) could not be packed and were left alone")
    return 1 if totals['failures'] else 0


def _mb(count):
    return f'{count / 1024 / 1024:.1f} MB'


# --- report -----------------------------------------------------------------

def cmd_report(args):
    store = _store(args)
    runs = store.load_runs()
    if not runs:
        print('no runs recorded yet')
        return 1
    entry = next((run for run in runs if run['run_id'] == args.run), None) if args.run \
        else runs[-1]
    if entry is None:
        print(f'no run {args.run}')
        return 1
    _print_run(entry)
    tenants = store.load_tenants()
    statuses = {}
    for record in tenants.values():
        statuses[record.get('status')] = statuses.get(record.get('status'), 0) + 1
    print(f'\ntenants: {len(tenants)} total; ' +
          ', '.join(f'{count} {status}' for status, count in sorted(statuses.items())))
    live = closed = suspected = 0
    for tenant in store.tenants_with_state():
        counts = store_module.counts(store.load_state(tenant))
        live += counts[store_module.OPEN]
        suspected += counts[store_module.SUSPECTED_CLOSING]
        closed += counts[store_module.CLOSED]
    print(f'postings tracked: {live} open, {suspected} suspected closing, {closed} closed')
    if args.verbose and entry.get('closed_keys'):
        print('closed in this run:')
        for key in entry['closed_keys'][:40]:
            print(f'  {key}')
    return 0


# --- map --------------------------------------------------------------------

def cmd_map(args):
    """Deliverable 4: which companies use which hiring platform.

    Reads every provider's tenants file and posting state plus the
    vault-probe file, and writes the tracked map, the full staging list
    and the readable report. Touches no network: the evidence is what
    `discover`, `probe-vault` and `fetch` already recorded.
    """
    stores = {}
    for provider in ALL_PROVIDERS:
        root = _root(args, provider)
        if (root / 'tenants.yaml').exists():
            stores[provider] = store_module.Store(root, provider=provider)
    if not stores:
        print('no provider has a tenants.yaml yet; run discover first')
        return 1
    built = platform_map.build(stores, probe_file=args.probe_file, day=args.day)
    paths = platform_map.write(built, map_path=Path(args.out), full=Path(args.full),
                               report=Path(args.report) if args.report else None)
    totals = built['totals']
    print(f"platform map: {totals['companies']} tenant(s) across "
          f"{len(built['providers'])} provider(s)")
    for provider, counts in built['providers'].items():
        print(f"  {provider:<16} {counts['tenants']:>6} discovered, "
              f"{counts['confirmed_live']:>5} confirmed live, "
              f"{counts['dead']:>5} dead, {counts['zurich']:>4} with a Zurich posting")
    for name, path in paths.items():
        print(f'  {name}: {path}')
    return 0


# --- command line -----------------------------------------------------------

def build_parser(default_root=None, providers=ALL_PROVIDERS, default_provider=None):
    """The command line. `default_root` and `default_provider` are what
    `scripts/run_personio_fetch.py` sets to keep CAREER-53's own command
    line working unchanged."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=default_root,
                        help='the staging store (default data/ats/<provider>)')
    parser.add_argument('--provider', choices=list(providers), default=default_provider,
                        required=default_provider is None,
                        help='which hiring platform to work on')
    parser.add_argument('--min-interval', type=float, default=polite_http.DEFAULT_MIN_INTERVAL,
                        help='seconds between requests, for the whole run (default 1.0)')
    subparsers = parser.add_subparsers(dest='command', required=True)

    probe = subparsers.add_parser('probe-vault', help="read the vault companies' own websites")
    probe.add_argument('--vault', type=Path, required=True)
    probe.add_argument('--max', type=int, default=500, help='cap the companies probed')
    probe.add_argument('--no-probe', action='store_true',
                       help='read the vault records only and touch no network')
    probe.add_argument('--out', type=Path, default=None)
    probe.set_defaults(handler=cmd_probe_vault)

    discover = subparsers.add_parser('discover', help='find tenants for one provider')
    discover.add_argument('--vault', type=Path, help='a vault to read websites and jobs from')
    discover.add_argument('--probe-websites', type=int, metavar='N', default=0,
                          help="also fetch up to N vault companies' sites looking for a tenant")
    discover.add_argument('--probe-file', type=Path, default=None,
                          help='a probe-vault output file to read route 2 from')
    discover.add_argument('--common-crawl', action='store_true',
                          help='query the Common Crawl URL index')
    discover.add_argument('--crawls', type=int, default=DEFAULT_CRAWLS,
                          help='how many crawl indexes to query, newest first')
    discover.add_argument('--max-cdx-pages', type=int, default=None,
                          help='cap the index pages per crawl (for a trial)')
    discover.add_argument('--from-file', type=Path,
                          help='replay saved CDX JSONL instead of calling Common Crawl')
    discover.add_argument('--save-cdx', type=Path, default=None,
                          help='write the raw index lines a live query returned, for replay')
    discover.add_argument('--zefix-file', type=Path,
                          default=Path('data/seeds/zefix_zurich_2026-10-17.yaml'),
                          help='the parked Zefix staging file, for name-only dedupe')
    discover.set_defaults(handler=cmd_discover)

    fetch = subparsers.add_parser('fetch', help='fetch every tenant feed')
    fetch.add_argument('--vault', type=Path, help='unused by fetch; accepted so cron lines match')
    fetch.add_argument('--max-tenants', type=int, default=None, help='cap the tenants fetched')
    fetch.add_argument('--tenants', nargs='+', default=None, help='fetch only these tenants')
    fetch.add_argument('--sample', type=int, default=None, metavar='N',
                       help='fetch a random sample of N tenants, for an unbiased trial estimate')
    fetch.add_argument('--seed', type=int, default=0, help='the sample seed (default 0)')
    fetch.add_argument('--languages', nargs='+', default=list(personio.DEFAULT_LANGUAGES),
                       help='feed languages, first one wins a posting (Personio only)')
    fetch.add_argument('--include-skipped', action='store_true',
                       help='also re-try tenants whose feed was unreadable')
    fetch.add_argument('--guide-version', default=None,
                       help='the labelling-guide version any flags are chosen under')
    fetch.add_argument('--detail', choices=(fetch_module.DETAIL_IN_AREA, fetch_module.DETAIL_ALL,
                                            fetch_module.DETAIL_NONE),
                       default=fetch_module.DETAIL_IN_AREA,
                       help='which postings get a second request for their text')
    fetch.add_argument('--robots-exception', nargs='+', default=None, metavar='PROVIDER',
                       help='proceed against a provider whose robots.txt disallows us, and '
                            'record that it was done')
    fetch.set_defaults(handler=cmd_fetch)

    export_parser = subparsers.add_parser('export', help='write the golden-set pool')
    export_parser.add_argument('--day', default=None, help='the date in the file name')
    export_parser.add_argument('--all-providers', action='store_true',
                               help='pool every provider that has a store')
    export_parser.add_argument('--include-out-of-area', action='store_true',
                               help='also export postings outside canton Zurich')
    export_parser.set_defaults(handler=cmd_export)

    compress = subparsers.add_parser(
        'compress', help='zstd-pack posting snapshots older than a month (dry run by default)')
    compress.add_argument('--older-than', type=int, metavar='DAYS',
                          default=store_module.COMPRESS_AFTER_DAYS,
                          help='pack snapshots untouched for this long (default 30)')
    compress.add_argument('--all-providers', action='store_true',
                          help='every provider that has a store')
    compress.add_argument('--apply', action='store_true',
                          help='actually pack them; the default is a dry run')
    compress.add_argument('--show', type=int, default=10, metavar='N',
                          help='how many candidate paths to list per provider (default 10)')
    compress.set_defaults(handler=cmd_compress)

    report = subparsers.add_parser('report', help='print a run report')
    report.add_argument('--run', default=None, help='a run id (default: the last one)')
    report.add_argument('--verbose', action='store_true')
    report.set_defaults(handler=cmd_report)

    mapper = subparsers.add_parser('map', help='build the ATS platform map')
    mapper.add_argument('--probe-file', type=Path, default=None,
                        help='a probe-vault output file, for the vault evidence')
    mapper.add_argument('--day', default=None, help='the date in the report file name')
    mapper.add_argument('--out', type=Path, default=Path('data/ats_platform_map.yaml'),
                        help='the tracked map')
    mapper.add_argument('--full', type=Path,
                        default=DEFAULT_ROOT_BASE / 'platform_map_full.yaml',
                        help='the full per-tenant list, which is too big to track')
    mapper.add_argument('--report', type=Path, default=None,
                        help='the readable report (default data/ats_platform_map_<date>.md)')
    mapper.set_defaults(handler=cmd_map)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == '__main__':
    raise SystemExit(main())
