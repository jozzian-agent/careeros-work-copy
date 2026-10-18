# CAREER-54 trial report — five more ATS adapters, and the platform map

Run live on **2026-10-17** against the public job APIs of Greenhouse,
Lever, Ashby, Recruitee and SmartRecruiters, the Common Crawl URL index,
and the live vault's own companies' websites. Everything below is a
measurement. Where a number is extrapolated it says so and says from
what.

The adapters are `careeros/feeds/`, the contract they share is
`careeros/feeds/base.py`, the runner is `scripts/run_ats_fetch.py`
(`scripts/run_personio_fetch.py` is the same program with Personio's
defaults, kept working). This report and the platform map
(`data/ats_platform_map.yaml`, `data/ats_platform_map_2026-10-17.md`)
are the tracked output; everything else under `data/ats/` is regenerable
and gitignored.

The Personio half of the picture is CAREER-53's own report,
`data/personio/TRIAL_REPORT.md`, and is not repeated here except where
this run corrects it (§8) or adds to its totals (§6).

---

## 1. What ran live, and what did not

| | |
|---|---|
| **Ran live** | Each provider's own API documentation, read and quoted; a shape probe of all five APIs against a real tenant each; `robots.txt` of all five API hosts; a careers-page probe over the live vault's 53 companies (one homepage each plus one careers page, 63 pages); Common Crawl `collinfo.json` and CDX queries over two indexes for the five adapted providers and one index for the four counted-only ones; a capped random-sample feed fetch per provider; the multi-provider pool export; the platform map |
| **Capped on purpose** | 150 tenants per provider, drawn at random with seed 54 (owner ruling 2026-10-17: no multi-hour crawls). No full crawl of any provider, and **no new Personio fetch at all** — CAREER-53's measurements stand and its store is read as it is |
| **Not run** | Occupation classification (forbidden here; CAREER-57 owns it). Any write to the vault. Any commit. |
| **Never touched** | The live vault was opened **read-only** (53 companies, 44 jobs). The pinned capability is unchanged, so the submodule pin does not move. |

---

## 2. Discovery: how many tenants each platform has

`discover --provider <p> --common-crawl --crawls 2 --probe-file … --vault …`
for the five adapted providers, `--crawls 1` for the four counted-only
ones. Console output is `discover_2026-10-17.log`; the raw index lines
are kept per provider as `cdx_2026-10-17.jsonl`, so every discovery run
replays offline with `--from-file`.

| Provider | Tenants found | CDX urls read | Index pages read/available | Still truncated | Pages lost | Vault route hits | Probe-file hits |
|---|---|---|---|---|---|---|---|
| personio (CAREER-53, unchanged) | 2467 | 29833 | - | - | - | 1 | 0 |
| greenhouse | 2923 | 51018 | 3 of 6 | 2 | 0 | 1 | 1 |
| lever | 91 | 826 | 2 of 2 | 0 | 0 | 0 | 0 |
| ashby | 3038 | 21819 | 2 of 2 | 0 | 0 | 3 | 3 |
| recruitee | 452 | 5294 | 1 of 1 | 0 | 0 | 0 | 0 |
| smartrecruiters | 629 | 3304 | 1 of 1 | 0 | 0 | 0 | 0 |
| join (counted only) | 963 | 6413 | 1 of 1 | 0 | 0 | 0 | 1 |
| refline (counted only) | 2 | 0 | 1 of 1 | 0 | 1 | 0 | 2 |
| teamtailor (counted only) | 0 | 0 | 2 of 2 | 0 | 2 | 0 | 0 |
| workday (counted only) | 746 | 28152 | 2 of 5 | 1 | 0 | 0 | 3 |

Counted-only providers have no adapter (yet) and were discovered from one CDX
index each so the platform map can size them; the Workday row is the
build-or-skip number the plan asked for. teamtailor and refline lost pages to
index truncation and are therefore floors, not counts.

---

## 3. The capped fetch per provider

Random sample of at most 150 tenants per provider, seed 54, one request a
second for the whole run. personio's row is CAREER-53's 400-tenant trial,
carried over and not re-fetched (owner ruling: no full crawl).

