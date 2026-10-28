"""Protects CAREER-36: AI work leaves the request path, and the record
says where that work stands.

Every Done-when clause of the ticket that can be checked without a
browser is here: the 202 answer, the queued/running/done and the
queued/running/failed transitions, the reason a failure carries, one unit
of AI work at a time, recovery from a restart, and the status fields
being readable from the payloads the front end polls. The UI half
(CAREER-37) is the owner click-test.

The restart recovery here is both halves of the same rule: the reading
status (CAREER-36) and the ingest state a process killed mid-extraction
leaves at `fetched` (CAREER-45), which no live worker can own.
"""
from pathlib import Path
from threading import Event, Lock
from unittest.mock import Mock
import shutil
import time

import pytest
import yaml

from careeros import ingest, intake, server, vault
from careeros.extraction_worker import ExtractionWorker
from careeros.server import create_app

ROOT = Path(__file__).resolve().parents[1]

POSTING = ('<main><h1>Senior Engineer</h1>'
           '<p>Build services with Python in Zurich.</p></main>')


@pytest.fixture
def own_queue(monkeypatch):
    """A queue of this test's own, so one test cannot see another's work.

    careeros.server reads the module global at call time, and create_app
    copies it into AI_QUEUE, so replacing it here covers both as long as
    the app is built after the fixture runs.
    """
    queue = ExtractionWorker()
    monkeypatch.setattr(server, 'ai_queue', queue)
    return queue


@pytest.fixture
def api(tmp_path, own_queue):
    """One job with a posting link, and a client over it."""
    vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    return create_app(tmp_path).test_client()


def blocking_fetch(gate, seen=None, html=POSTING):
    """A posting fetch that parks until `gate` is set, so the assertions
    can run while the reading is genuinely in flight. `seen` collects the
    urls it was called for."""
    def fetch(url):
        if seen is not None:
            seen.append(url)
        assert gate.wait(10), 'the gate was never released'
        return html
    return fetch


# --- The 202 answer -------------------------------------------------------

