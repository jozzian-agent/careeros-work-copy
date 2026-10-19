"""`scripts/run_personio_fetch.py`: the subcommands and the fetch queue.

The runner is wiring, so these tests are about the decisions it makes
that nothing else does: which tenants a capped run spends its budget on,
what a tenant's record says after a fetch, and that every subcommand is
safe to run twice. Its network call is monkeypatched out; the one
subcommand that reads live data here reads a replayed index file.
"""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from careeros.feeds import discovery, geocode, store as store_module
from tests.test_personio_runner import FakePersonio  # noqa: F401  (the recorded feeds)

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        'run_personio_fetch', ROOT / 'scripts' / 'run_personio_fetch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _module()


@pytest.fixture
def root(tmp_path):
    return tmp_path / 'personio'


def args(command, root, **overrides):
    """The parsed arguments for one subcommand, with `--root` set."""
    extra = []
    for key, value in overrides.items():
        flag = '--' + key.replace('_', '-')
        if value is True:
            extra.append(flag)
        elif value is not None and value is not False:
            extra += [flag, str(value)]
    # `--root` is a top-level option, so it goes before the subcommand.
    return script.build_parser().parse_args(['--root', str(root), command] + extra)


# --- discover ----------------------------------------------------------------

def test_discover_reads_a_vault_without_writing_to_it(root, monkeypatch, capsys):
    """The vault is opened read-only for route 1 and for nothing else."""
    monkeypatch.setattr(script.vault, 'list_companies', lambda path: [
        {'name': 'Bring Labs AG', 'website': 'https://www.bringlabs.com/',
         'identifiers': [{'type': 'ats_tenant', 'value': 'personio:bring-labs'}]}])
    monkeypatch.setattr(script.vault, 'list_owned_jobs', lambda path: [
        {'ats_provider': 'personio', 'ats_tenant': 'isolutions',
         'url': 'https://isolutions.jobs.personio.de/job/1'}])
    parsed = args('discover', root, vault='/some/vault', zefix_file='/nowhere.yaml')
    assert script.cmd_discover(parsed) == 0
    tenants = store_module.Store(root).load_tenants()
    assert sorted(tenants) == ['bring-labs', 'isolutions']
    assert tenants['bring-labs']['status'] == discovery.CANDIDATE
    assert tenants['bring-labs']['first_seen']
    assert 'vault: 2 tenant(s)' in capsys.readouterr().out


def test_discover_replays_a_saved_index_file_with_no_live_call(root, capsys):
    """`--from-file` is the route for an owner who declines the
    robots.txt reasoning: discovery with no call to Common Crawl at all."""
    saved = root.parent / 'cdx.jsonl'
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text('\n'.join(json.dumps({'url': url}) for url in (
        'https://acme.jobs.personio.de/job/1',
        'https://brue.jobs.personio.de/',
        'https://not-personio.example.com/')))
    parsed = args('discover', root, common_crawl=True, from_file=saved,
                  zefix_file='/nowhere.yaml')
    assert script.cmd_discover(parsed) == 0
    tenants = store_module.Store(root).load_tenants()
    assert sorted(tenants) == ['acme', 'brue']
    assert tenants['acme']['discovered_via'].startswith('common_crawl_replay:')
    stored = yaml.safe_load(store_module.Store(root).tenants_file.read_text())
    assert stored['discovery_routes']['common_crawl']['urls'] == 3
    assert stored['sources']['common_crawl_terms'] == discovery.CDX_TERMS


def test_discover_twice_adds_nothing_the_second_time(root, monkeypatch, capsys):
    monkeypatch.setattr(script.vault, 'list_companies', lambda path: [])
    monkeypatch.setattr(script.vault, 'list_owned_jobs', lambda path: [
        {'ats_provider': 'personio', 'ats_tenant': 'acme', 'url': 'https://x/'}])
    parsed = args('discover', root, vault='/some/vault', zefix_file='/nowhere.yaml')
    script.cmd_discover(parsed)
    capsys.readouterr()
    script.cmd_discover(parsed)
    assert '(+0 new)' in capsys.readouterr().out


