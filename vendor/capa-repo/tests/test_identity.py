"""Organisation identity resolution ladder. Pure store I/O, no network.

Ported from careeros tests/test_company_resolve.py's ladder-confidence
cases (the Flask-level cases there - dedupe, enrichment-thread scheduling,
posting extraction - are product plumbing out of scope for this
capability; see docs/capabilities/org-intake.md's "Not included").

Rule-to-test map (contract Behavior section):
  rule 1  -> test_rule1_*
  rule 2  -> test_rule2_*
  rule 3  -> test_rule3_*
  rule 4  -> test_rule4_*
  rule 5  -> test_rule5_*
  rule 6  -> test_rule6_*
  rule 13 -> test_rule13_*
  rule 14 -> test_rule14_*
  States (review token)  -> test_review_token_*
"""
import pytest

from org_intake import identity
from org_intake.store import InMemoryStore


@pytest.fixture
def store():
    return InMemoryStore()


# --- Rule 1: loose input never rejected, always a definite outcome --------

def test_rule1_stub_time_no_signal_is_pending(store):
    result = identity.resolve_identity(store, url='https://unrecognized.example/careers/role')
    assert result == {'record_id': None, 'link_state': 'pending', 'link_reason': None, 'review': None}


def test_rule1_never_raises_on_malformed_url(store):
    result = identity.resolve_identity(store, url='not a url at all', employer_name='Some Co')
    assert result['link_state'] in ('linked', 'needs_review', 'pending')


def test_m8_never_raises_on_structurally_malformed_bracket_url(store):
    # 'https://[broken' raises ValueError out of urlsplit itself (an
    # unparseable IPv6 host literal) - the ladder must degrade to no ATS
    # evidence and keep going, never raise (M8).
    result = identity.resolve_identity(store, url='https://[broken', employer_name='Some Co')
    assert result['link_state'] in ('linked', 'needs_review', 'pending')


# --- Rule 3: rungs 1-2 are pure local identifier lookups, no network ------

def test_rule3_rung1_ats_tenant_links_before_any_employer_name(store):
    store.save_organisation({'name': 'Northwind Logistics AG',
                             'identifiers': [{'type': 'ats_tenant', 'value': 'greenhouse:northwind',
                                              'provenance': 'scrape'}]})
    result = identity.resolve_identity(store, url='https://boards.greenhouse.io/northwind/jobs/2')
    assert result['link_state'] == 'linked'
    assert result['link_reason'] == 'ats_tenant'


def test_rule3_rung2_domain_links_before_any_employer_name(store):
    store.save_organisation({'name': 'Dune Logistics',
                             'identifiers': [{'type': 'domain', 'value': 'dune-logistics.example',
                                              'provenance': 'scrape'}]})
    result = identity.resolve_identity(store, url='https://dune-logistics.example/careers/role-b')
    assert result['link_state'] == 'linked'
    assert result['link_reason'] == 'domain'


def test_rule3_ats_hosted_url_never_uses_its_own_domain_as_identifier(store):
    # An ATS-hosted URL's domain belongs to the ATS provider, not the
    # employer - rung 2 must never fire for it.
    store.save_organisation({'name': 'Greenhouse Impersonator',
                             'identifiers': [{'type': 'domain', 'value': 'boards.greenhouse.io',
                                              'provenance': 'scrape'}]})
    result = identity.resolve_identity(store, url='https://boards.greenhouse.io/someoneelse/jobs/9')
    assert result['link_state'] == 'pending'  # no ats_tenant on file either


# --- Rule 2: a persisted identifier always wins over a fresh name guess ---

def test_rule2_existing_identifier_wins_over_fresh_name_match_elsewhere(store):
    tenant_owner = store.save_organisation({'name': 'Acme Robotics',
                                            'identifiers': [{'type': 'ats_tenant',
                                                            'value': 'greenhouse:acme', 'provenance': 'scrape'}]})
    store.save_organisation({'name': 'Acme Robotics Copy'})  # an unrelated exact-name duplicate
    result = identity.resolve_identity(
        store, url='https://boards.greenhouse.io/acme/jobs/9', employer_name='Acme Robotics')
    assert result['record_id'] == tenant_owner['id']
    assert result['link_reason'] == 'ats_tenant'