@pytest.mark.parametrize('route', ['enrich', 'extract', 're-extract'])
def test_every_job_ai_endpoint_answers_202_with_the_queued_status(tmp_path, own_queue,
                                                                  monkeypatch, route):
    """Done-when (CAREER-36): an enrich call returns 202 immediately. The
    body is the same small answer whichever of the three was called, so a
    caller has one shape to read rather than one per endpoint."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'description': 'Stored posting text.'})
    monkeypatch.setattr(intake, 'fetch_url', lambda url: POSTING)
    api = create_app(tmp_path).test_client()
    response = api.post(f'/api/jobs/{job["id"]}/{route}')
    assert (response.status_code, response.json) == (202, {'status': 'queued'})


def test_the_company_endpoint_answers_202_and_records_no_status(tmp_path, own_queue):
    """The company enrichment is queued the same way and answers the same
    202, and that is the whole of what it shares: it records no status.
    The four ai_ fields are the job record's, which is where the chip and
    its polling read them, and a company had them for one round with
    nothing reading them (fix round C5)."""
    company = vault.save_company(tmp_path, {'name': 'Example Labs'})
    api = create_app(tmp_path).test_client()
    response = api.post(f'/api/companies/{company["id"]}/enrich')
    assert (response.status_code, response.json) == (202, {'status': 'queued'})
    assert own_queue.drain(30)
    stored = vault.load_company(tmp_path, company['id'])
    assert not any(key.startswith('ai_') for key in stored)
    # The work itself still ran, which is what the 202 promised.
    assert stored['enrichment']


def test_a_company_that_already_carries_the_retired_fields_still_loads(tmp_path, own_queue):
    """Backwards compatibility for the removal: a company record written
    while companies did carry the four fields must load, enrich and save
    exactly like any other, with its stored values left alone rather than
    validated against a vocabulary the company record no longer has."""
    company = vault.save_company(tmp_path, {'name': 'Example Labs'})
    path = next((tmp_path / 'companies').glob('*.yaml'))
    stored = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump(stored | {'ai_status': 'running', 'ai_error': None,
                                             'ai_started': '2026-10-16T09:00:00Z',
                                             'ai_finished': None}))
    api = create_app(tmp_path).test_client()
    assert api.get(f'/api/companies/{company["id"]}').status_code == 200
    assert api.post(f'/api/companies/{company["id"]}/enrich').status_code == 202
    assert own_queue.drain(30)
    kept = vault.load_company(tmp_path, company['id'])
    assert kept['ai_status'] == 'running'
    assert kept['enrichment']


def test_the_request_returns_while_the_reading_is_still_running(api, tmp_path, monkeypatch,
                                                               own_queue):
    """The problem this ticket fixes: the request used to last as long as
    the reading, so a proxy that gives up after 100 seconds answered 524
    while the work quietly finished. The reading is parked here for as
    long as the assertions need, and the request still comes back."""
    gate = Event()
    monkeypatch.setattr(intake, 'fetch_url', blocking_fetch(gate))
    job_id = vault.list_jobs(tmp_path)[0]['id']
    started = time.monotonic()
    response = api.post(f'/api/jobs/{job_id}/enrich')
    elapsed = time.monotonic() - started
    assert response.status_code == 202
    # Nothing near a proxy's patience, and the reading has not finished:
    # the gate below is what finishes it.
    assert elapsed < 5
    assert vault.load_job(tmp_path, job_id)['ai_status'] in vault.AI_UNSETTLED
    gate.set()
    assert own_queue.drain(30)
    assert vault.load_job(tmp_path, job_id)['ai_status'] == 'done'


# --- The transitions -----------------------------------------------------

def test_a_job_moves_from_absent_through_queued_and_running_to_done(tmp_path, own_queue,
                                                                    monkeypatch):
    """Done-when (CAREER-36): polling the job shows queued, then running,
    then done.

    Two jobs and one gate are what make queued observable: the queue runs
    one unit at a time, so while the first job's reading is parked the
    second one is sitting in the queue, which is exactly the state the
    chip calls queued.
    """
    first = vault.save_job(tmp_path, {'title': 'First', 'url': 'https://posting.example/one'})
    second = vault.save_job(tmp_path, {'title': 'Second', 'url': 'https://posting.example/two'})
    assert vault.ai_status(vault.load_job(tmp_path, first['id'])) == 'absent'
    assert vault.ai_status(vault.load_job(tmp_path, second['id'])) == 'absent'

    entered = Event()
    gate = Event()

    def fetch(url):
        entered.set()
        assert gate.wait(10)
        return POSTING

    monkeypatch.setattr(intake, 'fetch_url', fetch)
    api = create_app(tmp_path).test_client()
    assert api.post(f'/api/jobs/{first["id"]}/enrich').status_code == 202
    assert api.post(f'/api/jobs/{second["id"]}/enrich').status_code == 202
    assert entered.wait(10)

    assert vault.ai_status(vault.load_job(tmp_path, first['id'])) == 'running'
    assert vault.ai_status(vault.load_job(tmp_path, second['id'])) == 'queued'
    gate.set()
    assert own_queue.drain(30)

    for identifier in (first['id'], second['id']):
        done = vault.load_job(tmp_path, identifier)
        assert vault.ai_status(done) == 'done'
        assert done['ai_error'] is None
        assert done['ai_started'] and done['ai_finished']
        assert done['enriched'] is True


def test_extract_marks_the_job_running_once_the_worker_has_it(tmp_path, own_queue, monkeypatch):
    """/extract and /re-extract hand the reading to the extraction worker
    rather than to the AI queue, so the running transition has its own
    place on that path and is checked on its own. The worker here never
    calls back, which is what parks the job in running."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'description': 'Stored posting text.'})
    callbacks = []
    monkeypatch.setattr(intake, 'fetch_url', lambda url: POSTING)
    monkeypatch.setattr('careeros.ingest.extract_async',
                        lambda description, callback, **kwargs:
                        callbacks.append(callback) or Mock(is_alive=lambda: True))
    api = create_app(tmp_path).test_client()
    assert api.post(f'/api/jobs/{job["id"]}/extract').status_code == 202
    for worker in list(api.application.config['REFRESH_THREADS'].values()):
        worker.join(timeout=5)
    assert len(callbacks) == 1
    assert vault.ai_status(vault.load_job(tmp_path, job['id'])) == 'running'

    callbacks[0]({'summary': 'A read summary.'}, None)
    assert vault.ai_status(vault.load_job(tmp_path, job['id'])) == 'done'


