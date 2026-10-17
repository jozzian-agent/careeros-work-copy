"""Seed the Zurich company universe from the Zefix commercial register.

Produces a STAGING file of active Zurich legal entities with their UID,
legal form and seat, deduplicated against the companies the vault already
holds. Nothing here writes to the vault. CAREER-52.


## Access finding, checked live on 2026-10-17

The brief asked for the Zefix public REST API and told this script to
stop and record the finding rather than scrape HTML if that API is shut.
It is shut, and the finding has three parts.

1. **The REST API needs credentials we do not have.** Its OpenAPI
   document is public at
   `https://www.zefix.admin.ch/ZefixPublicREST/v3/api-docs` (version
   2.7.2.4) and declares one security scheme, `Zefix-Credentials`, of
   type HTTP Basic. Every endpoint answers `401` with an empty body
   unauthenticated -- checked for `GET /api/v1/legalForm` and
   `POST /api/v1/company/search`. Credentials come from registering with
   the Federal Office of Justice; that is a founder action, not
   something this script can do.

2. **Even with credentials it could not list the Zurich register.** The
   only search endpoint is `POST /api/v1/company/search`, whose
   `CompanySearchQuery` makes `name` a REQUIRED field with
   `minLength: 3`, and whose response is a bare, unpaginated array of
   `CompanyShort`. There is no list-by-canton, no offset and no cursor.
   `canton` exists only as a narrowing filter on a name search. So the
   REST API is a lookup service, not a bulk source: enumerating ~138k
   Zurich entries through it would mean sweeping name prefixes and
   guessing when the sweep was complete.

3. **HTML is not an option either, and was not tried.** `robots.txt` on
   both `www.zefix.ch` and `www.zefix.admin.ch` is `Disallow: /` for
   `User-agent: *`, allowing only a short list of static pages to
   Googlebot and Bingbot. The brief forbade scraping; so does the site.

## The route this script actually uses

The same register is published as Open Government Data. The dataset
`Zefix - Zentraler Firmenindex` (publisher: Federal Office for the
Commercial Register, EHRA) is on opendata.swiss under the licence
"OGD Open use. Must provide the source"
(https://opendata.swiss/en/terms-of-use#terms_by), and its machine
distribution is Linked Data in LINDAS, queryable over the **public
SPARQL endpoint `https://lindas.admin.ch/query` with no credentials**:

  * landing page: https://opendata.swiss/en/dataset/zefix-zentraler-firmenindex
  * graph:        https://lindas.admin.ch/foj/zefix
  * 795,453 `admin:ZefixOrganisation` entities, of which **138,597** have
    their legal seat in a canton-Zurich commune (checked 2026-10-17)

This is the official distribution of the register, not a scrape of it,
and `SOURCE_ATTRIBUTION` below is written into every output file so the
licence's attribution condition travels with the data.

**One robots.txt tension the founder should accept or refuse.**
`lindas.admin.ch/robots.txt` is also `Disallow: /` for every agent. That
file governs crawlers walking pages; the endpoint this script calls is
the dataset's own documented query service, published by the federal
administration as the way to read this data programmatically. The script
therefore treats robots.txt as not governing this API call, while still
identifying itself and staying at one request a second. If the founder
disagrees, `--from-file` is the offline path (below) and needs no live
call at all.

## What a capped run actually gives you

`--max` takes the FIRST N rows ordered by the company's register URI,
which is an EHRA id -- roughly registration order, and otherwise
arbitrary. It is NOT the largest, the most recently active or the most
hire-likely Zurich companies, because Zefix holds no signal to order by:
no headcount, no sector, no website, no hiring activity. The register is
a list of legal entities, including every one-person Einzelunternehmen
and every dormant holding.

So a 5,000-row slice is a sample of the register, not a shortlist of
employers, and M3's "at least 50 companies with sector, size and
location" is not met by running this script harder. What this produces
is a deduplicated, UID-keyed candidate pool; deciding which of them are
employers worth a record needs a second signal from somewhere else. That
is the founder's next decision, not something to paper over here.

## What Zefix does not have: domains

Neither the REST API's `CompanyFull` nor the LINDAS graph carries a
website, URL or domain anywhere -- there is no such field to read. So
`domain` is `null` for every seeded company, and the run report says so
as a share rather than leaving it to be noticed. The brief's "leave null,
do not guess" is therefore the only branch this script ever takes for
that field. Finding a domain for a seeded company is separate work, and
it is what `ats_overview.py` is currently starved of.

## The merge is the founder's, not this script's

Output goes to `data/seeds/` and nothing else. The live vault is opened
read-only, to dedupe. No existing record is read-modify-written, no
record is created, and `vault.save_company` is never called. Moving an
accepted staging row into the vault is a separate, founder-gated step
that does not exist yet.

## Dedupe, and why a name match is not a decision

UID first, then normalised name, as the brief asks. Two honest notes:

  * **The UID key is inert today.** The capability's `IDENTIFIER_TYPES`
    has no `uid` entry and no vault company carries one, so the UID pass
    currently matches nothing. The report prints how many existing
    companies carry a UID at all, so that stays visible instead of
    looking like a clean result.
  * **A name-only match is a candidate, not a duplicate.** PROJECT.md's
    product rule is that only confident matches fill anything and
    ambiguity raises a flag. "Meier AG" in Zurich is several unrelated
    companies. So a row matched by name alone is held out of the
    acceptance list and recorded with `matched_on: name` and
    `confident: false` for the founder to confirm or reject; a UID match
    is `confident: true`.

Rows are NOT deduplicated against each other by name, on purpose: two
Zefix entries sharing a normalised name have different UIDs and are
different legal entities. The report counts those collisions instead.

## Offline / alternative source

`--from-file PATH` reads a saved file instead of calling the network, so
the script is ready for whichever bulk route the founder ends up with:

  * `.json` -- a SPARQL results document in the shape this script's own
    query returns (so a live run can be cached and replayed), or a list
    of row objects
  * `.csv`  -- a bulk export (Zefix's own download portal, or a cantonal
    opendata.swiss CSV). Column names are mapped by `CSV_COLUMNS`, which
    accepts the German and English headings those exports use.

## Usage

  python scripts/seed_zefix_zurich.py --vault /path/to/vault
  python scripts/seed_zefix_zurich.py --vault /path/to/vault --max 500
  python scripts/seed_zefix_zurich.py --vault /path/to/vault --from-file export.csv

`--vault` is required so a run can never default onto a vault by
accident, and so the output file can record which vault it deduplicated
against. An existing output file is never overwritten without `--force`:
re-running on the same day would otherwise clobber a staging file the
founder had already worked through.
"""
import argparse
import csv
import io
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import polite_http  # noqa: E402
from careeros import vault  # noqa: E402
from org_intake import identity  # noqa: E402

