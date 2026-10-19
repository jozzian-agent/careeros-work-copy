"""Protects the Companies directory context: the one open-jobs rule, and
that the count is the universe's rather than the reader's own board.

`directory_context` is pure, so most of these are record snapshots; the
visibility half reads a real vault, because that is where it is decided.
"""
from careeros import vault
from careeros.web.pages import companies

ISIC = [{'code': 'J', 'label': 'Information and communication'}]


def context(entries, jobs=()):
    return companies.directory_context(list(jobs), list(entries), ISIC)


def company(identifier='CO-001', **fields):
    return {'id': identifier, 'name': 'Studio'} | fields


def job(status, company_id='CO-001'):
    return {'id': f'JOB-{status}', 'status': status, 'company_id': company_id}


# --- open jobs ------------------------------------------------------------

def test_ended_statuses_are_exactly_the_closed_end_of_the_vocabulary():
    """The rule itself (D7): won, rejected and stopped end a job, every
    other stored status leaves it open, and the open list is derived from
    that one decision rather than typed out beside it."""
    open_statuses = [s for s in vault.STATUSES if vault.is_open_job({'status': s})]
    assert open_statuses == ['new', 'interested', 'applied', 'interviewing', 'offer']
    assert vault.ENDED_STATUSES == ('won', 'rejected', 'stopped')
    assert vault.OPEN_STATUSES == tuple(open_statuses)


def test_a_job_with_no_status_counts_as_open():
    assert vault.is_open_job({}) is True


def test_the_count_leaves_out_every_ended_job():
    jobs = [job(status) for status in vault.STATUSES]
    assert context([company()], jobs)['counts'] == {'CO-001': len(vault.OPEN_STATUSES)}


def test_the_count_is_per_company():
    jobs = [job('new'), job('applied', 'CO-002'), job('rejected', 'CO-002')]
    result = context([company(), company('CO-002', name='Other')], jobs)
    assert result['counts'] == {'CO-001': 1, 'CO-002': 1}


def test_a_company_with_no_jobs_counts_zero():
    assert context([company()], [job('new', 'CO-002')])['counts'] == {'CO-001': 0}


# --- B3: every company, counted over the universe -------------------------
#
# B5 (2026-10-19) removed the directory's own `needs_attention` mark and
# the "Needs your input" filter that read it, with the three tests that
# pinned them; `tests/test_company_page_context.py` holds the absence pin
# for the whole concept.

def universe(root, owner):
    return companies.page_context(root, owner)


def test_every_company_appears_whatever_its_source_and_counts_the_universe(tmp_path):
    """The owner's report was that API-added companies are missing from
    the list. The read path was never filtering one out; what was missing
    was its open jobs, because the count was the reader's own board. A
    company nobody on this board holds a posting at is in the list either
    way, and its count is now the universe's open jobs.
    """
    root = tmp_path / 'vault'
    linked = vault.save_company(root, {'name': 'Pool Employer'})
    untouched = vault.save_company(root, {'name': 'Api Added Co'})
    for title, fields in (('Pool posting', {}),
                          ('Mine', {vault.OWNER_FIELD: 'USER-002'}),
                          ('Another user\'s', {vault.OWNER_FIELD: 'USER-003'}),
                          ('Pool posting, ended', {'status': 'rejected'})):
        vault.save_job(root, {'title': title, 'url': f'https://example.test/{vault.slugify(title)}',
                              'company_id': linked['id']} | fields)

    result = universe(root, vault.Owner('USER-002'))

    assert [c['id'] for c in result['entries']] == [untouched['id'], linked['id']]
    # The ownerless posting and this reader's own; not the third user's,
    # and not the ended one.
    assert result['counts'] == {linked['id']: 2, untouched['id']: 0}


# --- what the cards and filters read -------------------------------------

def test_sector_labels_and_the_size_scale_come_from_the_context():
    entries = [company(sectors=['J', 'ZZ'], size_class='small')]
    result = context(entries)
    assert result['sector_labels'] == {'CO-001': ['Information and communication', 'ZZ']}
    assert result['size_classes'] == vault.SIZE_CLASSES