def test_discover_records_a_name_only_zefix_candidate(root, monkeypatch, tmp_path):
    monkeypatch.setattr(script.vault, 'list_companies', lambda path: [
        {'name': 'Bring! Labs AG',
         'identifiers': [{'type': 'ats_tenant', 'value': 'personio:bring-labs'}]}])
    monkeypatch.setattr(script.vault, 'list_owned_jobs', lambda path: [])
    seed = tmp_path / 'zefix.yaml'
    seed.write_text(yaml.safe_dump({'companies': [
        {'name': 'BRING LABS AG', 'uid': 'CHE-123.456.789', 'seat': 'Zürich'}]}))
    parsed = args('discover', root, vault='/some/vault', zefix_file=seed)
    script.cmd_discover(parsed)
    tenants = store_module.Store(root).load_tenants()
    assert tenants['bring-labs']['zefix_match']['confident'] is False
    assert tenants['bring-labs']['zefix_match']['candidates'][0]['uid'] == 'CHE-123.456.789'


def test_a_missing_zefix_file_is_a_printed_note_and_not_a_crash(root, capsys):
    assert script._load_zefix(Path('/nowhere.yaml')) == []
    assert 'dedupe skipped' in capsys.readouterr().out
    assert script._load_zefix(None) == []


# --- the fetch queue ---------------------------------------------------------

def queue(tenants, **overrides):
    return script._fetch_queue(tenants, args('fetch', Path('/tmp/x'), **overrides))


def test_a_capped_run_spends_its_budget_on_the_confirmed_zurich_tenants_first():
    """A `--max-tenants` cap that cut off the confirmed ones would make
    the pool shrink every run."""
    tenants = {
        'cand': {'status': discovery.CANDIDATE},
        'zurich': {'status': discovery.CONFIRMED_ZURICH},
        'foreign': {'status': discovery.NO_ZURICH_OFFICE},
    }
    assert queue(tenants, max_tenants=2) == ['zurich', 'cand']


def test_the_tenant_fetched_longest_ago_goes_first_within_a_status():
    tenants = {'a': {'status': discovery.CANDIDATE, 'last_fetch_run': '20261017'},
               'b': {'status': discovery.CANDIDATE},
               'c': {'status': discovery.CANDIDATE, 'last_fetch_run': '20261001'}}
    assert queue(tenants) == ['b', 'c', 'a']


def test_a_tenant_whose_feed_was_unreadable_is_left_out_unless_asked_for():
    tenants = {'live': {'status': discovery.CANDIDATE},
               'dead': {'status': discovery.SKIPPED}}
    assert queue(tenants) == ['live']
    assert sorted(queue(tenants, include_skipped=True)) == ['dead', 'live']


def test_a_named_tenant_list_wins_and_unknown_names_are_dropped():
    tenants = {'acme': {'status': discovery.CANDIDATE}}
    parsed = args('fetch', Path('/tmp/x'))
    parsed.tenants = ['acme', 'nobody']
    assert script._fetch_queue(tenants, parsed) == ['acme']


def test_a_sample_is_drawn_from_the_whole_queue_and_reproduces_from_its_seed():
    """A capped run is otherwise alphabetical, which is useless for
    measuring the share of tenants with a Zurich office."""
    tenants = {f'tenant-{index:03d}': {'status': discovery.CANDIDATE}
               for index in range(100)}
    first = queue(tenants, sample=10, seed=1)
    assert len(first) == 10
    assert first == queue(tenants, sample=10, seed=1)
    assert first != queue(tenants, sample=10, seed=2)
    assert first != sorted(tenants)[:10], 'a sample is not the alphabetical head'


def test_a_sample_larger_than_the_queue_is_the_whole_queue():
    tenants = {'a': {'status': discovery.CANDIDATE}, 'b': {'status': discovery.CANDIDATE}}
    assert sorted(queue(tenants, sample=50)) == ['a', 'b']


# --- what a fetch writes onto a tenant's record ------------------------------

def tenant_after(result, record=None):
    record = record if record is not None else {'tenant': 't', 'status': discovery.CANDIDATE}
    zurich = [posting for posting in result['postings']
              if posting['area_status'] == geocode.IN_AREA]
    script._update_tenant(record, result, run='r1', at='2026-10-17T06:00:00+00:00',
                          zurich=zurich)
    return record


