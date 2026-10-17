"""Report which companies' stored `size_class` would change under the BFS
size boundaries. Reads a vault, writes nothing, ever.

WHY A REPORT AND NOT A MIGRATION. Owner decision D3 (2026-10-17) moved the
class boundaries: they were inclusive at the top of each class (micro
<=10, small <=50, medium <=250), which was off by one against the EU
recommendation the capability cites and against the BFS classes, and a new
`xl` class now starts at 1000. Every company whose class was derived under
the old thresholds from a count at a boundary -- or from a count of 1000
or more -- now carries a class the current rule would not produce.

Rewriting those records would be a silent edit of owner-visible data, and
CAREER-55 says not to: it ships the code lists, not a data migration. So
this script answers the one question a migration would need answered
first, and leaves the decision with the owner.

WHAT IT CAN AND CANNOT SEE. A class can only be re-derived where the
record still holds the evidence it came from:

  * a headcount (`enrichment.employee_count`, the posting evidence the
    aggregation keeps, or a top-level `employee_count` on an older
    record) -- re-derivable, and reported as CHANGE or SAME
  * a legacy `size_range` bucket and nothing else -- NOT re-derivable.
    A bucket is a range, and three of the four bucket edges straddle a
    class boundary ('1-10' spans micro and small under the new rule), so
    the answer depends on the count the bucket replaced. Reported as
    INDETERMINATE rather than guessed.
  * nothing at all -- no evidence, nothing to say. Counted in the footer.

OWNER-LOCKED VALUES are reported and marked, never quietly excluded: a
`field_provenance` entry of 'user' on `size_class` means the owner set the
class by hand, and "human edits always win" makes that class correct by
definition whatever a count says. The owner still gets to see which ones
the arithmetic disagrees with.

Safety rails:
  * no write path at all: there is no --apply, and nothing here imports a
    save function
  * `--vault PATH` is required, so a run can never default onto a vault by
    accident
  * the report names records by id, never by company name, so it can be
    pasted into a build note or a PR without leaking the vault

Usage:
  python scripts/flag_size_review.py --vault /path/to/vault
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from careeros import taxonomy, vault  # noqa: E402
from org_intake import classify  # noqa: E402

CHANGE = 'change'
SAME = 'same'
INDETERMINATE = 'indeterminate'


def stored_count(company):
    """The headcount a company record still holds, as an integer, or None.

    `enrichment.employee_count` first, because that is where the size
    cascade's own evidence lives (owner decision 2026-10-16); a top-level
    `employee_count` is read too, for a record written before the
    aggregation put it under `enrichment`. Parsed with the capability's
    own reader, so "50-100" resolves the same way here as it does when a
    class is derived.
    """
    enrichment = company.get('enrichment') or {}
    for value in (enrichment.get('employee_count'), company.get('employee_count')):
        count = classify.resolve_employee_count(value)
        if count is not None:
            return count
    return None


def owner_locked(company):
    """Whether the owner set this company's class by hand."""
    return (company.get('field_provenance') or {}).get('size_class') == 'user'


def plan(companies):
    """One row per company that has a stored class worth checking, in list
    order. Pure: it reads records and returns rows, so the report is
    testable without a vault.

    A company with no stored `size_class` is not a row: there is no stored
    value to change. A re-derivation that agrees is a row (SAME), because
    "checked and unchanged" is a different answer from "could not check"
    and the footer counts them apart.
    """
    rows = []
    for company in companies:
        stored_class = company.get('size_class')
        if not stored_class:
            continue
        row = {'id': company.get('id'), 'size_class': stored_class,
               'locked': owner_locked(company)}
        count = stored_count(company)
        if count is None:
            if company.get('size_range'):
                rows.append(row | {'action': INDETERMINATE, 'count': None,
                                   'size_range': company.get('size_range'), 'derived': None})
            continue
        derived = classify.size_class_for(count)
        rows.append(row | {'action': CHANGE if derived != stored_class else SAME,
                           'count': count, 'size_range': company.get('size_range'),
                           'derived': derived})
    return rows


def describe(row):
    """One report line for one row."""
    lock = '  [owner-set]' if row['locked'] else ''
    if row['action'] == CHANGE:
        return (f"{row['id']}  size_class={row['size_class']!r} count={row['count']}"
                f"  -> would be {row['derived']!r}{lock}")
    if row['action'] == SAME:
        return (f"{row['id']}  size_class={row['size_class']!r} count={row['count']}"
                f"  -> unchanged{lock}")
    return (f"{row['id']}  size_class={row['size_class']!r} size_range={row['size_range']!r}"
            '  -> INDETERMINATE (a bucket is a range, so the class it implies'
            f' depends on the count it replaced){lock}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', required=True)
    args = parser.parse_args(argv)

    root = Path(args.vault)
    if not (root / 'companies').is_dir():
        raise SystemExit(f'{root} does not look like a CareerOS vault (missing companies/)')

    companies = vault.list_companies(root)
    rows = plan(companies)
    changes = [row for row in rows if row['action'] == CHANGE]
    print(f'vault={root}  mode=REPORT ONLY (this script has no write path)')
    # The boundaries from the taxonomy code list, so the header line
    # cannot drift from the thresholds the rows are judged against.
    print('boundaries: ' + ', '.join(
        f"{entry['code']} {entry['min']}-{entry['max']}" if entry['max'] is not None
        else f"{entry['code']} {entry['min']}+"
        for entry in taxonomy.entries('company_size')))
    print('-' * 70)
    for row in rows:
        print(describe(row))
    print('-' * 70)
    counts = {action: sum(1 for row in rows if row['action'] == action)
              for action in (CHANGE, SAME, INDETERMINATE)}
    no_class = sum(1 for company in companies if not company.get('size_class'))
    no_evidence = len(companies) - len(rows) - no_class
    print(f'{len(companies)} companies: {counts[CHANGE]} would change class, '
          f'{counts[SAME]} re-derive to the same class, '
          f'{counts[INDETERMINATE]} cannot be re-derived (legacy range only), '
          f'{no_evidence} have a class but no evidence to re-derive it, '
          f'{no_class} have no stored class')
    if not changes and no_evidence:
        # The likely outcome on a vault whose size evidence predates the
        # 2026-10-16 headcount decision: the classes are there, the counts
        # they came from are not. Say so, so a clean report is not read as
        # "every stored class is right under the new rule".
        print(f'no change found, but {no_evidence} company/ies hold a class with no headcount '
              'to re-derive it from: a clean report here means "nothing can be checked", '
              'not "nothing moved"')
    locked = [row['id'] for row in changes if row['locked']]
    if locked:
        print(f'of the {len(changes)} change(s), {len(locked)} is/are owner-set '
              f'({", ".join(locked)}): "human edits always win", so a change there is the '
              "owner's call and not an arithmetic one")
    print('nothing was written: this report has no --apply, by design (CAREER-55)')


if __name__ == '__main__':
    main()