def test_rule2_existing_param_takes_priority_over_rungs_1_2(store):
    other = store.save_organisation({'name': 'Owner Chosen Co'})
    store.save_organisation({'name': 'Domain Match Co',
                             'identifiers': [{'type': 'domain', 'value': 'owner-wins.example',
                                              'provenance': 'scrape'}]})
    result = identity.resolve_identity(
        store, url='https://owner-wins.example/role', existing=(other['id'], 'manual'))
    assert result['record_id'] == other['id']
    assert result['link_reason'] == 'manual'


# --- Rule 4: exact match links; anything short of exact is a candidate ---

def test_rule4_exact_name_match_case_and_punctuation_insensitive(store):
    record = store.save_organisation({'name': 'Globex Corp'})
    result = identity.resolve_identity(
        store, url='https://unrelated.example/role', employer_name='GLOBEX, CORP.')
    assert result == {'record_id': record['id'], 'link_state': 'linked',
                      'link_reason': 'name_exact', 'review': None}


def test_rule4_fuzzy_name_refuses_auto_link_and_reports_scored_candidate(store):
    record = store.save_organisation({'name': 'Acme GmbH'})
    result = identity.resolve_identity(store, url='https://unrelated.example/acme-role', employer_name='Acme')
    assert result['record_id'] is None
    assert result['link_state'] == 'needs_review'
    assert result['link_reason'] == 'fuzzy_name'
    candidates = result['review']['candidates']
    assert candidates and candidates[0]['record_id'] == record['id']
    assert 0 < candidates[0]['score'] < 1.0


def test_rule4_nothing_matches_creates_new_record_and_links(store):
    result = identity.resolve_identity(
        store, url='https://zyphyrion-holdings.example/careers/role', employer_name='Zyphyrion Holdings')
    assert result['link_state'] == 'linked'
    assert result['link_reason'] == 'new_company'
    record = store.load_organisation(result['record_id'])
    assert record['name'] == 'Zyphyrion Holdings'
    assert {'type': 'domain', 'value': 'zyphyrion-holdings.example', 'provenance': 'scrape'} \
        in record['identifiers']


# --- Rule 5: more than one record with the identical exact name is ambiguous

def test_rule5_ambiguous_exact_name_match_needs_review(store):
    first = store.save_organisation({'name': 'Acme Holdings'})
    second = store.save_organisation({'name': 'Acme Holdings'})
    result = identity.resolve_identity(
        store, url='https://unrelated.example/role', employer_name='Acme Holdings')
    assert result['record_id'] is None
    assert result['link_state'] == 'needs_review'
    assert result['link_reason'] == 'ambiguous_exact'
    candidate_ids = {c['record_id'] for c in result['review']['candidates']}
    assert candidate_ids == {first['id'], second['id']}


def test_m4_duplicate_exact_fallback_name_needs_review(store):
    # M4: the fallback_name branch must check ALL exact matches too, not
    # just employer_name's - more than one -> needs_review, never
    # first-wins.
    first = store.save_organisation({'name': 'Same Co'})
    second = store.save_organisation({'name': 'Same Co'})
    result = identity.resolve_identity(
        store, url='https://unrelated.example/role', fallback_name='Same Co')
    assert result['record_id'] is None
    assert result['link_state'] == 'needs_review'
    assert result['link_reason'] == 'ambiguous_exact_name_match'
    candidate_ids = {c['record_id'] for c in result['review']['candidates']}
    assert candidate_ids == {first['id'], second['id']}


# --- Rule 6: a unique ATS-tenant link must agree with the posting's own ---
# employer text before it counts as confirmed.

def test_rule6_employer_differs_from_tenant_with_no_better_candidate(store):
    tenant_owner = store.save_organisation({'name': 'Acme Robotics',
                                            'identifiers': [{'type': 'ats_tenant',
                                                            'value': 'greenhouse:acmerobotics',
                                                            'provenance': 'scrape'}]})
    result = identity.resolve_identity(
        store, url='https://boards.greenhouse.io/acmerobotics/jobs/222',
        employer_name='Totally Unrelated Corp')
    assert result['record_id'] == tenant_owner['id']
    assert result['link_state'] == 'needs_review'
    assert result['link_reason'] == 'employer_differs_from_tenant'


