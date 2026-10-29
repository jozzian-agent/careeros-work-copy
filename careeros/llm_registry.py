"""Every place this app sends text to a language model, as data.

Three call sites send text to a model, and this module is the list of
them. It holds no logic: each entry names the function that builds the
prompt, the functions that put it on the wire, the parts the prompt is
made of, and the function that reads the endpoint out of the
environment. Everything a reader wants to know on top of that -- which
routes reach a call site, which keys the builder really reads, how much
text it sends, which environment variables decide where the request
goes, and whether the request leaves this server -- is READ OUT OF THE
CODE by `scripts/gen_docs.py`, which writes `docs/as-built/llm.md` from
this list plus that reading, and aborts when the two disagree.

So an entry here is a claim, not a description: the generator and
`tests/test_llm_registry.py` check every field of it against the
source, and a prompt that starts carrying one more field, a config
function that starts reading one more variable, or a new function that
calls a model client fails CI until this list and the generated doc are
changed on purpose.

## Why the list is in careeros/ and not in the generator

Which text leaves this machine is a fact about the product, so it is
stored with the product. Nothing in the running app imports this module:
it is read by the generator and by the tests, exactly like the field
allowlists the data-model page is read out of are read by both the app
and the generator.

## What a part of a prompt is

A prompt is made of three kinds of part, and the distinction is the
whole point of the page:

  * `RECORD` -- text out of a stored record, the only kind that can
    carry what a person typed. `vault_kind` and `vault_fields` say which
    stored fields reach it, and the never-sent section of the page is
    every other field of those kinds.
  * `TAXONOMY` -- a vocabulary the app owns (the function facet options,
    the ISIC letter table). Not about any one person.
  * `FIXED` -- instruction text that is the same on every call.

`parameter` and `keys` are the claim the generator checks: `keys` is
every key the builder reads off that parameter, and `()` means the whole
value is placed as text. A builder that reads one more key than the
entry lists is a doc that has gone stale, and the generator says so
rather than writing it.
"""
from dataclasses import dataclass, field

#: The three kinds of prompt part. See the module docstring.
RECORD = 'record'
TAXONOMY = 'taxonomy'
FIXED = 'fixed'

#: How the generator and the tests exercise one prompt builder: what to
#: pass for each of its parameters. A canary record is a dict whose every
#: value is a sentinel naming its own key, which is how a run finds out
#: which stored fields a prompt really places (and, more to the point,
#: which it cannot). A parameter the registry does not describe is a
#: signature that moved under the doc, and the generator aborts.
CANARY_RECORD = 'canary record'
CANARY_RECORD_LIST = 'canary record list'
CANARY_TEXT = 'canary text'


@dataclass(frozen=True)
class Literal:
    """A value passed to a prompt builder as itself, for a parameter that
    is neither a record nor the text under test: the classification
    prompt needs to be told which fields to ask about before it will
    render at all."""
    value: object


@dataclass(frozen=True)
class PromptPart:
    """One thing a prompt carries."""
    label: str
    kind: str
    #: The builder parameter the value arrives in. Empty for a part the
    #: builder holds itself (a fixed instruction, a table it reads).
    parameter: str = ''
    #: The keys read off that parameter; `()` when the whole value is the
    #: part. Checked against the builder's own syntax tree.
    keys: tuple = ()
    #: Where the value comes from, in words, for the page.
    origin: str = ''
    #: The stored record kind behind a RECORD part, and the fields of it
    #: that reach the prompt. For a call site whose builder is handed the
    #: stored record itself, or reaches it through `adapter`, the fields
    #: are derived by a canary run and this is held against what the run
    #: finds.
    vault_kind: str = ''
    vault_fields: tuple = ()
    #: Set when the fields cannot be derived because the value reaches the
    #: builder as a plain argument from several callers. Then the entry's
    #: own fields stand, the generator checks only that each is a real
    #: field of the kind, and the page says which it is.
    declared: bool = False