def test_a_failed_reading_says_why_in_the_status_field(api, tmp_path, monkeypatch, own_queue):
    """Done-when (CAREER-36): a failed LLM call surfaces its error in the
    status field. A failure with nothing to show for it is the silent
    unknown the product rules forbid."""
    def fail(url):
        raise TimeoutError()

    monkeypatch.setattr(intake, 'fetch_url', fail)
    job_id = vault.list_jobs(tmp_path)[0]['id']
    assert api.post(f'/api/jobs/{job_id}/enrich').status_code == 202
    assert own_queue.drain(30)
    failed = vault.load_job(tmp_path, job_id)
    assert vault.ai_status(failed) == 'failed'
    assert failed['ai_error'] == 'Unable to fetch and parse posting.'
    assert failed['ai_finished']
    assert failed['enriched'] is False


def test_a_model_call_that_failed_is_never_reported_as_a_finished_reading(
        api, tmp_path, monkeypatch, own_queue):
    """Done-when (CAREER-36): a failed LLM call surfaces its error in the
    status field.

    Fix round B1: extraction answers with the offline rules whenever the
    model does not answer, so the filled fields look the same either way
    and the status used to say done for a reading the model never did.
    The fill is kept (the posting really does say those things) and the
    status is what tells the owner the reader failed, with the same
    sentence every other failed reading shows and a Retry beside it.
    """
    def refuses(**kwargs):
        raise OSError('connection refused by HOST:PORT')

    monkeypatch.setattr(intake, 'fetch_url', lambda url: POSTING)
    monkeypatch.setattr(ingest, 'get_llm_model', lambda: 'test-reader')
    monkeypatch.setattr(ingest, 'get_llm_client', lambda: Mock(
        chat=Mock(completions=Mock(create=refuses))))
    job_id = vault.list_jobs(tmp_path)[0]['id']
    assert api.post(f'/api/jobs/{job_id}/enrich').status_code == 202
    assert own_queue.drain(30)

    failed = vault.load_job(tmp_path, job_id)
    assert vault.ai_status(failed) == 'failed'
    assert failed['ai_error'] == 'Could not reach the reader. Try again.'
    assert failed['ai_finished']
    # Kept: what the offline rules read off the posting is real posting
    # data, and the record says it was them that read it.
    assert 'Python' in failed['description']
    assert failed['ingest_source'] == 'heuristic'


def test_a_reading_with_no_reader_configured_is_not_a_failed_call(api, tmp_path, monkeypatch,
                                                                  own_queue):
    """The other side of B1: an environment with no reader configured
    attempts no call, so the offline reading is the whole of what was
    ever coming and it is a finished reading rather than a failure. A
    reason this product never tried is not a failure with a reason, and
    the two are different words on purpose."""
    monkeypatch.setattr(intake, 'fetch_url', lambda url: POSTING)
    monkeypatch.setattr(ingest, 'get_llm_client',
                        lambda: (_ for _ in ()).throw(ValueError('not configured')))
    job_id = vault.list_jobs(tmp_path)[0]['id']
    assert api.post(f'/api/jobs/{job_id}/enrich').status_code == 202
    assert own_queue.drain(30)
    settled = vault.load_job(tmp_path, job_id)
    assert vault.ai_status(settled) == 'done'
    assert settled['ai_error'] is None


