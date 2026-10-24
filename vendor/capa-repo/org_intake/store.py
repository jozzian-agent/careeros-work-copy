"""Store adapter protocol and an in-memory reference implementation.

Settled at 2.3 (the contract's "how the store adapter interface is shaped"
open question): the capability never reads or writes a file itself (see
the contract's "Not included" - Storage); the product supplies an object
satisfying this minimal protocol.

Protocol (duck-typed, not enforced at import time - any object with these
three methods works):

    list_organisations() -> list[dict]
        Every organisation-shaped record currently on file, in any order.
        Each record is a plain dict; the capability only ever reads the
        keys it knows about (name, identifiers, sectors, size_range,
        size_class, website, ...) and never assumes any others.

    load_organisation(organisation_id) -> dict | None
        One record by id, or None when it does not exist.

    save_organisation(updates, organisation_id=None) -> dict
        Create (organisation_id omitted/None) or update (merge updates
        onto the existing record) one organisation record, and return the
        resulting full record. Identifier/source list fields in `updates`
        replace the stored list wholesale (the caller - identity.py - is
        responsible for building the full replacement list, e.g. the
        existing list plus one new entry); save_organisation itself does
        not merge list contents element-by-element.

This file's InMemoryStore is a reference implementation used by this
package's own tests; a product wires up its own store (e.g. backed by its
existing file-based vault) satisfying the same three methods.
"""
import itertools


class InMemoryStore:
    """Reference store: organisation records live in a plain dict, keyed
    by a sequentially assigned id (ORG-1, ORG-2, ...). Not thread-safe;
    adequate for tests and single-process callers only."""

    def __init__(self):
        self._records = {}
        self._ids = itertools.count(1)

    def list_organisations(self):
        return list(self._records.values())

    def load_organisation(self, organisation_id):
        record = self._records.get(organisation_id)
        return dict(record) if record is not None else None

    def save_organisation(self, updates, organisation_id=None):
        existing = self._records.get(organisation_id) if organisation_id is not None else None
        if existing is not None:
            record = dict(existing)
        else:
            if organisation_id is None:
                organisation_id = f'ORG-{next(self._ids)}'
            record = {'id': organisation_id, 'name': '', 'name_source': 'auto',
                      'identifiers': [], 'sources': [], 'website': None,
                      'sectors': [], 'size_range': None, 'size_class': None,
                      'review_flags': [], 'enrichment': {}}
        record.update(updates)
        record['id'] = organisation_id
        self._records[organisation_id] = record
        return dict(record)
