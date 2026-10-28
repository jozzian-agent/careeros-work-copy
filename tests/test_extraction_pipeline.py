"""JOZ-267: queued extraction, per-field status/provenance, posting_quality,
and the structured description block. Synthetic fixtures only; no real
network (tests/conftest.py's offline fixture blocks it)."""
import json
import time
from queue import Queue
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from careeros import ingest, intake, vault
from careeros.extraction_worker import ExtractionWorker
from careeros.server import apply_field_status, create_app, fail_pending_field_status


def client_for(content=None, error=None, on_call=None):
    def create(**kwargs):
        if on_call:
            on_call()
        if error:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=create))))


@pytest.fixture(autouse=True)
def no_configuration(monkeypatch):
    for key in ('LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL'):
        monkeypatch.delenv(key, raising=False)


# --- posting_quality: documented, testable word-count heuristic ---

@pytest.mark.parametrize('description,expected', [
    ('', 'thin'),
    ('Join our team!', 'thin'),
    (' '.join(['word'] * 39), 'thin'),
    (' '.join(['word'] * 40), 'ok'),
    (' '.join(['word'] * 149), 'ok'),
    (' '.join(['word'] * 150), 'rich'),
])
def test_classify_posting_quality(description, expected):
    assert ingest.classify_posting_quality(description) == expected


# --- heuristic_structured_description: section-splitting fallback ---

def test_heuristic_structured_description_splits_sections():
    text = ('We build tools for engineers.\n\n'
            'Requirements:\n- Five years of Python\n- Strong SQL\n\n'
            'Nice to have:\n- Kubernetes experience\n- Rust')
    result = ingest.heuristic_structured_description(text)
    assert result['requirements'] == ['Five years of Python', 'Strong SQL']
    assert result['nice_to_have'] == ['Kubernetes experience', 'Rust']
    assert result['method'] == 'heuristic'


def test_heuristic_structured_description_raw_when_nothing_found():
    assert ingest.heuristic_structured_description('') == {
        'summary': '', 'requirements': [], 'nice_to_have': [], 'method': 'raw'}
    assert ingest.heuristic_structured_description('   ')['method'] == 'raw'


# --- the named known failure: employment_type must not contradict seniority ---

def test_implausible_internship_on_senior_role_is_dropped():
    content = json.dumps({'title': 'Senior Product Manager', 'seniority': 'senior',
                          'employment_type': 'internship'})
    client = client_for(content)
    result = ingest.extract('Senior Product Manager role. ' * 30, client=client, model=object())
    assert 'employment_type' not in result or result.get('employment_type') != 'internship'


def test_plausible_internship_on_junior_role_is_kept():
    content = json.dumps({'title': 'Intern', 'seniority': 'intern', 'employment_type': 'internship'})
    client = client_for(content)
    result = ingest.extract('Intern role. ' * 30, client=client, model=object())
    assert result['employment_type'] == 'internship'


# --- field_status / field_provenance lifecycle ---

def test_not_evidenced_when_llm_finds_nothing_for_a_covered_field(tmp_path, monkeypatch):
    html = '<main>Build great things with our platform team.</main>'
    monkeypatch.setattr(intake, 'fetch_url', lambda url: html)
    monkeypatch.setattr(ingest, 'get_llm_client',
                        lambda: client_for(json.dumps({'title': 'Platform Engineer', 'company': 'Acme'})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
    job_id = response.json['job']['id']
    app.config['LLM_THREADS'][job_id].join(timeout=2)
    job = api.get('/api/jobs/' + job_id).json
    assert job['field_status']['title'] == 'done'
    assert job['field_provenance']['title'] == 'llm'
    for field in ('function', 'skills', 'seniority', 'employment_type'):
        assert job['field_status'][field] == 'not_evidenced'


def test_total_failure_marks_still_pending_fields_failed():
    baseline = {'field_provenance': {}, 'field_status': {}}
    status = fail_pending_field_status(baseline | {'field_status': apply_field_status(baseline, {}, unfilled='pending')})
    assert all(value == 'failed' for value in status.values())


def test_apply_field_status_never_overwrites_user_provenance():
    job = {'field_provenance': {'title': 'user'}, 'field_status': {'title': 'done'}}
    status = apply_field_status(job, {}, unfilled='not_evidenced')
    assert status['title'] == 'done'


def test_apply_field_status_does_not_downgrade_done():
    job = {'field_provenance': {}, 'field_status': {'title': 'done'}}
    status = apply_field_status(job, {}, unfilled='pending')
    assert status['title'] == 'done'


# --- finding 7: skill_codes is reserved, nullable, and defaults to null ---

def test_skill_codes_defaults_to_null(tmp_path):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    assert job['skill_codes'] is None


def test_skill_codes_accepts_explicit_null(tmp_path):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'skill_codes': ['SKL-1']})
    updated = vault.save_job(tmp_path, {'skill_codes': None}, job['id'])
    assert updated['skill_codes'] is None


def test_skill_codes_rejects_non_list_non_null(tmp_path):
    with pytest.raises(ValueError):
        vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                  'skill_codes': 'not-a-list'})


# --- human edits always win, even mid-extraction (global rule 1) ---

def test_human_edit_survives_inflight_extraction(tmp_path, monkeypatch):
    entered, release = Event(), Event()

    def on_call():
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Platform role with Python and SQL.</main>')
    monkeypatch.setattr(ingest, 'get_llm_client',
                        lambda: client_for(json.dumps({'title': 'LLM Title'}), on_call=on_call))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()
    try:
        response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
        job_id = response.json['job']['id']
        assert entered.wait(2)
        put_response = api.put('/api/jobs/' + job_id, json={'title': 'Owner Title'})
        assert put_response.status_code == 200
        assert put_response.json['field_provenance']['title'] == 'user'
    finally:
        release.set()
    app.config['LLM_THREADS'][job_id].join(timeout=2)
    job = api.get('/api/jobs/' + job_id).json
    assert job['title'] == 'Owner Title'
    assert job['field_provenance']['title'] == 'user'
    assert job['field_status']['title'] == 'done'


