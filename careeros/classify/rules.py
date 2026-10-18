"""The deterministic layer: every dimension a keyword table or a formula
can settle, at zero token cost.

CAREER-57 layer 1. The pipeline has three layers (rules, local LLM,
escalation) and this is the one that runs first and answers most of the
postings. Everything here is a table or a regular expression over the
posting's own words, so a run costs nothing, is reproducible, and can
always say which phrase decided it.

## The one matching idea, used by every dimension

A dimension is a list of `(code, phrase)` pairs. A phrase is matched as a
whole word inside the normalised text, and the LONGEST matching phrase
wins -- "ict project manager" beats "project manager", "chief product
officer" beats "product". That is the BFS title-assignment idea: a title
is assigned to the most specific entry whose wording it carries, not to
the first entry that happens to overlap.

Where a title says nothing, the department and then the posting text are
read in that order, each with a lower confidence than the one before,
because a word in a 20 000-character description is weaker evidence than
the same word in a six-word title (the same lesson `base.pensum` learned
the hard way with "...grew 30%...").

## Ambiguity is not a guess

Two codes tying on the title is the normal case for several families --
`head of product` deliberately anchors both ICT product manager and
chief product officer, and `product manager` anchors both the ICT and
the non-ICT reading, because the seed refuses to give one id sole
ownership of an ambiguous phrase. A tie is broken by how much of each
candidate's own vocabulary the whole posting carries, and a tie that
survives that is recorded as `unknown` with `needs_review` and the
candidates in the evidence. That is the ambiguous remainder the local-LLM
layer exists for, and it is the product rule "only confident matches fill
anything" in code.

## Nothing here invents a code

Every value is a `taxonomy.make_value_record(..., 'rule')` with the
phrase that triggered it in the evidence. A dimension nothing matched is
`unknown` with a reason, never a plausible default: a posting that does
not state a contract type is not a permanent one.
"""
from pathlib import Path
import re
import unicodedata

import yaml

from careeros import taxonomy
from careeros.feeds import base, geocode

#: The flags a rule may set come from `value_record.yaml`, so the guide
#: version a flagged record cites is that file's own standard version
#: rather than a string typed here. The labelling guide itself is not in
#: this repository (value_record.yaml says so under open_questions).
GUIDE_VERSION = taxonomy.dimension_meta('flag')['standard_version']

#: Confidence by where the evidence was found. A title is what the
#: employer chose to call the job; a description is 20 000 characters of
#: prose that mentions many things.
TITLE_CONFIDENCE = 0.85
DEPARTMENT_CONFIDENCE = 0.6
TEXT_CONFIDENCE = 0.5

#: Below this, a rule-matched value is still stored but marked for
#: review. Nothing in this module produces a confidence under it today;
#: it is the floor the pipeline grades both layers against, kept here so
#: the two layers read the same number.
CONFIDENCE_FLOOR = 0.5

_SEED = Path(__file__).resolve().parents[1] / 'data' / 'esco_occupations.yaml'


# --- the shared matcher ----------------------------------------------------

def normalise(text):
    """Casefolded, whitespace-collapsed text with typographic dashes and
    quotes folded onto the ASCII ones a table is written with.

    Accents are kept: `Projektleiter` and `Prüfer` are German words a
    keyword table spells correctly, and stripping them would make
    `uber` match `über`.
    """
    text = unicodedata.normalize('NFC', str(text or ''))
    for fancy, plain in (('‐', '-'), ('‑', '-'), ('‒', '-'), ('–', '-'),
                         ('—', '-'), ('―', '-'), ('’', "'"), ('‘', "'"),
                         ('“', '"'), ('”', '"'), (' ', ' ')):
        text = text.replace(fancy, plain)
    return ' '.join(text.casefold().split())


def _pattern(phrase):
    """A phrase as a whole-word pattern.

    `\\b` on each end, except where the phrase itself starts or ends with
    a non-word character (`r&d manager`, `fp&a`): a boundary before `&`
    would never match.
    """
    body = re.escape(normalise(phrase))
    left = r'\b' if re.match(r'\w', phrase) else ''
    right = r'\b' if re.search(r'\w$', phrase) else ''
    return re.compile(left + body + right)


