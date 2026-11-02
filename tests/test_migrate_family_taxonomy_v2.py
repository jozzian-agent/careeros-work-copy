"""The v2 family migration (CAREER-129): that the three absorbed codes
are rewritten everywhere a vault holds one, that the registry entry is
removed only after the records that pointed at it are safe, that nothing
is written without --apply, and that a second run finds nothing to do.

Synthetic fixtures only. Every vault here is built in tmp_path from
invented postings; no real vault path appears in this file and none is
ever opened.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import migrate_family_taxonomy_v2 as migrate  # noqa: E402

from careeros import taxonomy, vault  # noqa: E402


@pytest.fixture
def root(tmp_path):
    """A vault with a seeded `function` facet and nothing else in it."""
    place = tmp_path / 'vault'
    (place / 'jobs').mkdir(parents=True)
    vault.save_tags(place, {'facets': {
        'function': {'label': 'Job function', 'values': [
            {'id': 'product-manager', 'label': 'Product manager'},
            {'id': 'chief-product-officer', 'label': 'Chief product officer',
             'source': 'local-extension'},
            {'id': 'ict-business-analyst', 'label': 'ICT business analyst'},
            {'id': 'ict-business-analysis-manager', 'label': 'ICT business analysis manager'},
            {'id': 'innovation-manager', 'label': 'Innovation manager'},
            {'id': 'innovation-officer', 'label': 'Innovation officer',
             'source': 'local-extension'},
        ]},
        'skill/capability': {'label': 'Capability', 'values': [{'id': 'python',
                                                                'label': 'Python'}]},
    }})
    return place


def write_job(root, identifier, **fields):
    path = Path(root) / 'jobs' / f'{identifier}.yaml'
    vault._write(path, {'id': identifier, 'title': 'A role', **fields})
    return path


def family_record(primary, *alternatives):
    """A D4 family record as a vault written under the v1 list holds one.

    Built by hand and not through `taxonomy.make_value_record`, because
    the factory refuses a code the shipped list does not carry -- and an
    absorbed code is exactly that now. Which is the point: what this
    migration rewrites is records no current writer could produce.
    """
    codes = (primary,) + alternatives
    return {'value': primary, 'source': 'llm', 'confidence': 0.95, 'evidence': None,
            'taxonomy_version': '1.0.0', 'standard_version': 'the v1 family list',
            'classified_at': '2026-10-21T00:00:00+00:00', 'flags': [], 'guide_version': None,
            'ranked': [{'value': code, 'rank': position, 'source': 'llm', 'confidence': None}
                       for position, code in enumerate(codes, start=1)]}


def stored(root, identifier):
    return vault._read(Path(root) / 'jobs' / f'{identifier}.yaml')


# --- the mapping itself ---------------------------------------------------

def test_the_absorbed_codes_are_gone_from_the_shipped_list_and_their_targets_are_not():
    """The guard that runs before a vault is opened: a mapping that
    disagrees with the shipped list would rewrite records onto a code
    nothing accepts, which is the breakage this script prevents."""
    for code, target in migrate.MERGED.items():
        assert not taxonomy.valid_code('occupation_family', code), code
        assert taxonomy.valid_code('occupation_family', target), target
    migrate.check_targets()  # raises SystemExit when either half is false


# --- what one record looks like afterwards -------------------------------

def test_the_facet_id_list_the_board_filters_on_is_rewritten(root):
    write_job(root, 'JOB-001', function=['chief-product-officer'])
    assert migrate.main(['--vault', str(root), '--apply']) == 0
    assert stored(root, 'JOB-001')['function'] == ['product-manager']


def test_a_record_naming_both_the_absorbed_code_and_its_absorber_keeps_it_once(root):
    write_job(root, 'JOB-002', function=['product-manager', 'chief-product-officer'])
    migrate.main(['--vault', str(root), '--apply'])
    assert stored(root, 'JOB-002')['function'] == ['product-manager']


def test_a_function_tag_token_is_rewritten_and_no_other_facet_is_touched(root):
    write_job(root, 'JOB-003', tags=['function:innovation-officer', 'skill/capability:python'])
    migrate.main(['--vault', str(root), '--apply'])
    assert stored(root, 'JOB-003')['tags'] == ['function:innovation-manager',
                                               'skill/capability:python']


def test_the_value_record_and_every_rank_of_it_are_rewritten(root):
    write_job(root, 'JOB-004', values={'occupation_family': family_record(
        'ict-business-analysis-manager', 'ict-consultant')})
    migrate.main(['--vault', str(root), '--apply'])
    record = stored(root, 'JOB-004')['values']['occupation_family']
    assert record['value'] == 'ict-business-analyst'
    assert taxonomy.ranked_values(record) == ('ict-business-analyst', 'ict-consultant')
    assert record['ranked'][0]['rank'] == 1


def test_an_absorbed_rank_colliding_with_its_absorber_closes_the_ranks_up(root):
    """One family cannot hold two ranks, so the better rank wins and the
    ranks below it move up rather than leaving a gap at 2."""
    write_job(root, 'JOB-005', values={'occupation_family': family_record(
        'product-manager', 'chief-product-officer', 'marketing-manager')})
    migrate.main(['--vault', str(root), '--apply'])
    record = stored(root, 'JOB-005')['values']['occupation_family']
    assert taxonomy.ranked_values(record) == ('product-manager', 'marketing-manager')
    assert [item['rank'] for item in record['ranked']] == [1, 2]


def test_the_version_the_value_was_classified_under_is_not_rewritten(root):
    """The migration changes the CODE and nothing about the reading: the
    stored version is the one fact that says which vocabulary read the
    posting."""
    before = family_record('innovation-officer')
    write_job(root, 'JOB-006', values={'occupation_family': before})
    migrate.main(['--vault', str(root), '--apply'])
    after = stored(root, 'JOB-006')['values']['occupation_family']
    assert after['taxonomy_version'] == before['taxonomy_version'] == '1.0.0'
    assert after['classified_at'] == before['classified_at']


# --- the registry, and the order the two steps run in --------------------

def test_the_absorbed_registry_entries_are_removed_and_the_rest_stay(root):
    write_job(root, 'JOB-007', function=['chief-product-officer'])
    migrate.main(['--vault', str(root), '--apply'])
    assert vault.known_function_ids(root) == {'product-manager', 'ict-business-analyst',
                                              'innovation-manager'}


def test_a_rewritten_record_still_saves_through_the_vaults_own_validation(root):
    """The reason the order matters at all: `vault.save_job` rejects an
    unknown function id, so a record left naming an absorbed code after
    its registry entry went would be unsaveable."""
    write_job(root, 'JOB-008', function=['chief-product-officer'],
              url='https://fiction.example/a')
    migrate.main(['--vault', str(root), '--apply'])
    saved = vault.save_job(root, {'function': ['product-manager']}, 'JOB-008')
    assert saved['function'] == ['product-manager']


# --- the safety rails ----------------------------------------------------

def test_a_dry_run_writes_nothing(root, capsys):
    write_job(root, 'JOB-009', function=['chief-product-officer'])
    assert migrate.main(['--vault', str(root)]) == 0
    assert 'DRY RUN' in capsys.readouterr().out
    assert stored(root, 'JOB-009')['function'] == ['chief-product-officer']
    assert 'chief-product-officer' in vault.known_function_ids(root)


def test_the_report_names_records_by_id_and_never_by_title(root, capsys):
    write_job(root, 'JOB-010', function=['innovation-officer'], title='A very distinctive role')
    migrate.main(['--vault', str(root)])
    out = capsys.readouterr().out
    assert 'JOB-010' in out
    assert 'A very distinctive role' not in out


def test_a_second_run_finds_nothing_to_change(root, capsys):
    write_job(root, 'JOB-011', function=['chief-product-officer'],
              tags=['function:innovation-officer'],
              values={'occupation_family': family_record('ict-business-analysis-manager')})
    migrate.main(['--vault', str(root), '--apply'])
    capsys.readouterr()
    assert migrate.main(['--vault', str(root), '--apply']) == 0
    assert 'nothing to change' in capsys.readouterr().out


def test_a_vault_that_never_held_an_absorbed_code_is_left_alone(root, capsys):
    vault.save_tags(root, {'facets': {'function': {'label': 'Job function', 'values': [
        {'id': 'product-manager', 'label': 'Product manager'}]}}})
    write_job(root, 'JOB-012', function=['product-manager'])
    assert migrate.main(['--vault', str(root)]) == 0
    assert 'nothing to change' in capsys.readouterr().out


def test_a_path_that_is_not_a_vault_is_refused(tmp_path):
    with pytest.raises(SystemExit, match='does not look like a CareerOS vault'):
        migrate.main(['--vault', str(tmp_path / 'nowhere')])


def test_no_vault_at_all_stops_rather_than_guessing(monkeypatch):
    monkeypatch.delenv('CAREEROS_VAULT', raising=False)
    with pytest.raises(SystemExit, match='no vault given'):
        migrate.main([])
