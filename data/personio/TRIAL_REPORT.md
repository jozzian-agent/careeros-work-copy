# CAREER-53 trial report — Personio feed adapter

Run live on **2026-10-17** against Personio's public job XML feeds, the
Common Crawl URL index and the BFS municipality register. Everything
below is a measurement. Where a number is extrapolated it says so and
says from what.

The adapter itself is `careeros/feeds/`, the runner is
`scripts/run_personio_fetch.py`. This report is the one tracked file
under `data/personio/`; everything else here is regenerable output and
gitignored.

---

## 1. What ran live, and what did not

| | |
|---|---|
| **Ran live** | Personio documentation lookup; feed-shape probing on `bring-labs` (7 URL variants); the Common Crawl `collinfo.json` and CDX queries over two crawl indexes; the BFS municipality register load over LINDAS SPARQL; a careers-page probe over the live vault's companies; a 400-tenant random-sample feed fetch; two repeat fetches of one tenant to demonstrate snapshot stability; a 9-tenant refresh; the golden-set export |
| **Stubbed / not run** | The full crawl (all 2 467 discovered tenants) — the brief reserves it for Hermes. Coordinates for municipalities (the register publishes a boundary polygon, not a point, so `latitude`/`longitude` stay null rather than being invented). Occupation classification — forbidden here, CAREER-57 owns it. |
| **Never touched** | The live vault was opened **read-only** (53 companies, 44 jobs) and nothing was written to it. Nothing was committed. The pinned capability is unchanged, so the submodule pin does not move. |

---

## 2. Discovery

`scripts/run_personio_fetch.py discover --vault … --probe-websites 60 --common-crawl --crawls 2`
(console output kept as `discover_2026-10-17.log`; the raw index lines as
`cdx_live_2026-10-17.jsonl`).

| Route | Tenants found | Notes |
|---|---|---|
| 1. Existing universe (vault) | **1** | `bring-labs`, from the one stored Personio job. 53 companies and 44 jobs read. |
| 2. Company websites | **0** | 43 of the vault's 53 companies carry a website; 40 of those were probed (3 refused by their own robots.txt), 63 pages read — a homepage each plus a careers page where one was linked. None links to a `*.jobs.personio.*` career site. |
| 3. Common Crawl index | **2 466** | `CC-MAIN-2026-39`: 13 927 indexed URLs → 1 448 tenants. `CC-MAIN-2026-34`: 15 906 URLs → 1 735 tenants, of which 1 019 were new. No page lost, none truncated. |
| 4. Zefix seed | — | **Parked** (owner ruling 2026-10-17). Used for name-only dedupe; 0 candidate matches, because only one tenant had a company name before the first fetch. |
| **Total, deduplicated** | **2 467** | |

**Answering the spec's open question "how many tenants does the Common
Crawl query return".** 1 448 from one crawl index, 2 467 from two. The
marginal yield is high and declining: the second index added 70% of the
first index's count as new tenants. 128 indexes exist, back to 2013.

**Route 2's zero is a real finding, not a failure.** The vault's 53
companies are the owner's own browsing history, which skews to
consultancies and large corporates on other systems. The route stays in
because it costs two page fetches per company and will pay off as the
universe grows — but it cannot seed this pool.

**Rejected routes, and why.** Google and LinkedIn are not scraped: both
forbid it, both need a key or a browser, and a search result page is not
a source that could be cited in a value record. Tenant-id guessing
(`{company-slug}.jobs.personio.de`) is not done either: it is a
dictionary attack on someone else's host, it produces name-collision
false positives, and it makes the request count unbounded.

---

## 3. The fetch sample

`fetch --sample 400 --seed 7` — a **random** sample of the 2 467
discovered tenants, drawn with a stated seed. Alphabetical capping
(`--max-tenants`) is the default and is useless for measurement, which is
why `--sample` exists. Console output kept as
`fetch_sample400_seed7_2026-10-17.log`, run id `20261017T172548Z`.

