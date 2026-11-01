"""Legal forms a company name carries, and the one way to take one off.

Why this exists. A company request holds the name a person typed, and
the companies already on file hold the name a posting or an owner gave
them. "Northwind AG" and "Northwind" are the same employer and the
identity ladder's exact-name rung says they are not, because a legal
form is part of the stored string. The nightly resolver
(`scripts/resolve_company_requests.py`) and the admin review list both
need that one comparison, so it lives here rather than twice.

What this is NOT. It is not a second identity ladder. The ladder in
`org_intake.identity` stays the one place that decides what a company
is; this module answers one narrow question -- what is this name with
one trailing legal form removed -- and the resolver only ever acts on
the answer when EXACTLY one company matches, handing every ambiguity to
the admin instead.

The normalized form this returns mirrors `org_intake.identity.
_normalize_name`: everything but ASCII letters and digits collapses to
single spaces. Mirrored rather than imported, for the reason
`careeros/vault.py` already states beside its own copy: that function is
private to the capability and a product module imports nothing private
from one. A name written in a script with no ASCII letters or digits in
it normalizes to nothing here, exactly as it would match nothing there.
"""
import re
import unicodedata

#: The legal forms this module will take off the end of a name.
#:
#: Curated, Swiss/EU/US, and deliberately short. Every entry here is a
#: legal form and nothing else, because stripping is only ever safe for a
#: token that cannot be part of the name a person means. Two rules
#: decided the list:
#:
#: * a suffix that is also an ordinary word stays out. "Group",
#:   "Holdings", "Labs", "Systems", "Partners" and "Co" all read as part
#:   of the name in the records this product already holds ("Acme
#:   Group", "Deleted Holdings", "Lanternpeak Labs", "Fernharbor
#:   Systems", "Boundary Co"), and taking one off would merge two
#:   employers that only share a word. "Holding", singular, is the Swiss
#:   legal form and is in; "Holdings" is not. Norwegian/Danish "AS" is
#:   left out for the same reason, since "as" is an ordinary English
#:   word and "Clear As Day" must not become "Clear".
#: * both the accented and the plain spelling of a form are listed where
#:   both are written in practice (Sàrl, Sarl, SARL). Recognition is
#:   accent-insensitive anyway (see `_fold`), so the duplicates document
#:   what is accepted rather than changing what matches.
#:
#: Punctuation inside an entry is decoration: the comparison below reads
#: alphanumeric tokens only, so "Ltd." and "Ltd" are one entry's worth of
#: meaning, and "AG & Co. KG" is the three tokens ag/co/kg.
LEGAL_SUFFIXES = (
    # Switzerland, Germany, Austria
    'AG',
    'GmbH',
    'AG & Co. KG',
    'GmbH & Co. KG',
    'KG',
    'Holding',
    # France, Italy, Spain, francophone Switzerland
    'SA',
    'Sàrl',
    'Sarl',
    'SARL',
    'SpA',
    'SAS',
    # Netherlands, Belgium, Scandinavia
    'BV',
    'NV',
    'AB',
    'ApS',
    'Oy',
    # United Kingdom, Ireland
    'Ltd',
    'Ltd.',
    'Limited',
    'PLC',
    # United States
    'LLC',
    'Inc',
    'Inc.',
    'Corp',
    'Corp.',
    'Corporation',
)

#: Everything but ASCII letters and digits, which is what collapses to a
#: single space. The mirror of the ladder's own normalization; see the
#: module docstring for why it is a mirror.
_NOT_ALNUM = re.compile(r'[^a-z0-9]+')

#: One run of word characters, read off the name as the person wrote it.
#: Unicode-aware, so an accented letter stays inside its own token and
#: "Sàrl" is one token rather than two.
_WORD = re.compile(r'\w+', re.UNICODE)


def _fold(text):
    """Case- and accent-insensitive form of one token, for recognising a
    legal form.

    Decompose, drop the combining marks, then casefold: "Sàrl", "SARL"
    and "sarl" all become "sarl". This is used for RECOGNITION only. The
    name that survives the strip is normalized by `normalized_name`
    below, which does not fold accents, so this module's output stays the
    shape the identity ladder compares.
    """
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def normalized_name(name):
    """One name in the form two names are compared in.

    The ladder's own: casefold, then collapse every run that is not an
    ASCII letter or digit to one space, then strip.
    """
    return _NOT_ALNUM.sub(' ', (name or '').casefold()).strip()


def _suffix_token_sequences():
    """Every listed legal form as its folded token tuple, longest first.

    Longest first is what makes "Muster AG & Co. KG" lose all three
    tokens rather than only the trailing "KG": one strip, and the one it
    makes is the most specific form that fits.
    """
    sequences = {tuple(_WORD.findall(_fold(suffix))) for suffix in LEGAL_SUFFIXES}
    return sorted((s for s in sequences if s), key=len, reverse=True)


#: Computed once; LEGAL_SUFFIXES is a constant and the tokenisation of it
#: cannot change between calls.
_SUFFIX_SEQUENCES = _suffix_token_sequences()


def strip_legal_suffix(name):
    """`name` with at most one trailing legal form removed, normalized.

    Returns the normalized name either way, so a caller compares two
    results of this function and never a mix of stripped and unstripped
    strings.

        strip_legal_suffix('Northwind AG')        -> 'northwind'
        strip_legal_suffix('Northwind')           -> 'northwind'
        strip_legal_suffix('Muster AG & Co. KG')  -> 'muster'
        strip_legal_suffix('GmbH')                -> 'gmbh'

    At most ONE form comes off. "Northwind Holding AG" loses the AG and
    keeps the Holding, because a name carrying two forms is rare enough
    that guessing which of them the person meant to drop is worse than
    answering with the one that is certain.

    A form that is the WHOLE name is never stripped. "GmbH" on its own is
    somebody's answer to the question, not a legal form attached to a
    name, and returning the empty string for it would make it match every
    other name that normalizes to nothing. "AG & Co. KG" on its own is
    the same case, which is why the whole name is checked against every
    listed form before any trailing one is: without that, the compound
    would lose its own "KG" and answer "ag co".
    """
    tokens = _WORD.findall(name or '')
    folded = [_fold(token) for token in tokens]
    if tuple(folded) in set(_SUFFIX_SEQUENCES):
        return normalized_name(name)
    for sequence in _SUFFIX_SEQUENCES:
        length = len(sequence)
        # `length < len(tokens)`, never `<=`: equal would mean the name is
        # the legal form and nothing else, which the check above already
        # answered.
        if length < len(tokens) and tuple(folded[-length:]) == sequence:
            return normalized_name(' '.join(tokens[:-length]))
    return normalized_name(name)
