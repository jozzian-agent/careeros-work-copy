"""One-shot migration: rewrite every stored company sector letter from UN
ISIC Rev.4 to NOGA 2025 (NACE Rev. 2.1).

Owner ruling 2026-11-03 (CAREER-132): the product classifies companies
against NOGA 2025, Switzerland's implementation of NACE Rev. 2.1. That
table has 22 sections (A-V) where ISIC Rev.4 had 21 (A-U), and the two
agree only up to I:

  * A-I keep their letter and their meaning.
  * old J ("Information and communication") was SPLIT. Publishing,
    broadcasting and content production stayed J; telecommunication,
    software, computer programming, IT consulting and computing
    infrastructure became K. Which half a company belongs in cannot be
    read off the letter, so this script never decides it -- see
    --decisions below.
  * old K-U each moved up one letter: K->L, L->M, M->N, N->O, O->P, P->Q,
    Q->R, R->S, S->T, T->U, U->V.

RUN IT ONCE. The letters a record stores do not say which revision wrote
them, so this migration cannot tell migrated data from unmigrated data. A
second --apply run would shift every letter a second time (an N that was
already migrated from M becomes O). The dry run is the check: read the
table, then apply once.

Safety rails:
  * dry run by default: nothing is written unless `--apply` is passed
  * old J is never guessed. A J row prints the company's free-text
    industry and the letter the NEW keyword table proposes for it, and is
    reported as NEEDS-DECISION. It is skipped even under --apply unless
    `--decisions FILE.yaml` names that company's letter.
  * a stored letter that is not one of the 21 old ISIC letters is a
    warning row, never a guess, and the company is left exactly as it is
  * a company whose stored letters do not ALL resolve is skipped whole,
    so a record never ends up half-migrated
  * writes go through `vault.save_company`, so validation (the letter
    must be a known NOGA section) and the filename rule run -- never raw
    YAML edits
  * one record's failure is reported and skipped, never fatal for the rest

The vault is the one the product itself reads at runtime
(`careeros.users.vault_root`: `--vault`, then CAREEROS_VAULT, then the
installed default), so a migration can never run against a different
vault than the server serves.

The decisions file is a plain mapping of company name to the letter that
company belongs under, and the only letters it may name are J and K:

    Google: K
    Thomson Reuters Enterprise Centre GmbH: K

Usage:
  PYTHONPATH=vendor/capa-repo python3 scripts/migrate_sectors_noga2025.py
  PYTHONPATH=vendor/capa-repo python3 scripts/migrate_sectors_noga2025.py \
      --decisions old-j-decisions.yaml --apply
"""
import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from careeros import users, vault  # noqa: E402
from org_intake import classify  # noqa: E402

# A-I mean the same activity in both classifications.
UNCHANGED = tuple('ABCDEFGHI')
# Everything after the split moved up exactly one letter.
SHIFTED = {'K': 'L', 'L': 'M', 'M': 'N', 'N': 'O', 'O': 'P', 'P': 'Q',
           'Q': 'R', 'R': 'S', 'S': 'T', 'T': 'U', 'U': 'V'}
# The one old letter that became two.
SPLIT = 'J'
SPLIT_INTO = ('J', 'K')
OLD_LETTERS = frozenset(UNCHANGED) | {SPLIT} | frozenset(SHIFTED)

# Returned in place of a letter. Both mean "left exactly as it is".
NEEDS_DECISION = 'NEEDS-DECISION'
NOT_OLD_ISIC = 'NOT-AN-ISIC-LETTER'


def new_letter(old, decision=None):
    """The NOGA 2025 letter one stored ISIC Rev.4 letter becomes.

    Pure: the whole old->new table, including the split rule, in one
    place so it can be checked without a vault.

      * one of A-I: itself
      * one of K-U: the next letter up (SHIFTED)
      * J: `decision` when it is J or K, else NEEDS_DECISION -- the split
        is a per-company judgement and this function refuses to invent it
      * anything else (including 'V', which ISIC Rev.4 never had, and so
        is a sign the vault was already migrated): NOT_OLD_ISIC
    """
    if old in UNCHANGED:
        return old
    if old in SHIFTED:
        return SHIFTED[old]
    if old == SPLIT:
        return decision if decision in SPLIT_INTO else NEEDS_DECISION
    return NOT_OLD_ISIC


def proposed_split_letter(industry):
    """The half of the split one free-text industry string reads as, or
    None when the new keyword table cannot tell.

    Only a proposal, printed for a person to decide from: the keyword
    table is the same best-effort matcher the enrichment cascade uses,
    and a signal that matches both halves (or neither) proposes nothing
    rather than picking one.
    """
    halves = [code for code in classify.all_matched_sections(industry or '')
              if code in SPLIT_INTO]
    return halves[0] if len(halves) == 1 else None


def industry_text(company):
    """Every free-text industry signal this record carries, as one string:
    the legacy `sector` field an extractor wrote, plus the raw industry
    strings the enrichment aggregation collected. Empty when it has
    none, which is what makes a J company undecidable from the data."""
    parts = [company.get('sector') or '']
    parts += [text for text in (company.get('enrichment') or {}).get('sectors', [])
              if isinstance(text, str)]
    return '; '.join(part for part in parts if part.strip())