class Table:
    """A `{code: [phrase, ...]}` table, compiled once, matched longest-first.

    `match(text)` returns `(code, phrase, quote)` for the longest phrase
    present, or None. `candidates(text)` returns every code whose longest
    phrase is that same length, which is what tells a settled answer from
    an ambiguous one.
    """

    def __init__(self, entries):
        self.entries = tuple((code, phrase, _pattern(phrase))
                             for code, phrases in entries for phrase in phrases)

    def hits(self, text):
        """Every `(code, phrase, quote)` the text carries."""
        body = normalise(text)
        found = []
        for code, phrase, pattern in self.entries:
            found.extend((code, phrase, quote(body, found_at))
                         for found_at in pattern.finditer(body))
        return found

    def candidates(self, text):
        """The codes with the longest match, and that match's own length.

        Returns `({code: (phrase, quote)}, length)`. More than one code in
        the mapping is an ambiguity the caller has to settle or report.
        """
        best = {}
        longest = 0
        for code, phrase, found in self.hits(text):
            if len(phrase) > longest:
                best, longest = {}, len(phrase)
            if len(phrase) == longest and code not in best:
                best[code] = (phrase, found)
        return best, longest

    def match(self, text):
        best, _ = self.candidates(text)
        if len(best) != 1:
            return None
        code, (phrase, found) = next(iter(best.items()))
        return code, phrase, found


def quote(body, found):
    """The matched phrase with a little of what surrounds it, so a stored
    value's evidence reads like the posting rather than like a regex."""
    window = body[max(0, found.start() - 30):found.end() + 30]
    return ' '.join(window.split())


def _record(dimension, code, *, rule, phrase=None, where=None, confidence,
            flags=(), review=None, extra=None, at=None):
    """One rule-sourced value record.

    `review` is the reason this value needs a human, and it travels
    inside the evidence rather than as a field of its own: D4 fixes the
    value record's field list, and `evidence` is the key it reserves for
    why a value says what it says. `classify.review_reason` reads it back.
    """
    evidence = {'rule': rule}
    if phrase:
        evidence['phrase'] = phrase
    if where:
        evidence['found_in'] = where
    if review:
        evidence['needs_review'] = review
    evidence.update(extra or {})
    return taxonomy.make_value_record(dimension, code, 'rule', confidence=confidence,
                                      evidence=evidence, classified_at=at, flags=flags,
                                      guide_version=GUIDE_VERSION if flags else None)


def unknown(dimension, *, rule, review=None, extra=None, at=None):
    """"We looked and the posting says nothing", as a D4 record. Not a
    missing value: `unknown` is a real one."""
    return _record(dimension, taxonomy.UNKNOWN, rule=rule, confidence=None,
                   review=review, extra=extra, at=at)


#: A value whose only evidence is the description is kept and flagged.
#: THE RULE THAT EARNED THIS: measured over the 204-posting pool, a
#: contract type read from the text disagreed with the ATS's own stated
#: contract on 23 of 29 comparable postings -- "Ausbildung als
#: Informatiker EFZ" in a requirements list, "competitive internship
#: compensation" in a benefits list, an employer whose name contains
#: "Trainee". None of those sentences is about the contract on offer.
#: It is the same lesson `base.pensum` learned from "...grew 30%...": a
#: word in 20 000 characters of prose is usually about something else.
#: The value is still stored, because it is often right and `unknown`
#: would be worse, and it is flagged, because when it is wrong only a
#: reader can see that.
WEAK_IN_TEXT = 'weak_evidence'


def _read(table, subject, dimension, *, rule, at=None, missing=None):
    """One dimension through one table, title then department then text.

    The shape every simple dimension below shares: the first place that
    carries a phrase settles it, the confidence says which place that
    was, and a match found only in the description carries
    `needs_review` (see WEAK_IN_TEXT).
    """
    for where, confidence in (('title', TITLE_CONFIDENCE),
                              ('department', DEPARTMENT_CONFIDENCE),
                              ('text', TEXT_CONFIDENCE)):
        best, _ = table.candidates(subject.get(where) or '')
        if len(best) == 1:
            code, (phrase, found) = next(iter(best.items()))
            return _record(dimension, code, rule=rule, phrase=phrase, where=where,
                           confidence=confidence, extra={'quote': found},
                           review=WEAK_IN_TEXT if where == 'text' else None, at=at)
        if len(best) > 1:
            return unknown(dimension, rule=rule, review='ambiguous',
                           extra={'found_in': where, 'candidates': sorted(best)}, at=at)
    return unknown(dimension, rule=missing or f'the posting states no {dimension}', at=at)


