"""Runtime-configured client for the chat completions API."""
import json
import os
from types import SimpleNamespace
from urllib import request

TIMEOUT = 120


def get_llm_model():
    value = os.environ.get('LLM_MODEL', '').strip()
    if not value:
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
    base_url = os.environ.get('LLM_BASE_URL', '').strip()
    if not base_url:
        raise RuntimeError('LLM_BASE_URL is not set.')
    get_llm_model()
    return LLMClient(base_url, os.environ.get('LLM_API_KEY') or 'not-needed',
                     native=os.environ.get('LLM_NATIVE') == '1')
