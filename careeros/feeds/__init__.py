"""Job-feed adapters: discovery, fetch, map, filter, freeze, export.

CAREER-53 builds the golden-set pool out of Personio's public job XML
feeds. The spec's instruction is that the next adapter (Greenhouse) must
be "a new mapper, not a new pipeline", so this package is split that way
from the start:

  * `personio` -- the only Personio-specific module. The feed URL shape,
    the XML parse, and the field mapping from Personio's vocabulary onto
    CareerOS value records. A Greenhouse adapter is a sibling module with
    the same three entry points (`feed_urls`, `parse_feed`, `map_posting`)
    and nothing else to write.
  * `geocode` -- Swiss office text -> BFS municipality number. Provider
    agnostic: an office line is an office line.
  * `store` -- the run manifest, the immutable snapshots and the
    closure/reopen bookkeeping. Keyed by `{provider}:{tenant}:{id}`, so
    it holds two providers' postings without changing shape.
  * `discovery` -- finding tenants. The vault route and the feed-probe
    route are provider-agnostic; the Common Crawl host pattern is the one
    provider-specific input, and it is an argument.
  * `export` -- the golden-set pool file.

NOTHING HERE TOUCHES THE NETWORK BY ITSELF. Every function that needs a
response takes a `fetch` callable, which `scripts/run_personio_fetch.py`
wires to `scripts/polite_http.request_text` (shared user agent, one
request a second, robots check). That is why the whole package is
testable offline against recorded real feeds, and why the suite's network
guard never has to be worked around.

NOTHING HERE WRITES TO THE VAULT either. Output stages under
`data/personio/`; moving an accepted posting or a matched company into
the vault is a separate owner-gated step, the same rule
`scripts/seed_zefix_zurich.py` follows.
"""
