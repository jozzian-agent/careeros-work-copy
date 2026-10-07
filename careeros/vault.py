"""YAML storage for a selected vault; no implicit access to the host vault."""
from datetime import date, datetime, timezone
from pathlib import Path
import re
import tempfile
import os
import yaml

from careeros.sectors import known_section_codes, match_sectors

LISTS = ('roles', 'must_haves', 'nice_to_haves', 'avoid')
KINDS = ('employer', 'institution')
SIZE_CLASSES = ('micro', 'small', 'medium', 'large')
TAG_FACETS = ('skill/capability', 'skill/domain', 'function', 'experience-type', 'tool')
TAG_TOKEN_RE = re.compile(r'([a-z0-9/_-]+):([a-z0-9-]+)')

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

def default_tags():
    """Seed shape for tags.yaml (Section 2): five facets, with experience-type
    pre-populated since those three values are not owner-specific."""
    return {
        'facets': {
            'skill/capability': {'label': 'Capability', 'values': []},
            'skill/domain': {'label': 'Domain knowledge', 'values': []},
            'function': {'label': 'Job function', 'values': []},
            'experience-type': {'label': 'Experience type', 'values': [
                {'id': 'employment', 'label': 'Employment'},
                {'id': 'guest-lecture', 'label': 'Guest lecture / teaching'},
                {'id': 'volunteer', 'label': 'Volunteer'},
            ]},
            'tool': {'label': 'Tool', 'values': []},
        },
        'updated': date.today().isoformat(),
    }

def load_tags(root):
    data = _read(Path(root) / 'tags.yaml')
    seed = default_tags()
    if data is None:
        return seed
    facets = seed['facets']
    for key, value in (data.get('facets') or {}).items():
        facets[key] = value
    return {'facets': facets, 'updated': data.get('updated', seed['updated'])}

def save_tags(root, data):
    if not isinstance(data, dict) or not isinstance(data.get('facets'), dict):
        raise ValueError('Tags must include a facets object.')
    result = dict(data, updated=date.today().isoformat())
    _write(Path(root) / 'tags.yaml', result)
    return result

def split_tag_id(token):
    """Parse a facet:id token by splitting on the first colon only, per the
    transport rule: facet keys may contain a slash but never a colon, and
    value ids contain neither, so this split is always unambiguous."""
    if not isinstance(token, str):
        raise ValueError('Tag must be text.')
    match = re.fullmatch(TAG_TOKEN_RE, token)
    if not match:
        raise ValueError(f'"{token}" is not a valid facet:id tag.')
    return match.group(1), match.group(2)

def validate_tags(root, tokens, proposed=()):
    """Tags are open-with-review (decision 10): the facet list is fixed, so
    an unknown facet is always rejected, and an unknown value within a known
    facet is also rejected during ordinary validation, since silently
    registering it would turn every typo into a permanent registry entry.
    New values enter tags.yaml only through the explicit proposal flow: the
    caller passes the proposed tokens (facet:id strings the owner actively
    proposed in this same request), and only those may be registered. The
    function facet stays closed even to proposals here, since a proposed
    function value is governed by Section 4's own flow."""
    if not isinstance(tokens, list) or any(not isinstance(t, str) for t in tokens):
        raise ValueError('tags must be a list of text values.')
    proposed = set(proposed or ())
    tags = load_tags(root)
    result, dirty = [], False
    for token in tokens:
        facet, value_id = split_tag_id(token)
        if facet not in tags['facets']:
            raise ValueError(f'Unknown tag facet "{facet}".')
        values = tags['facets'][facet]['values']
        if not any(v['id'] == value_id for v in values):
            if facet == 'function' or f'{facet}:{value_id}' not in proposed:
                raise ValueError(f'Unknown tag id "{value_id}" in facet "{facet}". Propose it explicitly to add it.')
            values.append({'id': value_id, 'label': value_id.replace('-', ' ').title()})
            dirty = True
        result.append(f'{facet}:{value_id}')
    if dirty:
        save_tags(root, tags)
    return list(dict.fromkeys(result))

def known_function_ids(root):
    tags = load_tags(root)
    return {value['id'] for value in tags['facets'].get('function', {}).get('values', [])}

def function_facet_options(root):
    """Known function entries, for use as LLM prompt context (Section 4)."""
    tags = load_tags(root)
    return tags['facets'].get('function', {}).get('values', [])