def test_a_tenant_with_a_zurich_posting_is_confirmed_with_its_evidence(root):
    store = store_module.Store(root)
    result = script.fetch_module.fetch_tenant(
        'isolutions', store=store, run='r1', fetch=FakePersonio(), languages=('de',),
        sleep=lambda seconds: None)
    record = tenant_after(result)
    assert record['status'] == discovery.CONFIRMED_ZURICH
    assert 'geocode to canton Zurich' in record['status_reason']
    assert record['municipalities'] == ['261']
    assert record['company_name'] == 'isolutions AG'
    assert record['zurich_postings_seen'] == 3
    assert record['feeds']['de']['etag']
    assert record['last_fetch_status'] == 'ok'


def test_a_confirmed_tenant_stays_confirmed_when_its_zurich_jobs_all_close(root):
    """A tenant whose Zurich postings are all closed today is still a
    Zurich employer; demoting it would drop it out of the queue's front
    and hide its next opening."""
    record = {'tenant': 'isolutions', 'status': discovery.CONFIRMED_ZURICH}
    tenant_after({'fetch_status': 'ok', 'postings': [], 'error': None, 'host': 'h',
                  'etags': {}, 'publishes': {}}, record)
    assert record['status'] == discovery.CONFIRMED_ZURICH


def test_a_tenant_with_no_zurich_office_says_so_rather_than_being_dropped(root):
    store = store_module.Store(root)
    result = script.fetch_module.fetch_tenant(
        'knott', store=store, run='r1', fetch=FakePersonio(), languages=('de',),
        sleep=lambda seconds: None)
    record = tenant_after(result)
    assert record['status'] == discovery.NO_ZURICH_OFFICE
    assert 'no office geocodes to canton Zurich' in record['status_reason']


def test_an_empty_feed_keeps_the_tenant_valid_and_says_the_feed_is_empty(root):
    store = store_module.Store(root)
    result = script.fetch_module.fetch_tenant(
        'mapegy', store=store, run='r1', fetch=FakePersonio(), languages=('de',),
        sleep=lambda seconds: None)
    record = tenant_after(result)
    assert record['status'] == discovery.NO_ZURICH_OFFICE
    assert 'is empty' in record['status_reason']
    assert record['last_fetch_status'] == 'ok'


def test_an_unreadable_feed_skips_a_candidate_with_the_reason(root):
    record = tenant_after({'fetch_status': 'not_found', 'postings': [], 'error': 'HTTP 404',
                           'host': None, 'etags': {}, 'publishes': {}})
    assert record['status'] == discovery.SKIPPED
    assert record['status_reason'] == 'feed unreadable: not_found'
    assert record['last_fetch_error'] == 'HTTP 404'


# --- fetch, export and report, end to end through the command line -----------

def seeded(root, monkeypatch, tenants=('isolutions', 'bring-labs', 'knott')):
    store = store_module.Store(root)
    store.save_tenants({tenant: {'tenant': tenant, 'status': discovery.CANDIDATE,
                                 'first_seen': '2026-10-17'} for tenant in tenants})
    monkeypatch.setattr(script.polite_http, 'request_text', FakePersonio())
    monkeypatch.setattr(script.fetch_module.time, 'sleep', lambda seconds: None)
    return store


def test_fetch_writes_a_run_entry_with_the_numbers_the_spec_asks_for(root, monkeypatch, capsys):
    store = seeded(root, monkeypatch)
    assert script.cmd_fetch(args('fetch', root)) == 0
    entry = store.last_run()
    assert entry['tenants_queued'] == 3
    assert entry['tenants_ok'] == 3
    assert entry['postings_seen'] == 8
    assert entry['zurich_postings'] == 5
    assert entry['zurich_geocoded_to_municipality'] == 5
    assert entry['new_postings'] == 8
    assert entry['closed_postings'] == 0
    assert entry['user_agent'] == script.polite_http.USER_AGENT
    assert entry['rate_limit_seconds'] == 1.0
    assert entry['parse_failures'] == []
    assert 'parse success: 100.0%' in capsys.readouterr().out


def test_fetch_with_no_tenants_says_to_discover_first(root, capsys):
    assert script.cmd_fetch(args('fetch', root)) == 1
    assert 'run discover first' in capsys.readouterr().out


