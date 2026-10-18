# ATS platform map, 2026-10-18

Built by `scripts/run_ats_fetch.py map` at 2026-10-18T05:52:45+00:00 (CAREER-54, owner ruling 2026-10-17: "list which companies use which platform"). This supersedes and absorbs `data/seeds/ats_overview_2026-10-17.md` (CAREER-52), which probed 44 vault companies and could only answer which provider a careers page linked to; this map carries the tenant id, the evidence and whether the feed is live.

## What this says

- **11311 tenants** across **10 platforms**.
- 900 are **confirmed live** (a feed was fetched and parsed), 192 are **dead** (fetched, no feed), 10 are **recorded** by the vault and 10209 are **observed in a crawl index** only.
- 33 tenants have at least one posting in canton Zurich, holding 204 Zurich postings between them.

## Per platform

| Platform        | Tenants | Confirmed live | Dead | Recorded | Index only | Not fetched | Zurich tenants | Zurich postings | Adapter |
|-----------------|---------|----------------|------|----------|------------|-------------|----------------|-----------------|---------|
| ashby           | 3038    | 131            | 19   | 2        | 2886       | 2907        | 4              | 11              | yes     |
| greenhouse      | 2923    | 123            | 27   | 1        | 2772       | 2800        | 1              | 9               | yes     |
| personio        | 2467    | 270            | 131  | 1        | 2065       | 2197        | 9              | 43              | yes     |
| join            | 963     | 0              | 0    | 1        | 962        | 963         | 0              | 0               | no      |
| workday         | 746     | 0              | 0    | 3        | 743        | 746         | 0              | 0               | no      |
| smartrecruiters | 629     | 150            | 0    | 0        | 479        | 479         | 10             | 113             | yes     |
| recruitee       | 452     | 143            | 7    | 0        | 302        | 309         | 5              | 16              | yes     |
| lever           | 91      | 83             | 8    | 0        | 0          | 8           | 4              | 12              | yes     |
| refline         | 2       | 0              | 0    | 2        | 0          | 2           | 0              | 0               | no      |
| teamtailor      | 0       | 0              | 0    | 0        | 0          | 0           | 0              | 0               | no      |

## How each platform's tenants were found

| Platform        | Routes                          | Crawl indexes                           | Index pages read | Index pages available | Indexed URLs read | Pages lost |
|-----------------|---------------------------------|-----------------------------------------|------------------|-----------------------|-------------------|------------|
| ashby           | common_crawl, probe_file, vault | CC-MAIN-2026-39                         | 2                | 2                     | 21819             | 0          |
| greenhouse      | common_crawl, probe_file, vault | CC-MAIN-2026-39                         | 3                | 6                     | 51018             | 0          |
| personio        | common_crawl, vault             | data/personio/cdx_live_2026-10-17.jsonl | -                | -                     | 29833             | -          |
| join            | common_crawl, probe_file        | CC-MAIN-2026-39                         | 1                | 1                     | 6413              | 0          |
| workday         | common_crawl, probe_file        | CC-MAIN-2026-39                         | 2                | 5                     | 28152             | 0          |
| smartrecruiters | common_crawl, probe_file, vault | CC-MAIN-2026-39                         | 1                | 1                     | 3304              | 0          |
| recruitee       | common_crawl, probe_file, vault | CC-MAIN-2026-39                         | 1                | 1                     | 5294              | 0          |
| lever           | common_crawl, probe_file, vault | CC-MAIN-2026-39                         | 2                | 2                     | 826               | 0          |
| refline         | common_crawl, probe_file        | CC-MAIN-2026-39                         | 1                | 1                     | -                 | 1          |
| teamtailor      | common_crawl, probe_file        | CC-MAIN-2026-39                         | 2                | 2                     | -                 | 2          |

## Confidence levels

- **confirmed_live** -- the feed was fetched and parsed in a trial run
- **dead** -- the feed was fetched and the tenant does not serve one
- **recorded** -- the vault or a careers page names it; no feed was fetched
- **observed_in_crawl_index** -- a URL on this host appeared in a Common Crawl index

## Which platform is worth the next adapter

The owner's question, answered from the rows above rather than from impressions. Two orderings, because they are two different questions: how many companies are on a platform at all, and how many of them are hiring in Zurich. The second is what the pool needs and it can only be answered for a platform something has fetched.

| Rank | Platform        | Tenants found | Share of tenants found | Index pages read | Index blocks | Zurich tenants | Zurich postings | Adapter |
|------|-----------------|---------------|------------------------|------------------|--------------|----------------|-----------------|---------|
| 1    | ashby           | 3038          | 26.9%                  | 2 of 2           | -            | 4              | 11              | yes     |
| 2    | greenhouse      | 2923          | 25.8%                  | 3 of 6           | -            | 1              | 9               | yes     |
| 3    | personio        | 2467          | 21.8%                  | -                | -            | 9              | 43              | yes     |
| 4    | join            | 963           | 8.5%                   | 1 of 1           | 3            | not fetched    | -               | no      |
| 5    | workday         | 746           | 6.6%                   | 2 of 5           | 24           | not fetched    | -               | no      |
| 6    | smartrecruiters | 629           | 5.6%                   | 1 of 1           | 2            | 10             | 113             | yes     |
| 7    | recruitee       | 452           | 4.0%                   | 1 of 1           | 4            | 5              | 16              | yes     |
| 8    | lever           | 91            | 0.8%                   | 2 of 2           | -            | 4              | 12              | yes     |
| 9    | refline         | 2             | 0.0%                   | 1 of 1           | 3            | not fetched    | -               | no      |
| 10   | teamtailor      | 0             | 0.0%                   | 2 of 2           | 8            | not fetched    | -               | no      |

