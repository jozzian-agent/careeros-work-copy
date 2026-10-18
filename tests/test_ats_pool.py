"""The multi-provider golden-set pool, and the runner's two new gates.

What these protect: a pool row can name where it came from without
opening a snapshot (owner ruling 2026-10-17 2a), the pool spans
providers and says which strata it got from whom, and the runner refuses
a provider whose robots.txt disallows us unless it is told to proceed in
so many words.
"""
import importlib.util
from pathlib import Path

import pytest
import yaml

from careeros.feeds import export, registry
from careeros.feeds import store as store_module
from tests.test_ats_contract import fetch_one

ROOT = Path(__file__).resolve().parents[1]


def _module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _module('run_ats_fetch')


def stored(provider, tmp_path, *, tenant='acme'):
    """One provider's store with one Zurich posting recorded in it."""
    store, result, _ = fetch_one(provider, tmp_path, tenant=tenant)
    store.append_run({'run_id': 'r1', 'at': '2026-10-17T06:00:00+00:00'})
    store_module.record_run(store, run='r1', at='2026-10-17T06:00:00+00:00',
                            tenant_results={tenant: result})
    return store


# --- the pool ----------------------------------------------------------------

def test_the_pool_spans_providers_and_every_row_names_its_own(tmp_path):
    stores = [stored(provider, tmp_path) for provider in registry.PROVIDERS]
    rows, skipped = export.build_pool(stores)
    assert skipped == []
    assert len(rows) == len(registry.PROVIDERS)
    assert {row['provider'] for row in rows} == set(registry.PROVIDERS)
    assert [row['key'] for row in rows] == sorted(row['key'] for row in rows)


def test_a_pool_row_carries_the_whole_source_chain(tmp_path):
    rows, _ = export.build_pool([stored('greenhouse', tmp_path)])
    row = rows[0]
    assert row['provider'] == 'greenhouse'
    assert row['tenant'] == 'acme'
    assert row['url'].startswith('https://')
    assert row['feed_url'].startswith('https://boards-api.greenhouse.io/')
    assert row['feed_variant'] == 'boards-api.greenhouse.io:jobs'
    assert row['feed_snapshot'].endswith('.json.gz')
    assert row['content_hash'] and row['snapshot_id'].startswith('greenhouse:acme:')
    assert row['api_doc_url'] == 'https://docs.greenhouse.io/job-board.html'
    assert row['api_doc_accessed'] == '2026-10-17'
    assert row['run_id'] == 'r1' and row['fetched_at']


@pytest.mark.parametrize('posting,stratum,source', [
    ({'provider': 'personio', 'occupation': 'product_management',
      'occupation_category': 'marketing_and_product'},
     'product_management', "Personio's own occupation taxonomy"),
    ({'provider': 'recruitee', 'category_raw': 'internet', 'department': 'Eng'},
     'internet', "Recruitee's category_code"),
    ({'provider': 'smartrecruiters', 'function_raw': 'production',
      'industry_raw': 'packaging_and_containers'},
     'production', "SmartRecruiters' function and industry ids"),
    ({'provider': 'greenhouse', 'department': 'Sales'},
     'Sales', 'the department the employer typed'),
    ({'provider': 'lever', 'department': 'Customer Success'},
     'Customer Success', 'the department the employer typed'),
    ({'provider': 'ashby'}, None, 'no stratum'),
])
def test_a_row_says_which_kind_of_stratum_it_got(posting, stratum, source):
    """Three providers state a machine-readable occupation or function id
    and three state nothing but a department the employer typed. A
    stratified sample has to be able to tell those apart, so the row
    names the evidence rather than mixing the two."""
    found, _, said = export._stratum(posting)
    assert found == stratum
    assert source in said




def test_the_summary_breaks_the_pool_down_by_provider(tmp_path):
    stores = [stored(provider, tmp_path) for provider in ('greenhouse', 'lever')]
    rows, _ = export.build_pool(stores)
    summary = export.summarise(rows)
    assert summary['providers'] == 2
    assert summary['by_provider']['greenhouse'] == {'postings': 1, 'tenants': 1,
                                                    'with_description': 1}
    assert summary['tenants'] == 2, 'a tenant id is only unique within a provider'
    assert summary['by_work_model']['hybrid'] == 1, 'Lever states one; Greenhouse cannot'


def test_the_pool_file_names_every_provider_in_it(tmp_path):
    stores = [stored(provider, tmp_path) for provider in ('ashby', 'recruitee')]
    rows, _ = export.build_pool(stores)
    target = store_module.Store(tmp_path / 'combined', provider='combined')
    path = export.write_pool(target, rows, day='2026-10-17')
    data = yaml.safe_load(path.read_text())
    assert data['providers'] == ['ashby', 'recruitee']
    assert data['summary']['postings'] == 2
    assert len(data['postings']) == 2


# --- the runner's robots gate ------------------------------------------------

class _Robots:
    """A transport that answers robots.txt and nothing else."""

    def __init__(self, body):
        self.body = body
        self.requests = []

    def __call__(self, url, *, limiter=None, **options):
        self.requests.append(url)
        if url.endswith('/robots.txt'):
            return {'ok': True, 'status': 200, 'text': self.body, 'error': None,
                    'final_url': url, 'headers': {}}
        raise AssertionError(f'nothing else should have been fetched: {url}')


