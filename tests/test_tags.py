"""Section 2 (Tag Inventory and Taxonomy). Synthetic fixtures only."""
from pathlib import Path
import shutil

import pytest

from careeros import vault
from careeros.server import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / 'sample/vault', tmp_path / 'vault')
    return tmp_path / 'vault'


@pytest.fixture
def client(root):
    return create_app(root).test_client()


# --- Engineering item 1: tags.yaml round-trip ------------------------------

def test_tags_yaml_defaults_have_five_facets(tmp_path):
    tags = vault.load_tags(tmp_path)
    assert set(tags['facets']) == set(vault.TAG_FACETS)
    assert {v['id'] for v in tags['facets']['experience-type']['values']} == {
        'employment', 'guest-lecture', 'volunteer'}


def test_tags_round_trip_load_save(tmp_path):
    tags = vault.load_tags(tmp_path)
    tags['facets']['tool']['values'].append({'id': 'figma', 'label': 'Figma'})
    saved = vault.save_tags(tmp_path, tags)
    loaded = vault.load_tags(tmp_path)
    assert loaded['facets']['tool']['values'] == [{'id': 'figma', 'label': 'Figma'}]
    assert saved['updated'] == loaded['updated']


# --- Engineering item 2: unknown facet rejected, naming the facet ---------

def test_save_with_bogus_facet_raises_naming_the_facet(tmp_path):
    vault.save_company(tmp_path, {'name': 'Fiction Co'})
    with pytest.raises(ValueError, match='nonexistent/facet'):
        vault.save_experience(tmp_path, {'company': 'Fiction Co', 'title': 'Builder',
                                         'start': '2020-01', 'end': 'present',
                                         'tags': ['nonexistent/facet:something']})


def test_save_with_malformed_tag_token_raises(tmp_path):
    vault.save_company(tmp_path, {'name': 'Fiction Co'})
    with pytest.raises(ValueError, match='facet:id'):
        vault.save_experience(tmp_path, {'company': 'Fiction Co', 'title': 'Builder',
                                         'start': '2020-01', 'end': 'present', 'tags': ['bogus']})


def test_unknown_value_within_known_facet_is_rejected_without_proposal(tmp_path):
    # Decision 10: ordinary validation rejects unknown ids, naming the facet
    # and the value, so a typo never silently becomes a permanent registry
    # entry. Only the explicit proposal flow may add a new value.
    with pytest.raises(ValueError, match='Unknown tag id "public-speaking" in facet "skill/capability"'):
        vault.save_experience(tmp_path, {'company': 'Fiction Co', 'title': 'Builder', 'start': '2020-01',
                                          'end': 'present', 'tags': ['skill/capability:public-speaking']})
    assert not (tmp_path / 'tags.yaml').exists()


def test_proposed_tags_registers_new_value(tmp_path):
    exp = vault.save_experience(tmp_path, {'company': 'Fiction Co', 'title': 'Builder', 'start': '2020-01',
                                            'end': 'present', 'tags': ['skill/capability:public-speaking'],
                                            'proposed_tags': ['skill/capability:public-speaking']})
    assert exp['tags'] == ['skill/capability:public-speaking']
    tags = vault.load_tags(tmp_path)
    assert {'id': 'public-speaking', 'label': 'Public Speaking'} in tags['facets']['skill/capability']['values']


def test_proposal_cannot_open_the_function_facet(tmp_path):
    # The function facet stays closed to this flow: proposed function values
    # are governed by Section 4's own flow, not by proposed_tags here.
    with pytest.raises(ValueError, match='function'):
        vault.save_experience(tmp_path, {'company': 'Fiction Co', 'title': 'Builder', 'start': '2020-01',
                                          'end': 'present', 'tags': ['function:engineering-manager'],
                                          'proposed_tags': ['function:engineering-manager']})


def test_tag_id_split_on_first_colon_only():
    assert vault.split_tag_id('skill/capability:project-management') == ('skill/capability', 'project-management')
    with pytest.raises(ValueError):
        vault.split_tag_id('no-colon-here')


# --- Facet:id transport rules (percent-encoding / routing) -----------------

def test_tag_token_characters_are_url_safe_once_percent_encoded():
    from urllib.parse import quote, unquote
    token = 'skill/capability:project-management'
    encoded = quote(token, safe='')
    assert encoded == 'skill%2Fcapability%3Aproject-management'
    assert unquote(encoded) == token


# --- One-time migration: 27-tag mapping table ------------------------------

def test_migrate_skills_to_tags_maps_known_tools_and_default_capability(root):
    migrated = vault.migrate_skills_to_tags(root)
    assert migrated  # the sample vault's synthetic experiences all have skills, no tags yet
    for exp in vault.list_experiences(root):
        assert exp['tags'], exp['id']
        for token in exp['tags']:
            facet, _ = vault.split_tag_id(token)
            assert facet in ('tool', 'skill/capability')


def test_legacy_skill_to_tag_id_recognizes_known_tools():
    assert vault.legacy_skill_to_tag_id('Python') == 'tool:python'
    assert vault.legacy_skill_to_tag_id('AWS') == 'tool:aws'
    assert vault.legacy_skill_to_tag_id('Mentoring') == 'skill/capability:mentoring'


# --- Engineering item 5: legacy skills-only payload translated during the -
# --- overlap window, never silently treated as "no tags" ------------------

def test_skills_only_payload_translates_into_tags_during_overlap(client, root):
    vault.save_company(root, {'name': 'Fiction Co'})
    created = client.post('/api/experiences', json={'company': 'Fiction Co', 'title': 'Builder',
                                                     'start': '2020-01', 'end': 'present',
                                                     'skills': ['Python', 'Public speaking']}).json
    assert created['tags'] == ['tool:python', 'skill/capability:public-speaking']
    assert created['skills'] == ['Python', 'Public speaking']  # deprecated field still rendered


def test_skills_only_payload_retranslates_even_when_tags_already_set(root):
    # Decision 6: translation must run on every legacy payload, not only the
    # first one. Gating it on "stored tags are empty" would let an owner who
    # already has tags set from the new UI silently desync them from a
    # later legacy skills-only edit.
    vault.save_company(root, {'name': 'Fiction Co'})
    exp = vault.save_experience(root, {'company': 'Fiction Co', 'title': 'Builder', 'start': '2020-01',
                                        'end': 'present', 'tags': ['skill/capability:public-speaking'],
                                        'proposed_tags': ['skill/capability:public-speaking']})
    updated = vault.save_experience(root, {'skills': ['Python']}, exp['id'])
    assert updated['tags'] == ['tool:python']
    assert updated['skills'] == ['Python']


def test_absent_tags_key_leaves_existing_tags_untouched(root):
    vault.save_company(root, {'name': 'Fiction Co'})
    exp = vault.save_experience(root, {'company': 'Fiction Co', 'title': 'Builder', 'start': '2020-01',
                                        'end': 'present', 'tags': ['tool:python'],
                                        'proposed_tags': ['tool:python']})
    updated = vault.save_experience(root, {'title': 'Senior Builder'}, exp['id'])
    assert updated['tags'] == ['tool:python']
