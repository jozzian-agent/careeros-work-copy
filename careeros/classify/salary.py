"""Salary: what the posting said, and the one figure that compares.

CAREER-57's salary deliverable, and the first reader of
`salary_rules.yaml`. The comparable figure that file defines is an
**annual gross in CHF at 100% Pensum**, and every rule below exists to
get from a posting's wording to that number without hiding what was
assumed on the way.

## Why this is not a value record

There is no `salary` dimension in the taxonomy, on purpose: a salary is
an amount and a code list cannot hold one. So a reading is its own block
with the field list `salary_rules.yaml` states --
`{min, max, currency, period_stated, months_assumed, pensum_stated}` --
plus the normalised pair, the quote it came from, and the same
`source`/`confidence`/`classified_at` triple a value record carries, so
precedence works on it exactly as it works on everything else.

## What the rules do, in the file's own words

  * `x13_default`: a monthly figure times thirteen, because a Swiss
    salary is usually paid in thirteen instalments. A posting that states
    the count ("12 Monatslöhne", "13. Monatslohn") uses that count and
    raises nothing; the default raises the `assumed_13` flag, so a
    derived number is never shown as a stated one.
  * `hourly_to_annual`: `hourly * 40 * 52`. Forty hours is a
    normalisation convention and not a claim about anybody's full-time
    week, and the thirteenth-salary question does not arise, because the
    supplement -- if any -- is already inside an hourly rate.
  * `pensum_scaling`: a figure stated for an 80% position is divided by
    0.8 to compare with a full one. When the posting states a Pensum
    RANGE and not which bound the money is for, the maximum is used and
    the stated Pensum stays on the record, so the choice is visible.
  * `no_figure`: no block at all. Not a zero, and never an estimate --
    including for a public posting that names a wage class, because the
    four pay-scale tables in `salary_rules.yaml` are still placeholders.

## A range stays a range

"CHF 110 000 - 130 000" stores both bounds and nothing picks a midpoint,
which is the opposite of the employee-count rule (draft choice 18) and
deliberately so: a headcount is one number a posting is vague about, a
salary range is two numbers the employer means.
"""
import re

from careeros import taxonomy
from careeros.feeds import base

_RULES = {rule['id']: rule for rule in taxonomy.document('salary_rules')['rules']}

#: The target this module normalises onto, quoted from the file rather
#: than restated, so a change there is visible here.
TARGET = taxonomy.document('salary_rules')['target']['figure']

#: Hours and weeks of the `hourly_to_annual` convention.
HOURS_PER_WEEK = 40
WEEKS_PER_YEAR = 52

#: The default number of monthly payments (`x13_default`).
DEFAULT_MONTHS = 13

#: An amount: `110 000`, `110'000`, `110.000`, `110,000`, `6500.50`,
#: `45.50`. Swiss postings use the apostrophe; the dot, the comma and the
#: space come from English and German postings by international
#: employers.
#:
#: The grouped form requires at LEAST one thousands group and the plain
#: form comes second, so `4000` reads as four thousand rather than as
#: `400` with a stray `0` after it -- which is what a greedy three-digit
#: alternative does when it is allowed to match on its own.
_AMOUNT = r"\d{1,3}(?:['’., ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"

#: A currency the amount is in. Only CHF is normalised: `salary_rules.yaml`
#: records "a posting quoting EUR has no rule yet" as an open question,
#: and guessing an exchange rate would put a number on somebody's salary
#: expectation.
_CURRENCY = r'chf|fr\.|sfr\.?|franken|eur|€|usd|\$'

#: One amount or a range of two, with the currency on either side.
_FIGURE = re.compile(
    rf'(?P<before>{_CURRENCY})?\s*'
    # Not in the middle of a bigger number: without this, `14000` offers
    # `4000` as a second match once the first one is rejected.
    rf"(?<![\d.,'’])"
    rf'(?P<low>{_AMOUNT})'
    rf'(?:\s*(?:-|–|—|\bbis\b|\bto\b|\bund\b)\s*(?P<high>{_AMOUNT}))?'
    rf'\s*(?P<after>{_CURRENCY})?', re.I)

