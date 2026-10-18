"""The golden-set pool export, multi-provider, and its stratification keys.

The spec: "one command exports all in-scope open postings as a file with:
snapshot id, tenant, company, title, language, municipality, contract
type, schedule, has-salary flag, and a pre-assigned job family from a
quick LLM guess. The pre-guess is only for drawing the stratified sample;
labellers don't see it."

EVERY ROW IS READ OUT OF A SNAPSHOT, never out of a live fetch. That is
the point of the snapshot store: "the golden set always references a
snapshot id, never the live posting", so the pool and the label are about
the same text even if the posting changes tomorrow.

ONE POOL, SIX PROVIDERS (CAREER-54). `build_pool` takes one store or
several, and every row names the provider it came from plus its whole
source chain -- the feed URL, the raw-feed snapshot, the content hash,
the fetch time, the run and the provider's own API documentation URL
(owner ruling 2026-10-17: "keep the source of the job"). The strata are
the one thing that is not uniform across providers, and the row says so
rather than papering over it: Personio states its own occupation ids,
Recruitee a `category_code`, SmartRecruiters a `function`, and
Greenhouse, Lever and Ashby state only a department the employer typed.
`stratum_source` names which of those a row's stratum came from, so a
stratified sample can tell a machine-readable id from a free-text
department.

## The job family, and why there is no LLM guess here

The brief forbids classifying occupations with a model in this ticket --
the classification pipeline is CAREER-57 -- so the spec's "quick LLM
guess" is NOT produced. What replaces it is better for the purpose
anyway: **Personio's feed states its own occupation taxonomy**, as
`occupation` inside `occupationCategory` (`product_management` inside
`marketing_and_product`). Those are machine ids the tenant picked when
publishing, which makes them a real stratification key with no model, no
cost and no fabrication.

So the export carries `stratum_occupation_category` and
`stratum_occupation` as the strata, and `job_family` is present and
explicitly `null` with a `job_family_status` saying why. A reader has to
be able to tell "no family because nothing classified it yet" from "no
family because this posting has none", and a missing key would not say
that.

The acceptance criterion the spec counts against -- "[25] of the 35 job
families represented, each with [8] or more postings" -- therefore cannot
be settled by this export. What CAN be settled is how many distinct
occupation categories and occupations the pool holds, which is what
`summarise` reports, and whether that breadth is plausibly enough to
cover 25 families once CAREER-57 maps them. The trial report says so in
those words rather than claiming the criterion is met. Two further notes
for the owner: the spec says 35 families and the repository's own
`occupation_families.yaml` holds 40 (CAREER-29 follow-up), and nothing
crosswalks Personio's ids onto either list.

## The salary flag

A deterministic keyword-and-number rule over the snapshot's own text,
not a model and not a parse of an amount: the flag answers "is there a
salary statement in here at all", which is what a stratified sample needs
(the labelling of the amount itself is the labeller's job). The rule, its
match and the matched quote are recorded on the row, so a false positive
is visible rather than mysterious. No value record: there is no salary
dimension in the taxonomy -- `salary_rules.yaml` carries rules and its
four pay-scale tables are placeholders -- and inventing one here would be
exactly the new record shape the brief forbids.
"""
import re
from collections import Counter

from careeros.feeds import geocode, store as store_module

#: Words that mean a posting is talking about pay. German and English,
#: because the pool is both. Matched case-insensitively as whole words.
_SALARY_WORDS = re.compile(
    r'\b(?:lohn|löhne|gehalt|gehälter|salär|salaer|jahreslohn|monatslohn|bruttolohn|'
    r'jahresgehalt|monatsgehalt|grundgehalt|vergütung|verguetung|entlöhnung|entloehnung|'
    r'salary|salaries|compensation|pay\s?range|remuneration|wage|wages)\b', re.I)