def tag_label_map(root):
    """facet:id token -> {'label', 'local'} for every known tag value, so a
    display path resolves the canonical registry label instead of
    reformatting the slug portion of the id. 'local' marks a function-facet
    value with no corresponding ESCO concept (decision 25), so a renderer
    can show the local-extension marker next to it."""
    tags = load_tags(root)
    labels = {}
    for facet, info in tags['facets'].items():
        for value in info.get('values', []):
            labels[f"{facet}:{value['id']}"] = {
                'label': value.get('label') or value['id'],
                'local': facet == 'function' and value.get('source') == 'local-extension',
            }
    return labels

def function_label_map(root):
    """Bare function id -> {'label', 'local'}, the shape job.function values
    are stored in (unlike experience tags, function ids on a job are not
    facet-qualified)."""
    return {value['id']: {'label': value.get('label') or value['id'],
                          'local': value.get('source') == 'local-extension'}
            for value in function_facet_options(root)}

_ESCO_SEED_PATH = Path(__file__).resolve().parent / 'data' / 'esco_occupations.yaml'

def seed_function_facet(root):
    """One-time seed (Section 4 engineering items 1 and 3): populate
    tags.yaml's function facet from the curated esco_occupations.yaml
    bulk-export. esco_occupations.yaml is read here only as an import
    source and is never consulted again at runtime (decision 24); after
    this call, tags.yaml alone is authoritative.

    Only an entry whose esco_uri is actually present is added as an
    ESCO-backed value; the review that produced this seed file could not
    confirm a live esco_uri for every entry, so an entry without one is not
    yet a verified ESCO concept and is added as a local extension instead
    (decision 25), with isco cleared rather than left to imply a roll-up
    guarantee the entry has not earned.

    Explicit and idempotent, like migrate_skills_to_tags and
    backfill_company_kind: never runs automatically, and never overwrites
    or duplicates a function id already present in tags.yaml."""
    source = yaml.safe_load(_ESCO_SEED_PATH.read_text())
    tags = load_tags(root)
    values = tags['facets']['function']['values']
    existing_ids = {value['id'] for value in values}
    added = []
    for entry in source.get('occupations', []):
        if entry['id'] in existing_ids:
            continue
        verified = bool(entry.get('esco_uri'))
        seeded = {'id': entry['id'], 'label': entry['label'],
                  'isco': entry.get('isco') if verified else None,
                  'esco_uri': entry.get('esco_uri') if verified else None}
        if entry.get('label_de'):
            seeded['label_de'] = entry['label_de']
        if entry.get('keywords'):
            seeded['keywords'] = list(entry['keywords'])
        if not verified:
            seeded['source'] = 'local-extension'
        values.append(seeded)
        added.append(entry['id'])
    if added:
        save_tags(root, tags)
    return added

TOOL_KEYWORDS = ('python', 'sql', 'aws', 'javascript', 'django', 'postgresql',
                  'excel', 'figma', 'docker', 'kubernetes', 'typescript', 'java')

def legacy_skill_to_tag_id(skill):
    """Default mapping for the one-time skills-to-tags migration and the
    overlap-window translation: recognized tool names land in the tool
    facet, everything else lands in skill/capability as a reasonable
    default (per the document, most one-off tags land in capability or
    domain; a bulk migration cannot reliably tell those two apart without
    owner review, so capability is the safe default for the auto-created
    entry)."""
    slug = slugify(skill.casefold()) or 'skill'
    facet = 'tool' if skill.strip().casefold() in TOOL_KEYWORDS else 'skill/capability'
    return f'{facet}:{slug}'

def migrate_skills_to_tags(root):
    """One-time migration (Section 2 engineering item 3): map existing free
    skills values into tags.yaml entries plus rewritten experience records.
    Only touches experiences that have skills but no tags yet."""
    migrated = []
    for path, data in _entries(root):
        if data.get('skills') and not data.get('tags'):
            tokens = [legacy_skill_to_tag_id(skill) for skill in data['skills']]
            # The migration itself is the owner-approved proposal event for
            # these tokens: pass them as proposed so unknown values register
            # rather than failing the now-closed ordinary validation.
            data['tags'] = validate_tags(root, tokens, proposed=tokens)
            _write(path, data)
            migrated.append(data['id'])
    return migrated

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

