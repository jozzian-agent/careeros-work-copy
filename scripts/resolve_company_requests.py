"""Resolve the filed company requests: match, link, or hand to the admin.

A user who may not write a shared company asks for the one their posting
names, and the ask is stored as a private `company_requests` record with
status `filed` (PR #44, `careeros/vault.py`). This is the pass that
answers those. It runs nightly on the VPS under
`careeros-company-requests.timer` and it is also how the owner drains the
queue by hand.

## What one pass does

Every open request is read, grouped with the other open requests asking
for the same company, and the group is matched against the shared
companies with `careeros.company_requests.match_company`: exact
normalized name, then a name_variant identifier, then suffix-stripped
equality ("Northwind AG" is "Northwind"). A fuzzy candidate is never
linked, and more than one company matching is an ambiguity that goes to
the admin rather than a first-wins pick.

A confident match links every waiting job in the group to that company
and settles every request as `linked`.

No match is decided by `COMPANY_REQUEST_AUTO_CREATE`:

  * unset or anything but `1` (the default): the group is settled
    `needs_admin` and NO company is written. The admin review list
    (`GET /api/company-requests`) is what picks it up.
  * `1`: the company is created through the same path the server's own
    "create and link" uses, the jobs are linked, the group is settled
    `created`, and the new company gets the sector/size cascade an
    intake-created company gets.

Two outcomes are decided before any matching, because a request
outlives the job it came from: a request whose job was deleted is
`rejected`, and one whose job somebody has already linked is settled
`linked` against the company that job really points at. Neither writes
a company and neither touches an existing link.

## What it never does

  * it never logs a name. Every line this prints is a count. A request
    name, a company name, a job id and a user id are each a fact about
    one person's private record, and the journal on the VPS is read by
    whoever can read the journal. `tests/test_resolve_company_requests.py`
    asserts the absence through caplog with distinctive synthetic names.
  * it never writes outside a `vault.WriteLock` hold, and it never holds
    that lock across network I/O: the cascade runs after the write phase
    has released it, and takes the lock itself to apply its result.
  * it never guesses a vault. `--vault` or `CAREEROS_VAULT`, and neither
    means stop.

Idempotent: a settled request is no longer `filed`, so a second pass
with no new requests reads an empty queue and writes nothing.

Usage:
  python scripts/resolve_company_requests.py --vault /path/to/vault
  python scripts/resolve_company_requests.py --vault /path/to/vault --dry-run
  COMPANY_REQUEST_AUTO_CREATE=1 python scripts/resolve_company_requests.py --vault ...
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careeros import company_requests as requests_module  # noqa: E402
from careeros import enrich as company_enrichment  # noqa: E402
from careeros import vault  # noqa: E402

logger = logging.getLogger('careeros.resolve_company_requests')

#: The switch between admin-approval mode and auto-create mode. Off
#: unless it is exactly '1', which is the same reading every other
#: product switch uses (`CAREEROS_REACT_UI`, `BACKFILL_USE_LLM`): a
#: variable set to 'false' or 'no' must not read as on.
AUTO_CREATE_ENV = 'COMPANY_REQUEST_AUTO_CREATE'

VAULT_ENV = 'CAREEROS_VAULT'

#: The counts one pass reports, in the order the summary prints them.
#: Every one of them is a number of REQUESTS, not of companies or jobs,
#: so the four always add up to the queue the pass read.
OUTCOMES = ('linked', 'created', 'needs_admin', 'rejected')


def auto_create_enabled(environ=None):
    """Whether this pass may create a company for an unmatched name."""
    return (environ if environ is not None else os.environ).get(AUTO_CREATE_ENV) == '1'


def resolve(root, *, auto_create=False, dry_run=False, lock=None):
    """One pass. Returns the counts, and the ids of companies created.

    The write phase holds one `vault.WriteLock` for the whole of itself,
    so a pass is all-or-nothing against a concurrent writer rather than
    a record at a time. Nothing inside it reaches the network.

    The cascade for a created company runs AFTER that hold is released,
    because it fetches: `enrich.run_cascade` takes the lock itself to
    apply whatever it finds. A dry run never gets there, having created
    nothing.

    `lock` is for a caller that already has one (a test, or a future
    in-process caller). The default builds the one this vault needs.
    """
    lock = lock if lock is not None else vault.WriteLock(root)
    counts = {outcome: 0 for outcome in OUTCOMES}
    created_ids = []
    with lock:
        queue = requests_module.open_requests(root)
        waiting, gone, answered = requests_module.partition(root, queue)
        counts['rejected'] += len(gone)
        counts['linked'] += len(answered)
        if not dry_run:
            requests_module.settle_decided(root, gone, answered)
        companies = requests_module.shared_companies(root)
        for group in requests_module.group_waiting(waiting):
            name = group[0][0]['name']
            company, ambiguous = requests_module.match_company(companies, name)
            if company is not None:
                counts['linked'] += len(group)
                if not dry_run:
                    requests_module.apply_group(root, group, company, requests_module.LINKED)
                continue
            if ambiguous or not auto_create:
                counts['needs_admin'] += len(group)
                if not dry_run:
                    for request, _job in group:
                        requests_module.settle(root, request, requests_module.NEEDS_ADMIN)
                continue
            counts['created'] += len(group)
            if dry_run:
                # The creation a real pass would make, counted as having
                # happened: a later group whose name differs only by a
                # legal suffix must then report as linked to it rather
                # than as a second creation, or the dry run would promise
                # one more company than the pass writes. Only the name is
                # needed to match against, and no id exists to give it.
                companies.append({'id': '', 'name': name})
                continue
            company = requests_module.create_company(root, name)
            created_ids.append(company['id'])
            # Visible to the rest of this pass, for the same reason.
            companies.append(company)
            requests_module.apply_group(root, group, company, requests_module.CREATED)
    for company_id in created_ids:
        # Outside the lock hold above on purpose; see the docstring.
        company_enrichment.run_cascade(root, company_id, lock)
    return counts, created_ids


def summary(counts, *, dry_run=False):
    """The one line a pass prints. Counts only, never a name."""
    total = sum(counts.values())
    detail = ', '.join(f'{counts[outcome]} {outcome}' for outcome in OUTCOMES)
    prefix = 'dry run: would resolve' if dry_run else 'resolved'
    return f'{prefix} {total} request(s): {detail}'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', help=f'vault path (default: the {VAULT_ENV} variable)')
    parser.add_argument('--dry-run', action='store_true',
                        help='report the same counts and write nothing')
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    given = args.vault or os.environ.get(VAULT_ENV)
    if not given:
        raise SystemExit(f'no vault given: pass --vault PATH or set {VAULT_ENV}')
    root = Path(given)
    if not (root / 'jobs').is_dir():
        raise SystemExit(f'{root} does not look like a CareerOS vault (missing jobs/)')

    auto_create = auto_create_enabled()
    logger.info('company request pass: mode=%s%s',
                'auto-create' if auto_create else 'admin-approval',
                ' (dry run)' if args.dry_run else '')
    counts, created = resolve(root, auto_create=auto_create, dry_run=args.dry_run)
    logger.info('%s', summary(counts, dry_run=args.dry_run))
    if created:
        logger.info('ran the sector/size cascade on %d new company record(s)', len(created))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