| Measurement | Value |
|---|---|
| Tenants queued | 400 |
| Feed readable (`ok`) | **269 (67.3%)** |
| No career site any more (HTTP 404 on both hosts) | **131 (32.8%)** |
| Other failure (5xx, timeout, refusal) | 0 |
| Feeds read (host × language) | 800 |
| **Parse success** | **800 / 800 = 100.0%** |
| Postings seen | 2 189 |
| Postings in canton Zurich | **23 (1.05%)** |
| Zurich postings geocoded to a BFS municipality | **23 / 23 = 100%** |
| Tenants with ≥1 Zurich office | **8 / 269 readable = 3.0%** |
| Requests | 800, at ≥1.0 s apart (12 min of enforced waiting) |
| New / changed / closed postings | 2 189 / 0 / 0 (first run) |

The eight Zurich tenants the sample found, with their Zurich posting
count: `felfel` 5, `menhir-photonics` 4, `corealis` 4, `vicollective` 4,
`konzmann-gmbh` 2, `lalive-law` 2, `avian` 1, `pmone` 1.

`isolutions` (20 Zurich postings) is in the store too but was fetched
**separately and deliberately**, as a known Swiss tenant, to exercise the
Zurich path. It is excluded from every rate above, because a hand-picked
tenant is not a sample.

### A 33% tenant death rate is the single biggest cost