def validate_experience(data, existing=None):
    """Merge onto ``existing`` (the stored record, or {} for a new one) the
    same way _save_record already merges for jobs/companies: a key absent
    from the incoming payload leaves the existing value untouched rather than
    being reset to a blank default. This covers highlights/skills/custom too,
    not only the new company_id/tags fields, per decision 5."""
    if not isinstance(data, dict):
        raise ValueError('Position must be an object.')
    defaults = dict(company='', title='', start='', end='', location='', summary='', detail='',
                     highlights=[], skills=[], tags=[], people_led=None, custom={}, company_id=None)
    result = defaults | (existing or {})
    result.update({k: v for k, v in data.items() if k in defaults})
    for key in ('company', 'title', 'start', 'end', 'location', 'summary', 'detail'):
        if not isinstance(result[key], str):
            raise ValueError(f'{key} must be text.')
        result[key] = result[key].strip()
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
    for key in ('highlights', 'skills', 'tags'):
        value = result[key]
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ValueError(f'{key} must be a list of text values.')
        result[key] = [x.strip() for x in value if x.strip()]
    led = result['people_led']
    if led is not None and (type(led) is not int or led < 0):
        raise ValueError('People led must be a nonnegative integer or null.')
    custom = result['custom']
    if not isinstance(custom, dict) or any(not isinstance(k, str) for k in custom):
        raise ValueError('Custom fields must be an object with text keys.')
    result['custom'] = custom
    if result['company_id'] is not None and not isinstance(result['company_id'], str):
        raise ValueError('company_id must be text or null.')
    return result

def save_experience(root, data, identifier=None):
    existing = next(((p, d) for p, d in _entries(root) if d.get('id') == identifier), None) if identifier else None
    if identifier and not existing:
        raise KeyError(identifier)
    result = validate_experience(data, existing[1] if existing else None)
    if result['company_id'] is not None and not load_company(root, result['company_id']):
        raise ValueError('Company not found.')
    # Unlinking through the ordinary PUT must freeze the currently resolved
    # company label into the free-text field, exactly like the dedicated
    # link-company endpoint does, so clients cannot bypass the freeze by
    # sending company_id=null through the generic update route.
    if existing and existing[1].get('company_id') and result['company_id'] is None:
        linked = load_company(root, existing[1]['company_id'])
        if linked:
            result['company'] = linked['name']
    # Legacy skills-only payload during the Section 2 overlap window: a
    # client that never sends tags must not appear to wipe tags that were
    # never sent, but one that sends only skills is translated rather than
    # silently leaving tags empty. Decision 6 requires this translation on
    # every such legacy payload, not only the first one: gating it on the
    # stored tags being empty would let an owner who already has tags set
    # from the new UI desync them from a later legacy skills-only edit, since
    # that edit would then silently stop updating tags at all.
    if 'skills' in data and 'tags' not in data:
        result['tags'] = [legacy_skill_to_tag_id(skill) for skill in result['skills']]
        # The legacy translation is itself an owner-approved proposal event
        # (same rule as migrate_skills_to_tags): the translated ids may
        # register into the registry without a separate proposal payload.
        data = dict(data)
        prior_raw = data.get('proposed_tags')
        prior = [t for t in prior_raw if isinstance(t, str)] if isinstance(prior_raw, list) else []
        tags_raw = result.get('tags') or []
        translated = [t for t in tags_raw if isinstance(t, str)]
        data['proposed_tags'] = list(dict.fromkeys(prior + translated))
    proposed = data.get('proposed_tags')
    if proposed is None:
        proposed = []
    if not isinstance(proposed, list) or any(not isinstance(t, str) for t in proposed):
        raise ValueError('proposed_tags must be a list of facet:id values.')
    result['tags'] = validate_tags(root, result['tags'], proposed=proposed)
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
            if kind == 'jobs':
                for key in ('sectors', 'industries', 'function'):
                    if data.get(key) is None:
                        data[key] = []
            if kind == 'companies':
                for key in ('sectors', 'review_flags'):
                    if data.get(key) is None:
                        data[key] = []
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

