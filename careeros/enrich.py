"""Regenerable company facts derived only from stored job fields."""
from collections import Counter
from datetime import date

# Unknown seniority labels do not imply a rank and are excluded.
SENIORITY = ('intern', 'entry', 'junior', 'mid', 'senior', 'lead', 'staff',
             'principal', 'manager', 'director', 'executive')
ALIASES = {'internship': 'intern', 'entry-level': 'entry', 'entry level': 'entry',
           'mid-level': 'mid', 'mid level': 'mid', 'associate': 'junior'}


def _texts(value):
    values = [value] if isinstance(value, str) else value
    return [v.strip() for v in values if isinstance(v, str) and v.strip()] if isinstance(values, list) else []


def enrich_company(jobs):
    """Aggregate postings without mutating inputs or performing any IO.

    Keywords count once per posting, case-insensitively, with lexical ties.
    Missing or malformed legacy values are ignored. Empty bounds/dates are null.
    """
    jobs = list(jobs)
    sectors, locations, ranks, dates = set(), set(), set(), []
    keywords = Counter()
    for job in jobs:
        for key in ('sector', 'sectors', 'industry', 'industries'):
            sectors.update(_texts(job.get(key)))
        locations.update(_texts(job.get('location')))
        keywords.update({word.casefold() for word in _texts(job.get('keywords'))})
        level = job.get('seniority')
        if isinstance(level, str):
            level = level.strip().casefold()
            level = ALIASES.get(level, level)
            if level in SENIORITY:
                ranks.add(SENIORITY.index(level))
        try:
            dates.append(date.fromisoformat(str(job.get('posted_date'))).isoformat())
        except ValueError:
            pass
    return dict(
        sectors=sorted(sectors), locations_seen=sorted(locations),
        remote_friendly=any(job.get('remote_ok') is True for job in jobs),
        seniority_range={'min': SENIORITY[min(ranks)] if ranks else None,
                         'max': SENIORITY[max(ranks)] if ranks else None},
        hiring_activity={'count': len(jobs), 'most_recent_posted_date': max(dates, default=None)},
        top_keywords=sorted(keywords, key=lambda word: (-keywords[word], word))[:10],
    )


def regenerate_company(root, identifier):
    """Merge derived facts through vault helpers; caller holds any write lock.

    Sector aggregation is gated on kind == 'employer' (Section 1's behavior
    matrix): sector/size are not concepts that apply cleanly to an
    institution or an aggregate placeholder. Because block starts from a
    *copy of the existing* enrichment before merging derived values in, a
    company that was an employer at some earlier regeneration (so
    enrichment.sectors got populated) and is later re-kinded away keeps
    showing that stale data forever unless the gate actively deletes both
    the top-level sectors field and the nested enrichment.sectors key,
    rather than merely omitting sectors from what gets newly derived.
    """
    from careeros import vault
    company = vault.load_company(root, identifier)
    if company is None:
        return None
    derived = enrich_company(job for job in vault.list_jobs(root)
                             if job.get('company_id') == identifier)
    previous = company.get('enrichment')
    block = dict(previous) if isinstance(previous, dict) else {}
    updates = {}
    if company.get('kind', 'employer') == 'employer':
        for key, value in derived.items():
            if isinstance(value, dict) and isinstance(block.get(key), dict):
                value = block[key] | value
            block[key] = value
    else:
        for key, value in derived.items():
            if key == 'sectors':
                continue
            if isinstance(value, dict) and isinstance(block.get(key), dict):
                value = block[key] | value
            block[key] = value
        block.pop('sectors', None)
        # Section 1's matrix gives institutions and aggregates no sector and
        # no size, so a company re-kinded away from employer must lose both,
        # not just sectors: clear the top-level sectors list and every size
        # representation (legacy string plus the derived pair), same
        # active-deletion rule the sectors note above describes.
        if company.get('sectors'):
            updates['sectors'] = []
        for key in ('size', 'size_range', 'size_class'):
            if company.get(key) is not None:
                updates[key] = None
    return vault.save_company(root, {'enrichment': block} | updates, identifier)
