"""Office text -> BFS municipality number, over the taxonomy's own register.

WHAT THIS IS FOR. The spec's Zurich filter is "a posting is in scope when
at least one of its offices geocodes to a municipality in the canton of
Zurich", and its acceptance criterion is that 95% of Zurich offices
resolve to a BFS Gemeindenummer. A Personio office line is free text the
tenant typed; the shapes seen live on 2026-10-17 include "CH - Zürich",
"DE - Berlin", "Zürich", "8004 Zürich" and "Zürich-Oerlikon".

WHAT IT RESTS ON. `careeros.taxonomy`'s `municipality` dimension, loaded
from the BFS register through LINDAS by
`scripts/load_bfs_municipalities.py`: 2 110 municipalities with their
canton and their postal codes. Two properties of that data decide the
whole design, and both were measured rather than assumed:

  * **A name is not a key.** 35 municipality names collide once the
    register's own canton suffix is dropped -- Rickenbach is five
    municipalities, Buchs and Wald and Aesch and Oberdorf are three
    each. So a bare "Buchs" in a posting is AMBIGUOUS, not wrong, and
    this module refuses it instead of picking the Zurich one (PROJECT.md:
    only confident matches fill anything).
  * **A postal code is not a key either.** 169 of 3 177 Swiss postal
    codes span more than one municipality, and 19 of the 257 that touch
    canton Zurich also touch another canton. So a postal code alone
    settles the canton only when every municipality carrying it sits in
    one.

THE ONE AMBIGUITY WORTH SPELLING OUT. A two-letter prefix before a dash
is a country code in Personio's own office naming ("CH - Zürich"), but
Swiss canton abbreviations are two letters too and some of them collide
with country codes -- "BE - Bern" reads as Belgium or as canton Bern.
The rule here is CONSISTENCY: if the prefix is a canton abbreviation AND
the place resolves to a municipality in that canton, the prefix is read
as a canton and the two agree. Only a prefix that contradicts a Swiss
reading makes the office foreign. That resolves "ZH - Zürich" and
"BE - Bern" correctly without a country table this repository would have
to invent.

CONFIDENCE, stated once so no caller has to guess what a number means:

  * 0.95 -- postal code and place name agree on one municipality
  * 0.90 -- postal code alone resolves to one municipality
  * 0.85 -- the place name matches one register name exactly
  * 0.80 -- the place name matches one register name after folding
            (accents dropped, canton suffix dropped, district suffix
            dropped)
  * 0.70 -- several municipalities match but all sit in one canton, so
            the canton is settled and the municipality is `unknown`
  * None -- nothing matched. The office goes on the review list.

A canton or `CH` prefix that agrees with the match adds 0.05, capped at
0.95.

CORROBORATION, AND THE ONE FALSE POSITIVE THIS MODULE CANNOT RULE OUT.
A match that rests on a bare municipality NAME and nothing else cannot
distinguish a Swiss place from a foreign place that shares its name, and
several do: Lindau is a village in canton Zurich and a town on the German
side of the Bodensee; Baden, Freiburg and Wald are the same story. The
trial run found exactly this -- a German building-services company with
eight Baden-Wurttemberg offices, one of them "Gebäudetechnik, Lindau",
landed two postings in canton Zurich.

A sibling-office heuristic was measured against the trial pool and
REJECTED: sending a posting to review when its other offices look
foreign would have removed that one false positive and introduced two
false negatives, because "Zürich / US (Remote)" and "Zurich (ZRH) /
Geneva (GVA)" have the same shape and are both genuinely in Zurich.

So the answer carries `corroborated` instead of guessing: True when the
resolution used a postal code, a `CH` prefix or an agreeing canton
prefix, and False when it rests on a name alone. The posting keeps its
municipality either way, the pool row says which kind of evidence it
has, and whether a name-only Zurich match may be sampled into the golden
set is an owner decision rather than this module's
(`data/personio/TRIAL_REPORT.md`).

Everything is a `taxonomy.make_value_record(..., source='feed')`, per
CAREER-55 D4: `unknown` is a real value, so an office that could not be
resolved is recorded as classified-and-empty rather than as silence.
"""
import re
import unicodedata

from careeros import taxonomy

#: Canton Zurich's BFS canton number. The Zurich filter is the canton,
#: per the spec ("a municipality in the canton of Zurich"), not a radius
#: around the city: Winterthur and Uster are in scope and Zug is not.
ZURICH_CANTON = '1'