#: An amount with a currency or a Swiss-style thousands separator:
#: "CHF 95'000", "95 000 CHF", "80k", "EUR 60.000". A number alone is not
#: a salary -- a posting is full of numbers.
_SALARY_AMOUNT = re.compile(
    r"(?:chf|fr\.|sfr|eur|€)\s*\d[\d'’.\s]{2,}"
    r"|\d[\d'’.\s]{2,}\s*(?:chf|fr\.|sfr|eur|€)"
    r"|\b\d{2,3}\s?k\b(?=[^\w]|$)", re.I)


def salary_signal(text):
    """Whether a posting's own text states something about pay.

    Returns `{'has_salary', 'rule', 'quote'}`. `rule` is `word+amount`
    when both a pay word and an amount are present (the confident case),
    `amount` or `word` when only one is, and None when neither.
    """
    body = text or ''
    word = _SALARY_WORDS.search(body)
    amount = _SALARY_AMOUNT.search(body)
    if word and amount:
        rule = 'word+amount'
    elif amount:
        rule = 'amount'
    elif word:
        rule = 'word'
    else:
        return {'has_salary': False, 'rule': None, 'quote': None}
    match = word or amount
    start, end = max(0, match.start() - 40), min(len(body), match.end() + 40)
    return {'has_salary': True, 'rule': rule,
            'quote': ' '.join(body[start:end].split())}


def _value(posting, dimension):
    record = (posting.get('values') or {}).get(dimension) or {}
    return record.get('value')


#: Which field a provider's machine-readable stratum lives in, and what
#: to call that kind of evidence. A provider with no such field falls
#: back to the department the employer typed, which is free text and is
#: labelled as free text.
STRATUM_FIELDS = {
    'personio': ('occupation', 'occupation_category', "Personio's own occupation taxonomy"),
    'recruitee': ('category_raw', None, "Recruitee's category_code"),
    'smartrecruiters': ('function_raw', 'industry_raw',
                        "SmartRecruiters' function and industry ids"),
}


def _stratum(posting):
    """`(stratum, category, source)` for one posting.

    Three of the six providers state a machine-readable occupation or
    function id; the other three state nothing but a department, which
    is the employer's own free text. Both are usable for drawing a
    stratified sample and they are NOT the same kind of evidence, so the
    row carries which one it got.
    """
    provider = posting.get('provider')
    fields = STRATUM_FIELDS.get(provider)
    if fields:
        stratum, category, source = fields
        value = posting.get(stratum)
        if value:
            return value, (posting.get(category) if category else None), source
    department = posting.get('department')
    return (department, None,
            'the department the employer typed: this provider states no occupation id'
            if department else
            'no stratum: this provider states no occupation id and the posting names no '
            'department')


