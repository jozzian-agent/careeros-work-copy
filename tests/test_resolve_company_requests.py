"""Protects the nightly company request pass
(`scripts/resolve_company_requests.py`) and the shared resolution it runs
on (`careeros.company_requests`): which names it links, which it refuses
to guess at, what the auto-create switch changes, that a dry run writes
nothing, that a second pass changes nothing, and that it never logs a
name.

Synthetic fixture vaults throughout, built record by record; no test
here reaches the network (tests/conftest.py's offline fixture blocks it
process-wide, and the cascade switch it turns off is the only thing in
this pass that would fetch).
"""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import resolve_company_requests as resolver  # noqa: E402

from careeros import company_requests, vault  # noqa: E402

REQUESTER = 'USER-002'

#: A name no other fixture in this repository uses, so the caplog test
#: below can assert its absence and mean it.
DISTINCTIVE = 'Zqwibble Thornfax AG'


@pytest.fixture
def root(tmp_path):
    """An empty vault with the one directory every reader needs."""
    root = tmp_path / 'vault'
    (root / 'jobs').mkdir(parents=True)
    return root


def asking_job(root, index=0, **fields):
    """A job whose company ask is open: pending link, an employer name,
    the reading finished. Every one of those but the name is a default."""
    return vault.save_job(root, {
        'title': f'Pending Link {index}',
        'url': f'https://pending.example/jobs/{index}',
        'employer_named_in_posting': 'Pending Employer AG',
        vault.OWNER_FIELD: REQUESTER} | fields)


def filed(root, job, name):
    return vault.save_company_request(root, {
        'job_id': job['id'], 'name': name, vault.OWNER_FIELD: REQUESTER})


def request_by_id(root, identifier):
    return next(r for r in vault.list_company_requests(root) if r['id'] == identifier)


# --- Rung 1: the exact name ------------------------------------------------

def test_an_exact_name_links_the_job_and_settles_the_request(root):
    company = vault.save_company(root, {'name': 'Northwind AG'})
    job = asking_job(root)
    request = filed(root, job, 'Northwind AG')

    counts, created = resolver.resolve(root)

    assert counts == {'linked': 1, 'created': 0, 'needs_admin': 0, 'rejected': 0}
    assert created == []
    stored = vault.load_job(root, job['id'])
    assert stored['company_id'] == company['id']
    assert stored['company_link_state'] == 'linked'
    assert stored['company_link_reason'] == 'manual'
    assert stored['company_review'] is None
    # The provenance resolve_review writes, which is what keeps a later
    # re-run of the ladder from undoing the answer.
    assert stored['field_provenance']['company_id'] == 'user'
    settled = request_by_id(root, request['id'])
    assert settled['status'] == 'linked'
    assert settled['resolved_company_id'] == company['id']


def test_a_name_variant_the_owner_taught_counts_as_the_name(root):
    """Rung 1 matches a company's name_variant identifiers too, which is
    how a fuzzy case the owner once resolved by hand answers itself."""
    company = vault.save_company(root, {
        'name': 'Northwind Systems',
        'identifiers': [{'type': 'name_variant', 'value': 'Northwind Group AG',
                         'provenance': 'user'}]})
    job = asking_job(root)
    filed(root, job, 'Northwind Group AG')

    counts, _ = resolver.resolve(root)

    assert counts['linked'] == 1
    assert vault.load_job(root, job['id'])['company_id'] == company['id']


# --- Rung 3: the legal suffix ---------------------------------------------

@pytest.mark.parametrize('stored,asked', [
    ('Northwind AG', 'Northwind'),
    ('Northwind', 'Northwind AG'),
    ('Northwind GmbH', 'Northwind Ltd'),
])
def test_a_legal_suffix_is_not_a_different_employer(root, stored, asked):
    company = vault.save_company(root, {'name': stored})
    job = asking_job(root)
    filed(root, job, asked)

    counts, _ = resolver.resolve(root)

    assert counts['linked'] == 1
    assert vault.load_job(root, job['id'])['company_id'] == company['id']


