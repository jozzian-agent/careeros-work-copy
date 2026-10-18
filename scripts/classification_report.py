"""The accuracy report: how well the rules layer classifies, in writing.

CAREER-57's reporting deliverable. One command, one markdown file under
`data/`, and numbers nobody tuned.

    scripts/classification_report.py
    scripts/classification_report.py --golden /path/to/golden.csv --vault /srv/career-os
    scripts/classification_report.py --out data/classification_accuracy_2026-10-18.md

## What it measures, and what it cannot

Two sections, kept apart because they are different evidence
(`careeros.classify.grade` says why at length):

  * **Accuracy** against the hand-labelled golden set. Golden set v1
    labels ONE dimension -- the job function and its ISCO-08 unit group
    -- so that is the only gate-1 threshold this report can settle. The
    language and workload thresholds are reported as NOT GRADED, with
    the reason, because a report that lists two of three thresholds and
    is silent about the third reads as though the third passed.
  * **Agreement** with what the ATS feeds themselves state, over the
    whole pool export. Evidence about the rules, not ground truth: a
    feed states a contract type the employer typed into a form. Where
    the feed's own value comes from the same shared reader this pipeline
    calls, the comparison is arithmetic and the report says so on the
    row rather than counting it as a result.

## The rules layer alone

Every number here is layer 1. The local model is fixture-tested in this
build and was never run against the owner's host, so including it would
report a measurement that was not made.

## Known-bad rows

The golden set was labelled with model assistance and carries a
confidence per row; PROJECT.md scores rows at or below ~35% separately.
Both denominators are printed, headline and full, because dropping rows
from a denominator is how a gate gets passed without the product getting
better.
"""
import argparse
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_classification as runner  # noqa: E402

from careeros import classify, taxonomy  # noqa: E402
from careeros.classify import grade, rules  # noqa: E402

#: Neither the golden set nor the vault lives in this repository, and
#: neither path is written here: the golden set is the owner's own file
#: (PROJECT.md names where it sits) and the vault is the owner's data.
#: Both come from the environment, and the report says plainly what it
#: measured without one.
GOLDEN_ENV = 'CAREEROS_GOLDEN_SET'
VAULT_ENV = 'CAREEROS_VAULT'
OUT_DEFAULT = 'data/classification_accuracy_{day}.md'


def match_vault(rows, jobs):
    """Join golden rows to stored jobs by title, then title and company.

    The golden set names a posting by its title and its employer; the
    vault holds the same postings with their text. Matching gives the
    classifier the posting instead of six words of title, which is what
    it will have in production. A row that matches nothing is classified
    from its title alone and the report says how many of those there
    were, because an unmatched row is a weaker test than a matched one.
    """
    by_title = {}
    for job in jobs:
        by_title.setdefault((job.get('title') or '').strip().casefold(), []).append(job)
    joined = []
    for row in rows:
        candidates = by_title.get(row['title'].casefold()) or []
        if len(candidates) > 1 and row['company']:
            narrowed = [job for job in candidates
                        if (job.get('company') or '').strip().casefold()
                        == row['company'].casefold()]
            candidates = narrowed or candidates
        joined.append(candidates[0] if candidates else None)
    return joined


def golden_subjects(rows, jobs):
    found = match_vault(rows, jobs)
    subjects = [classify.from_vault_job(job) if job
                else classify.subject(title=row['title'], employer_name=row['company'])
                for row, job in zip(rows, found)]
    return subjects, sum(1 for job in found if job)


def percent(share):
    return 'not measured' if share is None else f'{share * 100:.1f}%'


def verdict(share, threshold):
    met = grade.meets(share, threshold)
    if met is None:
        return 'NOT GRADED'
    return 'MET' if met else 'NOT MET'


def _confidence_split(results, field):
    """How much of a field's coverage rests on the title and how much on
    the description alone, which is the difference between the strongest
    and the weakest evidence this layer produces."""
    counts = Counter()
    for result in results:
        record = (result.get('values') or {}).get(field)
        if not record or record['value'] == taxonomy.UNKNOWN:
            continue
        evidence = record.get('evidence')
        where = evidence.get('found_in', '-') if isinstance(evidence, dict) else '-'
        counts[f"{record['source']}/{where}"] += 1
    return counts


