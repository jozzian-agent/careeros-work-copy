"""Sector (ISIC Rev.4) and size (employee-count class) classification.

Pure, offline, deterministic logic; no network I/O lives here (that is
enrich.py's concern). Ported from careeros/sectors.py. Behavior rule 7
(sector keyword matching with ambiguity refusal) and rule 8 (one EU size
scale: the employee-count class is the only size this module derives for
writing).

Rule 8 used to derive the numeric `size_range` bucket beside the class,
atomically, so the two could not desync. There is no pair to keep in
step any more: a consumer settled on the EU class alone (CareerOS, owner
decision 2026-10-15), and deriving a second scale nobody writes only
erodes the first one. `size_range_bucket` stays as a read helper for a
stored or incoming bucket label - every function here that takes a
`size_range` reads one, and none returns one as an update.

The capability owns the size-class vocabulary as its own constant
(contract's settled "EU size labels" open question): the product does not
pass labels in. The boundaries moved once, on 2026-10-17, to the BFS
classes a consumer settled on; see SIZE_CLASS_THRESHOLDS for what was
wrong with the old ones.
"""
import re
from pathlib import Path

import yaml

_DATA_DIR = Path(__file__).resolve().parent / 'data'

# Numeric size_range buckets. Read-only: these label a count or parse a
# stored bucket back into bounds, and no derivation here writes one. Their
# edges never lined up with the class thresholds below and still do not,
# which is what size_class_hint_consistent_with_range exists for.
SIZE_BUCKETS = ((10, '1-10'), (50, '11-50'), (200, '51-200'), (1000, '201-1000'))
# Size-class thresholds, each the TOP of its class.
#
# These were inclusive at every boundary until 2026-10-17 (micro <=10,
# small <=50, medium <=250), which was off by one against the source this
# module cites: EU Recommendation 2003/361/EC Article 2 defines a micro
# enterprise as one that "employs fewer than 10 persons", so a company
# with exactly 10 people is small. Same at 50 and at 250. A consumer
# settled the boundaries as the BFS size classes state them (CareerOS
# owner decision D3, 2026-10-17), which are the same numbers read the
# right way: micro 1-9, small 10-49, medium 50-249.
#
# `xl` (1000+) is that consumer's addition, not a BFS or EU class: 250+
# puts a 300-person company and a 90 000-person bank in one bucket. It is
# the last class, so the BFS roll-up is still available as
# large-or-bigger.
#
# Still an employee-count proxy and not full SME qualification, which also
# needs turnover/balance-sheet and independence data this capability never
# has.
SIZE_CLASS_THRESHOLDS = ((9, 'micro'), (49, 'small'), (249, 'medium'), (999, 'large'))
SIZE_CLASSES = ('micro', 'small', 'medium', 'large', 'xl')

def load_isic_sections():
    data = yaml.safe_load((_DATA_DIR / 'isic_sections.yaml').read_text())
    return data['sections']


# isic_sections.yaml is read once, at import. This is allowed: the
# no-file-I/O boundary this capability holds to covers record storage
# (organisation records always cross through the injected `store`, never
# a path this package opens itself) - the ISIC taxonomy is reference data
# the capability owns outright, per Behavior rule 7.
_SECTIONS = load_isic_sections()


def _sections():
    return _SECTIONS


def known_section_codes():
    return {section['code'] for section in _sections()}


def all_matched_sections(text):
    """Raw keyword matches before the single-match filter. Callers use the
    distinction between zero matches (no signal) and two or more matches
    (ambiguous signal, which rule 7 requires flagging for review rather
    than guessing).

    A section is only resolved away in favor of another when its best
    matching keyword is a strict substring of the other section's best
    matching keyword - i.e. the two matches are a generic/specific
    restatement of the same phrase. When the competing sections matched via
    keywords that are not substrings of one another, this is genuine
    multi-activity ambiguity: every originally matched section is returned,
    unresolved."""
    if not isinstance(text, str) or not text.strip():
        return []
    lowered = text.casefold()
    matches = []
    for section in _sections():
        matched_keywords = [keyword for keyword in section.get('keywords', [])
                             if re.search(r'\b' + re.escape(keyword) + r'\b', lowered)]
        if matched_keywords:
            matches.append((section['code'], max(matched_keywords, key=len)))
    if len(matches) <= 1:
        return [code for code, _ in matches]
    survivors = [code for i, (code, keyword) in enumerate(matches)
                 if not any(i != j and len(other_keyword) > len(keyword) and keyword in other_keyword
                            for j, (_, other_keyword) in enumerate(matches))]
    if len(survivors) == 1:
        return survivors
    return [code for code, _ in matches]


def match_sectors(text):
    """Keyword-match one free-text industry signal to zero or more ISIC
    section codes.

    This answers "which single interpretation is right for one ambiguous
    signal," not "how many sectors apply": a signal that matches more than
    one section with comparable confidence is refused (empty result) rather
    than guessed, the same as a signal matching no section at all.

    classify_sector-facing callers use this through classify_sector; this
    function is the keyword matcher it is built on.
    """
    matched = all_matched_sections(text)
    return matched if len(matched) == 1 else []


