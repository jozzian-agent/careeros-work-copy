---
type: Audit
title: "Empty description and summary in the live vault"
description: "Name every live job whose description or summary is empty, what the record says about why, and what a re-read could restore."
timestamp: 2026-10-16
---

# Empty description and summary in the live vault

Read-only audit of the owner's live vault (`careeros.server.DEFAULT_VAULT`),
run 2026-10-16 (CAREER-31). Nothing was written and nothing was fetched:
every line below comes from the
stored YAML records. The re-read itself is the owner's action, and the
commands for it are at the end.

The audit was commissioned as a redaction-residue audit, on the premise
that the empty fields are leftovers of the pre-`a8ed2ae` redaction defect
(which emptied any extracted string holding a provider name, a time like
`9:00` or a decimal like `10.5`; fixed 2026-10-11). That premise does not
survive the records. Read on for what they do say.

## The count

**44 job records** (the first pass of this audit said 42, which was two
records out of date: JOB-048 and JOB-049 were already in the vault, and
neither is affected). 6 have an empty `description`, 7 have an empty
`summary`, and the two sets overlap in 5, so **8 distinct records** are
affected. Every per-record finding below was re-checked against the 44 on
2026-10-16 and stands unchanged.

## The records

| Job | Title | Empty | Last watcher check | What the record says about why |
|---|---|---|---|---|
| JOB-003 | Senior Growth Marketing Manager (100%) | description, summary | `ok` 2026-10-02 | **Never read.** History holds `watch_started` and `status_changed` and no `enriched` or `llm_enriched` event at all; `refresh` is unset. Nothing was ever extracted, so nothing was lost. |
| JOB-004 | Head Product Management Funds | description, summary | `ok` 2026-10-06 | `enriched` 2026-10-02, no `llm_enriched`. The scrape pass ran and left no description. Cause not recorded. |
| JOB-005 | Ökosystem & Strategie Manager 80-100% | description, summary | `ok` 2026-10-08 | `enriched` 2026-10-02, no `llm_enriched`. Cause not recorded. |
| JOB-006 | Head of Product (m/f/x) | description, summary | `ok` 2026-10-07 | `enriched` 2026-10-02, no `llm_enriched`. Cause not recorded. Personio ATS posting (`bring-labs`, 2726475). |
| JOB-007 | Projektleiter*in Digitales Ökosystem | description, summary | **`gone`** 2026-10-07 | `enriched` 2026-10-02, no `llm_enriched`. Cause not recorded, and now moot: `posting_gone` 2026-10-07 after 3 consecutive errors. |
| JOB-020 | Careers and jobs (Syngenta) | summary | `ok` 2026-10-07 | **Thin fetch.** `llm_enriched` 2026-10-06, and the stored description is the 16 characters `BACK TO ALL JOBS` — page chrome. The title is "Careers and jobs": the URL is a careers landing page, not a posting. The reading had nothing to summarise. |
| JOB-021 | Principal Product Manager (Strategic Account Interactions) | summary | `ok` 2026-10-08 | **Thin fetch.** `llm_enriched` 2026-10-06, and the stored description is the posting's own title and nothing else (79 characters). A JS-rendered Elastic posting; the plain fetcher got the shell. |
| JOB-034 | Head of Product Orchestration | description | **`error`** 2026-10-16 | **Fetch failed, and the record says so.** `ingest_state: fetch_failed` with `ingest_error {stage: fetch, reason: HTTPError, at: 2026-10-13}`, two `description_refresh_failed` events, `refresh: failed`, LinkedIn URL (login wall). Its `summary` is non-empty and owner-provenanced. |

## What this says about redaction

**No record can be attributed to redaction, and two are definitely
something else.** The evidence, record by record:

- **JOB-003** was never read. **JOB-034** failed to fetch, on
  2026-10-13 — two days *after* the redaction fix — and carries the
  reason on the record. Neither is residue of anything.
- **JOB-020** and **JOB-021** were read on 2026-10-06, before the fix, so
  redaction could have emptied their summaries. It did not have to: their
  stored descriptions are 16 and 79 characters of chrome and title, so a
  reading of that text yields an empty summary either way. Nothing
  distinguishes the two explanations.
- **JOB-004, 005, 006, 007** were enriched on 2026-10-02, before the fix,
  by the scrape pass only (no `llm_enriched` event). Their descriptions
  are empty afterwards. That is consistent with the pre-fix redaction
  blanking a fetched description, and equally consistent with a fetch
  that returned nothing usable. These four records predate
  `field_status`, `field_status_reason` and `field_provenance` — all
  three are empty on them — so there is nothing stored that tells the two
  apart.

That indistinguishability is the actual finding, and it is a product
defect rather than a data defect: a field emptied by redaction looked
exactly like a field the posting never supported. **CAREER-30 closes it**
(2026-10-16): `careeros.ingest.redact` now logs every field it empties,
and when the emptied field is one `field_status` reports, the record
gains a `field_status_reason` saying the reading answered and the answer
could not be stored. A record emptied this way from now on says so.

## Is the source URL stored, and could it be refetched

Every one of the 8 stores both `url` and `normalized_url`; JOB-006 also
stores `original_url`. So a re-read has a target in all 8 cases. Whether
that target still answers, judged only from what the watcher already
recorded (no fetch was made for this audit):

