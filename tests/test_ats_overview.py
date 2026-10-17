"""Protects scripts/ats_overview.py: a posting URL is confident evidence
and a provider host alone is not, robots.txt stops a probe, a company
costs at most two page fetches, and a dead host is a counted skip rather
than a crash.

Every page here is a fixture string and every fetch is injected; no test
reaches the network.
"""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'ats_overview.py'


@pytest.fixture(scope='module')
def script():
    spec = importlib.util.spec_from_file_location('ats_overview', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def page(*hrefs):
    links = ''.join(f'<a href="{href}">x</a>' for href in hrefs)
    return f'<html><body>{links}</body></html>'


def fetcher(pages, *, calls=None):
    """A fetch double: a URL in `pages` answers with that HTML, anything
    else answers like an unreachable host."""
    def fetch(url, *, limiter=None, **kwargs):
        if calls is not None:
            calls.append(url)
        if url in pages:
            return {'ok': True, 'status': 200, 'text': pages[url],
                    'final_url': pages.get(url + '#final', url), 'error': None}
        return {'ok': False, 'status': None, 'text': '', 'final_url': url,
                'error': 'URLError: nope'}
    return fetch


def allow_all(url, *, cache=None, limiter=None, fetch=None):
    return True, 'no robots.txt (HTTP 404)'


#
# Link reading.
#
def test_page_links_absolutises_dedupes_and_drops_non_http(script):
    links = script.page_links(
        page('/careers', 'careers', 'https://boards.greenhouse.io/acme/jobs/1',
             'mailto:a@b.ch', '#top', 'javascript:void(0)', '/careers'),
        'https://acme.ch/en/')
    assert links == ['https://acme.ch/careers',
                     'https://acme.ch/en/careers',
                     'https://boards.greenhouse.io/acme/jobs/1']


def test_a_malformed_page_still_yields_the_links_it_had(script):
    links = script.page_links('<a href="/jobs">x</a><div <<<', 'https://acme.ch/')
    assert 'https://acme.ch/jobs' in links


@pytest.mark.parametrize('path, expected', [
    ('/careers', True), ('/en/offene-stellen', True), ('/jobs/123', True),
    ('/de/arbeiten-bei-uns', True), ('/about', False), ('/', False),
])
def test_looks_like_careers(script, path, expected):
    assert script.looks_like_careers(f'https://acme.ch{path}') is expected


#
# Tier 4: a provider host is a hint, and a lookalike host is not even that.
#
@pytest.mark.parametrize('url, expected', [
    ('https://boards.greenhouse.io/acme', 'greenhouse'),
    ('https://acme.myworkdayjobs.com/en-US/careers', 'workday'),
    ('https://m.refline.ch/615/', 'refline'),
    # Exact-or-dot-prefixed, like the capability's own host checks: a
    # lookalike must never match on a substring.
    ('https://boards.greenhouse.io.attacker.example/acme', None),
    ('https://notmyworkdayjobs.com/x', None),
    ('https://acme.ch/careers', None),
])
def test_ats_host_provider(script, url, expected):
    assert script.ats_host_provider(url) == expected


#
# Tiers 1 and 2: what the vault already knows, with no network at all.
#
def test_recorded_providers_reads_the_three_places_it_can_be_known(script):
    assert script.recorded_providers(
        {'identifiers': [{'type': 'ats_tenant', 'value': 'workday:acme'},
                         {'type': 'domain', 'value': 'acme.ch'}]}) == {'workday'}
    assert script.recorded_providers(
        {'sources': [{'ats_provider': 'ashby'}]}) == {'ashby'}
    assert script.recorded_providers(
        {'website': 'https://jobs.lever.co/acme/1234'}) == {'lever'}
    assert script.recorded_providers({'website': 'https://acme.ch'}) == set()


def test_a_company_with_no_website_and_no_domain_is_not_a_target(script):
    targets = script.probe_targets(
        [{'id': 'CO-001', 'name': 'No Web AG'},
         {'id': 'CO-002', 'name': 'Has Web AG', 'website': 'https://acme.ch'}],
        [], limit=10)
    assert [target['company_id'] for target in targets] == ['CO-002']
    assert targets[0]['domain'] == 'acme.ch'


def test_seeded_companies_without_a_domain_contribute_nothing(script):
    """Today that is all of them: Zefix has no website field."""
    targets = script.probe_targets([], [{'name': 'Hedonia AG', 'domain': None},
                                         {'name': 'Other AG', 'domain': 'other.ch'}], limit=10)
    assert [target['name'] for target in targets] == ['Other AG']


def test_the_cap_limits_the_targets(script):
    records = [{'id': f'CO-{i:03}', 'name': f'C {i}', 'website': f'https://c{i}.ch'}
               for i in range(10)]
    assert len(script.probe_targets(records, [], limit=3)) == 3


#
# Tiers 3 and 4: the probe itself.
#
def test_a_posting_url_on_the_careers_page_is_confident_evidence(script, monkeypatch):
    monkeypatch.setattr(script.polite_http, 'robots_allows', allow_all)
    calls = []
    fetch = fetcher({
        'https://acme.ch': page('/about', '/careers'),
        'https://acme.ch/careers': page('https://boards.greenhouse.io/acme/jobs/9981'),
    }, calls=calls)
    row = script.probe({'website': 'https://acme.ch', 'domain': 'acme.ch'},
                       limiter=None, robots_cache={}, fetch=fetch)
    assert row['confident'] == ['greenhouse']
    assert row['host_only'] == []
    assert row['pages'] == 2
    # Two page fetches, no more: the homepage and one careers link.
    assert calls == ['https://acme.ch', 'https://acme.ch/careers']


def test_a_provider_host_without_a_posting_shape_is_host_only(script, monkeypatch):
    monkeypatch.setattr(script.polite_http, 'robots_allows', allow_all)
    fetch = fetcher({'https://acme.ch': page('https://boards.greenhouse.io/acme')})
    row = script.probe({'website': 'https://acme.ch', 'domain': 'acme.ch'},
                       limiter=None, robots_cache={}, fetch=fetch)
    assert row['confident'] == []
    assert row['host_only'] == ['greenhouse']


def test_a_provider_seen_as_a_posting_is_not_also_counted_as_host_only(script, monkeypatch):
    monkeypatch.setattr(script.polite_http, 'robots_allows', allow_all)
    fetch = fetcher({'https://acme.ch': page('https://boards.greenhouse.io/acme',
                                             'https://boards.greenhouse.io/acme/jobs/1')})
    row = script.probe({'website': 'https://acme.ch', 'domain': 'acme.ch'},
                       limiter=None, robots_cache={}, fetch=fetch)
    assert row['confident'] == ['greenhouse']
    assert row['host_only'] == []


def test_where_the_careers_link_redirects_to_is_itself_evidence(script, monkeypatch):
    monkeypatch.setattr(script.polite_http, 'robots_allows', allow_all)
    fetch = fetcher({
        'https://acme.ch': page('/jobs'),
        'https://acme.ch/jobs': page(),
        'https://acme.ch/jobs#final': 'https://jobs.lever.co/acme/1a2b-3c4d',
    })
    row = script.probe({'website': 'https://acme.ch', 'domain': 'acme.ch'},
                       limiter=None, robots_cache={}, fetch=fetch)
    assert row['confident'] == ['lever']


def test_robots_disallow_skips_the_company_with_a_reason(script, monkeypatch):
    monkeypatch.setattr(script.polite_http, 'robots_allows',
                        lambda url, **kwargs: (False, 'disallowed by robots.txt'))
    fetch = fetcher({'https://acme.ch': page('https://jobs.lever.co/acme/1')})
    row = script.probe({'website': 'https://acme.ch', 'domain': 'acme.ch'},
                       limiter=None, robots_cache={}, fetch=fetch)
    assert row['probed'] is False
    assert row['skip_reason'] == 'disallowed by robots.txt'
    assert row['confident'] == []


def test_a_dead_host_is_a_counted_skip_not_a_crash(script, monkeypatch):
    monkeypatch.setattr(script.polite_http, 'robots_allows', allow_all)
    row = script.probe({'website': 'https://gone.example', 'domain': 'gone.example'},
                       limiter=None, robots_cache={}, fetch=fetcher({}))
    assert row['probed'] is False
    assert 'homepage:' in row['skip_reason']


def test_a_careers_page_its_own_robots_refuses_is_not_fetched(script, monkeypatch):
    def robots(url, **kwargs):
        return ('/careers' not in url), 'robots.txt'

    monkeypatch.setattr(script.polite_http, 'robots_allows', robots)
    calls = []
    fetch = fetcher({'https://acme.ch': page('/careers')}, calls=calls)
    row = script.probe({'website': 'https://acme.ch', 'domain': 'acme.ch'},
                       limiter=None, robots_cache={}, fetch=fetch)
    assert calls == ['https://acme.ch']
    assert row['pages'] == 1


#
# scripts/polite_http.robots_allows, tested here because ats_overview.py
# is the only caller that consults it (the seeding script's own
# robots.txt decision is recorded in its docstring, not made in code).
#
def robots_fetcher(answer):
    def fetch(url, *, limiter=None, **kwargs):
        assert url.endswith('/robots.txt')
        return answer
    return fetch


def test_robots_refuses_what_it_disallows(script):
    allowed, reason = script.polite_http.robots_allows(
        'https://acme.ch/careers',
        fetch=robots_fetcher({'ok': True, 'status': 200, 'error': None,
                              'final_url': 'x', 'text': 'User-agent: *\nDisallow: /\n'}))
    assert (allowed, reason) == (False, 'disallowed by robots.txt')


def test_robots_allows_a_path_its_rules_permit(script):
    allowed, _ = script.polite_http.robots_allows(
        'https://acme.ch/careers',
        fetch=robots_fetcher({'ok': True, 'status': 200, 'error': None, 'final_url': 'x',
                              'text': 'User-agent: *\nDisallow: /private\n'}))
    assert allowed is True


def test_a_missing_robots_txt_is_no_restriction(script):
    allowed, reason = script.polite_http.robots_allows(
        'https://acme.ch/', fetch=robots_fetcher(
            {'ok': False, 'status': 404, 'text': '', 'final_url': 'x', 'error': 'HTTP 404'}))
    assert allowed is True
    assert '404' in reason


def test_an_unreadable_robots_txt_counts_as_a_refusal(script):
    """A sweep that cannot read the rules does not guess in its own
    favour."""
    allowed, reason = script.polite_http.robots_allows(
        'https://acme.ch/', fetch=robots_fetcher(
            {'ok': False, 'status': 503, 'text': '', 'final_url': 'x', 'error': 'HTTP 503'}))
    assert allowed is False
    assert 'unreadable' in reason


def test_robots_txt_is_fetched_once_per_host(script):
    calls = []

    def fetch(url, *, limiter=None, **kwargs):
        calls.append(url)
        return {'ok': True, 'status': 200, 'error': None, 'final_url': url,
                'text': 'User-agent: *\nDisallow: /private\n'}

    cache = {}
    for path in ('/', '/careers', '/private'):
        script.polite_http.robots_allows(f'https://acme.ch{path}', cache=cache, fetch=fetch)
    script.polite_http.robots_allows('https://other.ch/', cache=cache, fetch=fetch)
    assert calls == ['https://acme.ch/robots.txt', 'https://other.ch/robots.txt']


#
# The report.
#
def test_summarise_counts_each_strength_of_evidence_separately(script):
    rows = [
        {'probed': True, 'recorded': ['workday'], 'confident': [], 'host_only': []},
        {'probed': True, 'recorded': [], 'confident': ['greenhouse'], 'host_only': []},
        {'probed': True, 'recorded': [], 'confident': [], 'host_only': ['workday']},
        {'probed': False, 'recorded': [], 'confident': [], 'host_only': [],
         'skip_reason': 'robots.txt'},
    ]
    summary = script.summarise(rows)
    assert summary['considered'] == 4
    assert summary['probed'] == 3
    assert summary['detected'] == 3
    assert summary['recorded']['workday'] == 1
    assert summary['host_only']['workday'] == 1
    assert summary['any'] == {'workday': 2, 'greenhouse': 1}
    assert len(summary['skipped']) == 1


def test_top_employers_rank_by_size_then_open_jobs(script):
    rows = [{'name': 'Small', 'size_class': 'small', 'open_jobs': 9},
            {'name': 'Big', 'size_class': 'large', 'open_jobs': 0},
            {'name': 'Mid A', 'size_class': 'medium', 'open_jobs': 1},
            {'name': 'Mid B', 'size_class': 'medium', 'open_jobs': 4},
            {'name': 'Unknown', 'size_class': None, 'open_jobs': 0}]
    assert [row['name'] for row in sorted(rows, key=script.rank_key)] == [
        'Big', 'Mid B', 'Mid A', 'Small', 'Unknown']


def test_every_size_class_the_vault_knows_ranks_above_micro(script):
    """The ranking reads vault.SIZE_CLASSES rather than listing the
    classes again, so a class added to that fixed list is ranked by its
    place in the vocabulary instead of silently landing below micro,
    where an unknown class sits."""
    from careeros import vault
    assert set(script.SIZE_RANK) == set(vault.SIZE_CLASSES)
    assert script.SIZE_RANK['micro'] == min(script.SIZE_RANK.values())
    for name in vault.SIZE_CLASSES:
        if name != 'micro':
            assert script.SIZE_RANK[name] > script.SIZE_RANK['micro'], name
        # An unrecognised class ranks below every real one, so it sorts
        # last rather than jumping the table.
        assert script.rank_key({'size_class': name}) < script.rank_key({'size_class': 'unknown'})


@pytest.mark.parametrize('locations, expected', [
    (['Switzerland, Zürich, Zürich'], True),
    (['Zurich'], True),
    (['Switzerland, Zug, Zug'], False),
    ([], False),
    ([None], False),
])
def test_is_zurich(script, locations, expected):
    assert script.is_zurich(locations) is expected


def test_the_report_states_its_limits_and_its_politeness(script, tmp_path):
    rows = [{'name': 'Acme AG', 'size_class': 'large', 'open_jobs': 2, 'probed': True,
             'locations': ['Switzerland, Zürich'], 'recorded': [], 'confident': ['workday'],
             'host_only': []}]
    args = type('Args', (), {'vault': tmp_path, 'min_interval': 1.0})()
    text = script.render(rows, script.summarise(rows), args=args,
                         limiter=script.polite_http.RateLimiter(0),
                         seed_file=None, seed_total=0, seed_domains=0, probing=True)
    assert '1/1 (100%)' in text
    assert 'Zefix carries no website field' in text
    assert 'upper bound' in text
    assert script.polite_http.USER_AGENT in text
    assert 'Nothing was written to the vault.' in text
    assert '| workday | 0 | 1 | 0 | 1 |' in text


def test_a_run_with_no_probing_touches_no_network(script, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('--no-probe must not touch the network')

    monkeypatch.setattr(script.polite_http, 'request_text', forbidden)
    monkeypatch.setattr(script.vault, 'list_companies', lambda root: [
        {'id': 'CO-001', 'name': 'Acme AG', 'website': 'https://jobs.ashbyhq.com/acme/1',
         'size_class': 'large', 'locations': ['Zürich']}])
    monkeypatch.setattr(script.vault, 'list_jobs', lambda root: [])
    out = tmp_path / 'ats.md'
    assert script.main(['--vault', str(tmp_path), '--no-probe', '--out', str(out)]) == 0
    text = out.read_text()
    assert 'ashby' in text
    assert 'probing was off for this run' in text


def test_an_existing_report_is_not_overwritten_without_force(script, tmp_path):
    out = tmp_path / 'ats.md'
    out.write_text('read by the founder\n')
    with pytest.raises(SystemExit, match='--force'):
        script.main(['--vault', str(tmp_path), '--no-probe', '--out', str(out)])
    assert out.read_text() == 'read by the founder\n'
