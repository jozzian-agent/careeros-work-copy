"""The ATS platform map: which company uses which hiring platform.

Owner ruling 2026-10-17, priority b, in his own words: "list which
companies use which platform". This module is that list, and it is also
the stage-1 deliverable "Overview of ATS usage across Zurich companies"
and the evidence behind the plan's "Workday: build or skip" decision.

It reads what `discover`, `probe-vault` and `fetch` already recorded --
one tenants file and one state directory per provider, plus the vault
probe -- and writes three things:

    data/ats_platform_map.yaml        tracked, small: the totals and
                                      every tenant with real evidence
    data/ats/platform_map_full.yaml   staged, large: every tenant the
                                      crawl index named
    data/ats_platform_map_<date>.md   tracked: the readable report

THE SPLIT IS DELIBERATE and it is the one thing in this module that is a
judgement call rather than a measurement. A crawl-index sweep names tens
of thousands of tenants, which is a megabyte of YAML that would land in
git history on every run. So the tracked file keeps the totals, the
per-provider breakdown and every tenant whose evidence is stronger than
"a URL appeared in a crawl index" -- a fetched feed, a dead feed, a
vault record, a careers-page link -- plus a capped sample of the
index-only ones so the file still shows what they look like. The full
list stays under `data/ats/`, is gitignored like every other staging
output, and is regenerable from the tenants files with one command.

## The four confidence levels, which are never mixed

The brief asks for honest confidence, so the map carries exactly these,
each meaning one thing:

  * `confirmed_live` -- the provider's feed was fetched and parsed for
    this tenant in a trial run. The strongest evidence there is: the
    company is on this platform today.
  * `dead` -- the feed was fetched and the tenant does not serve one
    (404) or it could not be read. Recorded rather than dropped: a
    tenant that has left a platform is a fact about the platform's
    share, and PROJECT.md forbids silent drops.
  * `recorded` -- the vault already knew: a stored `ats_tenant`
    identifier, a stored posting URL, a company website that is itself
    an ATS URL, or a careers page that links to one. No feed was
    fetched, so the tenant may be stale -- but a human or an intake run
    put it there.
  * `observed_in_crawl_index` -- a URL on this provider's host appeared
    in a Common Crawl index. That is evidence the tenant EXISTED when
    the crawl ran (September 2026 for `CC-MAIN-2026-39`), and nothing
    more. A third of Personio's index-only tenants turned out to serve
    no feed at all.

A tenant is counted once, at its strongest level.

## What it cannot say, stated here rather than discovered later

  * **It is a map of TENANTS, not of companies.** A tenant id is a slug
    on a platform; matching it to a legal entity needs a name, and only
    the fetched ones state one (from the feed's own employer field).
    `company_name` is filled where a feed or a vault record stated it
    and is null otherwise, never guessed from the slug.
  * **Zurich is a posting-level fact.** A tenant counts as a Zurich
    tenant when at least one of its postings geocoded to canton Zurich
    in a trial fetch. A tenant nobody fetched has no Zurich answer at
    all, which is why the map reports "not yet fetched" as its own
    number rather than folding it into "no Zurich office".
  * **The index is a sample of the web, and a capped sweep is a sample
    of the index.** Every provider's row says how many index pages were
    available and how many were read, so a share is never presented as
    a census.
  * **A company can use two platforms**, and several do (a group with
    one board per subsidiary, or a migration in progress). The map keeps
    both rows; it is not a one-platform-per-company table.
"""
from collections import Counter
from datetime import date
from pathlib import Path

from careeros.feeds import store as store_module

CONFIRMED_LIVE = 'confirmed_live'
DEAD = 'dead'
RECORDED = 'recorded'
INDEXED = 'observed_in_crawl_index'

#: Strongest first. A tenant is counted once, at the best evidence it has.
CONFIDENCE_ORDER = (CONFIRMED_LIVE, DEAD, RECORDED, INDEXED)

CONFIDENCE_WORDS = {
    CONFIRMED_LIVE: 'the feed was fetched and parsed in a trial run',
    DEAD: 'the feed was fetched and the tenant does not serve one',
    RECORDED: 'the vault or a careers page names it; no feed was fetched',
    INDEXED: 'a URL on this host appeared in a Common Crawl index',
}

#: Discovery routes that mean a human or an intake run put the tenant on
#: file, which is the `recorded` level.
VAULT_ROUTES = frozenset({'vault_company', 'vault_job', 'vault_identifier', 'company_website'})

