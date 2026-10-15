"""One registry for every history event type the vault can write.

A job record stores history as raw `{ts, event, detail}` entries. Which of
those an owner should actually see, and under which words, is a product
decision, so it lives here rather than being re-decided by each renderer.
`resolve` turns a stored list into the entries a detail page shows.

Every event type written anywhere in `careeros/` must be a key below;
tests/test_history_registry.py scans the source to enforce that, so a new
event type cannot ship without a decision about its label and visibility.
"""
from careeros import vault

# The two extraction events describe the same thing to an owner (the
# posting got read), so they share one label and `resolve` collapses them.
READ_LABEL = 'Details read from the posting'
READ_FAILED_LABEL = 'Reading the posting failed'

REGISTRY = {
    'created':            ('Job added', True),
    'fetched':            ('Posting fetched', True),
    'pasted':             ('Posting text pasted', True),
    'duplicate_override': ('Added despite a possible duplicate', True),
    'fetch_failed':       (READ_FAILED_LABEL, True),
    'extract_failed':     (READ_FAILED_LABEL, True),
    'extracted':          (READ_LABEL, True),
    'llm_enriched':       (READ_LABEL, True),
    # The owner asking for the stored text to be read again (package 2's
    # per-job migration to grouped requirements). Its own label, not the
    # read label: the owner wants to see that they asked, and when, beside
    # what the reading then produced.
    're_extracted':       ('Posting read again', True),
    # That reading not having produced anything. Its own label, and not
    # the read-failure one: the posting was read before and those details
    # still stand, so this says the latest attempt found nothing new
    # rather than that reading the posting failed.
    're_extract_failed':  ('Reading the posting again found nothing new', True),
    # The owner asked and no reading ever started, so there is nothing to
    # have found: its own line, because saying the attempt found nothing
    # new would credit a reading that did not happen.
    're_extract_not_started': ('Reading the posting again could not start', True),
    # The label is built from the stored detail ('new -> interested').
    'status_changed':     (None, True),
    'note_added':         ('Note added', True),
    'promoted':           ('Added to your board', True),
    'posting_changed':    ('Posting changed', True),
    'posting_gone':       ('Posting is no longer online', True),
    'salary_found':       ('Salary found', True),
    'company_correction': ('Company corrected', False),
    'enriched':           ('Posting enriched', False),
    'watch_started':      ('Watch started', False),
    # The outcomes careeros.server.REFRESH_EVENTS can write, and only
    # those: two further refresh types were registered for outcomes no
    # writer produces, and are gone. `resolve` drops an unknown type
    # instead of failing on it, so a legacy record carrying one reads
    # exactly as it did while they were listed, which is not at all.
    'description_refreshed':       ('Description refreshed', False),
    'description_refresh_failed':  ('', False),
    'description_refresh_skipped': ('', False),
    # Ingest-state transitions written by vault._save_record's backstop,
    # which uses the new state itself as the event type. The two failure
    # states above are the owner-facing ones; these three are bookkeeping.
    'stub':               ('', False),
    'complete':           ('', False),
}


def status_label(status):
    """Human label for a stored status value, from vault.STATUS_LABELS when
    that mapping exists and title case otherwise."""
    labels = getattr(vault, 'STATUS_LABELS', None) or {}
    return labels.get(status) or str(status).replace('_', ' ').title()


def status_changed_label(detail):
    """Turn a stored 'old -> new' detail into owner-facing words. A detail
    that does not carry both sides degrades to the bare fact, never to a
    sentence with a blank or a literal arrow in it."""
    parts = [part.strip() for part in str(detail or '').split('->')]
    if len(parts) == 2 and all(parts):
        return f'Status changed from {status_label(parts[0])} to {status_label(parts[1])}'
    return 'Status changed'


def label_for(event, detail=None):
    """Registry label for one event type, or None when the type is unknown
    or marked invisible."""
    entry = REGISTRY.get(event)
    if entry is None or not entry[1]:
        return None
    if event == 'status_changed':
        return status_changed_label(detail)
    return entry[0]


def resolve(history):
    """Visible history for a detail page: `[{ts, label, detail}]` in stored
    order, invisible and unknown event types dropped, and the two
    extraction events collapsed into a single latest-timestamp entry (the
    posting is read once, however many pipeline stages reported it).

    An unknown event type is dropped rather than shown raw: a legacy record
    may carry a type that was retired, and the scan test guarantees no
    currently-written type reaches this branch."""
    entries = []
    for event in history or []:
        if not isinstance(event, dict):
            continue
        detail = event.get('detail')
        label = label_for(event.get('event'), detail)
        if label is None:
            continue
        entries.append({'ts': event.get('ts'), 'label': label, 'detail': detail})
    reads = [entry for entry in entries if entry['label'] == READ_LABEL]
    if len(reads) > 1:
        latest = max(reads, key=lambda entry: str(entry['ts'] or ''))
        entries = [entry for entry in entries
                   if entry['label'] != READ_LABEL or entry is latest]
    return entries