# --- occupation ------------------------------------------------------------

def _load_occupations():
    """The job families with their keywords and their ISCO unit group.

    Two files, one index: `esco_occupations.yaml` is where the keywords
    live (it is the extraction seed, and its own header says the keywords
    are there to be matched against real postings) and
    `occupation_families.yaml` is the taxonomy layer that says which
    four-digit ISCO group a family rolls up to and how much that mapping
    can be trusted. `tests/test_taxonomy.py` already pins the two
    together, so reading both here cannot drift.
    """
    seed = yaml.safe_load(_SEED.read_text())
    families = {entry['code']: entry for entry in taxonomy.entries('occupation_family')}
    index = {}
    for occupation in seed['occupations']:
        family = families.get(occupation['id'])
        if not family:
            continue
        index[occupation['id']] = {
            'keywords': tuple(occupation.get('keywords') or ()),
            'isco4': family.get('isco4'),
            'status': family.get('status'),
        }
    return index


_OCCUPATIONS = _load_occupations()
_OCCUPATION_TABLE = Table((code, entry['keywords']) for code, entry in _OCCUPATIONS.items())

OCCUPATION_RULE = ('the job-family keyword table in esco_occupations.yaml, longest phrase first')


def _vocabulary_score(family, subject):
    """How much of one family's own vocabulary the whole posting carries.

    The tie-breaker, and the only place the description is allowed to
    outvote the title. Distinct phrases, not occurrences: a description
    that says "product owner" forty times is one piece of evidence.
    """
    body = normalise(' \n '.join(str(subject.get(key) or '')
                                 for key in ('title', 'department', 'text')))
    return sum(1 for phrase in _OCCUPATIONS[family]['keywords']
               if _pattern(phrase).search(body))


def occupation(subject, *, at=None):
    """`occupation_family` and `isco_unit_group`, as two records.

    Two dimensions and therefore two records, with the family deciding
    and the unit group derived from it: D1 grades occupation at four
    digits, and `occupation_families.yaml` is what maps a family onto
    one. A family the taxonomy leaves unmapped (the five local extensions
    whose ESCO URIs 404) yields an `unknown` unit group naming the
    family, which is decision 25's "unmapped bucket" rather than a
    hand-picked code.
    """
    family = _settle_family(subject, at=at)
    return {'occupation_family': family, 'isco_unit_group': _isco(family, at=at)}


def _settle_family(subject, *, at=None):
    for where, confidence in (('title', TITLE_CONFIDENCE),
                              ('department', DEPARTMENT_CONFIDENCE),
                              ('text', TEXT_CONFIDENCE)):
        best, _ = _OCCUPATION_TABLE.candidates(subject.get(where) or '')
        if not best:
            continue
        if len(best) > 1:
            best = _break_tie(best, subject)
        if len(best) == 1:
            code, (phrase, found) = next(iter(best.items()))
            # A family read out of the description alone is the weakest
            # evidence this layer produces: a 20 000-character posting
            # mentions the recruiter who will call you and the team you
            # would work with, each with its own family vocabulary. The
            # value is kept, because it is usually right, and flagged,
            # because when it is wrong it is wrong in a way only a reader
            # can see.
            return _record('occupation_family', code, rule=OCCUPATION_RULE, phrase=phrase,
                           where=where, confidence=confidence, extra={'quote': found},
                           review=WEAK_IN_TEXT if where == 'text' else None, at=at)
        return unknown('occupation_family', rule=OCCUPATION_RULE, review='ambiguous',
                       extra={'found_in': where, 'candidates': sorted(best),
                              'why': 'more than one job family claims the same phrase and the '
                                     'posting carries no more of one vocabulary than the other'},
                       at=at)
    return unknown('occupation_family',
                   rule='no job-family keyword appears in the title, the department or the text',
                   at=at)