| Provider | Queued | Fetched ok | Dead | Other | Feeds read | Parse success | Postings | Zurich postings | Geocoded | Zurich tenants | Requests |
|---|---|---|---|---|---|---|---|---|---|---|---|
| personio (53) | 400 | 270 | 131 | 0 | 15 | 100% | 193 | 43 | 43 | 9 | 15 |
| greenhouse | 150 | 123 | 27 | 0 | 150 | 100% | 5426 | 9 | 9 | 1 | 150 |
| lever | 91 | 83 | 8 | 0 | 182 | 100% | 10222 | 12 | 12 | 4 | 182 |
| ashby | 150 | 131 | 18 | 1 | 149 | 100% | 3908 | 11 | 11 | 4 | 149 |
| recruitee | 150 | 143 | 7 | 0 | 150 | 100% | 2181 | 16 | 16 | 5 | 150 |
| smartrecruiters | 150 | 150 | 0 | 0 | 468 | 100% | 25301 | 113 | 113 | 10 | 468 |

Every readable feed parsed. SmartRecruiters paginates at 100 postings, hence
468 feeds for 150 tenants; its zero dead tenants reflect that discovery there
came from the provider's own company-list pattern. The one "other" ashby row
is a tenant whose board name is not a board name (`superhuman platform inc`)
— recorded, not dropped.

---

## 4. The Zurich pool as it stands

From the capped trial only (43 personio postings from CAREER-53 + 161 from
this run):

- **204 Zurich postings, 33 tenants, 23 companies, 8 BFS municipalities.**
- Zurich evidence: 152 corroborated (Swiss postal code / ISO CH /
  "Switzerland" in the location), 52 name-only ("Zurich" as a string) —
  owner question 2 in §9.
- Languages: de 142, unknown 29, en 24, fr 7, it 2.
- Contract: permanent 147, unknown 45, internship 9, fixed_term 1,
  trainee_programme 1, temporary_assignment 1 — "unknown" is mostly Lever
  and Ashby, whose employment fields name a workload, not a contract
  (§9 question 5).
- Work model: onsite 123, unknown 52, hybrid 27, remote 2.
- Occupational strata actually present: SmartRecruiters function/industry ids
  113, Personio's own taxonomy 43, employer-typed department 32, Recruitee
  category_code 16 — i.e. only two of five providers state any occupation id.
- Municipalities: Zürich 183, Wallisellen 6, Winterthur 4, Dietikon 3,
  Dietlikon 3, Lindau 2, Kloten 2, Bassersdorf 1.
- Skipped by the Zurich filter: 49048 postings (36650 out of area, 12398
  needs geocode review) — proof the filter does real work on real volume.
- Exported with full provenance per row (provider, tenant, posting id,
  canonical URL, snapshot + hash); every row names its platform.

---

## 5. The ATS platform map

`data/ats_platform_map.yaml` (tracked) + `data/ats_platform_map_2026-10-18.md`
(readable), rebuilt after the last fetch:

- **11311 tenants across 10 platforms**, each row with tenant id, evidence
  grade (confirmed_live / dead / recorded / observed_in_crawl_index) and,
  where fetched, Zurich status.
- 900 confirmed live, 231 dead from the capped trial; the rest index-only.
- Per platform: ashby 3038, greenhouse 2923, personio 2467, join 963,
  **workday 746**, smartrecruiters 629, recruitee 452, lever 91, refline 2,
  teamtailor 0 (both floors — §8 truncation).
- Vault companies matched to platforms are graded `recorded`; the map absorbs
  and supersedes CAREER-52's `data/seeds/ats_overview_2026-10-17.md`.
- Workday answer for build-or-skip: 746 tenants is 6.6% of all discovered
  tenants and would make it the 5th-largest platform here — sizeable, but it
  needs its own adapter before any Zurich share of it can be measured.

---

## 6. The combined extrapolation the owner asked for

Per-provider Zurich rates from the capped samples, scaled to full discovery
(honest arithmetic: ZH-tenant rate times fetch-ok rate times discovered
total; postings likewise). Personio's row is CAREER-53's own extrapolation.

| Provider | Discovered | ZH tenants (sample) | ZH tenants (full-crawl est.) | ZH postings (full-crawl est.) |
|---|---|---|---|---|
| personio | 2467 | 9 of 270 | 49-150 | 142-720 |
| greenhouse | 2923 | 1 of 123 | ~19 | ~171 |
| lever | 91 (full) | 4 of 83 | 4 (measured, not sampled) | 12 (measured) |
| ashby | 3038 | 4 of 131 | ~81 | ~255 |
| recruitee | 452 | 5 of 143 | ~14 | ~51 |
| smartrecruiters | 629 | 10 of 150 | ~42 | ~473 |
| **Total (six platforms)** | | | **~210-310** | **~1060-1680** |