def plan(companies, decisions=None):
    """One row per stored sector letter, in list order; companies with no
    sector produce no row.

    Pure: it reads records and returns rows, so the planned change is
    testable without a vault and identical in dry-run and apply mode.
    `updates` is the payload `vault.save_company` would receive, and is
    set on the FIRST row of a company whose every letter resolved; it is
    None on every other row, so a record is written once and whole or not
    at all.
    """
    decisions = decisions or {}
    rows = []
    for company in companies:
        stored = [code for code in (company.get('sectors') or []) if code]
        if not stored:
            continue
        industry = industry_text(company)
        resolved = [new_letter(code, decisions.get(company.get('name'))) for code in stored]
        writable = all(code not in (NEEDS_DECISION, NOT_OLD_ISIC) for code in resolved)
        for index, (old, new) in enumerate(zip(stored, resolved)):
            rows.append({
                'id': company.get('id'),
                'name': company.get('name') or '',
                'old': old,
                'new': new,
                'industry': industry,
                'proposed': proposed_split_letter(industry) if old == SPLIT else None,
                'updates': {'sectors': resolved} if writable and index == 0 else None,
            })
    return rows


def note(row):
    """The explanation column: why a row is not a plain letter swap, or
    '' when it is."""
    if row['new'] == NEEDS_DECISION:
        industry = row['industry'] or '(no free-text industry stored)'
        proposed = row['proposed'] or '(the keyword table cannot tell)'
        return f'industry: {industry} / proposed: {proposed}'
    if row['new'] == NOT_OLD_ISIC:
        return 'not one of the 21 ISIC Rev.4 letters: left as it is, never guessed'
    if row['old'] == row['new']:
        return 'unchanged in NOGA 2025'
    return ''


def table(rows):
    """The report, as `company | old letter | new letter | note` lines
    with the header and its rule. Returned rather than printed so the
    same text can be checked in a test."""
    header = ('company', 'old', 'new', 'note')
    cells = [header] + [(row['name'], row['old'], row['new'], note(row)) for row in rows]
    widths = [max(len(str(cell[column])) for cell in cells) for column in range(3)]
    lines = []
    for index, cell in enumerate(cells):
        line = ' | '.join(str(value).ljust(width) for value, width in zip(cell, widths))
        lines.append((line + ' | ' + cell[3]).rstrip(' |'))
        if index == 0:
            lines.append('-+-'.join('-' * width for width in widths) + '-+-' + '-' * 40)
    return '\n'.join(lines)


def load_decisions(path):
    """The old-J decisions, as {company name: letter}.

    A letter that is not J or K is fatal rather than skipped: a typo that
    quietly left a company undecided is the one outcome this file exists
    to prevent.
    """
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict) or not data:
        raise SystemExit(f'{path}: expected a mapping of company name to J or K')
    bad = {name: letter for name, letter in data.items() if letter not in SPLIT_INTO}
    if bad:
        raise SystemExit(f'{path}: these decisions name a letter that is not J or K: {bad}')
    return data


def run(root, rows, apply_changes):
    """Report the table, and write the resolved companies when
    apply_changes. Returns the ids actually written."""
    print(table(rows))
    written = []
    if not apply_changes:
        return written
    for row in (row for row in rows if row['updates']):
        try:
            vault.save_company(root, dict(row['updates']), row['id'])
        except Exception as error:
            print(f"  skipped {row['id']} ({type(error).__name__}: {error})", file=sys.stderr)
            continue
        written.append(row['id'])
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', help='vault directory (default: the one the server reads, '
                                        'via CAREEROS_VAULT or the installed default)')
    parser.add_argument('--decisions', help='YAML mapping of company name to J or K, for the '
                                            'companies whose stored letter is the old J')
    parser.add_argument('--apply', action='store_true',
                        help='actually write (default: dry run, writes nothing)')
    args = parser.parse_args(argv)

    root = users.vault_root(args.vault)
    if not (root / 'companies').is_dir():
        raise SystemExit(f'{root} does not look like a CareerOS vault (missing companies/)')
    decisions = load_decisions(args.decisions) if args.decisions else {}

    companies = vault.list_companies(root)
    rows = plan(companies, decisions)
    writable = [row for row in rows if row['updates']]
    undecided = [row for row in rows if row['new'] == NEEDS_DECISION]
    unknown = [row for row in rows if row['new'] == NOT_OLD_ISIC]
    unused = sorted(set(decisions) - {row['name'] for row in rows if row['old'] == SPLIT})

    print(f"vault={root}  mode={'APPLY' if args.apply else 'DRY RUN'}")
    if args.apply:
        # The letters carry no revision marker, so nothing downstream can
        # catch a second run. Say it where the person running it looks.
        print('note: this migration is NOT idempotent -- a second --apply would shift '
              'every letter again. Run it once.')
    print('-' * 70)
    if not rows:
        print('nothing to change: no company stores a sector')
    written = run(root, rows, args.apply)
    print('-' * 70)
    print(f"{len(companies)} companies, {len(rows)} stored sector letter(s): "
          f"{len(writable)} record(s) to rewrite, {len(undecided)} awaiting an old-J decision, "
          f"{len(unknown)} not an ISIC letter, "
          f"{len(companies) - len({row['id'] for row in rows})} with no sector")
    if unused:
        # A decision for a company that is not an old J is either a typo
        # in the name or a decision already applied; both are worth a word.
        print(f"note: {len(unused)} decision(s) matched no old-J company: {', '.join(unused)}")
    if args.apply:
        print(f'wrote {len(written)} record(s)')
        if len(written) < len(writable):
            # A skipped record printed its error to stderr, but a wrapper
            # reads the exit code: a partially written sweep is a failure,
            # not a success with a note.
            raise SystemExit(f'{len(writable) - len(written)} of {len(writable)} planned '
                             'write(s) were skipped (see the errors above)')
        if undecided:
            print(f'{len(undecided)} company/ies still store the old J: decide each one and '
                  're-run with --decisions')
    elif writable or undecided:
        print('DRY RUN: nothing was written. Re-run with --apply to write.')
    elif rows:
        print('DRY RUN: nothing was written, and --apply would write nothing either.')


if __name__ == '__main__':
    main()
