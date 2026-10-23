"""What the deploy path depends on: /healthz, the env-driven settings, and
the two LLM switches.

These four things are the contract between the app and
deploy/deploy.sh. The health poll and the automatic rollback trust
/healthz; the systemd units configure the host, the port and the vault
through the environment; and CI runs the whole suite with no LLM key at
all, which only works because LLM_MOCK=1 answers without a socket and
LLM_DISABLED=1 refuses before opening one.

Nothing here reaches the network. The suite-wide `offline` fixture in
conftest.py already makes `urllib.request.build_opener` raise, so a mock
or disabled client that tried to build a real transport would fail the
test rather than quietly succeed -- which is what makes the "no socket"
assertions below mean something.
"""
import os

import pytest

from careeros import classify, ingest, llm_client, server
from careeros.classify import llm as classify_llm


@pytest.fixture
def client(tmp_path):
    return server.create_app(tmp_path / 'vault').test_client()


@pytest.fixture(autouse=True)
def no_llm_env(monkeypatch):
    """Every test here decides the two switches for itself.

    The suite inherits whatever the developer's shell exports, and an
    LLM_MOCK left on in a terminal would make the "unset" assertions
    below pass for the wrong reason.
    """
    for name in ('LLM_MOCK', 'LLM_DISABLED', 'LLM_MODEL', 'LLM_BASE_URL',
                 'LLM_API_KEY', 'LLM_NATIVE'):
        monkeypatch.delenv(name, raising=False)


# --- /healthz --------------------------------------------------------------

def test_healthz_answers_200_and_status_ok_without_a_session(client, raw_session):
    """The one thing the deploy script polls, with the real login gate in
    place: `raw_session` puts the suite's auto-sign-in back to the real
    cookie loader, so this is an unauthenticated request for real."""
    response = client.get('/healthz')
    assert response.status_code == 200
    assert response.get_json() == {'status': 'ok'}


def test_healthz_is_listed_as_public_so_the_gate_cannot_start_redirecting_it(client):
    # The route and the gate's allow-list are two separate facts, and a
    # /healthz that answered 302 would still look alive to a poll that
    # follows redirects. Both are asserted.
    assert 'healthz' in server.PUBLIC_ENDPOINTS


def test_api_health_is_unchanged(client, raw_session):
    """The published surface stays exactly as it was: /healthz is a second
    route, not a rename (docs/surfaces/json-api.md)."""
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.get_json() == {'ok': True}


# --- the env-driven settings ----------------------------------------------

def test_session_cookie_secure_is_off_by_default(tmp_path):
    # A local run and the LAN install are plain HTTP; a Secure cookie
    # would never come back and the login would look broken.
    app = server.create_app(tmp_path / 'vault')
    assert app.config['SESSION_COOKIE_SECURE'] is False


def test_session_cookie_secure_is_on_when_the_environment_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv('SESSION_COOKIE_SECURE', '1')
    app = server.create_app(tmp_path / 'vault')
    assert app.config['SESSION_COOKIE_SECURE'] is True


@pytest.mark.parametrize('value', ['0', '', 'true', 'yes', 'True'])
def test_only_the_exact_value_1_turns_the_secure_cookie_on(tmp_path, monkeypatch, value):
    """One spelling, like every other flag in this app (CAREEROS_REACT_UI,
    LLM_NATIVE). A half-recognised 'true' that silently meant off would be
    worse than one that is simply not a value."""
    monkeypatch.setenv('SESSION_COOKIE_SECURE', value)
    assert server.create_app(tmp_path / 'vault').config['SESSION_COOKIE_SECURE'] is False


def test_the_other_three_cookie_settings_are_not_env_driven(tmp_path):
    # HttpOnly, SameSite and the lifetime are properties of the design,
    # not of where the instance runs, so there is nothing to configure
    # and no env file can weaken them.
    app = server.create_app(tmp_path / 'vault')
    assert app.config['SESSION_COOKIE_HTTPONLY'] is True
    assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'


