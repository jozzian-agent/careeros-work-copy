"""Single dedicated worker thread serializing queued per-job extraction
work, so the local LLM only ever processes one job's extraction call at
a time, in the order those calls were queued. This is not the watcher
cron: the watcher polls companies on its own schedule, unrelated to this
per-job extraction queue.

ingest.extract_async still spawns its own thread per call, since callers
(and their tests) rely on that thread's identity: it can fail to start,
and callers join() or is_alive() it directly. This worker sits one layer
deeper, inside that per-call thread: the actual network/LLM call runs
through ExtractionWorker.run(), which queues the call behind any
earlier-queued call and blocks only the per-call thread (never the Flask
request thread, which has already returned by the time this runs) until
its turn comes and the single worker thread has executed it.
"""
from queue import Queue
from threading import Event, Lock, Thread


class ExtractionWorker:
    def __init__(self):
        self._queue = Queue()
        self._thread = None
        self._start_lock = Lock()

    def _ensure_running(self):
        """Create and start the single worker thread at most once.

        Two concurrent first callers can both see self._thread as None (or
        dead) before either has started one; without a lock around the
        check-and-create, both spawn their own consumer thread and the
        queue is no longer serialized by a single worker (JOZ-267 fix
        round 1 finding 1)."""
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = Thread(target=self._loop, daemon=True)
                self._thread.start()

    def _loop(self):
        while True:
            task, outcome, done, cancelled, started, start_lock = self._queue.get()
            with start_lock:
                if cancelled.is_set():
                    done.set()
                    continue
                if started is not None:
                    started.set()
            try:
                outcome.append(task())
            except BaseException as error:
                outcome.append(error)
            finally:
                done.set()

    def run(self, task, cancelled=None, started=None, start_lock=None):
        """Queue task behind any earlier-queued task (FIFO) and block the
        calling thread until the single worker thread has run it, then
        return its result or re-raise its exception.

        cancelled, when supplied, lets the caller abandon task while it is
        still waiting its turn: once set, the worker skips calling task
        entirely instead of running it late (JOZ-267 fix round 1 finding
        2). Setting it after task has already started has no effect --
        execution, once begun, always runs to completion.

        started, when supplied, is set by the worker the instant it picks
        task up (right before calling it). start_lock, when supplied by
        the same caller that wants to make its own cancel decision
        race-free against that handoff, must be the lock the caller
        itself acquires around checking started/setting cancelled (JOZ-267
        fix round 2, R2-A): whoever acquires it first -- the worker
        deciding to run, or the caller about to cancel -- settles the
        outcome for the other side, so the caller can never cancel a task
        the worker has already committed to running, and the worker can
        never run a task the caller has already abandoned. A caller with
        no stake in that race can simply omit it."""
        self._ensure_running()
        outcome = []
        done = Event()
        cancelled = cancelled if cancelled is not None else Event()
        start_lock = start_lock if start_lock is not None else Lock()
        self._queue.put((task, outcome, done, cancelled, started, start_lock))
        done.wait()
        if not outcome:
            raise TimeoutError('Task was abandoned before the worker reached it.')
        result = outcome[0]
        if isinstance(result, BaseException):
            raise result
        return result


extraction_queue = ExtractionWorker()