def seeded(tmp_path, provider, monkeypatch, robots):
    store = store_module.Store(tmp_path / provider, provider=provider)
    store.save_tenants({'acme': {'tenant': 'acme', 'status': 'candidate',
                                 'first_seen': '2026-10-17'}})
    monkeypatch.setattr(script.polite_http, 'request_text', _Robots(robots))
    return store


def args(command, root, provider, **overrides):
    extra = []
    for key, value in overrides.items():
        flag = '--' + key.replace('_', '-')
        if value is True:
            extra.append(flag)
        elif value is not None and value is not False:
            extra += [flag, str(value)]
    return script.build_parser().parse_args(
        ['--root', str(root), '--provider', provider, command] + extra)


def test_a_provider_whose_robots_txt_refuses_us_is_not_fetched(tmp_path, monkeypatch, capsys):
    """SmartRecruiters allows only LinkedIn's crawler on the path its own
    documentation publishes as public. An unattended run must not touch
    it by accident."""
    root = tmp_path / 'smartrecruiters'
    seeded(tmp_path, 'smartrecruiters', monkeypatch,
           'User-agent: LinkedInBot\nAllow: /v1/companies/\nUser-agent: *\nDisallow: /\n')
    assert script.cmd_fetch(args('fetch', root, 'smartrecruiters')) == 2
    out = capsys.readouterr().out
    assert 'robots.txt refuses smartrecruiters' in out
    assert '--robots-exception smartrecruiters' in out
    assert not (root / 'runs.yaml').exists(), 'nothing was recorded either'


def test_the_exception_is_explicit_prints_the_rules_and_is_recorded(tmp_path, monkeypatch,
                                                                    capsys):
    root = tmp_path / 'smartrecruiters'
    store = seeded(tmp_path, 'smartrecruiters', monkeypatch,
                   'User-agent: *\nDisallow: /\n')
    monkeypatch.setattr(script.fetch_module, 'fetch_tenant',
                        lambda tenant, **kwargs: {
                            'tenant': tenant, 'fetch_status': 'ok', 'error': None,
                            'host': 'api.smartrecruiters.com', 'languages': {},
                            'postings': [], 'publishes': {}, 'parse_failures': [],
                            'posting_failures': [], 'requests': 1, 'etags': {},
                            'details': {'requested': 0, 'ok': 0, 'failed': 0}})
    assert script.cmd_fetch(args('fetch', root, 'smartrecruiters',
                                 robots_exception='smartrecruiters')) == 0
    out = capsys.readouterr().out
    assert 'proceeding under the --robots-exception flag' in out
    assert 'Disallow: /' in out, "the rules it is overriding are printed, not summarised"
    entry = store.last_run()
    assert entry['robots']['allowed'] is False
    assert entry['robots']['exception_used'] is True
    assert entry['robots_requests'] == 1
    assert entry['api_doc_url'].startswith('https://developers.smartrecruiters.com/')


def test_a_provider_robots_allows_needs_no_flag(tmp_path, monkeypatch, capsys):
    root = tmp_path / 'greenhouse'
    store = seeded(tmp_path, 'greenhouse', monkeypatch,
                   'User-agent: *\nDisallow: /embed/\n')
    monkeypatch.setattr(script.fetch_module, 'fetch_tenant',
                        lambda tenant, **kwargs: {
                            'tenant': tenant, 'fetch_status': 'ok', 'error': None,
                            'host': 'boards-api.greenhouse.io', 'languages': {},
                            'postings': [], 'publishes': {}, 'parse_failures': [],
                            'posting_failures': [], 'requests': 1, 'etags': {},
                            'details': {'requested': 0, 'ok': 0, 'failed': 0}})
    assert script.cmd_fetch(args('fetch', root, 'greenhouse')) == 0
    assert store.last_run()['robots']['allowed'] is True
    assert 'robots' not in capsys.readouterr().out


def test_a_provider_with_no_adapter_is_not_fetchable_and_says_why(tmp_path, capsys):
    assert script.cmd_fetch(args('fetch', tmp_path / 'workday', 'workday')) == 1
    assert 'has no adapter' in capsys.readouterr().out


def test_each_provider_gets_its_own_store_root_and_personio_keeps_its_own(tmp_path):
    parsed = script.build_parser().parse_args(['--provider', 'greenhouse', 'report'])
    assert script._root(parsed) == Path('data/ats/greenhouse')
    parsed = script.build_parser().parse_args(['--provider', 'personio', 'report'])
    assert script._root(parsed) == Path('data/personio'), \
        "CAREER-53's store stays where its snapshots already are"


@pytest.mark.parametrize('provider,expected', [
    ('personio', {'languages': ('de', 'en')}),
    ('greenhouse', {}),
])
def test_only_the_adapter_that_has_languages_is_handed_any(provider, expected):
    """A provider with no language must not be handed one, so the
    adapter declares which options its `feed_variants` takes."""
    parsed = script.build_parser().parse_args(['--provider', provider, 'fetch'])
    assert script._variant_options(parsed, registry.adapter(provider)) == expected
