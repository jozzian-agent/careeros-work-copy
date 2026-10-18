"""Grading the pipeline against the golden set, and against the feeds.

CAREER-57's accuracy deliverable. Two measurements, kept apart because
they are not the same kind of evidence and presenting them as one would
be the most expensive kind of dishonesty here:

  * **Accuracy** against golden set v1 -- 42 postings a person labelled
    by hand, with a confidence per row. This is the only thing that can
    settle a gate-1 threshold. Golden set v1 carries ONE labelled
    dimension: the job function with its ISCO-08 unit group. It carries
    no language and no workload label, so those two thresholds cannot be
    graded against it at all, and `accuracy` says so rather than
    quietly reporting something else under their name.
  * **Agreement** with the feed-stated values over the pool export. An
    ATS that states a contract type is evidence, not ground truth, and
    where the feed's own value came from the SAME shared reader this
    layer calls (`base.pensum` for workload), agreement measures nothing
    at all. `agreement` splits those rows out and labels them.

## Known-bad rows

The golden set was labelled with model assistance and every row carries
the labeller's confidence. PROJECT.md scores "rows at or below ~35%
confidence" separately, so `accuracy` reports three numbers per
dimension: all rows, the confident rows, and the low-confidence rows on
their own. The headline is the confident set, and the full set is beside
it, because dropping rows from a denominator is how a gate gets passed
without the product improving.

## What counts as right

A golden row with no ISCO group is `unclassifiable` ("Careers and jobs"
is a careers page, not a posting), and the pipeline answering `unknown`
for it is CORRECT: refusing to classify a non-posting is the behaviour,
not a miss.

A family the taxonomy leaves unmapped (the five local extensions whose
ESCO URIs 404) can never produce a four-digit code, by decision 22. A
row whose gold family is one of those is counted in its own **unmapped
bucket** at the ISCO level -- decision 25's own word -- and still graded
normally at the family level, where it can be right or wrong like any
other.
"""
import csv
from pathlib import Path

from careeros import taxonomy
from careeros.classify import rules

#: PROJECT.md: "rows at or below ~35% confidence are scored separately".
LOW_CONFIDENCE = 0.35

#: The golden set's own word for a row that is not a job posting.
UNCLASSIFIABLE = 'unclassifiable'

#: The columns golden set v1 ships, so a different file is refused with
#: a readable message instead of producing empty labels.
COLUMNS = ('Job title', 'Company', 'Job function (fill in)', 'ISCO-08 group', 'Confidence')

#: Which dimensions the golden set can grade. The gate names three; this
#: is the one the file carries labels for, and `missing_dimensions` is
#: the other two.
GRADED = ('occupation_family', 'isco_unit_group')
GATE = {'isco_unit_group': 0.85, 'language': 0.95, 'workload': 0.95}


def _family_by_label():
    return {entry['label'].strip().casefold(): entry['code']
            for entry in taxonomy.entries('occupation_family')}


def load_golden(path):
    """Golden set v1 as rows this module grades.

    Returns `[{title, company, family, isco, confidence, low_confidence}]`.
    A label the taxonomy has no family for is kept with `family: None`
    and reported, never silently dropped: a label nothing matches is a
    finding about the vocabulary.
    """
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in COLUMNS if column not in (reader.fieldnames or ())]
        if missing:
            raise ValueError(f"{path} is not a golden set v1 file: no column(s) "
                             f"{', '.join(missing)}")
        families = _family_by_label()
        rows = []
        for row in reader:
            label = (row['Job function (fill in)'] or '').strip()
            isco = (row['ISCO-08 group'] or '').strip()
            confidence = _percent(row['Confidence'])
            rows.append({
                'title': (row['Job title'] or '').strip(),
                'company': (row['Company'] or '').strip(),
                'label': label,
                'family': (taxonomy.UNKNOWN if label.casefold() == UNCLASSIFIABLE
                           else families.get(label.casefold())),
                'isco': isco or taxonomy.UNKNOWN,
                'confidence': confidence,
                'low_confidence': confidence is not None and confidence <= LOW_CONFIDENCE,
            })
    return rows


def _percent(text):
    body = str(text or '').strip().rstrip('%')
    try:
        return float(body) / 100
    except ValueError:
        return None


def unmapped_families():
    """The families that carry no ISCO code, so no four-digit grade is
    possible for a row labelled with one (decisions 22 and 25)."""
    return frozenset(entry['code'] for entry in taxonomy.entries('occupation_family')
                     if not entry.get('isco4'))