def _break_tie(best, subject):
    """Keep the tied families whose vocabulary the posting carries most of.

    Returns the same mapping when the tie survives, which is what makes
    it an ambiguity rather than an answer.
    """
    scores = {code: _vocabulary_score(code, subject) for code in best}
    top = max(scores.values())
    winners = [code for code, score in scores.items() if score == top]
    return {code: best[code] for code in winners}


def _isco(family, *, at=None):
    """The four-digit unit group a settled family rolls up to."""
    code = family['value']
    if code == taxonomy.UNKNOWN:
        return unknown('isco_unit_group',
                       rule='the job family is unsettled, so no unit group is derived',
                       review=review_reason(family), at=at)
    isco4 = _OCCUPATIONS[code]['isco4']
    if not isco4:
        return unknown('isco_unit_group',
                       rule='the job family is a local extension with no ESCO concept, so it '
                            'carries no ISCO code (decision 22 scopes the roll-up guarantee to '
                            'ESCO-backed entries, decision 25 keeps it in the unmapped bucket)',
                       extra={'occupation_family': code}, at=at)
    return _record('isco_unit_group', isco4,
                   rule=f"the ISCO unit group occupation_families.yaml maps {code} to",
                   confidence=family['confidence'],
                   # A derived value is never surer than what it was
                   # derived from, so a flagged family hands its flag on.
                   review=review_reason(family),
                   extra={'occupation_family': code, 'mapping_status': _OCCUPATIONS[code]['status']},
                   at=at)


def review_reason(record):
    """Why this value needs a human, or None. See `_record`."""
    evidence = record.get('evidence')
    return evidence.get('needs_review') if isinstance(evidence, dict) else None


# --- language --------------------------------------------------------------

#: Function words that are common in one of the five languages a Zurich
#: posting is written in and rare in the other four. Counted as whole
#: words; the language with the most hits wins, and a thin margin is an
#: unsettled answer rather than a coin toss.
_LANGUAGE_WORDS = {
    'de': ('der', 'die', 'das', 'und', 'für', 'mit', 'wir', 'sie', 'ist', 'eine', 'einen',
           'den', 'dem', 'von', 'bei', 'als', 'auch', 'werden', 'oder', 'nicht', 'sind',
           'unser', 'unsere', 'ihre', 'durch', 'kenntnisse', 'erfahrung', 'aufgaben'),
    'fr': ('le', 'la', 'les', 'des', 'une', 'vous', 'nous', 'pour', 'avec', 'est', 'dans',
           'votre', 'notre', 'qui', 'que', 'sur', 'par', 'aux', 'plus', 'ses', 'ainsi'),
    'it': ('il', 'lo', 'gli', 'una', 'per', 'con', 'sono', 'nostro', 'nostra', 'della',
           'delle', 'degli', 'che', 'nel', 'alla', 'anche', 'come', 'tua', 'nostri'),
    'en': ('the', 'and', 'you', 'with', 'for', 'our', 'are', 'will', 'your', 'this',
           'that', 'have', 'from', 'their', 'about', 'team', 'role', 'experience'),
}

#: How many function words a text has to carry before the count means
#: anything, and how far ahead the winner has to be. Both are about a
#: short text: a six-word English title shares `for` and `the` with
#: nothing, but a two-word one shares nothing with anything.
_LANGUAGE_MINIMUM = 4
_LANGUAGE_MARGIN = 1.5

LANGUAGE_RULE = ('the function-word profile of the posting text, counted as whole words '
                 'against the four written languages of a Zurich posting')