@dataclass(frozen=True)
class Endpoint:
    """Where a call site's request goes, as the environment decides it."""
    #: The function that reads the environment. Scanned for the names it
    #: reads and for the default it falls back to.
    config_function: str
    #: The variable that decides the address. The rest configure the call.
    base_url_var: str
    #: Every environment variable `config_function` reads, including the
    #: functions of its own module it calls. Held against the scan.
    env_vars: tuple
    #: Owner-supplied and NOT read from any code: what the owner has
    #: configured this endpoint to in the one environment where no
    #: default exists in code. The page labels it as such.
    owner_note: str = ''


@dataclass(frozen=True)
class CallSite:
    name: str
    #: Dotted name of the function that builds the messages.
    prompt_builder: str
    #: Dotted names of the functions that hand those messages to a client.
    #: Every function in the tree that calls a model client has to be one
    #: of these or be named in CLIENT_PLUMBING below.
    senders: tuple
    #: The `careeros` functions whose reachability from a route handler or
    #: a script means that caller can trigger this call site. A sender
    #: that is a closure (`classification_options`'s `create`) cannot be
    #: resolved by name, so the function that builds it stands in.
    reach_markers: tuple
    parts: tuple
    endpoint: Endpoint
    #: The function that turns a stored record into what the builder takes,
    #: when there is one. Empty when the builder is handed the stored
    #: record itself.
    adapter: str = ''
    #: The stored kind a canary run drives through `adapter` (or straight
    #: into the builder) to find out which fields reach the prompt.
    canary_kind: str = ''
    #: Parameter -> what to pass it. See the CANARY_ constants.
    canary: dict = field(default_factory=dict)
    #: Dotted name of the constant that caps the text, or empty when
    #: nothing does. Held against the slices the builder and the senders
    #: really apply.
    size_limit: str = ''
    #: The function the gate is read off -- the sender itself for a call
    #: site that has no gate -- every environment variable that function
    #: reads, and the one of them that decides whether the call happens at
    #: all. `gate_var` empty means there is no gate, and `gate_reads` is
    #: still every variable the function reads, so a variable that appears
    #: there without a decision about what it does stops the generator.
    gate_function: str = ''
    gate_reads: tuple = ()
    gate_var: str = ''
    #: Anything about the trigger that no call graph can say.
    trigger_note: str = ''


JOB_EXTRACTION = CallSite(
    name='Job extraction',
    prompt_builder='careeros.ingest.build_prompt',
    senders=('careeros.ingest._call_llm',),
    reach_markers=('careeros.ingest._call_llm',),
    parts=(
        PromptPart(
            label='the posting description',
            kind=RECORD,
            parameter='description',
            keys=(),
            origin="the stored posting text, or the body of the paste route's request",
            vault_kind='jobs',
            vault_fields=('description',),
            declared=True,
        ),
        PromptPart(
            label='the function facet option labels',
            kind=TAXONOMY,
            parameter='function_options',
            keys=('id', 'keywords', 'label', 'label_de'),
            origin='the vault tag vocabulary, through `storage.function_facet_options`',
        ),
        PromptPart(
            label='the fixed instructions and the field list',
            kind=FIXED,
            origin='`careeros.ingest` SYSTEM_PROMPT and the FIELDS TO EXTRACT text of the builder',
        ),
    ),
    endpoint=Endpoint(
        config_function='careeros.llm_client.get_llm_client',
        base_url_var='LLM_BASE_URL',
        env_vars=('LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_NATIVE'),
        owner_note='owner: third-party provider',
    ),
    canary={'description': CANARY_TEXT, 'function_options': CANARY_RECORD_LIST},
    size_limit='careeros.ingest.MAX_DESCRIPTION_CHARS',
    gate_function='careeros.ingest._call_llm',
    gate_reads=('LLM_TIMEOUT',),
)