def test_a_failure_reason_never_carries_the_exception_text(api, tmp_path, monkeypatch,
                                                           own_queue):
    """A transport failure's own message can name the host it was talking
    to, and a record is a file that gets copied around, so the reason is
    the exception type and never its text."""
    # Stands in for what a real transport failure says: the address it was
    # talking to. The placeholder is deliberate, since an address is a
    # thing this repo does not carry either.
    secret = 'connection refused by HOST:PORT'
    # An exception the queued work did not raise on purpose is reported by
    # type alone, which is what keeps the address out of the record.
    assert server.ai_reason(RuntimeError(secret)) == 'Enrichment failed (RuntimeError).'
    monkeypatch.setattr(intake, 'check_url', lambda url: url)
    monkeypatch.setattr(intake, 'fetch_url', lambda url: POSTING)
    monkeypatch.setattr(intake, 'ingest_posting',
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(secret)))
    job_id = vault.list_jobs(tmp_path)[0]['id']
    assert api.post(f'/api/jobs/{job_id}/enrich').status_code == 202
    assert own_queue.drain(30)
    reason = vault.load_job(tmp_path, job_id)['ai_error']
    assert reason == 'Unable to fetch and parse posting.'
    assert 'HOST' not in reason and 'PORT' not in reason


def test_a_reason_is_dropped_the_moment_the_status_stops_saying_failed(tmp_path):
    """Whatever moves the status on takes the reason with it, so no writer
    has to remember to clear it and a finished reading can never still
    show why the last one failed."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    failed = vault.save_job(tmp_path, vault.ai_failed('Could not reach the reader.'), job['id'])
    assert failed['ai_error'] == 'Could not reach the reader.'
    assert vault.save_job(tmp_path, vault.ai_queued(), job['id'])['ai_error'] is None
    assert vault.save_job(tmp_path, vault.ai_running(), job['id'])['ai_error'] is None
    assert vault.save_job(tmp_path, vault.ai_done(), job['id'])['ai_error'] is None
    # And the record enforces it, not just the four builders: a write that
    # names the status alone still drops the reason, so no writer has to
    # remember to clear it.
    vault.save_job(tmp_path, vault.ai_failed('Could not reach the reader.'), job['id'])
    for status in ('queued', 'running', 'done'):
        assert vault.save_job(tmp_path, {'ai_status': status}, job['id'])['ai_error'] is None
        vault.save_job(tmp_path, vault.ai_failed('Could not reach the reader.'), job['id'])


def test_a_failed_status_with_no_reason_is_refused(tmp_path):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    with pytest.raises(ValueError, match='ai_error'):
        vault.save_job(tmp_path, {'ai_status': 'failed', 'ai_error': '  '}, job['id'])
    with pytest.raises(ValueError, match='ai_status'):
        vault.save_job(tmp_path, {'ai_status': 'reading'}, job['id'])


def test_a_reading_abandoned_by_a_url_change_does_not_stay_owed(tmp_path, own_queue,
                                                                monkeypatch):
    """The owner changed the posting link while a reading of the old one
    was in flight. That result is discarded, which used to leave the
    record saying a reading was still owed with nothing left to deliver
    one. It now says what happened, under the same write lock the discard
    itself holds."""
    callbacks = []
    monkeypatch.setattr(intake, 'fetch_url', lambda url: POSTING)
    monkeypatch.setattr('careeros.ingest.extract_async',
                        lambda description, callback, **kwargs:
                        callbacks.append(callback) or Mock(is_alive=lambda: True))
    api = create_app(tmp_path).test_client()
    job = api.post('/api/jobs/intake', json={'url': 'https://a.recruitee.com/o/role'}).json['job']
    assert vault.ai_status(vault.load_job(tmp_path, job['id'])) == 'running'
    api.put(f'/api/jobs/{job["id"]}', json={'url': 'https://b.recruitee.com/o/other'})
    callbacks[0]({'title': 'A stale title'}, None)
    settled = vault.load_job(tmp_path, job['id'])
    assert vault.ai_status(settled) == 'failed'
    assert settled['ai_error'] == 'The posting link changed while it was being read.'
    assert settled['title'] != 'A stale title'


# --- One reading per job -------------------------------------------------

def test_a_second_enrich_post_never_queues_a_second_reading(api, tmp_path, monkeypatch,
                                                             own_queue):
    """Fix round C3: /enrich takes the same one-reading-per-job
    reservation /extract, /re-extract and the pasted-text path take.

    Without it, five clicks queued five readings of the same posting, and
    each one wrote done over the next one's queued: the record read as
    settled while four readings were still owed, which is exactly when
    the board stops polling and the chip stops moving.
    """
    gate = Event()
    seen = []
    monkeypatch.setattr(intake, 'fetch_url', blocking_fetch(gate, seen))
    job_id = vault.list_jobs(tmp_path)[0]['id']

    for _ in range(5):
        assert api.post(f'/api/jobs/{job_id}/enrich').status_code == 202
    # Five answers of queued, one reading, and nothing settled while it
    # is still parked in the fetch.
    assert vault.ai_status(vault.load_job(tmp_path, job_id)) in vault.AI_UNSETTLED
    gate.set()
    assert own_queue.drain(30)
    assert len(seen) == 1, 'a second click queued a second reading of the same posting'
    assert vault.ai_status(vault.load_job(tmp_path, job_id)) == 'done'

    # The reservation is given back once the unit has written its end
    # state, so the next click reads the posting again rather than
    # finding the job owned forever by a reading that finished.
    assert api.post(f'/api/jobs/{job_id}/enrich').status_code == 202
    assert own_queue.drain(30)
    assert len(seen) == 2


# --- One unit of AI work at a time ---------------------------------------

# Long enough that two units running in parallel are certain to be seen
# inside the window together, and that five of them run visibly longer in
# series than in parallel. Shorter than this (the 0.02s it was) and a
# vault write between two units can outlast the work itself, so even
# genuinely parallel units never meet (fix round C2).
UNIT_WORK_SECONDS = 0.3


def test_the_queue_never_runs_two_units_of_ai_work_at_once(tmp_path, own_queue, monkeypatch):
    """Scope item 2: serialize concurrent AI work, so the single reading
    host is never called in parallel.

    Checked two ways over, because each one alone can be satisfied by
    accident: no unit ever finds another one inside, and five units take
    at least as long as five units in series, which no parallel execution
    of them could.
    """
    jobs = [vault.save_job(tmp_path, {'title': f'Role {index}',
                                      'url': f'https://posting.example/{index}'})
            for index in range(5)]
    inside = []
    peak = []
    guard = Lock()

    def fetch(url):
        with guard:
            inside.append(url)
            peak.append(len(inside))
        time.sleep(UNIT_WORK_SECONDS)
        with guard:
            inside.remove(url)
        return POSTING

    monkeypatch.setattr(intake, 'fetch_url', fetch)
    api = create_app(tmp_path).test_client()
    started = time.monotonic()
    for job in jobs:
        assert api.post(f'/api/jobs/{job["id"]}/enrich').status_code == 202
    assert own_queue.drain(60)
    elapsed = time.monotonic() - started
    assert max(peak) == 1, 'a second unit of AI work started inside the first'
    assert elapsed >= len(jobs) * UNIT_WORK_SECONDS, (
        'five units of AI work finished faster than five in series could')
    assert all(vault.load_job(tmp_path, job['id'])['ai_status'] == 'done' for job in jobs)


def test_the_queue_runs_units_in_the_order_they_were_submitted(own_queue):
    """FIFO, so a reading the owner asked for first is not overtaken."""
    order = []
    for index in range(10):
        own_queue.submit(lambda index=index: order.append(index))
    assert own_queue.drain(30)
    assert order == list(range(10))


def test_a_unit_that_raises_does_not_stop_the_ones_behind_it(own_queue):
    """Nothing is listening for a submitted unit's exception, so the
    worker has to swallow it: one bad unit must not take the queue with
    it."""
    done = []
    own_queue.submit(lambda: (_ for _ in ()).throw(RuntimeError('boom')))
    own_queue.submit(lambda: done.append('after'))
    assert own_queue.drain(30)
    assert done == ['after']


# --- Recovery from a restart --------------------------------------------

@pytest.mark.parametrize('status', vault.AI_UNSETTLED)
def test_a_restart_fails_every_reading_it_interrupted(tmp_path, own_queue, status):
    """Scope item 5: no zombie states. The queue lives in the process, so
    a job left queued or running has nothing that could ever finish it,
    and it says so with a reason rather than reading as in flight
    forever."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    update = {'queued': vault.ai_queued, 'running': vault.ai_running}[status]()
    vault.save_job(tmp_path, update, job['id'])

    create_app(tmp_path)

    record = vault.load_job(tmp_path, job['id'])
    assert vault.ai_status(record) == 'failed'
    assert record['ai_error'] == 'interrupted by server restart'