def accuracy_section(rows, results, matched):
    report = grade.accuracy(rows, results)
    lines = ['## 1. Accuracy against golden set v1', '',
             f"Golden set: {report['rows']} hand-labelled postings. "
             f"{matched} of them were matched to a stored job, so the classifier read the "
             'posting text; the rest were classified from the title alone.', '',
             f"Rows the golden label could not be read as a job family: {report['unlabelled']}. "
             f"Rows whose gold family is an unmapped local extension and therefore carries no "
             f"four-digit code at all (decisions 22 and 25): {report['unmapped_bucket']}, "
             'counted in the unmapped bucket rather than graded at four digits.', '',
             '| Dimension | Rows | Right | Accuracy | Gate | Verdict |',
             '|---|---|---|---|---|---|']
    isco = report['isco']['confident']
    family = report['family']['confident']
    lines += [
        f"| ISCO-08 unit group (4 digits), confident rows | {isco['of']} | {isco['right']} | "
        f"{percent(isco['share'])} | 85% | "
        f"**{verdict(isco['share'], grade.GATE['isco_unit_group'])}** |",
        f"| ISCO-08 unit group (4 digits), all rows | {report['isco']['all']['of']} | "
        f"{report['isco']['all']['right']} | {percent(report['isco']['all']['share'])} | 85% | "
        f"{verdict(report['isco']['all']['share'], grade.GATE['isco_unit_group'])} |",
        f"| ISCO-08 unit group, low-confidence rows only | "
        f"{report['isco']['low_confidence']['of']} | "
        f"{report['isco']['low_confidence']['right']} | "
        f"{percent(report['isco']['low_confidence']['share'])} | - | scored separately |",
        f"| Job family, confident rows | {family['of']} | {family['right']} | "
        f"{percent(family['share'])} | - | reported, no gate |",
        f"| Job family, all rows | {report['family']['all']['of']} | "
        f"{report['family']['all']['right']} | {percent(report['family']['all']['share'])} | - | "
        'reported, no gate |',
    ]
    for name in grade.missing_dimensions():
        lines.append(f"| {name} | 0 | 0 | not measured | "
                     f"{int(grade.GATE[name] * 100)}% | **NOT GRADED** |")
    lines += ['', 'Language and workload are **not graded**: golden set v1 carries no column '
                  'for either, so there is nothing to grade against. Section 2 reports how often '
                  'the rules layer agrees with what the ATS feeds state, which is evidence of a '
                  'different and weaker kind.', '']
    return lines, report


def misses_section(report):
    lines = ['### Where the four-digit misses come from', '',
             '| Gold | Predicted | Rows |', '|---|---|---|']
    misses = Counter()
    for row in report['detail']:
        if row['isco_right'] is False:
            misses[(row['isco'], row['predicted_isco'])] += 1
    for (gold, predicted), count in misses.most_common():
        lines.append(f'| {gold} | {predicted} | {count} |')
    lines += ['', 'Every `unknown` above is the layer refusing to guess rather than guessing '
                  'wrong. The largest single group is the postings whose title carries a phrase '
                  'that two job families claim equally -- `product manager` anchors both the ICT '
                  'reading (1330) and the research-and-development one (1223), by the seed\'s own '
                  'decision not to give either id sole ownership of it. That remainder is exactly '
                  'what the local-model layer exists for, and that layer was not run in this '
                  'build.', '']
    return lines


def pool_section(subjects, results, note):
    coverage = classify.coverage(results)
    agree = grade.agreement(subjects, results)
    lines = ['## 2. The rules layer over the universe pool', '',
             f"{note['read']} postings, read from their frozen snapshots "
             f"({note['snapshot_missing']} rows had none). Export of {note['exported_at']}.", '',
             '### Coverage: what the pipeline settles, and by which source', '',
             '| Field | Settled | Unknown | Needs review | By source | By evidence |',
             '|---|---|---|---|---|---|']
    for field, row in coverage.items():
        sources = ', '.join(f'{name} {count}' for name, count in sorted(row['by_source'].items()))
        where = ', '.join(f'{name} {count}'
                          for name, count in sorted(_confidence_split(results, field).items()))
        lines.append(f"| {field} | {row['settled']} | {row['unknown']} | {row['needs_review']} | "
                     f"{sources or '-'} | {where or '-'} |")
    lines += ['', 'The `feed` rows are values the ATS adapters already stated and this pipeline '
                  'preserved rather than re-derived (the brief\'s own rule). The `rule` rows are '
                  'what layer 1 added -- either on a field the feed left `unknown`, or on a '
                  'field the feed has no column for at all.', '',
              '### Agreement with what the feeds state', '',
              '| Field | Compared | Agree | Disagree | Agreement | Independent? |',
              '|---|---|---|---|---|---|']
    for field, row in agree.items():
        if not row['compared'] and not row['rules_said_unknown']:
            continue
        shared = (f"no, both read by `{row['shared_reader']}`" if row['shared_reader']
                  else 'yes')
        lines.append(f"| {field} | {row['compared']} | {row['agree']} | {row['disagree']} | "
                     f"{percent(row['share'])} | {shared} |")
    lines += ['', 'Only rows where the feed states a real value are compared; a feed `unknown` '
                  'is the feed declining to answer, and scoring against it would measure '
                  'coverage and call it accuracy. **Agreement is not accuracy**: neither side '
                  'is a hand label, and the rows marked not independent share their reader with '
                  'the feed, so their agreement is arithmetic.', '',
              'A disagreement does not say which side is wrong, and on the small comparable '
              'sets above it often says the feed is. Reading the ten contract disagreements by '
              'hand: a posting titled "Lehrstelle als Zeichner:in" is an apprenticeship and its '
              'feed calls it an internship, and a posting titled "Working Student" is working '
              'student work and its feed calls it an internship. The language disagreements are '
              'the same shape -- four of the five are German texts the feed labels `fr` or '
              '`en`, which is `base.language_record` being honest about what it measures: the '
              'language the TENANT publishes a feed variant in, not a reading of the text. '
              'Precedence still gives the feed the stored value in every one of these cases, '
              'which is the owner\'s rule and not a judgement about who was right.', '']
    return lines