def test_a_second_fetch_of_an_unchanged_feed_reports_no_change(root, monkeypatch, capsys):
    store = seeded(root, monkeypatch)
    script.cmd_fetch(args('fetch', root))
    capsys.readouterr()
    script.cmd_fetch(args('fetch', root))
    entry = store.last_run()
    assert entry['new_postings'] == 0
    assert entry['changed_postings'] == 0
    assert entry['closed_postings'] == 0
    assert len(store.load_runs()) == 2


def test_export_writes_the_pool_and_its_taxonomy_versions(root, monkeypatch, capsys):
    seeded(root, monkeypatch)
    script.cmd_fetch(args('fetch', root))
    capsys.readouterr()
    assert script.cmd_export(args('export', root, day='2026-10-17')) == 0
    path = store_module.Store(root).export_path('2026-10-17')
    data = yaml.safe_load(path.read_text())
    assert data['summary']['postings'] == 5
    assert data['taxonomy_version']['municipality']
    assert data['skipped'] == 3
    assert set(data['skipped_reasons']) == {geocode.OUT_OF_AREA, geocode.NEEDS_REVIEW}
    assert '5 posting(s) exported' in capsys.readouterr().out


def test_report_prints_the_last_run_and_the_tenant_and_posting_tallies(
        root, monkeypatch, capsys):
    seeded(root, monkeypatch)
    script.cmd_fetch(args('fetch', root))
    capsys.readouterr()
    assert script.cmd_report(args('report', root)) == 0
    out = capsys.readouterr().out
    assert 'tenants: 3 ok, 0 failed' in out
    assert 'postings tracked: 8 open, 0 suspected closing, 0 closed' in out
    assert f'2 {discovery.CONFIRMED_ZURICH}' in out


def test_report_with_no_runs_says_so(root, capsys):
    assert script.cmd_report(args('report', root)) == 1
    assert 'no runs recorded yet' in capsys.readouterr().out


def test_report_can_be_asked_for_a_named_run(root, monkeypatch, capsys):
    store = seeded(root, monkeypatch)
    script.cmd_fetch(args('fetch', root))
    run = store.last_run()['run_id']
    capsys.readouterr()
    assert script.cmd_report(args('report', root, run=run)) == 0
    assert run in capsys.readouterr().out
    assert script.cmd_report(args('report', root, run='nope')) == 1


def test_the_parser_requires_a_subcommand():
    with pytest.raises(SystemExit):
        script.build_parser().parse_args([])


def test_a_skipped_language_keeps_its_marker_across_runs(root, monkeypatch, capsys):
    """A language this run skipped returns no etag entry, so replacing
    the feed state rather than merging it would lose the
    `publishes: False` marker and the skip would work only every other
    run."""
    seeded(root, monkeypatch, tenants=('isolutions',))
    store = store_module.Store(root)
    for _ in range(3):
        script.cmd_fetch(args('fetch', root))
    capsys.readouterr()
    record = store.load_tenants()['isolutions']
    assert record['feeds']['en']['publishes'] is False
    assert record['feeds']['de']['publishes'] is True
    requests = [entry['requests'] for entry in store.load_runs()]
    assert requests == [2, 1, 1], 'English is asked once, then never again'


def test_a_fetch_keeps_the_discovery_report_in_the_tenant_file(root, monkeypatch, capsys):
    monkeypatch.setattr(script.vault, 'list_companies', lambda path: [])
    monkeypatch.setattr(script.vault, 'list_owned_jobs', lambda path: [
        {'ats_provider': 'personio', 'ats_tenant': 'isolutions', 'url': 'https://x/'}])
    script.cmd_discover(args('discover', root, vault='/some/vault',
                             zefix_file='/nowhere.yaml'))
    monkeypatch.setattr(script.polite_http, 'request_text', FakePersonio())
    monkeypatch.setattr(script.fetch_module.time, 'sleep', lambda seconds: None)
    script.cmd_fetch(args('fetch', root))
    capsys.readouterr()
    stored = yaml.safe_load(store_module.Store(root).tenants_file.read_text())
    assert stored['discovery_routes']['vault']['tenants'] == 1
    assert stored['last_fetch_run']
