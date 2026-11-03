"""The family suggestion queue (CAREER-131): that a posting no family
fits produces a COUNTED proposal instead of a forced family, that the
owner can see the queue and approve one entry, that an approved
proposal becomes data in both files that must not drift (with the
pinned counts moved by the script, not by hand), and that the re-run
afterwards only pays for the postings whose family was unknown."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from careeros import classify, taxonomy
from careeros.classify import llm, rules

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_script():
    """scripts/ is not a package, so the queue script is loaded by path
    (the pattern tests/test_pool_import.py already uses)."""
    path = REPO_ROOT / 'scripts' / 'family_suggestions.py'
    spec = importlib.util.spec_from_file_location('family_suggestions', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = load_script()


class FakeClient:
    """The one method the llm layer uses, answering with fixed content."""

    def __init__(self, content):
        self.content = content
        self.chat = SimpleNamespace(completions=self)

    def create(self, **payload):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
            usage={'prompt_tokens': 900, 'completion_tokens': 40, 'total_tokens': 940})


CONFIG = llm.Config(base_url='http://fixture.test/v1', api_key='ollama', model='qwen3:30b-a3b')


# --- the model proposes instead of forcing --------------------------------

def test_a_proposal_arrives_in_the_prompt_only_with_the_family_field():
    """The extra-key instruction is about occupation_family alone; a
    prompt that asked for proposals on `contract` would invite the model
    to invent vocabulary on every dimension."""
    with_family = llm.prompt(classify.subject(title='x'), ('occupation_family',))[1]['content']
    assert 'proposed_role' in with_family
    without = llm.prompt(classify.subject(title='x'), ('contract',))[1]['content']
    assert 'proposed_role' not in without


def test_an_unfittable_posting_yields_unknown_plus_a_countable_proposal():
    """The core of CAREER-131: the value stays `unknown` (a proposal is
    a question, never a stored answer), and the record carries the name
    plus a review reason the run summary counts like any other."""
    content = json.dumps({'occupation_family': {
        'code': 'unknown', 'evidence': 'bedient Produktionsanlagen', 'confidence': 0.9,
        'proposed_role': 'Robotics Technician'}})
    answers, _ = llm.classify(classify.subject(title='Anlagenbediener Robotik'),
                              ('occupation_family',), client=FakeClient(content), config=CONFIG)
    record = answers['occupation_family']
    assert record['value'] == taxonomy.UNKNOWN
    assert classify.review_reason(record) == llm.FAMILY_SUGGESTED
    assert record['evidence']['proposed_role'] == 'Robotics Technician'


def test_a_plain_unknown_stays_a_plain_unknown():
    """No proposal attached, no family_suggested reason: the existing
    'the posting does not say' answer must not be relabelled, or the
    queue count would be the count of every unknown family."""
    content = json.dumps({'occupation_family': {
        'code': 'unknown', 'evidence': '', 'confidence': 0.9}})
    answers, _ = llm.classify(classify.subject(title='Mitarbeiter gesucht'),
                              ('occupation_family',), client=FakeClient(content), config=CONFIG)
    assert classify.review_reason(answers['occupation_family']) is None


def test_a_proposal_on_any_other_field_is_ignored():
    """`proposed_role` is defined for the family field only. A model that
    sprinkles it onto `contract` must not create queue entries the
    approval script cannot honour."""
    content = json.dumps({'contract': {
        'code': 'unknown', 'evidence': '', 'confidence': 0.9,
        'proposed_role': 'Werkvertrag'}})
    answers, _ = llm.classify(classify.subject(title='x'), ('contract',),
                              client=FakeClient(content), config=CONFIG)
    assert classify.review_reason(answers['contract']) is None
    assert 'proposed_role' not in (answers['contract'].get('evidence') or {})


# --- collect and count -----------------------------------------------------

def _run_file(day, postings):
    return {'classified_at': f'{day}T00:00:00+00:00', 'day': day, 'layer': 'llm',
            'postings': postings}


def _proposed(key, title, role, day='2026-11-02'):
    return {'key': key, 'title': title,
            'values': {'occupation_family': taxonomy.make_value_record(
                'occupation_family', taxonomy.UNKNOWN, 'llm',
                evidence={'needs_review': llm.FAMILY_SUGGESTED, 'proposed_role': role},
                classified_at=day)},
            'salary': None, 'review': {'occupation_family': llm.FAMILY_SUGGESTED},
            'metrics': []}


def _settled(key, title, code='software-engineer'):
    return {'key': key, 'title': title,
            'values': {'occupation_family': taxonomy.make_value_record(
                'occupation_family', code, 'llm', classified_at='2026-11-02')},
            'salary': None, 'review': {}, 'metrics': []}


def test_proposals_are_counted_by_distinct_postings_and_the_latest_run_wins(tmp_path):
    runs = tmp_path / 'runs'
    runs.mkdir()
    (runs / 'run_2026-11-01.yaml').write_text(yaml.safe_dump(_run_file('2026-11-01', [
        _proposed('k1', 'Anlagenbediener', 'Robotics Technician'),
        _proposed('k2', 'Roboterwartung', 'robotics technician'),
        _proposed('k3', 'Sous Chef', 'Kitchen Manager'),
    ])))
    # k1 re-run a day later with no proposal this time: it left the queue.
    (runs / 'run_2026-11-02.yaml').write_text(yaml.safe_dump(_run_file('2026-11-02', [
        _settled('k1', 'Anlagenbediener'),
    ])))
    proposals = script.collect(runs)
    assert set(proposals) == {'k2', 'k3'}
    # spacing and case are not two proposals
    assert script.normalise(' Robotics  Technician ') == 'robotics technician'


# --- approve: one proposal becomes a data entry -----------------------------

@pytest.fixture
def repo_copy(tmp_path):
    """The four files `approve` writes, plus a runs directory, copied so
    the real repository is never the subject of a write test."""
    root = tmp_path / 'repo'
    for relative in (script.SEED_REL, script.FAMILIES_REL,
                     script.TAXONOMY_TESTS_REL, script.FACET_TESTS_REL):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, target)
    runs = root / script.RUNS_DIR_REL
    runs.mkdir(parents=True)
    (runs / 'run_2026-11-02.yaml').write_text(yaml.safe_dump(_run_file('2026-11-02', [
        _proposed('k2', 'Roboterwartung 80-100%', 'Robotics Technician'),
        _proposed('k3', 'Anlagenführer Robotik', 'robotics technician'),
        _settled('k1', 'Backend Entwickler'),
    ])))
    return root


def test_approving_writes_both_files_the_drift_test_guards(repo_copy):
    script.approve('Robotics Technician', code='robotics-technician',
                   label_de='Robotertechniker', isco3='742', root=repo_copy)
    families = yaml.safe_load((repo_copy / script.FAMILIES_REL).read_text())
    entries = next(cl for cl in families['code_lists']
                   if cl['dimension'] == 'occupation_family')['codes']
    new = next(entry for entry in entries if entry['code'] == 'robotics-technician')
    assert new['label'] == 'Robotics Technician'
    assert new['label_de'] == 'Robotertechniker'
    assert new['status'] == 'proposed' and new['isco4'] is None
    assert new['isco3'] == '742'
    assert taxonomy.valid_code('isco_minor_group', '742')
    seed = yaml.safe_load((repo_copy / script.SEED_REL).read_text())
    seed_entry = next(e for e in seed['occupations'] if e['id'] == 'robotics-technician')
    assert seed_entry['label'] == new['label']
    assert seed_entry['esco_uri'] is None and seed_entry['keywords'] == []
    # the version moved: stored records say which list they were made against
    assert families['taxonomy_version'] == '1.4.0'


def test_the_pinned_counts_move_with_the_list(repo_copy):
    """The 62s in the tests are the owner's pins, and an approval the
    script cannot pin correctly must not half-write: this checks the
    numbers the drift test and the facet test compare against."""
    script.approve('Robotics Technician', code='robotics-technician',
                   label_de='Robotertechniker', isco3='742', root=repo_copy)
    taxonomy_tests = (repo_copy / script.TAXONOMY_TESTS_REL).read_text()
    facet_tests = (repo_copy / script.FACET_TESTS_REL).read_text()
    assert 'assert len(codes) == 63' in taxonomy_tests
    assert "statuses.count('proposed') == 51" in taxonomy_tests
    assert 'assert len(without_isco4) == 25' in taxonomy_tests
    assert 'assert len(families) == 63' in taxonomy_tests
    assert 'assert len(ids) == 63' in facet_tests
    assert "'robotics-technician'," in facet_tests


def test_a_second_approval_with_an_isco4_does_not_move_the_without_isco4_pin(repo_copy):
    script.approve('Robotics Technician', code='robotics-technician',
                   label_de='Robotertechniker', isco3='742', isco4='2512', root=repo_copy)
    taxonomy_tests = (repo_copy / script.TAXONOMY_TESTS_REL).read_text()
    assert 'assert len(without_isco4) == 24' in taxonomy_tests
    families = yaml.safe_load((repo_copy / script.FAMILIES_REL).read_text())
    entries = next(cl for cl in families['code_lists']
                   if cl['dimension'] == 'occupation_family')['codes']
    new = next(e for e in entries if e['code'] == 'robotics-technician')
    assert new['isco4'] == '2512'


def test_an_isco4_the_shipped_list_does_not_have_is_refused(repo_copy):
    """The drift test grades every family's isco4 against the shipped
    ISCO-08 list, so writing one outside it would turn the suite red."""
    with pytest.raises(SystemExit, match='unit-group list'):
        script.approve('Robotics Technician', code='robotics-technician',
                       label_de='Robotertechniker', isco3='742', isco4='7422', root=repo_copy)


def test_approval_refuses_a_bad_code_an_unknown_group_and_a_second_time(repo_copy):
    with pytest.raises(SystemExit, match='kebab-case'):
        script.approve('Robotics Technician', code='Robotics_Technician',
                       label_de='x', isco3='742', root=repo_copy)
    with pytest.raises(SystemExit, match='minor group'):
        script.approve('Robotics Technician', code='robotics-technician',
                       label_de='x', isco3='999', root=repo_copy)
    script.approve('Robotics Technician', code='robotics-technician',
                   label_de='Robotertechniker', isco3='742', root=repo_copy)
    with pytest.raises(SystemExit, match='already exists'):
        script.approve('Robotics Technician', code='robotics-technician',
                       label_de='Robotertechniker', isco3='742', root=repo_copy)


def test_the_note_records_the_proposal_count(repo_copy):
    script.approve('Robotics Technician', code='robotics-technician',
                   label_de='Robotertechniker', isco3='742', root=repo_copy)
    families = yaml.safe_load((repo_copy / script.FAMILIES_REL).read_text())
    entries = next(cl for cl in families['code_lists']
                   if cl['dimension'] == 'occupation_family')['codes']
    new = next(e for e in entries if e['code'] == 'robotics-technician')
    assert '2 posting(s)' in new['note']
    assert 'CAREER-131' in new['note']


# --- re-run only the unknown jobs -------------------------------------------

_spec = importlib.util.spec_from_file_location(
    'run_classification', REPO_ROOT / 'scripts' / 'run_classification.py')
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def test_settled_families_are_carried_and_unknown_ones_re_classified(tmp_path):
    previous = tmp_path / 'previous.yaml'
    previous.write_text(yaml.safe_dump(_run_file('2026-11-01', [
        _settled('k1', 'Backend Entwickler'),
        _proposed('k2', 'Roboterwartung', 'Robotics Technician'),
        {'key': 'k3', 'title': 'Praktikum', 'values': {
            'occupation_family': taxonomy.make_value_record(
                'occupation_family', taxonomy.UNKNOWN, 'llm',
                classified_at='2026-11-01')},
         'salary': None, 'review': {}, 'metrics': []},
    ])))
    loaded = runner.load_previous(previous)
    found = [classify.subject(key='k1', title='Backend Entwickler'),
             classify.subject(key='k2', title='Roboterwartung'),
             classify.subject(key='k3', title='Praktikum'),
             classify.subject(key='k4', title='Neu im Pool')]
    to_classify, carried = runner.split_by_previous(found, loaded)
    assert {s['key'] for s in to_classify} == {'k2', 'k3', 'k4'}
    assert set(carried) == {'k1'}


def test_a_carried_result_bills_no_tokens_for_the_previous_call():
    record = _settled('k1', 'Backend Entwickler')
    record['metrics'] = [{'model': 'qwen3:30b-a3b', 'ok': True, 'total_tokens': 940,
                          'latency_ms': 1200.0}]
    carried = runner.carried_result(record)
    assert carried['metrics'] == []
    assert carried['values']['occupation_family']['value'] == 'software-engineer'


def test_a_missing_previous_file_classifies_everything(tmp_path):
    assert runner.load_previous(tmp_path / 'absent.yaml') == {}
