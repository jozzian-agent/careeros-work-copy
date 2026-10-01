"""YAML storage for a selected vault; no implicit access to the host vault."""
from datetime import date
from pathlib import Path
import re
import tempfile
import os
import yaml

LISTS = ('roles', 'must_haves', 'nice_to_haves', 'avoid')

def slugify(value):
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-') or 'position'

def blank_search():
    return dict(updated=None, **{key: [] for key in LISTS}, notes='')

def _read(path):
    """Load a vault YAML file. Missing, empty, corrupt, or non-mapping content
    returns None so one bad file can never take down a listing or a page."""
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) and data else None

def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def load_search(root):
    data = _read(Path(root) / 'search.yaml')
    return None if data is None else {**blank_search(), **data}

def save_search(root, data):
    if not isinstance(data, dict):
        raise ValueError('Criteria must be an object.')
    result = blank_search()
    for key in LISTS:
        values = data.get(key, [])
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            raise ValueError(f'{key} must be a list of text values.')
        result[key] = [x.strip() for x in values if x.strip()]
    if not isinstance(data.get('notes', ''), str):
        raise ValueError('Notes must be text.')
    result.update(notes=data.get('notes', ''), updated=date.today().isoformat())
    _write(Path(root) / 'search.yaml', result)
    return result

def _entries(root):
    for path in sorted((Path(root) / 'experiences').glob('*.yaml')):
        data = _read(path)
        if data:
            yield path, data

def list_experiences(root):
    return sorted((d for _, d in _entries(root)), key=lambda d: str(d.get('start', '')), reverse=True)

def load_experience(root, identifier):
    return next((d for _, d in _entries(root) if d.get('id') == identifier), None)

def next_id(root):
    numbers = [int(d['id'][4:]) for _, d in _entries(root) if re.fullmatch(r'EXP-\d+', str(d.get('id', '')))]
    return f'EXP-{max(numbers, default=0) + 1:03d}'

def validate_experience(data):
    if not isinstance(data, dict):
        raise ValueError('Position must be an object.')
    result = {}
    for key in ('company', 'title', 'start', 'end', 'location', 'summary', 'detail'):
        value = data.get(key, '')
        if not isinstance(value, str):
            raise ValueError(f'{key} must be text.')
        result[key] = value.strip()
    for key in ('company', 'title'):
        if not result[key]:
            raise ValueError(f'{key.title()} is required.')
    for key in ('start', 'end'):
        if key == 'end' and result[key] == 'present':
            continue
        if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', result[key]):
            raise ValueError(f'{key.title()} must be YYYY-MM' + (' or present.' if key == 'end' else '.'))
    if result['end'] != 'present' and result['end'] < result['start']:
        raise ValueError('End must not precede start.')
    for key in ('highlights', 'skills'):
        value = data.get(key, [])
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ValueError(f'{key} must be a list of text values.')
        result[key] = [x.strip() for x in value if x.strip()]
    led = data.get('people_led')
    if led is not None and (type(led) is not int or led < 0):
        raise ValueError('People led must be a nonnegative integer or null.')
    custom = data.get('custom', {})
    if not isinstance(custom, dict) or any(not isinstance(k, str) for k in custom):
        raise ValueError('Custom fields must be an object with text keys.')
    result.update(people_led=led, salary=None, custom=custom)
    return result

def save_experience(root, data, identifier=None):
    existing = next(((p, d) for p, d in _entries(root) if d.get('id') == identifier), None) if identifier else None
    if identifier and not existing:
        raise KeyError(identifier)
    result = validate_experience(data)
    result['id'] = identifier or next_id(root)
    # Compensation can only be changed by editing the file itself.
    result['salary'] = existing[1].get('salary') if existing else None
    filename = f"{slugify(result['company'] + ' ' + result['title'])}-{result['id'].lower()}.yaml"
    path = Path(root) / 'experiences' / filename
    _write(path, result)
    if existing and existing[0] != path:
        existing[0].unlink()
    return result

def delete_experience(root, identifier):
    for path, data in _entries(root):
        if data.get('id') == identifier:
            path.unlink()
            return True
    return False