def size_range_bucket(count):
    return next((label for limit, label in SIZE_BUCKETS if count <= limit), '1000+')


def size_class_for(count):
    """Contract rule 8's classes: micro 1-9, small 10-49, medium 50-249,
    large 250-999, xl 1000+. Each threshold is the top of its class, so a
    count exactly on a published boundary (10, 50, 250, 1000) is the
    LOWER edge of the next class up."""
    return next((label for limit, label in SIZE_CLASS_THRESHOLDS if count <= limit), 'xl')


def derive_size(employee_count):
    """The size fields one raw employee count settles, as a record
    fragment a caller can apply as-is. One scale, so one key:
    `size_class` (rule 8). None when the value does not read as a
    plausible positive count, which is what tells a caller "this signal
    settles nothing" apart from an empty fragment.

    This returned `size_range` beside the class until 2026-10-15. It no
    longer does: the class is the only size scale, and a derivation that
    keeps handing back the retired one invites a caller to persist it
    again. `size_range_bucket` still labels a count for anyone who wants
    the bucket for a read."""
    if isinstance(employee_count, bool) or not isinstance(employee_count, (int, float)):
        return None
    if employee_count < 1:
        return None
    return {'size_class': size_class_for(int(employee_count))}


def range_consistent_with_size_range(count, size_range):
    return size_range_bucket(count) == size_range


def range_consistent_with_size_class(count, size_class):
    return size_class_for(count) == size_class


_SIZE_RANGE_RE = re.compile(r'^(\d+)(?:-(\d+)|\+)$')


def _size_range_bounds(size_range):
    """Parse one of SIZE_BUCKETS' own label strings ('1-10', ..., '1000+')
    back into (lower, upper) integers, upper None for the open-ended
    '1000+' bucket. None for anything that does not read as a bucket
    label at all, so a caller can treat an unrecognized value as "cannot
    rule anything out" rather than guessing."""
    if not isinstance(size_range, str):
        return None
    match = _SIZE_RANGE_RE.match(size_range.strip())
    if not match:
        return None
    lower = int(match.group(1))
    upper = int(match.group(2)) if match.group(2) else None
    return lower, upper


def size_class_hint_consistent_with_range(size_hint, size_range):
    """Whether a size-class hint is plausible for a record whose count
    falls somewhere in size_range. The class thresholds do not align with
    the range buckets' own edges, so a bucket can straddle two or more
    classes - such a bucket is compatible with every class it spans. An
    unrecognized size_range string cannot rule anything out either, so it
    is treated as compatible rather than blocking the fill.

    The classes a bucket spans are EVERY class between the one its lower
    bound falls in and the one its upper bound falls in, not just those
    two: '201-1000' spans medium (201-249), large (250-999) and xl (1000),
    and checking only the bounds would have called `large` inconsistent
    with a bucket most of whose counts are large. That was invisible while
    there were four classes and no bucket could span three of them."""
    bounds = _size_range_bounds(size_range)
    if bounds is None:
        return True
    lower, upper = bounds
    first = SIZE_CLASSES.index(size_class_for(lower))
    last = SIZE_CLASSES.index(size_class_for(upper) if upper is not None else SIZE_CLASSES[-1])
    return size_hint in SIZE_CLASSES[first:last + 1]


def count_conflicts_with_stored_size(count, size_range, size_class):
    """Whether a raw employee count contradicts a size the record already
    stores - its class, or a numeric range it still carries from before
    that scale was retired (rule 11).

    This is the question on its own, because "nothing to fill" and "this
    evidence disagrees with the record" stopped being the same answer
    once `size_class` became the only field anything fills: a count that
    agrees with an already-stored class fills nothing AND conflicts with
    nothing. A count that cannot be read at all contradicts nothing
    either; it is simply no evidence."""
    if not count or not derive_size(count):
        return False
    if size_range and not range_consistent_with_size_range(count, size_range):
        return True
    return bool(size_class) and not range_consistent_with_size_class(count, size_class)


def fill_size_updates(count, size_range, size_class):
    """Fill-empty-only, consistency-checked derivation of `size_class`
    from one raw employee count. Never overwrites an already-populated
    field (rule 11).

    Both stored size fields are READ here, and only the class is ever
    returned: a count that contradicts either the stored class or a
    `size_range` a record still carries from before that scale was
    retired fills nothing, because evidence that disagrees with what the
    record already says is a conflict for the caller to flag, not a
    value to write."""
    derived = derive_size(count) if count else None
    if not derived or count_conflicts_with_stored_size(count, size_range, size_class):
        return {}
    return {} if size_class else dict(derived)


def resolve_employee_count(value):
    """Parse a point value or a range string ("50-100") to a single
    integer, resolving an ambiguous range to its upper bound. Returns None
    when the value cannot be read as a plausible positive count."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 1 else None
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)\+?\s*", value)
        if match:
            try:
                upper = float(match.group(2).replace(',', '.'))
            except ValueError:
                return None
            return int(upper) if upper >= 1 else None
        try:
            count = float(value.replace(',', '.'))
        except ValueError:
            return None
        return int(count) if count >= 1 else None
    return None