Read this before re-basing the spec brackets:

1. **Postings: the spec's [1500] is in reach** at full crawl across the six
   adapted platforms — the estimate straddles it (1060-1680). One giant
   SmartRecruiters tenant can move the number a lot in either direction; the
   wide personio band dominates the uncertainty.
2. **Tenants: the spec's [150] Zurich tenants is likely EXCEEDED** (~210-310),
   but "tenant with a Zurich posting" is a weaker bar than "Zurich company" —
   several are global employers with one Zurich office.
3. **The [25 of 35 occupation families] target cannot be estimated from this
   trial**: only two of five providers state occupation ids, and CAREER-57
   owns classification. Flagged, not guessed.
4. Uncounted platforms (join 963, workday 746 tenants) would add to all of
   this if adapted.
5. All rates come from one seed (54) and one crawl generation of the index;
   a full crawl re-measures everything for real. This table is the decision
   input for re-basing, not a promise.

---

## 7. Source checks (owner rule: documented API, robots.txt, terms)

Every adapter module carries its own source check in its docstring. This
is the whole of it in one table, all read 2026-10-17, plus the one
provider that needs an owner ruling.

| Provider | Documented endpoint | Says it needs no key? | robots.txt of the API host | Verdict |
|---|---|---|---|---|
| Greenhouse | <https://docs.greenhouse.io/job-board.html> (`developers.greenhouse.io/job-board.html` 301s to it) | Yes — "Job Board data is publicly available, so authentication is not required for any GET endpoints" | `boards-api.greenhouse.io`: `User-agent: *` / `Disallow: /embed/` | **Clear.** The path used is not `/embed/` |
| Lever | <https://github.com/lever/postings-api> (Lever's own repository for this API) | Yes, no key documented | `api.lever.co` and `api.eu.lever.co`: `Allow: /` with `Crawl-delay: 1` | **Clear**, and the crawl delay it asks for is exactly the shared limiter's one second |
| Ashby | <https://developers.ashbyhq.com/docs/public-job-posting-api> | Yes, no authentication documented | `api.ashbyhq.com` answers **401** for `/robots.txt` | **No rules published.** A 4xx robots.txt means no restriction (RFC 9309), which is how `polite_http.robots_allows` reads it. Weaker than Greenhouse's explicit allow, and recorded as such rather than as permission |
| Recruitee | <https://support.recruitee.com/en/articles/1066286-show-jobs-on-your-own-website> | Yes — "The public API doesn't require any authentication" | `{tenant}.recruitee.com`: `Disallow: /v/` | **Clear.** The article does not spell the `/api/offers/` path out, so the path itself was verified live rather than cited |
| SmartRecruiters | <https://developers.smartrecruiters.com/reference/v1listpostings.md> | Yes — "For public postings only, no authentication is needed", `limit` max 100 | **`User-agent: * / Disallow: /`, with `Allow: /v1/companies/` for `LinkedInBot` only** | **NEEDS AN OWNER RULING — question 1 below** |

### The SmartRecruiters robots question, in full

`api.smartrecruiters.com/robots.txt`, read 2026-10-17:

    User-agent: LinkedInBot
    Allow: /v1/companies/
    User-agent: *
    Disallow: /

So the host disallows every agent except LinkedIn's crawler from exactly
the path this adapter reads — the path SmartRecruiters' own developer
documentation publishes as public and unauthenticated.

**Why this is not the Common Crawl case.** The owner accepted, on
2026-10-17, the reading that "robots.txt governs crawlers walking pages,
not a service's own documented machine API" for `index.commoncrawl.org`,
whose robots.txt is a blanket `Disallow: /`. SmartRecruiters' is
different in one way that matters: it **names one aggregator and allows
it**, which makes the exclusion of everyone else look deliberate rather
than boilerplate.

**What was done about it.** Nothing silently.

* The runner REFUSES this provider unless it is given
  `--robots-exception smartrecruiters`. Without the flag it prints the
  robots lines and exits 2 without a single feed request, so no
  scheduled or unattended run can touch it by accident.
* The capped trial below WAS run with that flag, so the owner has
  numbers to rule on: 150 tenants, one request a second, our own
  identifying user agent, read-only, nothing republished.
* If the owner rules against it, the adapter and its fixtures stay and
  the provider is simply never fetched again. **The platform map keeps
  working either way**, because its SmartRecruiters tenants come from
  the crawl index and not from that host.

### Common Crawl

