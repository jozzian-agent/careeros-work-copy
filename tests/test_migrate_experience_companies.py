"""Tests for scripts/migrate_experience_companies.py (batch 3).

Fixture-only vaults; the live owner vault is never touched by tests.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from careeros import vault

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'migrate_experience_companies.py'


def _load_script():
    spec = importlib.util.spec_from_file_location('migrate_exp_co', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def vault_root(tmp_path):
    for kind in ('experiences', 'companies', 'jobs'):
        (tmp_path / kind).mkdir()
    vault.save_company(tmp_path, {'name': 'Acme AG', 'website': 'https://acme.example'})
    vault.save_experience(tmp_path, {
        'company': 'Acme', 'title': 'Product Manager',
        'start': '2020-01', 'end': 'present'})
    vault.save_experience(tmp_path, {
        'company': 'Early Career', 'title': '2 roles',
        'start': '2013-01', 'end': '2015-12'})
    # Auto-assigned ids: first experience EXP-001, second EXP-002.
    ids = {e['id'] for e in vault.list_experiences(tmp_path)}
    assert ids == {'EXP-001', 'EXP-002'}
    return tmp_path


PLAN = {
    'companies': [{'name': 'Zeta Corp', 'website': 'https://example.test/aaa'}],
    'links': [{'experience_id': 'EXP-001', 'company_name': 'Acme AG'},
              {'experience_id': 'EXP-099', 'company_name': 'Ghost'}],
    'splits': [{'experience_id': 'EXP-002', 'delete_source': True, 'roles': [
        {'company_name': 'Zeta Corp', 'title': 'Advisor', 'start': '2013-01', 'end': '2014-06',
         'highlights': ['Kept highlight.']},
        {'company_name': 'NewCo', 'website': 'https://example.test/new',
         'title': 'Intern', 'start': '2014-07', 'end': '2015-12'}]}],
}


def test_migration_links_creates_and_splits(vault_root, tmp_path_factory):
    mod = _load_script()
    plan_path = tmp_path_factory.mktemp('plan') / 'plan.json'
    plan_path.write_text(json.dumps(PLAN))
    plan = mod.load_plan(plan_path)
    mod.apply_plan(vault_root, plan, apply_changes=True)

    # link: EXP-001 now points at the existing company, canonical name frozen
    exp1 = vault.load_experience(vault_root, 'EXP-001')
    assert exp1['company_id'] == 'CO-001'
    assert exp1['company'] == 'Acme AG'

    # explicit company created; split-role company created on demand
    names = {c['name'] for c in vault.list_companies(vault_root)}
    assert {'Zeta Corp', 'NewCo'} <= names

    # split: source deleted, two linked children created
    assert vault.load_experience(vault_root, 'EXP-002') is None
    kids = vault.list_experiences(vault_root)
    assert len(kids) == 3
    advisor = next(e for e in kids if e['title'] == 'Advisor')
    intern = next(e for e in kids if e['title'] == 'Intern')
    assert advisor['highlights'] == ['Kept highlight.']
    aaa_id = next(c['id'] for c in vault.list_companies(vault_root) if c['name'] == 'Zeta Corp')
    new_id = next(c['id'] for c in vault.list_companies(vault_root) if c['name'] == 'NewCo')
    assert advisor['company_id'] == aaa_id
    assert intern['company_id'] == new_id

    # missing experience id in the plan is skipped, not fatal
    assert all(e['id'] != 'EXP-099' for e in kids)


def test_migration_is_idempotent(vault_root, tmp_path_factory):
    mod = _load_script()
    plan_path = tmp_path_factory.mktemp('plan') / 'plan.json'
    plan_path.write_text(json.dumps(PLAN))
    for _ in range(2):
        mod.apply_plan(vault_root, mod.load_plan(plan_path), apply_changes=True)

    exps = vault.list_experiences(vault_root)
    assert len(exps) == 3
    assert len(vault.list_companies(vault_root)) == 3
    assert all(e['company_id'] for e in exps)