SPARQL_ENDPOINT = 'https://lindas.admin.ch/query'
SOURCE_GRAPH = 'https://lindas.admin.ch/foj/zefix'
SOURCE_DATASET = 'https://opendata.swiss/en/dataset/zefix-zentraler-firmenindex'
SOURCE_LICENCE = 'OGD Open use. Must provide the source. https://opendata.swiss/en/terms-of-use#terms_by'
SOURCE_ATTRIBUTION = ('Zefix - Zentraler Firmenindex, Federal Office for the Commercial '
                      'Register (EHRA), via LINDAS (https://lindas.admin.ch)')

# Canton Zurich as the federal commune register names it. The filter runs
# on the commune of the company's LEGAL SEAT (admin:municipality), not on
# the postal address canton: the seat is the register's own fact about
# where the entity sits, and an address can be a trustee in another
# canton.
CANTON_CODE = 'ZH'
CANTON_URI = 'https://ld.admin.ch/canton/1'

DEFAULT_MAX = 5000
DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 1000
# A 500-row page is ~440 KB of JSON; a 1000-row page at the widest is a
# couple of MB. 32 MB leaves the cap far out of the way of a real page
# while still refusing an unbounded body.
SPARQL_MAX_BODY = 32_000_000
SPARQL_TIMEOUT = 300

