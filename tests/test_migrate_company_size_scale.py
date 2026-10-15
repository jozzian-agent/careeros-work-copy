"""Protects scripts/migrate_company_size_scale.py: the class scale wins,
a dry run writes nothing, and a second run has nothing left to do.

Fixture-only vaults; the live owner vault is never touched by tests.
"""
import importlib.util
from pathlib import Path

import pytest

from careeros import vault
from tests.conftest import write_legacy_size_range

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'migrate_company_size_scale.py'


@pytest.fixture(scope='module')
def script():
    spec = importlib.util.spec_from_file_location('migrate_company_size_scale', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vault_root(tmp_path):
    """Four synthetic companies: a range with a class, a range with no
    class, a range holding no headcount, and one already on the scale.

    The three ranges are stamped onto the stored YAML, because a write no
    longer persists one (owner decision 2026-10-15), and a record this
    migration exists for is by definition one an older write left
    behind."""
    for kind in ('companies', 'jobs', 'experiences'):
        (tmp_path / kind).mkdir()
    for name, size_class, size_range in (
        ('Harbor Labs', 'small', '1000+'),
        ('Fern Robotics', None, '1000+'),
        ('Lantern Peak', None, 'lots of people'),
        ('Bluegrass Partners', 'medium', None),
    ):
        company = vault.save_company(tmp_path, {'name': name, 'size_class': size_class})
        if size_range:
            write_legacy_size_range(tmp_path, company['id'], size_range)
    return tmp_path


def stored(root):
    return {c['name']: (c.get('size_range'), c.get('size_class')) for c in vault.list_companies(root)}


# --- the headcount map ----------------------------------------------------

def test_a_range_maps_to_a_class_by_its_people(script):
    """The owner's conservative map: up to 50 small, up to 250 medium,
    above that large, judged by the range's upper bound (or its only
    bound when the range is open-ended)."""
    cases = {'1-10': 'small', '11-50': 'small', '51-250': 'medium',
             '251-500': 'large', '1000+': 'large', ' 1000+ ': 'large'}
    assert {value: script.size_class_for_range(value) for value in cases} == cases


def test_the_map_never_claims_the_smallest_class(script):
    """`micro` is in the class vocabulary but deliberately out of this
    map's reach: a stored range is a bucket, and calling a company micro
    off a bucket's lower edge would claim precision the range does not
    have. Pinned against the map itself, so adding a `(10, 'micro')` row
    fails here rather than silently relabelling records."""
    assert 'micro' in vault.SIZE_CLASSES
    assert 'micro' not in {label for _, label in script.SIZE_CLASS_BY_HEADCOUNT}
    buckets = ('1-10', '2-9', '1+', '10-49', '11-50', '51-250', '251-500', '1000+')
    assert 'micro' not in {script.size_class_for_range(value) for value in buckets}


def test_only_the_bucket_grammar_reads_as_a_headcount(script):
    """A stored range was free text when the writes that produced it still
    ran (they copied a legacy `size` string verbatim), so anything can
    reach the parser. Only the vault's own bucket labels are readable; every
    other shape is unreadable rather than a number to guess from, because
    guessing writes a wrong class AND clears the evidence.

    '10,000+' and '~12,000' used to parse as 0 and '10k+' as 10 -- all
    three recorded a five-figure company as `small`.
    """
    unreadable = ('10,000+', '1.000+', '10k+', '10K+', '~12,000', '0', '0+', '0-0',
                  'Fortune 500', '50', '1 000+', '51 - 250', '', 'lots of people', None)
    assert {value: script.headcount(value) for value in unreadable} == dict.fromkeys(unreadable)
    assert {value: script.size_class_for_range(value) for value in unreadable} == dict.fromkeys(unreadable)


# --- the plan -------------------------------------------------------------

def test_the_plan_keeps_the_class_and_derives_the_missing_one(script, vault_root):
    rows = {row['id']: row for row in script.plan(vault.list_companies(vault_root))}
    by_name = {c['name']: c['id'] for c in vault.list_companies(vault_root)}

    # A stored class wins over the range, even when the range says
    # otherwise: the class is what the owner and the UI go by.
    assert rows[by_name['Harbor Labs']]['action'] == script.CLEAR_RANGE
    assert rows[by_name['Harbor Labs']]['updates'] == {'size_range': None}
    assert rows[by_name['Fern Robotics']]['updates'] == {'size_class': 'large', 'size_range': None}
    assert rows[by_name['Lantern Peak']]['action'] == script.UNREADABLE
    assert rows[by_name['Lantern Peak']]['updates'] is None
    # A company already on the class scale is not a planned change at all.
    assert by_name['Bluegrass Partners'] not in rows


def test_a_range_outside_the_bucket_grammar_is_only_reported(script):
    """The plan-level shape of the parser rule: a thousands separator is
    reported and nothing about the record is touched -- deriving `small`
    from it and then clearing the range would lose the only record of a
    five-figure headcount."""
    rows = script.plan([{'id': 'CO-900', 'size_range': '10,000+'},
                        {'id': 'CO-901', 'size_range': 'Fortune 500'}])
    assert [row['action'] for row in rows] == [script.UNREADABLE, script.UNREADABLE]
    assert [row['updates'] for row in rows] == [None, None]


def test_provenance_follows_the_size_out_of_the_range(script):
    """A provenance entry describes where a stored value came from, so it
    cannot stay behind on a field this migration empties: the detail page
    would report the surviving class as owner-set, and the enrichment
    cascade would freeze the size pair."""
    cleared = script.plan([{'id': 'CO-902', 'size_range': '1000+', 'size_class': 'large',
                            'field_provenance': {'size_range': 'user', 'sectors': 'user'}}])[0]
    # The range is gone, so its entry goes with it -- and no other
    # field's provenance is disturbed.
    assert cleared['updates'] == {'size_range': None, 'field_provenance': {'sectors': 'user'}}

    derived = script.plan([{'id': 'CO-903', 'size_range': '51-250',
                            'field_provenance': {'size_range': 'user'}}])[0]
    # The derived class came from exactly that range, so the entry moves.
    assert derived['updates'] == {'size_class': 'medium', 'size_range': None,
                                  'field_provenance': {'size_class': 'user'}}

    # A record with no size provenance is not given one.
    silent = script.plan([{'id': 'CO-904', 'size_range': '51-250'}])[0]
    assert silent['updates'] == {'size_class': 'medium', 'size_range': None}


# --- dry run and apply ----------------------------------------------------

def test_a_dry_run_reports_and_writes_nothing(script, vault_root, capsys):
    before = stored(vault_root)
    script.main(['--vault', str(vault_root)])
    output = capsys.readouterr().out

    assert stored(vault_root) == before
    assert 'DRY RUN' in output
    assert 'nothing was written' in output
    assert 'Re-run with --apply' in output
    # The owner is told the YAML diff can be wider than the size change:
    # save_company rebuilds the record from the full schema, so an older
    # record also gains any key it is missing.
    assert 'vault.save_company' in output
    # The report names records by id, never by company name.
    assert not any(name in output for name in before)


def test_apply_leaves_every_company_on_the_class_scale(script, vault_root):
    script.main(['--vault', str(vault_root), '--apply'])
    assert stored(vault_root) == {
        'Harbor Labs': (None, 'small'),
        'Fern Robotics': (None, 'large'),
        # Nothing to derive a class from, so the range it does have stays.
        'Lantern Peak': ('lots of people', None),
        'Bluegrass Partners': (None, 'medium'),
    }


def test_a_second_apply_has_nothing_left_to_change(script, vault_root, capsys):
    script.main(['--vault', str(vault_root), '--apply'])
    after_first = stored(vault_root)
    capsys.readouterr()

    script.main(['--vault', str(vault_root), '--apply'])
    output = capsys.readouterr().out

    assert stored(vault_root) == after_first
    assert 'wrote 0 record(s)' in output


def test_the_legacy_free_text_size_is_reported_and_untouched(script, vault_root, capsys):
    # A pure legacy-size case: the legacy string is persisted as itself and
    # translated into no range at all.
    legacy = vault.save_company(vault_root, {'name': 'Old Shape', 'size': '200-500'})
    script.main(['--vault', str(vault_root), '--apply'])
    output = capsys.readouterr().out

    assert vault.load_company(vault_root, legacy['id'])['size'] == '200-500'
    assert vault.load_company(vault_root, legacy['id'])['size_range'] is None
    assert 'legacy free-text `size`' in output
    assert legacy['id'] in output


def test_apply_moves_a_hand_set_ranges_provenance_onto_the_class(script, vault_root):
    record = vault.save_company(vault_root, {'name': 'Cobalt Freight',
                                             'field_provenance': {'size_range': 'user'}})
    write_legacy_size_range(vault_root, record['id'], '51-250')
    script.main(['--vault', str(vault_root), '--apply'])

    written = vault.load_company(vault_root, record['id'])
    assert (written['size_class'], written['size_range']) == ('medium', None)
    assert written['field_provenance'] == {'size_class': 'user'}


def test_a_skipped_write_makes_the_run_fail(script, vault_root, monkeypatch, capsys):
    """A record whose write is refused prints to stderr; the run must also
    exit non-zero, or a partially applied sweep looks like a success to
    whatever wrapper called it."""
    def refuse(*args, **kwargs):
        raise ValueError('refused by validation')

    monkeypatch.setattr(script.vault, 'save_company', refuse)
    with pytest.raises(SystemExit) as failure:
        script.main(['--vault', str(vault_root), '--apply'])

    assert failure.value.code not in (0, None)
    assert 'wrote 0 record(s)' in capsys.readouterr().out


def test_a_vault_whose_only_findings_are_reports_is_not_told_to_apply(script, tmp_path, capsys):
    """--apply would write nothing here, so the footer must not offer it."""
    for kind in ('companies', 'jobs', 'experiences'):
        (tmp_path / kind).mkdir()
    company = vault.save_company(tmp_path, {'name': 'Lantern Peak'})
    write_legacy_size_range(tmp_path, company['id'], '10k+')
    script.main(['--vault', str(tmp_path)])
    output = capsys.readouterr().out

    assert 'LEFT AS IS' in output
    assert 'nothing was written' in output
    assert 'Re-run with --apply' not in output
    assert '--apply would write nothing' in output
    # Nothing writable, so the wider-YAML-diff warning is not raised either.
    assert 'vault.save_company' not in output


def test_a_vault_without_companies_is_refused(script, tmp_path):
    with pytest.raises(SystemExit):
        script.main(['--vault', str(tmp_path / 'nowhere')])
