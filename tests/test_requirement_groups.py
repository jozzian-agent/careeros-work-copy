"""Package 2: grouped requirements, their fixed vocabulary, the extraction
prompt and parser that produce them, and the rule-based fallback. Fixture
responses only; no live model (tests/conftest.py blocks the network and the
LLM client is always injected here)."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from careeros import history, ingest, vault
from careeros.server import apply_field_status, create_app
from careeros.web.pages import jobs


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
    # A level that insists and prefers in one breath is what the posting
    # insists on: the preferring word applies to something else in the
    # same sentence, so reading it first would demote a real requirement.
    ('must have, bonus if you also know Rust', 'must'),
    ('required, and a plus if recent', 'must'),
    ('essential', 'must'),
    ('mandatory', 'must'),
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


def test_a_model_group_wins_for_its_own_line_and_the_rest_fold_in():
    """A partial answer must not lose the lines it left out. The model's
    grouping wins line by line, not wholesale: the line it placed keeps
    its group, and every other line of the flat lists still lands under
    the fallback group."""
    groups = ingest.requirement_groups(
        [{'group': 'experience', 'level': 'must', 'text': 'Five years of Python'}],
        ['Five years of Python', 'Strong SQL'], ['Rust'])
    assert groups == [{'group': 'experience', 'level': 'must', 'text': 'Five years of Python'},
                      {'group': 'skills', 'level': 'must', 'text': 'Strong SQL'},
                      {'group': 'skills', 'level': 'nice', 'text': 'Rust'}]


def test_a_line_the_model_placed_is_never_repeated_under_the_fallback_group():
    groups = ingest.requirement_groups(
        [{'group': 'languages', 'level': 'must', 'text': 'German'}], ['german'], [])
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
        {'group': 'languages', 'level': 'nice', 'text': 'German'},
        # The model grouped one of the two lines it listed flat; the other
        # is still a requirement, so it folds in under the fallback group.
        {'group': 'skills', 'level': 'nice', 'text': 'Rust'}]
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


def test_the_vault_normalises_whatever_a_writer_hands_it(tmp_path):
    """The invariant belongs to the record, not to one writer: an owner
    edit arrives through the job PUT and the extraction through its
    callback, and both have to land stripped, deduplicated text."""
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'requirement_groups': [{'group': 'skills', 'level': 'nice', 'text': '  Kubernetes  '},
                               {'group': 'skills', 'level': 'must', 'text': 'kubernetes'},
                               {'group': 'languages', 'level': 'must', 'text': 'German '}]})
    assert job['requirement_groups'] == [
        # The same line in the same group, once, at the stronger level and
        # in the position it first arrived in.
        {'group': 'skills', 'level': 'must', 'text': 'kubernetes'},
        {'group': 'languages', 'level': 'must', 'text': 'German'}]


def test_invalid_stored_groups_are_refused_on_the_way_in_and_read_back_as_stored(tmp_path):
    """A record a hand edit broke must not be silently rewritten by a
    read: migration is the owner's own action (owner decision 2), so a
    read hands the bad value on and the next write is what refuses it."""
    (tmp_path / 'jobs').mkdir()
    (tmp_path / 'jobs' / 'broken-JOB-002.yaml').write_text(
        'id: JOB-002\ntitle: Engineer\nurl: https://posting.example/role\n'
        'requirement_groups:\n- group: tooling\n  level: must\n  text: Terraform\n')
    stored = vault.load_job(tmp_path, 'JOB-002')
    assert stored['requirement_groups'] == [{'group': 'tooling', 'level': 'must', 'text': 'Terraform'}]
    with pytest.raises(ValueError):
        vault.save_job(tmp_path, {'title': 'Engineer'}, 'JOB-002')


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


# --- the owner's per-job migration: POST /api/jobs/<id>/re-extract ---

LEGACY_FIELDS = {
    'title': 'Legacy Engineer', 'url': 'https://posting.example/legacy',
    'description': POSTING,
    'description_structured': {'summary': 'A role.', 'requirements': ['Five years of Python'],
                               'nice_to_have': ['Rust'], 'method': 'llm'},
}


def legacy_job(root, **fields):
    return vault.save_job(root, LEGACY_FIELDS | fields)


@pytest.fixture
def no_worker(monkeypatch):
    """Hold the queued extraction still, so what the endpoint itself
    writes can be asserted without racing the background pass. Returns
    the description each call was handed."""
    handed = []

    def extract_async(description, on_result, **kwargs):
        handed.append(description)
        return SimpleNamespace(is_alive=lambda: False)

    monkeypatch.setattr(ingest, 'extract_async', extract_async)
    return handed


def test_re_extract_groups_a_legacy_job_without_a_model(tmp_path, no_worker):
    """The migration has to land a result on the owner's one click even
    when no model answers, which is what the rule-based fallback is for."""
    job = legacy_job(tmp_path)
    assert job['requirement_groups'] == []
    api = create_app(tmp_path).test_client()
    response = api.post(f'/api/jobs/{job["id"]}/re-extract')
    assert response.status_code == 202
    stored = vault.load_job(tmp_path, job['id'])
    assert stored['requirement_groups'] == [
        {'group': 'skills', 'level': 'must', 'text': 'Five years of Python'},
        {'group': 'skills', 'level': 'nice', 'text': 'Rust'}]
    # The rules did the grouping, but a model read these lines (the stored
    # block says so), and they are still the model's requirements.
    assert stored['field_provenance']['requirement_groups'] == 'llm'


def test_re_extract_credits_the_page_for_lines_no_model_read(tmp_path, no_worker):
    """The other half of the same rule: a block the offline section split
    produced carries no model's work, so regrouping it is page data and
    the Requirements section must not claim an AI wrote it."""
    job = legacy_job(tmp_path, description_structured={
        'summary': 'A role.', 'requirements': ['Five years of Python'],
        'nice_to_have': [], 'method': 'heuristic'})
    api = create_app(tmp_path).test_client()
    assert api.post(f'/api/jobs/{job["id"]}/re-extract').status_code == 202
    stored = vault.load_job(tmp_path, job['id'])
    assert stored['requirement_groups'] == [
        {'group': 'skills', 'level': 'must', 'text': 'Five years of Python'}]
    assert stored['field_provenance']['requirement_groups'] == 'scrape'


def test_re_extract_regroups_a_list_the_owner_emptied(tmp_path, no_worker):
    """An owner who empties the list has set the field, so automation
    leaves it alone. Re-extract is not automation: it is the owner asking
    for the stored text to be read again, which is the one action that
    fills the groups, so it must not be a dead end after an intentional
    clear."""
    job = legacy_job(tmp_path)
    api = create_app(tmp_path).test_client()
    api.put(f'/api/jobs/{job["id"]}', json={'requirement_groups': []})
    assert vault.load_job(tmp_path, job['id'])['field_provenance']['requirement_groups'] == 'user'
    assert api.post(f'/api/jobs/{job["id"]}/re-extract').status_code == 202
    stored = vault.load_job(tmp_path, job['id'])
    assert stored['requirement_groups'] == [
        {'group': 'skills', 'level': 'must', 'text': 'Five years of Python'},
        {'group': 'skills', 'level': 'nice', 'text': 'Rust'}]
    # The list is no longer the owner's own, and the popup says so.
    assert stored['field_provenance']['requirement_groups'] == 'llm'


def test_re_extract_reads_the_stored_text_and_fetches_nothing(tmp_path, no_worker):
    """Not /extract: the posting a legacy job was read from may be gone,
    and the text to group is the one already stored. The suite's offline
    guard would raise on any fetch, so the passing call is the proof."""
    job = legacy_job(tmp_path)
    api = create_app(tmp_path).test_client()
    api.post(f'/api/jobs/{job["id"]}/re-extract')
    assert no_worker == [POSTING]


def test_re_extract_records_that_the_owner_asked(tmp_path, no_worker):
    job = legacy_job(tmp_path)
    api = create_app(tmp_path).test_client()
    api.post(f'/api/jobs/{job["id"]}/re-extract')
    stored = vault.load_job(tmp_path, job['id'])
    assert [entry['detail'] for entry in stored['history']
            if entry['event'] == 're_extracted'] == ['Stored posting text read again.']
    assert history.label_for('re_extracted') == 'Posting read again'


def test_re_extract_puts_the_covered_fields_back_to_pending(tmp_path, no_worker):
    job = legacy_job(tmp_path)
    api = create_app(tmp_path).test_client()
    api.post(f'/api/jobs/{job["id"]}/re-extract')
    status = vault.load_job(tmp_path, job['id'])['field_status']
    assert status['requirement_groups'] == 'done'
    assert status['title'] == 'pending'


def test_a_failed_extraction_keeps_the_rule_based_groups(tmp_path):
    """No model configured, so the queued pass fails: the groups the rules
    already wrote must survive it, or the owner's click would undo itself."""
    app = create_app(tmp_path)
    job = legacy_job(tmp_path)
    api = app.test_client()
    api.post(f'/api/jobs/{job["id"]}/re-extract')
    app.config['LLM_THREADS'][job['id']].join(timeout=5)
    stored = vault.load_job(tmp_path, job['id'])
    assert stored['requirement_groups'] == [
        {'group': 'skills', 'level': 'must', 'text': 'Five years of Python'},
        {'group': 'skills', 'level': 'nice', 'text': 'Rust'}]


