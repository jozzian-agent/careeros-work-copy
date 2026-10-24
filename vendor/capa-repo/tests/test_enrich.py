"""Sector/size enrichment cascades: SSRF guard, per-signal outcome
accounting, confidence rules, and the per-field state lifecycle.

Ported from careeros tests/test_sectors.py's company_lookup-equivalent
cases (vault/server plumbing - backfill persistence, companies-page
rendering - is product-specific and out of scope).

Rule-to-test map (contract Behavior section):
  rule 9  -> test_rule9_*          (cascade ordering, cheap-to-expensive)
  rule 10 -> test_rule10_*         (sector fill-on-one-confident-result)
  rule 11 -> test_rule11_*         (size never overwrites, conflict flags)
  rule 12 -> test_rule12_*         (every signal reports its own outcome)
  rule 13 -> test_rule13_*         (re-run skips already-populated fields)
  States (per-field lifecycle) -> test_field_state_*
  SSRF/safe-fetch guard -> test_safe_fetch_*
"""
import json
import urllib.error

import pytest

from org_intake import enrich


# --- SSRF / safe-fetch guard -----------------------------------------------

def test_safe_fetch_rejects_private_destination_without_calling_fetch():
    # 10.255.255.1 is a synthetic RFC1918 fixture address, not a real LAN
    # host (S2) - a literal, not runtime-constructed from octets, so it
    # reads clearly as a deliberate private-range test value.
    def fake_fetch(url):
        raise AssertionError('must not be called for a private-network destination')

    result = enrich.fetch_organisation_jsonld('http://10.255.255.1/', fetch=fake_fetch)
    assert result == {}


def test_safe_fetch_rejects_malformed_url():
    # T1: the previous version of this test asserted only "returns None,"
    # which _safe_fetch does both when the guard correctly rejects AND
    # when the guard is broken and fake_fetch's AssertionError gets
    # swallowed by _safe_fetch's own except-Exception clause - vacuous
    # either way. Track calls instead, so the assertion actually lands on
    # "the guard rejected before fetch was ever called."
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return 'unreachable'

    assert enrich._safe_fetch('not-a-url', fake_fetch) is None
    assert calls == []


def test_safe_fetch_rejects_structurally_malformed_bracket_url():
    # M8/M9: 'https://[broken' raises ValueError out of urlsplit itself
    # (an unparseable IPv6 host literal) - _rejects_unsafe_target must
    # catch that and reject, never let it escape.
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return 'unreachable'

    assert enrich._safe_fetch('https://[broken', fake_fetch) is None
    assert calls == []
    assert enrich._rejects_unsafe_target('https://[broken') is True


def test_fetch_organisation_jsonld_reports_fetch_error_not_empty():
    def fetch(url):
        raise ValueError('boom')

    result = enrich.fetch_organisation_jsonld('https://fiction.example', fetch=fetch)
    assert result == {'industry_status': 'error', 'size_status': 'error'}


def test_fetch_organisation_jsonld_extracts_industry_and_employee_count():
    html = '<script type="application/ld+json">{"industry":"Software","numberOfEmployees":42}</script>'
    result = enrich.fetch_organisation_jsonld('https://fiction.example', fetch=lambda url: html)
    assert result == {'industry': 'Software', 'employee_count': 42}


def test_warn_callback_invoked_on_fetch_failure():
    errors = []

    def fetch(url):
        raise ValueError('boom')

    enrich.fetch_organisation_jsonld('https://fiction.example', fetch=fetch, warn=errors.append)
    assert len(errors) == 1 and isinstance(errors[0], ValueError)


# --- Wikidata: dated-statement preference, retry/backoff -------------------

def test_fetch_wikidata_prefers_most_recent_dated_statement():
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {'P1128': [
            {'mainsnak': {'datavalue': {'value': {'amount': '+100'}}},
             'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2020-00-00T00:00:00Z'}}}]}},
            {'mainsnak': {'datavalue': {'value': {'amount': '+250'}}},
             'qualifiers': {'P585': [{'datavalue': {'value': {'time': '+2024-00-00T00:00:00Z'}}}]}},
        ]}}}})

    result = enrich.fetch_wikidata('Fiction Co', fetch=fetch)
    assert result['employee_count'] == 250


def test_fetch_wikidata_retries_429_then_succeeds():
    calls = {'n': 0}
    sleeps = []

    def fetch(url):
        if 'wbsearchentities' in url:
            calls['n'] += 1
            if calls['n'] == 1:
                raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {}, None)
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {}}}})

    result = enrich.fetch_wikidata('Fiction Co', fetch=fetch, sleep=sleeps.append)
    assert calls['n'] == 2
    assert sleeps == [enrich.WIKIDATA_BACKOFF_SECONDS]
    assert 'industry_status' not in result


def test_fetch_wikidata_rate_limited_after_retries_exhausted():
    calls = {'n': 0}

    def fetch(url):
        calls['n'] += 1
        raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {}, None)

    result = enrich.fetch_wikidata('Fiction Co', fetch=fetch, sleep=lambda s: None)
    assert calls['n'] == enrich.WIKIDATA_MAX_RETRIES + 1
    assert result == {'industry': None, 'employee_count': None,
                       'industry_status': 'rate_limited', 'size_status': 'rate_limited'}