Unchanged from CAREER-53's report, which states the terms, the three
restrictions that matter, the `Disallow: /` and the reasoning applied to
it, and the fact that the owner should read the "artificial intelligence
… large language models" sentence themselves. Two things are new:

* **What this run reads out of the index is host names AND path
  segments** (`boards.greenhouse.io/<board>`), where the Personio run
  read host names only. Still no crawled page body, still no person.
* **The index truncates its biggest pages**, which is §8's correction.

### The vault

Opened read-only for discovery routes 1 and 2. The careers-page probe
fetched at most two pages per company (a homepage and one careers link),
honoured each site's `robots.txt` (3 of 43 companies refused us and were
counted as skipped), and went through the shared limiter and user agent.

---

## 8. Two defects this run found, one of them in CAREER-53's numbers

### The CDX API truncates its biggest pages, and our own body cap was
### making it look worse

The first discovery run reported four truncated index pages in a row for
`job-boards.greenhouse.io`, each cut after 2 300 to 11 900 of its lines.
Two separate causes, found in this order:

1. **Our own 2 MB cap.** `scripts/polite_http.request_text` inherits
   `org_intake.fetch.MAX_BODY_SIZE`, and `discovery` never passed
   anything else, so an index page bigger than 2 MB was cut by us and
   reported as the service's fault. CAREER-53's feed fetcher had already
   hit this and fixed it for feeds (`fetch.FEED_MAX_BODY`) but not for
   the index. `discovery.CDX_MAX_BODY` is now 64 MB.
   **This corrects CAREER-53's own report**, which recorded "one page
   came back cut after 943 of its lines" as a CDN fault. It was 943
   lines of a page our 2 MB ceiling cut.
2. **The service really does truncate too.** With the 64 MB cap the same
   pages still came back short, at varying lengths and with no error. So
   a truncated page is now **re-read block by block**: the same range
   as five pages of `pageSize=1`, which are a fifth of the size each and
   far more likely to arrive whole, and when one still truncates the
   loss is one block instead of five. `recovered_pages` in the discovery
   report says how many blocks were re-read, how many still truncated,
   and therefore whether a page is complete.

### A bare percentage in a long description is not a Pensum

The first live run of the Ashby adapter stored a workload of **30** for
an engineering management role, read out of "…grew 30%…" in a 20 000
character description. CAREER-53's Pensum reader was written for Swiss
postings, where the percentage IS the workload, and it looked at the
whole text.

The shared reader now takes a title match as it stands and requires a
Pensum word (`Pensum`, `Arbeitszeit`, `Beschäftigungsgrad`, `Teilzeit`,
`full-time`, `FTE`, …) within 60 characters of a match inside the TEXT.
Personio's own behaviour is unchanged — its test cases are a title
percentage and a "Pensum 80 – 100 %" line, both of which still match.

---

## 9. What needs an owner ruling

1. **SmartRecruiters and its robots.txt.** §7. The capped trial ran with
   the explicit exception so the numbers exist; whether this provider is
   fetched again is the owner's call. Everything else about it — the
   adapter, its fixtures, its place in the platform map — works either
   way.
2. **May a name-only Zurich match be sampled into the golden set?**
   CAREER-53 raised this (4.7% of its pool rows) and CAREER-54 splits it
   by provider, because the providers differ in what they can prove. A
   posting whose office carries a Swiss postal code, an ISO country code
   or the word "Switzerland" is `corroborated`. Greenhouse's location
   field is free text with no country block, so a Greenhouse posting
   that says only "Zurich" cannot be corroborated at all — and "Zurich"
   is also a town in Montana and in Kansas. Every pool row says which
   kind it is (`zurich_evidence`), so a ruling can be applied without
   re-fetching anything.
3. **Two contract readings, both flagged rather than settled.**
   Recruitee's `..._temporary` and SmartRecruiters' `temporary` are
   mapped to `fixed_term` rather than `temporary_assignment`, because
   both providers' own labels describe a fixed-length employment and
   contract.yaml's `temporary_assignment` is placement work. If the
   owner disagrees it is one line in each adapter's table.
