"""First overview of which ATS the companies we know about actually use.

Feeds the "Workday: build or skip" decision. CAREER-52.

Reads company domains from two places -- the staging file
`seed_zefix_zurich.py` writes, and the websites the vault already holds --
then looks for an applicant tracking system behind each one with at most
two page requests per company. Writes
`data/seeds/ats_overview_<date>.md`. Nothing is written to the vault.

## Method, in the order the signals are trusted

1. **Recorded (no network).** An `ats_tenant` identifier or a source's
   `ats_provider` already stored on a vault company. This is the
   strongest signal there is: it was established when a real posting from
   that company came through intake.
2. **Stored website (no network).** `org_intake.ats.detect_ats` run on
   the company's own stored website, because some of them already ARE
   ATS URLs.
3. **Probed, posting URL (network).** Fetch the homepage, read its
   links, follow at most one careers link, and run `detect_ats` on every
   absolute link found. A match here means a real posting URL on a
   recognised provider -- confident.
4. **Probed, provider host only (network, weaker).** A link to a host
   `detect_ats` recognises, on a URL that is not posting-shaped (a
   careers index like `boards.greenhouse.io/acme` rather than
   `.../acme/jobs/123`). `detect_ats` correctly declines these, so they
   are counted separately and never mixed into the confident total.

## Limits, stated rather than discovered later

* **Zefix gives no domains.** The register carries no website field at
  all (see `seed_zefix_zurich.py`'s docstring), so a seeded company
  contributes nothing to probe until a domain is found for it some other
  way. In practice this report is currently about the vault's own
  companies, and it says so in its own output.
* **Two requests per company is a sample, not an audit.** An ATS reached
  only through a JavaScript-rendered careers page, a login, or a third
  page is invisible here. So the "no ATS detected" share is an upper
  bound on companies without one, never a finding that they have none.
* **The vault's companies are not a sample of Zurich.** They are the
  companies the owner happened to look at. Shares computed over them
  describe this vault, not the Zurich market.
* **"Top employers" means largest by what we already store** --
  `size_class`, then open jobs on the board, then name. Seeded companies
  have no size at all, so they could not rank even if they had domains.
* robots.txt is honoured: a domain whose robots.txt refuses our agent is
  skipped and counted as skipped. A robots.txt we cannot read is treated
  as a refusal.

## Usage

  python scripts/ats_overview.py --vault /path/to/vault
  python scripts/ats_overview.py --vault /path/to/vault \\
      --seed data/seeds/zefix_zurich_2026-10-17.yaml --max 100
  python scripts/ats_overview.py --vault /path/to/vault --no-probe

`--no-probe` runs tiers 1 and 2 only and touches no network, which is
also how the test suite drives it.
"""
import argparse
import sys
from collections import Counter
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import polite_http  # noqa: E402
from careeros import vault  # noqa: E402
from org_intake.ats import detect_ats  # noqa: E402

OUTPUT_DIR = Path('data/seeds')
DEFAULT_MAX = 500
MAX_LINKS_PER_PAGE = 400

# Hosts `org_intake.ats.detect_ats` recognises, kept here so tier 4 can
# say "a Greenhouse host was linked" about a URL that is not
# posting-shaped and that detect_ats therefore (correctly) declines.
#
# This mirrors ats.py's own host checks and is the one piece of knowledge
# this script duplicates from the capability. It belongs in the
# capability as something like `detect_ats_host(url)` next to
# `detect_ats(url)`; it is here because adding it there would edit the
# pinned submodule and move the pin, which is wider than this ticket.
# Suffix matching is exact-or-dot-prefixed, like ats.py's, so a lookalike
# host cannot match on a substring.
ATS_HOSTS = {
    'greenhouse': ('boards.greenhouse.io', 'job-boards.greenhouse.io'),
    'lever': ('jobs.lever.co',),
    'personio': ('personio.de', 'personio.com'),
    'workday': ('myworkdayjobs.com',),
    'smartrecruiters': ('jobs.smartrecruiters.com',),
    'ashby': ('jobs.ashbyhq.com',),
    'recruitee': ('recruitee.com',),
    'teamtailor': ('teamtailor.com',),
    'join': ('join.com',),
    'refline': ('refline.ch',),
}

