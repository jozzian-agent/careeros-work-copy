---
type: Routine
title: "Backfill empty descriptions on production's imported jobs"
description: "One-time fill: why 752 prod jobs have no posting text, how the text is re-resolved on the LAN, pushed as a generation and filled into the vault, and how to verify and roll back."
timestamp: 2026-11-05
---

# Backfill empty descriptions on production's imported jobs

Generation `2026-11-03` imported 752 jobs into the production vault with
EMPTY descriptions: it was exported before `descriptions.yaml` existed, so
there was no posting text to import (`deploy/import_prod_generation.sh`,
"DESCRIPTIONS, HONESTLY"). The text was never lost — it lives in the
frozen ATS snapshots on the LAN host, and every export since resolves it
into `descriptions.yaml`. CAREER-131 is the step that puts it on the jobs
that are still empty.

## What runs, and where

| Step | Where | What |
|---|---|---|
| 1. Export | LAN host | `scripts/export_jobs_for_prod.py` — resolves the posting text from the frozen snapshots into a generation's `descriptions.yaml` |
| 2. Upload | LAN → VPS | `deploy/push_to_prod.sh DATE` — the same push path, no changes |
| 3. Fill | VPS | `deploy/backfill_descriptions_prod.sh GEN` — runs `scripts/backfill_descriptions.py` against the prod vault |

Nothing new is uploaded except a normal export generation: the posting
text rides along in `descriptions.yaml`, covered by the MANIFEST sha256
like every other file. The VPS never resolves text itself — it has no ATS
snapshots and never will.

## What the fill writes

ONE field, `description`, and only on a job that:

* the generation's `pool.yaml` names (matched by the job's `source_id`,
  the pool `key` the importer stored verbatim), AND
* has an empty or whitespace-only stored description, AND
* has no owner.

It also stamps `field_provenance.description: feed` — the same word the
importer stamps, because the text is the feed's, not a person's reading.

It NEVER:

* overwrites a description that already has text (a second run fills
  nothing — it is idempotent);
* touches a record with an owner — a bulk backfill nobody has reviewed
  does not rewrite a person's job;
* writes any other field, a company rollup or a history event.

## The owner's commands, in order

### LAN host (export + upload)

The normal push-to-prod path — see
[push-to-prod.md](push-to-prod.md). Any export made after 2026-11-03
carries `descriptions.yaml`. If today's nightly already staged one, the
upload can reuse it; otherwise stage a fresh export first.

### VPS (fill)

```bash
# 1. dry run — needs no backup, writes nothing, prints the counts and a sample
sudo /srv/careeros/prod/app/current/deploy/backfill_descriptions_prod.sh \
    <generation> --dry-run

# 2. backup (the apply refuses without one younger than 60 minutes)
sudo tar -czf /srv/careeros/prod/backups/vault-$(date -u +%Y%m%dT%H%M%SZ).tar.gz \
    -C /srv/careeros/prod vault

# 3. apply
sudo /srv/careeros/prod/app/current/deploy/backfill_descriptions_prod.sh \
    <generation>
```

The wrapper is the import wrapper's guards, unchanged: COMPLETE marker,
prod-export manifest header, MANIFEST sha256 over every listed file, the
data lock, the fresh-backup gate, and the fill itself running as
`careeros-prod` via `runuser`. On top: the generation must CARRY
`descriptions.yaml` and the manifest must vouch for it — a generation
without text is refused, not silently "applied" as a no-op.

## Reading the report

```
matched (a job this generation's pool names):  NNN
  would fill (empty + text available):         NNN
  already had text (never overwritten):        NNN
  no source text (empty, none resolved):       NNN
  owned, skipped (a person's record):          NNN
```

* `matched` — stored jobs whose `source_id` is one of this generation's
  pool keys. Jobs from other generations are not matched at all.
* `would fill` / `filled` — empty description, text available.
* `already had text` — includes everything the fill already wrote on an
  earlier run, and any job the owner has since edited: it is never
  overwritten.
* `no source text` — matched and empty, but the generation resolved no
  text for that key (e.g. a greenhouse posting that publishes only a
  stub). Honest gap, counted not hidden.
* `owned, skipped` — matched a pool key but belongs to a user.

## Verify

Re-run the dry run. The report should show `would fill: 0` and every
matched job under `already had text`. Then load a job in the prod UI: the
posting text is there and its provenance reads feed.

## Rollback

Restore the backup the apply gate named:

```bash
sudo tar -xzf /srv/careeros/prod/backups/vault-<stamp>.tar.gz -C /srv/careeros/prod
```

The fill writes records one file at a time through the vault's atomic
writer, so a partial run is a vault where some descriptions are filled —
safe to leave, safe to re-run (idempotent). The backup exists for the
case where a fill wrote something it should not have.

## Tests

* `tests/test_backfill_descriptions.py` — the fill script itself: only
  empty, never overwrite, owned skipped, provenance, idempotence, counts.
* `tests/test_backfill_descriptions_prod.py` — the VPS wrapper: every
  guard, dry run writes nothing, apply fills, second apply no-op.
