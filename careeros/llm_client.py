"""Runtime-configured client for the chat completions API."""
import json
import os
from types import SimpleNamespace
from urllib import request

TIMEOUT = 30


def get_llm_model():
    value = os.environ.get('LLM_MODEL', '').strip()
    if not value:
        raise RuntimeError('LLM_MODEL is not set.')
    return value


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('LLM redirects are disabled.')


class LLMClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        # Credentials must never follow a redirect to another endpoint.
        self.opener = request.build_opener(NoRedirect())
        self.chat = SimpleNamespace(completions=self)

    def create(self, *, timeout=TIMEOUT, **payload):
        req = request.Request(
            self.base_url + '/chat/completions',
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     'Authorization': 'Bearer ' + self.api_key},
            method='POST',
        )
        with self.opener.open(req, timeout=timeout) as response:
            data = json.loads(response.read(2_000_000))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=data['choices'][0]['message']['content']))])


def get_llm_client():
    base_url = os.environ.get('LLM_BASE_URL', '').strip()
    if not base_url:
        raise RuntimeError('LLM_BASE_URL is not set.')
    get_llm_model()
    return LLMClient(base_url, os.environ.get('LLM_API_KEY') or 'not-needed')