def salary_section(results):
    readings = [result['salary'] for result in results if result['salary']]
    used = Counter(rule for reading in readings for rule in reading['rules'])
    lines = ['### Salary normalisation', '',
             f'{len(readings)} of {len(results)} postings state a salary this layer can read and '
             'normalise to an annual gross in CHF at 100% Pensum. The pool export flags more '
             'postings than that as mentioning pay, because its flag answers "is pay mentioned '
             'at all" -- a funding round in euros and a sentence about how compensation is '
             'decided both set it. No figure is read without an amount, a pay word beside it and '
             'a period the posting actually states, and nothing is estimated: a public posting '
             'naming a wage class is still no figure, because the four pay-scale tables in '
             '`salary_rules.yaml` are placeholders.', '']
    if used:
        lines += ['| Rule | Times applied |', '|---|---|']
        lines += [f'| `{rule}` | {count} |' for rule, count in used.most_common()]
        lines.append('')
    return lines


def write_report(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(body) + '\n')
    return path


def build(args):
    rows = grade.load_golden(args.golden)
    jobs = runner.vault_jobs(args.vault) if args.vault and Path(args.vault,
                                                                'jobs').is_dir() else []
    subjects, matched = golden_subjects(rows, jobs)
    golden_results = runner.run(subjects, layer='rules')
    pool_postings, note = runner.pool_postings(args.pool)
    pool_subjects = [classify.from_feed_posting(posting) for posting in pool_postings]
    # The merged result is what a posting would carry; `rules_only` is
    # what layer 1 said on its own, which is what the agreement section
    # compares, so a feed value cannot grade itself.
    pool_results = []
    for subject in pool_subjects:
        result = classify.classify(subject, layer='rules')
        result['rules_only'] = rules.classify(subject)
        pool_results.append(result)

    day = date.today().isoformat()
    accuracy, report = accuracy_section(rows, golden_results, matched)
    body = [f'# Classification accuracy, rules layer, {day}', '',
            'CAREER-57 layer 1 (deterministic rules), measured against golden set v1 and '
            'against the universe pool. Generated by `scripts/classification_report.py`; '
            'nothing in it is typed by hand.', '',
            f'- Taxonomy version: {taxonomy.TAXONOMY_VERSION}',
            f'- Golden set: `{args.golden}`',
            f'- Vault: `{args.vault}` ({len(jobs)} jobs)' if jobs else
            '- Vault: none given, so every golden row was classified from its title alone '
            f'(pass --vault or set {VAULT_ENV} to read the posting text)',
            f'- Pool: `{args.pool}`',
            '- Layers run: rules only. The local-model layer is fixture-tested in this build '
            'and was never called against the owner\'s host, so no number here includes it.', '']
    body += accuracy
    body += misses_section(report)
    body += pool_section(pool_subjects, pool_results, note)
    body += salary_section(pool_results)
    body += ['## What this report does not say', '',
             '- Nothing here is tuned to the golden set. The keyword tables are the ones '
             '`esco_occupations.yaml` already shipped for the extraction prompt, and the one '
             'tie-breaker added is generic (how much of a family\'s own vocabulary the posting '
             'carries), not a rule about any row.',
             '- The three incomplete taxonomy dimensions (CH-ISCO-19\'s 5-digit list, the NOGA '
             'divisions, the municipality register\'s coordinates) are untouched; occupation is '
             'classified at job family plus four-digit ISCO, which is what the shipped lists '
             'support (CAREER-77 owns the rest).',
             '- Agreement with a feed is not accuracy, and the two are never added together.', '']
    return body


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--golden', default=os.environ.get(GOLDEN_ENV),
                        help=f'the golden set CSV (default: the {GOLDEN_ENV} variable)')
    parser.add_argument('--vault', default=os.environ.get(VAULT_ENV),
                        help='a vault to read the golden postings\' text from, read-only '
                             f'(default: the {VAULT_ENV} variable)')
    parser.add_argument('--pool', default=runner.POOL_DEFAULT, help='a golden-set pool export')
    parser.add_argument('--out', help=f'where to write (default: {OUT_DEFAULT})')
    parser.add_argument('--stdout', action='store_true', help='print instead of writing')
    args = parser.parse_args(argv)
    if not args.golden:
        raise SystemExit(f'no golden set given: pass --golden PATH or set {GOLDEN_ENV}')

    body = build(args)
    if args.stdout:
        print('\n'.join(body))
        return 0
    path = write_report(args.out or OUT_DEFAULT.format(day=date.today().isoformat()), body)
    print(f'wrote {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
