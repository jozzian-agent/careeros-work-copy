---
type: Routine
title: "Import the ATS pool into a vault as universe jobs"
description: "Back up a vault, dry-run the pool import against it, run it, read the report and know what it costs."
timestamp: 2026-10-19
---

# Import the ATS pool into a vault as universe jobs

`scripts/import_pool_to_vault.py`. One owner-gated step that takes a
night's pool export plus its classification run and writes every posting
into a vault as a **universe job**: ownerless, `in_pipeline: false`, on
every user's All jobs tab and on nobody's board. CAREER-72/74; it closes
PROJECT.md's "a job the feed pool holds is in no vault, so it is on no
surface".

It is NOT part of the nightly pipeline and is not scheduled
([why](nightly-pipeline.md)): it holds the vault write lock for the
length of the run, and it is a decision the owner takes, not a fact that
accumulates every night.

## Before you run it

1. **Take a vault backup.** The script creates and never overwrites (see
   "What it never touches" below), but a bulk write of 700+ records into
   a single-file YAML vault is not something to do without one.
2. **Nobody is using the app.** The whole import runs inside one
   `vault.WriteLock`, so every request that writes a record waits for
   it. Run it in the nightly window.
3. **Have both files from the same day.** The pool export and the
   classification run are keyed on the same posting `key`; a mismatched
   pair silently imports jobs with no coded values rather than failing,
   because a missing classification row is a legal state.

## Running it

Rehearse first: `--dry-run` prints the full report and writes nothing.
VAULT below is the vault path, decided and passed explicitly — the
script never guesses one.

```sh
cd /root/work/careeros-dashboard
VAULT=/path/to/vault

# 1. back it up first
cp -a "$VAULT" "$VAULT.before-pool-import"

# 2. rehearse: prints the whole report, writes nothing
.venv/bin/python scripts/import_pool_to_vault.py \
    --pool data/ats/exports/golden_set_pool_2026-10-19.yaml \
    --classification data/classification/run_2026-10-19.yaml \
    --vault "$VAULT" --dry-run

# 3. the same command without --dry-run
```

Note the inverted default: unlike the `migrate_*.py` scripts in this
directory, which are a dry run until `--apply`, this one writes unless
asked not to. It is an import the owner runs on purpose after a backup,
not a one-shot that must never fire by accident.

`--stores DIR` points the description lookup at a different tree of
per-provider staging stores; the default is `data/ats/<provider>` plus
`data/personio`, which is where `scripts/run_ats_fetch.py` writes them.

## What it writes

**One job per posting**, carrying:

| Field | From |
| --- | --- |
| `title`, `url`, `source` (`provider:tenant`) | the pool row |
| `location` | the row's `municipality_label` |
| `posted_date` | the day out of the row's `published_at` (both shapes the six adapters state) |
| `salary_info` | the row's `has_salary` |
| `description` | the frozen posting snapshot the row names, by (tenant, posting id, content hash). No network call |
| `values`, `salary` | the classification run, validated by `vault.validate_value_records` / `validate_salary` |
| `source_id` | the pool `key`, which is the dedupe key below |
| `normalized_url`, `ats_provider`, `ats_tenant`, `ats_posting_id` | the row's own identity |
| `status: new`, `added: today`, `ingest_state: complete`, `origin: discovered` | fixed |
| `in_pipeline: false`, and no owner (`owner_id` null) | what makes it a universe job |

**Zero or one company per posting**, found or created in the shared
vault. The order, which is CAREER-74's with the one rung the pool cannot
reach left out:

1. exactly one stored company matches the employer name (case- and
   punctuation-insensitive, name variants included) → link it;
2. more than one does → **link none** and report it. The owner's
   2026-10-12 ruling is that duplicate exact names are a review, and
   there is nobody reviewing 704 rows;
3. a stored company holds this tenant's `ats_tenant` identifier → link
   it, so a company intake already placed under another spelling is not
   doubled. (A domain match, which is step 2 of the intake ladder, is
   impossible here: a pool row carries no website.)
4. otherwise create one: the name, `kind: employer`,
   `name_source: auto`, every municipality its postings name, one
   `ats_feed` source per TENANT (not per feed url — a paginated
   provider states a url per page of one board, and eight pages are not
   eight places to poll), and an `ats_tenant` identifier for each tenant
   that is not shared with another employer.

On the 2026-10-19 pool that is 146 company identities for 669 postings:
88 named by the feed, 57 named from a tenant slug, one inferred from its
tenant's other postings. 143 of them get an `ats_tenant` identifier; the
five tenants that state more than one employer name (`personio:collana`,
`demorecruiting`, `egruppe`, `kellerhals-carrard`, `vicollective`) get
none, because a tenant hosting two employers is not an identity.

The employer name itself has three sources, strongest first: the name
the feed states for this posting; the one name its tenant states for
every other posting in the pool; and the tenant slug, read the way
`careeros.intake` already reads one for a posting page that never named
its employer, except that a slug carrying its own capitals keeps them
(`AFRY`, not `Afry`). `name_source: auto` is the vault's own word for a
name nobody confirmed.

## What it never touches

* **No existing job.** A posting that duplicates a stored one is skipped
  whole; the stored record is not re-dated, re-linked or re-stamped (D4).