4. **Recruitee states hours a week, not a Pensum.** `min_hours: 32` is
   76% against a Swiss 42-hour week and 80% against a Dutch 40-hour one,
   and the API states no basis, so nothing is converted and the raw
   hours are kept. Adopting a stated basis (and saying so in the value
   record's evidence) is an owner decision.
5. **"Full time" is not a contract type, so most Lever and Ashby
   postings have `contract: unknown`.** Their employment fields name a
   workload (`FullTime`, "Regular Full Time (Salary)") and this
   repository refuses to read `permanent` into that. The consequence is
   a golden-set pool where the contract dimension is mostly unknown for
   two providers. If the owner would rather infer "permanent unless the
   posting says otherwise", that is a rule the labelling guide can state
   and an adapter must not invent.
6. **Real posting text in the repository.** Carried over from CAREER-53
   and now true of five more fixture files: they contain real postings'
   descriptions, trimmed to one or two per provider. Blanking them is
   possible and costs the description tests their only real input.
7. **The Common Crawl terms' AI sentence.** Unchanged and still worth
   the owner's own eyes; see CAREER-53's report, §6.
8. **The vault has a company called "Greenhouse".** `CO-039` is named
   after the ATS vendor, carries `careers@proton.ch` as its contact and
   lists Zürich among its locations: an intake run resolved the hiring
   platform as the employer for a Proton posting. The vault was not
   written to, so it is still there. Worth a correction and worth asking
   whether intake should refuse to resolve a company to a known ATS
   vendor's name.
9. **Ashby returns postings the board does not list** (`isListed:
   false`). They are stored with the flag rather than dropped, and the
   pool currently includes them. Whether an unlisted posting belongs in
   a golden set is a labelling decision.
10. **Workday: build or skip.** §5 is the evidence. The map's own report
    ranks it.
11. **Should the full platform map be tracked?** `data/ats_platform_map.yaml`
    keeps every tenant with real evidence plus a sample of the
    index-only ones; the full list (every tenant a crawl index named) is
    staged and gitignored because it is megabytes and is rewritten on
    every run. If the owner wants the whole list in git, it is one line
    in `.gitignore`.

---

## 10. Files this run produced

**Tracked** (the three things meant to be read, plus the code and its
tests):

    data/ats/TRIAL_REPORT.md            this file
    data/ats_platform_map.yaml          the map, small: every tenant with
                                        real evidence plus a sample of the
                                        index-only ones
    data/ats_platform_map_2026-10-17.md the map's readable report
    careeros/feeds/base.py              the adapter contract
    careeros/feeds/registry.py          which adapters exist
    careeros/feeds/greenhouse.py        the five new adapters, one module
    careeros/feeds/lever.py             each, every one carrying its own
    careeros/feeds/ashby.py             endpoint, documentation URL,
    careeros/feeds/recruitee.py         access date and source check
    careeros/feeds/smartrecruiters.py
    careeros/feeds/platform_map.py      the map's logic
    scripts/run_ats_fetch.py            the runner for all six providers
    scripts/build_platform_map.py       the map's own command line
    tests/test_ats_adapters.py          the five adapters against recorded
                                        real feeds
    tests/test_ats_contract.py          the contract, the provenance
                                        refusal, the shared pipeline over
                                        every provider, the geocoder's
                                        country reading
    tests/test_ats_platform_map.py      the map and its confidence levels
    tests/test_ats_pool.py              the multi-provider pool and the
                                        runner's robots gate
    tests/fixtures/ats/                 eight recorded bodies and a README
                                        with the recording method and the
                                        terms observation

Refactored rather than added: `careeros/feeds/{personio,fetch,store,
discovery,export,geocode}.py`, `scripts/run_personio_fetch.py` (now the
generic runner with Personio's defaults), `careeros/feeds/__init__.py`,
`tests/test_personio_{store,runner}.py` (two call sites that pin private
helpers), `.gitignore` and `PROJECT.md`.

**Staged and gitignored** under `data/ats/`:

    <provider>/tenants.yaml             the discovered tenants, with the
                                        discovery report and the evidence
    <provider>/runs.yaml                one entry per fetch run
    <provider>/state/<tenant>.yaml       posting state and closure
    <provider>/snapshots/feeds/…         every raw response, gzipped
    <provider>/snapshots/postings/…      every posting, frozen by hash
    <provider>/cdx_2026-10-17.jsonl      the raw index lines, so every
                                        discovery replays with --from-file
    exports/golden_set_pool_2026-10-17.yaml  the multi-provider pool
    platform_map_full.yaml              every tenant the index named
    vault_probe_2026-10-17.yaml         the careers-page probe's findings
    *.log                               the console output of every run
    discover_all.sh, fetch_trial.sh,
    fetch_chain.sh, refetch_trial.sh    exactly what was run, so the trial
                                        is repeatable
    summarise_trial.py                  the arithmetic behind §2 to §4
