"""Read-only taxonomy/methodology page: counts for the skills tagged on
the reading user's own experiences (M2: those records are private, see
decision D3), plus the ISIC industry sections companies sit in and
companies' EU size classes, which are shared universe and so stay
vault-wide. No editing lives here; this is a reporting surface only."""
from careeros import vault
from org_intake import classify as sectors

def taxonomy_context(root, owner=None):
    # M2 (CAREER-39): the skill counts are over this user's own
    # positions, so the page reports their own experience and never
    # aggregates somebody else's (D3). The industry and size breakdowns
    # are over companies, which are shared universe and stay vault-wide.
    return aggregate_context(vault.list_experiences(root, owner),
                             vault.visible_companies(root, owner),
                             sectors.load_isic_sections(), vault.tag_label_map(root))

def aggregate_context(experiences, companies, isic_sections, tag_labels):
    """Build the aggregate counts without I/O, so the breakdown logic is
    testable against plain lists of records."""
    return dict(
        skills=skill_counts(experiences, tag_labels),
        industries=industry_counts(companies, isic_sections),
        sizes=size_counts(companies),
        tag_labels=tag_labels,
    )

def skill_counts(experiences, tag_labels):
    """Every skill used across experiences, merging two sources per
    experience: the legacy free-text `skills` field (kept verbatim, since
    it is free text with no registry entry to label it) and `tags` tokens
    whose facet is one of the skill facets (`skill/capability`,
    `skill/domain` -- the registry's `skill/*` facets, per vault.TAG_FACETS;
    read dynamically from tag_labels rather than hardcoded here, so a
    future facet rename or addition is picked up automatically). A
    tag-derived skill displays as its registry label, falling back to the
    slug portion of the id when the token has no registry entry, so the
    same skill named identically by both sources merges into one row
    instead of appearing twice. Each experience is deduplicated before
    counting, so a repeated value within one record contributes at most
    one count. Sorted by count desc then name."""
    counts = {}
    for exp in experiences:
        seen = set(exp.get('skills') or [])
        for tag in exp.get('tags') or []:
            facet, _, value_id = tag.partition(':')
            if facet.startswith('skill/'):
                seen.add(tag_labels.get(tag, {}).get('label') or value_id)
        for skill in seen:
            counts[skill] = counts.get(skill, 0) + 1
    return [{'skill': skill, 'count': count}
            for skill, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))]

def industry_counts(companies, isic_sections):
    """Every ISIC section code any company's `sectors` field carries,
    human-labeled, with how many companies carry it, sorted by count
    desc then label. Each company is deduplicated before counting, so a
    repeated code within one record contributes at most one count."""
    isic_labels = {section['code']: section['label'] for section in isic_sections}
    counts = {}
    for company in companies:
        for code in set(company.get('sectors') or []):
            counts[code] = counts.get(code, 0) + 1
    return [{'code': code, 'label': isic_labels.get(code, code), 'count': count}
            for code, count in sorted(counts.items(),
                                      key=lambda item: (-item[1], isic_labels.get(item[0], item[0]).casefold()))]

def size_counts(companies):
    """Company size_class breakdown in the vocabulary's own order
    (`vault.SIZE_CLASSES`, smallest first), plus a trailing `unknown`
    entry for companies with no size_class, so the breakdown always
    accounts for every company.

    The order used to be a second copy of the vocabulary in this module.
    It is the taxonomy's list itself since CAREER-55, so a class added
    there (`xl`, 2026-10-17) appears here without an edit.

    Each row carries the words it is shown by as well as its code
    (CAREER-71). The page used to title-case the code, which reads "Xl"
    for the class the taxonomy labels "Very large"; the label travels with
    the count instead, and the `unknown` row -- which is this module's own
    row and not a taxonomy code -- says Unknown."""
    counts = {size: 0 for size in vault.SIZE_CLASSES}
    unknown = 0
    for company in companies:
        size_class = company.get('size_class')
        if size_class in counts:
            counts[size_class] += 1
        else:
            unknown += 1
    return [{'size_class': size, 'label': vault.SIZE_CLASS_LABELS[size], 'count': counts[size]}
            for size in vault.SIZE_CLASSES] + \
        [{'size_class': 'unknown', 'label': 'Unknown', 'count': unknown}]
