"""Snapshots, the run manifest and closure detection.

The closure rules these tests pin are the spec's and the brief's, word
for word: two consecutive SUCCESSFUL fetches without a posting close it,
one does not, and a failed fetch counts toward nothing.
"""
from pathlib import Path

import pytest
import yaml

from careeros.feeds import geocode, personio, store as store_module
from careeros.feeds.store import CLOSED, OPEN, SUSPECTED_CLOSING

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'personio'


@pytest.fixture
def store(tmp_path):
    return store_module.Store(tmp_path / 'personio')


def posting(tenant='acme', posting_id='1', *, title='Engineer', offices=('CH - Zürich',),
            hash_salt=None):
    """A mapped posting in the shape `fetch.locate` produces, built from
    the mapper so the shape cannot drift from the real one."""
    from careeros.feeds import fetch as fetch_module
    raw = {'id': posting_id, 'name': title, 'office': offices[0],
           'additionalOffices': list(offices[1:]), 'employmentType': 'permanent',
           'schedule': 'full-time'}
    if hash_salt:
        raw['department'] = hash_salt
    return fetch_module.locate(personio.map_posting(raw, tenant=tenant, language='de'))


def run(store, *, run_id, postings, tenant='acme', fetch_status='ok', error=None, at=None):
    at = at or f'2026-10-{run_id[-2:]}T06:00:00+00:00'
    store.append_run({'run_id': run_id, 'at': at})
    return store_module.record_run(
        store, run=run_id, at=at,
        tenant_results={tenant: {'fetch_status': fetch_status, 'postings': postings,
                                 'error': error}})


# --- immutability ------------------------------------------------------------

def test_a_snapshot_is_written_once_and_an_identical_write_is_a_no_op(store):
    path = store.feed_snapshot_path('acme', 'r1', 'de')
    blob = personio.compress('<workzag-jobs></workzag-jobs>')
    assert store.write_snapshot(path, blob) is True
    assert store.write_snapshot(path, blob) is False
    assert path.read_bytes() == blob


def test_a_snapshot_refuses_to_be_overwritten_with_different_content(store):
    path = store.feed_snapshot_path('acme', 'r1', 'de')
    store.write_snapshot(path, b'first')
    with pytest.raises(RuntimeError, match='immutable'):
        store.write_snapshot(path, b'second')
    assert path.read_bytes() == b'first'


def test_a_posting_snapshot_is_addressed_by_its_own_content_hash(store):
    record = posting()
    snapshot_id, path, created = store.write_posting_snapshot(record, run='r1')
    assert created is True
    assert snapshot_id == f"personio:acme:1@{record['content_hash']}"
    assert path.name == f"{record['content_hash']}.yaml"
    stored = yaml.safe_load(path.read_text())
    assert stored['posting']['title'] == 'Engineer'
    assert stored['content_hash'] == record['content_hash']
    assert stored['first_seen_run'] == 'r1'


def test_refetching_an_unchanged_posting_creates_no_second_snapshot(store):
    """The spec's acceptance criterion: "re-fetching an unchanged posting
    creates no new snapshot"."""
    first_id, path, created = store.write_posting_snapshot(posting(), run='r1')
    assert created is True
    second_id, same_path, created_again = store.write_posting_snapshot(posting(), run='r2')
    assert (second_id, same_path, created_again) == (first_id, path, False)
    directory = store.posting_snapshot_path('acme', '1', 'x').parent
    assert len(list(directory.glob('*.yaml'))) == 1


def test_a_changed_posting_gets_a_second_snapshot_and_the_first_one_survives(store):
    """The spec: "if the text changes later, store a new snapshot and
    keep the old one"."""
    store.write_posting_snapshot(posting(title='Engineer'), run='r1')
    store.write_posting_snapshot(posting(title='Senior Engineer'), run='r2')
    directory = store.posting_snapshot_path('acme', '1', 'x').parent
    titles = sorted(yaml.safe_load(path.read_text())['posting']['title']
                    for path in directory.glob('*.yaml'))
    assert titles == ['Engineer', 'Senior Engineer']


def test_a_feed_snapshot_is_the_raw_body_and_reads_back_byte_for_byte(store):
    body = (FIXTURES / 'isolutions_de_trimmed.xml').read_text()
    path, created = store.write_feed_snapshot('isolutions', 'r1', 'de',
                                              personio.compress(body))
    assert created is True
    assert personio.decompress(path.read_bytes()) == body


# --- the run manifest --------------------------------------------------------