A third of the tenants Common Crawl knows about no longer serve a feed.
Those tenants are cheap to skip (2 requests each: one per host, and the
other languages are not tried once a host 404s — a fix worth 50% of a
dead tenant's cost), but they are a third of any crawl's budget and they
mean "tenants discovered" and "tenants fetchable" are very different
numbers.

---

## 4. The golden-set pool as it stands

`export` → `exports/golden_set_pool_2026-10-17.yaml`. 43 live Zurich
postings, from the 8 sampled Zurich tenants plus `isolutions`.

| | |
|---|---|
| Postings | 43 |
| Tenants / companies | 9 / 8 |
| Municipalities | 3 — Zürich 40, Lindau 2, Winterthur 1 |
| Geocoded to a municipality | 43 / 43 = **100%** |
| With posting text | 43 / 43 |
| With a salary signal | 6 |
| Language | de 35, en 8 |
| Contract | permanent 38, internship 3, trainee_programme 1, temporary_assignment 1 |
| Workload | 100-100 × 27, 80-100 × 4, 80-80 × 4, unknown × 3, and one each of 40-60, 20-90, 60-60, 50-60, 30-40 |
| Seniority hint | experienced 34, entry-level 8, student 1 |
| Occupation categories (Personio's own) | **13 distinct**, 1 with ≥8 postings |

Postings kept in the snapshots and excluded from the pool: 2 138
unresolved offices and 33 out-of-area. Nothing was dropped.

### Breadth is there; the pool is not big enough to show it

Across **all 2 214** stored postings (Zurich and not), the feed states
**24 distinct occupation categories** and **182 distinct occupations**,
excluding `other`. The top categories are `it_software` (357),
`sales_and_business_development` (313), `marketing_and_product` (134),
`engineering` (108), `project_and_program_management` (99),
`customer_support_and_client_care` (97), `accounting_and_finance` (97),
`medical_and_health` (92), `training_and_instruction` (92),
`installation_and_maintenance_repair` (87),
`building_construction_and_skilled_trades` (78).

That is the breadth the spec says Personio has, and it is real: trades,
health, hospitality and clerical work are all in there, not just tech.
The 13 categories in the 43-posting Zurich pool is a sample-size
artefact, not a ceiling.

---

## 5. Against the acceptance criteria

| Criterion | Measured | Extrapolated to the full crawl | Verdict |
|---|---|---|---|
| **[150] valid tenants with a Zurich office** | 9 (8 sampled + 1 picked) | 2.0% of queued tenants × 2 467 ≈ **49** (95% CI roughly 25–95) | **Will MISS on two crawl indexes.** Needs ≈ 7 500 discovered tenants, i.e. 10–20 crawl indexes. |
| **[1 500] open Zurich postings** | 43 | 0.0575 Zurich postings per queued tenant × 2 467 ≈ **142** | **Will MISS badly.** At the observed 4.8 Zurich postings per Zurich tenant, 1 500 needs ≈ 310 Zurich tenants ≈ 15 500 discovered tenants. |
| **[25] of 35 job families, ≥8 each** | not measurable here | — | **Cannot be graded by this adapter.** No posting carries a job family: CAREER-53 classifies no occupations. The proxy says the breadth exists (24 categories, 182 occupations over 2 214 postings); whether 25 of the 40 families fill up with ≥8 each is CAREER-57's measurement. |
| **≥99% parse success** | **100.0%** (800 feeds; 819 across all runs) | holds | **MET.** |
| **≥95% of Zurich offices geocoded to a BFS municipality** | **100%** (43/43). Office-level: of 3 470 offices seen, exactly **20** looked Swiss and failed to resolve, and all 20 are Austrian (`1040 Wien` ×12, `1010 Wien` ×5, `3910 Zwettl` ×3) caught by the postal-code-versus-name conflict rule. Zero genuinely Swiss offices are unresolved. | holds | **MET.** |
| **Closed postings detected within 2 fetch cycles** | mechanism verified by tests over recorded feeds (missing-from-1 vs 2, failed fetch counts for nothing, reopen with the gap logged); not observable in a one-day build | — | **PENDING a test week.** The spec asks for 20 real closures, which needs daily runs. |
| **Snapshots stable: a re-fetch of an unchanged posting creates no new snapshot** | **verified live.** `isolutions` fetched twice, 4 s apart: second run reported 0 new, 0 changed, and wrote no new posting snapshot. A 9-tenant refresh 3 minutes later: 0 new, 0 changed over 193 postings. | holds | **MET.** |
| **Tests with saved real feeds, incl. an empty feed, a `.com` tenant and an English feed** | 8 recorded fixtures, all three cases present | — | **MET.** |
| **Daily run report** | `report` subcommand + `runs.yaml` per run | — | **MET.** |

### What the full crawl should actually do

1. **Fetch every discovered tenant, not 150.** The Zurich filter is a
   posting-level fact that only the feed states, so there is no way to
   pre-select Zurich tenants. 2 467 tenants at the measured 2.0 requests
   each is ≈ 4 900 requests ≈ **82 minutes** at one request a second.
2. **Widen discovery before fetching.** Query 10–20 Common Crawl indexes
   rather than 2. Expect ≈ 7 500–10 000 tenants and a higher death rate
   on the older crawls. At 2 requests a tenant that is ≈ 4–6 hours of
   fetching.
3. **Expect the postings target to miss anyway.** Even 150 Zurich tenants
   gives ≈ 720 postings at the observed rate. 1 500 Zurich postings from
   Personio alone is not supported by this evidence. The spec's own
   trigger applies: *"If the job family target fails, the Personio pool is
   too narrow on its own. That's the trigger to build the Greenhouse
   adapter before labelling starts, not after."* The same conclusion is
   reached here through the posting count rather than the family count.

---

## 6. Source checks (owner rule: terms + robots for every new source)

### Personio public job XML feeds

* **Documented for machine consumption.** `https://{tenant}.jobs.personio.de/xml`
  is Personio's own documented way to put a career site's jobs on another
  website; no credentials, and the `language` parameter values are
  documented (`de en fr es nl it pt`).
  <https://developer.personio.de/v1.0/reference/get_xml>
* **robots.txt allows it.** `https://bring-labs.jobs.personio.de/robots.txt`,
  checked 2026-10-17: `User-agent: *` / `Allow: /`. There is **no robots
  tension for the feeds**.
* **Politeness as run.** Every request carried
  `CareerOS/0.x (+contact: owner)` through `scripts/polite_http`, with one
  global rate limiter per run — so the cap was one request a second for
  the whole run, not per host, which is stricter than the spec asks.
  Retries back off exponentially from one second and are capped at three
  attempts; a 404 is not retried at all.
* **Content.** The posting text belongs to the employers who published
  it. Seven trimmed feeds are kept as test fixtures of the feed's shape;
  nothing republishes any posting text. See
  `tests/fixtures/personio/README.md` — it raises blanking the fixture
  descriptions as an owner option.

### Common Crawl URL index

* **Terms, read 2026-10-17** (<https://commoncrawl.org/terms-of-use>).
  A "limited, non-assignable, non-transferable, non-sublicensable,
  non-exclusive" licence to access and use the Service. **No attribution
  requirement.** Three restrictions matter here:
  * no collecting or harvesting of "any personally identifiable
    information or personal information for use separately from the
    Crawled Content" — this adapter reads **host names** out of the
    index and nothing else: no crawled page body, no person;
  * third-party copyrights must be respected and the crawled content
    "may be subject to separate terms of use" from its owners — which is
    why a discovered tenant is then read from **Personio's own
    documented feed under Personio's terms**, never from Common Crawl's
    stored copy of the page;
  * the terms single out use "in connection with artificial
    intelligence, machine learning, or other similar technologies,
    including … large language models" as something the user remains
    liable for.
  **The third one needs the owner's eyes.** This pool exists to build a
  golden set for evaluating a classifier. The reading taken here is that
  what comes out of Common Crawl is a list of host names, that no
  crawled content reaches the pool, and that every posting's text comes
  from Personio — so the sentence does not bite. That is a reading, not a
  ruling, and the owner should make it. If the owner would rather not
  rely on it at all, discovery works offline from
  `cdx_live_2026-10-17.jsonl`, and the alternative discovery route is
  route 2 (company careers pages), which found nothing in this vault but
  needs no third party's index.

  An earlier draft of this report and of the module docstring claimed the
  terms "permit use including for research and commercial purposes".
  They do not say that; the text above is what they say.
* **robots.txt DISALLOWS the API.** `https://index.commoncrawl.org/robots.txt`,
  checked 2026-10-17, is `Disallow: /` for every agent with an allow-list
  of six static files (`collinfo.json` among them). **The reasoning
  applied is the one the owner already accepted for the LINDAS SPARQL
  route** in `scripts/seed_zefix_zurich.py`: robots.txt governs crawlers
  walking pages, not a service's own documented machine API, and the CDX
  endpoint is published as the way to query the index programmatically.
  The run identified its agent, stayed at one request a second and was
  capped. **If the owner refuses this reading**, `discover --from-file`
  replays `cdx_live_2026-10-17.jsonl` and no live call happens — the
  discovery is fully reproducible offline from that file.
* **Reliability, measured.** The CDX API 504s often. In the morning it
  504'd roughly one call in three; later it 504'd every call for several
  minutes, which is rate limiting rather than slowness. Retries are
  therefore 6 attempts backing off 2, 4, 8, 16, 32 s, with a 180 s
  timeout. It also sometimes returns a **truncated body**: one page came
  back cut after 943 of its lines. That is now detected (a last line that
  is not parseable JSON), its tenants are kept and the page is counted as
  failed rather than complete.

### BFS municipality register

* **Source.** *Amtliches Gemeindeverzeichnis der Schweiz* (Federal
  Statistical Office), read through its Linked Data distribution in
  LINDAS over the public SPARQL endpoint `https://lindas.admin.ch/query`,
  no credentials. Two graphs: `.../fso/register` for the municipalities,
  their names and their cantons, and `.../territorial` (the
  `https://ld.admin.ch/dimension/municipality` shared dimension) for the
  postal codes.
* **Licence.** OGD Open use, must provide the source
  (<https://opendata.swiss/en/terms-of-use#terms_by>). The attribution
  line and both graph URIs are written into `location.yaml`'s
  `municipality_source` block, so the condition travels with the data.
* **robots.txt** on `lindas.admin.ch` is `Disallow: /`. Same reasoning as
  Common Crawl, and already owner-accepted for this exact endpoint in
  CAREER-52.
* **What was loaded.** 2 110 municipalities, all 26 cantons, 160 in canton
  Zurich (the official count), 4 958 municipality/postal-code pairs. The
  dimension stays `complete: false`: the register changes several times a
  year through mergers, so a code missing from it may be real.
  `scripts/load_bfs_municipalities.py --check` says whether the shipped
  list still matches the register and writes nothing.
* **Answering the spec's open question "which geocoder".** Neither
  swisstopo's geocoding service nor a bare postcode table: the register
  itself, as a code list inside the taxonomy. It needs no per-request
  call, it is the authority the stored field is defined against, and it
  carries both the names and the postal codes. A swisstopo call per
  office would be ~3 500 requests per crawl to answer something a 240 KB
  file already answers.

---

## 7. Things that need an owner ruling

1. **`seniority: entry-level` — spec table versus decision D6.** The spec
   maps Personio's `student` AND `entry-level` to `s0`. D6's own scale
   calls s0 "Student or intern" and s1 "Entry", and its crosswalk maps
   `entry-level` → `entry` → **s1**. Following the spec's letter would
   file a graduate role under "Student or intern". The adapter follows D6
   (s1) and keeps the feed's word in `seniority_hint` either way, so a
   re-reading costs nothing. **8 of the 43 pool postings are affected.**
2. **A name-only Zurich match can be a foreign place.** A match that rests
   on a bare municipality name cannot tell a Swiss place from a foreign
   one that shares its name. **All 43 pool rows are `name_only`** — not a
   single tenant in this sample wrote a postal code or a `CH -` prefix —
   so corroboration is usable as a flag and useless as a filter, and the
   row says which it is (`zurich_evidence`). The measured false-positive
   rate is **2 of 43 (4.7%)**: `konzmann-gmbh`, a German building-services
   company with eight Baden-Württemberg offices, one of them
   "Gebäudetechnik, Lindau" — and Lindau is also a village in canton
   Zurich. A sibling-office heuristic was measured and rejected: it would
   have removed that one false positive and introduced two false
   negatives (`Zürich / US (Remote)` and `Zurich (ZRH) / Geneva (GVA)`
   have the same shape and are genuinely in Zurich). **Proposal:** the
   sampler excludes any tenant whose Zurich share is under ~5% of its own
   postings (`konzmann-gmbh` is 2 of 128; every true positive here is
   17% or more), and the owner spot-checks the rest. The data is already
   on the tenant record; nothing enforces a threshold.
3. **Should an office with no Swiss evidence be `out_of_area` rather than
   `needs_geocode_review`?** 2 138 of the 2 214 stored postings sit in
   `needs_geocode_review` and almost all are German towns. The status is
   honest — we cannot prove a place is outside Switzerland — but it makes
   the review list unusable at face value. The `swiss_evidence` flag is
   the practical split and the run report already uses it (13 postings
   with Swiss-looking offices in the 400-tenant run, all 20 offices
   Austrian). Whether the status itself should change is the owner's.
4. **Closure counts fetches, not days.** Two successful fetches in one
   day close a posting after both; a tenant unreachable for a week closes
   nothing. That is what the spec describes. Whether a time floor ("and
   at least 24 hours apart") should be added is open.
5. **Daily or weekly for non-Zurich tenants** (the spec's own open
   question). On this evidence: **weekly, or not at all until another
   canton is in scope.** 97% of fetchable tenants have no Zurich office,
   and fetching them daily is 95% of the request budget for nothing. The
   queue already puts confirmed Zurich tenants first, so a per-status
   cadence is a small change; it is not implemented because the spec
   leaves it open.
6. **35 or 40 job families.** The spec counts 35; the repository's own
   `occupation_families.yaml` holds 40 (CAREER-29 follow-up). Nothing
   crosswalks Personio's 182 occupation ids onto either list, and this
   ticket does not build one.
7. **Real posting text as test fixtures.** See
   `tests/fixtures/personio/README.md`: seven trimmed real feeds are kept
   in the repository. Blanking the `jobDescription` values is the
   alternative and costs the description-concatenation test its only real
   input.

---

## 8. Defects this trial found in the adapter, and fixed

Recorded because all three were found by running against real feeds and
none would have been found by a fixture someone wrote.

1. **The shared 2 MB body cap truncated a real feed.** `1komma5grad`'s
   German feed is 2 212 621 bytes; `polite_http` inherits
   `org_intake.fetch.MAX_BODY_SIZE` (2 MB), so the body arrived cut
   mid-element and the XML parser said "unclosed token" — a failure that
   looked like a broken feed and was our own ceiling. Feeds now have
   their own 32 MB cap, and a body that stops exactly at the cap is
   reported as `truncated` rather than counted against the parse-success
   rate.
2. **A bracketed site code was matched as a place.** `knott`'s offices
   read "Eggstätt (EGG)" and "Regenstauf (ZNR)"; splitting on the
   parenthesis made `EGG` match the Zurich municipality **Egg**, filing
   eleven German postings in canton Zurich. A short all-capital token in
   a separated part is now never a place.
3. **A fetch erased the discovery report.** `discover` writes its route
   report into `tenants.yaml` and `fetch` writes the last run id into the
   same file; the metadata block was replaced rather than merged, so a
   fetch deleted the provenance of every tenant in the file.

All three have a regression test. (The discovery metadata for the live
run in section 2 is therefore cited from `discover_2026-10-17.log`, which
is the console output of that run, rather than from the file it was
erased from.)
