#!/usr/bin/env python3
"""The family suggestion queue (CAREER-131).

When no job family fits a posting, the classification model answers
`unknown` with a `proposed_role` name instead of forcing the closest
family (careeros/classify/llm.py). Those proposals land in the run
files under `data/classification/`; this script is the owner's view of
them and the tool that turns an approved one into taxonomy data.

    # what has been proposed, and how often
    scripts/family_suggestions.py list

    # owner approval: one proposal becomes a family
    scripts/family_suggestions.py approve "Robotics technician" \\
        --code robotics-technician --label-de "Robotertechniker" \\
        --isco3 742

    # then re-run ONLY the jobs whose family was unknown
    scripts/run_classification.py --pool ... --layer llm \\
        --previous data/classification/run_YYYY-MM-DD.yaml --out ...

`approve` writes the two files that must never drift -- the ESCO seed
(esco_occupations.yaml) and the family layer (occupation_families.yaml)
-- and updates the pinned counts in the tests that guard them, because
a family leaving or joining the list is a decision the pins exist to
make visible, not a number to hand-edit afterwards. The new family
starts as `proposed` with no ESCO citation: confirming one is the
CAREER-29 route (find the concept, fill esco_uri, re-run the seed),
unchanged by this script.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from careeros import taxonomy  # noqa: E402
from careeros.classify import llm  # noqa: E402

SEED_REL = Path('careeros/data/esco_occupations.yaml')
FAMILIES_REL = Path('careeros/data/taxonomy/occupation_families.yaml')
TAXONOMY_TESTS_REL = Path('tests/test_taxonomy.py')
FACET_TESTS_REL = Path('tests/test_function_facet.py')
RUNS_DIR_REL = Path('data/classification')


def normalise(name):
    """One proposal name regardless of spacing or capitalisation: the
    model writes 'Robotics Technician' on Monday and 'robotics
    technician' on Tuesday and those are one proposal, not two."""
    return ' '.join(str(name).split()).casefold()


# --- collect ---------------------------------------------------------------

def collect(runs_dir):
    """Every proposal in every run file, latest run per posting wins.

    A posting classified three times is one posting, so the count is of
    DISTINCT postings whose family is unknown with a proposal attached --
    the number the owner needs to decide whether a name is a real gap in
    the list or one odd posting.
    """
    latest = {}
    for path in sorted(Path(runs_dir).glob('run_*.yaml')):
        document = yaml.safe_load(path.read_text()) or {}
        for posting in document.get('postings') or []:
            if not posting.get('key'):
                continue
            latest[posting['key']] = posting
    proposals = {}
    for key, posting in latest.items():
        record = (posting.get('values') or {}).get('occupation_family') or {}
        evidence = record.get('evidence') or {}
        if evidence.get('needs_review') == llm.FAMILY_SUGGESTED and evidence.get('proposed_role'):
            proposals[key] = {
                'key': key,
                'title': posting.get('title') or '',
                'proposed_role': str(evidence['proposed_role']),
                'normalised': normalise(evidence['proposed_role']),
            }
    return proposals


def report(proposals):
    """The queue as the owner reads it: name, how many postings, examples."""
    if not proposals:
        print('no family proposals in the run files')
        return 0
    by_name = Counter(item['normalised'] for item in proposals.values())
    display = {}
    for item in proposals.values():
        display.setdefault(item['normalised'], item['proposed_role'])
    print(f"{'proposed role':<36}{'postings':>9}   examples")
    for name, count in by_name.most_common():
        examples = [item['title'] for item in proposals.values()
                    if item['normalised'] == name][:3]
        print(f"{display[name]:<36}{count:>9}   " + ' | '.join(filter(None, examples)))
    print('-' * 60)
    print(f'{len(by_name)} distinct proposals across {len(proposals)} postings')
    return len(by_name)


# --- approve ---------------------------------------------------------------

