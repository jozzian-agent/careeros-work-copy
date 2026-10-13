"""Read-only taxonomy/methodology page: vault-wide counts for the skills
tagged on experiences, the ISIC industry sections companies sit in, and
companies' EU size classes. No editing lives here; this is a reporting
surface only."""
from careeros import vault
from org_intake import classify as sectors

SIZE_CLASS_ORDER = ('micro', 'small', 'medium', 'large')

def taxonomy_context(root):
    return aggregate_context(vault.list_experiences(root), vault.list_companies(root),
                             sectors.load_isic_sections(), vault.tag_label_map(root))

def aggregate_context(experiences, companies, isic_sections, tag_labels):
    """Build the aggregate counts without I/O, so the breakdown logic is
    testable against plain lists of records."""
    return dict(
        skills=skill_counts(experiences),
        industries=industry_counts(companies, isic_sections),
        sizes=size_counts(companies),
        tag_labels=tag_labels,
    )

def skill_counts(experiences):
    """Every skill string used across experiences' `skills` field, with
    how many experiences carry it, sorted by count desc then name."""
    counts = {}
    for exp in experiences:
        for skill in exp.get('skills') or []:
            counts[skill] = counts.get(skill, 0) + 1
    return [{'skill': skill, 'count': count}
            for skill, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))]

def industry_counts(companies, isic_sections):
    """Every ISIC section code any company's `sectors` field carries,
    human-labeled, with how many companies carry it, sorted by count
    desc then label."""
    isic_labels = {section['code']: section['label'] for section in isic_sections}
    counts = {}
    for company in companies:
        for code in company.get('sectors') or []:
            counts[code] = counts.get(code, 0) + 1
    return [{'code': code, 'label': isic_labels.get(code, code), 'count': count}
            for code, count in sorted(counts.items(),
                                      key=lambda item: (-item[1], isic_labels.get(item[0], item[0]).casefold()))]

def size_counts(companies):
    """Company size_class breakdown in the canonical micro/small/medium/
    large order, plus a trailing `unknown` entry for companies with no
    size_class, so the breakdown always accounts for every company."""
    counts = {size: 0 for size in SIZE_CLASS_ORDER}
    unknown = 0
    for company in companies:
        size_class = company.get('size_class')
        if size_class in counts:
            counts[size_class] += 1
        else:
            unknown += 1
    return [{'size_class': size, 'count': counts[size]} for size in SIZE_CLASS_ORDER] + \
        [{'size_class': 'unknown', 'count': unknown}]