def test_one_unsaveable_job_cannot_stop_the_recovery_sweep(tmp_path, own_queue, capsys):
    """Fix round B2: the sweep runs while the app is being built, so a
    record whose save is refused must be skipped and named, never allowed
    to raise through create_app and leave the server unable to start. The
    bad record here carries a status this vocabulary retired, which is
    what a vault written before owner decision D7 holds."""
    healthy = vault.save_job(tmp_path, {'title': 'Healthy', 'url': 'https://posting.example/ok'})
    vault.save_job(tmp_path, vault.ai_running(), healthy['id'])
    bad = vault.save_job(tmp_path, {'title': 'Legacy', 'url': 'https://posting.example/legacy'})
    vault.save_job(tmp_path, vault.ai_running(), bad['id'])
    path = next(p for p in (tmp_path / 'jobs').glob('*.yaml')
                if yaml.safe_load(p.read_text())['id'] == bad['id'])
    stored = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump(stored | {'status': 'withdrawn'}))

    assert vault.recover_interrupted_ai(tmp_path) == [healthy['id']]
    assert vault.ai_status(vault.load_job(tmp_path, healthy['id'])) == 'failed'
    # Skipped, not rewritten: the legacy record is left exactly as found.
    assert yaml.safe_load(path.read_text()) == stored | {'status': 'withdrawn'}
    assert bad['id'] in capsys.readouterr().err

    # And the same through the startup path, which is where it mattered:
    # only OSError is caught around it, so anything else used to take the
    # whole app down with it.
    create_app(tmp_path)