def _yaml_quote(text):
    return '"' + str(text).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _insert_family(text, *, code, label, label_de, isco4, isco3, note):
    """The new family entry, appended to the occupation_family codes list.

    The anchor is the NEXT dimension in the file rather than the last
    entry, because entries carry free-form notes and a regex that finds
    "the end of the last entry" is one comment away from corrupting the
    file."""
    entry = (
        '      # Approved from the family suggestion queue (CAREER-131):\n'
        f'      # the model proposed {_yaml_quote(label)} for postings whose family was\n'
        '      # unknown and the owner approved the name as a family.\n'
        f'      - code: {code}\n'
        f'        label: {_yaml_quote(label)}\n'
        f'        label_de: {_yaml_quote(label_de)}\n'
        f"        isco4: {_yaml_quote(isco4) if isco4 else 'null'}\n"
        f'        isco3: {_yaml_quote(isco3)}\n'
        '        status: proposed\n'
        f'        synonyms: [{_yaml_quote(label)}]\n'
        '        note: >-\n'
        f'          {note}\n'
    )
    anchor = '  - dimension: occupation_family_status'
    if anchor not in text:
        raise SystemExit('occupation_families.yaml: cannot find the occupation_family_status '
                         'list to insert before; the file shape changed')
    return text.replace(anchor, entry + anchor, 1)


def _insert_seed(text, *, code, label, label_de, isco4):
    """The matching seed entry, appended at the end of the occupations list."""
    entry = (
        '  # Approved from the family suggestion queue (CAREER-131), proposed\n'
        '  # by the model for postings no family fitted. No ESCO concept cited:\n'
        '  # confirming one is the CAREER-29 route.\n'
        f'  - id: {code}\n'
        f'    label: {_yaml_quote(label)}\n'
        f'    label_de: {_yaml_quote(label_de)}\n'
        f"    isco: {_yaml_quote(isco4) if isco4 else 'null'}\n"
        '    esco_uri: null\n'
        '    keywords: []\n'
    )
    if not text.endswith('\n'):
        text += '\n'
    return text + entry


def _bump_pins(text, replacements, path):
    """Every pinned count this family moves, each matched exactly once.

    A pin that no longer matches is a changed test file, and silently
    skipping it would leave the suite red with no clue why -- so a
    miss aborts the whole approval before any file is written.
    """
    for pattern, value in replacements:
        new_text, count = re.subn(pattern, lambda m, v=value: m.group(1) + str(v), text)
        if count != 1:
            raise SystemExit(f'{path}: pinned count {pattern!r} matched {count} times, '
                             'expected exactly 1; the test file changed shape')
        text = new_text
    return text


def _append_function_id(text, code):
    match = re.search(r'FUNCTION_IDS = \(([^)]*)\)', text, re.S)
    if not match:
        raise SystemExit('test_function_facet.py: cannot find the FUNCTION_IDS tuple')
    body = match.group(1).rstrip()
    new_text = text[:match.start()] + f'FUNCTION_IDS = ({body}\n    {code!r},\n)' \
        + text[match.end():]
    return new_text


