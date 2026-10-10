"""One-shot, plan-driven migration: link experiences to the shared company DB.

Reads a plan JSON (kept OUTSIDE the repo -- it names real employers) with:

  companies: [{name, website}]            -- create if missing (match by
                                             casefolded name), else reuse
  links:     [{experience_id, company_name}]
                                          -- set company_id + canonical name
                                             through save_experience so
                                             validation and the filename
                                             rule run
  splits:    [{experience_id, delete_source: bool, roles: [
                {company_name, website, title, start, end, summary,
                 detail, skills, highlights, people_led}]}]
                                          -- each role becomes a new
                                             experience linked to its
                                             company (company created from
                                             the plan if missing); source
                                             deleted when delete_source

Safety rails:
  * refuses to write unless --apply AND --vault PATH (dry run by default)
  * idempotent: existing company names are reused, already-linked
    experiences are skipped, split re-runs detect the source is gone
  * all writes go through vault.save_company / save_experience /
    delete_experience -- never raw YAML edits

Usage:
  python scripts/migrate_experience_companies.py --vault /path/to/vault \
      --plan /path/to/plan.json [--apply]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from careeros import vault  # noqa: E402


def load_plan(path):
    plan = json.loads(Path(path).read_text())
    for key in ('companies', 'links', 'splits'):
        plan.setdefault(key, [])
    return plan


def ensure_company(root, name, website, index):
    """Return the CO-id for `name`, creating a minimal record if absent."""
    existing = next((c for c in vault.list_companies(root)
                     if c['name'].casefold() == name.casefold()), None)
    if existing:
        return existing['id'], False
    data = {'name': name, 'website': website or None, 'kind': 'employer',
            'name_source': 'owner'}
    if name not in index:
        index[name] = vault.next_company_id(root)
    # save_company assigns its own id internally via _save_record; create
    # then read the id back from the stored record.
    saved = vault.save_company(root, data)
    index[name] = saved['id']
    return saved['id'], True


def company_id_for(root, name, website, index):
    hit = next((c for c in vault.list_companies(root)
                if c['name'].casefold() == name.casefold()), None)
    if hit:
        return hit['id'], False
    return ensure_company(root, name, website, index)


def apply_plan(root, plan, apply_changes):
    log = []
    index = {}

    def emit(row):
        log.append(row)
        if apply_changes:
            row['run']()

    # 1. Companies from the plan (explicit create list first so splits/links
    #    reuse them).
    for entry in plan['companies']:
        def make(entry=entry):
            cid, created = ensure_company(root, entry['name'],
                                          entry.get('website'), index)
            print(f"company  {entry['name']:<45} {cid} ({'created' if created else 'exists'})")
        emit({'kind': 'company', 'name': entry['name'], 'run': make})

    # 2. Links.
    for entry in plan['links']:
        exp = vault.load_experience(root, entry['experience_id'])
        if exp is None:
            print(f"link     {entry['experience_id']} MISSING -- skipped")
            continue
        hit = next((c for c in vault.list_companies(root)
                    if c['name'].casefold() == entry['company_name'].casefold()), None)
        if exp.get('company_id') and hit and exp['company_id'] == hit['id']:
            print(f"link     {entry['experience_id']} already linked -- skipped")
            continue
        def link(entry=entry, exp=exp):
            cid, _ = company_id_for(root, entry['company_name'],
                                    entry.get('website'), index)
            canonical = next(c['name'] for c in vault.list_companies(root) if c['id'] == cid)
            vault.save_experience(root, {'company_id': cid, 'company': canonical},
                                  entry['experience_id'])
            print(f"link     {entry['experience_id']} -> {canonical} ({cid})")
        emit({'kind': 'link', 'name': entry['experience_id'], 'run': link})

    # 3. Splits.
    for entry in plan['splits']:
        exp = vault.load_experience(root, entry['experience_id'])
        if exp is None:
            print(f"split    {entry['experience_id']} already gone -- skipped")
            continue
        def split(entry=entry):
            for role in entry['roles']:
                cid, _ = company_id_for(root, role['company_name'],
                                        role.get('website'), index)
                canonical = next(c['name'] for c in vault.list_companies(root) if c['id'] == cid)
                data = {'company': canonical, 'company_id': cid,
                        'title': role['title'], 'start': role['start'],
                        'end': role['end'], 'location': role.get('location', ''),
                        'summary': role.get('summary', ''),
                        'detail': role.get('detail', ''),
                        'skills': role.get('skills', []),
                        'highlights': role.get('highlights', []),
                        'people_led': role.get('people_led')}
                saved = vault.save_experience(root, data)
                print(f"split    {entry['experience_id']} -> {saved['id']} "
                      f"{canonical} / {role['title']}")
            if entry.get('delete_source', True):
                vault.delete_experience(root, entry['experience_id'])
                print(f"split    deleted source {entry['experience_id']}")
        emit({'kind': 'split', 'name': entry['experience_id'], 'run': split})

    return log


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--vault', required=True)
    ap.add_argument('--plan', required=True)
    ap.add_argument('--apply', action='store_true',
                    help='actually write (default: dry run)')
    args = ap.parse_args()

    root = Path(args.vault)
    if not (root / 'experiences').is_dir() or not (root / 'companies').is_dir():
        raise SystemExit(f'{root} does not look like a CareerOS vault '
                         '(missing experiences/ or companies/)')

    plan = load_plan(args.plan)
    print(f"vault={root}  plan={args.plan}  mode={'APPLY' if args.apply else 'DRY RUN'}")
    print('-' * 70)
    apply_plan(root, plan, args.apply)
    print('-' * 70)
    exps = vault.list_experiences(root)
    comps = vault.list_companies(root)
    linked = sum(1 for e in exps if e.get('company_id'))
    print(f"after: {len(exps)} experiences ({linked} linked), {len(comps)} companies")


if __name__ == '__main__':
    main()