def test_human_edited_requirements_and_nice_to_have_survive_inflight_extraction(tmp_path, monkeypatch):
    """R2-E: round 1's human-edit-survives coverage only exercised title.
    description_structured's requirements/nice_to_have carry the exact
    same field_provenance protection (apply_llm_update's fillable list
    includes description_structured as a whole), so a user edit to those
    lists made while an extraction is still in flight must survive it too."""
    entered, release = Event(), Event()

    def on_call():
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Platform role with Python and SQL.</main>')
    monkeypatch.setattr(ingest, 'get_llm_client',
                        lambda: client_for(json.dumps({
                            'requirements': ['LLM requirement'], 'nice_to_have': ['LLM nice to have'],
                        }), on_call=on_call))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()
    owner_structured = {'summary': '', 'requirements': ['Owner requirement'],
                        'nice_to_have': ['Owner nice to have'], 'method': 'heuristic'}
    try:
        response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
        job_id = response.json['job']['id']
        assert entered.wait(2)
        put_response = api.put('/api/jobs/' + job_id, json={'description_structured': owner_structured})
        assert put_response.status_code == 200
        assert put_response.json['field_provenance']['description_structured'] == 'user'
    finally:
        release.set()
    app.config['LLM_THREADS'][job_id].join(timeout=2)
    job = api.get('/api/jobs/' + job_id).json
    assert job['description_structured']['requirements'] == ['Owner requirement']
    assert job['description_structured']['nice_to_have'] == ['Owner nice to have']
    assert job['field_provenance']['description_structured'] == 'user'
    assert job['field_status']['description_structured'] == 'done'


# --- retry re-queues extraction: stale terminal field_status becomes pending again ---

def test_retry_resets_non_user_field_status_to_pending(tmp_path, monkeypatch):
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'description': 'Stored text', 'ingest_state': 'extract_failed',
        'ingest_error': {'stage': 'extract', 'reason': 'no_usable_fields', 'at': vault.timestamp()},
        'field_status': {'title': 'done', 'seniority': 'failed', 'skills': 'not_evidenced'},
        'field_provenance': {},
    })
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer role.</main>')
    monkeypatch.setattr(ingest, 'extract_async',
                        lambda text, callback, **kwargs: Mock(is_alive=lambda: False))
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/' + job['id'] + '/extract')
    assert response.status_code == 202
    app.config['REFRESH_THREADS'][job['id']].join(timeout=2)
    updated = vault.load_job(tmp_path, job['id'])
    assert updated['field_status']['seniority'] == 'pending'
    assert updated['field_status']['skills'] == 'pending'
    assert updated['field_status']['title'] == 'done'


# --- manual-paste resumes extraction through the same worker ---

def test_paste_description_resumes_extraction(tmp_path, monkeypatch):
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'ingest_state': 'fetch_failed',
        'ingest_error': {'stage': 'fetch', 'reason': 'TimeoutError', 'at': vault.timestamp()},
    })
    monkeypatch.setattr(ingest, 'get_llm_client',
                        lambda: client_for(json.dumps({'title': 'Pasted Engineer'})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/' + job['id'] + '/paste-description',
                        json={'description': 'Senior Engineer role. Build things with Python.'})
    assert response.status_code == 202
    assert response.json['ingest_state'] == 'fetched'
    app.config['LLM_THREADS'][job['id']].join(timeout=2)
    updated = vault.load_job(tmp_path, job['id'])
    assert updated['ingest_state'] == 'complete'
    assert updated['field_provenance']['description'] == 'user'
    assert updated['description'] == 'Senior Engineer role. Build things with Python.'
    # B1: a manual paste is its own event type, never the fetch it replaces.
    assert any(e['event'] == 'pasted' for e in updated['history'])
    assert not any(e['event'] == 'fetched' for e in updated['history'])


def test_paste_description_reclassifies_posting_quality(tmp_path, monkeypatch):
    """Finding 5: pasting must recompute posting_quality from the pasted
    text, not leave the thin classification stale from the earlier failed
    fetch that had no text to classify at all."""
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'ingest_state': 'fetch_failed', 'posting_quality': 'thin',
        'ingest_error': {'stage': 'fetch', 'reason': 'TimeoutError', 'at': vault.timestamp()},
    })
    monkeypatch.setattr(ingest, 'get_llm_client',
                        lambda: client_for(json.dumps({'title': 'Pasted Engineer'})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()
    rich_text = ' '.join(['word'] * 160)
    response = api.post('/api/jobs/' + job['id'] + '/paste-description', json={'description': rich_text})
    assert response.status_code == 202
    assert response.json['posting_quality'] == 'rich'


def test_retry_reclassifies_posting_quality_from_fresh_fetch(tmp_path, monkeypatch):
    """Finding 5: a retry that successfully refetches must recompute
    posting_quality from the newly fetched description, not leave a thin
    classification from the earlier failed/empty attempt."""
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'ingest_state': 'extract_failed', 'posting_quality': 'thin', 'description': 'short',
        'ingest_error': {'stage': 'extract', 'reason': 'no_usable_fields', 'at': vault.timestamp()},
    })
    rich_html = '<main>' + ' '.join(['Engineer role with Python.'] * 40) + '</main>'
    monkeypatch.setattr(intake, 'fetch_url', lambda url: rich_html)
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/' + job['id'] + '/extract')
    assert response.status_code == 202
    app.config['REFRESH_THREADS'][job['id']].join(timeout=2)
    updated = vault.load_job(tmp_path, job['id'])
    assert updated['posting_quality'] == 'rich'


def test_paste_description_rejects_once_already_fetched(tmp_path):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'ingest_state': 'complete'})
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/' + job['id'] + '/paste-description',
                        json={'description': 'Some text'})
    assert response.status_code == 409


def test_paste_description_requires_text(tmp_path):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'ingest_state': 'stub'})
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/' + job['id'] + '/paste-description', json={'description': '   '})
    assert response.status_code == 400


# --- worker queue: FIFO order and single-flight serialization ---

def test_extraction_worker_runs_tasks_in_fifo_order():
    """Jobs 1 and 2 must both actually sit queued behind job 0's still-
    running task before anything is released, or this never exercises FIFO
    ordering under a real backlog -- starting and joining each caller in
    turn (the old shape) lets every task finish before the next is even
    enqueued.

    R2-F: starting thread 1 before thread 2 only guarantees they are
    STARTED in that order -- the OS is free to schedule thread 2's call
    to worker.run() (and its own queue.put) before thread 1's, so the
    hard-coded order/result assertions below could fail on a perfectly
    correct worker. Each task's enqueue is tagged (by identity of the
    task callable) and gated on an event confirming the previous one's
    enqueue has actually landed in the queue, so enqueue order is
    deterministic rather than a race between two newly-started threads."""
    worker = ExtractionWorker()
    order = []
    results = {}
    first_running, release_first = Event(), Event()
    enqueued = {0: Event(), 1: Event(), 2: Event()}
    task_index = {}

    def make_task(index):
        def task():
            if index == 0:
                first_running.set()
                assert release_first.wait(2)
            order.append(index)
            return index
        task_index[task] = index
        return task

    real_put = worker._queue.put

    def tracking_put(item):
        real_put(item)
        index = task_index.get(item[0])
        if index is not None:
            enqueued[index].set()
    worker._queue.put = tracking_put

    def run(index, wait_for=None):
        if wait_for is not None:
            assert wait_for.wait(2)
        results[index] = worker.run(make_task(index))

    threads = [Thread(target=run, args=(0,))]
    threads[0].start()
    assert first_running.wait(2)
    threads.append(Thread(target=run, args=(1, enqueued[0])))
    threads[-1].start()
    assert enqueued[1].wait(2), 'job 1 must actually be enqueued before job 2 is even started'
    threads.append(Thread(target=run, args=(2, enqueued[1])))
    threads[-1].start()
    assert enqueued[2].wait(2)
    assert worker._queue.qsize() == 2, 'jobs 1 and 2 must both be queued behind the still-running job 0'
    release_first.set()
    for thread in threads:
        thread.join(2)
    assert order == [0, 1, 2]
    assert [results[0], results[1], results[2]] == [0, 1, 2]