#: How many index-only tenants the TRACKED file keeps per provider, as a
#: sample. The rest are in the full file; see the module docstring.
TRACKED_SAMPLE = 25


def _confidence(entry):
    """One tenant's evidence level, read off what the stores recorded."""
    status = entry.get('last_fetch_status')
    if status == 'ok':
        return CONFIRMED_LIVE
    if status:
        return DEAD
    routes = {entry.get('discovered_via')} | set(entry.get('also_discovered_via') or ())
    if routes & VAULT_ROUTES:
        return RECORDED
    return INDEXED


def _zurich(entry, counts):
    """Whether this tenant has a Zurich posting, or has not been asked.

    Three answers, not two: `yes`, `no` and `not_fetched`. Folding the
    third into the second would make every undiscovered tenant look like
    a tenant without a Zurich office, which is exactly the number the
    owner is trying to estimate.
    """
    if entry.get('last_fetch_status') != 'ok':
        return 'not_fetched'
    return 'yes' if (entry.get('zurich_postings_seen') or counts.get('zurich')) else 'no'


def company_rows(store, *, probe=None):
    """Every tenant one provider's store knows, as map rows."""
    provider = store.provider
    tenants = store.load_tenants()
    probe = probe or {}
    rows = []
    for tenant, entry in sorted(tenants.items()):
        state_counts = _state_counts(store, tenant)
        confidence = _confidence(entry)
        probed = probe.get((provider, tenant)) or {}
        rows.append({
            'provider': provider,
            'tenant': tenant,
            'company_name': entry.get('company_name') or probed.get('company_name'),
            'vault_company': probed.get('company_name'),
            'confidence': confidence,
            'confidence_means': CONFIDENCE_WORDS[confidence],
            'discovered_via': entry.get('discovered_via'),
            'also_discovered_via': list(entry.get('also_discovered_via') or ()),
            'how': entry.get('how'),
            'evidence': entry.get('evidence'),
            'discovered_on': entry.get('first_seen'),
            'last_fetch_run': entry.get('last_fetch_run'),
            'last_fetch_status': entry.get('last_fetch_status'),
            'last_fetch_error': entry.get('last_fetch_error'),
            'postings_seen': entry.get('postings_seen'),
            'postings_open': state_counts.get('open'),
            'zurich': _zurich(entry, state_counts),
            'zurich_postings': entry.get('zurich_postings_seen') or state_counts.get('zurich'),
            'municipalities': list(entry.get('municipalities') or ()),
            'tenant_status': entry.get('status'),
            'status_reason': entry.get('status_reason'),
            'zefix_candidate': (entry.get('zefix_match') or {}).get('candidates'),
        })
    return rows


def _state_counts(store, tenant):
    """What this tenant's posting state says, or an empty answer."""
    path = store.state_file(tenant)
    if not path.exists():
        return {}
    state = store.load_state(tenant)
    postings = (state.get('postings') or {}).values()
    return {'open': sum(1 for item in postings if item.get('status') != store_module.CLOSED),
            'closed': sum(1 for item in postings if item.get('status') == store_module.CLOSED),
            'zurich': sum(1 for item in postings if item.get('canton') == '1')}


def _probe_index(probe_file):
    """`(provider, tenant) -> entry` out of a `probe-vault` file, so a
    row can name the vault company a tenant belongs to."""
    if not probe_file or not Path(probe_file).exists():
        return {}
    data = store_module.read_yaml(probe_file, {}) or {}
    index = {}
    for section in ('from_vault_records', 'from_websites'):
        for provider, entries in (data.get(section) or {}).items():
            for entry in entries or ():
                index.setdefault((provider, entry['tenant']), entry)
    return index