def test_runs_are_appended_in_run_order_and_a_rerun_replaces_its_own_entry(store):
    store.append_run({'run_id': 'r2', 'postings_seen': 1})
    store.append_run({'run_id': 'r1', 'postings_seen': 2})
    store.append_run({'run_id': 'r2', 'postings_seen': 9})
    assert [entry['run_id'] for entry in store.load_runs()] == ['r1', 'r2']
    assert store.last_run() == {'run_id': 'r2', 'postings_seen': 9}


def test_the_manifest_file_records_what_the_spec_asks_a_run_to_record(store):
    store.append_run({'run_id': 'r1', 'at': '2026-10-17T06:00:00+00:00',
                      'tenants_queued': 2, 'postings_seen': 7, 'failures': {}})
    data = yaml.safe_load(store.runs_file.read_text())
    assert data['count'] == 1
    assert data['runs'][0]['tenants_queued'] == 2


# --- closure detection -------------------------------------------------------

def test_a_posting_seen_for_the_first_time_is_open_and_counted_as_new(store):
    changes = run(store, run_id='20261001', postings=[posting()])
    assert changes['acme']['new'] == ['personio:acme:1']
    entry = store.load_state('acme')['postings']['personio:acme:1']
    assert entry['status'] == OPEN
    assert entry['misses'] == 0
    assert entry['first_seen_run'] == entry['last_seen_run'] == '20261001'


def test_missing_from_one_successful_fetch_is_suspected_closing_and_not_closed(store):
    """The brief: "Missing-from-1 is 'suspected_closing', not closed"."""
    run(store, run_id='20261001', postings=[posting()])
    changes = run(store, run_id='20261002', postings=[])
    assert changes['acme']['suspected'] == ['personio:acme:1']
    assert changes['acme']['closed'] == []
    entry = store.load_state('acme')['postings']['personio:acme:1']
    assert entry['status'] == SUSPECTED_CLOSING
    assert entry['misses'] == 1
    assert entry['closed_at'] is None
    assert entry['last_seen_run'] == '20261001', 'the date it was last seen is kept'


def test_missing_from_two_consecutive_successful_fetches_closes_it(store):
    run(store, run_id='20261001', postings=[posting()])
    run(store, run_id='20261002', postings=[])
    changes = run(store, run_id='20261003', postings=[])
    assert changes['acme']['closed'] == ['personio:acme:1']
    entry = store.load_state('acme')['postings']['personio:acme:1']
    assert entry['status'] == CLOSED
    assert entry['misses'] == 2
    assert entry['closed_after_run'] == '20261003'
    assert entry['closed_at'] == '2026-10-03T06:00:00+00:00'
    assert entry['last_seen_run'] == '20261001'


def test_a_failed_fetch_counts_toward_nothing(store):
    """The spec: "a failed fetch never closes anything". Three failures
    in a row leave the posting exactly as it was."""
    run(store, run_id='20261001', postings=[posting()])
    for day in ('02', '03', '04'):
        changes = run(store, run_id=f'202610{day}', postings=[],
                      fetch_status='http_error', error='HTTP 503')
        assert changes['acme']['skipped']
        assert changes['acme']['closed'] == [] and changes['acme']['suspected'] == []
    entry = store.load_state('acme')['postings']['personio:acme:1']
    assert entry['status'] == OPEN
    assert entry['misses'] == 0
    assert entry['last_seen_run'] == '20261001'


def test_a_failed_fetch_between_two_misses_does_not_break_the_count(store):
    """"Consecutive" means consecutive SUCCESSFUL fetches, so a failure
    in the middle neither closes the posting nor resets the counter."""
    run(store, run_id='20261001', postings=[posting()])
    run(store, run_id='20261002', postings=[])
    run(store, run_id='20261003', postings=[], fetch_status='unreachable')
    changes = run(store, run_id='20261004', postings=[])
    assert changes['acme']['closed'] == ['personio:acme:1']


def test_a_posting_that_comes_back_is_reopened_and_the_gap_is_logged(store):
    """The spec: "a posting that reappears is reopened, and the gap is
    logged"."""
    run(store, run_id='20261001', postings=[posting()])
    run(store, run_id='20261002', postings=[])
    run(store, run_id='20261003', postings=[])
    changes = run(store, run_id='20261004', postings=[posting()])
    assert changes['acme']['reopened'] == ['personio:acme:1']
    entry = store.load_state('acme')['postings']['personio:acme:1']
    assert entry['status'] == OPEN
    assert entry['misses'] == 0
    assert entry['closed_after_run'] is None and entry['closed_at'] is None
    assert len(entry['reopened']) == 1
    assert entry['reopened'][0]['was'] == CLOSED
    assert entry['reopened'][0]['missed_fetches'] == 2
    assert entry['reopened'][0]['gap']['last_seen_run'] == '20261001'