def test_extraction_worker_serializes_concurrent_callers():
    """R3-T2: a bare sleep(0.05) inside each task only hopes to create a
    window wide enough to catch a buggy worker running two tasks at once;
    it proves nothing deterministically. Instead, each task reports in
    (via entries) the instant it becomes active and then blocks on its
    own release Event until the test explicitly lets it go, so the
    invariant is checked, and each task is held open, under the test's
    own explicit control rather than a timing guess."""
    worker = ExtractionWorker()
    active = []
    max_concurrent = []
    entries = Queue()
    releases = [Event() for _ in range(4)]

    def make_task(index):
        def task():
            active.append(1)
            max_concurrent.append(len(active))
            entries.put(index)
            assert releases[index].wait(2)
            active.pop()
            return True
        return task

    threads = [Thread(target=lambda i=i: worker.run(make_task(i))) for i in range(4)]
    for thread in threads:
        thread.start()
    for _ in range(4):
        index = entries.get(timeout=2)
        assert max(max_concurrent) == 1, 'a second task became active before the first was released'
        releases[index].set()
    for thread in threads:
        thread.join(2)
    assert max(max_concurrent) == 1


def test_extraction_worker_propagates_exceptions():
    worker = ExtractionWorker()
    with pytest.raises(ValueError):
        worker.run(lambda: (_ for _ in ()).throw(ValueError('boom')))


# --- JOZ-267 fix round 1: findings 1-4 regressions ---

def test_ensure_running_starts_exactly_one_worker_under_concurrent_callers(monkeypatch):
    """Finding 1: _ensure_running had no synchronization, so two concurrent
    first callers could both see no live thread and each spawn their own
    consumer. A Barrier forces every caller to reach the check at the same
    instant, deterministically, with no sleep involved."""
    from threading import Barrier
    from careeros import extraction_worker as extraction_worker_module

    starts = []
    real_thread = extraction_worker_module.Thread

    class CountingThread(real_thread):
        def start(self):
            starts.append(1)
            super().start()

    monkeypatch.setattr(extraction_worker_module, 'Thread', CountingThread)
    worker = ExtractionWorker()
    callers = 8
    barrier = Barrier(callers)

    def call():
        barrier.wait(2)
        worker._ensure_running()

    threads = [Thread(target=call) for _ in range(callers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert len(starts) == 1
    assert worker.run(lambda: 'ok') == 'ok'


def test_abandoned_queued_task_never_calls_the_model(monkeypatch):
    """Finding 2: a task still waiting its turn when the caller's deadline
    fires must never run the model afterward -- it must be cancelled while
    still queued, with zero model calls. Occupying the worker with a
    blocking first task (released only after the deadline has already
    fired) proves the second task was genuinely still queued, not merely
    fast, when it got cancelled."""
    fresh_queue = ExtractionWorker()
    monkeypatch.setattr(ingest, 'extraction_queue', fresh_queue)
    monkeypatch.setattr(ingest, 'get_timeout', lambda: 0.1)
    occupied, release_occupant = Event(), Event()
    second_task_called = Event()

    def occupy():
        fresh_queue.run(lambda: (occupied.set(), release_occupant.wait(5)))

    occupier = Thread(target=occupy, daemon=True)
    occupier.start()
    assert occupied.wait(2)

    client = client_for(None, on_call=second_task_called.set)
    result = ingest._within_deadline('A real job description, long enough to matter.', client, object())
    assert result == (None, 'transport_error')

    release_occupant.set()
    occupier.join(2)
    assert not second_task_called.wait(0.5), 'the abandoned task must never reach the model'


# --- JOZ-267 fix round 3: R3-A1, R3-B1/B2/B3, R3-C1/C2 regressions ---

def test_execution_exception_still_publishes_a_result(monkeypatch):
    """R3-A1: an exception raised DURING execution (not a queued-phase
    cancellation) must still publish exactly one result. CancelledError is
    a BaseException, not an Exception, so it is never caught by
    _call_llm's own except Exception handlers and instead propagates all
    the way out of extraction_queue.run -- the exact repro the round 3
    reviewer used. Before the fix, _within_deadline's runner caught it,
    logged it, and never called result.put, so the caller's result.get()
    below blocked forever even though the worker had already moved on to
    its next queued task."""
    from asyncio import CancelledError

    fresh_queue = ExtractionWorker()
    monkeypatch.setattr(ingest, 'extraction_queue', fresh_queue)
    monkeypatch.setattr(ingest, 'get_timeout', lambda: 2)

    client = client_for(None, error=CancelledError())
    result = ingest._within_deadline(
        'A real job description, long enough to matter.', client, object())
    assert result == (None, 'transport_error')

    # The worker must have moved on and be ready for the next task, not
    # stuck or left in some half-handled state by the exception above.
    assert fresh_queue.run(lambda: 'ok') == 'ok'


def test_paste_during_inflight_retry_is_not_lost(tmp_path, monkeypatch):
    """Finding 3: pasting while a Retry's own fetch is still in flight must
    not be silently dropped. The retry cannot reserve a second worker slot
    (it already holds the only one), saves the pasted text, and waits;
    the in-flight retry must pick the pasted text up instead of discarding
    it as an unrelated concurrent edit and clearing its reservation with
    nothing left to process the paste."""
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'ingest_state': 'fetch_failed',
        'ingest_error': {'stage': 'fetch', 'reason': 'TimeoutError', 'at': vault.timestamp()},
    })
    fetch_entered, release_fetch = Event(), Event()

    def blocking_fetch(url):
        fetch_entered.set()
        assert release_fetch.wait(5)
        raise TimeoutError('still unreachable')

    monkeypatch.setattr(intake, 'fetch_url', blocking_fetch)
    monkeypatch.setattr(ingest, 'get_llm_client',
                        lambda: client_for(json.dumps({'title': 'Pasted Engineer'})))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()

    retry_response = api.post('/api/jobs/' + job['id'] + '/extract')
    assert retry_response.status_code == 202
    assert fetch_entered.wait(2)

    paste_response = api.post('/api/jobs/' + job['id'] + '/paste-description',
                              json={'description': 'Pasted Engineer role. Build things with Python.'})
    assert paste_response.status_code == 202
    assert paste_response.json.get('llm_pending') is True

    release_fetch.set()
    app.config['REFRESH_THREADS'][job['id']].join(timeout=2)
    app.config['LLM_THREADS'][job['id']].join(timeout=2)

    updated = vault.load_job(tmp_path, job['id'])
    assert updated['description'] == 'Pasted Engineer role. Build things with Python.'
    assert updated['field_provenance']['description'] == 'user'
    assert updated['ingest_state'] == 'complete'
    assert updated['title'] == 'Pasted Engineer'
    assert 'pending' not in updated['field_status'].values()


