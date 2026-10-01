"""YAML storage for a selected vault; no implicit access to the host vault."""
from datetime import date, datetime, timezone
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

# Chunk 3 records share the established tolerant reader and atomic writer.
STATUSES = ('new', 'interested', 'applied', 'interviewing', 'offer', 'rejected', 'closed', 'withdrawn')

def _records(root, kind):
    for path in sorted((Path(root) / kind).glob('*.yaml')):
        data = _read(path)
        if data:
            yield path, data

def list_jobs(root):
    return sorted((d for _, d in _records(root, 'jobs')), key=lambda d: str(d.get('added', '')), reverse=True)

def list_companies(root):
    return sorted((d for _, d in _records(root, 'companies')), key=lambda d: str(d.get('name', '')).casefold())

def _load(root, kind, identifier):
    return next((d for _, d in _records(root, kind) if d.get('id') == identifier), None)

def load_job(root, identifier):
    return _load(root, 'jobs', identifier)

def load_company(root, identifier):
    return _load(root, 'companies', identifier)

def _next(root, kind, prefix):
    numbers = [int(d['id'][len(prefix):]) for _, d in _records(root, kind) if re.fullmatch(prefix + r'\d+', str(d.get('id', '')))]
    return f'{prefix}{max(numbers, default=0)+1:03d}'

def next_job_id(root):
    return _next(root, 'jobs', 'JOB-')

def next_company_id(root):
    return _next(root, 'companies', 'CO-')

def _save_record(root, kind, data, identifier=None):
    from careeros.intake import check_url_format
    if not isinstance(data, dict):
        raise ValueError('Record must be an object.')
    existing = next(((p,d) for p,d in _records(root, kind) if d.get('id') == identifier), None) if identifier else None
    if identifier and not existing:
        raise KeyError(identifier)
    job = kind == 'jobs'
    defaults = (dict(company_id=None, title='', url='', original_url=None, source='', status='new', posted_date=None,
                     added=date.today().isoformat(), salary_info=False, salary_note='', location='', remote_ok=None,
                     notes='', enriched=False, employment_type='', valid_through='', custom={}) if job else
                dict(name='', name_source='owner', website=None, size=None, locations=[], sector=None, notes='', custom={}))
    result = defaults | (existing[1] if existing else {})
    result.update({k:v for k,v in data.items() if k in defaults})
    required = 'title' if job else 'name'
    for key, default in defaults.items():
        value = result[key]
        if isinstance(default, str) and not isinstance(value, str):
            raise ValueError(f'{key} must be text.')
    if not result[required].strip():
        raise ValueError(f'{required} is required.')
    for key in (('company_id', 'original_url') if job else ('website', 'size', 'sector')):
        if result[key] is not None and not isinstance(result[key], str):
            raise ValueError(f'{key} must be text or null.')
    if not isinstance(result['custom'], dict) or any(not isinstance(k,str) for k in result['custom']):
        raise ValueError('custom must be an object with text keys.')
    for key in (('url', 'original_url') if job else ('website',)):
        if result[key] is not None:
            check_url_format(result[key])
    if job:
        if result['status'] not in STATUSES:
            raise ValueError('Invalid job status.')
        for key in ('salary_info', 'enriched', 'remote_ok'):
            if type(result[key]) is not bool and not (key == 'remote_ok' and result[key] is None):
                raise ValueError(f'{key} must be boolean' + (' or null.' if key == 'remote_ok' else '.'))
        for key in ('posted_date', 'added'):
            value = result[key]
            if value is None and key == 'posted_date':
                continue
            try:
                result[key] = date.fromisoformat(str(value)).isoformat()
            except ValueError:
                raise ValueError(f'{key} must be YYYY-MM-DD.')
        if result['company_id'] and not load_company(root, result['company_id']):
            raise ValueError('Company not found.')
        if existing and result['status'] != existing[1].get('status'):
            result['status_changed'] = date.today().isoformat()
            append_event(result, 'status_changed', f"{existing[1].get('status')} -> {result['status']}")
            if (result['status'] in ('new', 'interested', 'applied', 'interviewing')
                    and result.get('watch', {}).get('watch_status') == 'gone'):
                result['watch'] = {}
        if not existing:
            append_event(result, 'created', 'Job created')
        if result.get('notes') and not (existing and existing[1].get('notes')):
            append_event(result, 'note_added', 'Notes added')
        if result.get('enriched') and not (existing and existing[1].get('enriched')):
            append_event(result, 'enriched', 'Posting enriched')
    elif not isinstance(result['locations'], list) or any(not isinstance(x,str) for x in result['locations']):
        raise ValueError('locations must be a list of text values.')
    if not job and result['name_source'] not in ('auto', 'owner'):
        raise ValueError('Invalid company name_source.')
    result['id'] = identifier or (next_job_id(root) if job else next_company_id(root))
    path = Path(root) / kind / f"{slugify(result[required])}-{result['id'].lower()}.yaml"
    _write(path, result)
    if existing and existing[0] != path:
        existing[0].unlink()
    return result

def save_job(root, data, identifier=None):
    return _save_record(root, 'jobs', data, identifier)

def save_company(root, data, identifier=None):
    return _save_record(root, 'companies', data, identifier)

def delete_job(root, identifier):
    for path, data in _records(root, 'jobs'):
        if data.get('id') == identifier:
            path.unlink()
            return True
    return False


def delete_company(root, identifier):
    for path, data in _records(root, 'companies'):
        if data.get('id') == identifier:
            path.unlink()
            return True
    raise ValueError('Company not found.')


# Lock the existing vault directory: no lock-file writes during dry runs.
# flock coordinates CLI/server processes; RLock coordinates server threads.
from threading import RLock
import fcntl
_LOCK = RLock()

class WriteLock:
    """Thread/process write lock; nesting on the same instance raises, never flocks twice."""
    def __init__(self, root, thread_lock=None):
        self.root = Path(root)
        self.depth = 0
        self.thread_lock = thread_lock if thread_lock is not None else _LOCK

    def __enter__(self):
        self.thread_lock.__enter__()
        if self.depth:
            self.thread_lock.__exit__(None, None, None)
            raise RuntimeError('WriteLock is not reentrant across flock; refactor to acquire once')
        self.fd = None
        try:
            self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except Exception:
            if self.fd is not None:
                os.close(self.fd)
            self.thread_lock.__exit__(None, None, None)
            raise
        self.depth = 1
        return self

    def __exit__(self, *args):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
        finally:
            self.depth = 0
            self.thread_lock.__exit__(*args)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def append_event(job, event, detail):
    entry = dict(ts=timestamp(), event=event, detail=detail)
    job['history'] = [*job.get('history', []), entry][-50:]
    return entry


def save_watch_result(root, job):
    """Internal watcher persistence; callers hold WriteLock. API cannot edit history."""
    path = next(p for p, d in _records(root, 'jobs') if d.get('id') == job['id'])
    _write(path, job)