def test_fetch_wikidata_no_name_is_not_attempted():
    assert enrich.fetch_wikidata('', fetch=lambda url: None) == {
        'industry': None, 'employee_count': None,
        'industry_status': 'not_attempted', 'size_status': 'not_attempted'}


def test_fetch_osm_matches_shop_only_result():
    def fetch(url):
        return json.dumps({'elements': [{'tags': {'shop': 'books'}}]})

    result = enrich.fetch_osm('Fiction Books', fetch=fetch)
    assert result['industry'] == 'books'


def test_fetch_osm_reports_fetch_error_not_empty():
    # M7: a fetch failure must be distinguishable from "fetched cleanly,
    # nothing there" - _safe_fetch alone (used before the fix) could
    # never report this, since it swallows the exception and returns the
    # same bare None either way.
    def fetch(url):
        raise ValueError('boom')

    assert enrich.fetch_osm('Fiction Co', fetch=fetch) == {'industry_status': 'error'}


def test_fetch_osm_empty_result_is_distinct_from_fetch_error():
    def fetch(url):
        return json.dumps({'elements': []})

    result = enrich.fetch_osm('Fiction Co', fetch=fetch)
    assert result == {'industry': None, 'employee_count': None}


# --- M2: LLM world-knowledge fallback, gated in code -----------------------

class _FakeLlmClient:
    """Minimal stand-in for an OpenAI-shaped chat client: chat.completions
    .create(...) returns an object with .choices[0].message.content."""

    def __init__(self, content):
        self._content = content

    class _Choice:
        def __init__(self, content):
            self.message = type('Message', (), {'content': content})()

    class _Completions:
        def __init__(self, content):
            self._content = content

        def create(self, **kwargs):
            return type('Response', (), {'choices': [_FakeLlmClient._Choice(self._content)]})()

    @property
    def chat(self):
        completions = self._Completions(self._content)
        return type('Chat', (), {'completions': completions})()


def test_m2_llm_signal_not_attempted_without_an_injected_client():
    record = {'name': 'No Client Co'}
    assert enrich._llm_signal(record) == {'industry_status': 'not_attempted', 'size_status': 'not_attempted'}