def test_two_companies_that_differ_only_by_suffix_are_an_ambiguity(root):
    """Exactly one match or nothing: two companies whose stripped names
    are the same is the admin's question, not a first-wins pick."""
    vault.save_company(root, {'name': 'Northwind AG'})
    vault.save_company(root, {'name': 'Northwind GmbH'})
    job = asking_job(root)
    request = filed(root, job, 'Northwind')

    counts, created = resolver.resolve(root, auto_create=True)

    assert counts == {'linked': 0, 'created': 0, 'needs_admin': 1, 'rejected': 0}
    # Ambiguity beats the switch: nothing was created either.
    assert created == []
    assert request_by_id(root, request['id'])['status'] == 'needs_admin'
    assert vault.load_job(root, job['id'])['company_id'] is None


def test_a_fuzzy_name_is_never_linked(root):
    """Rule 4 of the identity ladder. "Northwnd" is one letter off and
    scores well above the fuzzy cutoff; it still goes to the admin."""
    vault.save_company(root, {'name': 'Northwind Systems AG'})
    job = asking_job(root)
    request = filed(root, job, 'Northwnd Systems AG')

    counts, _ = resolver.resolve(root)

    assert counts['needs_admin'] == 1
    assert request_by_id(root, request['id'])['status'] == 'needs_admin'
    assert vault.load_job(root, job['id'])['company_id'] is None


def test_a_retired_company_is_not_matched(root):
    """A retired company takes no new link from anybody (M2 soft
    retire), so matching one would produce a link the vault refuses."""
    company = vault.save_company(root, {'name': 'Northwind AG'})
    vault.save_company(root, {'retired': True}, company['id'])
    job = asking_job(root)
    filed(root, job, 'Northwind AG')

    counts, _ = resolver.resolve(root)

    assert counts['needs_admin'] == 1
    assert vault.load_job(root, job['id'])['company_id'] is None


# --- The mode switch ------------------------------------------------------

def test_the_default_mode_writes_no_company(root):
    job = asking_job(root)
    request = filed(root, job, 'Northwind AG')

    counts, created = resolver.resolve(root)

    assert counts == {'linked': 0, 'created': 0, 'needs_admin': 1, 'rejected': 0}
    assert created == []
    assert vault.list_companies(root) == []
    assert request_by_id(root, request['id'])['status'] == 'needs_admin'


def test_auto_create_creates_the_company_and_links_the_job(root):
    job = asking_job(root)
    request = filed(root, job, 'Northwind AG')

    counts, created = resolver.resolve(root, auto_create=True)

    assert counts == {'linked': 0, 'created': 1, 'needs_admin': 0, 'rejected': 0}
    companies = vault.list_companies(root)
    assert [c['name'] for c in companies] == ['Northwind AG']
    assert created == [companies[0]['id']]
    # No requester stamp on the shared record: a company carries no owner
    # by design, and who asked stays on the private request.
    assert not companies[0].get(vault.OWNER_FIELD)
    assert vault.load_job(root, job['id'])['company_id'] == companies[0]['id']
    settled = request_by_id(root, request['id'])
    assert settled['status'] == 'created'
    assert settled['resolved_company_id'] == companies[0]['id']


def test_a_created_company_gets_the_cascade_after_the_write_lock_is_released(root, monkeypatch):
    """The same sector/size pass an intake-created company gets. It
    fetches, so it must run OUTSIDE the write lock the pass holds: the
    recorded call asserts both that it happened and that the lock was
    free when it did, which `vault.WriteLock` would otherwise refuse by
    raising on the nested acquire."""
    calls = []

    def record(root_arg, company_id, lock):
        with lock:
            calls.append(company_id)

    monkeypatch.setattr(resolver.company_enrichment, 'run_cascade', record)
    filed(root, asking_job(root), 'Northwind AG')

    _counts, created = resolver.resolve(root, auto_create=True)

    assert calls == created == [vault.list_companies(root)[0]['id']]


def test_nothing_is_cascaded_when_nothing_is_created(root, monkeypatch):
    monkeypatch.setattr(resolver.company_enrichment, 'run_cascade',
                        lambda *a, **kw: pytest.fail('cascaded with nothing created'))
    vault.save_company(root, {'name': 'Northwind AG'})
    filed(root, asking_job(root), 'Northwind AG')
    assert resolver.resolve(root, auto_create=True)[0]['linked'] == 1