def test_fetch_failure_settles_pending_fields_instead_of_leaving_them_pending(tmp_path, monkeypatch):
    """Finding 4: on_result used to skip settling field_status entirely
    whenever ingest_state was already fetch_failed/empty_content, leaving
    every covered field stuck at pending with nothing left to advance it."""
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (_ for _ in ()).throw(TimeoutError('unreachable')))
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
    job_id = response.json['job']['id']
    app.config['LLM_THREADS'][job_id].join(timeout=2)
    job = vault.load_job(tmp_path, job_id)
    assert job['ingest_state'] == 'fetch_failed'
    assert 'pending' not in job['field_status'].values()


def test_worker_start_failure_settles_pending_fields_as_failed(tmp_path, monkeypatch):
    """Finding 4: a worker that never even started (extract_async raising
    before spawning a thread) must settle pending fields too, not just
    mark ingest_state terminal while leaving them pending forever."""
    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer role with Python and SQL.</main>')
    monkeypatch.setattr(ingest, 'extract_async',
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('boom')))
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
    assert response.status_code == 503
    job_id = response.json['job']['id']
    job = vault.load_job(tmp_path, job_id)
    assert job['ingest_state'] == 'extract_failed'
    assert job['ingest_error']['reason'] == 'worker_start_failed'
    assert 'pending' not in job['field_status'].values()


# --- JOZ-267 fix round 2: R2-A, R2-B, R2-C, and the finding-4 barrier ---

def test_queue_wait_does_not_consume_execution_budget(monkeypatch):
    """R2-A (1): the execution timeout must be measured from the moment
    the worker actually picks the task up, not from when it was enqueued.
    A task that sits queued for most of the configured budget must still
    get its own full, fresh budget once it starts, instead of inheriting
    whatever was left over from a single combined deadline."""
    fresh_queue = ExtractionWorker()
    monkeypatch.setattr(ingest, 'extraction_queue', fresh_queue)
    monkeypatch.setattr(ingest, 'get_timeout', lambda: 0.5)

    occupied, release_occupant = Event(), Event()

    def occupy():
        fresh_queue.run(lambda: (occupied.set(), release_occupant.wait(5)))

    occupier = Thread(target=occupy, daemon=True)
    occupier.start()
    assert occupied.wait(2)

    entered_model_call, release_model_call = Event(), Event()

    def on_call():
        entered_model_call.set()
        assert release_model_call.wait(5)

    client = client_for(json.dumps({'title': 'Engineer'}), on_call=on_call)
    outcome = {}

    def call():
        outcome['result'] = ingest._within_deadline(
            'A real job description, long enough to matter.', client, object())

    # R3-T2: confirm the caller's task has actually landed in the queue
    # behind the occupant before timing the release delay below -- a bare
    # sleep(0.3) started right after caller.start() has no guarantee the
    # task was enqueued yet, so it could race ahead of its own "queued for
    # well over half the timeout" premise on a slow or busy scheduler.
    task_enqueued = Event()
    real_put = fresh_queue._queue.put

    def tracking_put(item):
        real_put(item)
        task_enqueued.set()
    fresh_queue._queue.put = tracking_put

    caller = Thread(target=call, daemon=True)
    caller.start()
    assert task_enqueued.wait(2), 'the caller must actually enqueue its task behind the occupant'

    # Keep the task queued for well over half the configured timeout --
    # under the old enqueue-measured deadline this alone would already
    # have consumed most of the budget before the task even started.
    held = Thread(target=lambda: (time.sleep(0.3), release_occupant.set()), daemon=True)
    held.start()
    assert entered_model_call.wait(2), 'the queued task must start once the occupant releases'

    # The model call itself now takes most of a full, fresh timeout; this
    # only succeeds if the execution budget started counting at pickup,
    # roughly 0.3s in, rather than at the original enqueue moment.
    Thread(target=lambda: (time.sleep(0.3), release_model_call.set()), daemon=True).start()
    caller.join(2)
    held.join(2)
    assert outcome['result'] == ({'title': 'Engineer'}, None)


def test_timed_out_then_executing_task_blocks_concurrent_retry(tmp_path, monkeypatch):
    """R2-A (2): once the wait budget expires while the task is already
    executing, ownership of the job must stay held until it genuinely
    finishes. Before this fix, the caller's single combined deadline
    returned (None, 'transport_error') the instant it elapsed regardless
    of whether the model call was still running, which released
    llm_pending while the first attempt was still in flight and let Retry
    start a second, concurrent extraction for the same job."""
    monkeypatch.setattr(ingest, 'get_timeout', lambda: 0.2)
    entered, release = Event(), Event()

    def on_call():
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer role with Python and SQL.</main>')
    monkeypatch.setattr(ingest, 'get_llm_client',
                        lambda: client_for(json.dumps({'title': 'Engineer'}), on_call=on_call))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()
    try:
        response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
        job_id = response.json['job']['id']
        assert entered.wait(2)

        # The configured wait budget (0.2s) has now elapsed while the
        # model call is still blocked -- exactly the probe's "timeout
        # returned while execution had started and not finished." Retry
        # must still see the job reserved, not get a second worker slot.
        time.sleep(0.3)
        retry = api.post('/api/jobs/' + job_id + '/extract')
        # CAREER-36: every AI endpoint answers with the queued status, so
        # the reservation itself is what this asserts on.
        assert (retry.status_code, retry.json) == (202, {'status': 'queued'})
        assert job_id in app.config['LLM_PENDING']
    finally:
        release.set()
    app.config['LLM_THREADS'][job_id].join(timeout=2)
    job = vault.load_job(tmp_path, job_id)
    assert job['ingest_state'] == 'complete'
    assert job['title'] == 'Engineer'