def approve(name, *, code, label_de, isco3, isco4=None, root=None):
    """One approved proposal becomes a family in both data files.

    Returns the number of postings the proposal covered (for the note).
    Validates against the taxonomy BEFORE touching any file, and writes
    all four files only once every edit is known to apply.
    """
    root = Path(root) if root else REPO_ROOT
    proposals = collect(root / RUNS_DIR_REL)
    covered = sum(1 for item in proposals.values() if item['normalised'] == normalise(name))
    label = next((item['proposed_role'] for item in proposals.values()
                  if item['normalised'] == normalise(name)), name)

    if not re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', code):
        raise SystemExit(f'code {code!r} is not kebab-case')
    if not taxonomy.valid_code('isco_minor_group', isco3):
        raise SystemExit(f'isco3 {isco3!r} is not a CH-ISCO-19 minor group this taxonomy knows')
    if isco4 and not taxonomy.valid_code('isco_unit_group', isco4):
        # The shipped ISCO-08 list is a curated subset, but the drift
        # test (test_every_family_isco_code_is_a_unit_group_this_
        # taxonomy_knows) grades EVERY family's isco4 against it -- so
        # an isco4 outside the list would turn the suite red the moment
        # it is written. Refusing here is what keeps approve from
        # producing that diff.
        raise SystemExit(f'isco4 {isco4!r} is not in the ISCO-08 unit-group list this '
                         'taxonomy ships; leave it off and confirm it via the CAREER-29 route')
    existing = {entry['code'] for entry in yaml.safe_load(
        (root / FAMILIES_REL).read_text())['code_lists'][0]['codes']}
    if code in existing:
        raise SystemExit(f'family {code!r} already exists; nothing to approve')

    seed_path = root / SEED_REL
    families_path = root / FAMILIES_REL
    taxonomy_tests_path = root / TAXONOMY_TESTS_REL
    facet_tests_path = root / FACET_TESTS_REL
    seed_text = seed_path.read_text()
    families_text = families_path.read_text()

    families_document = yaml.safe_load(families_text)
    entries = next(cl for cl in families_document['code_lists']
                   if cl['dimension'] == 'occupation_family')['codes']
    total = len(entries) + 1
    proposed = sum(1 for entry in entries if entry.get('status') == 'proposed') + 1
    without_isco4 = sum(1 for entry in entries
                        if entry.get('isco4') is None and entry.get('status') == 'proposed')
    if not isco4:
        without_isco4 += 1

    today = date.today().isoformat()
    note = (f'Approved by the owner on {today} from the family suggestion queue '
            f'(CAREER-131): the classification model proposed {label!r} for '
            f'{covered} posting(s) whose family was unknown, and the owner made it '
            f'the {total}th family. Proposed, not ESCO-backed: confirming the code '
            'is the CAREER-29 route.')

    new_families = _insert_family(families_text, code=code, label=label, label_de=label_de,
                                  isco4=isco4, isco3=isco3, note=note)
    new_seed = _insert_seed(seed_text, code=code, label=label, label_de=label_de, isco4=isco4)
    # The version and the date move with the list: a stored record says
    # which taxonomy it was classified against, and this changes it.
    version = families_document['taxonomy_version']
    major, minor, patch = (int(part) for part in version.split('.'))
    new_families = new_families.replace(
        f'taxonomy_version: "{version}"', f'taxonomy_version: "{major}.{minor + 1}.0"', 1)
    new_families = re.sub(r'^changed_at: "[\d-]+"', f'changed_at: "{today}"',
                          new_families, count=1, flags=re.M)

    new_taxonomy_tests = _bump_pins(taxonomy_tests_path.read_text(), [
        (r'(assert len\(codes\) == )\d+', total),
        (r'(assert len\(set\(codes\)\) == )\d+', total),
        (r'(assert len\(statuses\) == )\d+', total),
        (r"(statuses\.count\('proposed'\) == )\d+", proposed),
        (r'(assert len\(without_isco4\) == )\d+', without_isco4),
        (r'(assert len\(families\) == )\d+', total),
        (r"(if entry\['isco3'\]\) == )\d+", total),
    ], taxonomy_tests_path)
    new_facet_tests = _append_function_id(facet_tests_path.read_text(), code)
    new_facet_tests = _bump_pins(new_facet_tests, [
        (r'(assert len\(ids\) == )\d+', total),
    ], facet_tests_path)

    # Every edit applied; now write. A parse check first, because a
    # YAML file that loads is worth four regexes that looked right.
    yaml.safe_load(new_families)
    yaml.safe_load(new_seed)
    families_path.write_text(new_families)
    seed_path.write_text(new_seed)
    taxonomy_tests_path.write_text(new_taxonomy_tests)
    facet_tests_path.write_text(new_facet_tests)

    print(f'approved {label!r} as family {code!r} (isco3 {isco3}'
          + (f', isco4 {isco4}' if isco4 else '') + f'); {covered} posting(s) proposed it')
    print(f'wrote: {seed_path}\n       {families_path}\n'
          f'       {taxonomy_tests_path}\n       {facet_tests_path}')
    print('next: re-run only the unknown jobs --')
    print('  scripts/run_classification.py --pool ... --layer llm '
          '--previous <the run file the proposals came from> --out <new run file>')
    return covered


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)

    listed = sub.add_parser('list', help='every proposal, counted by distinct postings')
    listed.add_argument('--runs', default=str(REPO_ROOT / RUNS_DIR_REL),
                        help=f'run files to scan (default: {RUNS_DIR_REL})')

    approved = sub.add_parser('approve',
                              help='an approved proposal becomes a family in the taxonomy')
    approved.add_argument('name', help='the proposed role name, as the model wrote it')
    approved.add_argument('--code', required=True, help='the new family code (kebab-case)')
    approved.add_argument('--label-de', required=True, help='the German label')
    approved.add_argument('--isco3', required=True, help='the CH-ISCO-19 minor group (3 digits)')
    approved.add_argument('--isco4', help='an ISCO-08 unit group (4 digits), if known')
    approved.add_argument('--root', help='repository root to write into (tests use a copy)')

    args = parser.parse_args(argv)
    if args.command == 'list':
        report(collect(args.runs))
        return 0
    approve(args.name, code=args.code, label_de=args.label_de, isco3=args.isco3,
            isco4=args.isco4, root=args.root)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
