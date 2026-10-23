"""The local-model layer (CAREER-57 layer 2, CAREER-18 M1-3/M1-4): that
it is only asked about what the rules could not settle, that every
answer is validated against the taxonomy before it is stored, that a
refused answer becomes a flagged `unknown` rather than a guess or a gap,
and that every call is measured.

Fixtures only: the owner's Ollama host was never called in this build,
so the client here is a fake with the one method this layer uses.
"""
import json
from types import SimpleNamespace

from careeros import classify, llm_client, taxonomy
from careeros.classify import llm, rules


class FakeClient:
    """Anything with `.chat.completions.create(**payload)` is a client."""

    def __init__(self, content, usage=None, error=None):
        self.content = content
        self.usage = usage or {'prompt_tokens': 900, 'completion_tokens': 40,
                               'total_tokens': 940}
        self.error = error
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **payload):
        self.calls.append(payload)
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
            usage=self.usage)


def answer(**fields):
    return json.dumps({field: {'code': code, 'evidence': 'a phrase', 'confidence': 0.8}
                       for field, code in fields.items()})


CONFIG = llm.Config(base_url='http://fixture.test/v1', api_key='ollama', model='qwen3:30b-a3b')


# --- configuration (M1-4: comparing models is a config change) ------------

def test_the_defaults_are_the_owners_ollama_host():
    config = llm.Config.from_env({})
    assert config.base_url == 'http://192.168.1.10:11434/v1'
    assert config.api_key == 'ollama'
    assert config.model == 'qwen3:30b-a3b'


def test_every_part_of_the_configuration_is_an_environment_variable():
    config = llm.Config.from_env({'CLASSIFY_LLM_BASE_URL': 'http://other.test/v1',
                                  'CLASSIFY_LLM_MODEL': 'llama3.1:70b',
                                  'CLASSIFY_LLM_API_KEY': 'key',
                                  'CLASSIFY_LLM_NATIVE': '1'})
    assert (config.base_url, config.model, config.api_key, config.native) == (
        'http://other.test/v1', 'llama3.1:70b', 'key', True)


def test_the_model_a_value_was_read_by_is_on_the_record():
    """Which is what makes a model comparison readable afterwards."""
    client = FakeClient(answer(contract='internship'))
    values, _ = llm.classify(classify.subject(title='x'), ('contract',),
                             client=client, config=CONFIG)
    assert values['contract']['evidence']['model'] == 'qwen3:30b-a3b'


# --- measurement (M1-3) ---------------------------------------------------

def test_every_call_reports_its_tokens_and_its_latency():
    client = FakeClient(answer(contract='internship'))
    _, metrics = llm.classify(classify.subject(title='x'), ('contract',),
                              client=client, config=CONFIG)
    assert metrics['total_tokens'] == 940
    assert metrics['prompt_tokens'] == 900
    assert metrics['latency_ms'] is not None
    assert metrics['ok'] is True


def test_a_failed_call_is_still_measured():
    """A failed call still cost time, and a run that hides that cannot
    be budgeted."""
    client = FakeClient(None, error=TimeoutError('no route to host'))
    _, metrics = llm.classify(classify.subject(title='x'), ('contract',),
                              client=client, config=CONFIG)
    assert metrics['ok'] is False
    assert 'TimeoutError' in metrics['error']
    assert metrics['latency_ms'] is not None