def test_late_paste_after_retry_input_chosen_schedules_replacement_extraction(tmp_path, monkeypatch):
    """R2-B: Retry's fetch fails, so it dispatches extraction with the
    stale/old description as its already-chosen input. A Paste that
    lands only AFTER that input is chosen cannot reserve a slot of its
    own (Retry's is still running) and used to return 202 with the
    pasted text silently never reaching an extractor. The fix detects,
    once Retry's own reservation is released, that the persisted
    description now carries user provenance and differs from what Retry
    actually ran against, and schedules a replacement extraction with
    its own fresh ownership."""
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'description': 'Old stale description text from an earlier successful fetch.',
        'ingest_state': 'fetch_failed',
        'ingest_error': {'stage': 'fetch', 'reason': 'TimeoutError', 'at': vault.timestamp()},
    })
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (_ for _ in ()).throw(TimeoutError('still unreachable')))

    entered_model, release_model = Event(), Event()

    def on_call():
        entered_model.set()
        assert release_model.wait(5)

    client = client_for(json.dumps({'title': 'Stale Title'}), on_call=on_call)
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client)
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()

    retry_response = api.post('/api/jobs/' + job['id'] + '/extract')
    assert retry_response.status_code == 202
    assert entered_model.wait(2), 'extraction must already have been dispatched with the stale description'

    paste_response = api.post('/api/jobs/' + job['id'] + '/paste-description',
                              json={'description': 'Pasted Engineer role. Build things with Python.'})
    assert paste_response.status_code == 202
    assert paste_response.json.get('llm_pending') is True

    release_model.set()
    app.config['REFRESH_THREADS'][job['id']].join(timeout=2)
    app.config['LLM_THREADS'][job['id']].join(timeout=2)

    deadline = time.monotonic() + 2
    while job['id'] in app.config['LLM_PENDING'] and time.monotonic() < deadline:
        time.sleep(0.01)
    for thread in list(app.config['LLM_THREADS'].values()):
        thread.join(2)

    calls = client.chat.completions.create.call_args_list
    assert any('Pasted Engineer role' in call.kwargs['messages'][1]['content'] for call in calls), (
        'the pasted text must actually reach a model call, not just sit saved and unused')
    updated = vault.load_job(tmp_path, job['id'])
    assert updated['description'] == 'Pasted Engineer role. Build things with Python.'
    assert updated['field_provenance']['description'] == 'user'
    assert job['id'] not in app.config['LLM_PENDING']


def test_replacement_extraction_start_failure_is_recorded(tmp_path, monkeypatch):
    """R3-B1: Retry extracts old text, Paste returns 202, the old callback
    succeeds, and the replacement extraction this triggers for the pasted
    text fails to even start. That failure must be visible -- not
    silently dropped while the job still reads back as complete, with no
    error and no owner, and the pasted text never actually extracted."""
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'description': 'Old stale description text from an earlier successful fetch.',
        'ingest_state': 'fetch_failed',
        'ingest_error': {'stage': 'fetch', 'reason': 'TimeoutError', 'at': vault.timestamp()},
    })
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (_ for _ in ()).throw(TimeoutError('still unreachable')))

    entered_model, release_model = Event(), Event()

    def on_call():
        entered_model.set()
        assert release_model.wait(5)

    client = client_for(json.dumps({'title': 'Stale Title'}), on_call=on_call)
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client)
    monkeypatch.setattr(ingest, 'get_llm_model', object)

    real_extract_async = ingest.extract_async
    dispatches = []

    def flaky_extract_async(*args, **kwargs):
        dispatches.append(1)
        if len(dispatches) == 2:
            raise RuntimeError('replacement worker could not start')
        return real_extract_async(*args, **kwargs)
    monkeypatch.setattr(ingest, 'extract_async', flaky_extract_async)

    app = create_app(tmp_path)
    api = app.test_client()

    retry_response = api.post('/api/jobs/' + job['id'] + '/extract')
    assert retry_response.status_code == 202
    assert entered_model.wait(2), 'extraction must already have been dispatched with the stale description'

    paste_response = api.post('/api/jobs/' + job['id'] + '/paste-description',
                              json={'description': 'Pasted Engineer role. Build things with Python.'})
    assert paste_response.status_code == 202

    release_model.set()
    app.config['REFRESH_THREADS'][job['id']].join(timeout=2)
    app.config['LLM_THREADS'][job['id']].join(timeout=2)

    deadline = time.monotonic() + 2
    while job['id'] in app.config['LLM_PENDING'] and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(dispatches) == 2, 'the replacement must actually have been attempted'
    updated = vault.load_job(tmp_path, job['id'])
    assert updated['ingest_state'] == 'extract_failed'
    assert updated['ingest_error']['reason'] == 'worker_start_failed'
    assert 'pending' not in updated['field_status'].values()
    assert job['id'] not in app.config['LLM_PENDING']


def test_replacement_handoff_has_no_idle_gap_and_no_duplicate_extraction(tmp_path, monkeypatch):
    """R3-B2/R3-B3: between releasing the old run's ownership and
    reserving the replacement for a paste that landed while it ran,
    llm_pending must never go briefly absent -- a GET in that gap would
    see complete + llm_pending False + no pending fields and stop
    polling before the replacement even starts -- and no intervening
    Retry can win a reservation in that same gap and cause the pasted
    text to be extracted twice."""
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'description': 'Old stale description text from an earlier successful fetch.',
        'ingest_state': 'fetch_failed',
        'ingest_error': {'stage': 'fetch', 'reason': 'TimeoutError', 'at': vault.timestamp()},
    })
    monkeypatch.setattr(intake, 'fetch_url', lambda url: (_ for _ in ()).throw(TimeoutError('still unreachable')))

    model_calls = []
    entered_model, release_model = Event(), Event()
    entered_second_model, release_second_model = Event(), Event()

    def on_call():
        model_calls.append(1)
        if len(model_calls) == 1:
            entered_model.set()
            assert release_model.wait(5)
        else:
            entered_second_model.set()
            assert release_second_model.wait(5)

    client = client_for(json.dumps({'title': 'Stale Title'}), on_call=on_call)
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client)
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()

    retry_response = api.post('/api/jobs/' + job['id'] + '/extract')
    assert retry_response.status_code == 202
    assert entered_model.wait(2)

    paste_response = api.post('/api/jobs/' + job['id'] + '/paste-description',
                              json={'description': 'Pasted Engineer role. Build things with Python.'})
    assert paste_response.status_code == 202

    violations = []
    stop_polling = Event()
    sampled = Event()

    def poll():
        while not stop_polling.is_set():
            snapshot = api.get('/api/jobs/' + job['id']).json
            if snapshot['ingest_state'] == 'complete' and snapshot.get('llm_pending') is False:
                violations.append(snapshot)
            sampled.set()
            stop_polling.wait(0.001)

    poller = Thread(target=poll, daemon=True)
    poller.start()
    assert sampled.wait(2)

    release_model.set()
    assert entered_second_model.wait(2), 'the replacement must start with no observable idle gap in between'
    stop_polling.set()
    poller.join(2)

    assert not violations, 'a GET observed complete + llm_pending False before the replacement started'

    release_second_model.set()
    app.config['REFRESH_THREADS'][job['id']].join(timeout=2)
    for thread in list(app.config['LLM_THREADS'].values()):
        thread.join(2)

    calls = client.chat.completions.create.call_args_list
    stale_calls = [c for c in calls if 'Old stale description' in c.kwargs['messages'][1]['content']]
    pasted_calls = [c for c in calls if 'Pasted Engineer role' in c.kwargs['messages'][1]['content']]
    assert len(stale_calls) == 1, 'the stale description must be extracted exactly once, not duplicated'
    assert len(pasted_calls) == 1, 'the pasted description must be extracted exactly once, not duplicated'

    updated = vault.load_job(tmp_path, job['id'])
    assert updated['description'] == 'Pasted Engineer role. Build things with Python.'
    assert updated['ingest_state'] == 'complete'
    assert 'pending' not in updated['field_status'].values()