#: The period the figure is for. The first one found within reach of the
#: amount wins; nothing is assumed when none is found, because an
#: unlabelled "85 000" is annual and an unlabelled "45" is not a salary.
_PERIOD = (
    ('hour', re.compile(r'pro\s+stunde|stundenlohn|je\s+stunde|per\s+hour|/\s*h\b|\bp\.?h\.?\b|'
                        r'hourly|stundensatz', re.I)),
    ('month', re.compile(r'pro\s+monat|monatslohn|monatsgehalt|im\s+monat|per\s+month|monthly|'
                         r'/\s*monat|\bmtl\.?\b', re.I)),
    ('year', re.compile(r'pro\s+jahr|jahreslohn|jahresgehalt|im\s+jahr|per\s+(?:year|annum)|'
                        r'annual|\bp\.?a\.?\b|jährlich|/\s*jahr', re.I)),
)

#: How many monthly payments the posting states, when it says.
_MONTHS = re.compile(r'(\d{2})\s*(?:x|mal|monatsl[öo]hn|monatsgeh[äa]lt)|'
                     r'(\d{2})\.\s*monatslohn|(\d{2})\s*monthly\s+(?:payments|salaries)', re.I)

#: How far from an amount a period word may be and still be about it.
#: The same idea as `base.pensum`'s Pensum window, and the same reason:
#: a number in prose means nothing without the word beside it.
_WINDOW = 80

#: Words that say the sentence is about pay at all. An amount with none
#: of these near it is a headcount, a turnover or a year.
_PAY_WORDS = re.compile(
    r'lohn|l[öo]hne|gehalt|geh[äa]lter|sal[äa]r|verg[üu]tung|entl[öo]hnung|besoldung|'
    r'salary|salaries|compensation|pay|remuneration|wage|wages|verdienst|bezahlung', re.I)

#: The lowest and highest an annual Swiss gross can plausibly be. Outside
#: this, the match was something else -- a turnover, a headcount, a
#: budget -- and the honest answer is no reading rather than a wrong one.
_ANNUAL_FLOOR = 20_000
_ANNUAL_CEILING = 2_000_000


def _number(text):
    """A Swiss-written amount as a float, or None.

    `110'000` and `110 000` are thousands; `6500.50` and `6500,50` are
    decimals. The rule that tells them apart is the length of the group
    after the separator: three digits is a thousands group.
    """
    body = str(text).replace("'", '').replace('’', '').replace(' ', '')
    if re.fullmatch(r'\d+[.,]\d{3}', body):
        body = body.replace('.', '').replace(',', '')
    body = body.replace(',', '.')
    return float(body) if re.fullmatch(r'\d+(?:\.\d{1,2})?', body) else None


def _currency(match):
    word = (match.group('before') or match.group('after') or '').strip().lower()
    if not word:
        return None
    if word in ('eur', '€'):
        return 'EUR'
    if word in ('usd', '$'):
        return 'USD'
    return 'CHF'


def _period(body, match):
    window = body[max(0, match.start() - _WINDOW):match.end() + _WINDOW]
    for name, pattern in _PERIOD:
        if pattern.search(window):
            return name, ' '.join(window.split())
    return None, ' '.join(window.split())


def _stated_months(body, match):
    window = body[max(0, match.start() - _WINDOW * 2):match.end() + _WINDOW * 2]
    found = _MONTHS.search(window)
    if not found:
        return None
    count = next((int(group) for group in found.groups() if group), None)
    return count if count and 12 <= count <= 14 else None


def read(text, *, title=None):
    """The first salary statement in the text, or None.

    Returns the raw reading: `{min, max, currency, period_stated,
    months_assumed, pensum_stated, quote}` with the amounts exactly as
    the posting wrote them. `normalise` is what turns it into the
    comparable figure.

    Nothing is read without a pay word near the amount and a period the
    posting actually states, which is the `no_figure` rule doing its job:
    the common case is that a Swiss posting says nothing about pay, and
    inventing a reading for a number that happened to be in range would
    be worse than the silence.
    """
    body = str(text or '')
    for match in _FIGURE.finditer(body):
        window = body[max(0, match.start() - _WINDOW):match.end() + _WINDOW]
        if not _PAY_WORDS.search(window):
            continue
        low = _number(match.group('low'))
        high = _number(match.group('high')) if match.group('high') else low
        if low is None or high is None or high < low:
            continue
        period, quote = _period(body, match)
        if not period:
            continue
        if not _plausible(low, high, period):
            continue
        return {
            'min': low, 'max': high, 'currency': _currency(match) or 'CHF',
            'currency_stated': _currency(match) is not None,
            'period_stated': period,
            'months_stated': _stated_months(body, match),
            'quote': quote,
        }
    return None