def language(subject, *, at=None):
    """The language the posting is WRITTEN in, as a D4 record.

    Not the language it ASKS for: a German posting requiring English is
    still written in German, and the requirement is a separate fact this
    layer does not read. `base.language_record` says the same thing about
    the feed-stated language, which is why a feed value and this one are
    comparable at all.
    """
    body = normalise(' \n '.join(str(subject.get(key) or '')
                                 for key in ('title', 'department', 'text')))
    words = re.findall(r'[a-zà-öø-ÿ]+', body)
    counted = {code: sum(1 for word in words if word in set(markers))
               for code, markers in _LANGUAGE_WORDS.items()}
    total = sum(counted.values())
    if total < _LANGUAGE_MINIMUM:
        return unknown('language',
                       rule='the posting text is too short to read a language from',
                       extra={'function_words': total}, at=at)
    ranked = sorted(counted.items(), key=lambda item: -item[1])
    (best, best_count), (_, runner_up) = ranked[0], ranked[1]
    if best_count < max(_LANGUAGE_MINIMUM, runner_up * _LANGUAGE_MARGIN):
        return unknown('language', rule=LANGUAGE_RULE, review='ambiguous',
                       extra={'counts': counted,
                              'why': 'no language is far enough ahead of the next one'}, at=at)
    confidence = round(min(0.95, 0.6 + 0.35 * (1 - runner_up / best_count)), 2)
    return _record('language', best, rule=LANGUAGE_RULE, confidence=confidence,
                   extra={'counts': counted}, at=at)


# --- workload --------------------------------------------------------------

#: Words that state a full or a part position without a percentage.
#: `vollzeit` is a figure: it means 100%. `teilzeit` is not -- it says
#: less than a full position without saying how much -- so it is read as
#: a review flag and never as a number.
_FULL_TIME = Table([('100', ('vollzeit', 'full-time', 'full time', 'fulltime',
                             'vollzeitstelle', 'plein temps', 'tempo pieno'))])
_PART_TIME = Table([('part', ('teilzeit', 'part-time', 'part time', 'temps partiel',
                              'tempo parziale', 'teilzeitstelle'))])

WORKLOAD_RULE = ("the shared Swiss Pensum reader (feeds.base.pensum): a percentage in the "
                 "title, or one in the text with a Pensum word beside it")


def workload(subject, *, at=None):
    """`workload_min` and `workload_max`, over the taxonomy's steps of ten.

    The percentage reader is `base.pensum`, which is the pipeline's one
    home for "what is a Pensum and what is a statistic in prose" -- the
    rule that learned to require a Pensum word near a percentage after a
    live Ashby run read a workload of 30 out of "...grew 30%...". This
    layer adds only what that reader has no opinion on: a posting that
    writes the Pensum in words.
    """
    pair, found = base.pensum(subject.get('title'), subject.get('text'))
    if pair:
        return _as_workload(pair, rule=WORKLOAD_RULE, phrase=found,
                            confidence=TITLE_CONFIDENCE, at=at)
    full = _FULL_TIME.match(f"{subject.get('title') or ''} \n {subject.get('text') or ''}")
    if full:
        return _as_workload((100, 100), rule='the posting states a full position in words',
                            phrase=full[1], confidence=TEXT_CONFIDENCE, at=at)
    part = _PART_TIME.match(f"{subject.get('title') or ''} \n {subject.get('text') or ''}")
    if part:
        return {name: unknown('workload', rule='the posting says part time without a percentage, '
                                               'which states no Pensum',
                              review='ambiguous', extra={'phrase': part[1]}, at=at)
                for name in ('workload_min', 'workload_max')}
    return {name: unknown('workload', rule='the posting states no Pensum', at=at)
            for name in ('workload_min', 'workload_max')}


def _as_workload(pair, *, rule, phrase, confidence, at=None):
    """A percentage pair onto the steps of ten, the way workload.yaml
    rounds: a minimum down and a maximum up, so the stored range never
    overstates what the posting asks for."""
    return {
        'workload_min': _record('workload', base.workload_step(pair[0], up=False), rule=rule,
                                phrase=phrase, confidence=confidence,
                                extra={'stated': pair[0]}, at=at),
        'workload_max': _record('workload', base.workload_step(pair[1], up=True), rule=rule,
                                phrase=phrase, confidence=confidence,
                                extra={'stated': pair[1]}, at=at),
    }


# --- contract --------------------------------------------------------------