def test_a_restart_leaves_a_settled_reading_exactly_as_it_was(tmp_path, own_queue):
    """And it is idempotent for the same reason the field migrations are:
    a second start finds nothing unsettled left to settle."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    vault.save_job(tmp_path, vault.ai_done(), job['id'])
    # Built once first, so the startup field migrations this record also
    # goes through are already behind it and the snapshot compares the
    # recovery sweep against itself.
    create_app(tmp_path)
    done = vault.load_job(tmp_path, job['id'])
    create_app(tmp_path)
    assert vault.load_job(tmp_path, job['id']) == done

    vault.save_job(tmp_path, vault.ai_queued(), job['id'])
    create_app(tmp_path)
    first = vault.load_job(tmp_path, job['id'])
    create_app(tmp_path)
    assert vault.load_job(tmp_path, job['id']) == first


def test_the_recovery_sweep_names_the_records_it_settled(tmp_path):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    other = vault.save_job(tmp_path, {'title': 'Other', 'url': 'https://posting.example/other'})
    vault.save_job(tmp_path, vault.ai_running(), job['id'])
    assert vault.recover_interrupted_ai(tmp_path) == [job['id']]
    assert vault.recover_interrupted_ai(tmp_path) == []
    assert vault.ai_status(vault.load_job(tmp_path, other['id'])) == 'absent'


# --- Recovery from a restart: the extraction half (CAREER-45) -----------

def fetched_job(root, title='Engineer', url='https://posting.example/role'):
    """A job parked exactly where the extraction worker is handed one: the
    posting text is stored and ingest_state says a worker has it."""
    return vault.save_job(root, {'title': title, 'url': url,
                                 'description': 'Stored posting text.',
                                 'ingest_state': 'fetched'})


def test_a_restart_fails_every_extraction_it_interrupted(tmp_path, own_queue):
    """CAREER-45: the same no-zombie rule one state further along. A job
    sits at `fetched` from the handoff until the extraction worker reports
    back, and that worker died with the process, so at startup every
    `fetched` record is one nothing can ever settle. It says extract_failed
    with a reason rather than reading as still arriving forever."""
    job = fetched_job(tmp_path)

    create_app(tmp_path)

    record = vault.load_job(tmp_path, job['id'])
    assert record['ingest_state'] == 'extract_failed'
    assert record['ingest_error'] == {'stage': 'extract', 'reason': vault.AI_RESTART_ERROR,
                                      'at': record['ingest_error']['at']}
    assert record['ingest_error']['at']
    assert record['history'][-1]['event'] == 'extract_failed'
    assert record['history'][-1]['detail'] == 'Extraction interrupted by server restart.'


@pytest.mark.parametrize('state,error', [
    ('stub', None),
    ('complete', None),
    ('fetch_failed', {'stage': 'fetch', 'reason': 'http_404', 'at': '2026-10-28T09:00:00+00:00'}),
    ('extract_failed', {'stage': 'extract', 'reason': 'empty_content',
                        'at': '2026-10-28T09:00:00+00:00'}),
])
def test_the_extraction_sweep_leaves_every_other_ingest_state_as_it_was(tmp_path, state, error):
    """Only `fetched` says a worker holds this record. `stub` above all is
    left alone: it is a pre-fetch state the page already shows as not read
    yet and the retry path re-drives, so settling it would report an
    extraction that never started."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role',
                                    'description': 'Stored posting text.',
                                    'ingest_state': state, 'ingest_error': error})
    assert vault.recover_interrupted_ingest(tmp_path) == []
    assert vault.load_job(tmp_path, job['id']) == job


