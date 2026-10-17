"""The staging store: immutable snapshots, a run manifest, closure state.

WHAT THE SPEC ASKS FOR, and where each part lives under the store root
(`data/personio/`, gitignored because raw snapshots are large):

    tenants.yaml                              the discovered tenants
    runs.yaml                                 one entry per fetch run
    state/<tenant>.yaml                       posting state, per tenant
    snapshots/feeds/<tenant>/<run>-<lang>.xml.gz     the raw responses
    snapshots/postings/<tenant>/<id>/<hash>.yaml     the frozen postings
    exports/golden_set_pool_<date>.yaml       the sampling pool

TWO KINDS OF SNAPSHOT, because the spec asks for both and they answer
different questions. The RAW FEED snapshot is the evidence: "store every
raw response, compressed, with fetch timestamp and HTTP status. Raw data
is the evidence if a parser changes later." The POSTING snapshot is what
the golden set references: "the golden set always references a snapshot
id, never the live posting."

IMMUTABLE MEANS IMMUTABLE. `write_snapshot` refuses to change a file that
exists: writing identical bytes is a no-op and writing different bytes
raises. A posting snapshot is addressed by its own content hash, so
"different bytes at the same path" is either a hash collision or a bug in
the mapper, and both deserve a raise rather than a silent overwrite.
Nothing in this module deletes a snapshot, including after a posting
closes -- the spec says so outright.

WHY STATE IS SHARDED PER TENANT. One `postings.yaml` would be a single
file holding every posting of every tenant, Zurich or not: the trial
alone put a few thousand in it and a full crawl will put tens of
thousands there. Sharding by tenant keeps each write small, keeps a
re-run of one tenant from rewriting everything, and means a corrupt file
costs one tenant rather than the whole pool.

CLOSURE DETECTION, exactly as the spec and the brief state it:

  * A posting missing from **2 consecutive successful** fetches of its
    tenant is `closed`, with `closed_after_run` and `closed_at`, and
    `last_seen_at` is kept as the date it was last there.
  * Missing from **one** is `suspected_closing`, which is not closed.
  * A **failed** fetch never counts toward closure. A tenant whose fetch
    failed is skipped entirely by `record_run`, so a 500 on Personio's
    side cannot close a single posting.
  * A posting that comes back is **reopened**, and the gap is logged on
    the record (the spec: "a posting that reappears is reopened, and the
    gap is logged").

The counter is "consecutive successful fetches that did not list it", not
"days": two fetches in one day close a posting after both, and a tenant
that could not be fetched for a week closes nothing. That is the
behaviour the spec describes; whether a time floor should be added as
well is an owner question recorded in the trial report.
"""
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

_logger = logging.getLogger(__name__)

#: How many consecutive successful fetches of a tenant a posting has to
#: be missing from before it is closed. The spec's [2].
CLOSURE_MISSES = 2

OPEN = 'open'
SUSPECTED_CLOSING = 'suspected_closing'
CLOSED = 'closed'

#: A fetch that counts. Anything else -- a timeout, a 5xx, XML that would
#: not parse -- is a failure, and a failure closes nothing.
FETCH_OK = 'ok'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def run_id(at=None):
    """A sortable, filename-safe run id: `20261017T163000Z`."""
    moment = at or datetime.now(timezone.utc)
    return moment.strftime('%Y%m%dT%H%M%SZ')


def read_yaml(path, default=None):
    """A store file, or `default`. A corrupt file is a visible failure
    rather than a silent empty: unlike the vault, nothing here is being
    rendered to a user, and a store that quietly forgot a tenant's
    posting history would close every one of its postings."""
    path = Path(path)
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text())
    return default if data is None else data