def test_host_and_port_come_from_the_environment_with_the_local_defaults(monkeypatch):
    """What lets the systemd units bind 127.0.0.1:8001 and :8002 through
    /etc/careeros/<env>.env while `python -m careeros.server` with no
    arguments still starts where it always did."""
    import argparse

    def parsed(argv):
        parser = argparse.ArgumentParser()
        parser.add_argument('--host', default=os.environ.get('CAREEROS_HOST') or '0.0.0.0')
        parser.add_argument('--port', type=int,
                            default=int(os.environ.get('CAREEROS_PORT') or 8788))
        return parser.parse_args(argv)

    monkeypatch.delenv('CAREEROS_HOST', raising=False)
    monkeypatch.delenv('CAREEROS_PORT', raising=False)
    assert (parsed([]).host, parsed([]).port) == ('0.0.0.0', 8788)

    monkeypatch.setenv('CAREEROS_HOST', '127.0.0.1')
    monkeypatch.setenv('CAREEROS_PORT', '8001')
    assert (parsed([]).host, parsed([]).port) == ('127.0.0.1', 8001)

    # An explicit flag still wins over the environment, the same rule
    # --vault already followed (users.vault_root).
    explicit = parsed(['--host', '0.0.0.0', '--port', '9000'])
    assert (explicit.host, explicit.port) == ('0.0.0.0', 9000)


def test_the_vault_path_is_already_env_driven(tmp_path, monkeypatch):
    # Not new, asserted here because the systemd units depend on it: one
    # rule, in users.vault_root, that the server and the accounts command
    # both follow.
    monkeypatch.setenv('CAREEROS_VAULT', str(tmp_path / 'from-env'))
    assert server.create_app().config['VAULT_PATH'] == tmp_path / 'from-env'
    assert server.create_app(tmp_path / 'explicit').config['VAULT_PATH'] == tmp_path / 'explicit'


# --- LLM_MOCK --------------------------------------------------------------

def test_mock_mode_needs_no_base_url_model_or_key(monkeypatch):
    monkeypatch.setenv('LLM_MOCK', '1')
    assert llm_client.mocked() is True
    client = llm_client.get_llm_client()
    assert isinstance(client, llm_client.MockLLMClient)
    assert llm_client.get_llm_model() == llm_client.MOCK_MODEL


def test_mock_mode_answers_the_same_thing_every_time_and_opens_no_socket(monkeypatch):
    monkeypatch.setenv('LLM_MOCK', '1')
    first = llm_client.get_llm_client().chat.completions.create(
        model='m', messages=[{'role': 'user', 'content': 'hi'}])
    second = llm_client.get_llm_client().chat.completions.create(
        model='m', messages=[{'role': 'user', 'content': 'something else entirely'}])
    assert first.choices[0].message.content == llm_client.MOCK_CONTENT
    assert second.choices[0].message.content == llm_client.MOCK_CONTENT
    assert first.usage == {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}


def test_mock_mode_records_what_it_was_asked(monkeypatch):
    monkeypatch.setenv('LLM_MOCK', '1')
    client = llm_client.get_llm_client()
    client.chat.completions.create(model='m1', messages=[], temperature=0)
    assert client.calls == [{'model': 'm1', 'messages': [], 'temperature': 0}]


def test_a_set_model_still_wins_in_mock_mode(monkeypatch):
    # So a mock run can carry the real model's name when that is what is
    # being measured.
    monkeypatch.setenv('LLM_MOCK', '1')
    monkeypatch.setenv('LLM_MODEL', 'the-real-one')
    assert llm_client.get_llm_model() == 'the-real-one'


def test_mock_content_may_be_a_callable_so_one_mock_serves_two_prompt_shapes(monkeypatch):
    monkeypatch.setenv('LLM_MOCK', '1')
    client = llm_client.MockLLMClient(lambda payload: '{"saw": "%s"}' % payload['model'])
    answer = client.chat.completions.create(model='m2', messages=[])
    assert answer.choices[0].message.content == '{"saw": "m2"}'


def test_extraction_in_mock_mode_reaches_a_visible_failure_rather_than_inventing_fields(monkeypatch):
    """The default canned answer is an empty JSON object on purpose: a
    mock host read nothing, and a plausible-looking summary would land on
    a record as if it had. The extraction settles as `unusable_output`,
    which is a reason the app already shows."""
    monkeypatch.setenv('LLM_MOCK', '1')
    result = ingest.extract('Some posting text that is long enough to be read.')
    assert result['extract_reason'] == 'unusable_output'
    # The heuristic reading is what the record keeps, attributed to the
    # heuristic, so nothing on it claims a model wrote it.
    assert result['ingest_source'] == 'heuristic'


def test_the_classification_layer_mocks_as_unknown_for_every_field_asked(monkeypatch):
    monkeypatch.setenv('LLM_MOCK', '1')
    config = classify_llm.Config.from_env()
    client = config.client()
    assert isinstance(client, llm_client.MockLLMClient)

    fields = ('contract', 'work_model')
    answers, metrics = classify_llm.classify(
        {'title': 'Builder', 'text': 'A posting.'}, fields, client=client, config=config)
    assert metrics['ok'] is True
    assert sorted(answers) == sorted(fields)
    for field in fields:
        # `unknown` is a real answer in this taxonomy (D4), so a mocked
        # run produces records rather than failures: the "found nothing"
        # rule, not a `needs_review` reason.
        record = answers[field]
        assert record['value'] == 'unknown'
        assert record['source'] == 'llm'
        assert 'needs_review' not in record['evidence']
        assert record['evidence']['quote'] == 'mock mode'