def test_the_switch_reads_only_an_exact_one(root):
    """Same reading every other product switch uses: 'false' and 'no'
    must not read as on."""
    for value in ('1',):
        assert resolver.auto_create_enabled({resolver.AUTO_CREATE_ENV: value}) is True
    for value in ('', '0', 'false', 'no', 'yes', 'true', 'TRUE'):
        assert resolver.auto_create_enabled({resolver.AUTO_CREATE_ENV: value}) is False
    assert resolver.auto_create_enabled({}) is False


# --- Grouping -------------------------------------------------------------

def test_several_requests_for_one_name_resolve_together(root):
    """One match, every job linked, every status updated. Different jobs
    and different users, which is how the same company gets asked for."""
    company = vault.save_company(root, {'name': 'Northwind AG'})
    first = asking_job(root, 1)
    second = asking_job(root, 2, **{vault.OWNER_FIELD: 'USER-003'})
    one = filed(root, first, 'Northwind AG')
    two = vault.save_company_request(root, {
        'job_id': second['id'], 'name': 'NORTHWIND  ag', vault.OWNER_FIELD: 'USER-003'})

    counts, _ = resolver.resolve(root)

    assert counts['linked'] == 2
    for job in (first, second):
        assert vault.load_job(root, job['id'])['company_id'] == company['id']
    for request in (one, two):
        assert request_by_id(root, request['id'])['status'] == 'linked'


def test_auto_create_makes_one_company_for_one_group(root):
    first = asking_job(root, 1)
    second = asking_job(root, 2)
    filed(root, first, 'Northwind AG')
    filed(root, second, 'Northwind')

    counts, created = resolver.resolve(root, auto_create=True)

    # Two requests, one company: the second group's name strips to the
    # first group's, so it matches the creation this pass just made.
    assert len(created) == 1
    assert len(vault.list_companies(root)) == 1
    assert counts['created'] + counts['linked'] == 2


# --- The two outcomes decided before any matching -------------------------

def test_a_request_whose_job_is_gone_is_rejected(root):
    job = asking_job(root)
    request = filed(root, job, 'Northwind AG')
    vault.delete_job(root, job['id'])

    counts, _ = resolver.resolve(root, auto_create=True)

    assert counts == {'linked': 0, 'created': 0, 'needs_admin': 0, 'rejected': 1}
    settled = request_by_id(root, request['id'])
    assert settled['status'] == 'rejected'
    assert settled['resolution_note'] == company_requests.JOB_GONE_NOTE
    # Nothing was created for a request with nothing left to link.
    assert vault.list_companies(root) == []


def test_a_job_somebody_already_linked_is_left_alone(root):
    """Human edits win. The owner settled the pending ask themselves
    between the filing and the pass, so the request is answered against
    the company their job really points at and the link is untouched."""
    theirs = vault.save_company(root, {'name': 'Already Linked AG'})
    other = vault.save_company(root, {'name': 'Northwind AG'})
    job = asking_job(root)
    request = filed(root, job, 'Northwind AG')
    vault.save_job(root, {'company_id': theirs['id'], 'company_link_state': 'linked',
                          'company_link_reason': 'manual'}, job['id'])

    counts, _ = resolver.resolve(root)

    assert counts['linked'] == 1
    stored = vault.load_job(root, job['id'])
    assert stored['company_id'] == theirs['id'] != other['id']
    assert request_by_id(root, request['id'])['resolved_company_id'] == theirs['id']


# --- Idempotency and the dry run ------------------------------------------

def test_a_second_pass_changes_nothing(root):
    vault.save_company(root, {'name': 'Northwind AG'})
    job = asking_job(root)
    filed(root, job, 'Northwind AG')
    resolver.resolve(root)
    before = snapshot(root)

    counts, created = resolver.resolve(root)

    assert counts == {'linked': 0, 'created': 0, 'needs_admin': 0, 'rejected': 0}
    assert created == []
    assert snapshot(root) == before


def snapshot(root):
    """Every record file's bytes, so "changed nothing" means nothing."""
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(Path(root).rglob('*.yaml'))}