def test_settling_an_interrupted_extraction_twice_changes_nothing(tmp_path):
    """Idempotent for the same reason the AI sweep is: a second pass finds
    no `fetched` record left to settle."""
    job = fetched_job(tmp_path)
    other = vault.save_job(tmp_path, {'title': 'Other', 'url': 'https://posting.example/other'})

    assert vault.recover_interrupted_ingest(tmp_path) == [job['id']]
    settled = vault.load_job(tmp_path, job['id'])
    assert vault.recover_interrupted_ingest(tmp_path) == []
    assert vault.load_job(tmp_path, job['id']) == settled
    assert vault.load_job(tmp_path, other['id'])['ingest_state'] == 'complete'


@pytest.mark.parametrize('fetch_ok,expected,stage', [
    (True, 'fetched', None),
    (False, 'fetch_failed', 'fetch'),
])
def test_a_settled_extraction_is_retryable(tmp_path, own_queue, monkeypatch,
                                           fetch_ok, expected, stage):
    """The point of settling it: the record a restart left behind goes back
    through the retry the owner already has. /extract's own transition
    guard accepts extract_failed (careeros/server.py: the stub,
    fetch_failed, extract_failed tuple), so the retry moves the state on
    and clears the stale extract error either way -- to `fetched` when the
    refetch works, to a fresh fetch_failed when it does not."""
    job = fetched_job(tmp_path)
    if fetch_ok:
        monkeypatch.setattr(intake, 'fetch_url', lambda url: POSTING)
    monkeypatch.setattr('careeros.ingest.extract_async',
                        lambda description, callback, **kwargs: Mock(is_alive=lambda: True))
    api = create_app(tmp_path).test_client()
    assert vault.load_job(tmp_path, job['id'])['ingest_state'] == 'extract_failed'

    assert api.post(f'/api/jobs/{job["id"]}/extract').status_code == 202
    for worker in list(api.application.config['REFRESH_THREADS'].values()):
        worker.join(timeout=5)

    retried = vault.load_job(tmp_path, job['id'])
    assert retried['ingest_state'] == expected
    assert (retried['ingest_error'] or {}).get('stage') == stage
    assert (retried['ingest_error'] or {}).get('reason') != vault.AI_RESTART_ERROR