#: A posting's place in the pipeline. `out_of_area` is kept in the
#: snapshots and excluded from the golden-set pool; `needs_review` is the
#: spec's review list for an office that could not be geocoded at all.
IN_AREA = 'zurich'
OUT_OF_AREA = 'out_of_area'
NEEDS_REVIEW = 'needs_geocode_review'

#: Swiss postal codes are four digits, 1000-9999. Five-digit German ones
#: do not match because of the word boundaries, and a four-digit Austrian
#: one is caught by the country prefix or by the name disagreeing.
_POSTAL = re.compile(r'(?<!\d)([1-9]\d{3})(?!\d)')

#: "CH - Zürich", "DE – Berlin", "ZH-Winterthur". The separator may be a
#: hyphen, an en or em dash.
_PREFIX = re.compile(r'^([A-Za-z]{2})\s*[-–—]\s*(.+)$')

#: The register's own disambiguating suffixes: "Buchs (ZH)", "Wil (SG)",
#: "Wilen (TG)". Dropped only in the folded pass, never in the exact one.
_CANTON_SUFFIX = re.compile(r'\s*\(([A-Za-z]{2})\)\s*$')

#: Noise a tenant adds around a place: "Zürich (HQ)", "Zürich, Schweiz",
#: "Zürich / Remote", "Büro Zürich". Split on these and try each part.
#: Parentheses are separators too, which is why the whole line is always
#: tried BEFORE its parts: the register's own names use parentheses
#: ("Buchs (ZH)", "Wiler (Lötschen)") and splitting first would throw the
#: disambiguation away.
_SPLIT = re.compile(r'\s*(?:,|/|\||;|\(|\)|\bund\b|\band\b|\bor\b|\boder\b)\s*', re.I)

#: Words that are not a place and must never be matched as one. A posting
#: office of "Remote" has no municipality, and saying so is the honest
#: answer rather than a review-list entry nobody can resolve.
_NON_PLACES = frozenset({
    'remote', 'remote work', 'home office', 'homeoffice', 'work from home',
    'hybrid', 'flexible', 'various', 'verschiedene', 'schweiz', 'switzerland',
    'suisse', 'svizzera', 'deutschland', 'germany', 'austria', 'oesterreich',
    'europe', 'europa', 'worldwide', 'weltweit', 'mobile', 'unterwegs',
    'headquarters', 'hq', 'hauptsitz', 'zentrale',
})


#: A short all-upper token is a site code, not a place. Found the hard
#: way on the trial run: a German manufacturer's offices read "Eggstätt
#: (EGG)" and "Regenstauf (ZNR)", and splitting on the parenthesis made
#: "EGG" match the Zurich municipality Egg -- eleven German postings
#: filed in canton Zurich. Only separated PARTS are checked against this,
#: never the whole office line, so an office a tenant simply typed in
#: capitals ("ZÜRICH") still resolves.
_CODE = re.compile(r'^[A-Z0-9]{1,4}$')


def _is_code(part):
    return bool(_CODE.match((part or '').strip()))


