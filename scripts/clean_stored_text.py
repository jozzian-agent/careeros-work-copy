"""One-off cleanup: take markup and internal codes out of stored text.

Brief 2026-10-18, section 6. Three defects the owner found by reading
their own board, all of them records written before the pipeline learned
to refuse this text at the storage boundary:

  1. **Markup in a stored field.** A posting states its own `title` in
     JSON-LD and some of them put HTML in it: JOB-047 reads "Lead
     Business & Technology Engineering (w/m/d),<br/>80-100% Zürich /
     hybrid". Entity escapes ("&amp;") arrive the same way. Nothing
     renders a stored field as HTML, so markup in one is not formatting.
     Fixed at the boundary by `careeros.ingest.clean_extracted`; this is
     the same rule over what is already stored.

  2. **An internal code in a company name.** Thomson Reuters publishes
     "CHE003 Thomson Reuters Enterprise Centre GmbH" as the
     `hiringOrganization.name` of its Workday postings, where CHE003 is
     their own Swiss site code, and the company record CareerOS created
     from that posting took the whole string as the name. Fixed at the
     boundary by `careeros.ingest.company_name_text`.

  3. **A careers page's name taken as a job title.** JOB-043 is titled
     "Job Offers" and JOB-020 "Careers and jobs". Those are pages, not
     roles (`careeros.ingest.GENERIC_HEADINGS`). The job keeps a
     provisional title, because the vault requires a job to have one,
     and gains the `field_status_reason` for `title` that makes the board
     ask the owner for the real one (careeros/web/pages/jobs.py
     `needs_attention`).

## What it writes, and what it deliberately does not

WRITES, on jobs: `title`, `company`, `location`, `salary_note`,
`seniority`, `employment_type`, `summary`, `background`, `description`,
`employer_named_in_posting`, and the list fields that hold extracted
phrases, whenever plain text differs from what is stored. Plus, for a
generic heading, the provisional `title`, `field_status['title']` and
`field_status_reason['title']`.

WRITES, on companies: `name` (plain text, and without a leading site
code), `locations`, `notes` and `sector`.

DOES NOT WRITE a field whose `field_provenance` says `user`: text the
owner typed is theirs, and this script never edits it (global rule 1).

DOES NOT touch note bodies, history, provenance, values, ids, urls or
anything that is not prose a person reads. A URL, a provider id and a
raw vocabulary word are data, and plain text is not an improvement to
them.

Safety rails, the same ones scripts/migrate_record_owner.py follows:
  * dry run by default; nothing is written without `--apply`, and the
    full report is printed first in both modes
  * the vault path comes from `--vault` or `CAREEROS_VAULT`; neither
    means stop, not guess
  * the whole sweep holds `vault.WriteLock`
  * writes go through the vault's own atomic writer, one file at a time,
    so no company rollup and no status history event fires
  * one record's failure is reported and skipped, and a sweep that
    skipped anything exits non-zero
  * idempotent: plain text of plain text is the same text, so a second
    run reports nothing to change, and the run checks that itself
  * the report names records by id and names the field that changes,
    never the text, which can be a whole posting

Take a vault backup first. See docs/runbooks/clean-stored-text.md.

Usage:
  python scripts/clean_stored_text.py --vault /path/to/vault
  python scripts/clean_stored_text.py --vault /path/to/vault --apply
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careeros import ingest, vault  # noqa: E402

#: Job fields that hold prose or a phrase a person reads. `description`
#: is in here: it is the posting's own text and the one field markup
#: reached most often.
JOB_TEXT_FIELDS = ('title', 'company', 'location', 'salary_note', 'seniority',
                   'employment_type', 'summary', 'background',
                   'employer_named_in_posting', 'description')

#: Job fields holding a list of extracted phrases.
JOB_LIST_FIELDS = ('keywords', 'skills', 'certifications', 'responsibilities',
                   'requirements', 'nice_to_have', 'tags')

#: Company fields that hold prose. `name` is handled on its own, because
#: it is the one field that also loses a leading site code.
COMPANY_TEXT_FIELDS = ('sector', 'notes')
COMPANY_LIST_FIELDS = ('locations',)


def records(root, kind):
    """Every stored record of one kind with the file it lives in, through
    the vault's own tolerant reader. A directory that is not there yields
    nothing."""
    for path in sorted((Path(root) / kind).glob('*.yaml')):
        data = vault._read(path)
        if data and vault.is_reserved(data):
            # An id-reservation tombstone holds a number, not a record.
            continue
        if data:
            yield path, data
        else:
            print(f'  {path.name}: unreadable or empty, skipped', file=sys.stderr)


def _clean_text(value):
    return ingest.plain_text(value) if isinstance(value, str) else value


def _clean_list(value):
    if not isinstance(value, list):
        return value
    return [_clean_text(item) for item in value]


def _owner_set(data, field):
    return (data.get('field_provenance') or {}).get(field) == 'user'


def provisional_title(data):
    """The title a job keeps when the posting named no role.

    The same words `careeros.intake._extract` uses, so a record cleaned
    here and a record read today are indistinguishable.
    """
    company = _clean_text(data.get('company') or '') or ''
    return (company.strip() or 'Job') + ' opportunity'


def job_updates(data):
    """What this script would change on one job, field by field."""
    updates = {}
    for field in JOB_TEXT_FIELDS:
        if _owner_set(data, field):
            continue
        cleaned = _clean_text(data.get(field))
        if isinstance(cleaned, str) and cleaned != data.get(field):
            updates[field] = cleaned
    for field in JOB_LIST_FIELDS:
        cleaned = _clean_list(data.get(field))
        if isinstance(cleaned, list) and cleaned != data.get(field):
            updates[field] = cleaned

    # An employer name never carries a site code, wherever it is stored.
    for field in ('company', 'employer_named_in_posting'):
        if _owner_set(data, field):
            continue
        current = updates.get(field, data.get(field))
        if isinstance(current, str) and current:
            without_code = ingest.company_name_text(current)
            if without_code != data.get(field):
                updates[field] = without_code

    # A careers page's name is no title. Checked against the cleaned
    # title, so "Job&nbsp;Offers" counts as one as well.
    title = updates.get('title', data.get('title'))
    if not _owner_set(data, 'title') and ingest.is_generic_heading(title):
        updates['title'] = provisional_title({**data, **updates})
        updates['field_status'] = {**(data.get('field_status') or {}), 'title': 'not_evidenced'}
        updates['field_status_reason'] = {**(data.get('field_status_reason') or {}),
                                          'title': ingest.NO_TITLE_REASON}
    return updates


def company_updates(data):
    """What this script would change on one company, field by field."""
    updates = {}
    # A name the owner set themselves is theirs; `name_source` is the
    # company record's own word for that (vault._save_record).
    if data.get('name_source') != 'owner':
        name = ingest.company_name_text(data.get('name') or '')
        if name and name != data.get('name'):
            updates['name'] = name
    for field in COMPANY_TEXT_FIELDS:
        cleaned = _clean_text(data.get(field))
        if isinstance(cleaned, str) and cleaned != data.get(field):
            updates[field] = cleaned
    for field in COMPANY_LIST_FIELDS:
        cleaned = _clean_list(data.get(field))
        if isinstance(cleaned, list) and cleaned != data.get(field):
            updates[field] = cleaned
    return updates


PLANNERS = {'jobs': job_updates, 'companies': company_updates}


def plan(root):
    """What this cleanup would write, one row per record that changes."""
    rows = []
    for kind, planner in PLANNERS.items():
        for path, data in records(root, kind):
            updates = planner(data)
            if updates:
                rows.append({'id': data.get('id'), 'kind': kind, 'path': path,
                             'updates': updates})
    return rows


def write(rows):
    """Write every planned change, one record at a time, to the exact
    file the row was planned from."""
    written = []
    for row in rows:
        try:
            data = vault._read(row['path'])
            data.update(row['updates'])
            vault._write(row['path'], data)
        except Exception as error:
            print(f"  skipped {row['id']} ({type(error).__name__}: {error})", file=sys.stderr)
            continue
        written.append(row['id'])
    return written


def report(root, counts, rows, apply_changes):
    """Print the whole plan, in both modes, before anything is written.

    Field names only. A stored description is a whole posting, and a
    report that quoted one would be unreadable and would put posting
    text in a terminal scrollback for no gain.
    """
    print(f"vault={root}  mode={'APPLY' if apply_changes else 'DRY RUN'}")
    print('-' * 78)
    total = sum(counts.values())
    if not rows:
        print(f'{total} record(s): nothing to change, every stored field is already '
              'plain text with no internal code and no page heading for a title')
        return
    for row in rows:
        fields = ', '.join(sorted(row['updates']))
        print(f"  {row['id']}: {fields}")
    print('-' * 78)
    for kind in PLANNERS:
        changing = sum(row['kind'] == kind for row in rows)
        print(f'{kind}: {changing} of {counts[kind]} change')
    retitled = sum('field_status_reason' in row['updates'] for row in rows)
    if retitled:
        print(f'{retitled} job(s) had a careers page for a title and now ask the owner for one')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', help='vault path (default: the CAREEROS_VAULT variable)')
    parser.add_argument('--apply', action='store_true',
                        help='actually write (default: dry run, writes nothing)')
    args = parser.parse_args(argv)

    given = args.vault or os.environ.get('CAREEROS_VAULT')
    if not given:
        raise SystemExit('no vault given: pass --vault PATH or set CAREEROS_VAULT')
    root = Path(given)
    if not (root / 'jobs').is_dir():
        raise SystemExit(f'{root} does not look like a CareerOS vault (missing jobs/)')

    with vault.WriteLock(root):
        counts = {kind: sum(1 for _ in records(root, kind)) for kind in PLANNERS}
        rows = plan(root)
        report(root, counts, rows, args.apply)
        if not rows:
            return 0
        if not args.apply:
            print('DRY RUN: nothing was written. Re-run with --apply to write.')
            return 0
        written = write(rows)
        print(f'wrote {len(written)} record(s)')
        left = plan(root)
        if left:
            raise SystemExit(f'{len(left)} record(s) still hold text this would change: '
                             'check the vault by hand')
        if len(written) < len(rows):
            raise SystemExit(f"{len(rows) - len(written)} of {len(rows)} planned write(s) "
                             'were skipped (see the errors above)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
