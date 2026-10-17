"""The Personio adapter's runner: discover, fetch, export, report.

CAREER-53. Everything this script does lives in `careeros.feeds`; this
file is the command line, the wiring to `polite_http` (the one thing that
touches the network) and the printing.

## Subcommands

  discover  find tenants and write `data/personio/tenants.yaml`
  fetch     fetch each tenant's feed, freeze snapshots, update closure
            state, and write a run entry to `data/personio/runs.yaml`
  export    write the golden-set pool from the snapshots
  report    print the daily run report for the last (or a named) run

Every one of them is idempotent and safe to re-run. `discover` merges
rather than replaces and never downgrades a confirmed tenant. `fetch`
writes a new snapshot only when a posting's content hash changed. A
second `export` on the same day overwrites that day's pool file, which is
a derived file and the only one here that is not immutable.

## Daily shape (NOT installed -- the brief says do not install a cron job)

The adapter wants one discovery pass a week and one fetch pass a day,
because tenants appear slowly and postings close quickly.

    # /etc/cron.d/careeros-personio  -- one tab-free line each
    # fetch every morning at 06:20, discovery on Mondays at 05:40
    20 6 * * *  careeros  cd /srv/careeros && .venv/bin/python \\
        scripts/run_personio_fetch.py fetch --vault /srv/career-os \\
        >> /var/log/careeros/personio-fetch.log 2>&1
    40 5 * * 1  careeros  cd /srv/careeros && .venv/bin/python \\
        scripts/run_personio_fetch.py discover --vault /srv/career-os \\
        >> /var/log/careeros/personio-discover.log 2>&1

As systemd, the same two as a timer pair:

    # careeros-personio-fetch.timer
    [Timer]
    OnCalendar=*-*-* 06:20:00
    RandomizedDelaySec=10m
    Persistent=true

    # careeros-personio-fetch.service
    [Service]
    Type=oneshot
    WorkingDirectory=/srv/careeros
    ExecStart=/srv/careeros/.venv/bin/python scripts/run_personio_fetch.py \\
        fetch --vault /srv/career-os

`Persistent=true` matters: closure detection counts SUCCESSFUL fetches,
not days, so a run the machine slept through must happen late rather
than not at all -- otherwise a posting that closed during the gap waits
two more runs to be noticed.

`RandomizedDelaySec` matters too: one request a second against one
vendor, started at the same second every day, is the shape of a thing
worth not being. The spec's politeness rules are in
`careeros.feeds.fetch`; the global rate limiter is created here, once per
run, so the cap is one request a second for the whole run and not per
tenant.

**The fetch pass is long.** 150 tenants at two languages and one request
a second is around five minutes of requests plus Personio's own latency;
a full discovery pass over several Common Crawl indexes is longer. Both
are built to be run as a background job and to leave a report behind
rather than to be watched.

## The vault is read-only here

`--vault` is read for discovery route 1 (stored websites, stored ATS
identifiers, stored posting URLs) and for nothing else. No command writes
to it. Moving a tenant's postings or its company match into the vault is
a separate owner-gated step that does not exist yet, exactly as
`scripts/seed_zefix_zurich.py` leaves its own output staged.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import polite_http  # noqa: E402
import ats_overview  # noqa: E402  (reused: its link parser and careers-page heuristic)

from careeros import vault  # noqa: E402
from careeros.feeds import discovery, export, fetch as fetch_module, geocode, personio  # noqa: E402
from careeros.feeds import store as store_module  # noqa: E402

DEFAULT_ROOT = Path('data/personio')
#: The newest Common Crawl index, resolved live from collinfo.json. More
#: than one index is worth querying -- a tenant that existed in March and
#: not in September is still a tenant -- and `--crawls` says how many.
DEFAULT_CRAWLS = 1


def _store(args):
    return store_module.Store(args.root)


def _limiter(args):
    return polite_http.RateLimiter(min_interval=args.min_interval)


# --- discover ---------------------------------------------------------------

def cmd_discover(args):
    store = _store(args)
    limiter = _limiter(args)
    stored = store.load_tenants()
    found, routes = {}, {}

    if args.vault:
        companies = vault.list_companies(args.vault)
        jobs = vault.list_jobs(args.vault)
        route = discovery.tenants_from_vault(companies, jobs)
        routes['vault'] = {'tenants': len(route), 'companies_read': len(companies),
                           'jobs_read': len(jobs)}
        found.update(route)
        print(f'vault: {len(route)} tenant(s) from {len(companies)} companies '
              f'and {len(jobs)} jobs')

        if args.probe_websites:
            route, report = _probe_websites(companies, limiter=limiter, cap=args.probe_websites)
            routes['company_websites'] = report
            found.update({key: value for key, value in route.items() if key not in found})
            print(f"company websites: {len(route)} tenant(s) from {report['probed']} "
                  f"site(s) probed ({report['pages']} page(s) read)")

    if args.common_crawl:
        route, report = _common_crawl(args, limiter=limiter)
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
                                     'sources': {'common_crawl_terms': discovery.CDX_TERMS}})
    print(f'{len(merged)} tenant(s) in {store.tenants_file} (+{len(added)} new); '
          f'{len(matches)} name-only Zefix candidate(s)')
    return 0


def _probe_websites(companies, *, limiter, cap):
    """Discovery route 2, wired to `ats_overview`'s own page reader.

    That script already fetches a homepage, finds the careers link and
    parses the links out of both, with the robots check and the rate
    limit in the right places. Reusing its `page_links` and
    `looks_like_careers` is the difference between a second implementation
    of link scraping and none.
    """
    report = {'probed': 0, 'pages': 0, 'skipped': 0, 'with_tenant': 0}
    robots_cache, found = {}, {}
    targets = [record for record in companies if record.get('website')][:cap]
    for index, record in enumerate(targets, 1):
        start = record['website']
        allowed, reason = polite_http.robots_allows(start, cache=robots_cache, limiter=limiter)
        if not allowed:
            report['skipped'] += 1
            continue
        report['probed'] += 1
        home = polite_http.request_text(start, limiter=limiter)
        if not home['ok']:
            continue
        report['pages'] += 1
        links = ats_overview.page_links(home['text'], home['final_url'])
        candidates = [home['final_url']] + links
        careers = next((link for link in links if ats_overview.looks_like_careers(link)), None)
        if careers:
            allowed, _ = polite_http.robots_allows(careers, cache=robots_cache, limiter=limiter)
            if allowed:
                page = polite_http.request_text(careers, limiter=limiter)
                if page['ok']:
                    report['pages'] += 1
                    candidates += [page['final_url']] + ats_overview.page_links(
                        page['text'], page['final_url'])
        route = discovery.tenants_from_urls(candidates, discovered_via='company_website',
                                            company=record.get('name'))
        if route:
            report['with_tenant'] += 1
            print(f"  [{index:>3}/{len(targets)}] {record.get('name')}: "
                  f"{', '.join(sorted(route))}")
        found.update({key: value for key, value in route.items() if key not in found})
    return found, report


def _common_crawl(args, *, limiter):
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
            lines, discovered_via=f'common_crawl_replay:{Path(args.from_file).name}')
        return tenants, {'replayed_from': str(args.from_file), 'urls': stats['urls'],
                         'malformed_lines': stats['malformed'],
                         'truncated': stats['truncated'], 'tenants': len(tenants)}
    collections = discovery.cdx_collections(fetch=polite_http.request_text, limiter=limiter)
    crawls = [item['id'] for item in collections[:args.crawls]]
    tenants, reports, raw = {}, [], []
    for crawl in crawls:
        print(f'  querying Common Crawl index {crawl} ...')
        route, report = discovery.cdx_tenants(crawl, fetch=polite_http.request_text,
                                              limiter=limiter, max_pages=args.max_cdx_pages)
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
    store = _store(args)
    limiter = _limiter(args)
    tenants = store.load_tenants()
    if not tenants:
        print(f'no tenants in {store.tenants_file}; run discover first')
        return 1

    queue = _fetch_queue(tenants, args)
    run = store.next_run_id()
    at = store_module.now()
    print(f'run {run}: fetching {len(queue)} of {len(tenants)} tenant(s)')

    results, parse_failures, posting_failures = {}, [], []
    requests_made = 0
    for index, tenant in enumerate(queue, 1):
        record = tenants[tenant]
        result = fetch_module.fetch_tenant(
            tenant, store=store, run=run, fetch=polite_http.request_text, limiter=limiter,
            conditional=record.get('feeds') or {}, at=at,
            languages=tuple(args.languages), guide_version=args.guide_version)
        results[tenant] = result
        parse_failures.extend(result['parse_failures'])
        posting_failures.extend(result['posting_failures'])
        requests_made += result['requests']
        zurich = [posting for posting in result['postings']
                  if posting['area_status'] == geocode.IN_AREA]
        _update_tenant(record, result, run=run, at=at, zurich=zurich)
        print(f"  [{index:>4}/{len(queue)}] {tenant:<42} {result['fetch_status']:<12} "
              f"{len(result['postings']):>4} posting(s), {len(zurich):>3} in ZH"
              + (f" -- {result['error']}" if result['error'] else ''))

    changes = store_module.record_run(store, run=run, at=at, tenant_results=results)
    entry = _run_entry(run, at, queue, results, changes, parse_failures,
                       posting_failures=posting_failures, requests_made=requests_made,
                       limiter=limiter, args=args)
    store.append_run(entry)
    store.save_tenants(tenants, meta={'last_fetch_run': run})
    _print_run(entry)
    return 0


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
        import random
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
    # MERGED, not replaced: a language this run skipped (because the
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


def _run_entry(run, at, queue, results, changes, parse_failures, *, posting_failures,
               requests_made, limiter, args):
    ok = [tenant for tenant, result in results.items()
          if result['fetch_status'] == fetch_module.FETCH_OK]
    postings = sum(len(result['postings']) for result in results.values())
    zurich = sum(1 for result in results.values() for posting in result['postings']
                 if posting['area_status'] == geocode.IN_AREA)
    review = [posting for result in results.values() for posting in result['postings']
              if posting['area_status'] == geocode.NEEDS_REVIEW]
    review_swiss = [posting for posting in review if posting.get('swiss_evidence')]
    geocoded = sum(1 for result in results.values() for posting in result['postings']
                   if posting['area_status'] == geocode.IN_AREA and posting['municipality'])
    feeds_read = sum(1 for result in results.values()
                     for report in result['languages'].values()
                     if isinstance(report, dict) and report.get('positions') is not None)
    return {
        'run_id': run,
        'at': at,
        'provider': personio.PROVIDER,
        'tenants_queued': len(queue),
        'tenants_ok': len(ok),
        'tenants_failed': len(queue) - len(ok),
        'failures': {tenant: {'status': result['fetch_status'], 'error': result['error']}
                     for tenant, result in sorted(results.items())
                     if result['fetch_status'] != fetch_module.FETCH_OK},
        'feeds_read': feeds_read,
        'parse_failures': parse_failures,
        'posting_failures': posting_failures,
        'postings_seen': postings,
        'zurich_postings': zurich,
        'zurich_geocoded_to_municipality': geocoded,
        'offices_unresolved': len(review),
        'offices_needing_review': len(review_swiss),
        'offices_needing_review_examples': sorted({
            (posting.get('location') or {}).get('office') or ''
            for posting in review_swiss})[:20],
        'new_postings': sum(len(change['new']) for change in changes.values()),
        'changed_postings': sum(len(change['changed']) for change in changes.values()),
        'closed_postings': sum(len(change['closed']) for change in changes.values()),
        'suspected_closing': sum(len(change['suspected']) for change in changes.values()),
        'reopened_postings': sum(len(change['reopened']) for change in changes.values()),
        'closed_keys': sorted(key for change in changes.values() for key in change['closed']),
        'reopened_keys': sorted(key for change in changes.values() for key in change['reopened']),
        'requests': requests_made,
        'rate_limit_seconds': limiter.min_interval,
        'slept_seconds': round(limiter.slept, 1),
        'user_agent': polite_http.USER_AGENT,
        'languages': list(args.languages),
        'per_tenant': {tenant: {'fetch_status': result['fetch_status'],
                                'postings': len(result['postings']),
                                'requests': result['requests'],
                                'publishes': result['publishes'],
                                'new': len(changes[tenant]['new']),
                                'changed': len(changes[tenant]['changed']),
                                'closed': len(changes[tenant]['closed'])}
                       for tenant, result in sorted(results.items())},
    }


def _print_run(entry):
    parse_rate = (100.0 * (entry['feeds_read'] - len(entry['parse_failures']))
                  / entry['feeds_read']) if entry['feeds_read'] else 0.0
    geocode_rate = (100.0 * entry['zurich_geocoded_to_municipality']
                    / entry['zurich_postings']) if entry['zurich_postings'] else 0.0
    print(f"\nrun {entry['run_id']}")
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
    print(f"  requests: {entry['requests']} at >={entry['rate_limit_seconds']}s apart")
    for tenant, failure in list(entry['failures'].items())[:10]:
        print(f"    failed: {tenant}: {failure['status']} {failure['error'] or ''}")


# --- export -----------------------------------------------------------------

def cmd_export(args):
    store = _store(args)
    rows, skipped = export.build_pool(store, include_out_of_area=args.include_out_of_area)
    summary = export.summarise(rows)
    path = export.write_pool(store, rows, day=args.day or date.today().isoformat(),
                             summary=summary,
                             meta={'skipped': len(skipped),
                                   'skipped_reasons': _tally(skipped),
                                   'include_out_of_area': args.include_out_of_area,
                                   'taxonomy_version': _taxonomy_versions()})
    print(f"{len(rows)} posting(s) exported to {path}")
    print(f"  tenants {summary['tenants']}, companies {summary['companies']}, "
          f"municipalities {summary['municipalities']}")
    print(f"  occupation categories {summary['occupation_categories']} "
          f"({summary['occupation_categories_with_8_or_more']} with 8+ postings)")
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
                              'language')}


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


# --- command line -----------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT,
                        help='the staging store (default data/personio)')
    parser.add_argument('--min-interval', type=float, default=polite_http.DEFAULT_MIN_INTERVAL,
                        help='seconds between requests, for the whole run (default 1.0)')
    subparsers = parser.add_subparsers(dest='command', required=True)

    discover = subparsers.add_parser('discover', help='find Personio tenants')
    discover.add_argument('--vault', type=Path, help='a vault to read websites and jobs from')
    discover.add_argument('--probe-websites', type=int, metavar='N', default=0,
                          help='also fetch up to N vault companies\' sites looking for a tenant')
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
                       help='feed languages, first one wins a posting (default de en)')
    fetch.add_argument('--include-skipped', action='store_true',
                       help='also re-try tenants whose feed was unreadable')
    fetch.add_argument('--guide-version', default=None,
                       help='the labelling-guide version any flags are chosen under')
    fetch.set_defaults(handler=cmd_fetch)

    export_parser = subparsers.add_parser('export', help='write the golden-set pool')
    export_parser.add_argument('--day', default=None, help='the date in the file name')
    export_parser.add_argument('--include-out-of-area', action='store_true',
                               help='also export postings outside canton Zurich')
    export_parser.set_defaults(handler=cmd_export)

    report = subparsers.add_parser('report', help='print a run report')
    report.add_argument('--run', default=None, help='a run id (default: the last one)')
    report.add_argument('--verbose', action='store_true')
    report.set_defaults(handler=cmd_report)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == '__main__':
    raise SystemExit(main())