def test_rule6_shared_tenant_when_employer_matches_a_different_record(store):
    tenant_owner = store.save_organisation({'name': 'Acme Robotics',
                                            'identifiers': [{'type': 'ats_tenant',
                                                            'value': 'greenhouse:sharedtenant',
                                                            'provenance': 'scrape'}]})
    other = store.save_organisation({'name': 'Globex Staffing'})
    result = identity.resolve_identity(
        store, url='https://boards.greenhouse.io/sharedtenant/jobs/222', employer_name='Globex Staffing')
    assert result['record_id'] == tenant_owner['id']
    assert result['link_state'] == 'needs_review'
    assert result['link_reason'] == 'shared_tenant'
    candidates = result['review']['candidates']
    assert candidates and candidates[0]['record_id'] == other['id']


def test_rule6_confirming_employer_name_upgrades_reason_to_ats_tenant(store):
    tenant_owner = store.save_organisation({'name': 'Acme Robotics',
                                            'identifiers': [{'type': 'ats_tenant',
                                                            'value': 'greenhouse:confirmed',
                                                            'provenance': 'scrape'}]})
    result = identity.resolve_identity(
        store, url='https://boards.greenhouse.io/confirmed/jobs/2', employer_name='Acme Robotics')
    assert result['record_id'] == tenant_owner['id']
    assert result['link_state'] == 'linked'
    assert result['link_reason'] == 'ats_tenant'


def test_rule6_tenant_employer_names_param_flags_shared_tenant_for_null_employer(store):
    # The contract's settled tenant-sharing-evidence answer: the caller
    # passes already-observed employer names for this (provider, tenant)
    # pair; this module never scans posting/job records itself.
    tenant_owner = store.save_organisation({'name': 'Acme Robotics',
                                            'identifiers': [{'type': 'ats_tenant',
                                                            'value': 'greenhouse:m6shared',
                                                            'provenance': 'scrape'}]})
    result = identity.resolve_identity(
        store, url='https://boards.greenhouse.io/m6shared/jobs/333', employer_name=None,
        existing=(tenant_owner['id'], 'ats_tenant'), tenant_employer_names=['Globex Staffing'])
    assert result['record_id'] == tenant_owner['id']
    assert result['link_state'] == 'needs_review'
    assert result['link_reason'] == 'shared_tenant'


def test_rule6_ats_tenant_identifier_never_taken_over_by_a_second_record(store):
    owner = store.save_organisation({'name': 'Acme',
                                     'identifiers': [{'type': 'ats_tenant', 'value': 'greenhouse:acme',
                                                      'provenance': 'scrape'}]})
    staffing_client = store.save_organisation({'name': 'Globex'})
    updated = identity.add_identifier(store, staffing_client, 'ats_tenant', 'greenhouse:acme', 'scrape')
    assert updated == staffing_client  # no-op: tenant is already owned elsewhere
    assert not any(i['type'] == 'ats_tenant' for i in store.load_organisation(staffing_client['id'])['identifiers'])
    assert store.load_organisation(owner['id'])['identifiers'] == owner['identifiers']


# --- Rule 13/14: rerun is safe to call often, and human edits always win --

def test_rule13_rerun_resolves_pending_record_without_any_name_signal(store):
    record = store.save_organisation({'name': 'Still Pending Co',
                                      'identifiers': [{'type': 'domain', 'value': 'still-pending.example',
                                                       'provenance': 'scrape'}]})
    result = identity.rerun(store, url='https://still-pending.example/role', employer_name=None)
    assert result['record_id'] == record['id']
    assert result['link_state'] == 'linked'
    assert result['link_reason'] == 'domain'


def test_rule14_owner_set_rerun_never_overwrites_the_owner_choice(store):
    store.save_organisation({'name': 'Acme GmbH'})
    other = store.save_organisation({'name': 'Owner Chosen Co'})
    result = identity.rerun(
        store, url='https://unrelated.example/owner-wins-role', employer_name='Acme',
        record_id=other['id'], link_reason='manual', link_state='linked', review=None, owner_set=True)
    assert result == {'record_id': other['id'], 'link_state': 'linked', 'link_reason': 'manual', 'review': None}