def build(stores, *, probe_file=None, day=None):
    """The whole map: per-provider totals and every tenant row.

    `stores` is `{provider: Store}`. A provider with no adapter (Workday
    and the three smaller ones) has a tenants file and no state, so its
    rows are all `observed_in_crawl_index` -- which is the honest answer
    and the one the "build or skip" decision needs.
    """
    probe = _probe_index(probe_file)
    rows, providers = [], {}
    for provider, store in stores.items():
        provider_rows = company_rows(store, probe=probe)
        rows.extend(provider_rows)
        meta = store_module.read_yaml(store.tenants_file, {}) or {}
        confidence = Counter(row['confidence'] for row in provider_rows)
        zurich = Counter(row['zurich'] for row in provider_rows)
        providers[provider] = {
            'tenants': len(provider_rows),
            'confirmed_live': confidence[CONFIRMED_LIVE],
            'dead': confidence[DEAD],
            'recorded': confidence[RECORDED],
            'indexed_only': confidence[INDEXED],
            'fetched': confidence[CONFIRMED_LIVE] + confidence[DEAD],
            'not_fetched': zurich['not_fetched'],
            'zurich': zurich['yes'],
            'no_zurich_office': zurich['no'],
            'postings_seen': sum(row['postings_seen'] or 0 for row in provider_rows),
            'zurich_postings': sum(row['zurich_postings'] or 0 for row in provider_rows),
            'fetchable': bool(meta.get('fetchable', True)),
            'api_doc': (meta.get('sources') or {}).get('api_doc'),
            'api_doc_accessed': (meta.get('sources') or {}).get('api_doc_accessed'),
            'discovery': _discovery_summary(meta),
            'store': str(store.root),
        }
    rows.sort(key=lambda row: (row['provider'], row['tenant']))
    return {
        'built_at': store_module.now(),
        'day': day or date.today().isoformat(),
        'providers': dict(sorted(providers.items(),
                                 key=lambda item: -item[1]['tenants'])),
        'totals': {
            'companies': len(rows),
            'providers': len(providers),
            'confirmed_live': sum(item['confirmed_live'] for item in providers.values()),
            'dead': sum(item['dead'] for item in providers.values()),
            'recorded': sum(item['recorded'] for item in providers.values()),
            'indexed_only': sum(item['indexed_only'] for item in providers.values()),
            'zurich_tenants': sum(item['zurich'] for item in providers.values()),
            'zurich_postings': sum(item['zurich_postings'] for item in providers.values()),
        },
        'confidence_levels': dict(CONFIDENCE_WORDS),
        'companies': rows,
    }


def _discovery_summary(meta):
    """How the tenants of one provider were found, and how much of the
    index was actually read -- which is what stops a share from reading
    as a census."""
    routes = meta.get('discovery_routes') or {}
    crawl = routes.get('common_crawl') or {}
    pages = [page for report in (crawl.get('per_crawl') or []) for page in report.get('pages', [])]
    return {
        'routes': sorted(routes),
        'crawls': crawl.get('crawls') or ([crawl['replayed_from']]
                                          if crawl.get('replayed_from') else []),
        'indexed_urls_read': crawl.get('urls'),
        # How many index blocks the crawl holds for this provider's
        # hosts: the one number that does not depend on how much of the
        # index this run read. See `discovery.cdx_tenants`.
        'index_blocks': sum(page.get('blocks') or 0 for page in pages) or None,
        'index_pages_available': sum(page.get('available') or 0 for page in pages) or None,
        'index_pages_read': sum(page.get('queried') or 0 for page in pages) or None,
        'index_pages_lost': crawl.get('failed_pages'),
        'from_vault': (routes.get('vault') or {}).get('tenants'),
        'from_probe_file': (routes.get('probe_file') or {}).get('tenants'),
        'from_company_websites': (routes.get('company_websites') or {}).get('with_tenant'),
    }


#: What a row keeps in the TRACKED file. The rest -- the confidence
#: sentence (which the file states once, in `confidence_levels`), the
#: tenant's status reason, the second discovery route, the Zefix
#: candidates -- stays in the full list. Keeping the long fields on
#: every row is what made the first build of this file 294 KB.
TRACKED_FIELDS = ('provider', 'tenant', 'company_name', 'vault_company', 'confidence',
                  'discovered_via', 'how', 'evidence', 'discovered_on', 'last_fetch_run',
                  'last_fetch_status', 'postings_seen', 'zurich', 'zurich_postings',
                  'municipalities')


def _compact(row):
    return {name: row[name] for name in TRACKED_FIELDS if row.get(name) not in (None, [], '')}


def tracked(built, *, sample=TRACKED_SAMPLE):
    """The small, tracked half of the map. See the module docstring on
    why the index-only tenants are sampled rather than listed."""
    kept, sampled = [], Counter()
    for row in built['companies']:
        if row['confidence'] != INDEXED:
            kept.append(_compact(row))
            continue
        if sampled[row['provider']] < sample:
            sampled[row['provider']] += 1
            kept.append({**_compact(row), 'sampled': True})
    return {
        **{key: value for key, value in built.items() if key != 'companies'},
        'tracked_note': (
            f'every tenant with evidence stronger than a crawl-index hit, plus the first '
            f'{sample} index-only tenants per provider as a sample. The full list is the '
            'file named below and is regenerable with '
            '`scripts/run_ats_fetch.py --provider <p> map`.'),
        'full_list': 'data/ats/platform_map_full.yaml',
        'companies': kept,
    }


