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

Two further things it is not asked (CAREER-129, owner decision
2026-11-02). It is not asked about a dimension whose shipped vocabulary
is incomplete, because such a question cannot be answered or checked --
see `askable`. And for the job family it is not asked for one code: it is
asked for up to three in rank order, because the ambiguous remainder
above is ambiguous precisely in the sense that two or three families fit,
and recording the ranking is more honest than making the model pick. See
`RANKED_FIELDS` and `taxonomy.make_value_record`'s `ranked`.

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
#: The model read the posting, found no family that fits, and named what
#: the posting actually is instead of forcing one (CAREER-131). The
#: record still holds `unknown` -- a proposal is a question for the
#: owner, never a stored value -- but it carries the proposed name in
#: its evidence, which is what makes the queue collectable and
#: countable.
FAMILY_SUGGESTED = 'llm_family_suggested'


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
        """The shared OpenAI-compatible client, pointed at this host."""
        return llm_client.LLMClient(self.base_url, self.api_key, native=self.native)


# --- the prompt ------------------------------------------------------------

#: Field name -> the taxonomy dimension its codes come from. The two
#: workload fields are one dimension, which is why this mapping exists
#: at all. Derived from `rules.FIELDS`, so a field the rules layer gains
#: is mapped here without an edit: `isco_minor_group` (CAREER-130)
#: arrived that way, and what keeps it out of the ask is
#: `DERIVED_FIELDS` below, not an omission here.
DIMENSION_OF = {field: re.sub(r'_(min|max)$', '', field) for field in rules.FIELDS}

#: Fields the pipeline DERIVES from another field the model is already
#: asked about, and therefore never asks for (CAREER-130).
#: `isco_minor_group` is the 3-digit CH-ISCO-19 group of the settled job
#: family, and `classify.settle_minor_group` reads it straight out of
#: occupation_families.yaml where the owner approved it. An answer from
#: the model could only agree with that mapping or contradict it, and a
#: contradiction would be an invented code with a confidence attached.
DERIVED_FIELDS = frozenset({'isco_minor_group'})

#: The fields the model answers with a RANKED list rather than one code
#: (owner decision 2026-11-02, CAREER-129). A Zurich posting routinely
#: reads as two or three job families and the owner's own labelling picks
#: one of them; asking for three in rank order records that instead of
#: making the model pretend to a certainty it does not have. Only the
#: family is ranked -- a posting has one contract and is written in one
#: language, so a list there would be a list of wrong answers.
RANKED_FIELDS = ('occupation_family',)

#: How a ranked field is asked for, in the owner's own words.
RANKED_ASK = (f'list up to {taxonomy.MAX_RANKS}, best first; if none fits, say unknown '
              'and do not force one')

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


def askable(fields):
    """The fields it is worth asking the model about.

    A dimension whose shipped vocabulary is INCOMPLETE is dropped, and
    that is the whole rule -- generic, not a list of field names, so a
    dimension that becomes complete starts being asked without an edit
    here. The ask is unanswerable by construction for an incomplete one:
    `options` has no list to show the model, so it would be asked for a
    code it has never seen, and `taxonomy.valid_code` has no whole list
    to refuse an invented code against, so whatever came back would be
    stored. The run of 2026-11-01 asked 469 such questions across the
    three incomplete dimensions the rules layer writes:
    `isco_unit_group`, `language` and `municipality`. They stay
    rules-and-feed-only until their lists are whole -- the 4-digit unit
    groups are still a 19-group seed after CAREER-130, which loaded the
    3-digit backbone and not them. `canton` has 26 codes and is
    complete, so it is still asked -- the rule is the `complete` flag and
    not a guess about which lists are big.

    `DERIVED_FIELDS` is subtracted on top of that rule, and it answers a
    different question rather than making an exception to the same one.
    Completeness asks whether a code list EXISTS to refuse an invented
    answer against. A derived field asks whether asking could ever beat
    deriving, and for the 3-digit minor group it cannot: the pipeline
    reads it off the owner-approved mapping of the very family the model
    is asked about in the same call. Its list IS complete -- all 130
    groups ship -- so it would otherwise be asked, which is why the
    exclusion has to be named. `isco_unit_group` needs no naming: its
    list is incomplete and that is already enough to keep it out.
    """
    return tuple(field for field in fields
                 if field not in DERIVED_FIELDS and taxonomy.is_complete(DIMENSION_OF[field]))