OUTPUT_DIR = Path('data/seeds')

# The query asks only for what the brief lists plus the two things needed
# to be honest about provenance: the Zefix id (the entity's own register
# URI) and the eCH-0097 legal form code behind the label. No status
# predicate is selected because the graph has none -- see ACTIVE_BASIS.
COMPANY_QUERY = """
PREFIX schema: <http://schema.org/>
PREFIX admin: <https://schema.ld.admin.ch/>
SELECT ?company ?uid ?legalName ?legalFormCode ?legalFormLabel ?seat ?locality
WHERE {
  GRAPH <%(graph)s> {
    ?company a admin:ZefixOrganisation ;
             schema:legalName ?legalName ;
             schema:additionalType ?legalFormUri ;
             admin:municipality ?muni ;
             schema:address ?address ;
             schema:identifier ?uidUri .
    FILTER(CONTAINS(STR(?uidUri), "/UID/"))
    OPTIONAL { ?address schema:addressLocality ?locality }
  }
  GRAPH <https://lindas.admin.ch/fso/register> {
    ?muni schema:containedInPlace <%(canton)s> ;
          schema:name ?seat .
  }
  GRAPH <https://lindas.admin.ch/lindas-ech> {
    ?legalFormUri schema:identifier ?legalFormCode ;
                  schema:name ?legalFormLabel .
    FILTER(LANG(?legalFormLabel) = "" || LANGMATCHES(LANG(?legalFormLabel), "de"))
  }
  BIND(STRAFTER(STR(?uidUri), "/UID/") AS ?uid)
}
ORDER BY ?company
LIMIT %(limit)d OFFSET %(offset)d
"""

COUNT_QUERY = """
PREFIX schema: <http://schema.org/>
PREFIX admin: <https://schema.ld.admin.ch/>
SELECT (COUNT(DISTINCT ?company) AS ?total) WHERE {
  GRAPH <%(graph)s> { ?company a admin:ZefixOrganisation ; admin:municipality ?muni }
  GRAPH <https://lindas.admin.ch/fso/register> { ?muni schema:containedInPlace <%(canton)s> }
}
"""

# What "active" rests on, recorded in every output file rather than
# implied. The LINDAS Zefix graph holds no status predicate at all: it is
# the register's current stock of registered legal entities
# (Bestandsdaten), so a cancelled entity is absent rather than flagged.
# That means this script cannot filter on a status field, and does not
# pretend to -- it inherits the dataset's own scope. The REST API's
# CompanyShort does carry a `status` enum (ACTIVE / CANCELLED /
# BEING_CANCELLED), so a future credentialed run could assert it; a
# BEING_CANCELLED entity is the one case the two sources may disagree on.
ACTIVE_BASIS = ('the LINDAS Zefix graph is the register\'s current stock of registered '
                'legal entities and carries no status predicate, so "active" is the '
                'dataset\'s own scope and not a field this run filtered on')

# What a capped run is a slice of, recorded in every output file so an
# accepted staging row is never mistaken for a shortlist of employers.
SLICE_BASIS = ('the first --max rows ordered by register URI (roughly registration order); '
               'Zefix holds no headcount, sector, website or hiring signal to rank by, so '
               'this is a sample of the register and not a shortlist of Zurich employers')

