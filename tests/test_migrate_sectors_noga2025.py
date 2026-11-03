"""Protects scripts/migrate_sectors_noga2025.py: the ISIC Rev.4 -> NOGA
2025 letter table, the old-J split that is decided and never guessed, and
a dry run that writes nothing.

Fixture-only vaults; the live owner vault is never touched by tests.
"""
import importlib.util
from pathlib import Path

import pytest

from careeros import vault

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'migrate_sectors_noga2025.py'


@pytest.fixture(scope='module')
def script():
    spec = importlib.util.spec_from_file_location('migrate_sectors_noga2025', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vault_root(tmp_path):
    """Six synthetic companies covering every branch of the table: a
    letter that does not move, two that shift, an old J with no free-text
    industry to propose from, an old J whose industry proposes one, and a
    company with no sector at all."""
    for kind in ('companies', 'jobs', 'experiences'):
        (tmp_path / kind).mkdir()
    for name, sectors, sector_text in (
        ('Alpine Works', ['C'], None),
        ('Burgdorf Advisory', ['M'], None),
        ('Cantonal Office', ['O'], None),
        ('Delta Platform', ['J'], None),
        ('Echo Unclassified', [], None),
        ('Foxtrot Studios', ['J'], 'Publishing and broadcasting'),
    ):
        vault.save_company(tmp_path, {'name': name, 'sectors': sectors, 'sector': sector_text})
    return tmp_path


def stored(root):
    return {c['name']: c['sectors'] for c in vault.list_companies(root)}


# --- the old -> new letter table ------------------------------------------

@pytest.mark.parametrize('old,new', [
    # A-I mean the same activity in both classifications.
    ('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D'), ('E', 'E'),
    ('F', 'F'), ('G', 'G'), ('H', 'H'), ('I', 'I'),
    # Everything after the split moved up exactly one letter.
    ('K', 'L'), ('L', 'M'), ('M', 'N'), ('N', 'O'), ('O', 'P'), ('P', 'Q'),
    ('Q', 'R'), ('R', 'S'), ('S', 'T'), ('T', 'U'), ('U', 'V'),
])
def test_every_letter_but_j_maps_without_a_decision(script, old, new):
    assert script.new_letter(old) == new


def test_the_table_covers_all_21_old_letters_and_reaches_the_22nd_new_one(script):
    """The shape claim the table makes: it answers for every ISIC Rev.4
    letter, and its answers are all NOGA 2025 letters -- including V,
    which only exists because of the split."""
    from org_intake import classify

    assert script.OLD_LETTERS == set('ABCDEFGHIJKLMNOPQRSTU')
    answers = {script.new_letter(old, 'J') for old in script.OLD_LETTERS}
    assert answers <= classify.known_section_codes()
    assert 'V' in answers


def test_old_j_is_decided_and_never_guessed(script):
    """The split is a per-company judgement: without a decision the
    function refuses, and it only accepts the two halves."""
    assert script.new_letter('J') == script.NEEDS_DECISION
    assert script.new_letter('J', 'J') == 'J'
    assert script.new_letter('J', 'K') == 'K'
    # Anything else is not a decision, so the refusal stands.
    for not_a_decision in ('L', 'j', 'k', '', None, 'JK'):
        assert script.new_letter('J', not_a_decision) == script.NEEDS_DECISION


@pytest.mark.parametrize('letter', ['V', 'W', 'ZZ', 'j', 'm', '', None, 'J2'])
def test_a_letter_ISIC_never_had_is_reported_not_guessed(script, letter):
    """'V' is the telling one: ISIC Rev.4 stopped at U, so a stored V can
    only mean the vault was already migrated. Guessing a shift for it
    would move a correct letter to a wrong one."""
    assert script.new_letter(letter) == script.NOT_OLD_ISIC


# --- the old-J proposal ---------------------------------------------------

@pytest.mark.parametrize('industry,proposed', [
    ('Publishing and broadcasting', 'J'),
    ('Software and IT services', 'K'),
    ('cloud computing', 'K'),
    # Both halves at once, or neither: propose nothing rather than pick.
    ('software publishing', None),
    ('Banking and insurance', None),
    ('', None),
    (None, None),
])
def test_the_split_proposal_only_speaks_when_the_keywords_are_clear(script, industry, proposed):
    assert script.proposed_split_letter(industry) == proposed


# --- the plan -------------------------------------------------------------

def test_the_plan_rewrites_resolved_records_and_skips_the_undecided(script, vault_root):
    rows = {row['name']: row for row in script.plan(vault.list_companies(vault_root))}

    assert rows['Alpine Works']['new'] == 'C'
    assert rows['Burgdorf Advisory']['updates'] == {'sectors': ['N']}
    assert rows['Cantonal Office']['updates'] == {'sectors': ['P']}
    # An old J with no decision is reported and written by nothing.
    assert rows['Delta Platform']['new'] == script.NEEDS_DECISION
    assert rows['Delta Platform']['updates'] is None
    # A company with no sector is not a row at all.
    assert 'Echo Unclassified' not in rows


def test_a_decision_resolves_one_old_j_without_touching_the_others(script, vault_root):
    rows = {row['name']: row for row in
            script.plan(vault.list_companies(vault_root), {'Delta Platform': 'K'})}
    assert rows['Delta Platform']['updates'] == {'sectors': ['K']}
    assert rows['Foxtrot Studios']['new'] == script.NEEDS_DECISION


def test_a_record_whose_letters_do_not_all_resolve_is_skipped_whole(script):
    """A half-migrated record is worse than an unmigrated one: one letter
    the table cannot answer holds back the whole list."""
    rows = script.plan([{'id': 'CO-900', 'name': 'Mixed Co', 'sectors': ['M', 'V']}])
    assert [row['new'] for row in rows] == ['N', script.NOT_OLD_ISIC]
    assert [row['updates'] for row in rows] == [None, None]


def test_a_proposal_rides_along_with_an_undecided_j_row(script, vault_root):
    rows = {row['name']: row for row in script.plan(vault.list_companies(vault_root))}
    # The industry the record carries, and what the NEW keyword table makes
    # of it, are both in the row a person decides from.
    assert rows['Foxtrot Studios']['industry'] == 'Publishing and broadcasting'
    assert rows['Foxtrot Studios']['proposed'] == 'J'
    assert rows['Delta Platform']['industry'] == ''
    assert rows['Delta Platform']['proposed'] is None


# --- dry run and apply ----------------------------------------------------

def test_a_dry_run_reports_and_writes_nothing(script, vault_root, capsys):
    before = stored(vault_root)
    script.main(['--vault', str(vault_root)])
    output = capsys.readouterr().out

    assert stored(vault_root) == before
    assert 'DRY RUN' in output
    assert 'nothing was written' in output
    assert 'Re-run with --apply' in output
    # Every company that stores a letter is in the table, named, with the
    # letter it has and the letter it would get.
    assert 'Burgdorf Advisory | M   | N' in output
    assert 'Delta Platform' in output and 'NEEDS-DECISION' in output


def test_apply_writes_the_resolved_letters_and_leaves_the_old_j_alone(script, vault_root):
    script.main(['--vault', str(vault_root), '--apply'])
    assert stored(vault_root) == {
        'Alpine Works': ['C'],
        'Burgdorf Advisory': ['N'],
        'Cantonal Office': ['P'],
        'Delta Platform': ['J'],
        'Echo Unclassified': [],
        'Foxtrot Studios': ['J'],
    }


def test_apply_with_decisions_settles_the_split(script, vault_root, tmp_path, capsys):
    decisions = tmp_path / 'decisions.yaml'
    decisions.write_text('Delta Platform: K\nFoxtrot Studios: J\n')
    script.main(['--vault', str(vault_root), '--decisions', str(decisions), '--apply'])

    assert stored(vault_root)['Delta Platform'] == ['K']
    assert stored(vault_root)['Foxtrot Studios'] == ['J']
    assert 'wrote 5 record(s)' in capsys.readouterr().out


def test_a_decision_naming_a_letter_outside_the_split_is_fatal(script, vault_root, tmp_path):
    """A typo that quietly left a company undecided is the one outcome the
    decisions file exists to prevent."""
    decisions = tmp_path / 'bad.yaml'
    decisions.write_text('Delta Platform: L\n')
    with pytest.raises(SystemExit, match='not J or K'):
        script.main(['--vault', str(vault_root), '--decisions', str(decisions)])


def test_a_decision_that_matched_no_old_j_is_reported(script, vault_root, tmp_path, capsys):
    decisions = tmp_path / 'decisions.yaml'
    decisions.write_text('Delta Platfrom: K\n')  # the name is misspelt
    script.main(['--vault', str(vault_root), '--decisions', str(decisions)])
    assert 'matched no old-J company: Delta Platfrom' in capsys.readouterr().out


def test_the_vault_comes_from_the_resolver_the_server_uses(script, vault_root, monkeypatch, capsys):
    """No path is hardcoded anywhere in the script: with no --vault it
    reads whatever `careeros.users.vault_root` resolves, which is the
    vault the running server serves."""
    monkeypatch.setenv('CAREEROS_VAULT', str(vault_root))
    script.main([])
    assert f'vault={vault_root}' in capsys.readouterr().out