CLASSIFICATION = CallSite(
    name='Classification, the model layer',
    prompt_builder='careeros.classify.llm.prompt',
    senders=('careeros.classify.llm.call',),
    reach_markers=('careeros.classify.llm.call',),
    parts=(
        PromptPart(
            label='Title, Employer, Place and Text',
            kind=RECORD,
            parameter='subject',
            keys=('department', 'employer_name', 'location_text', 'text', 'title'),
            origin='one posting as a subject, built by `careeros.classify.from_vault_job` '
                   'for a stored job (Department is a feed posting only)',
            vault_kind='jobs',
            vault_fields=('background', 'company', 'description', 'employer_named_in_posting',
                          'location', 'responsibilities', 'skills', 'summary', 'title'),
        ),
        PromptPart(
            label='the code lists of the fields asked about',
            kind=TAXONOMY,
            parameter='fields',
            keys=(),
            origin='`careeros.classify.llm` options, over `careeros.taxonomy` entries',
        ),
        PromptPart(
            label='the fixed instructions and the field descriptions',
            kind=FIXED,
            origin='the system text of the builder and `careeros.classify.llm` _ASKS',
        ),
    ),
    endpoint=Endpoint(
        config_function='careeros.classify.llm.Config.from_env',
        base_url_var='CLASSIFY_LLM_BASE_URL',
        env_vars=('CLASSIFY_LLM_API_KEY', 'CLASSIFY_LLM_BASE_URL', 'CLASSIFY_LLM_MODEL',
                  'CLASSIFY_LLM_NATIVE', 'CLASSIFY_LLM_TEMPERATURE'),
    ),
    adapter='careeros.classify.from_vault_job',
    canary_kind='jobs',
    canary={'subject': CANARY_RECORD, 'fields': Literal(('contract',))},
    size_limit='careeros.classify.llm.TEXT_LIMIT',
    gate_function='careeros.classify.llm.call',
    trigger_note='only with `--layer llm` or `--layer all`; the default layer touches '
                 'no network',
)

COMPANY_WORLD_KNOWLEDGE = CallSite(
    name='Company sector and size, the world-knowledge fallback',
    prompt_builder='org_intake.enrich._llm_prompt',
    senders=('org_intake.enrich._llm_signal',
             'careeros.enrich.classification_options.create'),
    reach_markers=('careeros.enrich.classification_options',),
    parts=(
        PromptPart(
            label='Company name, Website, Locations and Notes',
            kind=RECORD,
            parameter='record',
            keys=('locations', 'name', 'notes', 'website'),
            origin='the stored company record itself, as `careeros.enrich.plan_backfill` '
                   'hands it to the capability',
            vault_kind='companies',
            vault_fields=('locations', 'name', 'notes', 'website'),
        ),
        PromptPart(
            label='the ISIC Rev.4 letter table and the fixed instructions',
            kind=FIXED,
            origin='`org_intake.enrich` _llm_system_prompt, over the sections of '
                   '`org_intake.classify`',
        ),
    ),
    endpoint=Endpoint(
        config_function='careeros.llm_client.get_llm_client',
        base_url_var='LLM_BASE_URL',
        env_vars=('LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_NATIVE'),
        owner_note='owner: third-party provider',
    ),
    canary_kind='companies',
    canary={'record': CANARY_RECORD},
    gate_function='careeros.enrich.classification_options',
    gate_reads=('BACKFILL_USE_LLM',),
    gate_var='BACKFILL_USE_LLM',
    trigger_note='and only after every structured signal came back empty '
                 '(`org_intake.enrich` sectors_cascade, size_cascade)',
)

#: The call sites, in the order the page lists them.
CALL_SITES = (JOB_EXTRACTION, CLASSIFICATION, COMPANY_WORLD_KNOWLEDGE)

#: Functions that handle a model client without sending a prompt of their
#: own, and why each is not a call site. The accounting test needs them:
#: it scans for every function that touches a model client and holds the
#: result against the senders above plus these.
CLIENT_PLUMBING = {
    'careeros.llm_client.get_llm_client':
        'builds the client the product call sites use; sends nothing itself',
    'careeros.llm_client.LLMClient.create':
        'the transport: the one function that opens the HTTP request, with no '
        'prompt of its own',
    'careeros.classify.llm.Config.client':
        'builds the client the classification layer uses; sends nothing itself',
}

#: The stored kinds the never-sent section is computed over: everything
#: this app keeps that holds what a person typed or a reading of their
#: postings. The rest of `gen_docs.kind_fields` is the machinery around
#: those records -- tokens, counters, rate-limit windows, the signing key
#: -- and naming it in a list of what a prompt does not carry would say
#: less, not more. Each name has to be a kind the data-model page knows,
#: or the generator aborts.
USER_DATA_KINDS = ('jobs', 'companies', 'experiences', 'notes', 'search criteria', 'users')