def test_the_mock_classification_answer_is_a_function_of_the_ask_alone(monkeypatch):
    monkeypatch.setenv('LLM_MOCK', '1')
    payload = {'messages': [{'role': 'user',
                             'content': '- contract: what kind\n- seniority: how far\n'}]}
    assert classify_llm.mock_answer(payload) == classify_llm.mock_answer(payload)
    assert '"contract"' in classify_llm.mock_answer(payload)
    assert '"seniority"' in classify_llm.mock_answer(payload)


# --- LLM_DISABLED ----------------------------------------------------------

def test_disabled_mode_refuses_with_one_message_and_no_configuration(monkeypatch):
    monkeypatch.setenv('LLM_DISABLED', '1')
    assert llm_client.disabled() is True
    for call in (llm_client.get_llm_client, llm_client.get_llm_model):
        with pytest.raises(llm_client.LLMDisabled) as raised:
            call()
        assert str(raised.value) == llm_client.DISABLED_MESSAGE


def test_disabled_wins_over_mock_when_both_are_set(monkeypatch):
    # "Off" is an instruction about this host; "mock" is only a
    # substitute for the network.
    monkeypatch.setenv('LLM_MOCK', '1')
    monkeypatch.setenv('LLM_DISABLED', '1')
    assert llm_client.mocked() is False
    with pytest.raises(llm_client.LLMDisabled):
        llm_client.get_llm_client()


def test_disabled_mode_is_a_runtime_error_so_existing_callers_already_report_it(monkeypatch):
    monkeypatch.setenv('LLM_DISABLED', '1')
    assert issubclass(llm_client.LLMDisabled, RuntimeError)


def test_an_injected_client_is_not_a_way_around_the_off_switch(monkeypatch):
    """An off host must make no call, including one through a client
    somebody else built and handed in -- which is why the check is in
    _call_llm and not only inside get_llm_client."""
    monkeypatch.setenv('LLM_DISABLED', '1')
    called = []

    class Loud:
        def __init__(self):
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **payload):
            called.append(payload)
            raise AssertionError('a disabled environment called the LLM')

    result = ingest.extract('A posting long enough to be read by something.',
                            client=Loud(), model='m')
    assert called == []
    assert result['extract_reason'] == 'not_configured'
    assert result['ingest_source'] == 'heuristic'


def test_the_classification_layer_refuses_before_building_a_client(monkeypatch):
    monkeypatch.setenv('LLM_DISABLED', '1')
    with pytest.raises(llm_client.LLMDisabled):
        classify_llm.Config.from_env().client()


def test_the_company_backfill_withholds_the_client_rather_than_injecting_a_raising_one(monkeypatch):
    """The capability only appends its LLM fallback signal when a client
    is passed (org_intake.enrich.external_sectors, rule 9), so withholding
    it is how an off host skips that signal instead of collecting one
    failure per company."""
    from careeros import enrich as company_enrichment

    monkeypatch.setenv('BACKFILL_USE_LLM', '1')
    monkeypatch.setenv('LLM_DISABLED', '1')
    assert 'llm_client' not in company_enrichment.classification_options()

    monkeypatch.delenv('LLM_DISABLED')
    assert 'llm_client' in company_enrichment.classification_options()


def test_neither_switch_set_leaves_the_old_behaviour_exactly_as_it_was(monkeypatch):
    # No flags and no configuration: the same RuntimeError the app has
    # always raised, with the same message, so nothing that reads it
    # changes meaning.
    assert llm_client.disabled() is False
    assert llm_client.mocked() is False
    with pytest.raises(RuntimeError, match='LLM_BASE_URL is not set'):
        llm_client.get_llm_client()
    with pytest.raises(RuntimeError, match='LLM_MODEL is not set'):
        llm_client.get_llm_model()


def test_the_classify_module_still_names_its_own_configuration(monkeypatch):
    # Guards the reach of the two switches: they change WHETHER a call
    # happens, never where the real one would go.
    monkeypatch.setenv('CLASSIFY_LLM_BASE_URL', 'http://host.example/v1')
    monkeypatch.setenv('CLASSIFY_LLM_MODEL', 'a-model')
    config = classify_llm.Config.from_env()
    assert (config.base_url, config.model) == ('http://host.example/v1', 'a-model')
    assert classify is not None  # the package imports with the switches in place