@pytest.mark.parametrize('auto_create', [False, True])
def test_a_dry_run_reports_the_same_counts_and_writes_nothing(root, auto_create):
    vault.save_company(root, {'name': 'Matched AG'})
    matched = asking_job(root, 1)
    unmatched = asking_job(root, 2)
    deleted = asking_job(root, 3)
    filed(root, matched, 'Matched AG')
    filed(root, unmatched, 'Nothing On File AG')
    filed(root, deleted, 'Deleted Job AG')
    vault.delete_job(root, deleted['id'])
    before = snapshot(root)

    dry_counts, dry_created = resolver.resolve(root, auto_create=auto_create, dry_run=True)

    assert dry_created == []
    assert snapshot(root) == before

    real_counts, _ = resolver.resolve(root, auto_create=auto_create)
    assert dry_counts == real_counts


def test_a_dry_run_counts_one_creation_for_a_group_pair(root):
    """Two names that strip to the same company must be reported as one
    creation and one link, which is what the real pass writes."""
    filed(root, asking_job(root, 1), 'Northwind AG')
    filed(root, asking_job(root, 2), 'Northwind')

    dry_counts, _ = resolver.resolve(root, auto_create=True, dry_run=True)
    real_counts, _ = resolver.resolve(root, auto_create=True)

    assert dry_counts == real_counts == {'linked': 1, 'created': 1,
                                         'needs_admin': 0, 'rejected': 0}


# --- The logs -------------------------------------------------------------

def test_a_pass_logs_counts_and_never_a_name(root, caplog):
    """The journal on the VPS is read by whoever can read the journal,
    and a requested company name is a fact about one person's private
    record. Fed distinctive synthetic values and asserted absent."""
    vault.save_company(root, {'name': 'Grumlewick Vastmoor Ltd'})
    matched = asking_job(root, 1, title='Snorbleth Underkeep Engineer')
    unmatched = asking_job(root, 2)
    deleted = asking_job(root, 3)
    filed(root, matched, 'Grumlewick Vastmoor Ltd')
    filed(root, unmatched, DISTINCTIVE)
    filed(root, deleted, 'Plinthquark Dolemire SA')
    vault.delete_job(root, deleted['id'])

    with caplog.at_level(logging.DEBUG):
        resolver.main(['--vault', str(root)])

    text = caplog.text
    assert 'resolved 3 request(s): 1 linked, 0 created, 1 needs_admin, 1 rejected' in text
    for secret in ('Grumlewick', 'Snorbleth', 'Zqwibble', 'Thornfax',
                   'Plinthquark', 'Dolemire', 'Vastmoor', REQUESTER,
                   matched['id'], unmatched['id'], deleted['id']):
        assert secret not in text, secret


def test_the_summary_says_a_dry_run_is_one(root):
    counts = {outcome: 0 for outcome in resolver.OUTCOMES}
    assert resolver.summary(counts).startswith('resolved 0 request(s)')
    assert resolver.summary(counts, dry_run=True).startswith('dry run: would resolve 0 request(s)')


# --- The command line -----------------------------------------------------

def test_no_vault_is_a_refusal_and_not_a_guess(root, monkeypatch):
    monkeypatch.delenv(resolver.VAULT_ENV, raising=False)
    with pytest.raises(SystemExit) as refused:
        resolver.main([])
    assert 'no vault given' in str(refused.value)


def test_a_path_that_is_not_a_vault_is_refused(tmp_path):
    with pytest.raises(SystemExit) as refused:
        resolver.main(['--vault', str(tmp_path / 'nowhere')])
    assert 'does not look like a CareerOS vault' in str(refused.value)


def test_the_vault_can_come_from_the_environment(root, monkeypatch):
    monkeypatch.setenv(resolver.VAULT_ENV, str(root))
    assert resolver.main([]) == 0


def test_the_switch_is_read_off_the_environment_by_the_command(root, monkeypatch):
    monkeypatch.setenv(resolver.AUTO_CREATE_ENV, '1')
    filed(root, asking_job(root), 'Northwind AG')
    assert resolver.main(['--vault', str(root)]) == 0
    assert [c['name'] for c in vault.list_companies(root)] == ['Northwind AG']