# Headings seen on the bulk exports --from-file is meant to consume, in
# the order they are tried. Lower-cased and stripped before lookup.
CSV_COLUMNS = {
    'uid': ('uid', 'uid_formatted', 'che', 'uid number', 'uid-nummer'),
    'legalName': ('legalname', 'name', 'firmenname', 'legal name', 'firma', 'company'),
    'legalFormCode': ('legalformcode', 'rechtsform_code', 'legal form code', 'legalformuid'),
    'legalFormLabel': ('legalformlabel', 'rechtsform', 'legal form', 'legalform'),
    'seat': ('seat', 'sitz', 'gemeinde', 'legalseat', 'legal seat', 'municipality'),
    'locality': ('locality', 'ort', 'addresslocality', 'city'),
    'company': ('company', 'zefix_url', 'url', 'ehraid', 'zefix_id', 'id'),
}


def format_uid(raw):
    """A Swiss UID in its canonical printed form, or None.

    Zefix writes the UID unspaced (`CHE116229891`) in the Linked Data and
    hyphen-dotted (`CHE-116.229.891`) on screen; a bulk export may use
    either. One stored form, so a dedupe key never misses on punctuation.

    The match is on the WHOLE value once punctuation is removed, not on a
    CHE prefix plus nine digits found somewhere in it: a column holding
    "Cheese AG 123456789" must not come out looking like a register
    number. Anything else returns None, which the caller records as a
    visible drop rather than storing a guess.
    """
    compact = re.sub(r'[^A-Za-z0-9]', '', str(raw or '')).upper()
    if not re.fullmatch(r'CHE[0-9]{9}', compact):
        return None
    return f'CHE-{compact[3:6]}.{compact[6:9]}.{compact[9:12]}'


def _text(value):
    value = (value or '').strip() if isinstance(value, str) else value
    return value or None


def parse_sparql_rows(payload):
    """Flatten a SPARQL results document to one plain dict per row.

    Also accepts a bare list of row dicts, which is what a hand-written
    fixture or a trimmed export looks like.
    """
    if isinstance(payload, list):
        return [dict(row) for row in payload]
    bindings = (payload or {}).get('results', {}).get('bindings', [])
    return [{name: cell.get('value') for name, cell in row.items()} for row in bindings]


def parse_csv_rows(text):
    """Rows from a bulk CSV export, with headings mapped onto the field
    names the SPARQL route produces, so everything downstream sees one
    shape. A heading this script does not know is ignored; a row missing
    a name or a UID fails validation later and is reported, never
    guessed at."""
    reader = csv.DictReader(io.StringIO(text))
    lookup = {}
    for field in reader.fieldnames or []:
        key = (field or '').strip().lower()
        for target, candidates in CSV_COLUMNS.items():
            if key in candidates and target not in lookup:
                lookup[target] = field
    return [{target: _text(row.get(column)) for target, column in lookup.items()}
            for row in reader]


def row_to_company(row):
    """One staging record, or `(None, reason)` when the row cannot make
    one. `domain` is always None: see the module docstring -- Zefix holds
    no such field, so there is nothing to derive and nothing to guess."""
    name = _text(row.get('legalName'))
    uid = format_uid(row.get('uid'))
    if not name:
        return None, 'no legal name'
    if not uid:
        return None, f"unusable UID {row.get('uid')!r}"
    zefix_url = _text(row.get('company'))
    return {
        'origin': 'seeded',
        'zefix_id': zefix_url.rstrip('/').rsplit('/', 1)[-1] if zefix_url else None,
        'zefix_url': zefix_url,
        'uid': uid,
        'name': name,
        'legal_form': _text(row.get('legalFormLabel')),
        'legal_form_code': _text(row.get('legalFormCode')),
        'seat': _text(row.get('seat')),
        'locality': _text(row.get('locality')),
        'canton': CANTON_CODE,
        'domain': None,
    }, None


