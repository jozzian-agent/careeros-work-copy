"""Layer 2: the local model, for the remainder the rules could not settle.

CAREER-57 layer 2, and CAREER-18's M1-3 and M1-4 folded into it.

## What it is for, and what it is not for

The rules layer answers most dimensions of most postings for nothing.
What it cannot answer is the genuinely ambiguous remainder -- the four
Head-of-Product postings whose title anchors two job families equally,
the posting that states a contract type in a sentence no table has a
phrase for. Those are what this layer is asked about, one posting at a
time, with ONLY the fields the rules layer left open. Asking the model
about a field a table already settled would spend tokens to produce a
weaker answer: `llm` is the last word in the precedence order, so its
answer would lose anyway.

## The host, and why nothing here fetches in this build

The model runs on the owner's own Ollama host over its OpenAI-compatible
API, which is why this reuses `careeros.llm_client.LLMClient` rather than
growing a second HTTP client: that class already has the no-redirect
opener, the native-endpoint translation that keeps a reasoning model from
emitting chain-of-thought on every call, and now the token accounting
M1-3 needs.

**No live batch was run against that host in this build.** Its
availability is unconfirmed, so everything here is exercised against
fixtures and fakes, and `scripts/run_classification.py --layer llm`
is the command the owner runs when the host is up. A fake is anything
with `.chat.completions.create(**payload)`, which is the one call this
module makes.

## Measurement (M1-3) and model comparison (M1-4)

Every call returns a metrics block beside its answer: the model, the
wall-clock latency, and the three token counts the server reported
(None, not zero, when it reported none). `Config` is read from the
environment with the owner's host as its default, so comparing two
models is `CLASSIFY_LLM_MODEL=... ` in front of the same command and
nothing else -- which is what M1-4 asks for.

## Escalation (layer 3)

This module never guesses. An answer that will not parse, names a code
the taxonomy does not have, or scores below the confidence floor becomes
an `unknown` record carrying `needs_review` and the reason, exactly like
an ambiguous rule match. Those records are the queue a cheap hosted
fallback would read later; a fallback plugs in by implementing this
module's own `classify(subject, fields, *, client, config)` signature and
being called where the pipeline calls this one. It is deliberately not
built here.
"""
import json
import logging
import os
import re
import time
from dataclasses import dataclass

from careeros import llm_client, taxonomy
from careeros.classify import rules

_logger = logging.getLogger(__name__)

#: The owner's Ollama host, its OpenAI-compatible path, and the literal
#: key that API wants. Every one of them is an environment variable, so
#: pointing the pipeline at another host or another model is a config
#: change and not an edit (M1-4).
DEFAULT_BASE_URL = 'http://192.168.1.10:11434/v1'
DEFAULT_API_KEY = 'ollama'
DEFAULT_MODEL = 'qwen3:30b-a3b'

#: Below this, an answer is recorded but marked for review rather than
#: trusted. The same floor the rules layer names, so both layers are
#: graded against one number.
CONFIDENCE_FLOOR = rules.CONFIDENCE_FLOOR

#: How much of a description the model is shown. A Zurich posting runs to
#: 20 000 characters and the dimensions here are settled in the first
#: screen of one; the cap is what keeps a batch of 200 affordable.
TEXT_LIMIT = 4000

#: Why a value came back unusable. These are the words that reach a
#: record's `needs_review`, so they are a closed list rather than
#: whatever a message happened to say.
UNPARSEABLE = 'llm_unparseable'
INVALID_CODE = 'llm_invalid_code'
BELOW_FLOOR = 'llm_below_floor'
CALL_FAILED = 'llm_failed'
NOT_ANSWERED = 'llm_did_not_answer'