def test_url_change_during_extraction_settles_pending_fields(tmp_path, monkeypatch):
    """R2-C (finding 4 gap): the stale on_result callback detected the url
    change via the baseline mismatch and returned before settling
    field_status, leaving every covered field pending forever with no
    reservation left to advance it. Polling stopped correctly (ingest_state
    went terminal) but the visible per-field statuses stayed wrong."""
    entered, release = Event(), Event()

    def on_call():
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer role with Python and SQL.</main>')
    monkeypatch.setattr(ingest, 'get_llm_client',
                        lambda: client_for(json.dumps({'title': 'LLM Title'}), on_call=on_call))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()
    try:
        response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
        job_id = response.json['job']['id']
        assert entered.wait(2)

        put_response = api.put('/api/jobs/' + job_id, json={'url': 'https://posting.example/changed-role'})
        assert put_response.status_code == 200
        assert put_response.json['ingest_state'] == 'extract_failed'
    finally:
        release.set()
    app.config['LLM_THREADS'][job_id].join(timeout=2)
    job = vault.load_job(tmp_path, job_id)
    assert job['ingest_state'] == 'extract_failed'
    assert job['ingest_error']['reason'] == 'source_url_changed'
    assert 'pending' not in job['field_status'].values()


def test_url_change_settle_and_release_are_atomic(tmp_path, monkeypatch):
    """R3-C2: the baseline-mismatch branch used to settle field_status
    under write_lock, exit it, and only release ownership under
    pending_lock in a separate step afterward -- a concurrent reader
    could observe the fields already settled (terminal) while llm_pending
    still showed this run as the owner. A poller hammering GET throughout
    must never see that combination."""
    entered, release = Event(), Event()

    def on_call():
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer role with Python and SQL.</main>')
    monkeypatch.setattr(ingest, 'get_llm_client',
                        lambda: client_for(json.dumps({'title': 'LLM Title'}), on_call=on_call))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()

    response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
    job_id = response.json['job']['id']
    assert entered.wait(2)
    # Grab the worker handle while it is provably alive and parked: after
    # release.set() the poller's GETs run prune_threads (server.py
    # before_request), which pops dead LLM_THREADS entries -- a later
    # app.config['LLM_THREADS'][job_id] lookup can then KeyError (the exact
    # 'JOB-001' flake seen in CI). Join is unbounded because release is
    # already set, so the parked worker is guaranteed to finish; a bounded
    # join that silently timed out would let the final state-reads race the
    # callback they are asserting on.
    worker = app.config['LLM_THREADS'][job_id]

    put_response = api.put('/api/jobs/' + job_id, json={'url': 'https://posting.example/changed-role'})
    assert put_response.status_code == 200

    violations = []
    stop_polling = Event()
    sampled = Event()

    def poll():
        while not stop_polling.is_set():
            snapshot = api.get('/api/jobs/' + job_id).json
            if (snapshot['ingest_state'] == 'extract_failed'
                    and 'pending' not in snapshot.get('field_status', {}).values()
                    and snapshot.get('llm_pending') is True):
                violations.append(snapshot)
            sampled.set()
            stop_polling.wait(0.001)

    poller = Thread(target=poll, daemon=True)
    poller.start()
    assert sampled.wait(2)
    release.set()
    worker.join()
    stop_polling.set()
    poller.join(2)

    assert not violations, 'a GET observed settled fields while this run still showed as the owner'
    job = vault.load_job(tmp_path, job_id)
    assert job['ingest_state'] == 'extract_failed'
    assert 'pending' not in job['field_status'].values()
    assert job_id not in app.config['LLM_PENDING']


def test_retry_fetch_blocked_url_changed_settles_all_pending_fields(tmp_path, monkeypatch):
    """R3-C1 (server.py refresh_and_enrich, first early return): a
    Retry's own fetch is still in flight when the owner changes the
    job's url. The retry must settle every covered field it was still
    the owner of and release ownership together, rather than abandoning
    the job with all eight covered fields left pending and no owner
    left to ever advance them."""
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'ingest_state': 'fetch_failed',
        'ingest_error': {'stage': 'fetch', 'reason': 'TimeoutError', 'at': vault.timestamp()},
        'field_status': {field: 'pending' for field in ingest.STATUS_FIELDS},
    })
    fetch_entered, release_fetch = Event(), Event()

    def blocking_fetch(url):
        fetch_entered.set()
        assert release_fetch.wait(5)
        raise TimeoutError('still unreachable')

    monkeypatch.setattr(intake, 'fetch_url', blocking_fetch)
    app = create_app(tmp_path)
    api = app.test_client()

    retry_response = api.post('/api/jobs/' + job['id'] + '/extract')
    assert retry_response.status_code == 202
    assert fetch_entered.wait(2)

    put_response = api.put('/api/jobs/' + job['id'],
                           json={'url': 'https://posting.example/changed-role'})
    assert put_response.status_code == 200
    assert put_response.json['ingest_state'] == 'extract_failed'

    release_fetch.set()
    app.config['REFRESH_THREADS'][job['id']].join(timeout=2)

    updated = vault.load_job(tmp_path, job['id'])
    assert updated['ingest_state'] == 'extract_failed'
    assert 'pending' not in updated['field_status'].values()
    assert all(updated['field_status'].get(field) == 'failed' for field in ingest.STATUS_FIELDS)
    assert job['id'] not in app.config['LLM_PENDING']