def test_token_counts_are_read_from_either_endpoints_names():
    """Ollama's native /api/chat reports `prompt_eval_count`; the
    OpenAI-compatible path reports `usage.prompt_tokens`."""
    assert llm_client.usage({'prompt_eval_count': 10, 'eval_count': 5}) == {
        'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}
    assert llm_client.usage({'usage': {'prompt_tokens': 7, 'completion_tokens': 3,
                                       'total_tokens': 10}})['total_tokens'] == 10


def test_a_server_that_reports_no_tokens_yields_none_and_not_zero():
    assert llm_client.usage({})['total_tokens'] is None


# --- what is asked, and what is not --------------------------------------

def test_only_the_fields_the_rules_left_open_are_asked_about():
    values = rules.classify(classify.subject(title='Senior Java-Entwickler/in 80%'))
    open_fields = classify.open_fields(values)
    assert 'occupation_family' not in open_fields
    assert 'seniority' not in open_fields
    assert 'contract' in open_fields


def test_asking_about_nothing_makes_no_call():
    client = FakeClient(answer())
    values, metrics = llm.classify(classify.subject(title='x'), (), client=client,
                                   config=CONFIG)
    assert (values, client.calls) == ({}, [])
    assert metrics['ok'] is True


def test_the_prompt_lists_the_codes_a_field_may_answer_with():
    messages = llm.prompt(classify.subject(title='Praktikum'), ('contract', 'work_model'))
    asked = messages[1]['content']
    assert 'internship' in asked and 'hybrid' in asked
    assert 'unknown' in asked


def test_an_incomplete_dimension_is_not_listed_code_by_code():
    """The municipality register has 2 110 entries; sending them per
    posting would cost more than the answer is worth."""
    assert 'a valid municipality code' in llm.options('municipality')


def test_a_long_description_is_capped_before_it_is_sent():
    subject = classify.subject(title='x', text='a' * 50_000)
    assert len(llm.prompt(subject, ('contract',))[1]['content']) < 10_000


# --- validation, and the escalation queue --------------------------------

def test_a_valid_code_becomes_a_value_record_sourced_llm():
    client = FakeClient(answer(contract='internship'))
    values, _ = llm.classify(classify.subject(title='x'), ('contract',),
                             client=client, config=CONFIG)
    assert values['contract']['value'] == 'internship'
    assert values['contract']['source'] == 'llm'
    assert values['contract']['evidence']['phrase'] == 'a phrase'


def test_a_code_the_taxonomy_does_not_have_is_refused_with_a_reason():
    """Never the nearest code: a made-up contract type is a flagged
    `unknown`, which is what the escalation queue reads."""
    client = FakeClient(answer(contract='gig_work'))
    values, _ = llm.classify(classify.subject(title='x'), ('contract',),
                             client=client, config=CONFIG)
    assert values['contract']['value'] == taxonomy.UNKNOWN
    assert classify.review_reason(values['contract']) == llm.INVALID_CODE
    assert values['contract']['evidence']['model_answer'] == 'gig_work'


def test_an_answer_under_the_confidence_floor_is_marked_for_review():
    client = FakeClient(json.dumps({'contract': {'code': 'permanent', 'confidence': 0.2}}))
    values, _ = llm.classify(classify.subject(title='x'), ('contract',),
                             client=client, config=CONFIG)
    assert values['contract']['value'] == taxonomy.UNKNOWN
    assert classify.review_reason(values['contract']) == llm.BELOW_FLOOR
    assert values['contract']['evidence']['model_answer'] == 'permanent'


def test_an_unparseable_answer_flags_every_field_it_was_asked_about():
    client = FakeClient('I think this is probably a permanent role.')
    values, _ = llm.classify(classify.subject(title='x'), ('contract', 'work_model'),
                             client=client, config=CONFIG)
    assert set(values) == {'contract', 'work_model'}
    assert all(classify.review_reason(record) == llm.UNPARSEABLE
               for record in values.values())


def test_a_failed_call_flags_every_field_rather_than_dropping_them():
    client = FakeClient(None, error=ConnectionError('host unreachable'))
    values, _ = llm.classify(classify.subject(title='x'), ('contract',),
                             client=client, config=CONFIG)
    assert classify.review_reason(values['contract']) == llm.CALL_FAILED


def test_a_field_the_model_skipped_is_a_fact_and_not_a_gap():
    client = FakeClient(answer(contract='internship'))
    values, _ = llm.classify(classify.subject(title='x'), ('contract', 'seniority'),
                             client=client, config=CONFIG)
    assert classify.review_reason(values['seniority']) == llm.NOT_ANSWERED


def test_the_model_may_answer_unknown_without_being_flagged():
    """`unknown` is a real answer (D4), and the prompt asks for it rather
    than for the most common code."""
    client = FakeClient(answer(contract='unknown'))
    values, _ = llm.classify(classify.subject(title='x'), ('contract',),
                             client=client, config=CONFIG)
    assert values['contract']['value'] == taxonomy.UNKNOWN
    assert classify.review_reason(values['contract']) is None


def test_a_fenced_json_answer_is_still_read():
    client = FakeClient('```json\n{"contract": {"code": "internship"}}\n```')
    values, _ = llm.classify(classify.subject(title='x'), ('contract',),
                             client=client, config=CONFIG)
    assert values['contract']['value'] == 'internship'


# --- the whole pipeline with layer 2 --------------------------------------

def test_the_model_never_displaces_what_a_rule_settled():
    """`llm` is last in the precedence order."""
    client = FakeClient(answer(contract='freelance_mandate', seniority='s0'))
    result = classify.classify(classify.subject(title='Senior Product Owner 80%', text='Festanstellung, unbefristet.'),
                               layer='all', client=client, config=CONFIG)
    assert result['values']['seniority']['source'] == 'rule'
    assert result['values']['seniority']['value'] == 's3'


def test_the_model_fills_what_the_rules_left_unknown():
    client = FakeClient(answer(work_model='remote'))
    result = classify.classify(classify.subject(title='Senior Java-Entwickler/in 80%'),
                               layer='all', client=client, config=CONFIG)
    assert result['values']['work_model']['value'] == 'remote'
    assert result['values']['work_model']['source'] == 'llm'


def test_a_run_carries_its_calls_measurements():
    client = FakeClient(answer(work_model='remote'))
    result = classify.classify(classify.subject(title='Entwickler'), layer='all',
                               client=client, config=CONFIG)
    assert result['layers'] == ['rules', 'llm']
    assert result['metrics'][0]['total_tokens'] == 940


def test_the_client_is_asked_for_json_with_thinking_off():
    """The LLMClient's own note: a reasoning model left thinking emits
    chain-of-thought on every call, which is ~20s of tokens for a
    classification."""
    client = FakeClient(answer(contract='internship'))
    llm.classify(classify.subject(title='x'), ('contract',), client=client, config=CONFIG)
    payload = client.calls[0]
    assert payload['response_format'] == {'type': 'json_object'}
    assert payload['think'] is False
    assert payload['temperature'] == 0.0
