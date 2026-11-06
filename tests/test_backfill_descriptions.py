"""Tests for scripts/backfill_descriptions.py (CAREER-131).

Run the script in-process through its main() against a real tmp_path
vault, with fixture descriptions.yaml/pool.yaml files written the way
export_jobs_for_prod.py writes them. The rules under test, in the order
the owner stated them:

  1. fill ONLY jobs whose description is empty
  2. NEVER overwrite an existing description
  3. dry run is the default and writes nothing; counts are reported
  4. owned records are never touched by a bulk backfill
  5. provenance says 'feed' on a filled description
  6. a second run fills nothing (idempotence)
  7. a job matched but with no resolved text is counted, not filled
"""
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from careeros import users, vault

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'scripts' / 'backfill_descriptions.py'
PASSWORD = 'correct horse battery staple'

_spec = importlib.util.spec_from_file_location('backfill_descriptions', SCRIPT)
assert _spec is not None and _spec.loader is not None
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)

KEY_A = 'greenhouse:acme:1001'   # empty description, text available -> filled
KEY_B = 'greenhouse:acme:1002'   # already has text -> never overwritten
KEY_C = 'greenhouse:acme:1003'   # empty, no text in descriptions.yaml
KEY_D = 'greenhouse:acme:1004'   # empty, but the record has an owner
KEY_E = 'greenhouse:acme:1005'   # whitespace-only description -> filled
TEXT_A = 'Acme is hiring a platform engineer in Zürich. Apply within.'
TEXT_E = 'On Running is hiring a retail associate in St. Gallen.'
GENERATION_TEXT = {KEY_A: TEXT_A, KEY_B: 'IGNORED new text', KEY_E: TEXT_E}


def make_job(root, key, *, description=None, owner=None, **extra):
    """A job written the way import_pool_to_vault writes imported universe
    records: origin 'discovered', in_pipeline False, ownerless unless the
    caller passes an owner."""
    data = {'id': f'job-{key.rsplit(":", 1)[-1]}', 'title': 'Platform Engineer',
            'url': f'https://boards.greenhouse.io/acme/jobs/{key.rsplit(":", 1)[-1]}',
            'source_id': key, 'status': 'new', 'origin': 'discovered',
            'in_pipeline': False, **extra}
    if description is not None:
        data['description'] = description
    if owner is not None:
        data[vault.OWNER_FIELD] = owner
    return vault.save_job(root, data)


@pytest.fixture
def env(tmp_path):
    """A production-shaped vault: five imported jobs (one owned by the
    user, one with text already), plus one job NOT in the generation
    (must never be touched at all), plus the two generation files."""
    root = tmp_path / 'vault'
    (root / 'jobs').mkdir(parents=True)
    user = users.create_user(root, email='owner@example.test', name='Owner',
                             role='admin', password=PASSWORD)
    empty_a = make_job(root, KEY_A, description='')
    has_text = make_job(root, KEY_B, description='The original posting text.')
    no_source = make_job(root, KEY_C, description='')
    owned = make_job(root, KEY_D, description='', owner=user['id'])
    whitespace = make_job(root, KEY_E, description='   \n ')
    outsider = make_job(root, 'ashby:other:9999', description='Untouched.',
                        source_id='ashby:other:9999')

    gen = tmp_path / 'generation'
    gen.mkdir()
    (gen / 'descriptions.yaml').write_text(yaml.safe_dump(
        {'day': '2026-11-03', 'descriptions': GENERATION_TEXT}, allow_unicode=True))
    pool_keys = [KEY_A, KEY_B, KEY_C, KEY_D, KEY_E]
    (gen / 'pool.yaml').write_text(yaml.safe_dump(
        {'day': '2026-11-03',
         'postings': [{'key': k, 'url': f'https://x/{k}'} for k in pool_keys]},
        allow_unicode=True))
    return {'root': root, 'gen': gen, 'user': user,
            'jobs': {'empty': empty_a, 'has_text': has_text, 'no_source': no_source,
                     'owned': owned, 'whitespace': whitespace, 'outsider': outsider}}


def run(env, *flags):
    return backfill.main(['--vault', str(env['root']),
                          '--descriptions', str(env['gen'] / 'descriptions.yaml'),
                          '--pool', str(env['gen'] / 'pool.yaml'), *flags])


def read_back(env, job):
    """Locate the stored record by source_id: save_job assigns its own ids,
    so the fixture cannot predict the filename."""
    for path in sorted((Path(env['root']) / 'jobs').glob('*.yaml')):
        data = vault._read(path)
        if data and data.get('source_id') == job['source_id']:
            return data
    raise AssertionError(f"no stored job with source_id {job['source_id']}")


# --- 1+2+3: the dry run reports the four counts and writes NOTHING --------

def test_dry_run_is_the_default_and_writes_nothing(env, capsys):
    before = {p.read_bytes() for p in (env['root'] / 'jobs').glob('*.yaml')}
    assert run(env) == 0
    out = capsys.readouterr().out
    assert 'DRY RUN' in out
    for count, expected in [('matched', 5), ('would fill', 2),
                            ('already had text', 1), ('no source text', 1),
                            ('owned, skipped', 1)]:
        assert count in out
        line = next(line for line in out.splitlines() if count in line)
        assert expected == int(''.join(c for c in line.rsplit(':', 1)[1] if c.isdigit())), \
            f'{count}: expected {expected} in {line!r}'
    after = {p.read_bytes() for p in (env['root'] / 'jobs').glob('*.yaml')}
    assert before == after, 'the dry run wrote a byte'