def write_yaml(path, data):
    """Atomic replace, the same pattern `careeros.vault._write` uses, so
    a crash mid-write cannot leave a half-parsed state file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Store:
    """The staging directory, as the one object that knows its layout."""

    def __init__(self, root):
        self.root = Path(root)

    # --- paths ---------------------------------------------------------
    @property
    def tenants_file(self):
        return self.root / 'tenants.yaml'

    @property
    def runs_file(self):
        return self.root / 'runs.yaml'

    def state_file(self, tenant):
        return self.root / 'state' / f'{tenant}.yaml'

    def feed_snapshot_path(self, tenant, run, language):
        return self.root / 'snapshots' / 'feeds' / tenant / f'{run}-{language}.xml.gz'

    def posting_snapshot_path(self, tenant, posting_id, content_hash):
        return (self.root / 'snapshots' / 'postings' / tenant / str(posting_id)
                / f'{content_hash}.yaml')

    def export_path(self, day, suffix='yaml'):
        return self.root / 'exports' / f'golden_set_pool_{day}.{suffix}'

    # --- immutable snapshots -------------------------------------------
    def write_snapshot(self, path, payload):
        """Write a snapshot once. Returns True when a file was created,
        False when an identical one was already there.

        `payload` is bytes or text. A path that exists with different
        content raises: snapshots are the golden set's evidence and
        rewriting one would silently change what a label was given for.
        """
        path = Path(path)
        blob = payload if isinstance(payload, bytes) else payload.encode()
        if path.exists():
            if path.read_bytes() == blob:
                return False
            raise RuntimeError(f'{path} exists with different content; snapshots are immutable')
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create, so two runs racing on the same path cannot
        # both believe they wrote it.
        with open(path, 'xb') as handle:
            handle.write(blob)
        return True

    def write_feed_snapshot(self, tenant, run, language, compressed):
        path = self.feed_snapshot_path(tenant, run, language)
        created = self.write_snapshot(path, compressed)
        return path, created

    def write_posting_snapshot(self, mapped, *, run, at=None):
        """Freeze one posting, addressed by its own content hash.

        Returns `(snapshot_id, path, created)`. `created` is False when
        the posting has not changed since a previous run, which is the
        spec's "re-fetching an unchanged posting creates no new
        snapshot".
        """
        snapshot_id = f"{mapped['key']}@{mapped['content_hash']}"
        path = self.posting_snapshot_path(mapped['tenant'], mapped['posting_id'],
                                          mapped['content_hash'])
        record = {'snapshot_id': snapshot_id, 'frozen_at': at or now(), 'first_seen_run': run,
                  'content_hash': mapped['content_hash'], 'posting': mapped}
        if path.exists():
            return snapshot_id, path, False
        self.write_snapshot(path, yaml.safe_dump(record, sort_keys=False, allow_unicode=True))
        return snapshot_id, path, True

    def read_posting_snapshot(self, tenant, posting_id, content_hash):
        return read_yaml(self.posting_snapshot_path(tenant, posting_id, content_hash))

    # --- tenants -------------------------------------------------------
    def load_tenants(self):
        data = read_yaml(self.tenants_file, {}) or {}
        return {entry['tenant']: entry for entry in data.get('tenants') or ()}

    def save_tenants(self, tenants, *, meta=None):
        """Write the tenant file, MERGING the metadata block.

        Merged rather than replaced because two commands write this file:
        `discover` puts its route report in it and `fetch` puts the last
        run id in it. Replacing meant a fetch erased the discovery
        report -- how many tenants each route found, which crawls were
        queried, the Common Crawl terms -- which is the provenance of
        every tenant in the file.
        """
        existing = read_yaml(self.tenants_file, {}) or {}
        payload = {key: value for key, value in existing.items()
                   if key not in ('tenants', 'count', 'updated_at')}
        payload.update({'provider': 'personio', 'updated_at': now()})
        payload.update(meta or {})
        payload['count'] = len(tenants)
        payload['tenants'] = [tenants[key] for key in sorted(tenants)]
        write_yaml(self.tenants_file, payload)

    # --- posting state -------------------------------------------------
    def load_state(self, tenant):
        return read_yaml(self.state_file(tenant),
                         {'tenant': tenant, 'provider': 'personio', 'postings': {}})

    def save_state(self, state):
        write_yaml(self.state_file(state['tenant']), state)

    def tenants_with_state(self):
        directory = self.root / 'state'
        return sorted(path.stem for path in directory.glob('*.yaml')) if directory.exists() else []

    # --- run manifest --------------------------------------------------
    def load_runs(self):
        data = read_yaml(self.runs_file, {}) or {}
        return list(data.get('runs') or ())

    def append_run(self, entry):
        runs = self.load_runs()
        runs = [run for run in runs if run.get('run_id') != entry['run_id']] + [entry]
        runs.sort(key=lambda run: run['run_id'])
        write_yaml(self.runs_file, {'provider': 'personio', 'updated_at': now(),
                                    'count': len(runs), 'runs': runs})
        return entry

    def last_run(self):
        runs = self.load_runs()
        return runs[-1] if runs else None

    def next_run_id(self, at=None):
        """A run id this store does not already hold.

        `run_id` is a timestamp to the second, so two runs started inside
        one second -- a manual re-run right after the cron one, or two
        fetches in one test -- would share an id, and sharing an id means
        one run's entry replaces the other's and both write to the same
        snapshot path. The suffix keeps the id sortable: `...Z` sorts
        before `...Z-2`.
        """
        taken = {run.get('run_id') for run in self.load_runs()}
        base = run_id(at)
        if base not in taken:
            return base
        suffix = 2
        while f'{base}-{suffix}' in taken:
            suffix += 1
        return f'{base}-{suffix}'


def record_run(store, *, run, at, tenant_results):
    """Fold one fetch run into the per-tenant posting state.

    `tenant_results` is `{tenant: {'fetch_status': ..., 'postings': [mapped, ...],
    'error': ...}}`. Returns a per-tenant summary of what changed, which
    is what the daily report prints: new, changed, closed, suspected,
    reopened.

    A tenant whose `fetch_status` is not `ok` is left untouched, which is
    the whole of "a failed fetch never closes anything".
    """
    at = at or now()
    summary = {}
    for tenant, result in sorted(tenant_results.items()):
        if result.get('fetch_status') != FETCH_OK:
            summary[tenant] = {'fetch_status': result.get('fetch_status'),
                               'error': result.get('error'),
                               'skipped': 'a failed fetch counts toward nothing',
                               'new': [], 'changed': [], 'closed': [], 'suspected': [],
                               'reopened': [], 'seen': 0}
            continue
        summary[tenant] = _record_tenant(store, tenant, result, run=run, at=at)
    return summary


def _record_tenant(store, tenant, result, *, run, at):
    state = store.load_state(tenant)
    postings = state.setdefault('postings', {})
    changes = {'fetch_status': FETCH_OK, 'error': None, 'new': [], 'changed': [], 'closed': [],
               'suspected': [], 'reopened': [], 'seen': len(result.get('postings') or ())}
    seen_keys = set()

    for mapped in result.get('postings') or ():
        key = mapped['key']
        seen_keys.add(key)
        entry = postings.get(key)
        snapshot_id, _, created = store.write_posting_snapshot(mapped, run=run, at=at)
        if entry is None:
            postings[key] = {
                'key': key, 'tenant': tenant, 'posting_id': mapped['posting_id'],
                'provider': mapped['provider'], 'url': mapped['url'],
                'first_seen_run': run, 'first_seen_at': at,
                'last_seen_run': run, 'last_seen_at': at,
                'status': OPEN, 'misses': 0,
                'closed_after_run': None, 'closed_at': None,
                'content_hash': mapped['content_hash'], 'snapshot_id': snapshot_id,
                'snapshots': [{'snapshot_id': snapshot_id, 'content_hash': mapped['content_hash'],
                               'run_id': run, 'frozen_at': at}],
                'reopened': [],
                **_derived(mapped),
            }
            changes['new'].append(key)
            continue
        if entry.get('status') in (CLOSED, SUSPECTED_CLOSING):
            gap = _gap(entry, run, store)
            entry['reopened'] = list(entry.get('reopened') or ()) + [
                {'run_id': run, 'at': at, 'was': entry.get('status'),
                 'missed_fetches': entry.get('misses', 0), 'last_seen_run': entry['last_seen_run'],
                 'gap': gap}]
            if entry['status'] == CLOSED:
                changes['reopened'].append(key)
                _logger.info('personio: %s reopened after %s missed fetches (last seen %s)',
                             key, entry.get('misses', 0), entry['last_seen_run'])
            entry['closed_after_run'] = None
            entry['closed_at'] = None
        entry['status'] = OPEN
        entry['misses'] = 0
        entry['last_seen_run'] = run
        entry['last_seen_at'] = at
        entry['url'] = mapped['url']
        entry.update(_derived(mapped))
        if entry.get('content_hash') != mapped['content_hash']:
            entry['content_hash'] = mapped['content_hash']
            entry['snapshot_id'] = snapshot_id
            entry['snapshots'] = list(entry.get('snapshots') or ()) + [
                {'snapshot_id': snapshot_id, 'content_hash': mapped['content_hash'],
                 'run_id': run, 'frozen_at': at}]
            changes['changed'].append(key)
        elif created:
            # The hash matched but no snapshot file existed: the store
            # was pruned or this is a state file from an earlier layout.
            # Writing it is right and reporting it as a change is not.
            _logger.info('personio: re-froze %s, whose snapshot file was missing', key)

    for key, entry in postings.items():
        if key in seen_keys or entry.get('status') == CLOSED:
            continue
        entry['misses'] = int(entry.get('misses') or 0) + 1
        if entry['misses'] >= CLOSURE_MISSES:
            entry['status'] = CLOSED
            entry['closed_after_run'] = run
            entry['closed_at'] = at
            changes['closed'].append(key)
        else:
            entry['status'] = SUSPECTED_CLOSING
            changes['suspected'].append(key)

    state['last_run'] = run
    state['last_run_at'] = at
    state['counts'] = counts(state)
    store.save_state(state)
    return changes


def _derived(mapped):
    """The part of a posting that is DERIVED rather than stated, kept on
    the live state entry and refreshed on every sighting.

    Why it lives here and not only in the snapshot: a snapshot is frozen
    evidence of what the feed SAID, and the geocode is not that -- it is
    what this repository's current municipality register and current
    geocoder make of it. CAREER-53's own trial proved the point: a
    geocoder defect filed eleven German postings in canton Zurich, and
    the fix had to be able to correct them on the next fetch without
    rewriting a single immutable snapshot. So the pool reads its content
    from the snapshot and its location from here, and the snapshot keeps
    the earlier reading as history.
    """
    return {
        'area_status': mapped.get('area_status'),
        'municipality': mapped.get('municipality'),
        'municipality_label': mapped.get('municipality_label'),
        'canton': mapped.get('canton'),
        'corroborated': mapped.get('corroborated'),
        'location': mapped.get('location'),
        'location_values': {dimension: (mapped.get('values') or {}).get(dimension)
                            for dimension in ('municipality', 'canton')},
    }


def _gap(entry, run, store):
    """How many runs a posting was missing for, in words a report can
    print. Counted over the run manifest so a tenant that was not
    fetched for a week does not read as a week-long absence."""
    runs = [item['run_id'] for item in store.load_runs()]
    if entry.get('last_seen_run') in runs:
        between = len([item for item in runs if item > entry['last_seen_run']])
        return {'runs_missing': entry.get('misses', 0), 'runs_since_last_seen': between,
                'last_seen_run': entry['last_seen_run'], 'reopened_in_run': run}
    return {'runs_missing': entry.get('misses', 0), 'last_seen_run': entry.get('last_seen_run'),
            'reopened_in_run': run}


def counts(state):
    """open / suspected / closed for one tenant's state."""
    tally = {OPEN: 0, SUSPECTED_CLOSING: 0, CLOSED: 0}
    for entry in (state.get('postings') or {}).values():
        tally[entry.get('status', OPEN)] = tally.get(entry.get('status', OPEN), 0) + 1
    return tally


def live_postings(store, tenant):
    """The postings of one tenant that are not closed, with their state.

    `suspected_closing` counts as live: the spec closes a posting after
    two misses and not after one, and a posting the pool dropped on a
    single hiccup would be a posting the golden set lost.
    """
    state = store.load_state(tenant)
    return [entry for entry in (state.get('postings') or {}).values()
            if entry.get('status') != CLOSED]
