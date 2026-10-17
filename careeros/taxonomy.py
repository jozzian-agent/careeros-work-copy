"""The taxonomy code lists, loaded once and frozen, plus the one factory
that builds a classified value record.

WHAT THIS MODULE IS FOR. CareerOS classifies a job and a company against
a dozen dimensions (occupation, industry, size, seniority, languages,
qualifications, contract, work model, workload, location, permit,
employer type). Until CAREER-55 each of those lived wherever its first
reader needed it: a tuple in `vault`, a tuple in a page module, a
threshold table inside the capability, a seed file read by one function.
The code lists now live in `careeros/data/taxonomy/`, one YAML file per
dimension with a version on it, and this module is the only thing that
reads them.

It deliberately does NOT classify anything. CAREER-55 ships the data
files and the schema; no pipeline writes a value record yet.

THE FILE FORMAT every file in that directory follows:

    taxonomy_version: "1.0.0"     # semver, bumped by any change
    standard: "BFS size classes"  # the authority, in words
    standard_version: "..."       # which revision of it
    changed_at: "2026-10-17"      # the date of the last bump
    code_lists:                   # optional: a file may carry none
      - dimension: company_size
        complete: true            # or false, and then `todo` is required
        codes:
          - code: micro
            label: "Micro"

A file may carry several code lists (languages.yaml carries `language`
and `cefr`), and a dimension name is unique across every file, so a
dimension is addressed by name and never by file. Anything in a file that
is not a code list -- the seniority crosswalk, the salary rules, the
work-model detail keys -- is reachable through `document()`.

COMPLETE AND INCOMPLETE MATTER. Several standards are too large or were
not verifiable offline (the CH-ISCO-19 5-digit list, the BFS municipality
register, the NOGA divisions), so their lists ship empty or partial with
a TODO naming the source. `valid_code` answers "is this code in the list
we ship", which for an incomplete dimension is NOT the same question as
"is this code valid". `is_complete(dim)` is what tells the two apart, and
`make_value_record` uses it: an unknown code is refused for a complete
dimension and accepted with a logged warning for an incomplete one,
because rejecting a real Zurich municipality on the grounds that a stub
list has no entries would be worse than recording it.
"""
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
import logging

import yaml

_logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent / 'data' / 'taxonomy'

#: Every file has to say these four things about itself. A code list with
#: no version and no date is a code list nothing can reason about later.
_REQUIRED_HEADER = ('taxonomy_version', 'standard', 'standard_version', 'changed_at')

#: D4: `unknown` is a real value, not a missing one. A record carrying it
#: was classified and came up empty, which is a different fact from no
#: record at all. Accepted for every dimension and part of none.
UNKNOWN = 'unknown'


