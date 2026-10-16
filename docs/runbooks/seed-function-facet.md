---
type: Routine
title: "Seed the function facet in a vault"
description: "Run the one-time function-facet seed against a live vault and verify it."
timestamp: 2026-10-15
---

# Seed the function facet in a vault

A vault with an empty `function` facet in `tags.yaml` cannot store a
function on any job: every id an extraction returns is validated against
the facet and an unknown id is dropped (decision 23), so the field stays
empty whatever the model answers. `vault.seed_function_facet` fills the
facet from the curated import source
`careeros/data/esco_occupations.yaml`. It is explicit by design and never
runs on startup, so a vault stays empty until someone runs the sequence
below.

This is the owner's action. The commands were proven against a fixture
copy of `sample/vault` on 2026-10-15, and again on 2026-10-16 against a
throwaway copy of the live vault's own `tags.yaml` (a copy, so the live
vault was only read); the output quoted below is those runs, not an
illustration.

## What it writes

- One file: `tags.yaml` at the root of the vault. No job, company or
  experience record is touched.
- 40 values in the `function` facet, which is every entry the import
  source carries today. 10 are ESCO-backed: their `esco_uri` was fetched
  from the live ESCO API on 2026-10-16 and the concept's own label and
  `code` matched what the entry records, so those 10 keep their `isco`.
  The other 30 are seeded as local extensions with `isco` cleared,
  because an entry with no verified ESCO concept must not imply a roll-up
  it has not earned (decision 25). 5 of those 30 are marked `local: true`
  in the import source — owner labels whose golden-set URIs 404, so there
  is nothing to verify and they stay unmapped for good. The remaining 25
  are simply not verified yet; confirming one means filling in its
  `esco_uri` in the import source and running the seed again.
- **Re-running is not a no-op** (since 2026-10-16). It used to skip every
  id the facet already held, which made the sentence above false: a URI
  filled into the import source reached no vault, and nor did a new
  keyword, even though the extraction prompt is built from the vault's
  facet and not from the import source. A re-run now also:
  - confirms or updates `esco_uri`, `isco` and the local-extension
    marker on an entry already present, since those three are one
    statement about which ESCO concept the entry is, and the import
    source is where that statement is made;
  - merges in keywords, adding what the source has gained and removing
    nothing, so an anchor the owner added by hand survives. The flip
    side, stated plainly: a keyword **removed** from the import source
    stays in a vault that already stored it, and taking one out is a
    hand edit of `tags.yaml`.
  - It still never touches `label` or `label_de`, which are the owner's
    wording, and it never duplicates an id.
- Nothing twice: a run that finds nothing to add and nothing to update
  reports `added 0 / updated 0` and writes no file at all.

## Before running

- The repository is at the commit whose `careeros/data/esco_occupations.yaml`
  you intend to seed. Read the file first: every entry reaches the
  extraction prompt, so an id the owner does not search in is better
  removed than left to bias the model.
- Decide the vault path. `VAULT` below is that path. The product has a
  default (`careeros.server.DEFAULT_VAULT`, which is also what
  `CAREEROS_VAULT` overrides), but pass the path explicitly here rather
  than relying on either, so a run can never land on a vault nobody
  named.
- The server may keep running. The seed takes the same cross-process
  write lock (`vault.WriteLock`) the server takes, and `load_tags` reads
  `tags.yaml` from disk on every request, so no restart is needed and no
  request can interleave with the write.

## The sequence

Run from the repository root, in the product virtual environment.

