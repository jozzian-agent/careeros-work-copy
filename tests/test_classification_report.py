"""The accuracy report (CAREER-57): that a golden set is graded against
the labels it actually carries, that a dimension it does not label is
reported as not graded rather than quietly skipped, that low-confidence
rows are scored separately, and that agreement with a feed is never
presented as accuracy."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import classification_report as report  # noqa: E402
import run_classification as runner  # noqa: E402

from careeros import classify, taxonomy  # noqa: E402
from careeros.classify import grade, rules  # noqa: E402

HEADER = 'Job title,Company,Board status,Job function (fill in),ESCO URI,ISCO-08 group,Confidence,Runner-up,Note\n'

ROWS = [
    'Senior Java-Entwickler/in,Ringler,new,Software developer,,2512,90%,,',
    # A family that carries no four-digit code, so the row lands in the
    # unmapped bucket. It was "Chief product officer" until v2 merged that
    # family into product-manager, which does carry one.
    'Projektleiter Digitales Ökosystem,Fiction AG,new,Digital transformation manager,,,60%,,',
    'Careers and jobs,Syngenta,new,unclassifiable,,,5%,,',
    'Product Manager TMS,Maagtechnic,new,Product manager,,1223,25%,,',
]


@pytest.fixture
def golden(tmp_path):
    path = tmp_path / 'golden.csv'
    path.write_text(HEADER + '\n'.join(ROWS) + '\n', encoding='utf-8')
    return path


# --- reading the golden set ----------------------------------------------

def test_the_rows_carry_their_label_their_code_and_their_confidence(golden):
    rows = grade.load_golden(golden)
    assert len(rows) == 4
    assert rows[0]['family'] == 'software-developer'
    assert rows[0]['isco'] == '2512'
    assert rows[0]['confidence'] == 0.9


def test_an_unclassifiable_row_labels_the_unknown_value(golden):
    """"Careers and jobs" is a careers page, not a posting. The
    pipeline answering `unknown` for it is the behaviour, not a miss."""
    rows = grade.load_golden(golden)
    assert rows[2]['family'] == taxonomy.UNKNOWN
    assert rows[2]['isco'] == taxonomy.UNKNOWN


def test_a_low_confidence_row_is_marked_as_one(golden):
    """PROJECT.md: rows at or below ~35% confidence are scored
    separately."""
    rows = grade.load_golden(golden)
    assert [row['low_confidence'] for row in rows] == [False, False, True, True]


def test_a_file_that_is_not_a_golden_set_is_refused(tmp_path):
    path = tmp_path / 'other.csv'
    path.write_text('a,b\n1,2\n')
    with pytest.raises(ValueError, match='not a golden set'):
        grade.load_golden(path)


# --- grading --------------------------------------------------------------

def results_for(rows):
    """One classified result per golden row.

    Since CAREER-138 the rules layer never settles the family, so the
    family these results carry is an `llm`-sourced record of the row's
    OWN label -- the grading logic under test (top-1 vs top-3, the
    unmapped bucket, the denominators) is about how a settled answer is
    compared, not about which layer produced it.
    """
    return [{'values': {'occupation_family': taxonomy.make_value_record(
                 'occupation_family', row['family'] or taxonomy.UNKNOWN, 'llm'),
             'isco_unit_group': (rules.derive_isco(taxonomy.make_value_record(
                 'occupation_family', row['family'], 'llm')) if row['family']
                 and row['family'] != taxonomy.UNKNOWN else None)}}
            for row in rows]


def test_a_right_answer_counts_on_both_dimensions(golden):
    rows = grade.load_golden(golden)
    graded = grade.grade_row(rows[0], results_for(rows)[0])
    assert (graded['family_right'], graded['isco_right']) == (True, True)


def test_refusing_to_classify_a_non_posting_is_correct(golden):
    rows = grade.load_golden(golden)
    graded = grade.grade_row(rows[2], results_for(rows)[2])
    assert (graded['predicted_family'], graded['family_right']) == (taxonomy.UNKNOWN, True)


def test_an_unmapped_local_extension_is_bucketed_not_graded_at_four_digits(golden):
    """Decision 22 scopes the ISCO roll-up to ESCO-backed entries, so a
    row labelled `digital transformation manager` can never produce a
    code."""
    rows = grade.load_golden(golden)
    graded = grade.grade_row(rows[1], results_for(rows)[1])
    assert graded['unmapped'] is True
    assert graded['isco_right'] is None


def test_the_three_denominators_are_reported_separately(golden):
    rows = grade.load_golden(golden)
    summary = grade.accuracy(rows, results_for(rows))
    assert summary['rows'] == 4
    assert summary['family']['confident']['of'] + summary['family']['low_confidence']['of'] \
        == summary['family']['all']['of']
    assert summary['unmapped_bucket'] == 1


# --- top-1 and top-3 (CAREER-129) ----------------------------------------

def ranked_result(*codes):
    """A pipeline result whose family record carries ranked alternatives."""
    return {'values': {'occupation_family': taxonomy.make_value_record(
        'occupation_family', codes[0], 'llm',
        ranked=[{'value': code, 'rank': position, 'source': 'llm', 'confidence': None}
                for position, code in enumerate(codes, start=1)])}}


def test_the_owners_family_at_rank_two_is_a_top_3_hit_and_a_top_1_miss(golden):
    """Which is the whole reason both are reported: a wider answer must
    not be readable as a better one."""
    rows = grade.load_golden(golden)  # rows[0] is labelled software-developer
    graded = grade.grade_row(rows[0], ranked_result('software-architect',
                                                    'software-developer'))
    assert graded['family_right'] is False
    assert graded['family_top3_right'] is True
    assert graded['predicted_ranked'] == ['software-architect', 'software-developer']


def test_a_family_in_no_rank_is_wrong_at_both(golden):
    rows = grade.load_golden(golden)
    graded = grade.grade_row(rows[0], ranked_result('marketing-manager', 'sales-manager'))
    assert graded['family_right'] is False and graded['family_top3_right'] is False


def test_a_record_with_no_ranked_list_scores_the_same_at_top_1_and_top_3(golden):
    """Everything written before CAREER-129, and everything the rules
    layer writes, carries one rank."""
    rows = grade.load_golden(golden)
    graded = grade.grade_row(rows[0], results_for(rows)[0])
    assert graded['family_right'] is True and graded['family_top3_right'] is True


def test_the_two_family_rates_are_separate_blocks_of_the_report(golden):
    rows = grade.load_golden(golden)
    results = [ranked_result('software-architect', 'software-developer')] + \
        results_for(rows)[1:]
    summary = grade.accuracy(rows, results)
    assert summary['family_top3']['all']['right'] == summary['family']['all']['right'] + 1
    assert summary['family']['confident']['of'] == summary['family_top3']['confident']['of']


def test_a_dimension_the_golden_set_does_not_label_is_not_graded():
    """A report listing two of three thresholds and silent about the
    third reads as though the third passed."""
    assert set(grade.missing_dimensions()) == {'language', 'workload'}
    assert grade.meets(None, 0.95) is None
    assert report.verdict(None, 0.95) == 'NOT GRADED'


@pytest.mark.parametrize('share,expected', [(0.9, 'MET'), (0.5, 'NOT MET'), (None, 'NOT GRADED')])
def test_a_threshold_verdict_says_exactly_one_of_three_things(share, expected):
    assert report.verdict(share, 0.85) == expected


# --- agreement is not accuracy -------------------------------------------

def feed_subject(title, **stated):
    values = {field: taxonomy.make_value_record(
        field.replace('_min', '').replace('_max', ''), code, 'feed')
        for field, code in stated.items()}
    return classify.subject(title=title, values=values)


def test_only_rows_where_the_feed_stated_a_value_are_compared():
    subjects = [feed_subject('Praktikum Marketing 100%', contract='internship'),
                feed_subject('Praktikum Marketing 100%', contract=taxonomy.UNKNOWN)]
    results = [{'rules_only': classify.rules.classify(subject)} for subject in subjects]
    assert grade.agreement(subjects, results)['contract']['compared'] == 1


def test_a_field_whose_feed_value_shares_this_pipelines_reader_says_so():
    """Agreement there is arithmetic, not evidence."""
    table = grade.agreement([], [])
    assert table['workload_min']['shared_reader'] == 'feeds.base.pensum'
    assert table['contract']['shared_reader'] is None


def test_a_disagreement_is_counted_and_not_resolved():
    subjects = [feed_subject('Lehrstelle als Zeichner:in', contract='internship')]
    results = [{'rules_only': classify.rules.classify(subjects[0])}]
    row = grade.agreement(subjects, results)['contract']
    assert (row['agree'], row['disagree']) == (0, 1)


# --- the whole report -----------------------------------------------------

@pytest.fixture
def pool(tmp_path):
    """A one-posting pool export with its snapshot beside it, which is
    the shape `run_classification.pool_postings` reads."""
    store = tmp_path / 'fixture'
    posting = {'provider': 'fixture', 'tenant': 'Acme', 'posting_id': 'p1',
               'key': 'fixture:Acme:p1', 'content_hash': 'abc', 'title': 'Praktikum 100%',
               'description': 'Wir bieten ein Praktikum in Zürich an.',
               'offices': ['8001 Zürich'],
               'values': {'contract': taxonomy.make_value_record(
                   'contract', taxonomy.UNKNOWN, 'feed')}}
    path = store / 'snapshots' / 'postings' / 'Acme' / 'p1' / 'abc.yaml'
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({'posting': posting}, allow_unicode=True))
    export = tmp_path / 'pool.yaml'
    export.write_text(yaml.safe_dump(
        {'stores': ['fixture'], 'exported_at': '2026-10-18T00:00:00+00:00',
         'postings': [{'provider': 'fixture', 'tenant': 'Acme', 'posting_id': 'p1',
                       'content_hash': 'abc'}]}, allow_unicode=True))
    return export, tmp_path


def test_a_pool_row_is_read_from_its_frozen_snapshot(pool, monkeypatch):
    export, root = pool
    monkeypatch.setattr(runner, '__file__', str(root / 'scripts' / 'x.py'))
    postings, note = runner.pool_postings(export)
    assert note['read'] == 1
    assert postings[0]['title'] == 'Praktikum 100%'


def test_the_report_writes_a_markdown_file_with_every_verdict_on_it(golden, pool, tmp_path,
                                                                    monkeypatch):
    export, root = pool
    monkeypatch.setattr(runner, '__file__', str(root / 'scripts' / 'x.py'))
    args = type('Args', (), {'golden': str(golden), 'vault': str(tmp_path / 'no-vault'),
                             'pool': str(export)})()
    body = report.build(args)
    text = '\n'.join(body)
    assert '# Classification accuracy, rules layer' in text
    assert 'NOT GRADED' in text
    # Top-1 and top-3 are two rows and never one (CAREER-129).
    assert 'Job family top-1, confident rows' in text
    assert 'Job family top-3, confident rows' in text
    assert 'Agreement is not accuracy' in text
    written = report.write_report(tmp_path / 'out.md', body)
    assert written.read_text().startswith('# Classification accuracy')
