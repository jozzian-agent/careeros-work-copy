"""Protects the Companies directory context: the one open-jobs rule and
the review-flag mark its filters read.

`directory_context` is pure, so these are record snapshots.
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
    """The rule itself: rejected, closed and withdrawn end a job, every
    other stored status leaves it open."""
    open_statuses = [s for s in vault.STATUSES if vault.is_open_job({'status': s})]
    assert open_statuses == ['new', 'interested', 'applied', 'interviewing', 'offer']
    assert vault.ENDED_STATUSES == ('rejected', 'closed', 'withdrawn')


def test_a_job_with_no_status_counts_as_open():
    assert vault.is_open_job({}) is True


def test_the_count_leaves_out_every_ended_job():
    jobs = [job(status) for status in vault.STATUSES]
    assert context([company()], jobs)['counts'] == {'CO-001': 5}


def test_the_count_is_per_company():
    jobs = [job('new'), job('applied', 'CO-002'), job('rejected', 'CO-002')]
    result = context([company(), company('CO-002', name='Other')], jobs)
    assert result['counts'] == {'CO-001': 1, 'CO-002': 1}


def test_a_company_with_no_jobs_counts_zero():
    assert context([company()], [job('new', 'CO-002')])['counts'] == {'CO-001': 0}


# --- needs your input -----------------------------------------------------

def test_needs_attention_marks_any_review_flag():
    entries = [company(review_flags=['sector-ambiguous']),
               company('CO-002', name='Other', review_flags=[])]
    marks = {c['id']: c['needs_attention'] for c in context(entries)['entries']}
    assert marks == {'CO-001': True, 'CO-002': False}


def test_needs_attention_is_set_even_for_a_classified_company():
    """Unlike the detail page's `needs_input`, the directory's filter asks
    only whether a flag stands against the record, so a company that has
    both its classification fields and a flag is still marked."""
    entries = [company(sectors=['J'], size_class='small', review_flags=['size-inconsistent'])]
    assert context(entries)['entries'][0]['needs_attention'] is True


def test_the_record_itself_is_not_mutated():
    record = company(review_flags=[])
    context([record])
    assert 'needs_attention' not in record


# --- what the cards and filters read -------------------------------------

def test_sector_labels_and_the_size_scale_come_from_the_context():
    entries = [company(sectors=['J', 'ZZ'], size_class='small')]
    result = context(entries)
    assert result['sector_labels'] == {'CO-001': ['Information and communication', 'ZZ']}
    assert result['size_classes'] == vault.SIZE_CLASSES
