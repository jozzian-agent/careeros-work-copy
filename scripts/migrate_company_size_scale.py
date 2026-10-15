"""One-shot migration: leave every company on ONE size scale, the classes.

Owner decision 2026-10-15: a company's size is its class (micro, small,
medium, large -- `vault.SIZE_CLASSES`), never the numeric `size_range` the
intake cascade also derives. Two coexisting scales made the Companies
directory show "1000+" for one company and "Large" for the next. This
script normalizes what is already stored:

  * a company with a `size_range` AND a `size_class` keeps the class, and
    the range is cleared -- the class wins
  * a company with a `size_range` and NO `size_class` gets the class its
    range implies (see SIZE_CLASS_BY_HEADCOUNT), and the range is cleared
  * a company whose `size_range` is not one of the vault's own bucket
    labels is reported and left exactly as it is: there is nothing to
    derive a class from, and clearing the range would drop the only size
    the record has
  * a company with no `size_range` is already on the class scale

Safety rails:
  * dry run by default: nothing is written unless `--apply` is passed
  * `--vault PATH` is required, so a run can never default onto the live
    vault by accident
  * writes go through `vault.save_company`, so validation and the
    filename rule run -- never raw YAML edits
  * one record's failure is reported and skipped, never fatal for the rest
  * idempotent: a second run finds nothing left to change
  * the report names records by id, never by company name, so it can be
    pasted into a build note or a PR without leaking the vault

`field_provenance` follows the value: a `size_range` key is dropped when
the range is cleared (a provenance entry for a now-empty field would
report the class as owner-set on the detail page and freeze the size pair
against future enrichment), and in the derive-class branch it moves onto
`size_class`, which is where the size the owner or the signal supplied
now lives. Nothing else about provenance changes.

An apply writes through `vault.save_company`, which rebuilds the record
from the full schema, so an older record's YAML diff can be slightly
wider than the reported change: it also gains any schema key it is
missing (`note_list: []`, `field_provenance: {}`).

Usage:
  python scripts/migrate_company_size_scale.py --vault /path/to/vault
  python scripts/migrate_company_size_scale.py --vault /path/to/vault --apply
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from careeros import vault  # noqa: E402

# The owner's conservative map from a range's headcount to a class: up to
# 50 people is small, up to 250 is medium, anything above is large. The
# class vocabulary also has `micro`, which this map deliberately never
# produces -- a stored range is a bucket, and guessing the smallest class
# from a bucket's edge would claim more precision than the range has.
SIZE_CLASS_BY_HEADCOUNT = ((50, 'small'), (250, 'medium'))

CLEAR_RANGE = 'clear-range'
DERIVE_CLASS = 'derive-class'
UNREADABLE = 'unreadable-range'


# The grammar of the vault's own range labels, and the ONLY shape this
# script reads a headcount out of (mirrors
# `org_intake.classify._SIZE_RANGE_RE`).
BUCKET_RE = re.compile(r'^(\d+)(?:-(\d+)|\+)$')


def headcount(size_range):
    """The headcount a stored range is judged by, or None when the stored
    text is not a bucket label at all.

    A closed bucket ("51-250") is judged by its upper bound, an open-ended
    one ("1000+") by the only bound it has.

    Anything outside that grammar is unreadable rather than a number to
    guess from: `size_range` is free text on the way in
    (`vault._translate_legacy_company_fields` copies a legacy `size`
    string in verbatim), so a thousands separator ("10,000+", "1.000+"),
    an abbreviation ("10k+"), an approximation ("~12,000"), a bare number
    ("50") or prose ("Fortune 500") all reach this function. Reading a
    number out of those would record a 10 000-person company as `small`
    and then clear the only evidence of its real size. A zero bound is
    unreadable too: no company has no people.
    """
    match = BUCKET_RE.match(str(size_range or '').strip())
    if not match:
        return None
    # The upper bound when the bucket has one, else its only bound.
    return int(match.group(2) or match.group(1)) or None


def size_class_for_range(size_range):
    """The class a stored range implies, or None when the range is not a
    readable bucket label."""
    count = headcount(size_range)
    if count is None:
        return None
    return next((label for limit, label in SIZE_CLASS_BY_HEADCOUNT if count <= limit), 'large')


def provenance_updates(company, *, derived_class):
    """The `field_provenance` this record should keep once its
    `size_range` is gone, as a payload fragment (empty when nothing about
    provenance changes).

    A provenance entry describes where a stored value came from, so an
    entry for a field this migration empties is a lie with teeth:
    `web.pages.companies.field_source` would report the surviving class as
    "set by you", and `server.py`'s size fill skips a record whose
    size pair is provenance-`user`, freezing it against future
    enrichment. So the key is dropped when the range is cleared, and when
    the class is derived FROM that range the entry moves onto
    `size_class` -- the derived class came from exactly that source.
    """
    provenance = company.get('field_provenance') or {}
    if 'size_range' not in provenance:
        return {}
    kept = {key: value for key, value in provenance.items() if key != 'size_range'}
    if derived_class:
        kept['size_class'] = provenance['size_range']
    return {'field_provenance': kept}


def plan(companies):
    """One row per company this migration would touch, in list order.

    Pure: it reads records and returns rows, so the planned change is
    testable without a vault and identical in dry-run and apply mode.
    `updates` is the payload `vault.save_company` would receive, or None
    when the row is only there to be reported.
    """
    rows = []
    for company in companies:
        stored_range = company.get('size_range')
        if not stored_range:
            continue
        row = {'id': company.get('id'), 'size_range': stored_range,
               'size_class': company.get('size_class')}
        if company.get('size_class'):
            rows.append(row | {'action': CLEAR_RANGE,
                               'updates': {'size_range': None}
                               | provenance_updates(company, derived_class=False)})
            continue
        derived = size_class_for_range(stored_range)
        if derived is None:
            rows.append(row | {'action': UNREADABLE, 'updates': None})
            continue
        rows.append(row | {'action': DERIVE_CLASS, 'derived': derived,
                           'updates': {'size_class': derived, 'size_range': None}
                           | provenance_updates(company, derived_class=True)})
    return rows


def describe(row):
    """One report line for one planned change."""
    current = row['size_class'] or '-'
    if row['action'] == CLEAR_RANGE:
        return (f"{row['id']}  size_range={row['size_range']!r} size_class={current!r}"
                f"  -> clear size_range, keep size_class={current!r}")
    if row['action'] == DERIVE_CLASS:
        return (f"{row['id']}  size_range={row['size_range']!r} size_class=None"
                f"  -> size_class={row['derived']!r}, clear size_range")
    return (f"{row['id']}  size_range={row['size_range']!r} size_class={current!r}"
            '  -> LEFT AS IS (not a bucket label, so there is no headcount'
            ' to derive a class from)')


def run(root, rows, apply_changes):
    """Report every planned change, and write them when apply_changes.

    Returns the ids actually written. A record that fails validation is
    reported to stderr and skipped, so one bad record cannot stop the
    sweep.
    """
    written = []
    for row in rows:
        print(describe(row))
        if not (apply_changes and row['updates']):
            continue
        try:
            vault.save_company(root, dict(row['updates']), row['id'])
        except Exception as error:
            print(f"  skipped {row['id']} ({type(error).__name__}: {error})", file=sys.stderr)
            continue
        written.append(row['id'])
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', required=True)
    parser.add_argument('--apply', action='store_true',
                        help='actually write (default: dry run, writes nothing)')
    args = parser.parse_args(argv)

    root = Path(args.vault)
    if not (root / 'companies').is_dir():
        raise SystemExit(f'{root} does not look like a CareerOS vault (missing companies/)')

    companies = vault.list_companies(root)
    rows = plan(companies)
    # The rows an --apply would actually write: an unreadable range is
    # only reported. Keeps the footer and the exit code honest about a
    # sweep whose every finding is a report.
    writable = [row for row in rows if row['updates']]
    print(f"vault={root}  mode={'APPLY' if args.apply else 'DRY RUN'}")
    if writable:
        # vault.save_company rebuilds the record from the full schema, so
        # the YAML diff can be wider than the size change reported below.
        print('note: writes go through vault.save_company, so an older record may also gain '
              'schema keys it is missing (note_list: [], field_provenance: {})')
    print('-' * 70)
    if not rows:
        print('nothing to change: every company is already on the class scale')
    written = run(root, rows, args.apply)
    print('-' * 70)
    counts = {action: sum(1 for row in rows if row['action'] == action)
              for action in (CLEAR_RANGE, DERIVE_CLASS, UNREADABLE)}
    legacy_size = [c.get('id') for c in companies if c.get('size')]
    print(f"{len(companies)} companies: {counts[CLEAR_RANGE]} range cleared (class kept), "
          f"{counts[DERIVE_CLASS]} class derived from the range, "
          f"{counts[UNREADABLE]} left as is, "
          f"{len(companies) - len(rows)} already on the class scale")
    if legacy_size:
        # The pre-ISIC free-text `size` field is a third shape, out of this
        # migration's scope; say so rather than let it pass unnoticed.
        print(f"note: {len(legacy_size)} company/ies also carry a legacy free-text `size` "
              f"({', '.join(legacy_size)}), which this migration does not touch")
    if args.apply:
        print(f'wrote {len(written)} record(s)')
        if len(written) < len(writable):
            # A skipped record printed its error to stderr, but a wrapper
            # reads the exit code: a partially written sweep is a failure,
            # not a success with a note.
            raise SystemExit(f'{len(writable) - len(written)} of {len(writable)} planned '
                             'write(s) were skipped (see the errors above)')
    elif writable:
        print('DRY RUN: nothing was written. Re-run with --apply to write.')
    elif rows:
        # Every finding is a report, so --apply has nothing to offer.
        print('DRY RUN: nothing was written, and --apply would write nothing either.')


if __name__ == '__main__':
    main()
