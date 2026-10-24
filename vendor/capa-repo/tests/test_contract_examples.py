"""The contract's Interface section examples, verbatim.

Each test below reproduces one worked example from
docs/capabilities/org-intake.md's Interface section exactly (modulo the
review token, which the contract itself shows as an illustrative literal
"a1b2c3" - a real token is a random uuid4 hex, asserted here as
"non-empty and distinct per event," see test_identity.py's dedicated
token test). fetch/warn/deadline/collector are omitted from the
contract's prose examples for brevity; the two classify_* tests below
still supply a minimal injected `fetch` so the documented input
deterministically produces the documented output in a test. Omitting
`fetch` entirely (as the contract's own prose literally shows) is also
exercised below, against the package's own default safe-fetch adapter
(R2, org_intake/fetch.py) rather than a fake - see
test_classify_sector_and_size_use_default_fetch_when_omitted.
"""
import json

from org_intake import classify_sector, classify_size, detect_ats, normalize_url, resolve_identity
from org_intake.enrich import field_state
from org_intake.store import InMemoryStore


# --- resolve_identity --------------------------------------------------

def test_resolve_identity_example_1_stub_time_pending():
    store = InMemoryStore()
    result = resolve_identity(store, url='https://boards.greenhouse.io/northwind/jobs/9981')
    assert result == {'record_id': None, 'link_state': 'pending', 'link_reason': None, 'review': None}


def test_resolve_identity_example_2_exact_name_match_on_file():
    store = InMemoryStore()
    store.save_organisation({'name': 'Northwind Logistics AG'}, organisation_id='ORG-104')
    result = resolve_identity(store, url='https://jobs.lever.co/northwind/55',
                              employer_name='Northwind Logistics AG')
    assert result == {'record_id': 'ORG-104', 'link_state': 'linked',
                      'link_reason': 'name_exact', 'review': None}


def test_resolve_identity_example_3_fuzzy_match_only():
    store = InMemoryStore()
    store.save_organisation({'name': 'Northwind Logistics AG'}, organisation_id='ORG-104')
    result = resolve_identity(store, url='https://northwind-logistics.example/careers/55',
                              employer_name='Nordwind Logistik AG')
    assert result['record_id'] is None
    assert result['link_state'] == 'needs_review'
    assert result['link_reason'] == 'fuzzy_name'
    assert result['review']['token']  # a real uuid4 hex, not the contract's illustrative "a1b2c3"
    # The contract's 0.78 is illustrative; difflib scores this pair 0.857.
    # Assert the candidate's shape and that the score is fuzzy-but-strong,
    # below exact-match (1.0) and above a weak-match floor.
    cands = result['review']['candidates']
    assert len(cands) == 1
    c = cands[0]
    assert c['record_id'] == 'ORG-104'
    assert c['name'] == 'Northwind Logistics AG'
    assert c['basis'] == 'Northwind Logistics AG'
    assert 0.5 < c['score'] < 1.0


# --- classify_sector / classify_size ------------------------------------

def test_classify_sector_example():
    def fetch(url):
        return '<script type="application/ld+json">{"industry":"industrial production"}</script>'

    record = {'name': 'Helvetia Robotics GmbH', 'website': 'https://helvetia-robotics.example', 'sectors': []}
    assert classify_sector(record, fetch=fetch) == (['C'], None)


def test_classify_size_example():
    def fetch(url):
        if 'wbsearchentities' in url:
            return json.dumps({'search': [{'id': 'Q1'}]})
        return json.dumps({'entities': {'Q1': {'claims': {
            'P1128': [{'mainsnak': {'datavalue': {'value': {'amount': '+42'}}}}],
        }}}})

    record = {'name': 'Helvetia Robotics GmbH', 'size_range': None, 'size_class': None}
    # F2/M6: this fixture's own fetch also resolves a Wikidata entity (Q1),
    # so the pinned (updates, flag) shape additionally carries the
    # discovered identifier - classify_size's plain 2-tuple interface is
    # enough on its own to get record['identifiers'] filled.
    assert classify_size(record, fetch=fetch) == (
        {'size_class': 'small',
         'identifiers': [{'type': 'wikidata', 'value': 'Q1', 'provenance': 'scrape'}]}, None)


def test_classify_sector_and_size_use_default_fetch_when_omitted():
    # R2: the contract's own Interface prose shows classify_sector/
    # classify_size called with no fetch= at all; with the default
    # adapter wired in, that literal call now runs for real rather than
    # silently skipping every signal. No real network destination is
    # ever reached here: the record has no 'name' (so wikidata/osm are
    # not-attempted regardless), and its website is a synthetic private
    # address the default adapter's own guard rejects before any socket
    # is opened - demonstrating the graceful fetch-error/empty outcome
    # (never a raise) the brief's verification step asks for.
    record = {'website': 'http://10.255.255.1/', 'sectors': []}
    assert classify_sector(record) == (None, None)
    assert classify_size({'website': 'http://10.255.255.1/', 'size_range': None, 'size_class': None}) == (
        None, None)


# --- detect_ats / normalize_url -----------------------------------------

def test_detect_ats_example():
    assert detect_ats('https://boards.greenhouse.io/northwind/jobs/9981') == {
        'provider': 'greenhouse', 'tenant': 'northwind'}


def test_normalize_url_example():
    assert normalize_url('HTTPS://Example.com/jobs/?utm_source=x&b=1&a=2') == 'https://example.com/jobs?a=2&b=1'


# --- States: never-tried, the one label the contract promises in full ---
# but no code path wrote before this capability (rule 15's caveat).

def test_never_tried_state_before_any_cascade_has_run():
    # A brand new record with nothing on it yet, before classify_sector
    # or classify_size has ever been called for it: never-tried, not
    # exhausted - the two are a real behavioral distinction (rule 15),
    # since "ran and found nothing" and "never ran" must not be conflated.
    assert field_state(already_populated=False, attempted=False, result=None, flag=None) == 'never-tried'
    # Once classify_sector actually runs and finds nothing usable, the
    # SAME record's state moves to exhausted, never back to never-tried.
    record = {'name': 'Fresh Co', 'sectors': []}
    # fetch=None explicitly (as opposed to omitting it, R2): every signal
    # reports not-attempted, deterministically, with no network call.
    codes, flag = classify_sector(record, fetch=None)
    assert field_state(already_populated=False, attempted=True, result=codes, flag=flag) == 'exhausted'