def write(built, *, map_path=None, full=None, report=None):
    """Write the three files and return where they went."""
    map_path = Path(map_path or 'data/ats_platform_map.yaml')
    full = Path(full or 'data/ats/platform_map_full.yaml')
    report = Path(report or f"data/ats_platform_map_{built['day']}.md")
    store_module.write_yaml(map_path, tracked(built))
    store_module.write_yaml(full, built)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render(built))
    return {'map': map_path, 'full': full, 'report': report}


def _row(cells, widths):
    return '| ' + ' | '.join(str(cell).ljust(width)
                             for cell, width in zip(cells, widths)) + ' |'


def _table(header, rows):
    widths = [max(len(str(cell)) for cell in column)
              for column in zip(header, *rows)] if rows else [len(cell) for cell in header]
    lines = [_row(header, widths), '|' + '|'.join('-' * (width + 2) for width in widths) + '|']
    lines += [_row(row, widths) for row in rows]
    return '\n'.join(lines)


def render(built):
    """The readable report, in the style of the Personio trial report:
    the numbers first, then what they do and do not support."""
    providers = built['providers']
    totals = built['totals']
    lines = [f"# ATS platform map, {built['day']}", '',
             f"Built by `scripts/run_ats_fetch.py map` at {built['built_at']} (CAREER-54, owner "
             'ruling 2026-10-17: "list which companies use which platform"). This supersedes '
             'and absorbs `data/seeds/ats_overview_2026-10-17.md` (CAREER-52), which probed 44 '
             'vault companies and could only answer which provider a careers page linked to; '
             'this map carries the tenant id, the evidence and whether the feed is live.', '',
             '## What this says', '',
             f"- **{totals['companies']} tenants** across "
             f"**{totals['providers']} platforms**.",
             f"- {totals['confirmed_live']} are **confirmed live** (a feed was fetched and "
             f"parsed), {totals['dead']} are **dead** (fetched, no feed), "
             f"{totals['recorded']} are **recorded** by the vault and "
             f"{totals['indexed_only']} are **observed in a crawl index** only.",
             f"- {totals['zurich_tenants']} tenants have at least one posting in canton "
             f"Zurich, holding {totals['zurich_postings']} Zurich postings between them.", '',
             '## Per platform', '',
             _table(['Platform', 'Tenants', 'Confirmed live', 'Dead', 'Recorded',
                     'Index only', 'Not fetched', 'Zurich tenants', 'Zurich postings',
                     'Adapter'],
                    [[provider, counts['tenants'], counts['confirmed_live'], counts['dead'],
                      counts['recorded'], counts['indexed_only'], counts['not_fetched'],
                      counts['zurich'], counts['zurich_postings'],
                      'yes' if counts['fetchable'] else 'no']
                     for provider, counts in providers.items()]),
             '', '## How each platform\'s tenants were found', '',
             _table(['Platform', 'Routes', 'Crawl indexes', 'Index pages read',
                     'Index pages available', 'Indexed URLs read', 'Pages lost'],
                    [[provider, ', '.join(counts['discovery']['routes']) or '-',
                      ', '.join(counts['discovery']['crawls']) or '-',
                      counts['discovery']['index_pages_read'] or '-',
                      counts['discovery']['index_pages_available'] or '-',
                      counts['discovery']['indexed_urls_read'] or '-',
                      counts['discovery']['index_pages_lost'] if
                      counts['discovery']['index_pages_lost'] is not None else '-']
                     for provider, counts in providers.items()]),
             '', '## Confidence levels', '']
    for level in CONFIDENCE_ORDER:
        lines.append(f'- **{level}** -- {CONFIDENCE_WORDS[level]}')
    lines += ['', '## Which platform is worth the next adapter', '',
              "The owner's question, answered from the rows above rather than from "
              'impressions. Two orderings, because they are two different questions: how many '
              'companies are on a platform at all, and how many of them are hiring in Zurich. '
              'The second is what the pool needs and it can only be answered for a platform '
              'something has fetched.', '']
    ranked = sorted(providers.items(), key=lambda item: -item[1]['tenants'])
    total = sum(counts['tenants'] for counts in providers.values()) or 1
    lines.append(_table(
        ['Rank', 'Platform', 'Tenants found', 'Share of tenants found', 'Index pages read',
         'Index blocks', 'Zurich tenants', 'Zurich postings', 'Adapter'],
        [[rank, provider, counts['tenants'],
          f"{100.0 * counts['tenants'] / total:.1f}%",
          (f"{counts['discovery']['index_pages_read']} of "
           f"{counts['discovery']['index_pages_available']}"
           if counts['discovery']['index_pages_available'] else '-'),
          counts['discovery']['index_blocks'] or '-',
          counts['zurich'] if counts['fetched'] else 'not fetched',
          counts['zurich_postings'] if counts['fetched'] else '-',
          'yes' if counts['fetchable'] else 'no']
         for rank, (provider, counts) in enumerate(ranked, 1)]))
    lines += ['',
              '**Read "tenants found" as a lower bound, not a market share.** It is a count of '
              'the tenants a capped read of ONE crawl index happened to name, and the crawl '
              'indexes each provider\'s hosts to a wildly different depth: measured '
              '2026-10-17, Greenhouse\'s two board hosts hold 29 index blocks and '
              '`jobs.lever.co` holds 1. The "Index blocks" column is the comparable number, '
              'because it does not depend on how much this run read -- but it is a fact about '
              'the crawl, which is itself a sample of the web.']
    unfetchable = [(provider, counts) for provider, counts in ranked
                   if not counts['fetchable']]
    if unfetchable:
        lines += ['', '**The platforms with no adapter**, which is what the "build or skip" '
                      'decision is about:', '']
        for provider, counts in unfetchable:
            pages = counts['discovery']
            lines.append(
                f"- **{provider}**: {counts['tenants']} tenants, "
                f"{100.0 * counts['tenants'] / total:.1f}% of everything this map knows"
                + (f", from {pages['index_pages_read']} of {pages['index_pages_available']} "
                   'index pages' if pages['index_pages_available'] else '')
                + '. Nothing has been fetched from it, so its Zurich share is unmeasured: '
                  'that is what an adapter would buy.')
    lines += ['',
              '## The Zurich tenants, by platform', '']
    zurich_rows = [row for row in built['companies'] if row['zurich'] == 'yes']
    if zurich_rows:
        lines.append(_table(
            ['Platform', 'Tenant', 'Company', 'Zurich postings', 'Municipalities', 'Evidence'],
            [[row['provider'], row['tenant'], row['company_name'] or '-',
              row['zurich_postings'] or 0, ', '.join(row['municipalities']) or '-',
              row['confidence']] for row in sorted(
                  zurich_rows, key=lambda item: (item['provider'],
                                                 -(item['zurich_postings'] or 0)))][:80]))
    else:
        lines.append('No tenant has a confirmed Zurich posting yet.')
    lines += ['',
              '## What the vault already knew', '']
    recorded = [row for row in built['companies'] if row['vault_company']]
    if recorded:
        lines.append(_table(['Platform', 'Tenant', 'Vault company', 'How', 'Evidence URL'],
                            [[row['provider'], row['tenant'], row['vault_company'],
                              row['how'] or '-', (row['evidence'] or '-')[:70]]
                             for row in recorded]))
    else:
        lines.append('No vault company resolved to a tenant in this run.')
    lines += ['', '## Method and limits', '',
              '- Tenants come from three routes: the vault (stored ATS identifiers, stored '
              'posting URLs, company websites), a probe of each vault company\'s own site '
              '(two page requests, robots.txt honoured), and the Common Crawl URL index. '
              'No search engine is scraped and no tenant id is guessed; see '
              '`careeros/feeds/discovery.py` for the rejected routes and the Common Crawl '
              'source check.',
              '- A crawl-index sweep is a sample of a sample: the index is what one crawl saw, '
              'and a capped sweep reads some of its pages. The pages-read column above is what '
              'makes that visible.',
              '- "Zurich" is a posting-level fact, so a tenant nobody fetched has no Zurich '
              'answer. That is the "Not fetched" column, kept apart from a tenant whose feed '
              'was read and has no Zurich office.',
              '- A tenant id is not a company. `Company` is filled from the feed\'s own '
              'employer field or from a vault record and is left empty otherwise, never '
              'guessed from the slug.',
              '- A company on two platforms keeps a row on each.', '']
    return '\n'.join(lines) + '\n'