**Read "tenants found" as a lower bound, not a market share.** It is a count of the tenants a capped read of ONE crawl index happened to name, and the crawl indexes each provider's hosts to a wildly different depth: measured 2026-10-17, Greenhouse's two board hosts hold 29 index blocks and `jobs.lever.co` holds 1. The "Index blocks" column is the comparable number, because it does not depend on how much this run read -- but it is a fact about the crawl, which is itself a sample of the web.

**The platforms with no adapter**, which is what the "build or skip" decision is about:

- **join**: 963 tenants, 8.5% of everything this map knows, from 1 of 1 index pages. Nothing has been fetched from it, so its Zurich share is unmeasured: that is what an adapter would buy.
- **workday**: 746 tenants, 6.6% of everything this map knows, from 2 of 5 index pages. Nothing has been fetched from it, so its Zurich share is unmeasured: that is what an adapter would buy.
- **refline**: 2 tenants, 0.0% of everything this map knows, from 1 of 1 index pages. Nothing has been fetched from it, so its Zurich share is unmeasured: that is what an adapter would buy.
- **teamtailor**: 0 tenants, 0.0% of everything this map knows, from 2 of 2 index pages. Nothing has been fetched from it, so its Zurich share is unmeasured: that is what an adapter would buy.

## The Zurich tenants, by platform

| Platform        | Tenant                          | Company                            | Zurich postings | Municipalities | Evidence       |
|-----------------|---------------------------------|------------------------------------|-----------------|----------------|----------------|
| ashby           | proxima-fusion                  | -                                  | 7               | 261            | confirmed_live |
| ashby           | openai                          | -                                  | 2               | 261            | confirmed_live |
| ashby           | Snyk                            | Snyk                               | 1               | 261            | confirmed_live |
| ashby           | rohlik                          | -                                  | 1               | 261            | confirmed_live |
| greenhouse      | digitalassetcorp                | Digital Asset                      | 9               | 261            | confirmed_live |
| lever           | grape-health                    | -                                  | 4               | 261            | confirmed_live |
| lever           | lyrahealth                      | -                                  | 3               | 69             | confirmed_live |
| lever           | westernacher                    | -                                  | 3               | 261            | confirmed_live |
| lever           | optotune                        | -                                  | 2               | 243            | confirmed_live |
| personio        | isolutions                      | isolutions AG                      | 20              | 261            | confirmed_live |
| personio        | felfel                          | -                                  | 5               | 261            | confirmed_live |
| personio        | corealis                        | -                                  | 4               | 261            | confirmed_live |
| personio        | menhir-photonics                | Menhir Photonics AG                | 4               | 261            | confirmed_live |
| personio        | vicollective                    | ViCAFE                             | 4               | 261            | confirmed_live |
| personio        | konzmann-gmbh                   | DEKTRO Abel GmbH                   | 2               | 176            | confirmed_live |
| personio        | lalive-law                      | LALIVE SA                          | 2               | 261            | confirmed_live |
| personio        | avian                           | Innovire USA LLC                   | 1               | 261            | confirmed_live |
| personio        | pmone                           | pmOne GmbH                         | 1               | 230            | confirmed_live |
| recruitee       | kiesertrainingag                | Kieser                             | 5               | 261            | confirmed_live |
| recruitee       | exeon                           | Exeon Analytics                    | 4               | 261            | confirmed_live |
| recruitee       | cornerbancasa                   | Cornèr Banca SA                    | 3               | 69             | confirmed_live |
| recruitee       | medecinssansfrontieressuisse    | Médecins Sans Frontières Suisse    | 3               | 261            | confirmed_live |
| recruitee       | fachstellemobbingundbelastigung | Fachstelle Mobbing und Belästigung | 1               | 261            | confirmed_live |
| smartrecruiters | AFRY                            | AFRY                               | 35              | 230, 261       | confirmed_live |
| smartrecruiters | afry                            | AFRY                               | 35              | 230, 261       | confirmed_live |
| smartrecruiters | ATParchitekteningenieure        | ATP architekten ingenieure         | 23              | 261            | confirmed_live |
| smartrecruiters | securitas                       | Securitas                          | 7               | 261            | confirmed_live |
| smartrecruiters | HMGroup                         | H&M Group                          | 4               | 261            | confirmed_live |
| smartrecruiters | JYSK                            | JYSK                               | 4               | 230, 54        | confirmed_live |
| smartrecruiters | StepStoneGroup                  | StepStone Group                    | 2               | 62             | confirmed_live |
| smartrecruiters | RepRiskAG                       | RepRisk AG                         | 1               | 261            | confirmed_live |
| smartrecruiters | continental                     | Continental                        | 1               | 243            | confirmed_live |
| smartrecruiters | somfygroup                      | SOMFY Group                        | 1               | 52             | confirmed_live |

## What the vault already knew

No vault company resolved to a tenant in this run.

## Method and limits

- Tenants come from three routes: the vault (stored ATS identifiers, stored posting URLs, company websites), a probe of each vault company's own site (two page requests, robots.txt honoured), and the Common Crawl URL index. No search engine is scraped and no tenant id is guessed; see `careeros/feeds/discovery.py` for the rejected routes and the Common Crawl source check.
- A crawl-index sweep is a sample of a sample: the index is what one crawl saw, and a capped sweep reads some of its pages. The pages-read column above is what makes that visible.
- "Zurich" is a posting-level fact, so a tenant nobody fetched has no Zurich answer. That is the "Not fetched" column, kept apart from a tenant whose feed was read and has no Zurich office.
- A tenant id is not a company. `Company` is filled from the feed's own employer field or from a vault record and is left empty otherwise, never guessed from the slug.
- A company on two platforms keeps a row on each.