def test_a_failed_re_read_leaves_a_read_job_read(tmp_path):
    """The owner's own machine with the model down. The job was read
    before and its details are on the page, so a re-read that produces
    nothing must not call the posting unread: no downgrade to
    extract_failed, and so no card asking for text the job already
    stores. The attempt says what happened in its own line of history."""
    app = create_app(tmp_path)
    job = legacy_job(tmp_path)
    assert job['ingest_state'] == 'complete'
    api = app.test_client()
    api.post(f'/api/jobs/{job["id"]}/re-extract')
    app.config['LLM_THREADS'][job['id']].join(timeout=5)
    stored = vault.load_job(tmp_path, job['id'])
    assert stored['ingest_state'] == 'complete'
    assert stored['ingest_error'] is None
    assert jobs.job_needs_input(stored) is None
    assert [entry['detail'] for entry in stored['history']
            if entry['event'] == 're_extract_failed'] == ['Reading the stored text again found nothing new.']
    assert history.label_for('re_extract_failed') == 'Reading the posting again found nothing new'


def test_a_failed_re_read_leaves_an_unread_posting_asking(tmp_path):
    """The other side of the same rule: a job whose reading never
    succeeded keeps the ordinary failure path, card and all, because
    there is no earlier reading to protect."""
    app = create_app(tmp_path)
    job = legacy_job(tmp_path, ingest_state='extract_failed',
                     ingest_error={'stage': 'extract', 'reason': 'no_usable_fields',
                                   'at': '2026-10-14T12:00:00+00:00'})
    api = app.test_client()
    api.post(f'/api/jobs/{job["id"]}/re-extract')
    app.config['LLM_THREADS'][job['id']].join(timeout=5)
    stored = vault.load_job(tmp_path, job['id'])
    assert stored['ingest_state'] == 'extract_failed'
    # The ask stands, and it names this attempt's own reason.
    assert jobs.job_needs_input(stored) == {'kind': 'read_failed', 'error_reason': 'not_configured'}