def test_a_posting_that_comes_back_after_one_miss_is_not_counted_as_reopened(store):
    """It was never closed, so "reopened" would overstate what happened,
    but the gap is still recorded."""
    run(store, run_id='20261001', postings=[posting()])
    run(store, run_id='20261002', postings=[])
    changes = run(store, run_id='20261003', postings=[posting()])
    assert changes['acme']['reopened'] == []
    entry = store.load_state('acme')['postings']['personio:acme:1']
    assert entry['status'] == OPEN
    assert entry['reopened'][0]['was'] == SUSPECTED_CLOSING


def test_a_closed_posting_keeps_its_snapshots(store):
    """The spec: "snapshots are never deleted, including after a posting
    closes"."""
    run(store, run_id='20261001', postings=[posting()])
    run(store, run_id='20261002', postings=[])
    run(store, run_id='20261003', postings=[])
    directory = store.posting_snapshot_path('acme', '1', 'x').parent
    assert len(list(directory.glob('*.yaml'))) == 1


def test_a_changed_posting_is_reported_as_changed_and_keeps_both_snapshots(store):
    run(store, run_id='20261001', postings=[posting(title='Engineer')])
    changes = run(store, run_id='20261002', postings=[posting(title='Lead Engineer')])
    assert changes['acme']['changed'] == ['personio:acme:1']
    entry = store.load_state('acme')['postings']['personio:acme:1']
    assert len(entry['snapshots']) == 2
    assert entry['snapshots'][-1]['run_id'] == '20261002'
    assert entry['snapshot_id'].endswith(entry['content_hash'])


def test_an_unchanged_posting_is_reported_as_neither_new_nor_changed(store):
    run(store, run_id='20261001', postings=[posting()])
    changes = run(store, run_id='20261002', postings=[posting()])
    assert changes['acme'] == {**changes['acme'], 'new': [], 'changed': [], 'closed': [],
                               'suspected': [], 'reopened': []}
    assert len(store.load_state('acme')['postings']['personio:acme:1']['snapshots']) == 1


def test_one_tenants_failure_does_not_touch_another_tenants_postings(store):
    at = '2026-10-02T06:00:00+00:00'
    run(store, run_id='20261001', postings=[posting(tenant='acme')], tenant='acme')
    run(store, run_id='20261001', postings=[posting(tenant='brue')], tenant='brue')
    store_module.record_run(store, run='20261002', at=at, tenant_results={
        'acme': {'fetch_status': 'http_error', 'postings': [], 'error': 'HTTP 500'},
        'brue': {'fetch_status': 'ok', 'postings': []},
    })
    assert store.load_state('acme')['postings']['personio:acme:1']['status'] == OPEN
    assert store.load_state('brue')['postings']['personio:brue:1']['status'] == \
        SUSPECTED_CLOSING


def test_the_counts_on_a_state_file_add_up(store):
    run(store, run_id='20261001', postings=[posting(posting_id='1'), posting(posting_id='2'),
                                            posting(posting_id='3')])
    run(store, run_id='20261002', postings=[posting(posting_id='1')])
    run(store, run_id='20261003', postings=[posting(posting_id='1'),
                                            posting(posting_id='2')])
    state = store.load_state('acme')
    # 1 was in every run; 2 missed run 2 and came back in run 3; 3 missed
    # both runs 2 and 3, which is the two consecutive misses that close it.
    assert store_module.counts(state) == {OPEN: 2, SUSPECTED_CLOSING: 0, CLOSED: 1}
    run(store, run_id='20261004', postings=[posting(posting_id='1')])
    state = store.load_state('acme')
    assert store_module.counts(state) == {OPEN: 1, SUSPECTED_CLOSING: 1, CLOSED: 1}


def test_a_suspected_posting_is_still_live_for_the_pool(store):
    """A posting missing from one fetch is not closed, so dropping it
    from the pool would be closing it a cycle early."""
    run(store, run_id='20261001', postings=[posting(posting_id='1'), posting(posting_id='2')])
    run(store, run_id='20261002', postings=[posting(posting_id='1')])
    live = {entry['key'] for entry in store_module.live_postings(store, 'acme')}
    assert live == {'personio:acme:1', 'personio:acme:2'}
    run(store, run_id='20261003', postings=[posting(posting_id='1')])
    live = {entry['key'] for entry in store_module.live_postings(store, 'acme')}
    assert live == {'personio:acme:1'}