def _fold(value):
    """A place name reduced to what two spellings of it have in common:
    accents dropped, case dropped, punctuation and runs of space
    collapsed. "Zürich" and "Zurich" fold together, which is the whole
    point -- the owner's own stored postings write it both ways."""
    text = unicodedata.normalize('NFKD', value or '')
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = text.replace('ß', 'ss').casefold()
    text = re.sub(r"[^a-z0-9]+", ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _build_index():
    """The lookups this module answers from, built once off the taxonomy.

    Three maps, all one-to-many on purpose (see the module docstring on
    why neither a name nor a postal code is a key):

      * `exact`  -- folded register name -> codes, names as the register
                    writes them, canton suffix included
      * `folded` -- folded name with the canton suffix dropped -> codes
      * `postal` -- postal code -> codes
    """
    exact, folded, postal, canton_of = {}, {}, {}, {}
    for item in taxonomy.entries('municipality'):
        code = item['code']
        canton_of[code] = item['canton']
        exact.setdefault(_fold(item['label']), []).append(code)
        folded.setdefault(_fold(_CANTON_SUFFIX.sub('', item['label'])), []).append(code)
        for plz in item.get('postal_codes') or ():
            postal.setdefault(str(plz), []).append(code)
    cantons = {entry['abbreviation'].casefold(): entry['code']
               for entry in taxonomy.entries('canton') if entry.get('abbreviation')}
    return {'exact': exact, 'folded': folded, 'postal': postal,
            'canton_of': canton_of, 'canton_abbreviations': cantons}


_INDEX = _build_index()


def municipality_label(code):
    """The register's own name for a code, or None."""
    item = taxonomy.entry('municipality', code)
    return item['label'] if item else None


def _canton_set(codes):
    return {_INDEX['canton_of'][code] for code in codes}


def _name_candidates(place):
    """Codes a place name could mean, and how the match was made.

    Exact register name first, then the folded form with the canton
    suffix dropped, then the part before a district hyphen
    ("Zürich-Oerlikon" -> "Zürich"). The hyphen pass is last because
    several municipalities are genuinely hyphenated
    ("Wildhaus-Alt St. Johann"), so it must never pre-empt a real match.
    """
    folded = _fold(place)
    if not folded or folded in _NON_PLACES:
        return [], 'not a place'
    if folded in _INDEX['exact']:
        return list(_INDEX['exact'][folded]), 'name'
    if folded in _INDEX['folded']:
        return list(_INDEX['folded'][folded]), 'name_folded'
    head = folded.split(' ')[0] if '-' not in place else _fold(place.split('-')[0])
    if '-' in place and head and head not in _NON_PLACES:
        for key in ('exact', 'folded'):
            if head in _INDEX[key]:
                return list(_INDEX[key][head]), 'name_district'
    return [], 'no match'


def geocode_office(text):
    """One office line -> what can be said about where it is.

    Returns a dict, always the same keys:

        {'raw', 'country_prefix', 'postal_code', 'place',
         'municipality', 'canton', 'method', 'confidence',
         'candidates', 'reason', 'status'}

    `municipality` and `canton` are codes or None. `status` is one of
    IN_AREA / OUT_OF_AREA / NEEDS_REVIEW. Nothing raises: an office line
    is whatever the tenant typed, and an unreadable one is an answer with
    a reason (PROJECT.md: failures are visible states, never silent).
    """
    raw = (text or '').strip()
    answer = {'raw': raw, 'country_prefix': None, 'postal_code': None, 'place': None,
              'municipality': None, 'canton': None, 'method': 'none',
              'confidence': None, 'candidates': [], 'reason': 'empty office',
              'status': NEEDS_REVIEW, 'swiss_evidence': False, 'corroborated': False}
    if not raw:
        return answer

    body = raw
    prefix = _PREFIX.match(raw)
    if prefix:
        answer['country_prefix'] = prefix.group(1).upper()
        body = prefix.group(2).strip()

    postal = _POSTAL.search(body)
    if postal:
        answer['postal_code'] = postal.group(1)
        body = (body[:postal.start()] + ' ' + body[postal.end():]).strip()

    # The whole line first, then whichever separated part resolves. A
    # tenant writes "Zürich, Schweiz" and also "Remote / Zürich", so the
    # parts are tried in order and the first that matches wins -- but the
    # whole line goes first so a register name that contains a separator
    # ("Buchs (ZH)", "Illnau-Effretikon") is matched as itself.
    parts = [body] + [part for part in _SPLIT.split(body) if part.strip()
                      and not _is_code(part)]
    by_name, name_method, place = [], 'no match', None
    for part in parts:
        candidates, method = _name_candidates(part)
        if candidates:
            by_name, name_method, place = candidates, method, part.strip()
            break
        if place is None and _fold(part) and _fold(part) not in _NON_PLACES:
            place = part.strip()
    answer['place'] = place or (body.strip() or None)

    by_postal = _INDEX['postal'].get(answer['postal_code'] or '', [])
    # Does this office say anything Swiss at all? A German tenant writing
    # "Berlin" resolves to nothing and needs no human; an office that
    # names CH, carries a Swiss postal code or matches a Swiss
    # municipality name ambiguously is the one the spec's review list is
    # for. Both are excluded from the pool; only one is worth a person's
    # time, and a review list of every foreign city would be read by
    # nobody.
    answer['swiss_evidence'] = bool(
        by_postal or by_name
        or (answer['country_prefix'] or '').upper() == 'CH'
        or (answer['country_prefix'] or '').casefold() in _INDEX['canton_abbreviations'])
    return _settle(answer, by_postal, by_name, name_method)


def _place_fits(place, codes):
    """Whether an unresolved place name is at least consistent with one
    of the municipalities a postal code points at.

    This is what stops "1010 Wien" from being geocoded to Lausanne: 1010
    is a real Swiss postal code, "Wien" matches no Swiss municipality,
    and a postal code on its own would otherwise answer confidently about
    a city in another country. "8600 Dübendorf ZH" still resolves,
    because the register name is contained in what the tenant typed.
    """
    folded = _fold(place)
    if not folded:
        return True
    for code in codes:
        label = _fold(_CANTON_SUFFIX.sub('', municipality_label(code) or ''))
        if label and (label in folded or folded in label):
            return True
    return False


def _settle(answer, by_postal, by_name, name_method):
    """Turn the postal-code and name candidate sets into one answer.

    The order is deliberate: agreement beats either signal alone, a
    postal code beats a name (it is a code, not a spelling), and a
    contradiction between the two is recorded as a contradiction rather
    than resolved in favour of whichever came first.
    """
    both = [code for code in by_postal if code in by_name]
    if both:
        candidates, method, confidence = both, f'postal_code+{name_method}', 0.95
    elif by_postal and by_name:
        # Both signals resolved and they point at different places --
        # "8004 Winterthur", a Zurich-city postal code beside a
        # different Zurich municipality. A postal code that resolves
        # beside a place name that resolves to NOTHING is the other
        # case, and `_place_fits` handles it a few lines down.
        answer.update({'method': 'postal_code_vs_name_conflict', 'confidence': None,
                       'candidates': sorted(set(by_postal) | set(by_name), key=int),
                       'reason': 'the postal code and the place name resolve to different '
                                 'municipalities, so neither is confident',
                       'status': NEEDS_REVIEW})
        return _foreign_if_prefix_says_so(answer)
    elif by_postal and not _place_fits(answer['place'], by_postal):
        answer.update({'method': 'postal_code_vs_name_conflict', 'confidence': None,
                       'candidates': sorted(set(by_postal), key=int),
                       'reason': 'the four-digit code is a Swiss postal code but the place '
                                 'beside it is not the municipality it belongs to',
                       'status': NEEDS_REVIEW})
        return _foreign_if_prefix_says_so(answer)
    elif by_postal:
        # A postal code shared by several municipalities, with a place
        # name beside it that matched no register name on its own:
        # "8600 Dübendorf ZH" is the live shape. Keeping only the
        # candidates the place name fits settles it without guessing,
        # because the fit is the register's own name appearing in what
        # the tenant typed.
        narrowed = [code for code in by_postal if _place_fits(answer['place'], [code])]
        if len(by_postal) > 1 and len(narrowed) == 1:
            candidates, method, confidence = narrowed, 'postal_code+name_contained', 0.90
        else:
            candidates, method, confidence = by_postal, 'postal_code', 0.90
    elif by_name:
        candidates, method, confidence = by_name, name_method, (
            0.85 if name_method == 'name' else 0.80)
    else:
        answer.update({'method': 'none', 'reason': 'no Swiss municipality matches this office',
                       'status': NEEDS_REVIEW})
        return _foreign_if_prefix_says_so(answer)

    answer['candidates'] = sorted(set(candidates), key=int)
    cantons = _canton_set(answer['candidates'])
    prefix = answer['country_prefix']
    prefix_canton = _INDEX['canton_abbreviations'].get((prefix or '').casefold())

    # The prefix/canton reading, per the module docstring: a prefix that
    # is a canton abbreviation and agrees with the match is a canton, and
    # the agreement narrows the candidates. A prefix that is neither 'CH'
    # nor an agreeing canton is a foreign country code and overrides a
    # Swiss name that happens to collide.
    if prefix_canton and prefix_canton in cantons:
        answer['candidates'] = [code for code in answer['candidates']
                                if _INDEX['canton_of'][code] == prefix_canton]
        cantons = {prefix_canton}
        method = f'{method}+canton_prefix'
        confidence = round(min(0.95, (confidence or 0) + 0.05), 2)
    elif prefix == 'CH':
        # The office says Switzerland outright, which is exactly the
        # corroboration a bare name lacks. It narrows nothing -- every
        # candidate is already Swiss -- so it only raises the confidence.
        method = f'{method}+country_prefix'
        confidence = round(min(0.95, (confidence or 0) + 0.05), 2)
    elif prefix:
        answer.update({'method': 'country_prefix', 'confidence': 0.9,
                       'candidates': [], 'place': answer['place'],
                       'reason': f'the office names country {prefix}, not CH',
                       'status': OUT_OF_AREA})
        return answer

    answer['method'] = method
    # See the module docstring: a name alone cannot tell a Swiss place
    # from a foreign one that shares its name, and this is what says so.
    answer['corroborated'] = bool(answer['postal_code']) or 'prefix' in method
    if len(answer['candidates']) == 1:
        answer['municipality'] = answer['candidates'][0]
        answer['canton'] = _INDEX['canton_of'][answer['municipality']]
        answer['confidence'] = confidence
        answer['reason'] = f'one municipality matches: {municipality_label(answer["municipality"])}'
    elif len(cantons) == 1:
        answer['canton'] = next(iter(cantons))
        answer['confidence'] = 0.70
        answer['reason'] = (f'{len(answer["candidates"])} municipalities match and all are in '
                            'one canton, so the canton is settled and the municipality is not')
    else:
        answer['confidence'] = None
        answer['reason'] = (f'{len(answer["candidates"])} municipalities in '
                            f'{len(cantons)} cantons match, so nothing is confident')
    answer['status'] = (IN_AREA if answer['canton'] == ZURICH_CANTON
                        else OUT_OF_AREA if answer['canton']
                        else NEEDS_REVIEW)
    return answer


def _foreign_if_prefix_says_so(answer):
    """An unresolved office whose own prefix names a foreign country is
    out of area, not a review-list entry: "DE - Berlin" needs no human."""
    prefix = answer['country_prefix']
    if prefix and prefix != 'CH' and prefix.casefold() not in _INDEX['canton_abbreviations']:
        answer.update({'status': OUT_OF_AREA, 'method': 'country_prefix', 'confidence': 0.9,
                       'reason': f'the office names country {prefix}, not CH'})
    return answer


def geocode_offices(offices):
    """Every office of one posting, plus the posting-level answer.

    Returns `(results, summary)`. The summary is the spec's filter: the
    posting is in scope when ANY office lands in canton Zurich, and the
    Zurich office is the one whose municipality the posting records.
    An out-of-area posting keeps its own best answer, so the pool can
    report what it excluded and why.
    """
    results = [geocode_office(office) for office in offices if (office or '').strip()]
    if not results:
        return results, {'status': NEEDS_REVIEW, 'municipality': None, 'canton': None,
                         'method': 'none', 'confidence': None, 'office': None,
                         'swiss_evidence': False, 'corroborated': False,
                         'reason': 'the posting names no office'}
    in_area = [item for item in results if item['status'] == IN_AREA]
    # A Zurich office with a municipality beats a Zurich office without
    # one, and a corroborated one beats a name-only one, so a posting
    # that has both kinds of Zurich office is recorded by the better
    # evidence. Otherwise the best-resolved office of any status speaks
    # for the posting, so an out-of-area posting still says where it is.
    pool = in_area or results
    best = max(pool, key=lambda item: ((item['municipality'] is not None),
                                       item['corroborated'],
                                       item['confidence'] or 0.0))
    summary = {'status': IN_AREA if in_area else best['status'],
               'municipality': best['municipality'], 'canton': best['canton'],
               'method': best['method'], 'confidence': best['confidence'],
               'reason': best['reason'], 'office': best['raw'],
               'corroborated': best['corroborated'],
               'swiss_evidence': any(item['swiss_evidence'] for item in results)}
    return results, summary


def location_value_records(summary, *, guide_version=None):
    """The summary as the two D4 value records a posting stores.

    `municipality` and `canton` are separate taxonomy dimensions, so they
    are separate records, and both are written even when empty: `unknown`
    is a real value and "we looked and found nothing" is a different fact
    from no record at all.
    """
    evidence = {'office': summary.get('office'), 'method': summary['method'],
                'corroborated': summary.get('corroborated', False),
                'reason': summary['reason']}
    records = {}
    for dimension in ('municipality', 'canton'):
        value = summary.get(dimension) or taxonomy.UNKNOWN
        records[dimension] = taxonomy.make_value_record(
            dimension, value, 'feed',
            confidence=summary['confidence'] if summary.get(dimension) else None,
            evidence=evidence, guide_version=guide_version)
    return records
