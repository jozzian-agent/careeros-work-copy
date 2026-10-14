"""B1: the single history event registry and its resolved page entries.

The scan test is the point of the registry: it reads the backend source and
fails when any event type the code can write has no entry, so a new event
cannot ship without a label and a visibility decision.
"""
import ast
from pathlib import Path

import pytest

from careeros import history, server, vault
from careeros.server import create_app

CAREEROS = Path(__file__).resolve().parents[1] / 'careeros'

# Positional argument that carries the event type, by called-function name.
EVENT_ARGUMENT = {'append_event': 1, 'record': 0}
# The same argument in keyword form, by called-function name. Scoped to
# those functions rather than matched on the keyword name alone: 'kind'
# especially means something else in most of the codebase.
EVENT_TYPE_KEYWORDS = {'append_event': ('event',), 'record': ('kind',)}
# Keyword arguments that carry an (event, detail) pair.
EVENT_KEYWORDS = ('history', 'history_event')


def literal_event_types(node):
    """Event types reachable from one expression node. A tuple contributes
    its first element, a conditional expression contributes both branches,
    and anything the source does not spell out as a literal (a variable, a
    concatenation) contributes nothing: those are covered by the explicit
    vocabulary checks below instead of by guesswork here."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Tuple) and node.elts:
        return literal_event_types(node.elts[0])
    if isinstance(node, ast.IfExp):
        return literal_event_types(node.body) | literal_event_types(node.orelse)
    return set()


def called_name(node):
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


def assigned_names(node):
    """Local names one assignment statement binds, plain or annotated."""
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def scan_source(path):
    tree = ast.parse(path.read_text())
    found = set()
    # Event types literally assigned to a local, by local name, and the
    # locals a history keyword actually passes on. An (event, detail) pair
    # built into a local before it is handed over (the duplicate-override
    # event) never appears at the call site, under any name, so the two are
    # matched up after the walk instead of guessing from the name.
    assigned, passed = {}, set(EVENT_KEYWORDS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = called_name(node)
            index = EVENT_ARGUMENT.get(name)
            if index is not None and len(node.args) > index:
                found |= literal_event_types(node.args[index])
            for keyword in node.keywords:
                if keyword.arg in EVENT_TYPE_KEYWORDS.get(name, ()):
                    found |= literal_event_types(keyword.value)
                if keyword.arg in EVENT_KEYWORDS:
                    found |= literal_event_types(keyword.value)
                    if isinstance(keyword.value, ast.Name):
                        passed.add(keyword.value.id)
        for name in assigned_names(node):
            if node.value is not None:
                assigned.setdefault(name, set()).update(literal_event_types(node.value))
    for name in passed:
        found |= assigned.get(name, set())
    return found


def written_event_types():
    found = set()
    for path in sorted(CAREEROS.rglob('*.py')):
        found |= scan_source(path)
    return found


def test_registry_covers_all_written_events():
    written = written_event_types()
    # Guard the scan itself: a scanner that silently stopped matching would
    # otherwise make this test pass by finding nothing at all. One event per
    # shape the scanner has to recognise: a positional literal, a literal in
    # a conditional, and a pair built into a local first.
    assert {'created', 'extracted', 'pasted', 'posting_gone',
            'duplicate_override'} <= written
    undefined = sorted(event for event in written if event not in history.REGISTRY)
    assert undefined == [], f'history event types with no registry entry: {undefined}'


# Every shape a history event can be written in, including the ones no
# current call site happens to use: without this the scanner could lose a
# shape and the suite would stay green while real events went unregistered.
SCANNER_SHAPES = '''
vault.append_event(job, 'created', 'Job created')
vault.append_event(job, event='note_added', detail='Notes added')
record('posting_changed', 'Posting changed')
record(kind='posting_gone', detail='Posting is no longer online')
storage.save_job(root, {}, identifier, history_event=('promoted', 'Promoted to pipeline.'))
pair = ('pasted', 'Posting text pasted manually.')
storage.save_job(root, {}, identifier, history_event=pair)
annotated: tuple = ('salary_found', 'Salary found')
mark_ingest_state(root, identifier, 'complete', history=annotated)
mark_ingest_state(root, identifier, 'stub', history=(
    ('fetched', 'Extraction worker started.') if ok else ('fetch_failed', 'Unable to fetch.')))
untouched = ('never_passed_anywhere', 'not an event')
label = 'not an event either'
'''


def test_scanner_sees_every_shape_an_event_can_be_written_in(tmp_path):
    source = tmp_path / 'shapes.py'
    source.write_text(SCANNER_SHAPES)
    assert scan_source(source) == {
        'created', 'note_added', 'posting_changed', 'posting_gone', 'promoted',
        'pasted', 'salary_found', 'fetched', 'fetch_failed',
    }


def test_registry_covers_every_ingest_state():
    """vault._save_record's backstop writes the new ingest_state as the
    event type, which no source scan can see as a literal."""
    undefined = [state for state in vault.INGEST_STATES if state not in history.REGISTRY]
    assert undefined == []


def test_registry_covers_every_description_refresh_outcome():
    """The extract route's refresh picks its history event by outcome, so
    the source scan sees a table lookup rather than a literal. Every event
    in that table has to be a registry key, and the table has to cover
    every outcome the route can reach."""
    events = server.REFRESH_EVENTS
    assert set(events) == {'ok', 'failed', 'skipped'}
    undefined = [event for event, _ in events.values() if event not in history.REGISTRY]
    assert undefined == []
    # Nothing is registered for an outcome the route cannot produce.
    registered = {event for event in history.REGISTRY if event.startswith('description_refresh')}
    assert registered == {event for event, _ in events.values()}


def test_registry_entries_are_well_formed():
    for event, entry in history.REGISTRY.items():
        label, visible = entry
        assert isinstance(visible, bool), event
        if visible and event != 'status_changed':
            assert label, event


def test_resolve_dedupes_extracted_and_llm_enriched():
    resolved = history.resolve([
        {'ts': '2026-10-01T10:00:00+00:00', 'event': 'extracted', 'detail': 'Extraction completed.'},
        {'ts': '2026-10-01T09:00:00+00:00', 'event': 'llm_enriched', 'detail': 'LLM extraction completed.'},
    ])
    assert [entry['label'] for entry in resolved] == [history.READ_LABEL]
    assert resolved[0]['ts'] == '2026-10-01T10:00:00+00:00'


def test_resolve_keeps_a_single_read_event_untouched():
    resolved = history.resolve([
        {'ts': '2026-10-01T09:00:00+00:00', 'event': 'llm_enriched', 'detail': 'LLM extraction completed.'},
    ])
    assert [entry['label'] for entry in resolved] == [history.READ_LABEL]


def test_resolve_drops_invisible_and_unknown():
    resolved = history.resolve([
        {'ts': '1', 'event': 'enriched', 'detail': 'Posting enriched'},
        {'ts': '2', 'event': 'watch_started', 'detail': 'Posting baseline recorded'},
        {'ts': '3', 'event': 'company_correction', 'detail': 'corrected'},
        {'ts': '4', 'event': 'retired_event_type', 'detail': 'legacy'},
        {'ts': '5', 'event': 'note_added', 'detail': 'Notes added'},
    ])
    assert resolved == [{'ts': '5', 'label': 'Note added', 'detail': 'Notes added'}]


def test_resolve_tolerates_malformed_history():
    assert history.resolve(None) == []
    assert history.resolve(['not an event', {'event': None}]) == []


@pytest.mark.parametrize('detail,expected', [
    ('new -> interested', 'Status changed from New to Interested'),
    ('applied -> rejected', 'Status changed from Applied to Rejected'),
    ('', 'Status changed'),
    ('nonsense', 'Status changed'),
    (' -> interested', 'Status changed'),
])
def test_status_changed_label(detail, expected):
    assert history.status_changed_label(detail) == expected
    resolved = history.resolve([{'ts': '1', 'event': 'status_changed', 'detail': detail}])
    assert resolved[0]['label'] == expected


def test_job_page_history_is_resolved(tmp_path):
    job = vault.save_job(tmp_path, {'title': 'Engineer', 'url': 'https://posting.example/role'})
    vault.save_job(tmp_path, {'status': 'interested'}, job['id'])
    api = create_app(tmp_path).test_client()
    page = api.get(f'/api/jobs/{job["id"]}?view=page').get_json()
    labels = [entry['label'] for entry in page['history']]
    assert labels == ['Job added', 'Status changed from New to Interested']
    # The raw record stays available for anything that needs event types.
    assert [entry['event'] for entry in page['job']['history']] == ['created', 'status_changed']


def test_paste_writes_pasted_event(tmp_path):
    job = vault.save_job(tmp_path, {
        'title': 'Engineer', 'url': 'https://posting.example/role',
        'ingest_state': 'fetch_failed',
        'ingest_error': {'stage': 'fetch', 'reason': 'TimeoutError', 'at': vault.timestamp()},
    })
    api = create_app(tmp_path).test_client()
    response = api.post(f'/api/jobs/{job["id"]}/paste-description',
                        json={'description': 'Senior Engineer role. Build things with Python.'})
    assert response.status_code in (202, 503)
    stored = vault.load_job(tmp_path, job['id'])
    pasted = [entry for entry in stored['history'] if entry['event'] == 'pasted']
    assert [entry['detail'] for entry in pasted] == ['Posting text pasted manually.']
    assert history.label_for('pasted') == 'Posting text pasted'