def test_the_sample_names_the_jobs_it_would_fill(env, capsys):
    run(env)
    out = capsys.readouterr().out
    assert KEY_A in out and TEXT_A[:40] in out
    assert KEY_E in out
    assert 'IGNORED new text' not in out, 'the already-filled job is not in the plan'


# --- 4: APPLY fills only the empty ones ------------------------------------

def test_apply_fills_only_empty_descriptions(env):
    assert run(env, '--apply') == 0
    filled = read_back(env, env['jobs']['empty'])
    assert filled['description'] == TEXT_A
    ws = read_back(env, env['jobs']['whitespace'])
    assert ws['description'] == TEXT_E, 'a whitespace-only description counts as empty'


def test_apply_never_overwrites_an_existing_description(env):
    original = read_back(env, env['jobs']['has_text'])['description']
    assert run(env, '--apply') == 0
    after = read_back(env, env['jobs']['has_text'])
    assert after['description'] == original
    assert 'IGNORED new text' not in after['description']


def test_apply_leaves_the_no_source_and_outsider_jobs_alone(env):
    assert run(env, '--apply') == 0
    no_source = read_back(env, env['jobs']['no_source'])
    assert no_source['description'] == ''
    outsider = read_back(env, env['jobs']['outsider'])
    assert outsider['description'] == 'Untouched.'


def test_apply_never_touches_an_owned_record(env):
    assert run(env, '--apply') == 0
    owned = read_back(env, env['jobs']['owned'])
    assert owned['description'] == ''
    assert owned[vault.OWNER_FIELD] == env['user']['id']


# --- 5: provenance ----------------------------------------------------------

def test_a_filled_description_carries_feed_provenance(env):
    run(env, '--apply')
    filled = read_back(env, env['jobs']['empty'])
    assert filled['field_provenance']['description'] == 'feed'


def test_an_already_filled_job_is_left_byte_for_byte_alone(env):
    before = read_back(env, env['jobs']['has_text'])
    run(env, '--apply')
    kept = read_back(env, env['jobs']['has_text'])
    assert kept == before, 'the apply rewrote a job it should not touch'
    assert kept['description'] == 'The original posting text.'


# --- 6: idempotence ---------------------------------------------------------

def test_a_second_apply_fills_nothing_again(env, capsys):
    run(env, '--apply')
    capsys.readouterr()
    assert run(env, '--apply') == 0
    out = capsys.readouterr().out
    assert 'nothing to fill' in out
    line = next(line for line in out.splitlines() if 'already had text' in line)
    assert int(''.join(c for c in line.rsplit(':', 1)[1] if c.isdigit())) == 3


# --- matching is by source_id, through the generation's pool --------------

def test_a_job_whose_source_id_is_not_in_the_pool_is_not_matched(env, capsys):
    run(env)
    out = capsys.readouterr().out
    matched = next(line for line in out.splitlines() if line.startswith('matched'))
    assert int(matched.rsplit(':', 1)[1].strip()) == 5, \
        'the outsider job is not part of this generation'


# --- refusal shapes ---------------------------------------------------------

def test_no_vault_and_no_variable_is_a_refusal_not_a_guess(monkeypatch, env):
    monkeypatch.delenv('CAREEROS_VAULT', raising=False)
    with pytest.raises(SystemExit) as failure:
        backfill.main(['--descriptions', str(env['gen'] / 'descriptions.yaml'),
                       '--pool', str(env['gen'] / 'pool.yaml')])
    assert 'no vault given' in str(failure.value)


def test_a_vault_that_is_not_a_vault_is_refused(env, tmp_path):
    with pytest.raises(SystemExit) as failure:
        backfill.main(['--vault', str(tmp_path),
                       '--descriptions', str(env['gen'] / 'descriptions.yaml'),
                       '--pool', str(env['gen'] / 'pool.yaml')])
    assert 'does not look like a CareerOS vault' in str(failure.value)


def test_the_descriptions_reader_is_the_importer_s_strict_one(env, tmp_path):
    """A descriptions.yaml whose value is not text is refused loudly -- the
    importer's own reader, so a malformed file cannot smuggle a dict or a
    list into a job's description."""
    bad = tmp_path / 'descriptions.yaml'
    bad.write_text(yaml.safe_dump({'day': '2026-11-03',
                                   'descriptions': {KEY_A: {'nested': 'not text'}}}))
    with pytest.raises(SystemExit) as failure:
        backfill.main(['--vault', str(env['root']), '--descriptions', str(bad),
                       '--pool', str(env['gen'] / 'pool.yaml')])
    assert 'not text' in str(failure.value)


def test_careeros_vault_variable_is_honoured(monkeypatch, env, capsys):
    monkeypatch.setenv('CAREEROS_VAULT', str(env['root']))
    assert backfill.main(['--descriptions', str(env['gen'] / 'descriptions.yaml'),
                          '--pool', str(env['gen'] / 'pool.yaml')]) == 0
    assert 'DRY RUN' in capsys.readouterr().out
