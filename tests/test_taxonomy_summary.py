"""Read-only vault-wide taxonomy/methodology page (skills, ISIC industries,
company size classes): pure aggregation functions, then the API endpoint
that wraps them."""
from careeros.web.pages import taxonomy

ISIC_SECTIONS = [{'code': 'J', 'label': 'Information and communication'},
                  {'code': 'K', 'label': 'Financial and insurance activities'}]


def test_skill_counts_sorted_by_count_desc_then_name():
    experiences = [{'skills': ['Python', 'SQL']}, {'skills': ['Python']}, {'skills': []}, {}]
    assert taxonomy.skill_counts(experiences, {}) == [
        {'skill': 'Python', 'count': 2},
        {'skill': 'SQL', 'count': 1},
    ]


def test_skill_counts_includes_tag_derived_skills_with_registry_label():
    experiences = [{'tags': ['skill/capability:python']}, {'tags': ['skill/domain:finance']}]
    tag_labels = {'skill/capability:python': {'label': 'Python', 'local': False},
                  'skill/domain:finance': {'label': 'Finance', 'local': False}}
    assert taxonomy.skill_counts(experiences, tag_labels) == [
        {'skill': 'Finance', 'count': 1},
        {'skill': 'Python', 'count': 1},
    ]


def test_skill_counts_falls_back_to_the_slug_for_an_unknown_tag():
    experiences = [{'tags': ['skill/capability:public-speaking']}]
    assert taxonomy.skill_counts(experiences, {}) == [{'skill': 'public-speaking', 'count': 1}]


def test_skill_counts_ignores_non_skill_facets():
    experiences = [{'tags': ['function:builder', 'tool:python', 'experience-type:employment']}]
    assert taxonomy.skill_counts(experiences, {}) == []


def test_skill_counts_merges_legacy_and_tag_derived_skill_named_the_same():
    experiences = [{'skills': ['Python']}, {'tags': ['skill/capability:python']}]
    tag_labels = {'skill/capability:python': {'label': 'Python', 'local': False}}
    assert taxonomy.skill_counts(experiences, tag_labels) == [{'skill': 'Python', 'count': 2}]


def test_skill_counts_keeps_legacy_skills_as_is_free_text():
    """Legacy `skills` strings are free text: unlike tag-derived skills,
    they are never relabeled against the registry, even if a value
    happens to look like a slug."""
    experiences = [{'skills': ['public-speaking']}]
    assert taxonomy.skill_counts(experiences, {}) == [{'skill': 'public-speaking', 'count': 1}]


def test_skill_counts_dedupes_repeated_values_within_one_experience():
    experiences = [{'skills': ['Python', 'Python'],
                    'tags': ['skill/capability:python', 'skill/domain:python']}]
    tag_labels = {'skill/capability:python': {'label': 'Python', 'local': False},
                  'skill/domain:python': {'label': 'Python', 'local': False}}
    assert taxonomy.skill_counts(experiences, tag_labels) == [{'skill': 'Python', 'count': 1}]


def test_skill_counts_legacy_only_record():
    experiences = [{'skills': ['Excel']}, {}]
    assert taxonomy.skill_counts(experiences, {}) == [{'skill': 'Excel', 'count': 1}]


def test_industry_counts_dedupes_repeated_codes_within_one_company():
    companies = [{'sectors': ['J', 'J']}]
    assert taxonomy.industry_counts(companies, ISIC_SECTIONS) == [
        {'code': 'J', 'label': 'Information and communication', 'count': 1},
    ]


def test_industry_counts_labels_and_sorts_by_count_desc_then_label():
    companies = [{'sectors': ['J']}, {'sectors': ['J', 'K']}, {'sectors': []}, {}]
    assert taxonomy.industry_counts(companies, ISIC_SECTIONS) == [
        {'code': 'J', 'label': 'Information and communication', 'count': 2},
        {'code': 'K', 'label': 'Financial and insurance activities', 'count': 1},
    ]


def test_industry_counts_falls_back_to_the_code_for_an_unknown_section():
    companies = [{'sectors': ['Z']}]
    assert taxonomy.industry_counts(companies, ISIC_SECTIONS) == [{'code': 'Z', 'label': 'Z', 'count': 1}]


def test_size_counts_canonical_order_with_an_honest_unknown_bucket():
    """Every class in the vocabulary gets a row, in the vocabulary's own
    order, whether or not a company is in it -- including `xl`, which
    joined the list with the BFS boundaries (D3, 2026-10-17)."""
    companies = [{'size_class': 'small'}, {'size_class': 'small'}, {'size_class': 'large'},
                 {'size_class': None}, {}]
    assert taxonomy.size_counts(companies) == [
        {'size_class': 'micro', 'count': 0},
        {'size_class': 'small', 'count': 2},
        {'size_class': 'medium', 'count': 0},
        {'size_class': 'large', 'count': 1},
        {'size_class': 'xl', 'count': 0},
        {'size_class': 'unknown', 'count': 2},
    ]


def test_aggregate_context_shape():
    context = taxonomy.aggregate_context(
        [{'skills': ['Python']}], [{'sectors': ['J'], 'size_class': 'small'}], ISIC_SECTIONS,
        {'function:builder': {'label': 'Builder', 'local': True}})
    assert context == {
        'skills': [{'skill': 'Python', 'count': 1}],
        'industries': [{'code': 'J', 'label': 'Information and communication', 'count': 1}],
        'sizes': [{'size_class': 'micro', 'count': 0}, {'size_class': 'small', 'count': 1},
                  {'size_class': 'medium', 'count': 0}, {'size_class': 'large', 'count': 0},
                  {'size_class': 'xl', 'count': 0}, {'size_class': 'unknown', 'count': 0}],
        'tag_labels': {'function:builder': {'label': 'Builder', 'local': True}},
    }


def test_taxonomy_api_endpoint(api_client):
    data = api_client.get('/api/taxonomy').get_json()
    assert sorted(data) == ['industries', 'sizes', 'skills', 'tag_labels']
    assert {'code': 'J', 'label': 'Information and communication', 'count': 1} in data['industries']
    assert {'size_class': 'small', 'count': 1} in data['sizes']
