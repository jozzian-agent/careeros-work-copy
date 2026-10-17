"""The size-review report (CAREER-55/D3): that it finds the companies the
new BFS boundaries would reclassify, says so rather than guessing when the
record kept only a bucket, marks an owner-set class, and writes nothing."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import flag_size_review as report  # noqa: E402

from careeros import vault


def company(identifier, **fields):
    return {'id': identifier} | fields


def test_a_boundary_count_is_reported_as_a_change():
    """The off-by-one D3 fixes: a 10-person company was micro under the
    old inclusive thresholds and is small under the BFS ones."""
    rows = report.plan([company('CO-001', size_class='micro',
                                enrichment={'employee_count': 10})])
    assert rows == [{'id': 'CO-001', 'size_class': 'micro', 'locked': False,
                     'action': report.CHANGE, 'count': 10, 'size_range': None,
                     'derived': 'small'}]


@pytest.mark.parametrize('count,stored,derived', [
    (10, 'micro', 'small'),
    (50, 'small', 'medium'),
    (250, 'medium', 'large'),
    (1500, 'large', 'xl'),  # the new class, not a boundary move
])
def test_every_moved_boundary_shows_up(count, stored, derived):
    rows = report.plan([company('CO-001', size_class=stored,
                                enrichment={'employee_count': count})])
    assert (rows[0]['action'], rows[0]['derived']) == (report.CHANGE, derived)


def test_a_class_the_count_still_agrees_with_is_reported_as_unchanged():
    """"Checked and unchanged" is a different answer from "could not
    check", so it is a row and not a silence."""
    rows = report.plan([company('CO-001', size_class='medium',
                                enrichment={'employee_count': 120})])
    assert rows[0]['action'] == report.SAME


def test_a_legacy_bucket_alone_is_indeterminate_rather_than_guessed():
    """'1-10' spans micro and small under the new boundaries, so the class
    it implies depends on the count the bucket replaced. Guessing would
    report a change that may not exist."""
    rows = report.plan([company('CO-001', size_class='micro', size_range='1-10')])
    assert rows[0]['action'] == report.INDETERMINATE
    assert rows[0]['derived'] is None


def test_a_company_with_a_class_and_no_evidence_is_not_a_row():
    assert report.plan([company('CO-001', size_class='large')]) == []


def test_a_company_with_no_stored_class_is_not_a_row():
    """There is no stored value to change, whatever the count says."""
    assert report.plan([company('CO-001', enrichment={'employee_count': 10})]) == []


def test_an_owner_set_class_is_marked_and_still_reported():
    rows = report.plan([company('CO-001', size_class='micro',
                                enrichment={'employee_count': 10},
                                field_provenance={'size_class': 'user'})])
    assert rows[0]['locked'] is True and rows[0]['action'] == report.CHANGE
    assert '[owner-set]' in report.describe(rows[0])


def test_a_range_shaped_count_resolves_the_way_a_classification_would():
    """Read through the capability's own parser, so "50-100" means here
    what it means when a class is derived from it (upper bound)."""
    rows = report.plan([company('CO-001', size_class='small',
                                enrichment={'employee_count': '50-100'})])
    assert rows[0]['count'] == 100 and rows[0]['derived'] == 'medium'


def test_a_top_level_count_on_an_older_record_is_read_too():
    rows = report.plan([company('CO-001', size_class='micro', employee_count=10)])
    assert rows[0]['action'] == report.CHANGE


def test_the_report_writes_nothing(tmp_path, capsys):
    """The whole point of the script: a run over a real vault leaves every
    byte of it alone."""
    vault.save_company(tmp_path, {'name': 'Boundary Co', 'size_class': 'micro',
                                  'enrichment': {'employee_count': 10}})
    vault.save_company(tmp_path, {'name': 'Settled Co', 'size_class': 'medium',
                                  'enrichment': {'employee_count': 120}})
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    report.main(['--vault', str(tmp_path)])
    assert {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()} == before
    out = capsys.readouterr().out
    assert 'would be' in out and '1 would change class' in out
    assert 'REPORT ONLY' in out


def test_a_path_that_is_not_a_vault_is_refused():
    with pytest.raises(SystemExit, match='does not look like a CareerOS vault'):
        report.main(['--vault', '/tmp'])