def grade_row(row, result):
    """One golden row against one pipeline result.

    Returns `family_right` and `isco_right`, each `True`, `False` or
    None, where None means the row cannot be graded on that dimension at
    all. The keys are suffixed because a graded row is merged onto the
    golden row it came from, whose own `family` and `isco` are the
    labels -- two different facts that must not share a name.
    """
    values = result.get('values') or {}
    family = (values.get('occupation_family') or {}).get('value', taxonomy.UNKNOWN)
    isco = (values.get('isco_unit_group') or {}).get('value', taxonomy.UNKNOWN)
    graded = {'family_right': None if row['family'] is None else family == row['family'],
              'predicted_family': family, 'predicted_isco': isco,
              'unmapped': row['family'] in unmapped_families()}
    graded['isco_right'] = None if graded['unmapped'] else isco == row['isco']
    return graded


def accuracy(rows, results):
    """Per-dimension accuracy over the golden set, three denominators.

    `rows` and `results` are parallel. Returns a mapping with one block
    per graded dimension, each carrying `all`, `confident` and
    `low_confidence` counts, plus the unmapped bucket and the rows no
    label could be read for.
    """
    graded = [grade_row(row, result) for row, result in zip(rows, results)]
    report = {'rows': len(rows), 'unlabelled': sum(1 for row in rows if row['family'] is None),
              'unmapped_bucket': sum(1 for item in graded if item['unmapped'])}
    for name in ('family_right', 'isco_right'):
        report[name.removesuffix('_right')] = {
            'all': _tally(rows, graded, name, lambda row: True),
            'confident': _tally(rows, graded, name, lambda row: not row['low_confidence']),
            'low_confidence': _tally(rows, graded, name, lambda row: row['low_confidence']),
        }
    report['detail'] = [dict(row, **item) for row, item in zip(rows, graded)]
    return report


def _tally(rows, graded, name, keep):
    pairs = [item[name] for row, item in zip(rows, graded) if keep(row) and item[name] is not None]
    right = sum(1 for value in pairs if value)
    return {'right': right, 'of': len(pairs),
            'share': (right / len(pairs)) if pairs else None}


def missing_dimensions():
    """The gate-1 dimensions golden set v1 carries no label for.

    Named rather than silently skipped: a report that lists two of three
    thresholds and says nothing about the third reads as though the third
    passed.
    """
    return tuple(name for name in GATE if name not in GRADED)


def meets(share, threshold):
    """Whether a measured share clears a gate threshold. None in means
    None out: not measured is not passed."""
    return None if share is None else share >= threshold


# --- agreement with the feeds ---------------------------------------------

#: Fields whose feed value is read by the SAME shared reader this
#: pipeline calls, so agreement on them is arithmetic and not evidence.
SHARED_READER = {'workload_min': 'feeds.base.pensum', 'workload_max': 'feeds.base.pensum',
                 'municipality': 'feeds.geocode', 'canton': 'feeds.geocode'}


def agreement(subjects, results, fields=rules.FIELDS):
    """How often the rules layer says what the feed said.

    Only rows where the feed stated a real value are counted: a feed
    `unknown` is the feed declining to answer, and counting the rules
    layer's answer against it would measure coverage and call it
    accuracy. `shared_reader` names the fields where the comparison is
    not independent at all.
    """
    table = {}
    for field in fields:
        same = different = 0
        rules_unknown = 0
        for subject, result in zip(subjects, results):
            stated = (subject.get('values') or {}).get(field)
            if not stated or stated['value'] == taxonomy.UNKNOWN or stated['source'] != 'feed':
                continue
            answer = _rules_answer(result, field)
            if answer is None or answer == taxonomy.UNKNOWN:
                rules_unknown += 1
                continue
            if answer == stated['value']:
                same += 1
            else:
                different += 1
        compared = same + different
        table[field] = {'agree': same, 'disagree': different, 'compared': compared,
                        'rules_said_unknown': rules_unknown,
                        'share': (same / compared) if compared else None,
                        'shared_reader': SHARED_READER.get(field)}
    return table


def _rules_answer(result, field):
    """What the rules layer itself said, independent of what won the
    merge. `rules_only` is put on the result by the report runner."""
    record = (result.get('rules_only') or result.get('values') or {}).get(field)
    return record['value'] if record else None