```bash
export VAULT=/path/to/the/vault

# 1. Back up the one file this writes. Keep the copy outside the vault,
#    so a stray file never sits beside the records.
test -f "$VAULT/tags.yaml" && cp -n "$VAULT/tags.yaml" ~/tags.yaml.before-function-seed

# 2. Look before writing: how many function ids the vault knows today.
.venv/bin/python - <<'PY'
import os
from careeros import vault
print('function ids before:', len(vault.known_function_ids(os.environ['VAULT'])))
PY

# 3. Seed, under the vault's own write lock.
.venv/bin/python - <<'PY'
import os
from careeros import vault
root = os.environ['VAULT']
with vault.WriteLock(root):
    result = vault.seed_function_facet(root)
print('added', len(result.added), 'ids:', result.added)
print('updated', len(result.updated), 'ids:', result.updated)
PY

# 4. Verify: every seeded id is a known id, and each one says whether it
#    is ESCO-backed or a local extension.
.venv/bin/python - <<'PY'
import os
from careeros import vault
root = os.environ['VAULT']
for value in vault.function_facet_options(root):
    kind = 'local extension' if value.get('source') == 'local-extension' else 'ESCO-backed'
    print(' ', value['id'], '|', value['label'], '|', kind)
print('function ids after:', len(vault.known_function_ids(root)))
PY
```

Step 3 on an empty facet adds all 40 and updates nothing. On the live
vault, which was seeded with the 28 entries of 2026-10-15, it prints the
following — the output of a run against a copy of the live `tags.yaml`
on 2026-10-16, not an illustration:

```
added 12 ids: ['embedded-systems-security-engineer', 'ict-business-analysis-manager',
 'ict-consultant', 'product-manager', 'chief-product-officer', 'digital-marketing-manager',
 'banking-products-manager', 'business-consultant', 'business-development-manager',
 'innovation-manager', 'innovation-officer', 'digital-transformation-manager']
updated 7 ids: ['ict-product-manager', 'software-developer', 'ict-security-manager',
 'ict-project-manager', 'marketing-manager', 'sales-manager', 'compliance-officer']
```

The 7 updates are what the old skip-everything behaviour would have
dropped on the floor: 5 entries gaining the ESCO URI and code verified on
2026-10-16 (`software-developer`, `ict-project-manager`,
`marketing-manager`, `sales-manager`, and `ict-product-manager`, whose
code is confirmed rather than new), and the keyword additions on
`ict-security-manager` and `compliance-officer` that the extraction
prompt could not otherwise see.

Step 4 ends with:

```
function ids after: 40
```

Running step 3 again prints `added 0` and `updated 0`, which is how the
run proves it is idempotent rather than a second write.

## What the seed does not do

- It gives no existing job a function. A job gets one only from a reading
  of its posting: `POST /api/jobs/<id>/re-extract` reads the text the job
  already stores and fetches nothing, and `POST /api/jobs/<id>/extract`
  fetches the posting again. Deciding which jobs to re-read, and counting
  how many then carry a function, is the audit step (M0-5), not this
  runbook.
- It changes no prompt text. The option list the prompt carries is built
  from **the vault's own facet** at call time
  (`vault.function_facet_options`, rendered by
  `ingest._function_options_text`), so it fills in on its own once the
  facet has values — and, equally, an entry or keyword that reaches no
  vault reaches no reading. That is why the re-run above matters.

## If it goes wrong

Restore the backup and the facet is exactly as it was:

```bash
cp ~/tags.yaml.before-function-seed "$VAULT/tags.yaml"
```

A vault that had no `tags.yaml` before the seed is restored by deleting
the file the seed created, since the code falls back to the built-in
default facets when the file is absent:

```bash
rm "$VAULT/tags.yaml"
```

## Open questions

- 25 of the 40 entries are still unverified: no `esco_uri`, and an
  `isco` that is the import source's best reading rather than a
  citation. The 2026-10-16 round verified the 10 concepts the golden set
  needed, which is every function label the owner's own 42 labelled
  postings use, and left the rest for the day a posting needs one.
  Whether the owner wants all 25 verified against the live ESCO API
  before the first classification measurement, or is content to run with
  the local-extension markers, is not decided. They reach no vault with
  a code while `esco_uri` is empty, so nothing claims a roll-up it has
  not earned in the meantime.
- The 5 entries marked `local: true` are a different case and not an
  open question: their URIs were checked and 404, so there is nothing to
  verify and decision 25 keeps them as owner labels with a marker.