_CONTRACT = Table([
    ('internship', ('praktikum', 'praktikant', 'praktikantin', 'internship',
                    'stage pratique', 'praktikumsstelle')),
    # `efz` and `eba` are NOT here: they are qualification codes
    # (qualification.yaml), and "Ausbildung als Informatiker EFZ" in a
    # requirements list is about the candidate's diploma, not about an
    # apprenticeship being offered.
    ('apprenticeship', ('lehrstelle', 'berufslehre', 'apprenticeship', 'apprenti',
                        'auszubildende', 'lernende', 'lernender', 'ausbildungsplatz')),
    ('trainee_programme', ('trainee', 'trainee-programm', 'trainee programme',
                           'graduate programme', 'graduate program', 'absolventenprogramm')),
    ('working_student', ('werkstudent', 'werkstudentin', 'working student',
                         'studentische hilfskraft')),
    # `einsatz von` was here and is gone: it is ordinary German for "use
    # of", and it made four postings temporary assignments over the
    # phrase "Einsatz von Microsoft-Migrationswerkzeugen".
    ('temporary_assignment', ('temporäreinsatz', 'temporär', 'temporary assignment',
                              'temporary placement')),
    ('fixed_term', ('befristet', 'befristete', 'fixed term', 'fixed-term', 'limited contract',
                    'durée déterminée', 'cdd', 'zeitlich begrenzt')),
    # `mandat` alone is gone: a Swiss posting calls a client engagement a
    # Mandat as often as it calls a contract one.
    ('freelance_mandate', ('freelance', 'freiberuflich', 'werkvertrag', 'auftragsverhältnis',
                           'contractor', 'selbständig erwerbend', 'auf mandatsbasis')),
    ('on_call', ('auf abruf', 'on call', 'on-call basis', 'stundenlohn auf abruf')),
    ('seasonal', ('saisonstelle', 'saisonal', 'seasonal', 'wintersaison', 'sommersaison')),
    ('permanent', ('unbefristet', 'unbefristete', 'festanstellung', 'permanent position',
                   'permanent contract', 'dauerstelle', 'durée indéterminée')),
])

#: The posting is published by someone whose business is placing people.
#: A flag and not a contract code (contract.yaml says why): a staffing
#: firm advertises permanent positions too.
_VIA_AGENCY = Table([('via_agency', ('im auftrag unseres kunden', 'on behalf of our client',
                                     'personaldienstleister', 'personalberatung',
                                     'unser kunde ist', 'our client is', 'im auftrag eines kunden',
                                     'stellenvermittlung', 'temporärbüro'))])

CONTRACT_RULE = 'the contract keyword table, longest phrase first'


def contract(subject, *, at=None):
    """The contract type, with `via_agency` as a flag beside it.

    Nothing defaults to `permanent`. A posting that does not say what
    kind of contract it offers has not said it, and the most common
    answer is not evidence for this one.
    """
    record = _read(_CONTRACT, subject, 'contract', rule=CONTRACT_RULE, at=at,
                   missing='the posting names no contract type')
    agency = _VIA_AGENCY.match(f"{subject.get('employer_name') or ''} \n "
                               f"{subject.get('text') or ''}")
    if not agency:
        return record
    evidence = dict(record['evidence'])
    evidence['via_agency_phrase'] = agency[1]
    return taxonomy.make_value_record('contract', record['value'], 'rule',
                                      confidence=record['confidence'], evidence=evidence,
                                      classified_at=record['classified_at'],
                                      flags=('via_agency',), guide_version=GUIDE_VERSION)


# --- work model ------------------------------------------------------------

_WORK_MODEL = Table([
    ('remote', ('fully remote', '100% remote', 'remote-first', 'remote first',
                'vollständig remote', 'ortsunabhängig', 'work from anywhere',
                'télétravail complet')),
    ('hybrid', ('hybrid', 'hybrides arbeiten', 'hybrid working', 'hybrid work',
                'teilweise homeoffice', 'tage homeoffice', 'tage home-office',
                'days in the office', 'days per week in the office', 'flexible remote',
                'homeoffice möglich', 'home-office möglich', 'home office möglich',
                'remote möglich', 'mobile arbeit', 'remote work possible')),
    ('onsite', ('vor ort', 'on-site', 'on site', 'onsite', 'présence sur site',
                'kein homeoffice', 'no remote', 'office-based', 'präsenzpflicht')),
])

