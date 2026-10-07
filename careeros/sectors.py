"""ISIC Rev.4 section matching and EU-threshold company size derivation.

Pure, offline, deterministic logic only; no network IO lives here. External
fetching for the Section 3 enrichment pipeline lives in company_lookup.py.
"""
import re
from pathlib import Path

import yaml

_DATA_DIR = Path(__file__).resolve().parent / 'data'

# Same numeric buckets intake.py's posting extraction already used for
# size_range, kept here so the atomic derivation function and the
# posting-intake path agree on one scheme.
SIZE_BUCKETS = ((10, '1-10'), (50, '11-50'), (200, '51-200'), (1000, '201-1000'))
# EU Recommendation 2003/361/EC employee-count thresholds (an employee-count
# proxy, not full SME qualification, which also needs turnover/balance-sheet
# and independence data this vault never has).
SIZE_CLASS_THRESHOLDS = ((10, 'micro'), (50, 'small'), (250, 'medium'))

_SECTIONS = None


def load_isic_sections():
    data = yaml.safe_load((_DATA_DIR / 'isic_sections.yaml').read_text())
    return data['sections']


def _sections():
    global _SECTIONS
    if _SECTIONS is None:
        _SECTIONS = load_isic_sections()
    return _SECTIONS


def known_section_codes():
    return {section['code'] for section in _sections()}


def all_matched_sections(text):
    """Raw keyword matches before the single-match filter. Callers use the
    distinction between zero matches (no signal) and two or more matches
    (ambiguous signal, which decisions 20/21 require flagging for owner
    review rather than guessing).

    A section is only resolved away in favor of another when its best
    matching keyword is a strict substring of the other section's best
    matching keyword -- i.e. the two matches are a generic/specific
    restatement of the *same* phrase, such as the generic "technology" word
    M matches also being present inside J's longer "technology industry" or
    "information technology" keywords. That is specialization, not
    independent evidence, so the more specific section wins and the generic
    one is dropped.

    When the competing sections matched via keywords that are NOT
    substrings of one another -- e.g. "software and retail" matching J via
    "software" and G via "retail", two unrelated activities that merely
    happen to share no textual relationship -- neither keyword specializes
    the other, so this is genuine multi-activity ambiguity: every originally
    matched section is returned, unresolved, exactly as decisions 20/21
    require. The same applies when the longest keyword is itself tied
    between two or more sections (e.g. bare "technology", matched by J and M
    at equal length): there is no specialization relationship to resolve."""
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
    """
    matched = all_matched_sections(text)
    return matched if len(matched) == 1 else []


def size_range_bucket(count):
    return next((label for limit, label in SIZE_BUCKETS if count <= limit), '1000+')


def size_class_for(count):
    return next((label for limit, label in SIZE_CLASS_THRESHOLDS if count < limit), 'large')


def derive_size(employee_count):
    """Compute size_range and size_class together from one raw employee
    count, so the two fields can never desync by being derived separately."""
    if isinstance(employee_count, bool) or not isinstance(employee_count, (int, float)):
        return None
    if employee_count < 1:
        return None
    count = int(employee_count)
    return {'size_range': size_range_bucket(count), 'size_class': size_class_for(count)}


def range_consistent_with_size_range(count, size_range):
    return size_range_bucket(count) == size_range


def range_consistent_with_size_class(count, size_class):
    return size_class_for(count) == size_class


_SIZE_RANGE_RE = re.compile(r'^(\d+)(?:-(\d+)|\+)$')


def _size_range_bounds(size_range):
    """Parse one of SIZE_BUCKETS' own label strings ('1-10', ..., '1000+')
    back into (lower, upper) integers, upper None for the open-ended
    '1000+' bucket. None for anything that doesn't read as a bucket label at
    all, so a caller can treat an unrecognized value as "can't rule
    anything out" rather than guessing."""
    if not isinstance(size_range, str):
        return None
    match = _SIZE_RANGE_RE.match(size_range.strip())
    if not match:
        return None
    lower = int(match.group(1))
    upper = int(match.group(2)) if match.group(2) else None
    return lower, upper


def size_class_hint_consistent_with_range(size_hint, size_range):
    """Whether an EU size-class hint (e.g. the LLM world-knowledge signal's
    size_hint) is plausible for a company whose count falls somewhere in
    size_range. The class thresholds don't align with the range buckets'
    own edges, so a bucket can straddle two adjacent classes right at its
    boundary (count==50 within the '11-50' bucket is already 'medium', not
    'small') -- such a bucket is compatible with either adjacent class, since
    the range alone can't rule out the narrower one sitting at that boundary.
    An unrecognized size_range string can't rule anything out either, so it
    is treated as compatible rather than blocking the fill."""
    bounds = _size_range_bounds(size_range)
    if bounds is None:
        return True
    lower, upper = bounds
    implied = {size_class_for(lower)}
    implied.add(size_class_for(upper) if upper is not None else 'large')
    return size_hint in implied


def fill_size_updates(count, size_range, size_class):
    """Fill-empty-only, consistency-checked derivation of whichever of
    size_range/size_class is still missing, from one raw employee count.
    Never overwrites an already-populated field; when the count contradicts
    one that is already populated, nothing is filled, since writing the
    missing field from it would produce an inconsistent pair."""
    if not count:
        return {}
    derived = derive_size(count)
    if not derived:
        return {}
    if size_range and not range_consistent_with_size_range(count, size_range):
        return {}
    if size_class and not range_consistent_with_size_class(count, size_class):
        return {}
    updates = {}
    if not size_range:
        updates['size_range'] = derived['size_range']
    if not size_class:
        updates['size_class'] = derived['size_class']
    return updates


def resolve_employee_count(value):
    """Parse a point value or a range string ("50-100") to a single integer,
    resolving an ambiguous range to its upper bound per the owner's default.
    Returns None when the value cannot be read as a plausible positive count."""
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
