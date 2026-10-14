"""B4: the job detail page context, built from explicit record snapshots.

`job_context` is pure, so every case here is a record pair rather than a
vault fixture; the two tests that go through the API use tmp_path vaults.
"""
from careeros import server, vault
from careeros.web.pages import jobs

ISIC = [{'code': 'J', 'label': 'Information and communication'},
        {'code': 'C', 'label': 'Manufacturing'}]


def context(job=None, company=None, **kwargs):
    record = {'id': 'JOB-001', 'title': 'Builder', 'url': 'https://example.com/jobs/1'}
    return jobs.job_context(record | (job or {}), company, {}, isic_sections=ISIC, **kwargs)


# --- classification -------------------------------------------------------

def test_sector_falls_back_to_the_linked_company():
    """Bug 4: a posting that never named a sector still shows one when its
    company is classified, and says where it came from."""
    result = context(company={'id': 'CO-001', 'sectors': ['J']})['classification']
    assert result['sector'] == {'value': 'Information and communication', 'source': 'company'}


def test_sector_prefers_the_job_record():
    result = context({'sector': 'Logistics software'},
                     company={'id': 'CO-001', 'sectors': ['J']})['classification']
    assert result['sector'] == {'value': 'Logistics software', 'source': 'job'}


def test_sector_is_null_when_neither_record_has_one():
    assert context(company={'id': 'CO-001'})['classification']['sector'] == {
        'value': None, 'source': None}
    assert context()['classification']['sector'] == {'value': None, 'source': None}


def test_sector_label_degrades_to_the_bare_code():
    """An ISIC code the loaded sections do not name must still be shown,
    not swallowed."""
    result = context(company={'id': 'CO-001', 'sectors': ['ZZ']})['classification']
    assert result['sector'] == {'value': 'ZZ', 'source': 'company'}


def test_classification_carries_function_and_tags():
    result = context({'function': ['builder'], 'tags': ['function:builder']})['classification']
    assert result['function'] == ['builder']
    assert result['tags'] == ['function:builder']


# --- needs_input ----------------------------------------------------------

REVIEW = {'token': 'abc', 'candidates': [{'company_id': 'CO-002', 'name': 'Other Labs'}]}


def test_needs_input_company_review():
    result = context({'company_link_state': 'needs_review', 'company_review': REVIEW})
    assert result['needs_input'] == {'kind': 'company', 'review': REVIEW}


def test_needs_input_passes_every_candidate_through():
    review = {'token': 'abc', 'candidates': [{'company_id': f'CO-00{n}'} for n in range(1, 5)]}
    result = context({'company_link_state': 'needs_review', 'company_review': review})
    assert result['needs_input']['review']['candidates'] == review['candidates']


def test_needs_input_read_failed():
    result = context({'ingest_state': 'fetch_failed',
                      'ingest_error': {'stage': 'fetch', 'reason': 'http_404', 'at': '2026-10-10'}})
    assert result['needs_input'] == {'kind': 'read_failed', 'error_reason': 'http_404'}


def test_needs_input_company_ask_without_a_review_block():
    """The link state alone raises the company ask: a needs_review record
    with no review block is still a record whose company is unresolved, and
    must not fall through to the read failure under it."""
    result = context({'company_link_state': 'needs_review',
                      'ingest_state': 'fetch_failed',
                      'ingest_error': {'stage': 'fetch', 'reason': 'http_404', 'at': 'x'}})
    assert result['needs_input'] == {'kind': 'company', 'review': None}


def test_needs_input_read_failed_when_no_review_is_pending():
    """The other side of that precedence: a review block left behind on a
    link that no longer needs one is not a pending ask, so the failed read
    is what the page surfaces."""
    result = context({'company_link_state': 'linked', 'company_review': REVIEW,
                      'ingest_state': 'fetch_failed',
                      'ingest_error': {'stage': 'fetch', 'reason': 'http_404', 'at': 'x'}})
    assert result['needs_input'] == {'kind': 'read_failed', 'error_reason': 'http_404'}


def test_needs_input_company_review_wins_over_read_failure():
    """One ask at a time: the unresolved link comes first."""
    result = context({'company_link_state': 'needs_review', 'company_review': REVIEW,
                      'ingest_state': 'extract_failed',
                      'ingest_error': {'stage': 'extract', 'reason': 'empty_content', 'at': 'x'}})
    assert result['needs_input']['kind'] == 'company'


def test_needs_input_null_when_a_failed_fetch_produced_text():
    """A posting pasted by hand after a failed fetch leaves the failure
    state behind but nothing left to ask for: text is all the fetch was
    for."""
    result = context({'ingest_state': 'fetch_failed', 'description': 'The real posting text.',
                      'ingest_error': {'stage': 'fetch', 'reason': 'http_404', 'at': 'x'}})
    assert result['needs_input'] is None