@dataclass(frozen=True)
class Config:
    """Where the model is and which one it is.

    Read from the environment by `from_env`, with the owner's host as the
    default so the documented command line needs no arguments.
    """
    base_url: str = DEFAULT_BASE_URL
    api_key: str = DEFAULT_API_KEY
    model: str = DEFAULT_MODEL
    native: bool = False
    temperature: float = 0.0
    timeout: int = llm_client.TIMEOUT

    @classmethod
    def from_env(cls, environ=None):
        env = environ if environ is not None else os.environ
        return cls(
            base_url=env.get('CLASSIFY_LLM_BASE_URL', DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
            api_key=env.get('CLASSIFY_LLM_API_KEY', DEFAULT_API_KEY).strip() or DEFAULT_API_KEY,
            model=env.get('CLASSIFY_LLM_MODEL', DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            native=env.get('CLASSIFY_LLM_NATIVE') == '1',
            temperature=float(env.get('CLASSIFY_LLM_TEMPERATURE', '0') or 0),
        )

    def client(self):
        """The shared OpenAI-compatible client, pointed at this host.

        The two deploy switches are honored here as well as in
        `llm_client.get_llm_client`, because this layer builds its own
        client from CLASSIFY_LLM_* rather than going through that
        factory: LLM_DISABLED=1 refuses before a socket is opened, and
        LLM_MOCK=1 answers `unknown` for every field asked (see
        MOCK_ANSWER), which is a real answer in this taxonomy (D4) and
        so needs no pretend evidence.
        """
        if llm_client.disabled():
            raise llm_client.LLMDisabled(llm_client.DISABLED_MESSAGE)
        if llm_client.mocked():
            return llm_client.MockLLMClient(mock_answer)
        return llm_client.LLMClient(self.base_url, self.api_key, native=self.native)


# --- the prompt ------------------------------------------------------------

#: Field name -> the taxonomy dimension its codes come from. The two
#: workload fields are one dimension, which is why this mapping exists
#: at all.
DIMENSION_OF = {field: re.sub(r'_(min|max)$', '', field) for field in rules.FIELDS}

#: What each field means, in the words the model is asked in. Short on
#: purpose: a long instruction costs tokens on every posting.
_ASKS = {
    'occupation_family': 'which job family this posting is for',
    'language': 'which language the posting text is WRITTEN in (not which it asks for)',
    'workload_min': 'the lowest Pensum percentage the posting offers',
    'workload_max': 'the highest Pensum percentage the posting offers',
    'contract': 'the kind of contract offered',
    'work_model': 'where the work happens',
    'seniority': 'how far into a career this role sits',
    'employer_type': 'what kind of organisation the employer is',
    'municipality': 'the BFS municipality number of the office',
    'canton': 'the canton number of the office',
}


def options(field):
    """The codes a field may answer with, as a short line.

    `unknown` is always allowed and always last, because it is a real
    answer (D4) and the model has to be able to give it instead of
    reaching for the nearest code.
    """
    dimension = DIMENSION_OF[field]
    listed = [f"{entry['code']} ({entry['label']})" for entry in taxonomy.entries(dimension)]
    if not taxonomy.is_complete(dimension) or len(listed) > 60:
        return f'a valid {dimension} code from the CareerOS taxonomy, or unknown'
    return ', '.join(listed + ['unknown'])


def prompt(subject, fields):
    """The one message pair sent per posting.

    One call per posting rather than one per field: the fields share the
    whole text, so asking separately would re-send it once per dimension.
    """
    asked = '\n'.join(f'- {field}: {_ASKS.get(field, field)}. One of: {options(field)}'
                      for field in fields)
    posting = '\n'.join(filter(None, [
        f"Title: {subject.get('title') or ''}",
        f"Department: {subject.get('department')}" if subject.get('department') else '',
        f"Employer: {subject.get('employer_name')}" if subject.get('employer_name') else '',
        f"Place: {subject.get('location_text')}" if subject.get('location_text') else '',
        f"Text: {(subject.get('text') or '')[:TEXT_LIMIT]}",
    ]))
    system = ('You classify Swiss job postings against a fixed taxonomy. Answer only with codes '
              'from the lists given. When the posting does not say, answer "unknown" -- never '
              'guess the most common answer. Quote the posting phrase that decided each value.')
    user = (f'Classify this posting on these fields:\n{asked}\n\n'
            'Answer with one JSON object, one key per field above, each value an object '
            '{"code": "...", "evidence": "the phrase from the posting", "confidence": 0.0-1.0}. '
            'No other keys and no prose.\n\n'
            f'POSTING\n{posting}')
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


#: Which fields one request asked for, read back off the request itself.
#: `prompt` above writes one "- <field>: ..." line per field, so the ask
#: is recoverable from the payload without the mock being handed the
#: field list separately.
_ASKED = re.compile(r'^- (\w+):', re.MULTILINE)


def mock_answer(payload):
    """What LLM_MOCK=1 answers this request (see Config.client).

    `unknown` for every field asked, at confidence 1.0, which the record
    builder turns into D4's "the model read it and found nothing" rather
    than a refusal or a failure. Deterministic by construction: the
    answer is a function of the ask and of nothing else, so the same
    posting mocks the same way on every run.
    """
    asked = []
    for message in payload.get('messages') or []:
        if isinstance(message, dict) and message.get('role') == 'user':
            asked += _ASKED.findall(str(message.get('content') or ''))
    return json.dumps({field: {'code': taxonomy.UNKNOWN, 'evidence': 'mock mode',
                               'confidence': 1.0} for field in asked})


# --- the call --------------------------------------------------------------

def _content(response):
    return response.choices[0].message.content


def _usage(response):
    reported = getattr(response, 'usage', None)
    if isinstance(reported, dict):
        return dict(reported)
    if reported is None:
        return {'prompt_tokens': None, 'completion_tokens': None, 'total_tokens': None}
    return {name: getattr(reported, name, None)
            for name in ('prompt_tokens', 'completion_tokens', 'total_tokens')}


def _parse(content):
    """The model's answer as a mapping, or None.

    A model wraps JSON in a fence often enough that stripping one is
    worth four lines; anything beyond that is unparseable and says so.
    """
    text = str(content or '').strip()
    fenced = re.search(r'```(?:json)?\s*(.+?)```', text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        answer = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


def call(subject, fields, *, client, config, at=None):
    """One posting, one request. Returns `(answer, metrics)`.

    `answer` is the parsed mapping or None. `metrics` is M1-3's
    measurement and is returned whether the call worked or not, because a
    failed call still cost time.
    """
    metrics = {'model': config.model, 'fields': list(fields), 'latency_ms': None,
               'prompt_tokens': None, 'completion_tokens': None, 'total_tokens': None,
               'ok': False, 'error': None}
    started = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=config.model, messages=prompt(subject, fields),
            temperature=config.temperature, response_format={'type': 'json_object'},
            think=False, timeout=config.timeout)
    except Exception as error:
        metrics['latency_ms'] = round((time.monotonic() - started) * 1000, 1)
        metrics['error'] = f'{type(error).__name__}: {error}'
        _logger.warning('classification model call failed after %sms: %s',
                        metrics['latency_ms'], metrics['error'])
        return None, metrics
    metrics['latency_ms'] = round((time.monotonic() - started) * 1000, 1)
    metrics.update(_usage(response))
    metrics['ok'] = True
    return _parse(_content(response)), metrics


def classify(subject, fields, *, client, config, at=None):
    """The open fields through the local model, as `{field: record}`.

    Every field asked for comes back with a record, because a field the
    model skipped is a fact worth storing: it is `unknown` with
    `needs_review: llm_did_not_answer`, not a silent gap.

    This signature is the escalation seam. A hosted fallback takes the
    same arguments, returns the same mapping, and is called by the
    pipeline on whatever is still flagged after this layer.
    """
    fields = tuple(fields)
    if not fields:
        return {}, {'model': config.model, 'fields': [], 'latency_ms': None, 'ok': True,
                    'prompt_tokens': None, 'completion_tokens': None, 'total_tokens': None,
                    'error': None}
    answer, metrics = call(subject, fields, client=client, config=config, at=at)
    if answer is None:
        reason = CALL_FAILED if metrics.get('error') else UNPARSEABLE
        return {field: _unknown(field, reason, at=at, detail=metrics.get('error'))
                for field in fields}, metrics
    return {field: _record(field, answer.get(field), config=config, at=at)
            for field in fields}, metrics


def _unknown(field, reason, *, at=None, detail=None, extra=None):
    evidence = {'rule': f'the local model layer could not settle this field ({reason})',
                'needs_review': reason, 'model_detail': detail}
    evidence.update(extra or {})
    return taxonomy.make_value_record(DIMENSION_OF[field], taxonomy.UNKNOWN, 'llm',
                                      evidence=evidence, classified_at=at)


def _record(field, answered, *, config, at=None):
    """One field of the model's answer, validated against the taxonomy.

    Three ways an answer is refused, each with its own reason on the
    record: the field is missing, the code is not in the list, or the
    model's own confidence is under the floor. None of the three is a
    dropped value -- D4's `unknown` plus a reason is what a refusal
    looks like.
    """
    dimension = DIMENSION_OF[field]
    if not isinstance(answered, dict):
        return _unknown(field, NOT_ANSWERED, at=at)
    code = str(answered.get('code') or '').strip()
    evidence = str(answered.get('evidence') or '').strip() or None
    confidence = answered.get('confidence')
    confidence = float(confidence) if isinstance(confidence, (int, float)) else None
    if confidence is not None:
        confidence = max(0.0, min(1.0, confidence))
    if not code:
        return _unknown(field, NOT_ANSWERED, at=at)
    if code == taxonomy.UNKNOWN:
        return taxonomy.make_value_record(
            dimension, taxonomy.UNKNOWN, 'llm', confidence=confidence,
            evidence={'rule': 'the model read the posting and found nothing for this field',
                      'model': config.model, 'quote': evidence}, classified_at=at)
    if not taxonomy.valid_code(dimension, code) and taxonomy.is_complete(dimension):
        return _unknown(field, INVALID_CODE, at=at, extra={'model_answer': code,
                                                           'model': config.model})
    if confidence is not None and confidence < CONFIDENCE_FLOOR:
        return _unknown(field, BELOW_FLOOR, at=at,
                        extra={'model_answer': code, 'model_confidence': confidence,
                               'model': config.model, 'quote': evidence})
    return taxonomy.make_value_record(
        dimension, code, 'llm', confidence=confidence,
        evidence={'rule': f'read from the posting text by {config.model}', 'model': config.model,
                  'phrase': evidence}, classified_at=at)
