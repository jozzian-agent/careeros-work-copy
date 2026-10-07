"""Regression coverage for LLMClient.create (review fix round, finding 6):
the default /v1 chat-completions mode previously had only indirect coverage
through ingest.py/company_lookup.py call sites, and native mode (Ollama's
/api/chat) had none at all. Every test here mocks LLMClient.opener.open
directly -- the one seam between this module and the actual network -- so
no live network call happens anywhere in this file.

conftest.py's suite-wide `offline` fixture patches urllib.request.build_opener
itself to raise (a blanket guard against any test accidentally reaching the
network), which also makes constructing a real LLMClient impossible as-is --
exactly why this class had no direct regression coverage before. _make_client
below restores the real build_opener just long enough to construct the
client, then _capture_opener replaces that real opener's .open with a fake,
so the client is exercised for real with no socket ever touched."""
import json

from urllib import request as urllib_request

import pytest

from careeros.llm_client import LLMClient, NoRedirect

_REAL_BUILD_OPENER = urllib_request.build_opener


def _make_client(monkeypatch, *args, **kwargs):
    monkeypatch.setattr('urllib.request.build_opener', _REAL_BUILD_OPENER)
    return LLMClient(*args, **kwargs)


class FakeHTTPResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode('utf-8')

    def read(self, amount=-1):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _capture_opener(client, response_payload):
    """Replaces the real opener.open with a fake that records the outgoing
    Request (url, method, headers, decoded JSON body, timeout) and returns a
    canned response, so create()'s request-building and response-parsing can
    be asserted on without any real socket."""
    captured = {}

    def fake_open(req, timeout=None):
        captured['url'] = req.full_url
        captured['method'] = req.get_method()
        captured['headers'] = dict(req.header_items())
        captured['body'] = json.loads(req.data.decode('utf-8'))
        captured['timeout'] = timeout
        return FakeHTTPResponse(response_payload)

    client.opener.open = fake_open
    return captured


def test_default_mode_sends_v1_payload_unchanged_and_parses_response(monkeypatch):
    client = _make_client(monkeypatch, 'https://host.example/v1', 'secret-key')
    captured = _capture_opener(client, {'choices': [{'message': {'content': 'hello'}}]})

    response = client.create(model='m1', messages=[{'role': 'user', 'content': 'hi'}],
                              temperature=0, response_format={'type': 'json_object'},
                              think=False, timeout=7)

    assert captured['url'] == 'https://host.example/v1/chat/completions'
    assert captured['method'] == 'POST'
    assert captured['headers']['Authorization'] == 'Bearer secret-key'
    assert captured['headers']['Content-type'] == 'application/json'
    assert captured['body'] == {'model': 'm1', 'messages': [{'role': 'user', 'content': 'hi'}],
                                 'temperature': 0, 'response_format': {'type': 'json_object'},
                                 'think': False}
    assert captured['timeout'] == 7
    assert response.choices[0].message.content == 'hello'


def test_native_mode_endpoint_payload_translation_and_response_extraction(monkeypatch):
    client = _make_client(monkeypatch, 'https://host.example/v1', 'secret-key', native=True)
    captured = _capture_opener(client, {'message': {'content': 'native-reply'}})

    response = client.create(model='m2', messages=[{'role': 'user', 'content': 'yo'}],
                              temperature=0.3, response_format={'type': 'json_object'},
                              think=True, timeout=9)

    assert captured['url'] == 'https://host.example/api/chat'
    assert captured['body'] == {'model': 'm2', 'stream': False, 'think': True,
                                 'messages': [{'role': 'user', 'content': 'yo'}],
                                 'format': 'json', 'options': {'temperature': 0.3}}
    assert captured['timeout'] == 9
    assert response.choices[0].message.content == 'native-reply'


def test_native_mode_endpoint_construction_without_v1_suffix(monkeypatch):
    # base_url with no trailing /v1 must not have characters chopped off it.
    client = _make_client(monkeypatch, 'https://host.example', 'secret-key', native=True)
    captured = _capture_opener(client, {'message': {'content': 'ok'}})
    client.create(model='m', messages=[], temperature=0, response_format={}, think=False)
    assert captured['url'] == 'https://host.example/api/chat'


def test_native_mode_omits_optional_keys_when_not_supplied(monkeypatch):
    # No `response_format`/`temperature` in the caller's payload: 'format'
    # and 'options' must not appear at all, not appear as empty/None.
    client = _make_client(monkeypatch, 'https://host.example/v1', 'secret-key', native=True)
    captured = _capture_opener(client, {'message': {'content': 'ok'}})
    client.create(model='m', messages=[{'role': 'user', 'content': 'hi'}])
    assert captured['body'] == {'model': 'm', 'stream': False, 'think': False,
                                 'messages': [{'role': 'user', 'content': 'hi'}]}


@pytest.mark.parametrize('native', [False, True])
def test_no_redirect_handler_retained_in_both_modes(monkeypatch, native):
    # Credentials must never follow a redirect to another endpoint, in
    # either mode -- the opener is built identically regardless of `native`.
    client = _make_client(monkeypatch, 'https://host.example/v1', 'secret-key', native=native)
    assert any(isinstance(handler, NoRedirect) for handler in client.opener.handlers)
    with pytest.raises(RuntimeError):
        NoRedirect().redirect_request(None, None, 301, 'Moved', {}, 'https://evil.example')


@pytest.mark.parametrize('native,payload', [
    (False, {}),  # default mode: no 'choices' key at all
    (True, {}),   # native mode: no 'message' key at all
])
def test_malformed_response_raises_same_error_class_in_both_modes(monkeypatch, native, payload):
    client = _make_client(monkeypatch, 'https://host.example/v1', 'secret-key', native=native)
    _capture_opener(client, payload)
    with pytest.raises(KeyError):
        client.create(model='m', messages=[], temperature=0, response_format={}, think=False)