def _plausible(low, high, period):
    """Whether an amount can be a salary for the period it is stated in.

    The bounds are wide on purpose: the point is to throw out a turnover
    in millions read as a monthly wage, not to have an opinion on what
    anybody should earn.
    """
    annual_low = _to_annual(low, period, DEFAULT_MONTHS)
    annual_high = _to_annual(high, period, DEFAULT_MONTHS)
    return _ANNUAL_FLOOR <= annual_low <= annual_high <= _ANNUAL_CEILING


def _to_annual(figure, period, months):
    if period == 'hour':
        return figure * HOURS_PER_WEEK * WEEKS_PER_YEAR
    if period == 'month':
        return figure * months
    return figure


def normalise(reading, *, pensum=None, source='rule', confidence=0.7, at=None):
    """A reading as the comparable figure, with every assumption visible.

    `pensum` is the Pensum the figure was stated for, as the
    `(min, max)` pair `base.pensum` returns. When the posting gives a
    range and does not say which bound the money is for, the MAXIMUM is
    used (`pensum_scaling`) and the pair stays on the record, so a reader
    can always redo the arithmetic.

    Returns None for a currency this repository has no rule for, rather
    than converting at a rate nobody recorded.
    """
    if reading is None:
        return None
    if reading['currency'] != 'CHF':
        return {
            'currency': reading['currency'], 'min': reading['min'], 'max': reading['max'],
            'period_stated': reading['period_stated'], 'months_assumed': None,
            'pensum_stated': list(pensum) if pensum else None,
            'annual_gross_chf_min': None, 'annual_gross_chf_max': None,
            'quote': reading['quote'], 'rules': ['no_figure'],
            'needs_review': f"the posting quotes {reading['currency']}, which salary_rules.yaml "
                            'has no conversion rule for',
            'source': source, 'confidence': None,
            'classified_at': taxonomy._check_classified_at(at), 'flags': [],
        }
    period = reading['period_stated']
    months = reading['months_stated'] or (DEFAULT_MONTHS if period == 'month' else None)
    rules, flags = [], []
    if period == 'hour':
        rules.append('hourly_to_annual')
    elif period == 'month':
        rules.append('x13_default')
        if not reading['months_stated']:
            flags.append('assumed_13')
    low = _to_annual(reading['min'], period, months or DEFAULT_MONTHS)
    high = _to_annual(reading['max'], period, months or DEFAULT_MONTHS)
    # An HOURLY rate is already a full-time-equivalent figure: the rate
    # is per hour worked, so `hourly * 40 * 52` is the annual at 100% and
    # dividing it by a 55% Pensum again would invent half a salary. Only
    # a monthly or annual figure is stated FOR the position offered,
    # which is what `pensum_scaling` is about.
    share = (max(pensum) / 100) if pensum and period in ('month', 'year') else None
    if share and share != 1:
        rules.append('pensum_scaling')
        low, high = low / share, high / share
    return {
        'currency': 'CHF', 'min': reading['min'], 'max': reading['max'],
        'period_stated': period, 'months_assumed': months,
        'pensum_stated': list(pensum) if pensum else None,
        'annual_gross_chf_min': round(low, 2), 'annual_gross_chf_max': round(high, 2),
        'quote': reading['quote'], 'rules': rules, 'needs_review': None,
        'source': source, 'confidence': confidence,
        'classified_at': taxonomy._check_classified_at(at),
        'flags': sorted(flags),
        'guide_version': None,
        'target': TARGET,
    }


def classify(subject, *, at=None):
    """The salary block for one posting, or None when it states no pay.

    The Pensum it scales by is the same one the workload rule read, so a
    posting saying "80-100%" and "CHF 90 000" is normalised to the full
    position once and not twice.
    """
    pensum, _ = base.pensum(subject.get('title'), subject.get('text'))
    reading = read(subject.get('text'), title=subject.get('title'))
    return normalise(reading, pensum=pensum, at=at)


def rule_text(rule_id):
    """One normalisation rule in the words `salary_rules.yaml` uses, for
    a report that has to explain a derived number."""
    rule = _RULES.get(rule_id)
    return rule['label'] if rule else rule_id
