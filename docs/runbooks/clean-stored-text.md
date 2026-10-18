---
type: Routine
title: "Take markup and internal codes out of a vault's stored text"
description: "Back up a vault, dry-run the stored-text cleanup against it, apply it, verify it and roll it back."
timestamp: 2026-10-18
---

# Take markup and internal codes out of a vault's stored text

The owner found three defects by reading their own board (brief
`docs/briefs/2026-10-18-jobs-page-fixes.md`, section 6). All three are
records written before the extraction pipeline learned to refuse this
text at the point it is stored, so fixing the pipeline leaves the stored
records as they are. `scripts/clean_stored_text.py` is the same rules
over what is already in a vault.

## What it fixes

1. **Markup in a stored field.** A posting states its own title in
   JSON-LD and some of them put HTML in it. JOB-047 in the owner's vault
   reads `Lead Business & Technology Engineering (w/m/d),<br/>80-100%
   Zürich / hybrid`. Entity escapes (`&amp;`) arrive the same way.
   Nothing in CareerOS renders a stored field as HTML, so markup in one
   is a defect the owner reads, not formatting.

2. **An internal code in a company name.** Thomson Reuters publishes
   `CHE003 Thomson Reuters Enterprise Centre GmbH` as the
   `hiringOrganization.name` of its Workday postings, where `CHE003` is
   their own Swiss site code, and the company record CareerOS created
   from that posting took the whole string as the name.

3. **A careers page's name taken as a job title.** JOB-043 is titled
   `Job Offers` and JOB-020 `Careers and jobs`. Those are pages, not
   roles. Such a job keeps a provisional title, because a job in the
   vault has to have one, and gains the record note that makes the board
   ask the owner for the real one.

## What it writes

On a job: the text and phrase-list fields, plus the provisional title and
the no-title note for case 3. On a company: the name, the sector, the
notes and the locations.

It never touches a field whose `field_provenance` says `user`, a company
whose `name_source` says `owner`, a note body, a URL, an id, provenance
or a value record. Text the owner typed is theirs, and a URL or a
provider id is data rather than prose.

## Before you run it

Take a backup. The script writes records in place.

```bash
tar czf ~/career-os-backup-$(date +%Y%m%d-%H%M%S).tgz -C ~ career-os
```

Check you are pointing at the vault you mean. The script refuses a path
that has no `jobs/` directory, and refuses to guess when neither
`--vault` nor `CAREEROS_VAULT` is set.

## Run it

Dry run first. It writes nothing and prints every record and field it
would change, by id and field name, never the text itself (a stored
description is a whole posting).

```bash
.venv/bin/python scripts/clean_stored_text.py --vault ~/career-os
```

Read the report. Then apply it.

```bash
.venv/bin/python scripts/clean_stored_text.py --vault ~/career-os --apply
```

An applied run re-plans afterwards and exits non-zero if anything it
planned is still there, so a silent partial sweep is not possible.

## Verify

```bash
.venv/bin/python scripts/clean_stored_text.py --vault ~/career-os
```

A second run reports `nothing to change`: plain text of plain text is the
same text, which is what makes the script idempotent. Then open the board
and check the three records the brief names:

- no title shows `<` or `&amp;`
- the Thomson Reuters company has no code in its name
- the two jobs that were titled after a careers page now show a
  provisional title and the "Needs your input" chip

## Roll back

Restore the backup. There is no reverse script: the original text is
exactly what the script removes, so a reverse would have to store it, and
a backup already does.

```bash
tar xzf ~/career-os-backup-<stamp>.tgz -C ~
```

## Open questions

None. The three cases are closed; a fourth kind of stored-text defect
would be a new rule in `careeros/ingest.py` and a new case here.