def pool_row(entry, posting):
    """One export row: the state entry plus the frozen posting.

    Flat on purpose -- it has to survive a CSV as well as a YAML -- and
    every field is either the feed's own word or a code from the
    taxonomy, with the two kept apart by their key names (`contract` is a
    code, `employment_type_raw` is Personio's word).

    The CONTENT comes from the snapshot and the LOCATION comes from the
    state entry, which is deliberate: see `store._derived`. A snapshot
    froze what the feed said; the municipality is what today's register
    and today's geocoder make of it, and an improved geocoder has to be
    able to correct a row without rewriting frozen evidence.
    """
    salary = salary_signal(posting.get('description'))
    location = entry.get('location') or posting.get('location') or {}
    provenance = posting.get('provenance') or entry.get('provenance') or {}
    stratum, stratum_category, stratum_source = _stratum(posting)
    return {
        'key': posting['key'],
        'snapshot_id': entry.get('snapshot_id'),
        'content_hash': posting.get('content_hash'),
        'feed_snapshot': posting.get('feed_snapshot'),
        'provider': posting.get('provider'),
        'tenant': posting.get('tenant'),
        'posting_id': posting.get('posting_id'),
        'url': posting.get('url'),
        # The source chain, flat, because a pool row has to be able to
        # answer "where did this come from" on its own (owner ruling
        # 2026-10-17 2a). The nested block stays on the snapshot and on
        # the state entry.
        'feed_url': provenance.get('feed_url'),
        'feed_variant': provenance.get('feed_variant'),
        'detail_url': provenance.get('detail_url'),
        'api_doc_url': provenance.get('api_doc_url'),
        'api_doc_accessed': provenance.get('api_doc_accessed'),
        'fetched_at': provenance.get('fetched_at'),
        'run_id': provenance.get('run_id'),
        'company': posting.get('employer_name'),
        'title': posting.get('title'),
        'language': _value(posting, 'language'),
        'municipality': entry.get('municipality'),
        'municipality_label': entry.get('municipality_label')
                              or geocode.municipality_label(entry.get('municipality')),
        'canton': entry.get('canton'),
        'offices_raw': posting.get('offices') or [],
        'office_matched': location.get('office'),
        'geocode_method': location.get('method'),
        'geocode_confidence': location.get('confidence'),
        # 'corroborated' when a postal code or a CH/canton prefix backed
        # the match, 'name_only' when a bare municipality name is all
        # there was. See careeros.feeds.geocode on the false positive
        # this cannot rule out; whether a name-only row may be sampled
        # is an owner decision.
        'zurich_evidence': ('corroborated' if location.get('corroborated')
                            else 'name_only'),
        'contract': _value(posting, 'contract'),
        'employment_type_raw': posting.get('employment_type_raw'),
        'workload_min': _value(posting, 'workload_min'),
        'workload_max': _value(posting, 'workload_max'),
        'schedule_raw': posting.get('schedule_raw') or posting.get('commitment_raw'),
        'work_model': _value(posting, 'work_model'),
        'seniority': _value(posting, 'seniority'),
        'seniority_hint': posting.get('seniority_hint') or posting.get('experience_raw'),
        'years_of_experience': posting.get('years_of_experience'),
        'department': posting.get('department'),
        'recruiting_category': posting.get('recruiting_category'),
        'stratum_occupation_category': posting.get('occupation_category') or stratum_category,
        'stratum_occupation': posting.get('occupation') or stratum,
        'stratum_source': stratum_source,
        'job_family': None,
        'job_family_status': ('not classified: CAREER-53 does not classify occupations and '
                              'CAREER-57 owns the pipeline that will. The strata above are '
                              "Personio's own feed-stated occupation ids."),
        'keywords': posting.get('keywords') or [],
        'has_salary': salary['has_salary'],
        'salary_rule': salary['rule'],
        'salary_quote': salary['quote'],
        'published_at': posting.get('published_at'),
        'first_seen_run': entry.get('first_seen_run'),
        'last_seen_run': entry.get('last_seen_run'),
        'posting_status': entry.get('status'),
        'description_characters': len(posting.get('description') or ''),
    }


def build_pool(stores, *, tenants=None, include_out_of_area=False):
    """Every live in-scope posting of one or several stores, as rows.

    "Live" is not closed, which includes `suspected_closing` -- a posting
    missing from ONE fetch is not closed (the spec), and dropping it from
    the pool would be closing it a cycle early. "In scope" is the Zurich
    filter: an office in canton Zurich. Out-of-area postings stay in the
    snapshots either way and are only included here when asked for, which
    is how the excluded half can be counted without being sampled.

    Returns `(rows, skipped)`, where `skipped` says why each posting was
    left out, so the pool's size is always explainable.

    `stores` is one `Store` or several. Several is the multi-provider
    pool: the rows interleave and sort by key, which is
    `{provider}:{tenant}:{id}`, so the file is grouped by provider
    without anything grouping it.
    """
    rows, skipped = [], []
    for store in ([stores] if hasattr(stores, 'root') else list(stores)):
        for tenant in (tenants if tenants is not None else store.tenants_with_state()):
            for entry in store_module.live_postings(store, tenant):
                area = entry.get('area_status')
                if area != geocode.IN_AREA and not include_out_of_area:
                    skipped.append({'key': entry['key'], 'provider': store.provider,
                                    'reason': area or 'no area status'})
                    continue
                snapshot = store.read_posting_snapshot(tenant, entry['posting_id'],
                                                       entry.get('content_hash'))
                if not snapshot or not snapshot.get('posting'):
                    skipped.append({'key': entry['key'], 'provider': store.provider,
                                    'reason': 'the snapshot this posting points at is missing'})
                    continue
                rows.append(pool_row(entry, snapshot['posting']))
    rows.sort(key=lambda row: row['key'])
    return rows, skipped