def test_needs_input_read_failed_when_extraction_failed_on_stored_text():
    """A posting whose text arrived and whose extraction then failed has no
    details and no way to get them without the owner, so the ask stands.
    Without this the page showed empty sections and no action anywhere."""
    result = context({'ingest_state': 'extract_failed', 'description': 'The real posting text.',
                      'ingest_error': {'stage': 'extract', 'reason': 'empty_content', 'at': 'x'}})
    assert result['needs_input'] == {'kind': 'read_failed', 'error_reason': 'empty_content'}


def test_needs_input_null_on_a_healthy_job():
    assert context({'description': 'text', 'company_link_state': 'linked'})['needs_input'] is None


# --- reading --------------------------------------------------------------

def test_reading_while_the_extractor_runs():
    assert context(llm_pending=True)['reading'] is True
    assert context()['reading'] is False


# --- summary_is_copy ------------------------------------------------------

LONG = 'This team builds planning tools for warehouse operators across Europe.'


def test_summary_is_copy_detects_a_verbatim_opening():
    assert jobs.summary_is_copy(LONG, LONG + ' We are hiring a senior engineer.') is True


def test_summary_is_copy_ignores_whitespace_differences():
    reflowed = LONG.replace(' ', '\n  ')
    assert jobs.summary_is_copy(reflowed, LONG + ' More posting text.') is True


def test_summary_is_copy_false_for_a_real_summary():
    assert jobs.summary_is_copy('A senior engineering role on a planning platform in Zurich.',
                                LONG + ' We are hiring.') is False


def test_summary_is_copy_false_below_the_length_floor():
    """A short line that happens to match the opening is not evidence of a
    copy, so it is left alone."""
    short = 'This team builds planning tools.'
    assert len(short) < jobs.SUMMARY_COPY_MIN
    assert jobs.summary_is_copy(short, short + ' And much more text follows here.') is False


def test_summary_is_copy_false_when_the_summary_runs_past_the_description():
    """The prefix test runs one way only. A summary that opens with the
    whole of a short description is not a copy of it, and would read as one
    if the two arguments were ever compared the other way round."""
    description = 'This team builds planning tools for warehouse operators.'
    summary = description + ' Senior engineer, hybrid in Zurich, mostly backend.'
    assert jobs.summary_is_copy(summary, description) is False
    assert jobs.summary_is_copy(description, summary) is True, 'the other direction is a copy'


def test_summary_is_copy_false_without_a_description():
    assert jobs.summary_is_copy(LONG, '') is False
    assert jobs.summary_is_copy('', '') is False


def test_summary_effective_suppresses_a_copy_and_keeps_a_summary():
    copied = context({'summary': LONG, 'description': LONG + ' We are hiring.'})
    assert copied['summary_effective'] is None
    assert copied['job']['summary'] == LONG, 'the stored record is untouched'
    real = context({'summary': 'A planning-platform role in Zurich, mostly backend work.',
                    'description': LONG})
    assert real['summary_effective'] == 'A planning-platform role in Zurich, mostly backend work.'


# --- fit and history ------------------------------------------------------

def test_fit_is_a_placeholder():
    result = context()
    assert result['fit'] is None
    assert result['fit_placeholder'] == 'Not calculated yet'


def test_history_is_resolved_not_raw(tmp_path):
    root = tmp_path / 'vault'
    job = vault.save_job(root, {'title': 'Builder', 'url': 'https://example.com/jobs/1'})
    vault.save_job(root, {'status': 'interested'}, job['id'])
    client = server.create_app(root).test_client()

    result = client.get(f'/api/jobs/{job["id"]}?view=page').get_json()

    assert result['history'] == [
        {'ts': entry['ts'], 'label': label, 'detail': entry['detail']}
        for entry, label in zip(vault.load_job(root, job['id'])['history'],
                                ['Job added', 'Status changed from New to Interested'])]


def test_detail_context_loads_isic_labels_for_the_company_sector(tmp_path):
    """The route wires the label source in; without it the fallback would
    show a bare ISIC code."""
    root = tmp_path / 'vault'
    company = vault.save_company(root, {'name': 'Studio', 'sectors': ['J']})
    job = vault.save_job(root, {'title': 'Builder', 'url': 'https://example.com/jobs/1',
                                'company_id': company['id']})

    result = jobs.detail_context(root, job['id'])

    assert result['classification']['sector'] == {
        'value': 'Information and communication', 'source': 'company'}