def test_a_re_read_leaves_the_fields_the_first_reading_settled(tmp_path):
    """A field the first reading found nothing for was read already, and
    the same text has not changed its mind. A re-read must not move it to
    pending and then to failed, which is how the one click turned every
    "Not found in posting" row into "Failed"."""
    app = create_app(tmp_path)
    job = legacy_job(tmp_path, field_status={'title': 'done', 'seniority': 'not_evidenced',
                                             'skills': 'failed'})
    api = app.test_client()
    api.post(f'/api/jobs/{job["id"]}/re-extract')
    pending = vault.load_job(tmp_path, job['id'])['field_status']
    assert pending['seniority'] == 'not_evidenced'
    assert pending['title'] == 'done'
    # A field an earlier attempt left failed is open again: a re-read is
    # the further attempt it was waiting for.
    assert pending['skills'] == 'pending'
    app.config['LLM_THREADS'][job['id']].join(timeout=5)
    settled = vault.load_job(tmp_path, job['id'])['field_status']
    assert settled['seniority'] == 'not_evidenced'
    assert settled['skills'] == 'failed'


def test_re_extract_replaces_the_rule_based_groups_with_the_model_groups(tmp_path, monkeypatch):
    content = json.dumps({'requirement_groups': [
        {'group': 'education', 'level': 'must', 'text': 'BSc in computer science'},
        {'group': 'languages', 'level': 'nice', 'text': 'German'}]})
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client_for(content))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    job = legacy_job(tmp_path)
    api = app.test_client()
    assert api.post(f'/api/jobs/{job["id"]}/re-extract').status_code == 202
    app.config['LLM_THREADS'][job['id']].join(timeout=5)
    stored = vault.load_job(tmp_path, job['id'])
    assert stored['requirement_groups'] == [
        {'group': 'education', 'level': 'must', 'text': 'BSc in computer science'},
        {'group': 'languages', 'level': 'nice', 'text': 'German'}]
    assert stored['field_provenance']['requirement_groups'] == 'llm'