CAREERS_HINTS = ('career', 'careers', 'jobs', 'job', 'stellen', 'offene-stellen', 'vacanc',
                 'join-us', 'arbeiten', 'recruit', 'hiring', 'emploi', 'lavoro', 'werken',
                 'jobboerse', 'jobportal')

# Biggest-first ordering read off the vault's own size vocabulary, which
# is stored smallest-first, rather than listed again here: the class list
# is a fixed list PROJECT.md owns, and a report that hard-coded it would
# silently rank a newly added class last.
SIZE_RANK = {name: rank for rank, name in enumerate(vault.SIZE_CLASSES, start=1)}


class _Links(HTMLParser):
    """Every href on a page, capped, because a sitemap-sized page is not
    worth reading to the end for this."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a' or len(self.hrefs) >= MAX_LINKS_PER_PAGE:
            return
        for name, value in attrs:
            if name == 'href' and value:
                self.hrefs.append(value.strip())


def page_links(html, base_url):
    """Absolute http(s) links from one page, deduplicated, in order."""
    parser = _Links()
    try:
        parser.feed(html)
    except Exception:
        # A malformed page is not an error worth stopping a sweep for;
        # whatever links were parsed before the break are still useful.
        pass
    seen, links = set(), []
    for href in parser.hrefs:
        if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
            continue
        absolute = urljoin(base_url, href)
        if urlsplit(absolute).scheme in ('http', 'https') and absolute not in seen:
            seen.add(absolute)
            links.append(absolute)
    return links


def ats_host_provider(url):
    """The provider whose host this URL is on, for a URL that is not
    posting-shaped. Tier 4 only: `detect_ats` stays the confident test."""
    host = (urlsplit(url).hostname or '').casefold()
    for provider, suffixes in ATS_HOSTS.items():
        for suffix in suffixes:
            if host == suffix or host.endswith('.' + suffix):
                return provider
    return None


def looks_like_careers(url):
    path = (urlsplit(url).path or '').casefold()
    return any(hint in path for hint in CAREERS_HINTS)


def domain_of(url):
    host = (urlsplit(url if '//' in str(url or '') else f'https://{url}').hostname or '').casefold()
    return host[4:] if host.startswith('www.') else host


def recorded_providers(record):
    """Tiers 1 and 2 for one vault company: what is already on file, and
    what its own stored website says. No network."""
    found = set()
    for item in record.get('identifiers') or []:
        if item.get('type') == 'ats_tenant' and ':' in str(item.get('value') or ''):
            found.add(str(item['value']).split(':', 1)[0])
    for source in record.get('sources') or []:
        if source.get('ats_provider'):
            found.add(source['ats_provider'])
    website = record.get('website')
    if website:
        match = detect_ats(website)
        if match:
            found.add(match['provider'])
    return found


def probe_targets(records, seeded, *, limit):
    """One row per company worth probing, vault companies first.

    Vault companies come first on purpose: they are the ones with a size,
    a board and a name the founder recognises, so a capped run spends its
    budget where the report can say something. Seeded companies follow
    and, today, contribute nothing -- Zefix has no domains.
    """
    targets = []
    for record in records:
        website = record.get('website')
        domain = next((item.get('value') for item in (record.get('identifiers') or [])
                       if item.get('type') == 'domain'), None)
        if not website and not domain:
            continue
        targets.append({
            'name': record.get('name'), 'company_id': record.get('id'),
            'origin': 'vault', 'website': website,
            'domain': domain or domain_of(website),
            'size_class': record.get('size_class'),
            'locations': record.get('locations') or [],
            'recorded': sorted(recorded_providers(record)),
        })
    for company in seeded:
        if company.get('domain'):
            targets.append({
                'name': company.get('name'), 'company_id': None, 'origin': 'seeded',
                'website': f"https://{company['domain']}", 'domain': company['domain'],
                'size_class': None, 'locations': [company.get('seat')], 'recorded': [],
            })
    return targets[:limit]


def probe(target, *, limiter, robots_cache, fetch=None):
    """Tiers 3 and 4 for one company: at most two page fetches.

    Never raises. Every outcome is a reason string on the returned row,
    so a sweep of hundreds of unrelated hosts produces counts rather than
    a traceback (PROJECT.md: failures are visible states with a reason).
    """
    fetch = fetch or polite_http.request_text
    row = {'probed': True, 'confident': [], 'host_only': [], 'pages': 0, 'skip_reason': None}
    start = target['website'] or f"https://{target['domain']}"

    allowed, reason = polite_http.robots_allows(start, cache=robots_cache, limiter=limiter)
    if not allowed:
        return {**row, 'probed': False, 'skip_reason': reason}

    def harvest(result):
        if not result['ok']:
            return []
        row['pages'] += 1
        links = page_links(result['text'], result['final_url'])
        # The landing URL itself counts: a careers link that 302s onto a
        # provider is exactly the evidence we are after.
        for candidate in [result['final_url']] + links:
            match = detect_ats(candidate)
            if match and match['provider'] not in row['confident']:
                row['confident'].append(match['provider'])
            elif not match:
                provider = ats_host_provider(candidate)
                if provider and provider not in row['host_only']:
                    row['host_only'].append(provider)
        return links

    home = fetch(start, limiter=limiter)
    if not home['ok']:
        return {**row, 'probed': False, 'skip_reason': f"homepage: {home['error']}"}
    links = harvest(home)

    careers = next((link for link in links if looks_like_careers(link)), None)
    if careers:
        allowed, reason = polite_http.robots_allows(careers, cache=robots_cache, limiter=limiter)
        if allowed:
            harvest(fetch(careers, limiter=limiter))
        row['careers_url'] = careers
    row['host_only'] = [p for p in row['host_only'] if p not in row['confident']]
    return row


def is_zurich(locations):
    text = ' '.join(str(item or '') for item in locations).casefold()
    return 'zurich' in text or 'zürich' in text or 'zuerich' in text


def rank_key(row):
    return (-SIZE_RANK.get(row.get('size_class'), 0), -row.get('open_jobs', 0),
            str(row.get('name') or ''))


def summarise(rows):
    """Provider counts and the probed/detected shares the decision needs."""
    confident = Counter()
    host_only = Counter()
    recorded = Counter()
    for row in rows:
        for provider in row.get('recorded', []):
            recorded[provider] += 1
        for provider in row.get('confident', []):
            confident[provider] += 1
        for provider in row.get('host_only', []):
            host_only[provider] += 1
    any_provider = Counter()
    for row in rows:
        for provider in set(row.get('recorded', [])) | set(row.get('confident', [])) | set(row.get('host_only', [])):
            any_provider[provider] += 1
    probed = [row for row in rows if row.get('probed')]
    detected = [row for row in rows if (set(row.get('recorded', [])) | set(row.get('confident', []))
                                        | set(row.get('host_only', [])))]
    return {'recorded': recorded, 'confident': confident, 'host_only': host_only,
            'any': any_provider, 'considered': len(rows), 'probed': len(probed),
            'detected': len(detected),
            'skipped': [row for row in rows if row.get('skip_reason')]}


def _table(header, widths, lines):
    out = ['| ' + ' | '.join(header) + ' |',
           '|' + '|'.join('-' * (width + 2) for width in widths) + '|']
    out.extend('| ' + ' | '.join(line) + ' |' for line in lines)
    return out


def render(rows, summary, *, args, limiter, seed_file, seed_total, seed_domains, probing):
    share = (f"{summary['detected']}/{summary['considered']} "
             f"({100 * summary['detected'] // max(1, summary['considered'])}%)")
    lines = [
        f'# ATS usage overview, {date.today().isoformat()}',
        '',
        f'Written by `scripts/ats_overview.py` (CAREER-52) at '
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}. "
        'Feeds the "Workday: build or skip" decision.',
        '',
        '## What this says',
        '',
        f"- **{share} of the companies considered have a detectable ATS.**",
        f"- {summary['considered']} companies considered, "
        f"{summary['probed']} of them actually probed over the network"
        f"{' (probing was off for this run)' if not probing else ''}.",
        f"- {len(summary['skipped'])} skipped (robots.txt, or the host did not answer).",
        '',
        '## Counts per provider',
        '',
        'Three columns, because they are three different strengths of evidence. '
        '**Recorded** came from a real posting that went through intake or from the '
        "company's own stored website. **Posting URL** is a `detect_ats` match on a link "
        'found while probing. **Host only** is a link to a provider host on a URL that is '
        'not posting-shaped, which `detect_ats` declines and which is therefore a hint '
        'rather than a fact.',
        '',
    ]
    providers = sorted(summary['any'], key=lambda p: (-summary['any'][p], p))
    if providers:
        lines += _table(['Provider', 'Recorded', 'Posting URL', 'Host only', 'Companies'],
                        [16, 8, 11, 9, 9],
                        [[provider, str(summary['recorded'][provider]),
                          str(summary['confident'][provider]), str(summary['host_only'][provider]),
                          str(summary['any'][provider])] for provider in providers])
    else:
        lines.append('No ATS was detected for any company considered.')
    lines += ['', '## Top employers per provider', '',
              'Largest first, by stored `size_class`, then open jobs on the board, then name. '
              'A **ZH** mark means the stored locations name Zurich; the vault holds companies '
              'outside Zurich too, and nothing here filters them out.', '']
    for provider in providers:
        holders = [row for row in rows
                   if provider in (set(row.get('recorded', [])) | set(row.get('confident', []))
                                   | set(row.get('host_only', [])))]
        holders.sort(key=rank_key)
        lines.append(f'### {provider}')
        lines.append('')
        lines += _table(['Company', 'Size', 'Open jobs', 'ZH', 'Evidence'],
                        [34, 7, 9, 3, 12],
                        [[str(row['name'] or '-'), row.get('size_class') or '-',
                          str(row.get('open_jobs', 0)),
                          'yes' if is_zurich(row.get('locations') or []) else '-',
                          ('recorded' if provider in row.get('recorded', [])
                           else 'posting URL' if provider in row.get('confident', [])
                           else 'host only')]
                         for row in holders[:10]])
        lines.append('')
    lines += [
        '## Method and limits',
        '',
        f'- Source of domains: the vault at `{args.vault}`'
        + (f', plus `{seed_file}` ({seed_total} seeded companies, of which '
           f'{seed_domains} carry a domain)' if seed_file else ' (no seed file given)')
        + '.',
        '- **Zefix carries no website field**, so a seeded company contributes no domain to '
        'probe. See `scripts/seed_zefix_zurich.py` for that finding. Today this report is '
        "about the vault's own companies.",
        '- At most two page fetches per company (homepage, then one careers link). An ATS '
        'behind JavaScript, a login, or a third page is invisible here, so '
        f'"no ATS detected" is an upper bound: {summary["considered"] - summary["detected"]} '
        'companies showed nothing, not the same as having nothing.',
        "- The vault's companies are the ones the owner happened to look at. These shares "
        'describe this vault, not the Zurich market.',
        f'- Politeness: user agent `{polite_http.USER_AGENT}`, at least '
        f'{args.min_interval}s between requests, robots.txt honoured (an unreadable '
        f'robots.txt counts as a refusal). {limiter.requests} requests in this run, '
        f'{limiter.slept:.0f}s spent waiting.',
        '- Nothing was written to the vault.',
        '',
        '## What the founder decides next',
        '',
        '- Whether the Workday share above is worth a Workday-specific build, or whether '
        'the broad-provider route wins.',
        '- Whether to accept the robots.txt call recorded in '
        '`scripts/seed_zefix_zurich.py` for the LINDAS query endpoint.',
        '- How a seeded Zurich company gets a domain at all, since Zefix has none. Without '
        'that, this report cannot grow past the companies already in the vault.',
        '',
    ]
    if summary['skipped']:
        lines += ['## Skipped', '']
        lines += [f"- {row['name']}: {row['skip_reason']}" for row in summary['skipped'][:40]]
        lines.append('')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', required=True, type=Path,
                        help='vault to read companies from. READ-ONLY; nothing is written to it.')
    parser.add_argument('--seed', type=Path,
                        help='a seed_zefix_zurich.py staging file, for its domains')
    parser.add_argument('--max', type=int, default=DEFAULT_MAX,
                        help=f'cap on companies probed (default {DEFAULT_MAX})')
    parser.add_argument('--min-interval', type=float, default=polite_http.DEFAULT_MIN_INTERVAL,
                        help=f'minimum seconds between requests (default '
                             f'{polite_http.DEFAULT_MIN_INTERVAL})')
    parser.add_argument('--no-probe', action='store_true',
                        help='recorded signals only; touches no network')
    parser.add_argument('--out', type=Path,
                        help='output path (default data/seeds/ats_overview_<date>.md)')
    parser.add_argument('--force', action='store_true', help='replace the output file if it exists')
    args = parser.parse_args(argv)

    out = args.out or OUTPUT_DIR / f'ats_overview_{date.today().isoformat()}.md'
    if out.exists() and not args.force:
        raise SystemExit(f'{out} exists already. Re-run with --force to replace it.')

    limiter = polite_http.RateLimiter(args.min_interval)
    records = vault.list_companies(args.vault)
    seeded, seed_total = [], 0
    if args.seed:
        document = yaml.safe_load(Path(args.seed).read_text()) or {}
        seeded = document.get('companies') or []
        seed_total = len(seeded)

    jobs = vault.list_jobs(args.vault)
    open_jobs = Counter(job.get('company_id') for job in jobs if vault.is_open_job(job))

    targets = probe_targets(records, seeded, limit=args.max)
    print(f'{len(records)} vault companies, {seed_total} seeded; '
          f'{len(targets)} with a domain to look at (cap {args.max})')
    print(f'user agent: {polite_http.USER_AGENT}  >={args.min_interval}s between requests')
    print('-' * 72)

    robots_cache = {}
    for index, target in enumerate(targets, 1):
        target['open_jobs'] = open_jobs.get(target['company_id'], 0)
        if args.no_probe:
            target.update({'probed': False, 'confident': [], 'host_only': [],
                           'skip_reason': None})
        else:
            target.update(probe(target, limiter=limiter, robots_cache=robots_cache))
        found = sorted(set(target['recorded']) | set(target['confident']) | set(target['host_only']))
        print(f"  [{index:>3}/{len(targets)}] {str(target['domain'])[:38]:<38} "
              f"{', '.join(found) if found else '-'}"
              f"{'  (' + target['skip_reason'] + ')' if target.get('skip_reason') else ''}")

    summary = summarise(targets)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(targets, summary, args=args, limiter=limiter,
                          seed_file=args.seed, seed_total=seed_total,
                          seed_domains=sum(1 for c in seeded if c.get('domain')),
                          probing=not args.no_probe))
    print('-' * 72)
    print(f"{summary['detected']} of {summary['considered']} companies have a detectable ATS "
          f"({summary['probed']} probed, {len(summary['skipped'])} skipped)")
    for provider, count in sorted(summary['any'].items(), key=lambda item: -item[1]):
        print(f"  {provider:<18} {count}")
    print(f'requests {limiter.requests}, slept {limiter.slept:.1f}s')
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
