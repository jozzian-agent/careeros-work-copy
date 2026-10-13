"""Read-only vault-wide taxonomy/methodology page (skills, ISIC industries,
company size classes): pure aggregation functions, then the API endpoint
that wraps them."""
from careeros.web.pages import taxonomy

ISIC_SECTIONS = [{'code': 'J', 'label': 'Information and communication'},
                  {'code': 'K', 'label': 'Financial and insurance activities'}]


def test_skill_counts_sorted_by_count_desc_then_name():
    experiences = [{'skills': ['Python', 'SQL']}, {'skills': ['Python']}, {'skills': []}, {}]
    assert taxonomy.skill_counts(experiences) == [
        {'skill': 'Python', 'count': 2},
        {'skill': 'SQL', 'count': 1},
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
    companies = [{'size_class': 'small'}, {'size_class': 'small'}, {'size_class': 'large'},
                 {'size_class': None}, {}]
    assert taxonomy.size_counts(companies) == [
        {'size_class': 'micro', 'count': 0},
        {'size_class': 'small', 'count': 2},
        {'size_class': 'medium', 'count': 0},
        {'size_class': 'large', 'count': 1},
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
                  {'size_class': 'unknown', 'count': 0}],
        'tag_labels': {'function:builder': {'label': 'Builder', 'local': True}},
    }


def test_taxonomy_api_endpoint(api_client):
    data = api_client.get('/api/taxonomy').get_json()
    assert sorted(data) == ['industries', 'sizes', 'skills', 'tag_labels']
    assert {'code': 'J', 'label': 'Information and communication', 'count': 1} in data['industries']
    assert {'size_class': 'small', 'count': 1} in data['sizes']
