"""Protects `careeros.company_suffixes`: which legal forms come off the
end of a company name, which deliberately do not, and that the name left
behind is normalized the way the identity ladder compares names.

A pure function with a case per rule, so it is table-driven. Nothing
here touches a vault or the network.
"""
import pytest

from careeros import company_suffixes as suffixes

#: (name, what strip_legal_suffix answers). The whole contract, in one
#: table, grouped by the rule each row is about.
STRIPPED = [
    # The plain case, once per listed region.
    ('Northwind AG', 'northwind'),
    ('Northwind GmbH', 'northwind'),
    ('Northwind SA', 'northwind'),
    ('Northwind Sarl', 'northwind'),
    ('Northwind SARL', 'northwind'),
    ('Northwind Ltd', 'northwind'),
    ('Northwind Ltd.', 'northwind'),
    ('Northwind Limited', 'northwind'),
    ('Northwind LLC', 'northwind'),
    ('Northwind Inc', 'northwind'),
    ('Northwind Inc.', 'northwind'),
    ('Northwind Corp', 'northwind'),
    ('Northwind Corporation', 'northwind'),
    ('Northwind KG', 'northwind'),
    ('Northwind Holding', 'northwind'),

    # Case-insensitive, which is the point of comparing folded tokens.
    ('NORTHWIND AG', 'northwind'),
    ('northwind ag', 'northwind'),
    ('Northwind aG', 'northwind'),

    # Accent-insensitive recognition: the accented and the plain spelling
    # of the same form are one form.
    ('Northwind Sàrl', 'northwind'),
    ('Northwind SÀRL', 'northwind'),

    # The compound forms, which is why the longest match wins: a name
    # ending "AG & Co. KG" must lose all three tokens, not only the KG.
    ('Muster AG & Co. KG', 'muster'),
    ('Muster GmbH & Co. KG', 'muster'),

    # One form, never two. A name carrying both keeps the inner one,
    # because guessing which of them the person meant to drop is worse
    # than answering with the one that is certain.
    ('Northwind Holding AG', 'northwind holding'),

    # Punctuation and spacing collapse exactly as the ladder collapses
    # them, which is what makes the answer comparable with a normalized
    # name that was never stripped.
    ('ACME Industries  AG', 'acme industries'),
    ("O'Neill, Inc.", 'o neill'),
    ('Bring! Labs AG', 'bring labs'),

    # Nothing to strip: the name is the answer, normalized.
    ('Northwind', 'northwind'),
    ('Fernharbor Systems', 'fernharbor systems'),
    ('3M', '3m'),

    # A form that is the WHOLE name is never stripped, or it would match
    # every other name that normalizes to nothing.
    ('GmbH', 'gmbh'),
    ('AG', 'ag'),
    ('Ltd.', 'ltd'),
    ('AG & Co. KG', 'ag co kg'),

    # A name with no ASCII letters or digits in it normalizes to nothing,
    # which is the ladder's own answer for it and the reason
    # `vault.validate_company_name` refuses one at the door.
    ('...', ''),
    ('', ''),
]

#: Names whose last word is NOT a legal form, however much it looks like
#: one. Each of these is a word a real company name here ends with, and
#: stripping it would merge two employers that share one word.
KEPT = [
    'Acme Group',
    'Deleted Holdings',
    'Lanternpeak Labs',
    'Fernharbor Systems',
    'Boundary Co',
    'Pebbleorbit Studio',
    'Cloudkettle Works',
    # "as" is an ordinary English word, so Norwegian AS is off the list.
    'Clear As Day',
]


@pytest.mark.parametrize('name,expected', STRIPPED)
def test_one_legal_form_comes_off_and_the_rest_is_normalized(name, expected):
    assert suffixes.strip_legal_suffix(name) == expected


@pytest.mark.parametrize('name', KEPT)
def test_a_word_that_is_not_a_legal_form_stays(name):
    assert suffixes.strip_legal_suffix(name) == suffixes.normalized_name(name)


def test_the_two_spellings_of_one_name_meet_in_the_middle():
    """The whole reason the module exists: a request for "Northwind AG"
    and a company called "Northwind" have to compare equal, and so do a
    request for "Northwind" and a company called "Northwind AG"."""
    assert suffixes.strip_legal_suffix('Northwind AG') == suffixes.strip_legal_suffix('Northwind')
    assert suffixes.strip_legal_suffix('Northwind Sàrl') == suffixes.strip_legal_suffix('Northwind Sarl')


def test_two_different_employers_do_not_meet():
    """Stripping brings names together; it must not bring these two."""
    assert suffixes.strip_legal_suffix('Northwind AG') != suffixes.strip_legal_suffix('Northwind Systems AG')
    assert suffixes.strip_legal_suffix('Acme Group') != suffixes.strip_legal_suffix('Acme')


def test_normalized_name_is_the_ladders_own_collapse():
    """Mirrored rather than imported (the module says why), so this pins
    the mirror against the function it mirrors."""
    from org_intake.identity import _normalize_name
    for name in ('Acme, Inc.', 'ACME INC', 'Müller & Söhne GmbH', '  spaced  out  ', '3M', ''):
        assert suffixes.normalized_name(name) == _normalize_name(name)


def test_every_listed_suffix_is_recognised_at_the_end_of_a_name():
    """The list and the matcher cannot drift: every entry in
    LEGAL_SUFFIXES has to actually come off a name that ends with it."""
    for suffix in suffixes.LEGAL_SUFFIXES:
        assert suffixes.strip_legal_suffix(f'Northwind {suffix}') == 'northwind', suffix