# --- the derived half of a state entry ---------------------------------------

def test_the_geocode_lives_on_the_state_entry_so_a_better_geocoder_can_fix_it(store):
    """A snapshot is frozen evidence of what the feed SAID. The
    municipality is what today's register makes of it, so it is refreshed
    on every sighting and never rewritten into a snapshot."""
    run(store, run_id='20261001', postings=[posting(offices=('CH - Zürich',))])
    entry = store.load_state('acme')['postings']['personio:acme:1']
    assert entry['area_status'] == geocode.IN_AREA
    assert entry['municipality'] == '261'
    assert entry['municipality_label'] == 'Zürich'
    assert entry['location_values']['municipality']['value'] == '261'

    # The same posting, same content hash, now read as Berlin.
    moved = posting(offices=('DE - Berlin',))
    moved['content_hash'] = entry['content_hash']
    moved['key'] = entry['key']
    run(store, run_id='20261002', postings=[moved])
    entry = store.load_state('acme')['postings']['personio:acme:1']
    assert entry['area_status'] == geocode.OUT_OF_AREA
    assert entry['municipality'] is None
    assert len(entry['snapshots']) == 1, 'no snapshot was rewritten'


# --- the file layout ---------------------------------------------------------

def test_the_store_lays_its_files_out_where_the_brief_says(store):
    assert store.tenants_file.name == 'tenants.yaml'
    assert store.runs_file.name == 'runs.yaml'
    assert store.state_file('acme').parts[-2:] == ('state', 'acme.yaml')
    assert str(store.feed_snapshot_path('acme', 'r1', 'de')).endswith(
        'snapshots/feeds/acme/r1-de.xml.gz')
    assert str(store.posting_snapshot_path('acme', '7', 'abc')).endswith(
        'snapshots/postings/acme/7/abc.yaml')
    assert str(store.export_path('2026-10-17')).endswith(
        'exports/golden_set_pool_2026-10-17.yaml')


def test_a_run_id_is_sortable_and_filename_safe():
    from datetime import datetime, timezone
    assert store_module.run_id(datetime(2026, 10, 17, 16, 30, 0, tzinfo=timezone.utc)) == \
        '20261017T163000Z'
    assert ':' not in store_module.run_id()


def test_tenants_round_trip_through_their_file(store):
    store.save_tenants({'acme': {'tenant': 'acme', 'status': 'candidate'}})
    assert store.load_tenants() == {'acme': {'tenant': 'acme', 'status': 'candidate'}}
    assert yaml.safe_load(store.tenants_file.read_text())['count'] == 1


def test_a_missing_store_reads_as_empty_rather_than_raising(store):
    assert store.load_tenants() == {}
    assert store.load_runs() == []
    assert store.tenants_with_state() == []
    assert store.load_state('nobody') == {'tenant': 'nobody', 'provider': 'personio',
                                          'postings': {}}


def test_two_runs_inside_one_second_do_not_share_a_run_id(store):
    """A run id is a timestamp to the second, and a manual re-run right
    after the cron one would otherwise replace its entry and write to the
    same snapshot path."""
    first = store.next_run_id()
    store.append_run({'run_id': first, 'at': 'x'})
    second = store.next_run_id()
    assert second != first
    store.append_run({'run_id': second, 'at': 'x'})
    assert store.next_run_id() not in (first, second)
    assert sorted([first, second]) == [first, second], 'the suffix keeps ids sortable'


def test_a_fetch_does_not_erase_what_discovery_recorded(store):
    """Two commands write this file: `discover` puts its route report in
    it and `fetch` puts the last run id in it. Replacing the metadata
    meant a fetch erased the provenance of every tenant in the file."""
    store.save_tenants({'acme': {'tenant': 'acme'}},
                       meta={'discovery_routes': {'common_crawl': {'tenants': 1}}})
    store.save_tenants({'acme': {'tenant': 'acme'}}, meta={'last_fetch_run': 'r1'})
    stored = yaml.safe_load(store.tenants_file.read_text())
    assert stored['discovery_routes'] == {'common_crawl': {'tenants': 1}}
    assert stored['last_fetch_run'] == 'r1'
    assert stored['count'] == 1