def _save_record(root, kind, data, identifier=None, *, correction_detail=None, history_event=None):
    from careeros.intake import check_url_format
    if not isinstance(data, dict):
        raise ValueError('Record must be an object.')
    existing = next(((p,d) for p,d in _records(root, kind) if d.get('id') == identifier), None) if identifier else None
    if identifier and not existing:
        raise KeyError(identifier)
    job = kind == 'jobs'
    defaults = (dict(company_id=None, title='', url='', original_url=None, source='', status='new', posted_date=None,
                     added=date.today().isoformat(), salary_info=False, salary_note='', location='', remote_ok=None,
                     notes='', enriched=False, employment_type='', valid_through='', custom={},
                     description='', company='', seniority='', keywords=[], summary='', contact_email='',
                     ingest_source='', sector=None, sectors=[], industry=None, industries=[],
                     background='', skills=[], certifications=[], responsibilities=[], summary_source='', refresh='skipped',
                     employee_count=None, function=[], tags=[]) if job else
                dict(name='', name_source='owner', website=None, size=None, locations=[], sector=None,
                     contact_email='', notes='', custom={}, enrichment={},
                     kind='employer', sectors=[], size_range=None, size_class=None, review_flags=[]))
    result = defaults | (existing[1] if existing else {})
    result.update({k:v for k,v in data.items() if k in defaults})
    required = 'title' if job else 'name'
    for key, default in defaults.items():
        value = result[key]
        if isinstance(default, str) and not isinstance(value, str):
            raise ValueError(f'{key} must be text.')
    if not result[required].strip():
        raise ValueError(f'{required} is required.')
    for key in (('company_id', 'original_url', 'sector', 'industry') if job else
                ('website', 'size', 'sector', 'size_range')):
        if result[key] is not None and not isinstance(result[key], str):
            raise ValueError(f'{key} must be text or null.')
    if not isinstance(result['custom'], dict) or any(not isinstance(k,str) for k in result['custom']):
        raise ValueError('custom must be an object with text keys.')
    for key in (('url', 'original_url') if job else ('website',)):
        if result[key] is not None:
            check_url_format(result[key])
    if job:
        for key in ('sectors', 'industries'):
            if result[key] is None:
                result[key] = []
            if not isinstance(result[key], list) or any(not isinstance(x, str) for x in result[key]):
                raise ValueError(f'{key} must be a list of text values.')
        if result['ingest_source'] not in ('', 'llm', 'heuristic'):
            raise ValueError('Invalid ingest_source.')
        if result['summary_source'] not in ('', 'ai'):
            raise ValueError('Invalid summary_source.')
        for key in ('keywords', 'skills', 'certifications', 'responsibilities'):
            if not isinstance(result[key], list) or any(not isinstance(x, str) for x in result[key]):
                raise ValueError(f'{key} must be a list of text values.')
        if result['employee_count'] is not None and (type(result['employee_count']) is not int or result['employee_count'] < 0):
            raise ValueError('employee_count must be a nonnegative integer or null.')
        if not isinstance(result['function'], list) or any(not isinstance(x, str) for x in result['function']):
            raise ValueError('function must be a list of text values.')
        # A typo in a directly owner-edited function id must surface as an
        # error; LLM-sourced writes are expected to have already dropped any
        # unknown id before reaching this point (see server.py).
        known_functions = known_function_ids(root)
        unknown = [value for value in result['function'] if value not in known_functions]
        if unknown:
            raise ValueError(f'Unknown function id(s): {", ".join(unknown)}')
        # Job tags use the same controlled-vocabulary flow as experiences
        # (Section 2): closed registry, new values only via an explicit
        # proposal payload in the same request.
        proposed = data.get('proposed_tags') or []
        if not isinstance(proposed, list) or any(not isinstance(t, str) for t in proposed):
            raise ValueError('proposed_tags must be a list of facet:id values.')
        result['tags'] = validate_tags(root, result['tags'], proposed=proposed)
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
        if correction_detail:
            append_event(result, 'company_correction', correction_detail)
        if history_event:
            append_event(result, *history_event)
        if not existing:
            append_event(result, 'created', 'Job created')
        if result.get('notes') and not (existing and existing[1].get('notes')):
            append_event(result, 'note_added', 'Notes added')
        if result.get('enriched') and not (existing and existing[1].get('enriched')):
            append_event(result, 'enriched', 'Posting enriched')
        if result.get('ingest_source') == 'llm' and not (existing and existing[1].get('ingest_source') == 'llm'):
            append_event(result, 'llm_enriched', 'LLM extraction completed')
    elif not isinstance(result['locations'], list) or any(not isinstance(x,str) for x in result['locations']):
        raise ValueError('locations must be a list of text values.')
    if not job:
        for key in ('sectors', 'review_flags'):
            if result[key] is None:
                result[key] = []
            if not isinstance(result[key], list) or any(not isinstance(x, str) for x in result[key]):
                raise ValueError(f'{key} must be a list of text values.')
        if result['kind'] not in KINDS:
            raise ValueError('Invalid company kind.')
        unknown_sections = [code for code in result['sectors'] if code not in known_section_codes()]
        if unknown_sections:
            raise ValueError(f'Unknown ISIC section code(s): {", ".join(unknown_sections)}')
        if result['size_class'] is not None and result['size_class'] not in SIZE_CLASSES:
            raise ValueError('Invalid company size_class.')
    if not job and 'enrichment' in data:
        validate_enrichment(data['enrichment'])
    if not job and result['name_source'] not in ('auto', 'owner'):
        raise ValueError('Invalid company name_source.')
    result['id'] = identifier or (next_job_id(root) if job else next_company_id(root))
    path = Path(root) / kind / f"{slugify(result[required])}-{result['id'].lower()}.yaml"
    _write(path, result)
    if existing and existing[0] != path:
        existing[0].unlink()
    return result, existing[1] if existing else None

