"""Package 2: grouped requirements, their fixed vocabulary, the extraction
prompt and parser that produce them, and the rule-based fallback. Fixture
responses only; no live model (tests/conftest.py blocks the network and the
LLM client is always injected here)."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from careeros import ingest, vault
from careeros.server import apply_field_status


def client_for(content):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=Mock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))])))))


POSTING = ('We build tools for engineers.\n\n'
           'Requirements:\n- Five years of Python\n- Strong SQL\n\n'
           'Nice to have:\n- Kubernetes experience\n- Rust')


# --- the fixed vocabulary ---

def test_the_vocabulary_is_the_five_owner_chosen_groups():
    assert vault.REQUIREMENT_GROUPS == ('education', 'experience', 'skills',
                                        'languages', 'certifications')
    assert vault.REQUIREMENT_LEVELS == ('must', 'nice')
    assert ingest.REQUIREMENT_GROUP_FALLBACK in vault.REQUIREMENT_GROUPS


@pytest.mark.parametrize('answered,expected', [
    ('Education', 'education'),
    ('experience', 'experience'),
    ('Languages', 'languages'),
    ('language', 'languages'),
    ('Certification', 'certifications'),
    ('certificates', 'certifications'),
    ('skill', 'skills'),
    # Nothing the owner chose: the fallback group, never a sixth heading.
    ('Tooling', 'skills'),
    ('', 'skills'),
    (None, 'skills'),
])
def test_every_answered_group_lands_in_the_vocabulary(answered, expected):
    assert ingest.requirement_group(answered) == expected


@pytest.mark.parametrize('answered,expected', [
    ('must', 'must'),
    ('nice', 'nice'),
    ('Nice to have', 'nice'),
    ('preferred', 'nice'),
    ('bonus points', 'nice'),
    ('required', 'must'),
    # A posting insists on a requirement unless it says otherwise.
    ('', 'must'),
    (None, 'must'),
])
def test_every_answered_level_lands_in_must_or_nice(answered, expected):
    assert ingest.requirement_level(answered) == expected


# --- the prompt the model is given ---

def test_the_prompt_names_the_five_groups_and_the_fallback_rule():
    """Pins what the extraction asks for: the field, the closed vocabulary
    and the instruction that an unplaceable line goes to the fallback
    group. A prompt that stops saying this starts inventing groups."""
    prompt = ingest.build_prompt(POSTING)[1]['content']
    assert 'requirement_groups: list of objects' in prompt
    for group in vault.REQUIREMENT_GROUPS:
        assert group in prompt
    assert 'never invent another group' in prompt
    assert '"must"' in prompt and '"nice"' in prompt


# --- the parser ---

def test_parser_normalizes_the_model_groups_into_the_vocabulary():
    parsed = ingest.parse_response(json.dumps({'requirement_groups': [
        {'group': 'Education', 'level': 'must', 'text': 'BSc in computer science'},
        {'group': 'Languages', 'level': 'nice to have', 'text': 'German'},
        {'group': 'Tooling', 'level': 'must', 'text': 'Terraform'},
    ]}))
    assert parsed['requirement_groups'] == [
        {'group': 'education', 'level': 'must', 'text': 'BSc in computer science'},
        {'group': 'languages', 'level': 'nice', 'text': 'German'},
        {'group': 'skills', 'level': 'must', 'text': 'Terraform'},
    ]


def test_parser_keeps_one_entry_per_group_and_text_preferring_must():
    parsed = ingest.parse_response(json.dumps({'requirement_groups': [
        {'group': 'skills', 'level': 'nice', 'text': 'Kubernetes'},
        {'group': 'skills', 'level': 'must', 'text': 'kubernetes'},
        {'group': 'experience', 'level': 'nice', 'text': 'Kubernetes'},
    ]}))
    assert parsed['requirement_groups'] == [
        {'group': 'skills', 'level': 'must', 'text': 'kubernetes'},
        {'group': 'experience', 'level': 'nice', 'text': 'Kubernetes'},
    ]


def test_parser_drops_entries_with_no_text_and_malformed_items():
    parsed = ingest.parse_response(json.dumps({
        'title': 'Platform Engineer',
        'requirement_groups': [{'group': 'skills', 'level': 'must', 'text': '  '},
                               'not an object', {'group': 'skills'}],
    }))
    assert 'requirement_groups' not in parsed


def test_groups_alone_are_a_usable_extraction():
    parsed = ingest.parse_response(json.dumps({'requirement_groups': [
        {'group': 'skills', 'level': 'must', 'text': 'Python'}]}))
    assert parsed['requirement_groups'] == [
        {'group': 'skills', 'level': 'must', 'text': 'Python'}]


# --- the rule-based fallback ---

def test_flat_lists_map_into_the_skills_group():
    groups = ingest.requirement_groups(None, ['Five years of Python'], ['Rust'])
    assert groups == [{'group': 'skills', 'level': 'must', 'text': 'Five years of Python'},
                      {'group': 'skills', 'level': 'nice', 'text': 'Rust'}]


def test_the_model_groups_win_over_the_flat_lists():
    groups = ingest.requirement_groups(
        [{'group': 'languages', 'level': 'must', 'text': 'German'}],
        ['Five years of Python'], ['Rust'])
    assert groups == [{'group': 'languages', 'level': 'must', 'text': 'German'}]


def test_nothing_in_means_nothing_out():
    assert ingest.requirement_groups() == []
    assert ingest.requirement_groups([], [], []) == []


# --- extraction end to end, with a fixture response ---

def test_extraction_stores_the_model_groups():
    content = json.dumps({'title': 'Platform Engineer',
                          'requirements': ['Five years of Python'],
                          'nice_to_have': ['Rust'],
                          'requirement_groups': [
                              {'group': 'experience', 'level': 'must', 'text': 'Five years of Python'},
                              {'group': 'languages', 'level': 'nice', 'text': 'German'}]})
    result = ingest.extract(POSTING, client=client_for(content), model=object())
    assert result['requirement_groups'] == [
        {'group': 'experience', 'level': 'must', 'text': 'Five years of Python'},
        {'group': 'languages', 'level': 'nice', 'text': 'German'}]
    # The flat lists stay as they were: the groups are an added field, not
    # a replacement, so a pre-package-2 reader keeps working.
    assert result['description_structured']['requirements'] == ['Five years of Python']


def test_extraction_falls_back_to_grouped_flat_lists_without_a_model():
    """No model reachable: the offline section split still produces groups,
    which is the whole no-LLM fallback."""
    result = ingest.extract(POSTING)
    assert result['ingest_source'] == 'heuristic'
    assert result['requirement_groups'] == [
        {'group': 'skills', 'level': 'must', 'text': 'Five years of Python'},
        {'group': 'skills', 'level': 'must', 'text': 'Strong SQL'},
        {'group': 'skills', 'level': 'nice', 'text': 'Kubernetes experience'},
        {'group': 'skills', 'level': 'nice', 'text': 'Rust'}]


def test_extraction_groups_the_flat_lists_when_the_model_skips_the_field():
    content = json.dumps({'title': 'Platform Engineer',
                          'requirements': ['Five years of Python'], 'nice_to_have': ['Rust']})
    result = ingest.extract(POSTING, client=client_for(content), model=object())
    assert result['requirement_groups'] == [
        {'group': 'skills', 'level': 'must', 'text': 'Five years of Python'},
        {'group': 'skills', 'level': 'nice', 'text': 'Rust'}]


def test_empty_posting_text_yields_no_groups():
    assert ingest.extract('')['requirement_groups'] == []


# --- the stored field ---

def test_a_job_stores_grouped_requirements(tmp_path):
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'requirement_groups': [{'group': 'languages', 'level': 'nice', 'text': 'German'}]})
    assert job['requirement_groups'] == [{'group': 'languages', 'level': 'nice', 'text': 'German'}]
    assert vault.load_job(tmp_path, job['id'])['requirement_groups'] == job['requirement_groups']


def test_a_job_with_no_groups_stores_an_empty_list(tmp_path):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    assert job['requirement_groups'] == []


@pytest.mark.parametrize('groups', [
    'not a list',
    [{'group': 'tooling', 'level': 'must', 'text': 'Terraform'}],
    [{'group': 'skills', 'level': 'maybe', 'text': 'Terraform'}],
    [{'group': 'skills', 'level': 'must', 'text': ''}],
    [{'group': 'skills', 'level': 'must'}],
    [{'group': 'skills', 'level': 'must', 'text': 'Terraform', 'source': 'llm'}],
    [{'group': 'skills', 'level': 'must', 'text': 42}],
    ['Terraform'],
])
def test_an_invalid_group_entry_is_refused(tmp_path, groups):
    with pytest.raises(ValueError):
        vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                  'requirement_groups': groups})


def test_the_migration_backfills_an_empty_list_and_leaves_flat_lists_alone(tmp_path):
    """Owner decision: a job written before the groups keeps its flat
    must/nice lists until the owner re-extracts it. The additive backfill
    gives it the key, never a guess at its content."""
    (tmp_path / 'jobs').mkdir()
    (tmp_path / 'jobs' / 'legacy-JOB-001.yaml').write_text(
        'id: JOB-001\ntitle: Legacy Engineer\nurl: https://posting.example/legacy\n'
        'description_structured:\n  summary: A role.\n  requirements:\n  - Five years of Python\n'
        '  nice_to_have:\n  - Rust\n  method: llm\n')
    vault.migrate_job_fields(tmp_path)
    stored = vault.load_job(tmp_path, 'JOB-001')
    assert stored['requirement_groups'] == []
    assert stored['description_structured']['requirements'] == ['Five years of Python']


def test_the_extraction_popup_reports_on_the_groups():
    """The Requirements section renders the groups, so the per-field
    extraction report has to cover them (package 1's Found / Not found /
    Failed / Pending rows read field_status)."""
    assert 'requirement_groups' in ingest.STATUS_FIELDS
    status = apply_field_status({'field_provenance': {}, 'field_status': {}},
                                {'requirement_groups': [
                                    {'group': 'skills', 'level': 'must', 'text': 'Python'}]})
    assert status['requirement_groups'] == 'done'
    assert apply_field_status({'field_provenance': {}, 'field_status': {}},
                              {})['requirement_groups'] == 'not_evidenced'