- **5 refetchable as far as the record knows** — JOB-003, JOB-004,
  JOB-005, JOB-006, JOB-021: the watcher's last check was `ok`, on dates
  from 2026-10-02 to 2026-10-08. An `ok` check is the watcher having
  fetched that URL successfully, which is evidence of reachability at
  that moment and no promise about today.
- **JOB-020 refetchable, pointless** — `ok`, but the URL is a careers
  landing page. A re-read restores the same chrome.
- **JOB-007 gone** — `posting_gone` 2026-10-07, watch status `gone`
  after 3 consecutive errors. A re-read restores nothing.
- **JOB-034 not refetchable** — a LinkedIn posting URL behind a login
  wall; the last check errored and two description refreshes already
  failed against it.

## What a re-read would restore

Two paths exist and they are not interchangeable:

- `POST /api/jobs/<id>/re-extract` reads **the text the job already
  stores** and fetches nothing. For the 6 records with an empty
  `description` it therefore restores **nothing at all** — there is no
  text to re-read. For JOB-020 and JOB-021 it re-reads 16 and 79
  characters of chrome, which cannot produce a real summary either.
  **Re-extract is the wrong tool for every record in this audit.**
- `POST /api/jobs/<id>/extract` **fetches the posting again** (
  `original_url` if set, else `url`), replaces `description` with what
  comes back, and queues the reading that fills `summary`,
  `requirement_groups`, `skills` and the rest. This is the only path that
  can restore a description.

So, per record, what `/extract` could restore:

| Job | Re-read restores |
|---|---|
| JOB-003 | A full description and everything read from it — the posting was never read, so this is a first reading rather than a repair. |
| JOB-004, JOB-005, JOB-006 | A full description and the fields a reading fills. These are the three worth running. |
| JOB-021 | Likely the same shell again (JS-rendered page); a paste of the posting text is the surer route. |
| JOB-020 | Chrome again. Not worth running; the URL is not a posting. |
| JOB-007 | Nothing: the posting is gone. |
| JOB-034 | Nothing: the fetch already fails, twice recorded. Paste the posting text instead. |

Caveats the owner should know before running any of them:

- `/extract` **replaces** the stored description with whatever the fetch
  returns. On these records that is an empty field being overwritten, so
  there is nothing to lose — but it is a write, so back the vault up
  first.
- An owner-provenanced field is never overwritten by the reading
  (`field_provenance` = `user`), so JOB-034's own summary is safe. The
  four 2026-10-02 records carry no provenance at all, so nothing on them
  is protected that way.
- A job whose posting is gone or login-walled takes the **Paste posting
  text** route instead, which is an ordinary owner edit of
  `description`, after which `re-extract` reads it.

## Commands

The owner's action, not this audit's. Run from the repository root, in
the product virtual environment, against a running server on the live
vault. `VAULT` below is that vault's path and `BASE` the address of the
server already serving it, so this file names neither; the product's own
default is `careeros.server.DEFAULT_VAULT`, which `CAREEROS_VAULT` and
`--vault` override.

```bash
export VAULT=/path/to/the/vault
export BASE=http://localhost:PORT   # the running server's address

# 0. Back up the records this touches. Keep the copy outside the vault.
mkdir -p ~/vault-jobs.before-reread-2026-10-16
cp "$VAULT"/jobs/*.yaml ~/vault-jobs.before-reread-2026-10-16/

# 1. The three worth re-fetching, one at a time so a failure is readable.
curl -sS -X POST "$BASE"/api/jobs/JOB-004/extract
curl -sS -X POST "$BASE"/api/jobs/JOB-005/extract
curl -sS -X POST "$BASE"/api/jobs/JOB-006/extract

# 2. The never-read one: the same call, but it is a first reading.
curl -sS -X POST "$BASE"/api/jobs/JOB-003/extract

# 3. Optional, expected to return the page shell again.
curl -sS -X POST "$BASE"/api/jobs/JOB-021/extract

# 4. Check what each one restored (description length and the summary).
for id in JOB-003 JOB-004 JOB-005 JOB-006 JOB-021; do
  curl -sS "$BASE/api/jobs/$id" \
    | .venv/bin/python -c 'import json,sys; j=json.load(sys.stdin); print(j["id"], len(j["description"] or ""), repr((j["summary"] or "")[:60]), j["ingest_state"])'
done
```

Each `/extract` returns at once and does the fetch and the reading in the
background, so step 4 is worth repeating a minute later. `202` with
`llm_pending: true` means another reading already holds the slot for that
job; wait and repeat.

Not to be run: `JOB-007` (posting gone), `JOB-020` (not a posting),
`JOB-034` (fetch fails; paste the text instead).

## Open questions

- Whether the four 2026-10-02 records (JOB-004 to JOB-007) were emptied
  by the pre-fix redaction or by a fetch that returned nothing cannot be
  answered from the vault, and the only thing that would answer it — a
  log from 2026-10-02 — was never written. Running the re-read makes the
  question moot for the three that can be refetched.
- Whether JOB-020 and JOB-043 ("Job Offers", Finders) should stay job
  records at all. Both are careers landing pages rather than postings,
  which is a separate decision from this audit.
