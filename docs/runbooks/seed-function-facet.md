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
copy of `sample/vault` on 2026-10-15 and the output quoted here is that
run, not an illustration.

## What it writes

- One file: `tags.yaml` at the root of the vault. No job, company or
  experience record is touched.
- 28 values in the `function` facet, which is every entry the import
  source carries today. One is ESCO-backed (`ict-product-manager`, the
  only entry whose `esco_uri` is filled in); the other 27 are seeded as
  local extensions with `isco` cleared, because an entry with no verified
  ESCO concept must not imply a roll-up it has not earned (decision 25).
  Confirming an entry means filling in its `esco_uri` in the import
  source and running the seed again.
- Nothing twice: the run is idempotent and never overwrites a value the
  owner has edited. A second run reports `[]`.

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
    added = vault.seed_function_facet(root)
print('added', len(added), 'ids')
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

Step 3 on an empty facet prints:

```
added 28 ids
```

Step 4 ends with:

```
function ids after: 28
```

Running step 3 again prints `added 0 ids`, which is how the run proves it
is idempotent rather than a second write.

## What the seed does not do

- It gives no existing job a function. A job gets one only from a reading
  of its posting: `POST /api/jobs/<id>/re-extract` reads the text the job
  already stores and fetches nothing, and `POST /api/jobs/<id>/extract`
  fetches the posting again. Deciding which jobs to re-read, and counting
  how many then carry a function, is the audit step (M0-5), not this
  runbook.
- It changes no prompt text. The option list the prompt carries is built
  from the facet at call time (`ingest._function_options_text`), so it
  fills in on its own once the facet has values.

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

- The `esco_uri` of every entry added in the 2026-10-15 round is unknown,
  so 27 of the 28 seeded values are local extensions. Whether the owner
  wants them verified against the live ESCO portal before the first
  classification measurement, or is content to run with the markers, is
  not decided.
- The ISCO codes in the import source are that file's best reading, not
  citations. They reach no vault while `esco_uri` is empty, so the
  question only matters when an entry is confirmed.