def test_retry_fetch_blocked_while_intake_completes_settles_pending_fields(tmp_path, monkeypatch):
    """R3-C1 (server.py refresh_and_enrich, second early return): intake's
    own Phase B fetch and a concurrent Retry's fetch are both in flight
    for the same job. Retry reserves the only worker slot first, so once
    intake's fetch finishes it saves the scraped description with
    pending field statuses but cannot reserve its own worker. When
    Retry's fetch later resolves against a description that has since
    changed underneath it (scrape provenance, not a user paste), it must
    settle those pending fields and release ownership together instead
    of abandoning them forever."""
    fetch_calls = []
    intake_entered, release_intake = Event(), Event()
    retry_entered, release_retry = Event(), Event()

    def blocking_fetch(url):
        fetch_calls.append(url)
        if len(fetch_calls) == 1:
            intake_entered.set()
            assert release_intake.wait(5)
            return '<main>Engineer role with Python and SQL.</main>'
        retry_entered.set()
        assert release_retry.wait(5)
        raise TimeoutError('still unreachable')

    monkeypatch.setattr(intake, 'fetch_url', blocking_fetch)
    app = create_app(tmp_path)
    api = app.test_client()

    intake_result = {}
    intake_thread = Thread(target=lambda: intake_result.update(
        response=api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})))
    intake_thread.start()
    assert intake_entered.wait(2)

    job_id = next(j['id'] for j in vault.list_jobs(tmp_path) if j['url'] == 'https://posting.example/role')

    retry_response = api.post('/api/jobs/' + job_id + '/extract')
    assert (retry_response.status_code, retry_response.json) == (202, {'status': 'queued'})
    assert retry_entered.wait(2)

    release_intake.set()
    intake_thread.join(2)
    assert 'response' in intake_result
    assert job_id in app.config['LLM_PENDING'], 'Retry must still own the only worker slot'

    release_retry.set()
    app.config['REFRESH_THREADS'][job_id].join(timeout=2)

    updated = vault.load_job(tmp_path, job_id)
    assert updated['ingest_state'] == 'fetched'
    assert 'pending' not in updated['field_status'].values()
    assert job_id not in app.config['LLM_PENDING']


def test_terminal_extraction_failure_settles_fields_while_poller_observes(tmp_path, monkeypatch):
    """Finding 4 (round 1) never got a barrier-based regression: a
    concurrent poller must never observe a terminal ingest_state next to
    a still-pending field. The model call blocks on a release Event so
    the poller gets a guaranteed, deterministic window -- confirmed by
    sampled_once, not by sleep -- to sample state both before and after
    the failure settles."""
    entered, release = Event(), Event()

    def on_call():
        entered.set()
        assert release.wait(5)
        raise RuntimeError('boom')

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer role with Python and SQL.</main>')
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client_for(None, on_call=on_call))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()

    response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
    job_id = response.json['job']['id']
    assert entered.wait(2)
    # Capture the worker handle before any poller GET runs: before_request's
    # prune_threads pops dead LLM_THREADS entries, so after release the
    # dict lookup below could KeyError (the CI flake seen as
    # KeyError: 'JOB-001'). Unbounded join: release is set, so the parked
    # worker is guaranteed to terminate; a bounded join timing out would
    # let the final state-reads race the settling callback.
    worker = app.config['LLM_THREADS'][job_id]

    violations = []
    sampled_once = Event()
    sampled_after_release = Event()
    released = Event()
    stop_polling = Event()

    def poll():
        while not stop_polling.is_set():
            snapshot = api.get('/api/jobs/' + job_id).json
            terminal = snapshot['ingest_state'] in ('fetch_failed', 'extract_failed', 'complete')
            if terminal and 'pending' in snapshot.get('field_status', {}).values():
                violations.append(snapshot)
            sampled_once.set()
            if released.is_set():
                sampled_after_release.set()
            stop_polling.wait(0.002)

    poller = Thread(target=poll, daemon=True)
    poller.start()
    assert sampled_once.wait(2), 'the poller must have sampled the pre-failure state at least once'
    release.set()
    released.set()
    # R3-T1: the old version joined and stopped polling right after release,
    # with no proof the poller ever actually got a sample in the window
    # between the failure being released and settlement becoming
    # observable -- so it could "pass" having never really probed that
    # window at all. Require at least one confirmed post-release sample
    # before letting the worker thread (and then the poller) finish.
    assert sampled_after_release.wait(2), (
        'the poller must sample at least once after the failure is released')
    worker.join()
    stop_polling.set()
    poller.join(2)

    assert not violations
    final = vault.load_job(tmp_path, job_id)
    assert final['ingest_state'] == 'extract_failed'
    assert 'pending' not in final['field_status'].values()


# --- the vault write lock is never held across a slow LLM call ---

def test_write_lock_not_held_during_slow_extraction(tmp_path, monkeypatch):
    entered, release = Event(), Event()

    def on_call():
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(intake, 'fetch_url', lambda url: '<main>Engineer role with Python.</main>')
    monkeypatch.setattr(ingest, 'get_llm_client',
                        lambda: client_for(json.dumps({'title': 'Engineer'}), on_call=on_call))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    app = create_app(tmp_path)
    api = app.test_client()
    try:
        response = api.post('/api/jobs/intake', json={'url': 'https://posting.example/role'})
        job_id = response.json['job']['id']
        assert entered.wait(2)
        other_lock = vault.WriteLock(tmp_path)
        started = time.monotonic()
        with other_lock:
            pass
        assert time.monotonic() - started < 1.0
    finally:
        release.set()
    app.config['LLM_THREADS'][job_id].join(timeout=2)