* **No existing company.** One it finds is linked and nothing is added to
  it, so an owner-curated name, sector, size or location cannot be
  overwritten by a bulk import nobody has reviewed. Only companies this
  run creates are written.
* **No company rollup.** `enrich.shared_jobs` reads boards and
  `vault.save_job` skips the regeneration for a record on no board, so
  these postings add not one derived fact to the companies they name.
  When somebody adds one to their board it becomes a board entry and
  rolls up like any other posting.
* **No `owner_id`, on anything.** No privacy rule moves
  ([schemas](../schemas.md)).

## Idempotence

Two dedupe keys, both read off what is already stored, so a second run
imports nothing:

1. the pool `key` stored as `source_id`;
2. the posting url, compared against both `url` and `normalized_url` of
   every stored job, in normalised form. This is the key that makes the
   owner's own jobs win: a posting one of them already holds is skipped
   rather than imported beside it.

Both indexes grow as the run writes, so two pool rows sharing one url
land once. The 2026-10-19 export has 35 of those — one posting read under
two spellings of its tenant (`smartrecruiters:AFRY` and
`smartrecruiters:afry`), same content hash, two keys.

## The report

Printed in both modes, before anything else. The 2026-10-19 pool into a
fixture vault holding one job that already had one of its urls:

```
pool postings:            704
imported:                 668
skipped-duplicate:        36  (source_id 0, url 36)
companies created:        145
companies linked:         0  (by name 0, by ats tenant 0)
companies ambiguous:      0  (name shared by more than one stored company; linked none)
descriptions resolved:    660/668 new  (8 imported with none; ...)
values attached:          668
invalid-values skipped:   0
salary attached:          2  (0 invalid, dropped)
jobs linked to a company: 668  (0 with none, employer name kept as free text)
```

36 skipped: the 35 postings the export itself holds twice, plus the one
the fixture vault's own job already had. `salary attached: 2` is not a
bug — the classification run normalised a figure for two of the 704,
because a Swiss posting usually states none.

A posting whose classification block does not validate is imported
**without** it, with a warning naming the posting and the reason, and
counted — never repaired and never silently kept. A posting whose
description cannot be resolved is imported with an empty one and counted;
dropping it would hide a job from the tab this import exists to fill.

A run that failed to import any posting exits non-zero and names each
one; every other posting still landed.

## What it costs, measured

Measured 2026-10-19 on this host (`ideaai`), importing the 704-posting
2026-10-19 pool into a fixture vault that started with 7 jobs and 4
companies:

| | |
| --- | --- |
| Wall clock | **2 856 s (47.6 min)** for 668 jobs, holding the vault write lock throughout |
| Written | 668 jobs, 145 companies |
| Vault afterwards | 675 jobs, 149 companies, 8.7 MB on disk |

The cost is the vault, not the import. It is quadratic: every record save
re-reads the whole `jobs/` directory to allocate an id
(`vault._highest_allocated`, which deliberately checks the id counter
against what is on disk), so the per-save cost grows with the number of
stored jobs — about 4 s per save at 350 jobs. Nothing here works around
that, because that scan is the belt to the id counter's braces and three
rounds of review put it there ([schemas](../schemas.md), "Record ids:
handed out once, never again").

**The same arithmetic then applies to the app**, and it is the thing to
know before clicking through a vault this size. Measured on the imported
fixture vault above (675 job files, 7 MB of YAML):

| Read | Time | Rows |
| --- | --- | --- |
| `vault.list_jobs` (My Jobs, admin) | 7.9 s | 7 |
| `vault.list_universe_jobs` (All jobs, admin) | 7.9 s | 675 |
| `jobs.page_context` (My Jobs payload) | 8.1 s | 7 |
| `jobs.universe_context` (All jobs payload) | 8.0 s | 675 |
| `companies.page_context` (directory) | 8.0 s | 149 |

Note the first row: **My Jobs takes 8 seconds to answer with 7 jobs**,
because `vault._jobs_newest_first` parses every stored job file before
anything is filtered. The board filter this import introduced decides
what is *returned*, not what is *read*, so it saves nothing here — an
index or a cache would, and neither exists. PROJECT.md has carried
"whether the single YAML vault holds up for five users — untested beyond
about 24 jobs" as an open risk since the Frame; these are the first
numbers that answer it. They are the owner's call to act on, not this
import's to fix.

## If something goes wrong

| Symptom | What it means | What to do |
| --- | --- | --- |
| `does not look like a CareerOS vault (missing jobs/)` | wrong `--vault` | check the path |
| `descriptions resolved` far below the pool's own `with_description` | `--stores` is pointing somewhere without the snapshots | run from the repository root, or pass `--stores` |
| `companies ambiguous` above zero | the vault holds two companies with one name | merge them by hand and re-run; the affected postings are imported with the employer name as free text and link nothing |
| `FAILED to import: N` | a posting the vault refused | the warnings name each one and the reason; the run exits 1 and everything else landed |
| The import is interrupted | partially imported | re-run it; the dedupe keys make it resume rather than duplicate |

Undoing an import is a restore from the backup. Nothing in the script
deletes, and there is no `--undo`: 668 records is not something to remove
one API call at a time.
