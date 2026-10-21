"""Packing old posting snapshots: smaller on disk, identical to read.

What this protects (CAREER-93): the snapshots are the golden set's
evidence and nothing prunes them, so the only way to stop 6.1G of
`data/ats` filling the root disk is to compress it -- and compressing it
is only allowed if every reader keeps reading exactly what it read
before. These tests run the real readers (`read_posting_snapshot`, the
pool export, the immutability check and the next fetch's own "is this
posting already frozen?") over a packed store.
"""
import os
import time

import pytest
import yaml

from careeros.feeds import export
from careeros.feeds import store as store_module
from tests.test_ats_contract import fetch_one
from tests.test_ats_pool import args, script
from tests.test_personio_store import posting


@pytest.fixture
def store(tmp_path):
    return store_module.Store(tmp_path / 'personio')


def aged(store, days=40):
    """Every posting snapshot in the store, as old as the disk says."""
    when = time.time() - days * 86400
    paths = sorted((store.root / 'snapshots' / 'postings').rglob('*.yaml'))
    for path in paths:
        os.utime(path, (when, when))
    return paths


def test_a_packed_snapshot_is_the_same_snapshot_to_every_reader(store):
    record = posting()
    _, path, _ = store.write_posting_snapshot(record, run='r1')
    before = store.read_posting_snapshot('acme', '1', record['content_hash'])
    aged(store)

    report = store_module.compress_posting_snapshots(store, apply=True)
    assert report['compressed'] == 1
    assert not path.exists(), 'the plain file is replaced, not left beside the packed one'
    assert store_module.packed_path(path).exists()
    assert report['bytes_after'] < report['bytes_before']
    assert store.read_posting_snapshot('acme', '1', record['content_hash']) == before


def test_a_dry_run_names_every_candidate_and_changes_nothing(store):
    store.write_posting_snapshot(posting(), run='r1')
    store.write_posting_snapshot(posting(posting_id='2'), run='r1')
    paths = aged(store)
    frozen = {path: path.read_bytes() for path in paths}

    report = store_module.compress_posting_snapshots(store)
    assert report['applied'] is False
    assert report['candidates'] == [str(path) for path in paths]
    assert report['bytes_before'] == sum(len(blob) for blob in frozen.values())
    assert report['compressed'] == 0
    assert {path: path.read_bytes() for path in paths} == frozen


def test_a_snapshot_younger_than_the_cutoff_is_left_alone(store):
    record = posting()
    _, path, _ = store.write_posting_snapshot(record, run='r1')
    report = store_module.compress_posting_snapshots(store, apply=True)
    assert report == {'root': str(store.root), 'candidates': [], 'bytes_before': 0,
                      'bytes_after': 0, 'compressed': 0, 'failures': [], 'applied': True}
    assert path.exists()


def test_a_packed_posting_is_not_re_frozen_by_the_next_fetch(store):
    """The one way compression could corrupt the store: a packed
    snapshot that reads as missing would be written again, leaving two
    copies of one posting and reporting an unchanged posting as new."""
    record = posting()
    first, path, _ = store.write_posting_snapshot(record, run='r1')
    aged(store)
    store_module.compress_posting_snapshots(store, apply=True)

    again, packed, created = store.write_posting_snapshot(record, run='r2')
    assert (again, created) == (first, False)
    assert packed == store_module.packed_path(path)
    assert not path.exists()
    directory = path.parent
    assert sorted(item.name for item in directory.iterdir()) == [f'{path.name}.zst']

    changes = store_module.record_run(store, run='r2', at='2026-10-18T06:00:00+00:00',
                                      tenant_results={'acme': {'fetch_status': 'ok',
                                                               'postings': [record],
                                                               'error': None}})
    assert changes['acme']['new'] == [record['key']]
    assert changes['acme']['changed'] == []


def test_an_identical_write_over_a_packed_snapshot_is_still_a_no_op(store):
    path = store.feed_snapshot_path('acme', 'r1', 'de')
    store.write_snapshot(path, b'the body')
    store_module._pack(path)

    assert store.write_snapshot(path, b'the body') is False
    with pytest.raises(RuntimeError, match='immutable'):
        store.write_snapshot(path, b'another body')
    assert store_module.read_stored_bytes(store_module.packed_path(path)) == b'the body'


def test_the_pool_export_reads_a_packed_store(tmp_path):
    """The reader the day's work actually depends on: the golden-set pool
    is built from the snapshots, so a packed store must export the same
    rows."""
    store, result, _ = fetch_one('greenhouse', tmp_path)
    store.append_run({'run_id': 'r1', 'at': '2026-10-17T06:00:00+00:00'})
    store_module.record_run(store, run='r1', at='2026-10-17T06:00:00+00:00',
                            tenant_results={'acme': result})
    before, skipped = export.build_pool([store])
    assert before and skipped == []

    aged(store)
    assert store_module.compress_posting_snapshots(store, apply=True)['compressed'] == 1
    assert export.build_pool([store]) == (before, [])


def test_the_command_line_is_a_dry_run_until_it_is_told_otherwise(tmp_path, capsys):
    store, result, _ = fetch_one('greenhouse', tmp_path)
    store_module.record_run(store, run='r1', at='2026-10-17T06:00:00+00:00',
                            tenant_results={'acme': result})
    paths = aged(store)
    frozen = {path: path.read_bytes() for path in paths}

    assert script.cmd_compress(args('compress', store.root, 'greenhouse',
                                    older_than=30)) == 0
    out = capsys.readouterr().out
    assert str(paths[0]) in out, 'a dry run names the files it would pack'
    assert 'Pass --apply' in out
    assert {path: path.read_bytes() for path in paths} == frozen

    assert script.cmd_compress(args('compress', store.root, 'greenhouse',
                                    older_than=30, apply=True)) == 0
    out = capsys.readouterr().out
    assert 'freed' in out
    assert not paths[0].exists()
    packed = store_module.packed_path(paths[0])
    assert yaml.safe_load(store_module.read_stored_bytes(packed).decode())['posting']['key'] \
        == result['postings'][0]['key']