def options(field):
    """The codes a field may answer with, as a short line.

    Every code, always. Until CAREER-129 an incomplete dimension (and
    any list over sixty) degraded to the prose "a valid <dimension> code
    from the CareerOS taxonomy", which is an invitation to invent one.
    Such a dimension is no longer asked at all (`askable`), so this
    raises for one rather than building a line no caller should send, and
    the sixty-code cap is gone with it -- the 62 job families are the
    longest list the model is shown and they are the whole point of
    asking.

    `unknown` is always allowed and always last, because it is a real
    answer (D4) and the model has to be able to give it instead of
    reaching for the nearest code.
    """
    dimension = DIMENSION_OF[field]
    if not taxonomy.is_complete(dimension):
        raise ValueError(f'{dimension} is an incomplete vocabulary, so the model is never '
                         'asked for one; see careeros.classify.llm.askable')
    listed = [f"{entry['code']} ({entry['label']})" for entry in taxonomy.entries(dimension)]
    return ', '.join(listed + ['unknown'])


def prompt(subject, fields):
    """The one message pair sent per posting.

    One call per posting rather than one per field: the fields share the
    whole text, so asking separately would re-send it once per dimension.
    """
    asked = '\n'.join(
        f'- {field}: {_ASKS.get(field, field)}. '
        + (f'{RANKED_ASK}. Each one of: {options(field)}' if field in RANKED_FIELDS
           else f'One of: {options(field)}')
        for field in fields)
    ranked = [field for field in fields if field in RANKED_FIELDS]
    ranked_note = (f'For {", ".join(ranked)} send "codes" as a list of at most '
                   f'{taxonomy.MAX_RANKS} codes in rank order, best first, and fewer when '
                   'fewer fit. '
                   if ranked else '')
    # CAREER-138 (variant C, owner-approved): choose the CLOSEST family
    # whenever one reasonably fits, answer unknown only when none fits
    # at all -- and then name the role. CAREER-131's "never force the
    # closest family" made the model refuse 14 of 150 postings and
    # propose a role for NONE of them (run of 2026-11-03), which starved
    # the suggestion queue it exists to feed. The proposal is only ever
    # asked for on the field it is about, and only travels in evidence --
    # see `_record`.
    proposal_note = ('Choose the closest occupation_family code whenever one reasonably fits '
                     'the daily work of this posting, even if the fit is not perfect. Answer '
                     '"unknown" only when no family fits the daily work at all -- and then add '
                     'one extra key "proposed_role": a short role name for the job (2-4 words, '
                     'e.g. "Robotics technician"), in that field\'s object only. '
                     if 'occupation_family' in fields else '')
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
            + ranked_note
            + proposal_note
            + ('Apart from "proposed_role" where the rule above asks for it: no other keys '
               'and no prose.\n\n' if proposal_note else 'No other keys and no prose.\n\n')
            + f'POSTING\n{posting}')
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


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


def _answered_codes(answered):
    """The codes one field's answer carries, in the order the model gave.

    `codes` for a ranked field and `code` for a single one, with either
    key accepted for either kind: a model asked for a list sometimes
    sends one string and a model asked for one code sometimes sends a
    list of one, and in both cases the answer is perfectly usable. A
    repeated code is folded out here rather than refused, because
    repeating a code is a formatting slip and not a second opinion.
    """
    raw = answered.get('codes')
    if raw is None:
        raw = answered.get('code')
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    found = []
    for item in raw:
        code = str(item or '').strip()
        if code and code not in found:
            found.append(code)
    return found