def _freeze(value):
    """Deep-freeze parsed YAML: mappings become read-only views and lists
    become tuples, so a caller cannot edit the taxonomy for the whole
    process by mutating what it was handed."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _version_key(version):
    """A semver string as a comparable tuple. Raises for anything that is
    not three dot-separated integers, because a version that cannot be
    compared cannot answer "which of these files is newest"."""
    parts = str(version).split('.')
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f'taxonomy_version must be X.Y.Z, got {version!r}')
    return tuple(int(part) for part in parts)


def _load_documents():
    """Parse every YAML file in the taxonomy directory, header-checked.

    Read once, at import, the same way `org_intake.classify` reads its
    ISIC table: this is reference data that ships with the application and
    does not change per owner, so re-reading it per request would buy
    nothing.
    """
    documents = {}
    for path in sorted(_DATA_DIR.glob('*.yaml')):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            raise ValueError(f'{path.name}: a taxonomy file must be a mapping')
        missing = [key for key in _REQUIRED_HEADER if not data.get(key)]
        if missing:
            raise ValueError(f'{path.name}: missing header field(s) {", ".join(missing)}')
        _version_key(data['taxonomy_version'])
        documents[path.stem] = _freeze(data)
    if not documents:
        raise ValueError(f'no taxonomy files found in {_DATA_DIR}')
    return documents


def _load_dimensions(documents):
    """Index every code list in every file by dimension name.

    One dimension name per taxonomy, so the name is the address. The
    checks here are the ones that would otherwise become a silent wrong
    answer much later: a duplicate dimension would shadow a file, a
    duplicate code inside a list would make a lookup arbitrary, and an
    incomplete list with no TODO would look like a complete one.
    """
    dimensions = {}
    for stem, document in documents.items():
        for code_list in document.get('code_lists', ()):
            name = code_list.get('dimension')
            if not name:
                raise ValueError(f'{stem}.yaml: a code list has no dimension name')
            if name in dimensions:
                raise ValueError(f'{stem}.yaml: dimension {name!r} is already defined in '
                                 f'{dimensions[name]["file"]}')
            if 'complete' not in code_list:
                raise ValueError(f'{stem}.yaml: dimension {name!r} must say whether it is complete')
            if not code_list['complete'] and not code_list.get('todo'):
                raise ValueError(f'{stem}.yaml: dimension {name!r} is incomplete and must carry a '
                                 'todo naming what is missing and where to get it')
            entries = code_list.get('codes') or ()
            by_code = {}
            for entry in entries:
                code = entry.get('code') if isinstance(entry, MappingProxyType) else None
                if not isinstance(code, str) or not code:
                    raise ValueError(f'{stem}.yaml: dimension {name!r} has an entry with no code')
                if not entry.get('label'):
                    raise ValueError(f'{stem}.yaml: code {code!r} in {name!r} has no label')
                if code in by_code:
                    raise ValueError(f'{stem}.yaml: dimension {name!r} lists code {code!r} twice')
                by_code[code] = entry
            dimensions[name] = MappingProxyType({
                'file': f'{stem}.yaml',
                'dimension': name,
                'complete': bool(code_list['complete']),
                'todo': code_list.get('todo'),
                'taxonomy_version': document['taxonomy_version'],
                'standard': document['standard'],
                'standard_version': document['standard_version'],
                'changed_at': document['changed_at'],
                'entries': entries,
                'by_code': MappingProxyType(by_code),
            })
    return MappingProxyType(dimensions)


_DOCUMENTS = _load_documents()
_DIMENSIONS = _load_dimensions(_DOCUMENTS)

#: File stems, which is what `document()` takes.
DOCUMENTS = tuple(sorted(_DOCUMENTS))
#: Every dimension this taxonomy can validate a code against.
DIMENSIONS = tuple(sorted(_DIMENSIONS))

#: The taxonomy as a whole, which is as new as its newest file. Each file
#: also carries its own version (`dimension_meta(dim)['taxonomy_version']`)
#: and that is the one a value record stores, because a record is
#: classified against one dimension and not against the set.
TAXONOMY_VERSION = max((document['taxonomy_version'] for document in _DOCUMENTS.values()),
                       key=_version_key)

# --- the value-record vocabulary (D4) --------------------------------------

#: Where a value came from, in no particular order; see SOURCE_PRECEDENCE
#: for the order that matters.
SOURCES = tuple(entry['code'] for entry in _DIMENSIONS['source']['entries'])
#: Highest precedence first: admin > user > feed > rule > llm.
SOURCE_PRECEDENCE = tuple(_DOCUMENTS['value_record']['source_precedence'])
#: The labelling-guide flags a value may carry.
FLAGS = tuple(entry['code'] for entry in _DIMENSIONS['flag']['entries'])

if set(SOURCE_PRECEDENCE) != set(SOURCES) or len(SOURCE_PRECEDENCE) != len(SOURCES):
    raise ValueError('value_record.yaml: source_precedence must order every source exactly once')


def document(name):
    """One whole taxonomy file, frozen, for the parts of it that are not
    code lists: the seniority crosswalk, the salary rules, the work-model
    detail keys, the skills note."""
    if name not in _DOCUMENTS:
        raise KeyError(f'unknown taxonomy document {name!r}; known: {", ".join(DOCUMENTS)}')
    return _DOCUMENTS[name]


def dimension_meta(dimension):
    """Everything known about one dimension except its codes: which file
    it came from, which standard and revision it follows, when it last
    changed, whether the list is complete, and the TODO if it is not."""
    meta = _dimension(dimension)
    return MappingProxyType({key: value for key, value in meta.items()
                             if key not in ('entries', 'by_code')})


def _dimension(dimension):
    if dimension not in _DIMENSIONS:
        raise KeyError(f'unknown taxonomy dimension {dimension!r}; known: {", ".join(DIMENSIONS)}')
    return _DIMENSIONS[dimension]


def entries(dimension):
    """Every code list entry, in file order, frozen. File order is
    meaningful in several lists (the size classes run small to large, the
    seniority steps s0 to s5), so nothing here sorts them."""
    return _dimension(dimension)['entries']


def codes(dimension):
    """Just the codes, in file order."""
    return tuple(entry['code'] for entry in entries(dimension))


def entry(dimension, code):
    """One entry, or None. None rather than a raise, because asking about
    a code a record happens to carry is an ordinary question."""
    return _dimension(dimension)['by_code'].get(code)


def labels(dimension):
    """code -> label, for a surface that shows a stored code."""
    return MappingProxyType({item['code']: item['label'] for item in entries(dimension)})


def is_complete(dimension):
    """Whether the shipped list is the whole standard. False for the
    stubs and curated subsets -- see the module docstring on why a caller
    has to know."""
    return _dimension(dimension)['complete']


def valid_code(dimension, code):
    """Whether `code` is in the list this taxonomy ships for `dimension`.

    `unknown` is true for every dimension (D4). For an incomplete
    dimension a False answer means "not in our list", not "not a valid
    code"; `is_complete` is what tells the difference.
    """
    return code == UNKNOWN or code in _dimension(dimension)['by_code']


def source_wins(candidate, stored):
    """Whether a `candidate` source may overwrite a value that `stored`
    put there. Strictly higher precedence only, so two values from the
    same source leave the stored one alone -- the data-side half of
    "human edits always win"."""
    if candidate not in SOURCES:
        raise ValueError(f'unknown source {candidate!r}; known: {", ".join(SOURCES)}')
    if stored is None:
        return True
    if stored not in SOURCES:
        raise ValueError(f'unknown source {stored!r}; known: {", ".join(SOURCES)}')
    return SOURCE_PRECEDENCE.index(candidate) < SOURCE_PRECEDENCE.index(stored)


def seniority_crosswalk():
    """old ordinal value -> {seniority, flags}, covering both
    `careeros.enrich.SENIORITY` and its alias spellings, so a stored
    seniority can be recomputed on the s-scale (D6). Lossy by design: see
    the note in seniority.yaml."""
    crosswalk = document('seniority')['crosswalk']
    mapping = {row['old']: MappingProxyType({'seniority': row['seniority'], 'flags': row['flags']})
               for row in crosswalk['old_values']}
    for alias, old in crosswalk['old_aliases'].items():
        mapping[alias] = mapping[old]
    return MappingProxyType(mapping)


def _check_confidence(confidence):
    if confidence is None:
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError('confidence must be a number between 0 and 1, or None')
    if not 0 <= confidence <= 1:
        raise ValueError(f'confidence must be between 0 and 1, got {confidence}')
    return float(confidence)


def _check_evidence(evidence):
    if evidence is None:
        return None
    if isinstance(evidence, str):
        if not evidence.strip():
            raise ValueError('evidence must be non-empty text, a mapping, or None')
        return evidence
    if isinstance(evidence, dict):
        return dict(evidence)
    raise ValueError('evidence must be non-empty text, a mapping, or None')


def _check_classified_at(classified_at):
    if classified_at is None:
        return datetime.now(timezone.utc).isoformat(timespec='seconds')
    if not isinstance(classified_at, str):
        raise ValueError('classified_at must be an ISO-8601 timestamp string')
    try:
        datetime.fromisoformat(classified_at.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(f'classified_at is not an ISO-8601 timestamp: {classified_at!r}') from None
    return classified_at


def _check_flags(flags, guide_version):
    unknown = [flag for flag in flags if flag not in FLAGS]
    if unknown:
        # Refused rather than dropped: a misspelled flag that vanished
        # silently would read as "the labeller did not flag it".
        raise ValueError(f'unknown flag(s) {", ".join(map(repr, unknown))}; known: {", ".join(FLAGS)}')
    if flags and not guide_version:
        raise ValueError('flags need the guide_version they were chosen under')
    if guide_version is not None and not isinstance(guide_version, str):
        raise ValueError('guide_version must be text or None')
    return sorted(set(flags))


def make_value_record(dimension, value, source, *, confidence=None, evidence=None,
                      classified_at=None, flags=(), guide_version=None):
    """One classified value in the D4 shape, validated.

    The one place a value record is built, so the shape cannot drift
    between writers:

        {value, source, confidence, evidence, taxonomy_version,
         standard_version, classified_at, flags, guide_version}

    `taxonomy_version` and `standard_version` are taken from the
    dimension's own file rather than passed in -- the point of recording
    them is that a stored value says which list it was classified
    against, and a caller that could pass a version could pass the wrong
    one. The record carries no dimension name: the field it is stored
    under names the dimension (D4's field list has no room for it either).

    Raises ValueError for a bad field, and KeyError for an unknown
    dimension. An unknown CODE is refused only for a complete dimension;
    for an incomplete one it is accepted and logged, per the module
    docstring. The code is in the log line because a taxonomy code is the
    thing the owner needs to see to extend the list -- unlike the field
    values CAREER-30's drop logs deliberately leave out.
    """
    meta = _dimension(dimension)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{dimension}: value must be a non-empty code (or {UNKNOWN!r})')
    if not valid_code(dimension, value):
        if meta['complete']:
            raise ValueError(f'{value!r} is not a valid {dimension} code')
        _logger.warning('taxonomy %s: accepted code %r that the shipped list does not have; '
                        '%s marks this dimension incomplete, so the code is kept and the list '
                        'is what needs extending', dimension, value, meta['file'])
    if source not in SOURCES:
        raise ValueError(f'unknown source {source!r}; known: {", ".join(SOURCES)}')
    return {
        'value': value,
        'source': source,
        'confidence': _check_confidence(confidence),
        'evidence': _check_evidence(evidence),
        'taxonomy_version': meta['taxonomy_version'],
        'standard_version': meta['standard_version'],
        'classified_at': _check_classified_at(classified_at),
        'flags': _check_flags(tuple(flags), guide_version),
        'guide_version': guide_version,
    }