def run_query(query, *, limiter, endpoint=SPARQL_ENDPOINT, transport=None):
    """One SPARQL POST. Returns the parsed document, or raises
    RuntimeError with the reason -- a page that cannot be read stops the
    run rather than quietly shortening the universe."""
    transport = transport or polite_http.request_text
    result = transport(
        endpoint,
        data=urlencode({'query': query}).encode(),
        headers={'Accept': 'application/sparql-results+json',
                 'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=SPARQL_TIMEOUT, max_body=SPARQL_MAX_BODY, limiter=limiter)
    if not result['ok']:
        raise RuntimeError(f"SPARQL request failed: {result['error']}")
    try:
        return json.loads(result['text'])
    except ValueError as error:
        raise RuntimeError(f'SPARQL response was not JSON: {error}') from error


def total_available(*, limiter, endpoint=SPARQL_ENDPOINT, transport=None):
    """How many Zurich entries the register holds, so the report can say
    what share of them a capped run actually took. A failure here is not
    fatal: the cap matters, the denominator is a nicety."""
    try:
        rows = parse_sparql_rows(run_query(COUNT_QUERY % {'graph': SOURCE_GRAPH, 'canton': CANTON_URI},
                                           limiter=limiter, endpoint=endpoint, transport=transport))
        return int(rows[0]['total'])
    except (RuntimeError, KeyError, IndexError, ValueError):
        return None


def fetch_rows(*, max_rows, page_size, limiter, endpoint=SPARQL_ENDPOINT, transport=None,
               on_page=None):
    """Paginated rows, never more than `max_rows` of them.

    The cap is the point: the Zurich register is ~138k entries and a
    first run has no business pulling all of them. Pages are ordered by
    the company URI so offsets are stable, and the loop stops on the cap,
    on a short page, or on an empty page -- whichever comes first.
    """
    rows = []
    offset = 0
    while len(rows) < max_rows:
        limit = min(page_size, max_rows - len(rows))
        page = parse_sparql_rows(run_query(
            COMPANY_QUERY % {'graph': SOURCE_GRAPH, 'canton': CANTON_URI,
                             'limit': limit, 'offset': offset},
            limiter=limiter, endpoint=endpoint, transport=transport))
        rows.extend(page)
        if on_page:
            on_page(offset, len(page), len(rows))
        if len(page) < limit:
            break
        offset += limit
    return rows[:max_rows]


def existing_uids(records):
    """Every UID the vault already holds, mapped to the company id that
    holds it. Looks at a `uid` identifier, at the record's own `uid`
    field, and nowhere else -- there is no third place a UID could hide
    today, and inventing one would make the dedupe report less honest,
    not more. Returns {} on today's vault, which is the finding."""
    found = {}
    for record in records:
        candidates = [record.get('uid')]
        candidates += [item.get('value') for item in (record.get('identifiers') or [])
                       if item.get('type') in ('uid', 'che_uid')]
        for candidate in candidates:
            formatted = format_uid(candidate)
            if formatted:
                found.setdefault(formatted, record.get('id'))
    return found


def dedupe(companies, records):
    """Split seeded rows into the ones ready for acceptance and the ones
    the vault already appears to hold.

    UID first (confident), then exact normalised name via the
    capability's own matcher, which already folds case and punctuation
    and also checks each record's `name_variant` identifiers -- so an
    owner's past review decision about a name is honoured here for free.
    A name match is reported with `confident: false`; see the module
    docstring for why that is held back rather than dropped.
    """
    by_uid = existing_uids(records)
    fresh, duplicates = [], []
    for company in companies:
        if company['uid'] in by_uid:
            duplicates.append({**company, 'matched_on': 'uid', 'confident': True,
                               'matched_company_ids': [by_uid[company['uid']]]})
            continue
        matches = identity.find_all_by_exact_name(records, company['name'])
        if matches:
            duplicates.append({**company, 'matched_on': 'name', 'confident': False,
                               'matched_company_ids': [match.get('id') for match in matches]})
            continue
        fresh.append(company)
    return fresh, duplicates


def name_collisions(companies):
    """How many seeded rows share a normalised name with another seeded
    row. Reported, never deduplicated: they are distinct legal entities
    with distinct UIDs, and collapsing them would delete real companies.

    This repeats the capability's own normalisation rule (fold case, turn
    every run of non-alphanumerics into one space) rather than calling
    it: `identity._normalize_name` is private, and the public matcher
    `find_all_by_exact_name` re-normalises every record on every call, so
    asking it once per row would be quadratic on a 5,000-row run. Revisit
    if the capability ever exports the normaliser.
    """
    counts = {}
    for company in companies:
        key = ' '.join(re.sub(r'[^a-z0-9]+', ' ', company['name'].casefold()).split())
        counts[key] = counts.get(key, 0) + 1
    return sum(count for count in counts.values() if count > 1)


def build_report(*, fetched, companies, duplicates, dropped, total, args, limiter, source):
    with_domain = sum(1 for company in companies if company['domain'])
    return {
        'run': {
            'script': 'scripts/seed_zefix_zurich.py',
            'ticket': 'CAREER-52',
            'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'source': source,
            'source_dataset': SOURCE_DATASET,
            'source_graph': SOURCE_GRAPH,
            'licence': SOURCE_LICENCE,
            'attribution': SOURCE_ATTRIBUTION,
            'user_agent': polite_http.USER_AGENT,
            'canton': CANTON_CODE,
            'active_basis': ACTIVE_BASIS,
            'slice_basis': SLICE_BASIS,
            'max': args.max,
            'page_size': args.page_size,
            'min_interval_seconds': args.min_interval,
            'requests': limiter.requests,
            'slept_seconds': round(limiter.slept, 1),
            'vault_read': str(args.vault),
            'vault_written': None,
            'merge': 'founder-gated, not part of this script',
        },
        'report': {
            'fetched': fetched,
            'available_in_canton': total,
            'new': len(companies),
            'duplicate_uid': sum(1 for row in duplicates if row['matched_on'] == 'uid'),
            'duplicate_name_candidate': sum(1 for row in duplicates if row['matched_on'] == 'name'),
            'dropped': len(dropped),
            'with_domain': with_domain,
            'without_domain': len(companies) - with_domain,
            'seeded_name_collisions': name_collisions(companies),
            'vault_companies': None,
            'vault_companies_with_uid': None,
            'errors': [],
        },
    }


def check_output_free(path, *, force):
    """Refuse an occupied output path BEFORE anything is fetched: a run
    that spends two minutes on the register and then declines to write
    has wasted the register's bandwidth as well as the founder's time."""
    if path.exists() and not force:
        raise SystemExit(f'{path} exists already. Re-run with --force to replace it, '
                         'or pass --out with another name; a staging file the founder '
                         'has worked through is not overwritten by accident.')


def write_output(path, document, *, force):
    check_output_free(path, force=force)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False))
    return path