# --- What the front end polls -------------------------------------------

def test_every_payload_the_front_end_polls_carries_the_status_fields(tmp_path, own_queue):
    """Scope item 4: the collection, the board and the detail payloads all
    expose the status fields, so the chip and its polling read one
    contract."""
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    vault.save_job(tmp_path, vault.ai_failed('Could not reach the reader.'), job['id'])
    api = create_app(tmp_path).test_client()
    fields = ('ai_status', 'ai_error', 'ai_started', 'ai_finished')

    collection = api.get('/api/jobs').json
    board = api.get('/api/jobs?view=board').json['entries']
    page = api.get(f'/api/jobs/{job["id"]}?view=page').json['job']
    taxonomy = api.get(f'/api/jobs/{job["id"]}/taxonomy').json['job']
    record = api.get(f'/api/jobs/{job["id"]}').json

    for payload in (collection[0], board[0], page, taxonomy, record):
        assert all(key in payload for key in fields)
        assert payload['ai_status'] == 'failed'
        assert payload['ai_error'] == 'Could not reach the reader.'


def test_a_record_written_before_the_field_reads_as_never_tried(tmp_path, own_queue):
    """Backwards compatibility: a vault full of records that predate this
    field must not look like a vault full of readings in flight. The key
    is simply absent, and absent is the word for never tried."""
    (tmp_path / 'jobs').mkdir()
    (tmp_path / 'jobs' / 'legacy.yaml').write_text(yaml.safe_dump(
        {'id': 'JOB-001', 'title': 'Legacy', 'url': 'https://posting.example/legacy'}))
    api = create_app(tmp_path).test_client()
    entry = api.get('/api/jobs').json[0]
    assert 'ai_status' not in entry
    assert vault.ai_status(entry) == 'absent'
    assert vault.ai_status({}) == 'absent'
    assert vault.ai_status(None) == 'absent'


def test_the_four_fields_are_the_job_records_alone(tmp_path):
    """They have to be in the one true list of fields a job write
    persists, or every transition would be dropped as an unknown payload
    key. And they have to be absent from the company's list, which is
    what keeps the company from carrying four fields no surface reads
    (fix round C5)."""
    fields = {'ai_status', 'ai_error', 'ai_started', 'ai_finished'}
    assert fields <= vault.job_field_names()
    assert not fields & vault.company_field_names()


# --- The retry the chip offers ------------------------------------------

def test_a_retry_after_a_failure_starts_a_fresh_reading(tmp_path, own_queue, monkeypatch):
    """The failed chip offers Retry, and a retry has to read as a new
    attempt rather than the old failure with a new timestamp: the reason
    goes, and the record is queued again."""
    shutil.copytree(ROOT / 'sample/vault', tmp_path / 'vault')
    api = create_app(tmp_path / 'vault').test_client()
    monkeypatch.setattr(intake, 'fetch_url',
                        lambda url: (_ for _ in ()).throw(TimeoutError()))
    assert api.post('/api/jobs/JOB-001/enrich').status_code == 202
    assert own_queue.drain(30)
    assert vault.load_job(tmp_path / 'vault', 'JOB-001')['ai_status'] == 'failed'

    monkeypatch.setattr(intake, 'fetch_url', lambda url: POSTING)
    assert api.post('/api/jobs/JOB-001/enrich').status_code == 202
    assert own_queue.drain(30)
    retried = vault.load_job(tmp_path / 'vault', 'JOB-001')
    assert retried['ai_status'] == 'done' and retried['ai_error'] is None