def test_re_extract_never_overwrites_groups_the_owner_edited(tmp_path, monkeypatch):
    content = json.dumps({'requirement_groups': [
        {'group': 'languages', 'level': 'must', 'text': 'French'}]})
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client_for(content))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    job = legacy_job(tmp_path)
    owned = [{'group': 'languages', 'level': 'must', 'text': 'German'}]
    api = app.test_client()
    api.put(f'/api/jobs/{job["id"]}', json={'requirement_groups': owned})
    assert api.post(f'/api/jobs/{job["id"]}/re-extract').status_code == 202
    app.config['LLM_THREADS'][job['id']].join(timeout=5)
    stored = vault.load_job(tmp_path, job['id'])
    assert stored['requirement_groups'] == owned
    assert stored['field_provenance']['requirement_groups'] == 'user'


def test_an_owner_edit_to_the_groups_is_a_final_value(tmp_path):
    """The Languages editor writes through the generic job PUT, so the
    groups get the same owner protection every other field has."""
    job = legacy_job(tmp_path)
    api = create_app(tmp_path).test_client()
    api.put(f'/api/jobs/{job["id"]}',
            json={'requirement_groups': [{'group': 'languages', 'level': 'must', 'text': 'German'}]})
    stored = vault.load_job(tmp_path, job['id'])
    assert stored['field_provenance']['requirement_groups'] == 'user'
    assert stored['field_status']['requirement_groups'] == 'done'


def test_re_extract_refuses_a_job_with_no_posting_text(tmp_path):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    api = create_app(tmp_path).test_client()
    response = api.post(f'/api/jobs/{job["id"]}/re-extract')
    assert response.status_code == 409
    assert response.get_json()['error'] == 'This job has no posting text to read.'
    assert vault.load_job(tmp_path, job['id'])['requirement_groups'] == []


def test_re_extract_refuses_a_job_whose_reading_is_already_running(tmp_path, no_worker):
    """One reservation per job: the second click did not get it, and must
    not answer as though it had started a reading of its own."""
    app = create_app(tmp_path)
    job = legacy_job(tmp_path)
    api = app.test_client()
    app.config['LLM_PENDING'][job['id']] = object()
    response = api.post(f'/api/jobs/{job["id"]}/re-extract')
    assert response.status_code == 409
    assert response.get_json()['error'] == 'This posting is already being read.'
    # Nothing was written: no groups, and no event claiming the owner's
    # click was acted on.
    stored = vault.load_job(tmp_path, job['id'])
    assert stored['requirement_groups'] == []
    assert [entry for entry in stored['history'] if entry['event'] == 're_extracted'] == []


def test_re_extract_gives_the_reservation_back_when_its_write_fails(tmp_path, no_worker, monkeypatch):
    """A failed write started no reading, so the token it holds has to go
    back: a token left behind blocks every later attempt on that job for
    the life of the process."""
    app = create_app(tmp_path)
    job = legacy_job(tmp_path)
    api = app.test_client()

    def refuse(*args, **kwargs):
        raise ValueError('The vault refused this write.')

    monkeypatch.setattr(vault, 'save_job', refuse)
    assert api.post(f'/api/jobs/{job["id"]}/re-extract').status_code == 400
    assert job['id'] not in app.config['LLM_PENDING']
    monkeypatch.undo()
    assert api.post(f'/api/jobs/{job["id"]}/re-extract').status_code == 202


def test_re_extract_on_a_missing_job_is_a_404(tmp_path):
    api = create_app(tmp_path).test_client()
    assert api.post('/api/jobs/JOB-404/re-extract').status_code == 404


def test_the_job_page_context_carries_the_groups(tmp_path):
    """Contract: everything downstream of the job record reads the groups
    off the page context, so they have to be in it."""
    groups = [{'group': 'languages', 'level': 'nice', 'text': 'German'}]
    job = legacy_job(tmp_path, requirement_groups=groups)
    api = create_app(tmp_path).test_client()
    page = api.get(f'/api/jobs/{job["id"]}?view=page').get_json()
    assert page['job']['requirement_groups'] == groups


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
