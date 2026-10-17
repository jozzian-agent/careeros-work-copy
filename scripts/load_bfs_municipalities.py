"""Load the BFS municipality register into the taxonomy's location.yaml.

CAREER-53 needs to turn a Personio office line ("CH - Zürich",
"8004 Zürich", "Winterthur") into a BFS Gemeindenummer, and
`careeros/data/taxonomy/location.yaml` shipped its municipality dimension
as an honest stub: 26 cantons and `codes: []`, with the register named as
the source it could not reach offline (CAREER-55). This script is what
fills it, and the only thing that is allowed to: the file's own todo says
not to type entries by hand, because a municipality number that merged
away would silently mislocate every record carrying it.

## The source, and the licence

The register is the BFS *Amtliches Gemeindeverzeichnis der Schweiz*. Its
machine distribution is Linked Data in LINDAS, the federal Linked Data
Service operated by the Swiss Federal Archives, queryable over the public
SPARQL endpoint `https://lindas.admin.ch/query` with no credentials. Two
graphs are read:

  * `https://lindas.admin.ch/fso/register` -- the register itself. Every
    `admin:PoliticalMunicipality`, its official `schema:name`, and the
    canton it is `schema:containedInPlace`. Superseded entries are typed
    `version:Deprecated` and are filtered out, so what is loaded is the
    register's current stock rather than its history.
  * `https://lindas.admin.ch/territorial` -- the LINDAS `municipality`
    shared dimension (`https://ld.admin.ch/dimension/municipality`),
    which carries `schema:postalCode` per municipality. That is the
    postal-code half: without it "8004 Zürich" is not resolvable.

Licence: OGD Open use, must provide the source
(https://opendata.swiss/en/terms-of-use#terms_by). The attribution line
and both graph URIs are written into location.yaml's
`municipality_source` block so the condition travels with the data.

**robots.txt.** `lindas.admin.ch/robots.txt` is `Disallow: /` for every
agent. That file governs crawlers walking pages; this endpoint is the
dataset's own documented query service, published by the federal
administration as the way to read this data programmatically. The same
reasoning is already owner-accepted for `scripts/seed_zefix_zurich.py`,
which calls the same endpoint -- see its docstring. This script makes two
requests, identifies itself with the shared CareerOS user agent, and runs
through the shared rate limiter.

## What it writes, and what it will not touch

Only the municipality dimension of location.yaml, between the two
`# BEGIN/END generated municipality codes` marker lines, plus the three
header fields that have to move with it (`taxonomy_version`,
`changed_at`, `standard_version`) and `municipality_source.loaded_at`.
Every hand-written comment, the canton list, the record shape and the
open questions are left exactly as they are: the file is prose as much as
data, and a `yaml.safe_dump` round-trip would delete all of it.

The dimension stays `complete: false`. The register changes several times
a year through mergers, so the right claim is "this is the register as of
the load date", which is what the todo says. Keeping it incomplete is
also what makes `taxonomy.make_value_record` accept a municipality code
that is newer than this load instead of refusing it.

## Versioning

Per PROJECT.md's versioning rule, any change to a taxonomy file bumps its
`taxonomy_version`. A write here bumps the minor version (adding codes is
additive) and sets `changed_at` to the run date. `--check` compares the
live register against what the file holds and writes nothing, which is
what a daily job or a reviewer wants.

## Usage

  python scripts/load_bfs_municipalities.py            # fetch and write
  python scripts/load_bfs_municipalities.py --check    # compare only
  python scripts/load_bfs_municipalities.py --from-file saved.json
  python scripts/load_bfs_municipalities.py --save-response saved.json

`--from-file` replays a saved SPARQL results document, so a load can be
reproduced without the network and so a reviewer can see exactly what the
live run returned.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import polite_http  # noqa: E402

SPARQL_ENDPOINT = 'https://lindas.admin.ch/query'
REGISTER_GRAPH = 'https://lindas.admin.ch/fso/register'
POSTAL_CODE_GRAPH = 'https://lindas.admin.ch/territorial'
SHARED_DIMENSION = 'https://ld.admin.ch/dimension/municipality'
SOURCE_LICENCE = ('OGD Open use. Must provide the source. '
                  'https://opendata.swiss/en/terms-of-use#terms_by')
SOURCE_ATTRIBUTION = ('Amtliches Gemeindeverzeichnis der Schweiz, Federal Statistical '
                      'Office (BFS), via LINDAS (https://lindas.admin.ch)')

TAXONOMY_FILE = Path('careeros/data/taxonomy/location.yaml')
BEGIN_MARKER = '    # BEGIN generated municipality codes'
END_MARKER = '    # END generated municipality codes'

# ~2 100 municipalities with ~3 200 postal codes between them is a couple
# of megabytes of SPARQL JSON. 32 MB is the same cap seed_zefix_zurich.py
# uses: far out of the way of a real response, still not unbounded.
MAX_BODY = 32_000_000
TIMEOUT = 300

# A canton is the parent of a municipality through one or more
# containedInPlace hops (municipality -> district -> canton in most
# cantons, municipality -> canton in the ones with no districts), so the
# property path is `+` and the FILTER is what picks the canton out of the
# chain. Deprecated versions of a municipality are excluded by type, not
# by date: the register types a superseded entry version:Deprecated, and
# that is the register's own statement rather than our reading of one.
MUNICIPALITY_QUERY = """
PREFIX schema: <http://schema.org/>
PREFIX admin: <https://schema.ld.admin.ch/>
PREFIX version: <https://version.link/>
SELECT ?muni ?name ?canton ?plz WHERE {
  GRAPH <%(register)s> {
    ?muni a admin:PoliticalMunicipality ;
          schema:name ?name ;
          schema:containedInPlace+ ?canton .
    FILTER(CONTAINS(STR(?canton), "/canton/"))
    FILTER NOT EXISTS { ?muni a version:Deprecated }
  }
  OPTIONAL { GRAPH <%(postal)s> { ?muni schema:postalCode ?plz } }
}
""" % {'register': REGISTER_GRAPH, 'postal': POSTAL_CODE_GRAPH}

# What a load has to clear before it is allowed to overwrite a working
# list. These are not style checks: a query that silently returned half
# the register would otherwise retire thousands of real codes.
MIN_MUNICIPALITIES = 1800
EXPECTED_CANTONS = 26
#: Canton 1 is Zurich, which is the one canton CAREER-53 cannot work
#: without. The official count has been 160 since the 2023 mergers; a
#: load that finds many fewer is a broken query, not a merger wave.
MIN_ZURICH_MUNICIPALITIES = 150


def fetch_rows(*, fetch=None, limiter=None):
    """Run the register query and return the raw SPARQL results document.

    Raises RuntimeError on anything that is not a parseable results
    document, because a partial answer here becomes a wrong municipality
    number later.
    """
    fetch = fetch or polite_http.request_text
    result = fetch(SPARQL_ENDPOINT, data=f'query={_quote(MUNICIPALITY_QUERY)}'.encode(),
                   headers={'Accept': 'application/sparql-results+json',
                            'Content-Type': 'application/x-www-form-urlencoded'},
                   timeout=TIMEOUT, max_body=MAX_BODY, limiter=limiter)
    if not result['ok']:
        raise RuntimeError(f"LINDAS query failed: {result['error']} "
                           f"(status {result['status']})")
    try:
        return json.loads(result['text'])
    except ValueError as error:
        raise RuntimeError(f'LINDAS returned something that is not JSON: {error}') from None


def _quote(value):
    from urllib.parse import quote_plus
    return quote_plus(value)


def parse_rows(document):
    """SPARQL bindings -> {code: {code, label, canton, postal_codes}}.

    One row per (municipality, postal code) pair, so the rows are folded
    by municipality number. A municipality with no postal code in the
    shared dimension keeps an empty list rather than being dropped: it is
    still a real municipality and a name match can still land on it.
    """
    try:
        bindings = document['results']['bindings']
    except (KeyError, TypeError):
        raise RuntimeError('not a SPARQL results document: no results.bindings') from None
    municipalities = {}
    for row in bindings:
        try:
            uri = row['muni']['value']
            label = row['name']['value']
            canton_uri = row['canton']['value']
        except (KeyError, TypeError):
            raise RuntimeError('a row is missing muni, name or canton') from None
        code = uri.rstrip('/').rsplit('/', 1)[-1]
        canton = canton_uri.rstrip('/').rsplit('/', 1)[-1]
        if not code.isdigit() or not canton.isdigit():
            raise RuntimeError(f'unexpected URI shape: {uri} in canton {canton_uri}')
        entry = municipalities.setdefault(code, {'code': code, 'label': label,
                                                 'canton': canton, 'postal_codes': set()})
        if entry['label'] != label or entry['canton'] != canton:
            # Two different names or cantons for one number means the
            # deprecated filter let a historical version through, and
            # picking one of them would be a coin toss.
            raise RuntimeError(f'municipality {code} came back twice with different '
                               f'name or canton ({entry["label"]}/{entry["canton"]} vs '
                               f'{label}/{canton})')
        postal = (row.get('plz') or {}).get('value')
        if postal:
            entry['postal_codes'].add(str(postal))
    return {code: {**entry, 'postal_codes': sorted(entry['postal_codes'])}
            for code, entry in municipalities.items()}


def check_load(municipalities):
    """Refuse a load that cannot be the whole register. Returns the
    canton -> count map so a caller can print it."""
    if len(municipalities) < MIN_MUNICIPALITIES:
        raise RuntimeError(f'only {len(municipalities)} municipalities came back; the register '
                           f'holds over {MIN_MUNICIPALITIES}, so this is a partial answer and '
                           'not something to overwrite a working list with')
    counts = {}
    for entry in municipalities.values():
        counts[entry['canton']] = counts.get(entry['canton'], 0) + 1
    if len(counts) != EXPECTED_CANTONS:
        raise RuntimeError(f'{len(counts)} cantons are represented, expected {EXPECTED_CANTONS}')
    if counts.get('1', 0) < MIN_ZURICH_MUNICIPALITIES:
        raise RuntimeError(f"canton Zurich came back with {counts.get('1', 0)} municipalities, "
                           f'expected at least {MIN_ZURICH_MUNICIPALITIES}')
    return counts


def render_codes(municipalities):
    """The generated block, as the text that goes between the markers.

    Hand-rendered rather than `yaml.safe_dump`ed so the indentation
    matches the rest of the file and a diff between two loads reads as
    the municipalities that changed. Every value is quoted, because a BFS
    number and a postal code are strings in this taxonomy (location.yaml
    says why) and an unquoted 8001 is an integer.
    """
    lines = ['    codes:']
    for code in sorted(municipalities, key=int):
        entry = municipalities[code]
        lines.append(f'      - code: "{entry["code"]}"')
        lines.append(f'        label: {json.dumps(entry["label"], ensure_ascii=False)}')
        lines.append(f'        canton: "{entry["canton"]}"')
        if entry['postal_codes']:
            codes = ', '.join(f'"{plz}"' for plz in entry['postal_codes'])
            lines.append(f'        postal_codes: [{codes}]')
        else:
            lines.append('        postal_codes: []')
    return '\n'.join(lines)


def bump_minor(version):
    major, minor, patch = (int(part) for part in str(version).split('.'))
    return f'{major}.{minor + 1}.{patch}'


def splice(text, municipalities, *, today):
    """Replace the generated block and the header fields that move with
    it. Everything else in the file is returned untouched."""
    begin = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if begin < 0 or end < 0 or end < begin:
        raise RuntimeError(f'{TAXONOMY_FILE} has no generated-code markers to write between; '
                           'add them back before loading')
    head = text[:begin]
    block_start = text.index('\n', begin) + 1
    body = render_codes(municipalities)
    text = head + text[begin:block_start] + body + '\n' + text[end:]

    current = re.search(r'^taxonomy_version: "([0-9.]+)"$', text, re.M)
    if not current:
        raise RuntimeError(f'{TAXONOMY_FILE} has no taxonomy_version line to bump')
    text = text.replace(current.group(0), f'taxonomy_version: "{bump_minor(current.group(1))}"', 1)
    text = re.sub(r'^changed_at: ".*"$', f'changed_at: "{today}"', text, count=1, flags=re.M)
    text = re.sub(r'^standard_version: ".*"$',
                  'standard_version: "canton list stable since 1979 (26 cantons); municipality '
                  f'register as published in LINDAS on {today}"',
                  text, count=1, flags=re.M)
    text = re.sub(r'^(  loaded_at: ").*(")$', rf'\g<1>{today}\g<2>', text, count=1, flags=re.M)
    return text


def stored_municipalities(path):
    """What the file holds today, in the shape `parse_rows` returns, so a
    check compares like with like."""
    data = yaml.safe_load(path.read_text())
    for code_list in data.get('code_lists', ()):
        if code_list.get('dimension') == 'municipality':
            return {entry['code']: {'code': entry['code'], 'label': entry['label'],
                                    'canton': entry['canton'],
                                    'postal_codes': list(entry.get('postal_codes') or ())}
                    for entry in (code_list.get('codes') or ())}
    raise RuntimeError(f'{path} carries no municipality dimension')


def diff(stored, loaded):
    """What a write would change, as three lists a report can print."""
    added = sorted(set(loaded) - set(stored), key=int)
    removed = sorted(set(stored) - set(loaded), key=int)
    changed = sorted((code for code in set(stored) & set(loaded)
                      if stored[code] != loaded[code]), key=int)
    return {'added': added, 'removed': removed, 'changed': changed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true',
                        help='compare the register against the stored list and write nothing')
    parser.add_argument('--from-file', type=Path,
                        help='replay a saved SPARQL results document instead of calling LINDAS')
    parser.add_argument('--save-response', type=Path,
                        help='write the raw SPARQL response beside the load, for reproducibility')
    parser.add_argument('--taxonomy-file', type=Path, default=TAXONOMY_FILE)
    args = parser.parse_args(argv)

    if args.from_file:
        document = json.loads(args.from_file.read_text())
        print(f'Replaying {args.from_file}')
    else:
        limiter = polite_http.RateLimiter()
        print(f'Querying {SPARQL_ENDPOINT} ({REGISTER_GRAPH} + {POSTAL_CODE_GRAPH})')
        document = fetch_rows(limiter=limiter)
        if args.save_response:
            args.save_response.parent.mkdir(parents=True, exist_ok=True)
            args.save_response.write_text(json.dumps(document))
            print(f'Saved the raw response to {args.save_response}')

    loaded = parse_rows(document)
    counts = check_load(loaded)
    postal = sum(len(entry['postal_codes']) for entry in loaded.values())
    print(f'{len(loaded)} municipalities in {len(counts)} cantons, '
          f'{postal} municipality/postal-code pairs; '
          f"canton Zurich (1): {counts.get('1')}")

    stored = stored_municipalities(args.taxonomy_file)
    changes = diff(stored, loaded)
    print(f"Against {args.taxonomy_file}: {len(changes['added'])} to add, "
          f"{len(changes['removed'])} to remove, {len(changes['changed'])} to change")
    for kind in ('added', 'removed', 'changed'):
        if changes[kind]:
            sample = ', '.join(changes[kind][:12])
            more = '' if len(changes[kind]) <= 12 else f" (+{len(changes[kind]) - 12} more)"
            print(f'  {kind}: {sample}{more}')

    if args.check:
        print('--check: nothing written.')
        return 0 if not any(changes.values()) else 1
    if not any(changes.values()):
        print('Already current; nothing written.')
        return 0

    text = splice(args.taxonomy_file.read_text(), loaded, today=date.today().isoformat())
    args.taxonomy_file.write_text(text)
    print(f'Wrote {args.taxonomy_file}. Licence condition: {SOURCE_LICENCE}')
    print(f'Attribution: {SOURCE_ATTRIBUTION}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