def test_m2_llm_fallback_skipped_entirely_when_no_client_injected():
    record = {'name': 'Unmatched Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=())
    assert codes is None and flag is None
    assert 'not-attempted' in state['signal_outcomes']


def test_m2_llm_fallback_skipped_when_structured_evidence_already_present():
    def confident(record, fetch=None, warn=None, deadline=None):
        return {'industry': 'Banking and insurance'}

    client = _FakeLlmClient('{"sector": "J", "confidence": "high"}')
    record = {'name': 'Already Matched Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=(confident,), llm_client=client, llm_model='m')
    assert codes == ['K']  # the LLM's "J" never ran: confident was never overridden
    assert flag is None


def test_m2_llm_fallback_runs_and_fills_only_when_structured_evidence_absent():
    client = _FakeLlmClient('{"sector": "K", "sector_label": "Banking and insurance", "confidence": "high"}')
    record = {'name': 'LLM Only Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=(), llm_client=client, llm_model='m')
    assert codes == ['K']
    assert flag is None


def test_m2_llm_response_validated_low_confidence_is_refused_not_trusted():
    client = _FakeLlmClient('{"sector": "K", "confidence": "low"}')
    record = {'name': 'Unsure Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=(), llm_client=client, llm_model='m')
    assert codes is None
    assert flag == enrich.FLAG_SECTOR_AMBIGUOUS


def test_m2_llm_response_validated_unknown_section_letter_is_refused():
    client = _FakeLlmClient('{"sector": "ZZ", "confidence": "high"}')
    record = {'name': 'Bad Letter Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=(), llm_client=client, llm_model='m')
    assert codes is None
    assert flag == enrich.FLAG_SECTOR_AMBIGUOUS


def test_m2_llm_response_validated_self_contradictory_rationale_is_refused():
    # Letter says K (banking) but the rationale's own keywords say J
    # (software) - a confident response that contradicts itself.
    client = _FakeLlmClient(
        '{"sector": "K", "sector_label": "Software and IT services", "confidence": "high"}')
    record = {'name': 'Contradicts Itself Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=(), llm_client=client, llm_model='m')
    assert codes is None
    assert flag == enrich.FLAG_SECTOR_AMBIGUOUS


def test_m2_llm_sector_code_honored_without_keyword_matching():
    client = _FakeLlmClient('{"sector": "K", "confidence": "high"}')  # no sector_label at all
    record = {'name': 'Letter Only Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=(), llm_client=client, llm_model='m')
    assert codes == ['K']
    assert flag is None


# --- M5: an owner-provenanced field is skipped even when it is empty ------

def test_m5_owner_provenanced_empty_sectors_is_not_attempted():
    def would_match(record, fetch=None, warn=None, deadline=None):
        raise AssertionError('must not be called: sectors is owner-protected')

    record = {'name': 'Owner Protected Co', 'sectors': [], 'field_provenance': {'sectors': 'user'}}
    codes, flag, state = enrich.sectors_cascade(record, signals=(would_match,))
    assert (codes, flag) == (None, None)
    assert state['field_state'] == 'filled'  # owner-set counts as "already handled"
    assert all(outcome == 'not-attempted' for outcome in state['signal_outcomes'])


def test_m5_owner_provenanced_empty_size_is_not_attempted():
    def would_match(record, fetch=None, warn=None, deadline=None):
        raise AssertionError('must not be called: size is owner-protected')

    record = {'name': 'Owner Protected Size Co', 'size_range': None, 'size_class': None,
             'field_provenance': {'size': 'user'}}
    updates, flag, state = enrich.size_cascade(record, signals=(would_match,))
    assert (updates, flag) == (None, None)
    assert state['field_state'] == 'filled'
    assert all(outcome == 'not-attempted' for outcome in state['signal_outcomes'])


def test_m5_non_owner_provenance_does_not_protect_an_empty_field():
    def matches(record, fetch=None, warn=None, deadline=None):
        return {'industry': 'Banking and insurance'}

    record = {'name': 'Scrape Provenance Co', 'sectors': [], 'field_provenance': {'sectors': 'scrape'}}
    codes, flag, state = enrich.sectors_cascade(record, signals=(matches,))
    assert codes == ['K']


# --- M6: a resolved Wikidata entity becomes an identifier -----------------

def test_m6_wikidata_identifier_added_when_entity_resolves():
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q12345'}]})
        return json.dumps({'entities': {'Q12345': {'claims': {}}}})

    record = {'name': 'Wikidata Co', 'size_range': None, 'size_class': None, 'identifiers': []}
    updates, flag, state = enrich.size_cascade(record, signals=(enrich._wikidata_signal,), fetch=fetch)
    assert {'type': 'wikidata', 'value': 'Q12345', 'provenance': 'scrape'} in state['identifiers']


def test_m6_wikidata_identifier_deduplicated_against_existing():
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q12345'}]})
        return json.dumps({'entities': {'Q12345': {'claims': {}}}})

    record = {'name': 'Wikidata Co', 'size_range': None, 'size_class': None,
             'identifiers': [{'type': 'wikidata', 'value': 'Q12345', 'provenance': 'scrape'}]}
    updates, flag, state = enrich.size_cascade(record, signals=(enrich._wikidata_signal,), fetch=fetch)
    assert state['identifiers'] == []


def test_m6_no_identifier_added_when_no_entity_resolves():
    def fetch(url):
        return json.dumps({'search': []})

    record = {'name': 'No Entity Co', 'size_range': None, 'size_class': None, 'identifiers': []}
    updates, flag, state = enrich.size_cascade(record, signals=(enrich._wikidata_signal,), fetch=fetch)
    assert state['identifiers'] == []


# --- Rule 9: cascade runs cheap/structured before expensive/fuzzy ---------

def test_rule9_sector_signals_are_evaluated_in_the_given_cheap_to_expensive_order():
    # Every structured sector signal runs (unlike size, sectors has no
    # early exit - two independent confident matches must still be
    # detected as a conflict, rule 10), but the given order (cheap/local
    # first) is preserved in the accounting trail.
    calls = []

    def jsonld_signal(record, fetch=None, warn=None, deadline=None):
        calls.append('jsonld')
        return {'industry': 'Banking and insurance'}

    def wikidata_signal(record, fetch=None, warn=None, deadline=None):
        calls.append('wikidata')
        return {}

    record = {'name': 'Ordered Co', 'sectors': []}
    codes, flag = enrich.external_sectors(record, signals=(jsonld_signal, wikidata_signal))
    assert codes == ['K'] and flag is None
    assert calls == ['jsonld', 'wikidata']


def test_rule9_size_cascade_tries_jsonld_before_wikidata_and_stops_once_matched():
    calls = []

    def jsonld_signal(record, fetch=None, warn=None, deadline=None):
        calls.append('jsonld')
        return {'employee_count': 42}

    def wikidata_signal(record, fetch=None, warn=None, deadline=None):
        calls.append('wikidata')
        return {}

    record = {'name': 'Ordered Co', 'size_range': None, 'size_class': None}
    enrich.size_cascade(record, signals=(jsonld_signal, wikidata_signal))
    assert calls == ['jsonld']  # cheaper signal already matched: the pricier one is skipped


def test_rule9_promotion_runs_before_any_network_signal():
    calls = []

    def tracking_fetch(url):
        calls.append(url)
        return None

    record = {'name': 'Promotable Labs', 'sectors': [], 'enrichment': {'sectors': ['Banking and insurance']}}
    codes, flag, state = enrich.sectors_cascade(record, fetch=tracking_fetch)
    assert calls == []
    assert codes == ['K'] and flag is None
    assert state['field_state'] == 'filled'


# --- R4: size gets the same zero-network promotion tier as sectors --------

def test_r4_size_promotion_runs_before_any_network_signal():
    calls = []

    def tracking_fetch(url):
        calls.append(url)
        return None

    record = {'name': 'Promotable Size Co', 'size_range': None, 'size_class': None,
             'enrichment': {'employee_count': 42}}
    updates, flag, state = enrich.size_cascade(record, fetch=tracking_fetch)
    assert calls == []
    assert updates == {'size_class': 'small'}
    assert flag is None
    assert state['field_state'] == 'filled'


def test_r4_size_network_consulted_only_when_promotion_absent():
    def jsonld(record, fetch=None, warn=None, deadline=None):
        return {'employee_count': 42}

    record = {'name': 'No Size Promotion Co', 'size_range': None, 'size_class': None}
    updates, flag, state = enrich.size_cascade(record, signals=(jsonld,))
    assert updates == {'size_class': 'small'}
    assert flag is None


# --- Rule 10: sector fills only on one confident result --------------------

def test_rule10_two_structured_signals_disagreeing_refuses_and_flags_conflict():
    def software_signal(record, fetch=None, warn=None, deadline=None):
        return {'industry': 'Software and IT services'}

    def banking_signal(record, fetch=None, warn=None, deadline=None):
        return {'industry': 'Banking and insurance'}

    record = {'name': 'Conflicted Labs', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=(software_signal, banking_signal))
    assert codes is None
    assert flag == enrich.FLAG_SECTOR_CONFLICT
    assert state['field_state'] == 'flagged'


def test_rule10_ambiguous_signal_flags_for_review():
    def ambiguous_signal(record, fetch=None, warn=None, deadline=None):
        return {'industry': 'Technology'}  # matches both J and M

    record = {'name': 'Ambiguous Labs', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=(ambiguous_signal,))
    assert codes is None
    assert flag == enrich.FLAG_SECTOR_AMBIGUOUS
    assert state['field_state'] == 'flagged'


def test_rule10_already_populated_sectors_is_a_no_op():
    record = {'name': 'Populated Labs', 'sectors': ['K']}
    codes, flag, state = enrich.sectors_cascade(record)
    assert (codes, flag) == (None, None)
    assert state['field_state'] == 'filled'


# --- Rule 11: size never overwrites; a contradicting count flags ----------

def test_rule11_size_cascade_respects_consistency_with_populated_range():
    def contradicting(record, fetch=None, warn=None, deadline=None):
        return {'employee_count': 500}

    record = {'name': 'Partial Labs', 'size_range': '1-10', 'size_class': None}
    updates, flag, state = enrich.size_cascade(record, signals=(contradicting,))
    assert updates is None
    assert flag == enrich.FLAG_SIZE_INCONSISTENT
    assert state['field_state'] == 'flagged'


def test_rule11_size_cascade_already_populated_pair_is_a_no_op():
    record = {'name': 'Sized Labs', 'size_range': '1-10', 'size_class': 'micro'}
    updates, flag, state = enrich.size_cascade(record)
    assert (updates, flag) == (None, None)
    assert state['field_state'] == 'filled'


def test_rule11_a_count_agreeing_with_a_stored_class_neither_writes_nor_flags():
    """The record already says 'xl' and the evidence says so too, so
    there is nothing to write (the class is the only field anything fills)
    and nothing to flag. Reading the empty fill as a conflict would raise
    FLAG_SIZE_INCONSISTENT on every company whose stored class a signal
    merely confirms."""
    def agrees(record, fetch=None, warn=None, deadline=None):
        return {'employee_count': 1500}

    # 'xl' and not 'large': 1500 people is xl since the class boundaries
    # moved (2026-10-17), and this test needs a count that AGREES.
    record = {'name': 'Confirmed Class Co', 'size_range': None, 'size_class': 'xl'}
    updates, flag, state = enrich.size_cascade(record, signals=(agrees,))
    assert updates is None
    assert flag is None


def test_rule11_a_count_contradicting_a_stored_class_still_flags():
    def contradicts(record, fetch=None, warn=None, deadline=None):
        return {'employee_count': 1500}

    record = {'name': 'Contradicted Class Co', 'size_range': None, 'size_class': 'micro'}
    updates, flag, state = enrich.size_cascade(record, signals=(contradicts,))
    assert updates is None
    assert flag == enrich.FLAG_SIZE_INCONSISTENT
    assert state['field_state'] == 'flagged'


def test_rule11_size_class_hint_fills_the_class_and_nothing_else():
    def hint_only(record, fetch=None, warn=None, deadline=None):
        return {'size_class_hint': 'large'}

    record = {'name': 'Hint Co', 'size_range': None, 'size_class': None}
    updates, flag, state = enrich.size_cascade(record, signals=(hint_only,))
    assert updates == {'size_class': 'large'}
    assert flag is None
    assert state['field_state'] == 'filled'


# --- Rule 12: every signal reports its own outcome -------------------------

def test_rule12_backfill_accounting_distinguishes_rate_limited_from_empty():
    collector = enrich.BackfillAccounting()

    def rate_limited(record, fetch=None, warn=None, deadline=None):
        return {'industry_status': 'rate_limited', 'size_status': 'rate_limited'}

    record = {'id': 'ORG-1', 'name': 'Swept Co', 'sectors': []}
    enrich.sectors_cascade(record, signals=(rate_limited,), collector=collector)
    assert collector.summary()['rate-limited'] == 1
    events = {(e['signal'], e['field'], e['outcome']) for e in collector.events}
    assert ('rate_limited', 'sectors', 'rate-limited') in events
    assert ('promotion', 'sectors', 'empty') in events


def test_rule12_fetch_error_and_empty_are_never_conflated():
    collector = enrich.BackfillAccounting()

    def errors(record, fetch=None, warn=None, deadline=None):
        return {'industry_status': 'error', 'size_status': 'error'}

    record = {'id': 'ORG-2', 'name': 'Errored Co', 'sectors': []}
    enrich.sectors_cascade(record, signals=(errors,), collector=collector)
    summary = collector.summary()
    assert summary['fetch-error'] == 1
    assert summary['empty'] == 1  # the zero-network promotion tier's own 'empty' event


def test_rule12_not_attempted_recorded_for_every_skipped_signal():
    collector = enrich.BackfillAccounting()
    record = {'id': 'ORG-3', 'name': 'Already Sized', 'size_range': '1-10', 'size_class': 'micro'}
    enrich.size_cascade(record, signals=(enrich._jsonld_signal, enrich._wikidata_signal), collector=collector)
    # R4 adds the zero-network promotion tier itself to this accounting,
    # and F9a adds the LLM signal too: 1 (promotion) + 2 (jsonld,
    # wikidata) + 1 (llm), all skipped since the pair is already
    # populated.
    assert collector.summary()['not-attempted'] == 4


# --- Rule 13: re-run never repeats work a field already has ---------------

def test_rule13_size_cascade_breaks_on_first_match_and_skips_the_rest():
    def first(record, fetch=None, warn=None, deadline=None):
        return {'employee_count': 42}

    def second(record, fetch=None, warn=None, deadline=None):
        raise AssertionError('must not be called once an earlier signal already matched')

    record = {'name': 'Break Labs', 'size_range': None, 'size_class': None}
    updates, flag, state = enrich.size_cascade(record, signals=(first, second))
    assert updates == {'size_class': 'small'}


# --- Per-field enrichment state lifecycle (contract States section) -------

def test_field_state_never_tried_before_any_cascade_call():
    assert enrich.field_state(already_populated=False, attempted=False, result=None, flag=None) == 'never-tried'


def test_field_state_filled_when_already_populated_or_result_present():
    assert enrich.field_state(already_populated=True, attempted=True, result=None, flag=None) == 'filled'
    assert enrich.field_state(already_populated=False, attempted=True, result=['K'], flag=None) == 'filled'


def test_field_state_flagged_when_a_flag_is_raised():
    assert enrich.field_state(already_populated=False, attempted=True, result=None,
                              flag=enrich.FLAG_SECTOR_AMBIGUOUS) == 'flagged'


def test_field_state_exhausted_when_every_signal_ran_with_nothing_usable():
    assert enrich.field_state(already_populated=False, attempted=True, result=None, flag=None) == 'exhausted'


def test_field_state_matches_real_cascade_outcomes():
    record = {'name': 'Exhausted Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=())
    assert enrich.field_state(already_populated=bool(record.get('sectors')), attempted=True,
                              result=codes, flag=flag) == 'exhausted'
    # M3: the cascade's own native state agrees with the manually
    # assembled field_state call above.
    assert state['field_state'] == 'exhausted'


# --- Interface doctest-shaped usage: classify_sector/classify_size --------

def test_classify_sector_interface_example_with_injected_fetch():
    def fetch(url):
        return ('<script type="application/ld+json">'
                '{"industry":"industrial production"}</script>')

    record = {'name': 'Helvetia Robotics GmbH', 'website': 'https://helvetia-robotics.example', 'sectors': []}
    assert enrich.classify_sector(record, fetch=fetch) == (['C'], None)


def test_classify_size_interface_example_with_injected_fetch():
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {
            'P1128': [{'mainsnak': {'datavalue': {'value': {'amount': '+42'}}}}],
        }}}})

    record = {'name': 'Helvetia Robotics GmbH', 'size_range': None, 'size_class': None}
    # F2/M6: this fixture's own fetch also resolves a Wikidata entity (Q1),
    # so the pinned (updates, flag) shape additionally carries the
    # discovered identifier.
    assert enrich.classify_size(record, fetch=fetch) == (
        {'size_class': 'small',
         'identifiers': [{'type': 'wikidata', 'value': 'Q1', 'provenance': 'scrape'}]}, None)


def test_classify_sector_and_size_never_call_fetch_when_fetch_is_explicitly_none():
    # Passing fetch=None explicitly (as opposed to omitting it, R2) still
    # means "no network call at all" - every signal reports not-attempted.
    record = {'name': 'No Fetch Co', 'website': 'https://no-fetch.example', 'sectors': []}
    assert enrich.classify_sector(record, fetch=None) == (None, None)
    assert enrich.classify_size(
        {'name': 'No Fetch Co', 'size_range': None, 'size_class': None}, fetch=None) == (None, None)


def test_classify_sector_and_size_use_default_fetch_when_omitted():
    # R2: omitting `fetch` entirely falls back to org_intake/fetch.py's
    # own safe default adapter rather than silently skipping every
    # signal. No real network destination is ever reached here: the
    # record has no 'name', so the only signal that could run at all is
    # the jsonld one (website present); its destination is a private,
    # synthetic address the default adapter's own guard rejects before
    # any socket is opened - demonstrating the graceful degrade (never a
    # raise) without a live network call.
    record = {'website': 'http://10.255.255.1/', 'sectors': []}
    assert enrich.classify_sector(record) == (None, None)
    assert enrich.classify_size({'website': 'http://10.255.255.1/', 'size_range': None, 'size_class': None}) == (
        None, None)


def test_f8c_classify_sector_omitting_fetch_actually_invokes_the_default_adapter(monkeypatch):
    # F8c: the previous version of this test fixture (a literal private
    # IP website) was rejected by enrich.py's own local guard before the
    # injected fetch callable was ever reached, so org_intake.fetch's
    # default adapter never actually ran - a silent zero-call pass. A
    # well-formed-but-unresolvable hostname clears that local guard, so
    # the default adapter itself is the thing that gets invoked here.
    calls = []

    def fake_default_fetch(url, *args, **kwargs):
        calls.append(url)
        raise ValueError('no real network call in this test')

    monkeypatch.setattr(enrich.fetch_adapter, 'default_fetch', fake_default_fetch)
    record = {'website': 'https://example.com/', 'sectors': []}
    result = enrich.classify_sector(record)
    assert calls, 'default_fetch was never invoked through classify_sector'
    assert result == (None, enrich.FLAG_SECTOR_FETCH_ERROR)


# --- F1: the LLM fallback is gated on structured ambiguity too -----------

def test_f1_ambiguous_structured_evidence_suppresses_the_llm():
    def ambiguous_signal(record, fetch=None, warn=None, deadline=None):
        return {'industry': 'Technology'}  # matches both J and M: ambiguous

    llm_calls = []
    client = _FakeLlmClient('{"sector": "K", "confidence": "high"}')

    class _TrackedClient:
        @property
        def chat(self):
            llm_calls.append('called')
            return client.chat

    record = {'name': 'Ambiguous With Llm Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(
        record, signals=(ambiguous_signal,), llm_client=_TrackedClient(), llm_model='m')
    assert codes is None
    assert flag == enrich.FLAG_SECTOR_AMBIGUOUS  # the structured flag stands
    assert llm_calls == []  # the LLM was never actually called
    assert state['signal_outcomes'][-1] == 'not-attempted'


def test_f1_fetch_error_does_not_suppress_the_llm_and_both_outcomes_are_accounted():
    def failing_signal(record, fetch=None, warn=None, deadline=None):
        return {'industry_status': 'error'}

    client = _FakeLlmClient('{"sector": "K", "confidence": "high"}')
    record = {'name': 'Fetch Error With Llm Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(
        record, signals=(failing_signal,), llm_client=client, llm_model='m')
    assert codes == ['K']  # the LLM ran and filled the field
    assert flag is None
    assert 'fetch-error' in state['signal_outcomes']  # the earlier failure stays recorded
    assert 'matched' in state['signal_outcomes']  # the LLM's own match is recorded too


# --- F2: Wikidata identifiers reach the record through classify_size -----

def test_f2_classify_size_public_interface_returns_updates_containing_identifiers():
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q999'}]})
        return json.dumps({'entities': {'Q999': {'claims': {}}}})

    record = {'name': 'Identifier Via Classify Size Co', 'size_range': None, 'size_class': None,
             'identifiers': []}
    updates, flag = enrich.classify_size(record, signals=(enrich._wikidata_signal,), fetch=fetch)
    assert updates == {'identifiers': [{'type': 'wikidata', 'value': 'Q999', 'provenance': 'scrape'}]}
    assert flag is None


def test_f2_classify_size_identifier_deduplicated_against_existing():
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q999'}]})
        return json.dumps({'entities': {'Q999': {'claims': {}}}})

    record = {'name': 'Dedup Via Classify Size Co', 'size_range': None, 'size_class': None,
             'identifiers': [{'type': 'wikidata', 'value': 'Q999', 'provenance': 'scrape'}]}
    updates, flag = enrich.classify_size(record, signals=(enrich._wikidata_signal,), fetch=fetch)
    assert updates is None  # nothing new to report: already on the record
    assert flag is None


# --- F3: the promotion tier validates size_class_hint ---------------------

def test_f3_promotion_rejects_a_size_class_hint_outside_size_classes():
    record = {'name': 'Bad Hint Co', 'size_range': None, 'size_class': None,
             'enrichment': {'size_class_hint': 'INVALID'}}
    updates, flag, state = enrich.size_cascade(record, signals=())
    assert updates is None
    assert flag is None
    assert state['field_state'] == 'exhausted'  # never silently 'filled'


def test_f3_promotion_still_fills_a_valid_size_class_hint():
    record = {'name': 'Good Hint Co', 'size_range': None, 'size_class': None,
             'enrichment': {'size_class_hint': 'small'}}
    updates, flag, state = enrich.size_cascade(record, signals=())
    assert updates == {'size_class': 'small'}
    assert flag is None
    assert state['field_state'] == 'filled'


# --- F5: an OSM fetch failure flags the sector field, not just exhausted -

def test_f5_osm_fetch_failure_flags_the_sector_field():
    def failing_osm(record, fetch=None, warn=None, deadline=None):
        return {'industry_status': 'error'}

    record = {'name': 'OSM Only Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=(failing_osm,))
    assert codes is None
    assert flag == enrich.FLAG_SECTOR_FETCH_ERROR
    assert state['field_state'] == 'flagged'


# --- F6: a structurally malformed URL reports fetch-error, not ok/empty --

def test_f6_safe_fetch_status_reports_fetch_error_for_structurally_malformed_url():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return 'unreachable'

    value, status = enrich._safe_fetch_status('https://[broken', fake_fetch)
    assert value is None
    assert status == 'error'
    assert calls == []


# --- F7: field-level owner provenance on size sub-fields -------------------

def test_f7_user_cleared_size_class_is_never_filled_by_any_count():
    def matches(record, fetch=None, warn=None, deadline=None):
        return {'employee_count': 42}

    record = {'name': 'User Cleared Size Class Co', 'size_range': None, 'size_class': None,
             'field_provenance': {'size_class': 'user'}}
    updates, flag, state = enrich.size_cascade(record, signals=(matches,))
    # The class is the only size field the cascade writes, and the owner
    # cleared it, so a matching count writes nothing at all - it no longer
    # has the retired numeric scale to land in instead.
    assert updates is None
    assert flag is None


def test_f7_user_cleared_size_class_alone_does_not_block_the_whole_field():
    # Only size_class is locked; size_range is neither populated nor
    # owner-provenanced, so the cascade must still run (not early-exit as
    # fully "protected") - its signals are what a conflict against the
    # owner's decision would be flagged from (G4).
    calls = []

    def tracking_signal(record, fetch=None, warn=None, deadline=None):
        calls.append('called')
        return {'employee_count': 7}

    record = {'name': 'Partial Lock Co', 'size_range': None, 'size_class': None,
             'field_provenance': {'size_class': 'user'}}
    enrich.size_cascade(record, signals=(tracking_signal,))
    assert calls == ['called']


# --- G1: ambiguous structured size evidence flags, and suppresses the ----
#         LLM with a recorded reason (mirrors the sector suppression test
#         above, test_f1_ambiguous_structured_evidence_suppresses_the_llm)

def test_g1_ambiguous_structured_size_evidence_flags_and_suppresses_the_llm():
    def ambiguous_signal(record, fetch=None, warn=None, deadline=None):
        return {'size_status': 'ambiguous'}

    llm_calls = []
    client = _FakeLlmClient('{"confidence": "high", "size_hint": "small"}')

    class _TrackedClient:
        @property
        def chat(self):
            llm_calls.append('called')
            return client.chat

    collector = enrich.BackfillAccounting()
    record = {'name': 'Ambiguous Size With Llm Co', 'size_range': None, 'size_class': None}
    updates, flag, state = enrich.size_cascade(
        record, signals=(ambiguous_signal,), collector=collector, llm_client=_TrackedClient(), llm_model='m')
    assert updates is None
    assert flag == enrich.FLAG_SIZE_AMBIGUOUS  # the structured flag stands, never a silent 'exhausted'
    assert state['field_state'] == 'flagged'
    assert llm_calls == []  # the LLM was never actually called
    suppression = next(e for e in collector.events if e['signal'] == 'llm' and e['field'] == 'size')
    assert suppression['outcome'] == 'not-attempted'
    assert suppression['reason'] == 'structured-ambiguity'


def test_g1_sector_ambiguity_suppression_also_records_the_reason():
    # Same reason now recorded on the sector side too (rule 9), where the
    # existing F1 test (test_f1_ambiguous_structured_evidence_suppresses_
    # the_llm, above) only checked the not-attempted outcome, not why.
    def ambiguous_signal(record, fetch=None, warn=None, deadline=None):
        return {'industry': 'Technology'}  # matches both J and M: ambiguous

    collector = enrich.BackfillAccounting()
    record = {'name': 'Ambiguous Sector Reason Co', 'sectors': []}
    enrich.sectors_cascade(record, signals=(ambiguous_signal,), collector=collector,
                           llm_client=_FakeLlmClient('{"sector": "K", "confidence": "high"}'), llm_model='m')
    suppression = next(e for e in collector.events if e['signal'] == 'llm' and e['field'] == 'sectors')
    assert suppression['outcome'] == 'not-attempted'
    assert suppression['reason'] == 'structured-ambiguity'


# --- G2: the sector cascade also collects Wikidata identifiers -----------

def test_g2_sectors_cascade_collects_wikidata_identifiers():
    def wikidata_lookup(record, fetch=None, warn=None, deadline=None):
        return {'wikidata_id': 'Q777'}

    record = {'name': 'Sector Identifier Co', 'sectors': []}
    codes, flag, state = enrich.sectors_cascade(record, signals=(wikidata_lookup,))
    assert state['identifiers'] == [{'type': 'wikidata', 'value': 'Q777', 'provenance': 'scrape'}]


# --- G3: classify_size's identifier updates MERGE, never replace ---------

def test_g3_classify_size_identifiers_merge_with_existing_not_replace():
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q999'}]})
        return json.dumps({'entities': {'Q999': {'claims': {}}}})

    record = {'name': 'Merge Identifiers Co', 'size_range': None, 'size_class': None,
             'identifiers': [{'type': 'domain', 'value': 'merge-identifiers.example', 'provenance': 'user'}]}
    updates, flag = enrich.classify_size(record, signals=(enrich._wikidata_signal,), fetch=fetch)
    # Existing (owner-provenanced) identifier first, new suggestion after,
    # no duplicates - applying `updates` wholesale is safe.
    assert updates == {'identifiers': [
        {'type': 'domain', 'value': 'merge-identifiers.example', 'provenance': 'user'},
        {'type': 'wikidata', 'value': 'Q999', 'provenance': 'scrape'},
    ]}
    assert flag is None


# --- G4: the size-class lock must not swallow the conflict check ---------

def test_g4_locked_populated_size_class_still_flags_conflicting_hint():
    def hint_only(record, fetch=None, warn=None, deadline=None):
        return {'size_class_hint': 'small'}

    record = {'name': 'Locked Conflict Co', 'size_range': None, 'size_class': 'large'}
    updates, flag, state = enrich.size_cascade(record, signals=(hint_only,))
    assert updates is None  # never overwritten: size_class is locked (already populated)
    assert flag == enrich.FLAG_SIZE_INCONSISTENT
    assert state['field_state'] == 'flagged'


def test_g4_locked_populated_size_class_consistent_hint_is_a_quiet_no_op():
    def hint_only(record, fetch=None, warn=None, deadline=None):
        return {'size_class_hint': 'large'}

    record = {'name': 'Locked Consistent Co', 'size_range': None, 'size_class': 'large'}
    updates, flag, state = enrich.size_cascade(record, signals=(hint_only,))
    assert updates is None
    assert flag is None  # the hint agrees: no conflict, no write needed


# --- G5: a structured size match records the LLM as not-attempted too ----

def test_g5_structured_size_match_records_llm_not_attempted():
    def matches(record, fetch=None, warn=None, deadline=None):
        return {'employee_count': 42}

    collector = enrich.BackfillAccounting()
    record = {'name': 'Structured Match Co', 'size_range': None, 'size_class': None}
    enrich.size_cascade(record, signals=(matches,), collector=collector)
    llm_events = [e for e in collector.events if e['signal'] == 'llm' and e['field'] == 'size']
    assert len(llm_events) == 1
    assert llm_events[0]['outcome'] == 'not-attempted'


# --- H1: classify_sector's public interface also surfaces identifiers ----

def test_h1_classify_sector_public_interface_surfaces_merged_identifiers():
    def wikidata_lookup(record, fetch=None, warn=None, deadline=None):
        return {'wikidata_id': 'Q999'}

    record = {'name': 'Sector Identifier Via Classify Co', 'sectors': [],
             'identifiers': [{'type': 'domain', 'value': 'sector-identifier.example', 'provenance': 'user'}]}
    updates, flag = enrich.classify_sector(record, signals=(wikidata_lookup,), fetch=None)
    # Existing (owner-provenanced) identifier first, new suggestion after,
    # no duplicates - mirrors classify_size's own G3 merge behavior.
    assert updates == {'identifiers': [
        {'type': 'domain', 'value': 'sector-identifier.example', 'provenance': 'user'},
        {'type': 'wikidata', 'value': 'Q999', 'provenance': 'scrape'},
    ]}
    assert flag is None


def test_h1_classify_sector_with_no_identifiers_keeps_the_plain_list_shape():
    # No identifier was discovered, so the pinned (codes_or_None, flag)
    # shape stays exactly as the contract documents - unchanged from
    # before H1.
    def fetch(url):
        return ('<script type="application/ld+json">'
                '{"industry":"industrial production"}</script>')

    record = {'name': 'No Identifier Co', 'website': 'https://no-identifier.example', 'sectors': []}
    assert enrich.classify_sector(record, fetch=fetch) == (['C'], None)


# --- H2: _merge_identifiers also dedupes pre-existing duplicates ---------

def test_h2_merge_identifiers_dedupes_pre_existing_duplicates_too():
    record = {'identifiers': [
        {'type': 'domain', 'value': 'dup.example', 'provenance': 'user'},
        {'type': 'domain', 'value': 'dup.example', 'provenance': 'user'},
    ]}
    merged = enrich._merge_identifiers(record, [{'type': 'wikidata', 'value': 'Q999', 'provenance': 'scrape'}])
    assert merged == [
        {'type': 'domain', 'value': 'dup.example', 'provenance': 'user'},
        {'type': 'wikidata', 'value': 'Q999', 'provenance': 'scrape'},
    ]
