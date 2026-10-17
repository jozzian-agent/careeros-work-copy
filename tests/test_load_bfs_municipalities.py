"""The BFS municipality loader, and the file it writes.

CAREER-55 shipped `location.yaml`'s municipality dimension as an honest
stub with the register named as its source; CAREER-53 needed the numbers
and `scripts/load_bfs_municipalities.py` loaded them. These tests are
about the loader's guards, because the thing it can get wrong is to
overwrite 2 110 real municipality numbers with a partial answer.

No network: every test either replays a saved response shape or passes
its own transport.
"""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_FILE = ROOT / 'careeros' / 'data' / 'taxonomy' / 'location.yaml'


def _module():
    spec = importlib.util.spec_from_file_location(
        'load_bfs_municipalities', ROOT / 'scripts' / 'load_bfs_municipalities.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _module()


def bindings(*rows):
    """A SPARQL results document in the shape LINDAS answers with."""
    return {'head': {'vars': ['muni', 'name', 'canton', 'plz']},
            'results': {'bindings': [
                {'muni': {'value': f'https://ld.admin.ch/municipality/{code}'},
                 'name': {'value': name},
                 'canton': {'value': f'https://ld.admin.ch/canton/{canton}'},
                 **({'plz': {'value': plz}} if plz else {})}
                for code, name, canton, plz in rows]}}


def whole_register(extra=()):
    """Enough rows to clear every guard: 26 cantons, 1 800+ rows, 160 in
    canton Zurich."""
    rows = [(str(code), f'Zurich town {code}', '1', f'8{code:03d}')
            for code in range(1, 161)]
    code = 1000
    for canton in range(2, 27):
        for _ in range(70):
            code += 1
            rows.append((str(code), f'Town {code}', str(canton), f'{canton:02d}{code % 100:02d}'))
    return bindings(*rows, *extra)


# --- parsing -----------------------------------------------------------------

def test_rows_are_folded_by_municipality_number():
    """One row per (municipality, postal code) pair comes back, so a
    municipality with several postal codes is several rows."""
    parsed = script.parse_rows(bindings(
        ('261', 'Zürich', '1', '8001'), ('261', 'Zürich', '1', '8004'),
        ('230', 'Winterthur', '1', '8400')))
    assert parsed['261'] == {'code': '261', 'label': 'Zürich', 'canton': '1',
                             'postal_codes': ['8001', '8004']}
    assert parsed['230']['postal_codes'] == ['8400']


def test_a_municipality_with_no_postal_code_is_kept_with_an_empty_list():
    """It is still a real municipality and a name match can still land
    on it; dropping it would lose a code the register has."""
    parsed = script.parse_rows(bindings(('1', 'Aeugst am Albis', '1', None)))
    assert parsed['1']['postal_codes'] == []


def test_postal_codes_come_back_sorted_so_two_loads_diff_cleanly():
    parsed = script.parse_rows(bindings(
        ('261', 'Zürich', '1', '8004'), ('261', 'Zürich', '1', '8001')))
    assert parsed['261']['postal_codes'] == ['8001', '8004']


def test_one_number_with_two_names_is_refused_rather_than_resolved():
    """That means the deprecated-version filter let a historical entry
    through, and picking one of them would be a coin toss."""
    with pytest.raises(RuntimeError, match='came back twice'):
        script.parse_rows(bindings(('261', 'Zürich', '1', '8001'),
                                   ('261', 'Zurich (old)', '1', '8001')))


def test_a_document_that_is_not_sparql_results_is_refused():
    with pytest.raises(RuntimeError, match='not a SPARQL results document'):
        script.parse_rows({'nothing': 'useful'})
    with pytest.raises(RuntimeError, match='missing muni, name or canton'):
        script.parse_rows({'results': {'bindings': [{'muni': {'value': 'x'}}]}})


def test_a_uri_that_is_not_a_number_is_refused():
    with pytest.raises(RuntimeError, match='unexpected URI shape'):
        script.parse_rows(bindings(('zurich', 'Zürich', '1', '8001')))


# --- the guards --------------------------------------------------------------

def test_a_partial_answer_never_overwrites_a_working_list():
    """The failure this guard exists for: a query that silently returned
    half the register would retire thousands of real codes."""
    with pytest.raises(RuntimeError, match='partial answer'):
        script.check_load(script.parse_rows(bindings(('261', 'Zürich', '1', '8001'))))


def test_a_load_missing_a_canton_is_refused():
    document = whole_register()
    short = {code: entry for code, entry in script.parse_rows(document).items()
             if entry['canton'] != '26'}
    with pytest.raises(RuntimeError, match='cantons are represented'):
        script.check_load(short)


def test_a_load_without_canton_zurich_is_refused():
    """Zurich is the one canton CAREER-53 cannot work without."""
    parsed = script.parse_rows(whole_register())
    thin = {code: entry for code, entry in parsed.items()
            if entry['canton'] != '1' or int(code) < 150}
    with pytest.raises(RuntimeError, match='canton Zurich came back with'):
        script.check_load(thin)


def test_a_whole_register_clears_the_guards_and_reports_its_cantons():
    counts = script.check_load(script.parse_rows(whole_register()))
    assert counts['1'] == 160
    assert len(counts) == 26


# --- writing -----------------------------------------------------------------

def test_the_generated_block_quotes_every_code_because_they_are_strings():
    """location.yaml says why: every code in this taxonomy is a string,
    and an unquoted 8001 is an integer."""
    text = script.render_codes(script.parse_rows(bindings(
        ('261', 'Zürich', '1', '8001'), ('1', 'Aeugst am Albis', '1', None))))
    assert '- code: "1"' in text and '- code: "261"' in text
    assert 'postal_codes: ["8001"]' in text
    assert 'postal_codes: []' in text
    assert text.index('code: "1"') < text.index('code: "261"'), 'numeric order, not lexical'
    parsed = yaml.safe_load(text)
    assert parsed['codes'][0] == {'code': '1', 'label': 'Aeugst am Albis', 'canton': '1',
                                  'postal_codes': []}


def test_a_write_replaces_only_the_generated_block_and_the_header_fields(tmp_path):
    original = TAXONOMY_FILE.read_text()
    written = script.splice(original, script.parse_rows(whole_register()), today='2026-11-01')
    assert '# WHY THE MUNICIPALITY NUMBER' in written, 'the prose survives'
    assert 'abbreviation: ZH' in written, 'the canton list survives'
    assert 'coordinates_note' in written, 'the record shape survives'
    assert 'taxonomy_version: "1.2.0"' in written, 'a change bumps the minor version'
    assert 'changed_at: "2026-11-01"' in written
    assert 'LINDAS on 2026-11-01' in written
    assert '  loaded_at: "2026-11-01"' in written
    reloaded = yaml.safe_load(written)
    municipality = next(item for item in reloaded['code_lists']
                        if item['dimension'] == 'municipality')
    assert len(municipality['codes']) == 1910
    assert municipality['complete'] is False, 'the register moves; see the todo'


def test_a_file_with_no_markers_refuses_to_be_written():
    with pytest.raises(RuntimeError, match='no generated-code markers'):
        script.splice('taxonomy_version: "1.0.0"\n', {}, today='2026-11-01')


def test_the_version_bump_is_the_minor_one():
    assert script.bump_minor('1.1.0') == '1.2.0'
    assert script.bump_minor('2.0.3') == '2.1.3'


# --- idempotency, which is what makes a re-run safe --------------------------

def test_what_the_file_holds_reads_back_in_the_shape_a_load_returns():
    stored = script.stored_municipalities(TAXONOMY_FILE)
    assert len(stored) > 2000
    assert stored['261'] == {'code': '261', 'label': 'Zürich', 'canton': '1',
                             'postal_codes': stored['261']['postal_codes']}
    assert '8004' in stored['261']['postal_codes']


def test_loading_what_the_file_already_holds_changes_nothing():
    """`--check` has to be able to say "already current", or a daily job
    would rewrite a taxonomy file and bump its version every morning."""
    stored = script.stored_municipalities(TAXONOMY_FILE)
    changes = script.diff(stored, stored)
    assert changes == {'added': [], 'removed': [], 'changed': []}


def test_a_diff_names_what_a_write_would_add_remove_and_change():
    stored = {'1': {'code': '1', 'label': 'A', 'canton': '1', 'postal_codes': ['8914']},
              '2': {'code': '2', 'label': 'B', 'canton': '1', 'postal_codes': []}}
    loaded = {'1': {'code': '1', 'label': 'A', 'canton': '1', 'postal_codes': ['8914']},
              '3': {'code': '3', 'label': 'C', 'canton': '1', 'postal_codes': []}}
    assert script.diff(stored, loaded) == {'added': ['3'], 'removed': ['2'], 'changed': []}
    loaded['1'] = {**loaded['1'], 'label': 'A (merged)'}
    assert script.diff(stored, loaded)['changed'] == ['1']


def test_the_file_the_loader_wrote_is_the_one_the_taxonomy_reads():
    from careeros import taxonomy
    stored = script.stored_municipalities(TAXONOMY_FILE)
    assert set(stored) == set(taxonomy.codes('municipality'))
    assert taxonomy.dimension_meta('municipality')['standard'].startswith('BFS municipality')


# --- the fetch, with its own transport ---------------------------------------

def test_the_query_is_posted_to_lindas_and_its_json_returned():
    sent = {}

    def transport(url, *, data=None, headers=None, timeout=None, max_body=None, limiter=None):
        sent.update({'url': url, 'data': data, 'headers': headers})
        return {'ok': True, 'status': 200, 'text': json.dumps(whole_register()),
                'final_url': url, 'error': None, 'headers': {}}

    document = script.fetch_rows(fetch=transport)
    assert script.check_load(script.parse_rows(document))['1'] == 160
    assert sent['url'] == script.SPARQL_ENDPOINT
    assert b'PoliticalMunicipality' in sent['data']
    assert b'version%3ADeprecated' in sent['data'], 'superseded entries are filtered out'
    assert sent['headers']['Accept'] == 'application/sparql-results+json'


def test_a_failed_query_raises_rather_than_writing_nothing_quietly():
    def transport(url, **kwargs):
        return {'ok': False, 'status': 503, 'text': '', 'error': 'HTTP 503', 'headers': {}}
    with pytest.raises(RuntimeError, match='LINDAS query failed'):
        script.fetch_rows(fetch=transport)


def test_a_non_json_answer_raises():
    def transport(url, **kwargs):
        return {'ok': True, 'status': 200, 'text': '<html>', 'final_url': url,
                'error': None, 'headers': {}}
    with pytest.raises(RuntimeError, match='not JSON'):
        script.fetch_rows(fetch=transport)


# --- the command line --------------------------------------------------------

def test_check_against_the_current_file_writes_nothing_and_answers_zero(tmp_path, capsys):
    saved = tmp_path / 'response.json'
    stored = script.stored_municipalities(TAXONOMY_FILE)
    saved.write_text(json.dumps(bindings(*[
        (entry['code'], entry['label'], entry['canton'], plz)
        for entry in stored.values()
        for plz in (entry['postal_codes'] or [None])])))
    before = TAXONOMY_FILE.read_bytes()
    code = script.main(['--check', '--from-file', str(saved)])
    assert code == 0
    assert 'nothing written' in capsys.readouterr().out
    assert TAXONOMY_FILE.read_bytes() == before


def test_a_write_goes_to_the_file_it_was_given_and_nowhere_else(tmp_path, capsys):
    target = tmp_path / 'location.yaml'
    target.write_text(TAXONOMY_FILE.read_text())
    saved = tmp_path / 'response.json'
    saved.write_text(json.dumps(whole_register()))
    before = TAXONOMY_FILE.read_bytes()
    assert script.main(['--from-file', str(saved), '--taxonomy-file', str(target)]) == 0
    assert TAXONOMY_FILE.read_bytes() == before, 'the shipped file was not touched'
    assert len(script.stored_municipalities(target)) == 1910
    assert 'OGD Open use' in capsys.readouterr().out, 'the licence condition is printed'