WORK_MODEL_RULE = 'the work-model keyword table, longest phrase first'


def work_model(subject, *, at=None):
    """Where the work happens.

    The posting's own words stay in the evidence rather than in a
    `detail` block: D4 fixes the value record's fields and work_model.yaml
    marks every detail key optional, so the quote carries what the
    posting said and nothing claims a number it did not state.
    """
    return _read(_WORK_MODEL, subject, 'work_model', rule=WORK_MODEL_RULE, at=at,
                 missing='the posting says nothing about where the work happens')


# --- seniority -------------------------------------------------------------

#: D6's scale, read from what a title says. `manager` on its own is NOT
#: here: "Product Manager" is a job family and not a rank, and the old
#: ordinal's own crosswalk putting `manager` at s4 is about the retired
#: list's word, not about every title containing it.
_SENIORITY = Table([
    ('s0', ('praktikum', 'praktikant', 'praktikantin', 'intern', 'internship', 'werkstudent',
            'working student', 'studentische hilfskraft', 'student assistant')),
    ('s1', ('junior', 'einsteiger', 'berufseinsteiger', 'entry level', 'entry-level',
            'graduate', 'absolvent', 'trainee', 'nachwuchs')),
    ('s3', ('senior', 'erfahrene', 'erfahrener', 'experienced professional', 'sr.')),
    ('s4', ('lead ', 'tech lead', 'team lead', 'teamleiter', 'teamleiterin', 'principal',
            'staff engineer', 'staff product', 'head of', 'leiter', 'leiterin',
            'abteilungsleiter', 'bereichsleiter', 'gruppenleiter', 'expert', 'experte',
            'responsable')),
    ('s5', ('chief', 'ceo', 'cto', 'cfo', 'coo', 'cpo', 'ciso', 'managing director',
            'geschäftsführer', 'geschäftsführerin', 'geschäftsleitung', 'director',
            'vice president', 'vp ', 'c-level')),
])

SENIORITY_RULE = 'the seniority keyword table over the D6 scale, longest phrase first'


def seniority(subject, *, at=None):
    """A step of D6's s0-s5 scale, from the title first.

    No default step. D6 puts years of experience in a field of its own
    precisely because they map onto no step reliably, and a title with no
    rank word in it is a title that did not state a rank -- `s2`
    (Professional) is the most common answer, which is not the same thing
    as evidence for it.
    """
    return _read(_SENIORITY, subject, 'seniority', rule=SENIORITY_RULE, at=at,
                 missing='the title and the text state no seniority')


# --- employer type ---------------------------------------------------------

#: Read from the employer's NAME first, because this is a dimension of
#: the organisation and not of the posting (employer_type.yaml says so).
_EMPLOYER_TYPE = Table([
    ('agency', ('personalberatung', 'personaldienstleist', 'staffing', 'recruiting agency',
                'personalvermittlung', 'stellenvermittlung', 'temporärbüro',
                'recruitment agency')),
    ('international_org', ('united nations', 'vereinte nationen', 'world health organization',
                           'international committee of the red cross', 'internationales komitee',
                           'world trade organization', 'cern', 'unhcr', 'unicef',
                           'international organization for')),
    ('public', ('stadt zürich', 'kanton ', 'gemeinde ', 'stadtverwaltung', 'bundesamt',
                'amt für', 'departement', 'universität', 'university of', 'eth zürich',
                'fachhochschule', 'hochschule', 'kantonsschule', 'volksschule',
                'staatssekretariat', 'bundesverwaltung', 'öffentliche verwaltung')),
    ('public_enterprise', ('kantonalbank', 'schweizerische bundesbahnen', 'sbb cff ffs',
                           'die post', 'swisscom', 'stadtwerke', 'elektrizitätswerk',
                           'verkehrsbetriebe', 'kantonsspital', 'universitätsspital',
                           'stadtspital', 'suva')),
    ('nonprofit', ('stiftung', 'verein ', 'gemeinnützig', 'non-profit', 'nonprofit', 'ngo',
                   'genossenschaft', 'foundation', 'association', 'charity')),
    ('private', (' ag', ' gmbh', ' sa', ' sàrl', ' ltd', ' ltd.', ' inc', ' inc.', ' plc',
                 ' holding', ' group', ' llc', ' se')),
])

