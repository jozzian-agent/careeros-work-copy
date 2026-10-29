"""What this app sends to a language model, pinned.

`careeros.llm_registry` is the list of the places that put text in front of
a model, and `docs/as-built/llm.md` is written out of that list plus a
reading of the code it names. These tests are the third reading, and they
hold the other two to the sets written out below rather than to each other:
a prompt that starts carrying a job's `notes`, a config function that starts
reading a fifth variable, or a fourth function that calls a model client
fails here first, before the generator, so the failure names the field, the
variable or the function rather than a diff in a generated file.

That is on purpose and it is why the sets are spelled out in this file.
Reading them out of the registry would make the test agree with whatever the
registry says, which is exactly what a doc about what leaves the machine must
not do.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import gen_docs  # noqa: E402

from careeros import llm_registry  # noqa: E402

#: Every function in `careeros/`, `scripts/` and the one vendored file that
#: sends a prompt of its own, that hands text to a model client. Three send a
#: prompt; the rest build a client or open the request and carry no prompt of
#: their own, which is what `CLIENT_PLUMBING` records.
MODEL_CLIENT_FUNCTIONS = {
    'careeros.classify.llm.Config.client',
    'careeros.classify.llm.call',
    'careeros.enrich.classification_options.create',
    'careeros.ingest._call_llm',
    'careeros.llm_client.get_llm_client',
    'org_intake.enrich._llm_signal',
}

#: Per prompt builder, the keys it reads off each of its own parameters. An
#: empty set is a parameter whose whole value is placed as text.
PROMPT_READS = {
    'careeros.ingest.build_prompt': {
        'description': set(),
        'function_options': {'id', 'keywords', 'label', 'label_de'},
    },
    'careeros.classify.llm.prompt': {
        'subject': {'department', 'employer_name', 'location_text', 'text', 'title'},
        'fields': set(),
    },
    'org_intake.enrich._llm_prompt': {
        'record': {'locations', 'name', 'notes', 'website'},
    },
}

#: Per call site, the stored fields its prompt carries, by record kind.
PROMPT_FIELDS = {
    'Job extraction': {'jobs': {'description'}},
    'Classification, the model layer': {
        'jobs': {'background', 'company', 'description', 'employer_named_in_posting',
                 'location', 'responsibilities', 'skills', 'summary', 'title'},
    },
    'Company sector and size, the world-knowledge fallback': {
        'companies': {'locations', 'name', 'notes', 'website'},
    },
}

#: Per function the registry reads a configuration off, the environment
#: variables it reads. The endpoint config functions and the gate functions
#: together: renaming any one of these names is a change to what the page
#: says and has to be made here too.
ENVIRONMENT_READS = {
    'careeros.llm_client.get_llm_client': {'LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL',
                                           'LLM_NATIVE'},
    'careeros.classify.llm.Config.from_env': {'CLASSIFY_LLM_API_KEY', 'CLASSIFY_LLM_BASE_URL',
                                              'CLASSIFY_LLM_MODEL', 'CLASSIFY_LLM_NATIVE',
                                              'CLASSIFY_LLM_TEMPERATURE'},
    'careeros.enrich.classification_options': {'BACKFILL_USE_LLM'},
    'careeros.ingest._call_llm': {'LLM_TIMEOUT'},
    'careeros.classify.llm.call': set(),
}

#: Fields a prompt must never carry. The generated page computes the whole
#: list; these are the ones worth naming in a test, because each is a thing
#: a reader of this repository would want to be sure about.
NEVER_SENT = (('jobs', 'status'), ('jobs', 'salary'), ('jobs', 'salary_info'),
              ('jobs', 'salary_note'), ('jobs', 'notes'), ('jobs', 'note_list'),
              ('experiences', 'summary'), ('experiences', 'highlights'),
              ('search criteria', 'must_haves'), ('search criteria', 'notes'),
              ('users', 'name'), ('users', 'email'), ('users', 'password_hash'))

SITES = {entry.name: entry for entry in llm_registry.CALL_SITES}


@pytest.fixture(scope='module')
def universe():
    """The stored field allowlists, which is the same reading the data model
    page is written out of."""
    return gen_docs.kind_fields()


# --- 1: nothing calls a model without being on the list --------------------

def test_every_function_that_calls_a_model_client_is_accounted_for():
    """The scan of the product tree, held to the list above. A function that
    hands text to a model client and is in neither the registry's senders nor
    its declared plumbing is a call site nobody wrote down."""
    found = gen_docs.llm_client_calls()
    assert set(found) == MODEL_CLIENT_FUNCTIONS, (
        'the set of functions that call a model client has changed; update '
        'careeros.llm_registry and this test, and regenerate docs/as-built/llm.md'
    )
    registered = {name for entry in llm_registry.CALL_SITES for name in entry.senders}
    unaccounted = set(found) - registered - set(llm_registry.CLIENT_PLUMBING)
    assert unaccounted == set(), (
        f'{sorted(unaccounted)} hands text to a model client and is in no registry entry'
    )


def test_every_registered_sender_still_calls_a_model_client():
    """The other direction: a sender that stopped calling a client is a
    registry entry describing something that no longer happens."""
    found = set(gen_docs.llm_client_calls())
    for entry in llm_registry.CALL_SITES:
        for name in entry.senders:
            assert name in found, f'{entry.name}: the scan finds no model call in {name}'


def test_the_generator_refuses_a_call_site_it_cannot_account_for():
    """And the generator itself aborts on the same reading, so the doc cannot
    be written around an unregistered call."""
    assert gen_docs.check_call_site_accounting() == gen_docs.llm_client_calls()


def test_the_plumbing_is_named_with_a_reason_and_still_exists():
    for name, reason in llm_registry.CLIENT_PLUMBING.items():
        assert reason.strip(), f'{name} is declared plumbing with no reason given'
        _value, remainder = gen_docs.resolve_dotted(name)
        assert remainder == '', f'{name} is declared plumbing and no longer exists'


# --- 2: one test per call site, pinning the fields it sends ----------------

def test_job_extraction_sends_the_description_and_nothing_else_of_a_job(universe):
    entry = SITES['Job extraction']
    builder = gen_docs.registry_function(entry.prompt_builder)
    reads = {name: keys for name, keys in gen_docs.prompt_reads(builder).items()}
    assert reads == PROMPT_READS['careeros.ingest.build_prompt']
    carried, evidence = gen_docs.prompt_fields(entry, universe)
    assert {kind: set(names) for kind, names in carried.items()} \
        == PROMPT_FIELDS['Job extraction']
    # The builder is handed a string by five routes rather than a record, so
    # what stands in for a canary run is that it reads no key off it at all.
    assert reads['description'] == set()
    assert 'reads no key off' in evidence


def test_the_classification_layer_sends_nine_fields_of_a_stored_job(universe):
    entry = SITES['Classification, the model layer']
    builder = gen_docs.registry_function(entry.prompt_builder)
    assert gen_docs.prompt_reads(builder) == PROMPT_READS['careeros.classify.llm.prompt']
    carried, evidence = gen_docs.prompt_fields(entry, universe)
    assert {kind: set(names) for kind, names in carried.items()} \
        == PROMPT_FIELDS['Classification, the model layer']
    assert 'canary run' in evidence


def test_the_company_fallback_sends_four_fields_of_a_company(universe):
    entry = SITES['Company sector and size, the world-knowledge fallback']
    builder = gen_docs.registry_function(entry.prompt_builder)
    assert gen_docs.prompt_reads(builder) == PROMPT_READS['org_intake.enrich._llm_prompt']
    carried, evidence = gen_docs.prompt_fields(entry, universe)
    assert {kind: set(names) for kind, names in carried.items()} \
        == PROMPT_FIELDS['Company sector and size, the world-knowledge fallback']
    assert 'canary run' in evidence


@pytest.mark.parametrize('kind,field', NEVER_SENT)
def test_a_canary_run_finds_no_prompt_carrying(kind, field, universe):
    """Each of these is shown absent the way the page shows it: a record whose
    every field is a sentinel naming itself goes through the real adapter into
    the real prompt builder, and the sentinel for this field is not in what
    comes out."""
    for entry in llm_registry.CALL_SITES:
        if not entry.canary_kind:
            continue
        reached = gen_docs.reaching_fields(entry, universe[entry.canary_kind])
        if entry.canary_kind != kind:
            continue
        assert field not in reached, f'{entry.name} carries the {kind} field {field!r}'


def test_the_never_sent_list_is_the_allowlists_minus_the_prompts(universe):
    """And the whole list on the page is computed, not kept: every field of
    every user-data kind that no prompt carries."""
    _rows, evidence = gen_docs.llm_rows(gen_docs.flask_rules(), universe)
    never = gen_docs.llm_never_sent(universe, evidence)
    for kind, field in NEVER_SENT:
        assert field in never[kind][0], f'the page does not list {kind} {field!r} as never sent'
    for kind in llm_registry.USER_DATA_KINDS:
        assert kind in universe, f'USER_DATA_KINDS names {kind!r}, which is not a record kind'


# --- 3: the variables that decide where a request goes --------------------

def test_the_endpoint_and_gate_variable_names_have_not_changed():
    """Read off the config and gate functions the registry names. A renamed
    variable is a change to how this app is configured, and it has to be made
    here, in the registry and in the generated page together."""
    for name, expected in ENVIRONMENT_READS.items():
        function = gen_docs.registry_function(name)
        assert set(gen_docs.environment_reads(function)) == expected, (
            f'{name} no longer reads {sorted(expected)} out of the environment'
        )


def test_the_registry_names_the_variables_its_config_functions_read():
    for entry in llm_registry.CALL_SITES:
        endpoint = entry.endpoint
        function = gen_docs.registry_function(endpoint.config_function)
        assert set(gen_docs.environment_reads(function)) == set(endpoint.env_vars), (
            f'{entry.name}: the registry and {endpoint.config_function} disagree about '
            'which variables configure the endpoint'
        )
        assert endpoint.base_url_var in endpoint.env_vars


def test_the_registry_names_the_variables_its_gate_functions_read():
    for entry in llm_registry.CALL_SITES:
        function = gen_docs.registry_function(entry.gate_function)
        assert set(gen_docs.environment_reads(function)) == set(entry.gate_reads), (
            f'{entry.name}: the registry and {entry.gate_function} disagree about which '
            'variables are read where the call is gated'
        )
        if entry.gate_var:
            assert entry.gate_var in entry.gate_reads


def test_whether_the_request_leaves_the_server_is_read_off_the_default():
    """The two shapes the code has, and the answer each one gives: a private
    default, and no default at all."""
    local = SITES['Classification, the model layer']
    leaves, how = gen_docs.leaves_the_server(local)
    assert leaves == 'no (LAN) unless CLASSIFY_LLM_BASE_URL points elsewhere'
    assert 'private address' in how
    for name in ('Job extraction', 'Company sector and size, the world-knowledge fallback'):
        leaves, how = gen_docs.leaves_the_server(SITES[name])
        assert leaves == ('conditional: whatever LLM_BASE_URL is configured to '
                          '(owner: third-party provider)')
        assert 'no default in code' in how


def test_the_size_limits_are_the_slices_the_code_applies():
    assert gen_docs.size_limit(SITES['Job extraction']) \
        == '32 000 characters (`careeros.ingest.MAX_DESCRIPTION_CHARS`)'
    assert gen_docs.size_limit(SITES['Classification, the model layer']) \
        == '4 000 characters (`careeros.classify.llm.TEXT_LIMIT`)'
    assert gen_docs.size_limit(
        SITES['Company sector and size, the world-knowledge fallback']) == 'none'


def test_the_gate_flags_are_the_flags_the_code_reads():
    assert gen_docs.gate_flag(SITES['Company sector and size, the world-knowledge fallback']) \
        == 'only with `BACKFILL_USE_LLM=1`'
    assert gen_docs.gate_flag(SITES['Classification, the model layer']) == 'none'
    assert gen_docs.gate_flag(SITES['Job extraction']).startswith('none (the sender also reads')


def test_the_classification_layer_is_reached_by_no_route_and_by_one_script():
    """The fact the page turns on: layer 2 is not wired into the server. The
    accuracy report reaches the same function through `classify.classify` and
    is not a trigger, because it names only `careeros.classify` and asks for
    the rules layer."""
    entry = SITES['Classification, the model layer']
    assert gen_docs.route_triggers(entry, gen_docs.flask_rules()) == []
    assert gen_docs.script_triggers(entry) == ['scripts/run_classification.py']


def test_the_job_routes_are_the_ones_that_reach_job_extraction():
    entry = SITES['Job extraction']
    assert gen_docs.route_triggers(entry, gen_docs.flask_rules()) == [
        'POST /api/jobs/<identifier>/enrich',
        'POST /api/jobs/<identifier>/extract',
        'POST /api/jobs/<identifier>/paste-description',
        'POST /api/jobs/<identifier>/re-extract',
        'POST /api/jobs/intake',
    ]
    assert gen_docs.script_triggers(entry) == []
