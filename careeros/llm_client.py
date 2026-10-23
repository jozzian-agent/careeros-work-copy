"""Runtime-configured client for the chat completions API."""
import json
import os
from types import SimpleNamespace
from urllib import request

TIMEOUT = 120

#: The deploy switches (deploy runbook Part 5, `.env.example`). Both are
#: read at call time, never cached, so a restart with a changed env file
#: is all it takes to flip either one.
#:
#:   LLM_MOCK=1      answer from a canned reply and never open a socket.
#:                   What the test suite and CI run on, which is how no
#:                   test needs a key.
#:   LLM_DISABLED=1  refuse before any call, with one message, so an
#:                   environment that has no key says so instead of
#:                   failing at the transport a minute later.
#:
#: LLM_DISABLED wins over LLM_MOCK when both are set: "off" is an
#: instruction about this host and "mock" is only a substitute for the
#: network, so a host told to make no calls makes none, canned or not.
DISABLED_MESSAGE = 'LLM disabled'

#: What mock mode answers when the caller names nothing better: one empty
#: JSON object, because every prompt in this app asks for
#: `response_format: json_object`. Deliberately empty rather than
#: plausible-looking: a mock host did not read anything, and a canned
#: summary would land on a record as if it had. A caller whose prompt
#: shape needs a fuller answer passes its own (see MockLLMClient).
MOCK_CONTENT = '{}'

#: The model name mock mode reports when LLM_MODEL is unset, so a mock
#: run needs no configuration at all. A set LLM_MODEL still wins, so a
#: mock run can carry the real model's name when that is what is being
#: measured.
MOCK_MODEL = 'mock-model'


class LLMDisabled(RuntimeError):
    """Raised in place of making a call when LLM_DISABLED=1.

    A RuntimeError subclass because that is what the callers already
    catch for "there is no usable LLM here" (ingest._call_llm's
    `not_configured`), so switching an environment off is an outcome the
    app already knows how to report rather than a new failure mode.
    """


def disabled():
    """Whether this environment refuses LLM calls (LLM_DISABLED=1)."""
    return os.environ.get('LLM_DISABLED') == '1'


def mocked():
    """Whether this environment answers from canned replies (LLM_MOCK=1).

    False whenever LLM_DISABLED is also set, per the resolution order
    noted above.
    """
    return not disabled() and os.environ.get('LLM_MOCK') == '1'


class MockLLMClient:
    """A client that answers without a socket (LLM_MOCK=1).

    Same call surface as LLMClient: `.chat.completions.create(**payload)`
    returning an object with `.choices[0].message.content` and `.usage`,
    so nothing downstream can tell the difference.

    `content` is either the reply string or a callable taking the request
    payload and returning one. The callable is what lets one mock serve
    two prompt shapes -- extraction asks for job fields, classification
    asks for one record per field -- without this class knowing either
    prompt.

    Every payload is appended to `calls`, so a test can assert on what
    was asked without a transport to inspect.
    """

    def __init__(self, content=MOCK_CONTENT):
        self.content = content
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, *, timeout=TIMEOUT, **payload):
        self.calls.append(payload)
        reply = self.content(payload) if callable(self.content) else self.content
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage={'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0})


def get_llm_model():
    if disabled():
        raise LLMDisabled(DISABLED_MESSAGE)
    value = os.environ.get('LLM_MODEL', '').strip()
    if not value:
        if mocked():
            return MOCK_MODEL
        raise RuntimeError('LLM_MODEL is not set.')
    return value


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('LLM redirects are disabled.')


class LLMClient:
    """OpenAI-compatible chat client. With native=True the same call
    signature is served by Ollama's native /api/chat endpoint instead of
    /v1/chat/completions: the OpenAI-compat layer of Ollama (verified on
    0.34.4) silently ignores the `think` parameter and reasoning-capable
    models keep emitting chain-of-thought tokens on every call (~20s for a
    trivial reply vs ~1s natively with think off). The payload keys used
    by callers (model, messages, temperature, response_format json_object,
    think) are translated; anything else is dropped rather than guessed
    at. Enable with LLM_NATIVE=1 when LLM_BASE_URL points at Ollama."""

    def __init__(self, base_url, api_key, native=False):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.native = native
        # Credentials must never follow a redirect to another endpoint.
        self.opener = request.build_opener(NoRedirect())
        self.chat = SimpleNamespace(completions=self)

    def _native_payload(self, payload):
        body = {'model': payload.get('model'), 'stream': False,
                'think': bool(payload.get('think'))}
        if payload.get('messages') is not None:
            body['messages'] = payload['messages']
        response_format = payload.get('response_format') or {}
        if isinstance(response_format, dict) and response_format.get('type') == 'json_object':
            body['format'] = 'json'
        options = {}
        if payload.get('temperature') is not None:
            options['temperature'] = payload['temperature']
        if options:
            body['options'] = options
        return body

    def _endpoint(self):
        if not self.native:
            return self.base_url + '/chat/completions'
        root = self.base_url[:-3] if self.base_url.endswith('/v1') else self.base_url
        return root + '/api/chat'

    def create(self, *, timeout=TIMEOUT, **payload):
        if self.native:
            payload = self._native_payload(payload)
        req = request.Request(
            self._endpoint(),
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     'Authorization': 'Bearer ' + self.api_key},
            method='POST',
        )
        with self.opener.open(req, timeout=timeout) as response:
            data = json.loads(response.read(2_000_000))
        if self.native:
            content = data['message']['content']
        else:
            content = data['choices'][0]['message']['content']
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=content))], usage=usage(data))


def usage(data):
    """Token counts from either endpoint, under one set of names.

    CAREER-57 M1-3 measures tokens and latency per call, and the two
    endpoints report the same three numbers under different keys:
    OpenAI-compat says `usage.prompt_tokens`, Ollama's native `/api/chat`
    says `prompt_eval_count`. A response that reports neither yields
    None per field rather than a zero, because "the server did not say"
    and "no tokens" are different facts.
    """
    reported = data.get('usage') or {}
    prompt = reported.get('prompt_tokens', data.get('prompt_eval_count'))
    completion = reported.get('completion_tokens', data.get('eval_count'))
    total = reported.get('total_tokens')
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return {'prompt_tokens': prompt, 'completion_tokens': completion, 'total_tokens': total}


def get_llm_client():
    """The client this environment's configuration asks for.

    Both switches are resolved here, before anything reads LLM_BASE_URL,
    so neither a mock nor a disabled run needs a base URL, a model or a
    key to be set at all.
    """
    if disabled():
        raise LLMDisabled(DISABLED_MESSAGE)
    if mocked():
        return MockLLMClient()
    base_url = os.environ.get('LLM_BASE_URL', '').strip()
    if not base_url:
        raise RuntimeError('LLM_BASE_URL is not set.')
    get_llm_model()
    return LLMClient(base_url, os.environ.get('LLM_API_KEY') or 'not-needed',
                     native=os.environ.get('LLM_NATIVE') == '1')
