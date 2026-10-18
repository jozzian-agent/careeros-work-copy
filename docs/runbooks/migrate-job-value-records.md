---
type: Routine
title: "Give a vault's jobs their coded value records"
description: "Back up a vault, run the CAREER-57 classification migration against it, verify it, roll it back, and know what the second step still owes."
timestamp: 2026-10-18
---

# Give a vault's jobs their coded value records

CAREER-57 replaces free-text classification on a job with D4 value
records: a code from a versioned taxonomy list, the source that put it
there, the phrase that decided it, and the taxonomy version it was
classified under. `scripts/migrate_job_value_records.py` writes them.

This is the owner's action. The commands below were proven against a
copy of the live vault on 2026-10-18;
`tests/test_migrate_job_value_records.py` runs the same code against
fixture vaults, and the quoted numbers are from the copy, so a later run
will differ.

## What it writes

- Job records only, one YAML file each. No company, experience or tags
  file is touched.
- Per job: **`values`** (field name → value record, built by
  `careeros.taxonomy.make_value_record`) and **`salary`** (the
  normalised pay block, or null). Both are fields no record carried
  before this ticket, so a first run overwrites nothing.
- Nothing else. In particular it does not touch `field_provenance`,
  stored history, or any free-text field.
- Nothing twice: the run is idempotent. A stored value is only replaced
  by a value from a strictly stronger source, and the rules layer is not
  stronger than itself, so a second run reports `nothing to change`.

## What it does NOT write, and why

### The free-text fields stay

`seniority`, `employment_type`, `location`, `salary_note` and the
free-text half of `requirement_groups` are left exactly as they are, and
every surface that reads them keeps working.

The value records are the replacement, but a field cannot be retired
before its readers move, and these are the readers:

| Field | Read by |
|---|---|
| `seniority` | `careeros.enrich` (`seniority_range` over the retired ordinal), `ingest.TEXT_FIELDS` / `STATUS_FIELDS` / the extraction prompt and its sanity check, `server` fillable list, `ExtractionPopup.jsx` |
| `employment_type` | `intake` (schema.org `employmentType`), `ingest` (prompt, TEXT_FIELDS, sanity check), `server` fillable list, `ExtractionPopup.jsx` |
| `location` | `enrich` (company location rollup), `intake` (schema.org `jobLocation`), `ingest`, `server` fillable list, `JobDetail.jsx`, `JobCard.jsx`, `EditJobPopup.jsx` |
| `salary_note` | `intake`, `watcher` (the `salary_found` change event), `server` fill list |

Moving all of those is a second ticket, not a line in this one. The
migration's own report prints how many records still carry each field,
which is how to judge whether that second ticket is worth scheduling.

### `field_provenance` keeps its shape

It is still validated as `dict[str, str]` and still means "who last
wrote this free-text field". A value record carries its own `source`,
`confidence`, `evidence` and `taxonomy_version`; putting one inside a
mapping of field name to a single word would mean changing that
validator and all ~40 of its readers to store something it was never
for. The two sit side by side: `field_provenance` describes the
free-text fields, `values` describes the coded ones.

### An owner edit is carried across, a machine's is not

A free-text field whose `field_provenance` says `user` becomes a value
record with the source `user`, which outranks every machine source
(admin > user > feed > rule > llm), so neither this run nor any later one
can overwrite a seniority the owner typed. A field a machine wrote is
**not** carried across: the pipeline re-reads the posting anyway, and
pinning an old model's answer in place as though a person had made it is
the one thing the precedence order exists to prevent.

## Before running

- The instance is on the commit that carries this chunk. An older
  `save_job` drops `values` and `salary` from every payload, so a
  migrated vault served by older code would silently lose them on the
  next write.
- Stop the server, or accept that a job edited mid-sweep is written
  twice. The sweep holds `vault.WriteLock`, so the two cannot interleave
  inside one record, but a sweep is not a transaction across records.
- Back the vault up. A copy of the directory is enough and is also the
  rollback:

```
cp -a /srv/career-os /srv/career-os.backup-$(date +%Y%m%d-%H%M%S)
```

## Dry run

```
python scripts/migrate_job_value_records.py --vault /srv/career-os
```

It prints one line per job, then the totals. Against a copy of the live
vault on 2026-10-18:

```
44 of 44 jobs gain value records
settled per field: occupation_family=25, isco_unit_group=18, language=36,
  workload_min=12, workload_max=12, contract=2, work_model=7, seniority=32,
  employer_type=34, municipality=31, canton=31
needs review: ambiguous=50, weak_evidence=27
salary blocks: 0
free-text fields still stored and still read by the app:
  employment_type=31, location=41, salary_note=4, seniority=18
DRY RUN: nothing was written. Re-run with --apply to write.
```

Read `needs review` as the queue, not as a failure. `ambiguous` is the
layer refusing to choose between two job families whose vocabularies
both fit; `weak_evidence` is a value found only in the description,
which is kept because it is usually right and flagged because when it is
wrong only a reader can see it.

## Apply

```
python scripts/migrate_job_value_records.py --vault /srv/career-os --apply
```

It prints the same report, writes, and then **re-plans the vault it just
wrote**. Anything still differing from the plan is an error and the
script exits non-zero. A record that could not be written is named on
stderr and also makes the run exit non-zero, so a half-finished sweep is
never reported as a success.

## Verify

```
python scripts/migrate_job_value_records.py --vault /srv/career-os
# -> "44 jobs: nothing to change, every job already carries its value records"
```

Then open one job in the app and check that nothing changed on screen:
no surface reads `values` yet, so a migrated job must look exactly as it
did. That is the point of the step being additive.

## Roll back

Put the backup back:

```
rm -rf /srv/career-os && mv /srv/career-os.backup-<stamp> /srv/career-os
```

There is no partial undo, and none is needed: the migration only adds
two fields, so an older build that ignores them behaves as it did
before.

## Re-classifying later

The migration is the rules layer. To add the local model's answers for
the fields the rules could not settle, run the pipeline instead and read
its output before writing anything:

```
python scripts/run_classification.py --vault /srv/career-os --layer all \
    --out data/classification/vault.yaml --dry-run
```

`--layer all` needs the Ollama host (`CLASSIFY_LLM_BASE_URL`,
`CLASSIFY_LLM_MODEL`); `--probe` makes one request first and prints its
latency and token count. **No live batch has been run against that host
yet**, so treat the first one as an experiment and keep `--dry-run` on
until its output reads right.