def test_rule14_rerun_without_owner_set_re_derives_from_current_evidence(store):
    record = store.save_organisation({'name': 'Acme GmbH'})
    result = identity.rerun(
        store, url='https://unrelated.example/role', employer_name='Acme GmbH',
        record_id=None, link_reason=None, owner_set=False)
    assert result['record_id'] == record['id']
    assert result['link_reason'] == 'name_exact'


# --- Rule 14: identifier/name provenance, owner-taught name_variant -------

def test_rule14_apply_review_teaches_name_variant_and_short_circuits_repeat(store):
    record = store.save_organisation({'name': 'Acme GmbH'})
    first = identity.resolve_identity(store, url='https://unrelated.example/first-acme-role', employer_name='Acme')
    assert first['link_state'] == 'needs_review'

    outcome = identity.apply_review(store, record_id=record['id'], employer_name='Acme')
    assert outcome['rejected'] is False
    resolved = outcome['record']
    assert resolved['id'] == record['id']
    assert {'type': 'name_variant', 'value': 'Acme', 'provenance': 'user'} in resolved['identifiers']

    second = identity.resolve_identity(store, url='https://unrelated.example/second-acme-role', employer_name='Acme')
    assert second['record_id'] == record['id']
    assert second['link_state'] == 'linked'
    assert second['link_reason'] == 'name_exact'
    assert second['review'] is None


def test_rule14_apply_review_create_preserves_discovered_domain_identifier(store):
    store.save_organisation({'name': 'Acme GmbH'})
    created = identity.apply_review(
        store, url='https://unknown.example/m8-role', employer_name='Acme', create={'name': 'Acme Holdings'})['record']
    assert created['name'] == 'Acme Holdings'
    assert {'type': 'domain', 'value': 'unknown.example', 'provenance': 'scrape'} in created['identifiers']


def test_rule14_apply_review_create_omits_ats_tenant_for_shared_tenant_case(store):
    # A staffing-agency create-new must never assert exclusive tenant
    # ownership (rule 6's caveat carried into the review-resolution path).
    created = identity.apply_review(
        store, url='https://boards.greenhouse.io/acme/jobs/999', link_reason='shared_tenant',
        employer_name='Globex', create={'name': 'Globex'})['record']
    assert not any(i['type'] == 'ats_tenant' for i in created['identifiers'])


# --- States: review token is present and distinguishes resolution events --

def test_review_token_present_and_distinct_across_resolution_events(store):
    store.save_organisation({'name': 'Acme GmbH'})
    first = identity.resolve_identity(store, url='https://unrelated.example/a', employer_name='Acme')
    second = identity.resolve_identity(store, url='https://unrelated.example/b', employer_name='Acme')
    assert first['review']['token'] and second['review']['token']
    assert first['review']['token'] != second['review']['token']


# --- M10: apply_review rejects a stale review token -----------------------

def test_m10_apply_review_rejects_stale_token(store):
    record = store.save_organisation({'name': 'Acme GmbH'})
    outcome = identity.apply_review(store, record_id=record['id'], employer_name='Acme',
                                    token='stale-token', current_token='fresh-token')
    assert outcome == {'record': None, 'rejected': True, 'reason': 'stale_review_token'}
    # The stale attempt must not have mutated the record at all.
    assert store.load_organisation(record['id'])['identifiers'] == []


def test_m10_apply_review_accepts_current_token(store):
    record = store.save_organisation({'name': 'Acme GmbH'})
    outcome = identity.apply_review(store, record_id=record['id'], employer_name='Acme',
                                    token='same-token', current_token='same-token')
    assert outcome['rejected'] is False
    assert outcome['record']['id'] == record['id']


def test_m10_apply_review_absent_token_behaves_as_before(store):
    # Per the contract's own apply_review behavior: omitting both token
    # params entirely skips the staleness check, unchanged from before
    # M10 (a caller that does not track tokens at all).
    record = store.save_organisation({'name': 'Acme GmbH'})
    outcome = identity.apply_review(store, record_id=record['id'], employer_name='Acme')
    assert outcome['rejected'] is False
    assert outcome['record']['id'] == record['id']
