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

CAREER-36 adds a second instance of this same class, `ai_queue`, one
layer further out: a whole unit of AI work (fetch the posting, read it,
write the result) is handed to it with submit() and the request thread
returns 202 at once, so no proxy timeout can ever cut an AI call short.
The two instances are deliberately separate workers rather than one:
a unit of work on `ai_queue` reaches the model through the ordinary
extraction path, which queues the call itself on `extraction_queue`, and
one shared queue would have the outer task waiting on a worker thread the
outer task is itself occupying.

Serialization of the model host is not what `ai_queue` provides, which
is what this paragraph claimed until the CAREER-36 fix round: /extract
and /re-extract keep their own per-job thread and hand nothing to
`ai_queue` at all, so a reading those endpoints started runs beside
whatever unit `ai_queue` holds. The guarantee is one layer down, and it
covers every path rather than one of them: every model call there is
goes through `extraction_queue.run` (see `ingest._within_deadline`), so
this single worker thread executes one `_call_llm` at a time in the
order the calls were queued, whichever endpoint queued them.
"""
import time
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
                    self._queue.task_done()
                    continue
                if started is not None:
                    started.set()
            try:
                outcome.append(task())
            except BaseException as error:
                outcome.append(error)
            finally:
                done.set()
                # Paired with every _queue.put below, so drain() can tell
                # "nothing queued and nothing running" from "between two
                # tasks". A task that was cancelled before it ran takes
                # the same path through the continue above.
                self._queue.task_done()

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

    def submit(self, task):
        """Queue task behind any earlier-queued task and return at once
        (CAREER-36).

        The opposite half of run(): nothing waits for the result and
        nothing reads it, so a request thread can hand over a unit of work
        that takes minutes and answer 202 in milliseconds. A task
        submitted this way must therefore record its own outcome
        somewhere durable, because raising is the only thing it can do
        with a failure here and nobody is listening: the worker swallows
        the exception rather than dying on it, which is what keeps one bad
        unit of work from stopping every later one.
        """
        self._ensure_running()
        self._queue.put((task, [], Event(), Event(), None, Lock()))

    def drain(self, timeout=30.0):
        """Wait until nothing is queued and nothing is running, and say
        whether that happened inside timeout.

        This is Queue.join() with a deadline, which Queue itself does not
        offer. It exists for the checks that have to observe a finished
        outcome rather than a started one -- the tests, and the smoke run
        in the verification -- and for nothing in a request path: a
        request that waits for the queue is the synchronous call this
        whole queue exists to retire.
        """
        with self._queue.all_tasks_done:
            deadline = time.monotonic() + timeout
            while self._queue.unfinished_tasks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
            return True


extraction_queue = ExtractionWorker()

# The outer layer (CAREER-36): one unit of AI work at a time, in the order
# the requests arrived. See the module docstring for why this is a second
# instance and not the one above.
ai_queue = ExtractionWorker()