def _record(field, answered, *, config, at=None):
    """One field of the model's answer, validated against the taxonomy.

    Three ways an answer is refused, each with its own reason on the
    record: the field is missing, the code is not in the list, or the
    model's own confidence is under the floor. None of the three is a
    dropped value -- D4's `unknown` plus a reason is what a refusal
    looks like.

    VALIDATION IS UNCONDITIONAL since CAREER-129. It used to be skipped
    for a dimension whose shipped list is incomplete, so an invented
    language code was stored with a log line instead of being escalated;
    `askable` now keeps an incomplete dimension out of the ask entirely,
    which means every code reaching here is checkable against a whole
    list and the exception is gone rather than merely narrowed.

    For a ranked field the PRIMARY rank is the answer: an invalid best
    code escalates the whole field, because promoting a later rank into
    its place would be inventing a ranking the model did not give. An
    invalid second or third rank is dropped and named in the evidence
    instead -- a bad second choice is no reason to throw away a good
    first one.
    """
    dimension = DIMENSION_OF[field]
    if not isinstance(answered, dict):
        return _unknown(field, NOT_ANSWERED, at=at)
    codes = _answered_codes(answered)
    quote = str(answered.get('evidence') or '').strip() or None
    confidence = answered.get('confidence')
    confidence = float(confidence) if isinstance(confidence, (int, float)) else None
    if confidence is not None:
        confidence = max(0.0, min(1.0, confidence))
    if not codes:
        return _unknown(field, NOT_ANSWERED, at=at)
    code = codes[0]
    if code == taxonomy.UNKNOWN:
        # CAREER-131: `unknown` on the family field with a proposed_role
        # attached is the suggestion queue's entry point. The value stays
        # unknown -- only the owner approving the proposal makes it a
        # family -- but the record carries the name, a countable review
        # reason, and enough to find the posting again for a re-run.
        proposal = str(answered.get('proposed_role') or '').strip() if (
            field == 'occupation_family') else ''
        if proposal:
            return taxonomy.make_value_record(
                dimension, taxonomy.UNKNOWN, 'llm', confidence=confidence,
                evidence={'rule': 'the model found no family that fits and proposed a role '
                                  'name instead (owner approval required, CAREER-131)',
                          'needs_review': FAMILY_SUGGESTED, 'proposed_role': proposal,
                          'model': config.model, 'quote': quote}, classified_at=at)
        return taxonomy.make_value_record(
            dimension, taxonomy.UNKNOWN, 'llm', confidence=confidence,
            evidence={'rule': 'the model read the posting and found nothing for this field',
                      'model': config.model, 'quote': quote}, classified_at=at)
    if not taxonomy.valid_code(dimension, code):
        return _unknown(field, INVALID_CODE, at=at, extra={'model_answer': code,
                                                           'model': config.model})
    if confidence is not None and confidence < CONFIDENCE_FLOOR:
        return _unknown(field, BELOW_FLOOR, at=at,
                        extra={'model_answer': code, 'model_confidence': confidence,
                               'model': config.model, 'quote': quote})
    evidence = {'rule': f'read from the posting text by {config.model}',
                'model': config.model, 'phrase': quote}
    return taxonomy.make_value_record(
        dimension, code, 'llm', confidence=confidence, evidence=evidence, classified_at=at,
        ranked=_ranked(dimension, field, codes, confidence, evidence))


def _ranked(dimension, field, codes, confidence, evidence):
    """The up-to-three ranked entries for a ranked field, or None.

    None for every other field, which is what keeps a single-valued
    record exactly the shape it has always been.

    Only rank 1 carries the model's confidence. The model states ONE
    confidence for the whole answer, not one per rank, so copying it onto
    the alternatives would turn one number into three claims -- and the
    owner's ruling is that the number is not the signal anyway (the local
    model answers ~0.95 for everything); the rank position is.
    """
    if field not in RANKED_FIELDS:
        return None
    considered = codes[:taxonomy.MAX_RANKS]
    kept = [code for code in considered
            if code != taxonomy.UNKNOWN and taxonomy.valid_code(dimension, code)]
    refused = [code for code in considered if code not in kept]
    if refused:
        evidence['dropped_ranks'] = refused
    return [{'value': code, 'rank': position, 'source': 'llm',
             'confidence': confidence if position == 1 else None}
            for position, code in enumerate(kept, start=1)]