EMPLOYER_TYPE_RULE = 'the employer-type keyword table over the employer name, then the text'


def employer_type(subject, *, at=None):
    """What kind of organisation the employer is.

    A legal-form suffix (`AG`, `GmbH`) is the weakest of these rules and
    sits last in the table on purpose: a cantonal bank is an AG too, and
    the longest-phrase rule is what keeps `kantonalbank` winning over
    ` ag`.
    """
    name = subject.get('employer_name') or ''
    best, _ = _EMPLOYER_TYPE.candidates(name)
    if len(best) == 1:
        code, (phrase, found) = next(iter(best.items()))
        return _record('employer_type', code, rule=EMPLOYER_TYPE_RULE, phrase=phrase,
                       where='employer_name', confidence=TITLE_CONFIDENCE,
                       extra={'quote': found}, at=at)
    if len(best) > 1:
        return unknown('employer_type', rule=EMPLOYER_TYPE_RULE, review='ambiguous',
                       extra={'found_in': 'employer_name', 'candidates': sorted(best)}, at=at)
    best, _ = _EMPLOYER_TYPE.candidates(subject.get('text') or '')
    if len(best) == 1:
        code, (phrase, found) = next(iter(best.items()))
        return _record('employer_type', code, rule=EMPLOYER_TYPE_RULE, phrase=phrase,
                       where='text', confidence=TEXT_CONFIDENCE, extra={'quote': found}, at=at)
    return unknown('employer_type', rule='the posting names no employer this table recognises',
                   at=at)


# --- location --------------------------------------------------------------

LOCATION_RULE = ('the BFS municipality register through the shared geocoder '
                 '(feeds.geocode.geocode_office)')


def location(subject, *, at=None):
    """`municipality` and `canton` from a free-text place.

    The feed half of the pipeline already codes these
    (`geocode.location_value_records`, source `feed`), so this exists for
    the other half: a vault job whose location is a line somebody typed.
    Same geocoder, same register, different source word -- which is the
    whole point of the precedence order, because a feed that states its
    office beats this reading of a free-text line.
    """
    text = subject.get('location_text') or ''
    if not text.strip():
        return {dimension: unknown(dimension, rule='the posting states no place', at=at)
                for dimension in ('municipality', 'canton')}
    answer = geocode.geocode_office(text)
    records = {}
    for dimension in ('municipality', 'canton'):
        value = answer.get(dimension)
        if not value:
            records[dimension] = unknown(
                dimension, rule=LOCATION_RULE,
                review='ambiguous' if answer.get('status') == geocode.NEEDS_REVIEW else None,
                extra={'place': text, 'why': answer.get('reason')}, at=at)
            continue
        records[dimension] = _record(dimension, str(value), rule=LOCATION_RULE,
                                     phrase=answer.get('place') or text, where='location_text',
                                     confidence=answer.get('confidence'),
                                     extra={'method': answer.get('method')}, at=at)
    return records


# --- the whole layer -------------------------------------------------------

#: Every field this layer writes, in the order the report lists them. The
#: names are field names and not dimension names: `workload_min` and
#: `workload_max` are two fields over the one `workload` dimension.
FIELDS = ('occupation_family', 'isco_unit_group', 'language', 'workload_min', 'workload_max',
          'contract', 'work_model', 'seniority', 'employer_type', 'municipality', 'canton')


def classify(subject, *, at=None):
    """Every dimension this layer can settle, as `{field: value record}`.

    Always the full set of fields: a dimension nothing matched is an
    `unknown` record with a reason, because "we looked and found nothing"
    is a different fact from no record at all (D4).
    """
    values = {}
    values.update(occupation(subject, at=at))
    values['language'] = language(subject, at=at)
    values.update(workload(subject, at=at))
    values['contract'] = contract(subject, at=at)
    values['work_model'] = work_model(subject, at=at)
    values['seniority'] = seniority(subject, at=at)
    values['employer_type'] = employer_type(subject, at=at)
    values.update(location(subject, at=at))
    return values
