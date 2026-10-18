"""Job-feed adapters: discovery, fetch, map, filter, freeze, export.

CAREER-53 built the Personio adapter and promised that the next one
would be "a new mapper, not a new pipeline". CAREER-54 is five more
adapters and the contract that makes the promise checkable:

  * `base` -- THE CONTRACT. What a provider adapter must supply (its
    variants, its parse, its field mapping, its documentation URL, its
    tenant pattern, its crawl patterns) and everything it gets for free
    (the gzip codec, the HTML-to-text pass, the Pensum reader, the
    content hash, the value-record shapes and the provenance block).
    `check_adapter` is the list and the suite runs it over every
    registered adapter, so a seventh provider cannot half-exist.
  * `registry` -- which adapters exist, plus the four providers the ATS
    platform map counts from a crawl index without being able to fetch
    them (Workday above all).
  * `personio`, `greenhouse`, `lever`, `ashby`, `recruitee`,
    `smartrecruiters` -- one module each, and the ONLY place anything
    provider-specific lives. Each one's docstring carries the endpoint
    it was built against, the day that documentation was read, what the
    live API actually returned, and the field decisions it refused to
    make.
  * `geocode` -- Swiss office text -> BFS municipality number. Provider
    agnostic: an office line is an office line. It takes the country
    field the four JSON providers state, which is what finally rules out
    a foreign town that shares a Swiss municipality name.
  * `store` -- the run manifest, the immutable snapshots and the
    closure/reopen bookkeeping, one root per provider. It is where the
    provenance contract is ENFORCED: a posting that cannot name its own
    source chain is refused outright.
  * `fetch` -- requests, retries, conditional requests, variant groups,
    paging, the detail pass, the geocode pass. No provider name in it.
  * `discovery` -- finding tenants: the vault route, the careers-page
    route and the Common Crawl index, with each provider's URL patterns
    as an argument.
  * `export` -- the golden-set pool, now multi-provider: every row names
    its provider and its whole source chain.
  * `platform_map` -- which company uses which hiring platform, with
    four confidence levels that are never mixed (owner ruling
    2026-10-17).

NOTHING HERE TOUCHES THE NETWORK BY ITSELF. Every function that needs a
response takes a `fetch` callable, which `scripts/run_ats_fetch.py`
wires to `scripts/polite_http.request_text` (shared user agent, one
request a second, robots check). That is why the whole package is
testable offline against recorded real feeds, and why the suite's
network guard never has to be worked around.

NOTHING HERE WRITES TO THE VAULT either. Output stages under
`data/personio/` and `data/ats/<provider>/`; moving an accepted posting
or a matched company into the vault is a separate owner-gated step, the
same rule `scripts/seed_zefix_zurich.py` follows.
"""