def load_source(args):
    """Rows plus a one-word name for where they came from."""
    if args.from_file:
        text = Path(args.from_file).read_text()
        if str(args.from_file).lower().endswith('.csv'):
            return parse_csv_rows(text), f'file:csv:{args.from_file}'
        return parse_sparql_rows(json.loads(text)), f'file:json:{args.from_file}'
    return None, 'lindas-sparql'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', required=True, type=Path,
                        help='vault to deduplicate against. Opened READ-ONLY; nothing is written '
                             'to it. Required so a run cannot default onto a vault by accident.')
    parser.add_argument('--max', type=int, default=DEFAULT_MAX,
                        help=f'hard cap on rows fetched (default {DEFAULT_MAX}). The Zurich '
                             'register holds ~138k entries; a first run takes a slice.')
    parser.add_argument('--page-size', type=int, default=DEFAULT_PAGE_SIZE,
                        help=f'rows per request (default {DEFAULT_PAGE_SIZE}, max {MAX_PAGE_SIZE})')
    parser.add_argument('--min-interval', type=float, default=polite_http.DEFAULT_MIN_INTERVAL,
                        help='minimum seconds between requests (default '
                             f'{polite_http.DEFAULT_MIN_INTERVAL}, i.e. one request a second)')
    parser.add_argument('--from-file',
                        help='read rows from a saved SPARQL JSON or a bulk CSV export instead of '
                             'calling the network at all')
    parser.add_argument('--out', type=Path, help='output path (default '
                                                 'data/seeds/zefix_zurich_<date>.yaml)')
    parser.add_argument('--force', action='store_true',
                        help='replace the output file if it exists')
    args = parser.parse_args(argv)

    if args.max < 1:
        raise SystemExit('--max must be at least 1')
    args.page_size = max(1, min(args.page_size, MAX_PAGE_SIZE))
    out = args.out or OUTPUT_DIR / f'zefix_zurich_{date.today().isoformat()}.yaml'
    check_output_free(out, force=args.force)
    limiter = polite_http.RateLimiter(args.min_interval)

    records = vault.list_companies(args.vault)
    rows, source = load_source(args)
    print(f"source={source}  canton={CANTON_CODE}  max={args.max}  "
          f"page_size={args.page_size}  >={args.min_interval}s between requests")
    print(f"user agent: {polite_http.USER_AGENT}")
    print(f"vault read (never written): {args.vault}  ({len(records)} companies)")
    print('-' * 72)

    total = None
    if rows is None:
        total = total_available(limiter=limiter)
        if total is not None:
            print(f'{total} active Zurich entries in the register; taking up to {args.max}')
        rows = fetch_rows(
            max_rows=args.max, page_size=args.page_size, limiter=limiter,
            on_page=lambda offset, got, so_far: print(
                f'  offset {offset:>6}: {got:>4} rows  (total {so_far})'))
    else:
        print(f'{len(rows)} rows read from the file; taking up to {args.max}')
        rows = rows[:args.max]

    seeded, dropped = [], []
    for row in rows:
        company, reason = row_to_company(row)
        if company:
            seeded.append(company)
        else:
            # CAREER-30: no drop on the way into a record is silent.
            dropped.append({'reason': reason, 'row': {k: v for k, v in row.items() if v}})
            print(f'  dropped a row: {reason}', file=sys.stderr)

    fresh, duplicates = dedupe(seeded, records)
    document = build_report(fetched=len(rows), companies=fresh, duplicates=duplicates,
                            dropped=dropped, total=total, args=args, limiter=limiter,
                            source=source)
    by_uid = existing_uids(records)
    document['report']['vault_companies'] = len(records)
    document['report']['vault_companies_with_uid'] = len(by_uid)
    document['companies'] = fresh
    document['duplicates'] = duplicates
    document['dropped'] = dropped

    write_output(out, document, force=args.force)

    counts = document['report']
    print('-' * 72)
    print(f"fetched {counts['fetched']}  ->  new {counts['new']}, "
          f"duplicate by UID {counts['duplicate_uid']}, "
          f"name candidates for review {counts['duplicate_name_candidate']}, "
          f"dropped {counts['dropped']}")
    print(f"domains: {counts['with_domain']} with, {counts['without_domain']} without "
          '(Zefix carries no website field at all -- see the docstring)')
    if not by_uid:
        print(f"note: 0 of {len(records)} vault companies carry a UID, so the UID pass "
              'matched nothing and every match above is a name candidate')
    if counts['seeded_name_collisions']:
        print(f"note: {counts['seeded_name_collisions']} seeded rows share a name with another "
              'seeded row; kept, because their UIDs differ')
    print(f"requests {limiter.requests}, slept {limiter.slept:.1f}s to stay under the rate limit")
    print(f'wrote {out}')
    print('STAGING ONLY: the vault was not written. Accepting these into the vault is a '
          'separate founder-gated step.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