def summarise(rows):
    """What the pool holds, in the terms the spec's acceptance criteria
    are written in -- plus the honest note that the job-family criterion
    is not one this export can settle (see the module docstring)."""
    def tally(field):
        return dict(Counter(row.get(field) or 'unknown' for row in rows).most_common())

    categories = Counter(row.get('stratum_occupation_category') or 'unknown' for row in rows)
    providers = {}
    for row in rows:
        provider = providers.setdefault(row.get('provider') or 'unknown',
                                        {'postings': 0, 'tenants': set(), 'with_description': 0})
        provider['postings'] += 1
        provider['tenants'].add(row.get('tenant'))
        provider['with_description'] += 1 if row.get('description_characters') else 0
    return {
        'postings': len(rows),
        'providers': len(providers),
        'by_provider': {name: {'postings': counts['postings'],
                               'tenants': len(counts['tenants']),
                               'with_description': counts['with_description']}
                        for name, counts in sorted(providers.items())},
        'tenants': len({(row.get('provider'), row['tenant']) for row in rows}),
        'companies': len({row['company'] for row in rows if row['company']}),
        'municipalities': len({row['municipality'] for row in rows if row['municipality']}),
        'geocoded_to_municipality': sum(1 for row in rows if row['municipality']),
        'corroborated_location': sum(1 for row in rows
                                     if row['zurich_evidence'] == 'corroborated'),
        'name_only_location': sum(1 for row in rows
                                  if row['zurich_evidence'] == 'name_only'),
        'with_description': sum(1 for row in rows if row['description_characters']),
        'with_salary_signal': sum(1 for row in rows if row['has_salary']),
        'by_language': tally('language'),
        'by_contract': tally('contract'),
        'by_work_model': tally('work_model'),
        'by_stratum_source': tally('stratum_source'),
        'by_seniority_hint': tally('seniority_hint'),
        'by_workload': dict(Counter(f"{row.get('workload_min')}-{row.get('workload_max')}"
                                    for row in rows).most_common()),
        'by_municipality': tally('municipality_label'),
        'by_occupation_category': dict(categories.most_common()),
        'occupation_categories': len([key for key in categories if key != 'unknown']),
        'occupation_categories_with_8_or_more': len(
            [key for key, count in categories.items() if key != 'unknown' and count >= 8]),
        'occupations': len({row['stratum_occupation'] for row in rows
                            if row['stratum_occupation'] and row['stratum_occupation'] != 'other'}),
        'job_families': None,
        'job_family_note': ('no posting carries a job family: CAREER-53 classifies no '
                            'occupations (CAREER-57 owns that). The occupation-category counts '
                            'above are what this pool can say about breadth.'),
    }


def write_pool(store, rows, *, day, summary=None, meta=None):
    """The pool file. YAML, because every other staging file in this
    repository is YAML and a row carries a list (`keywords`) that a CSV
    would have to flatten and a reader un-flatten."""
    path = store.export_path(day)
    payload = {'provider': store.provider,
               'providers': sorted({row.get('provider') for row in rows if row.get('provider')}),
               'exported_at': store_module.now(), 'day': day}
    payload.update(meta or {})
    payload['summary'] = summary if summary is not None else summarise(rows)
    payload['postings'] = rows
    store_module.write_yaml(path, payload)
    return path