def save_job(root, data, identifier=None, *, correction_detail=None, history_event=None):
    from careeros.enrich import regenerate_company
    result, previous = _save_record(root, 'jobs', data, identifier, correction_detail=correction_detail,
                                     history_event=history_event)
    from careeros.ingest import is_valid_contact_email
    if is_valid_contact_email(result.get('contact_email')) and result.get('company_id'):
        company = load_company(root, result['company_id'])
        if company and not company.get('contact_email'):
            save_company(root, {'contact_email': result['contact_email']}, company['id'])
    for company_id in sorted({c for c in (result.get('company_id'),
                                          previous.get('company_id') if previous else None) if c}):
        try:
            regenerate_company(root, company_id)
        except Exception:
            # Derived data failure must not mask a persisted job save.
            pass
    return result

def _translate_legacy_company_fields(root, data, identifier=None):
    """Translate legacy sector/size into sectors/size_range on the raw
    incoming payload, before _save_record validates and persists it, per
    decision 6: the new-shape field always wins when a payload carries both.
    A bucket-only legacy size string yields size_range but never a confident
    size_class, since that needs a raw employee count this payload lacks.
    The new-shape value already stored on the record wins too: a legacy
    signal must never clobber owner-set or previously derived sectors,
    size_range, or size_class."""
    if not isinstance(data, dict):
        return data
    stored = load_company(root, identifier) if identifier else None
    data = dict(data)
    new_sectors = 'sectors' in data or (stored or {}).get('sectors')
    if 'sector' in data and not new_sectors and isinstance(data.get('sector'), str) and data['sector']:
        matched = match_sectors(data['sector'])
        if matched:
            data['sectors'] = matched
    new_size = 'size_range' in data or (stored or {}).get('size_range')
    if 'size' in data and not new_size and isinstance(data.get('size'), str) and data['size']:
        data['size_range'] = data['size']
    return data

def save_company(root, data, identifier=None):
    data = _translate_legacy_company_fields(root, data, identifier)
    result, _ = _save_record(root, 'companies', data, identifier)
    return result

def backfill_company_kind(root):
    """One-time migration (Section 1): every company record gains
    kind: employer as a filled-empty-only default. Explicit, callable once;
    never runs implicitly."""
    updated = []
    for _, data in _records(root, 'companies'):
        if not data.get('kind'):
            save_company(root, {'kind': 'employer'}, data['id'])
            updated.append(data['id'])
    return updated

def delete_job(root, identifier):
    from careeros.enrich import regenerate_company
    for path, data in _records(root, 'jobs'):
        if data.get('id') == identifier:
            path.unlink()
            if data.get('company_id'):
                try:
                    regenerate_company(root, data['company_id'])
                except Exception:
                    # The deletion succeeded; derived data can be rebuilt later.
                    pass
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
    if job.get('company_id'):
        from careeros.enrich import regenerate_company
        regenerate_company(root, job['company_id'])


def validate_enrichment(block):
    """Validate known derived fields while retaining future extension keys."""
    if not isinstance(block, dict):
        raise ValueError('enrichment must be an object.')
    for key in ('sectors', 'locations_seen', 'top_keywords'):
        if key in block and (not isinstance(block[key], list) or
                             any(not isinstance(v, str) for v in block[key])):
            raise ValueError(f'enrichment.{key} must be a list of text values.')
    if 'remote_friendly' in block and type(block['remote_friendly']) is not bool:
        raise ValueError('enrichment.remote_friendly must be boolean.')
    for key in ('seniority_range', 'hiring_activity'):
        if key in block and not isinstance(block[key], dict):
            raise ValueError(f'enrichment.{key} must be an object.')
    for key in ('min', 'max'):
        value = block.get('seniority_range', {}).get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f'enrichment.seniority_range.{key} must be text or null.')
    activity = block.get('hiring_activity', {})
    if 'count' in activity and (type(activity['count']) is not int or activity['count'] < 0):
        raise ValueError('enrichment.hiring_activity.count must be a nonnegative integer.')
    value = activity.get('most_recent_posted_date')
    if value is not None:
        try:
            if not isinstance(value, (str, date)):
                raise ValueError
            date.fromisoformat(str(value))
        except ValueError:
            raise ValueError('enrichment.hiring_activity.most_recent_posted_date must be YYYY-MM-DD or null.')