def test_llm_correction_creating_new_company_completes(tmp_path, monkeypatch):
    """The extraction callback's new-company branch read `shared`, which is
    a local of apply_llm_update and not of the callback: the NameError was
    swallowed by the outer handler, which then marked a fully successful
    extraction (company created, fields saved) as extract_failed. This
    drives the real path end to end: intake lands in fuzzy_name/needs_review
    (ladder still open), then the LLM correction names a company nothing
    matches, so resolve_company's create rung fires inside apply_llm_update
    and on_result reaches the cascade branch that used to raise."""
    from careeros import server

    def schema_html(name):
        return ('<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
                f'"hiringOrganization":{{"name":"{name}"}}}}</script>'
                '<p>Great opportunity for an experienced builder.</p>')

    # A vault company 'Acme GmbH' makes intake's schema name 'Acme' land
    # in fuzzy_name with no company_id -- the same shape test_company_resolve
    # uses for its needs_review rung-3 probe.
    vault.save_company(tmp_path, {'name': 'Acme GmbH'})
    # CI flake: job_intake starts the LLM worker BEFORE the 201 returns and
    # the instant fake model means the worker's callback overwrites the link
    # group ~65ms after POST-return (measured). On a loaded runner the main
    # thread can be descheduled longer than that between the POST and the
    # pre-read below, which then sees post-LLM state ('new_company') instead
    # of 'fuzzy_name'. Gate the model call on a release Event -- the pattern
    # test_write_lock_not_held_during_slow_extraction already uses -- so the
    # worker provably cannot reach its callback until both pre-reads are
    # done. No sleeps, no weakened assertions.
    entered, release = Event(), Event()

    def on_call():
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme'))
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client_for(json.dumps(
        {'title': 'Senior Platform Engineer', 'company': 'Zzztqx Novelworks AG'}),
        on_call=on_call))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    # The cascade runs a background thread gated on AUTO_CASCADE_ENABLED;
    # count its sector/size calls instead of patching the closure.
    from org_intake import enrich as company_lookup
    cascaded = []
    monkeypatch.setattr(server, 'AUTO_CASCADE_ENABLED', True)
    monkeypatch.setattr(company_lookup, 'classify_sector',
                        lambda company, *a, **k: cascaded.append(company['id']) or (None, None))
    monkeypatch.setattr(company_lookup, 'classify_size', lambda *a, **k: (None, None))
    app = create_app(tmp_path)
    api = app.test_client()
    response = api.post('/api/jobs/intake', json={'url': 'https://unrelated.example/role'})
    job_id = response.json['job']['id']
    # The worker is now provably parked inside the model call (entered is
    # set there and release is not), so these pre-reads cannot race it.
    assert entered.wait(2)
    pre = vault.load_job(tmp_path, job_id)
    assert pre['company_link_reason'] == 'fuzzy_name'
    assert pre['company_id'] is None
    release.set()

    app.config['LLM_THREADS'][job_id].join(timeout=5)

    job = vault.load_job(tmp_path, job_id)
    # The regression: the successful extraction must not be failed by the
    # callback's own bookkeeping.
    assert job['ingest_state'] == 'complete'
    assert job['ingest_error'] is None
    assert job['ai_status'] == 'done'
    # The company was created and the job links to it.
    assert job['company_link_reason'] == 'new_company'
    company = vault.load_company(tmp_path, job['company_id'])
    assert company['name'] == 'Zzztqx Novelworks AG'
    # And the new-company cascade branch actually ran -- before the fix it
    # was unreachable (it raised the NameError instead).
    thread = app.config['CASCADE_THREADS'].get(job['company_id'])
    if thread is not None:  # A completed worker may already be pruned at teardown.
        thread.join(timeout=5)
    assert cascaded == [job['company_id']]


def test_llm_correction_for_a_tester_creates_no_company_and_still_completes(tmp_path, monkeypatch):
    """The opposite side of the gate. A tester-owned record does not
    contribute to the shared half (enrich.contributes_to_shared, M2/D3),
    so resolve_company's create rung raises CompanyCreationDenied and the
    ladder settles the job at link_state 'pending' with no company_id --
    nothing is created, yet the extraction itself succeeded: its fields
    are saved and the job reports complete/done, NOT extract_failed.
    This pins that the callback's new-company branch staying quiet
    (new_company_id is None) is the correct outcome for a denied ladder,
    not a masked error."""
    from careeros import server, users

    def schema_html(name):
        return ('<script type="application/ld+json">{"@type":"JobPosting","title":"Role",'
                f'"hiringOrganization":{{"name":"{name}"}}}}</script>'
                '<p>Great opportunity for an experienced builder.</p>')

    # Same fuzzy shape as the create-side test: a vault company makes the
    # schema name land in fuzzy_name with no link, leaving the ladder open.
    vault.save_company(tmp_path, {'name': 'Acme GmbH'})
    # CI flake (this test failed once in the real repo: line 1299 got None):
    # same race as the create-side test above -- the worker started before
    # the 201 returns, and on a denied ladder its callback writes
    # link_reason=None over the 'fuzzy_name' stub. Gate the model call until
    # the pre-reads are done. No sleeps, no weakened assertions.
    entered, release = Event(), Event()

    def on_call():
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(intake, 'fetch_url', lambda url: schema_html('Acme'))
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: client_for(json.dumps(
        {'title': 'Senior Platform Engineer', 'company': 'Zzztqx Novelworks AG'}),
        on_call=on_call))
    monkeypatch.setattr(ingest, 'get_llm_model', object)
    monkeypatch.setattr(server, 'AUTO_CASCADE_ENABLED', True)
    from org_intake import enrich as company_lookup
    cascaded = []
    monkeypatch.setattr(company_lookup, 'classify_sector',
                        lambda company, *a, **k: cascaded.append(company['id']) or (None, None))
    monkeypatch.setattr(company_lookup, 'classify_size', lambda *a, **k: (None, None))

    app = create_app(tmp_path)
    api = app.test_client()
    # A tester signs in for real: the job gets their owner stamp (M2/D4),
    # which is what makes contributes_to_shared answer False for it.
    users.create_user(tmp_path, email='tester@example.test', name='Tester',
                      role='tester', password='correct horse battery staple')
    login = api.post('/login', json={'email': 'tester@example.test',
                                     'password': 'correct horse battery staple'})
    assert login.status_code == 200

    response = api.post('/api/jobs/intake', json={'url': 'https://unrelated.example/role'})
    job_id = response.json['job']['id']
    # The worker is parked inside the model call, so these pre-reads
    # cannot race its callback.
    assert entered.wait(2)
    pre = vault.load_job(tmp_path, job_id)
    assert pre['company_link_reason'] == 'fuzzy_name'
    assert pre['company_id'] is None
    release.set()

    app.config['LLM_THREADS'][job_id].join(timeout=5)

    job = vault.load_job(tmp_path, job_id)
    # The extraction itself is a success and is reported as one.
    assert job['ingest_state'] == 'complete'
    assert job['ingest_error'] is None
    assert job['ai_status'] == 'done'
    # But the gate held: no company was created and the link stays pending.
    assert job['company_id'] is None
    assert job['company_link_state'] == 'pending'
    names = {c['name'] for c in vault.list_companies(tmp_path)}
    assert names == {'Acme GmbH'}
    # The employer name survives as the job's own free text, so the record
    # still reads who the posting is from.
    assert job['company'] == 'Zzztqx Novelworks AG'
    assert job['employer_named_in_posting'] == 'Zzztqx Novelworks AG'
    # And no cascade was scheduled for a company that does not exist.
    assert cascaded == []
