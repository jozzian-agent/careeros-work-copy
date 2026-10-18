"""YAML storage for a selected vault; no implicit access to the host vault."""
from datetime import date, datetime, timezone
from pathlib import Path
from typing import NamedTuple
import logging
import re
import sys
import tempfile
import os
import yaml
import uuid

from org_intake.classify import known_section_codes, match_sectors
from org_intake.url import normalize_url
from careeros import taxonomy
from careeros.intake import posting_ats

_logger = logging.getLogger(__name__)

LISTS = ('roles', 'must_haves', 'nice_to_haves', 'avoid')
KINDS = ('employer', 'institution')
# The one size scale (owner decision 2026-10-15), read from the taxonomy
# code list rather than retyped here (CAREER-55): the same vocabulary used
# to live in three places -- this tuple, `web.pages.taxonomy`'s own
# SIZE_CLASS_ORDER and the capability's `classify.SIZE_CLASSES` -- and two
# of the three were orderings of the same list. The capability keeps its
# own constant, because a capability imports nothing from the product;
# `tests/test_taxonomy.py` pins the two against each other so they cannot
# drift. `xl` joined the list on 2026-10-17 (owner decision D3).
SIZE_CLASSES = taxonomy.codes('company_size')
COMPANY_LINK_REASONS = ('ats_tenant', 'domain', 'name_exact', 'fuzzy_name',
                        'employer_differs_from_tenant', 'shared_tenant', 'new_company', 'manual',
                        'ambiguous_exact')
IDENTIFIER_TYPES = ('domain', 'ats_tenant', 'wikidata', 'name_variant')
SOURCE_KINDS = ('careers_page', 'ats_feed')
FIELD_STATUS_VALUES = ('pending', 'done', 'failed', 'not_evidenced')
# _save_record's history backstop writes the new state itself as the event
# type, so careeros.history.REGISTRY must name every member of this tuple.
INGEST_STATES = ('stub', 'fetched', 'complete', 'fetch_failed', 'extract_failed')
POSTING_QUALITY_VALUES = ('thin', 'ok', 'rich')
# CAREER-36: where a job's own AI reading stands right now. The AI call
# runs off the request path, so the job record is the only place a caller
# can read the outcome from, and these are the words it reads.
#
# 'absent' is deliberately not in this tuple: a record that never tried
# stores no ai_status at all, which is every record written before this
# field existed. ai_status() below is what turns that absence into the
# word, so no migration has to stamp a value on a vault full of records
# that never queued anything.
AI_STATUSES = ('queued', 'running', 'done', 'failed')
AI_ABSENT = 'absent'
# The two statuses that say work is still owed. A process that stops holds
# the only copy of its queue, so a record left in one of these is a record
# nothing will ever finish; recover_interrupted_ai settles them at startup.
AI_UNSETTLED = ('queued', 'running')
AI_RESTART_ERROR = 'interrupted by server restart'
# How a stored description_structured block was produced. 'user' is the
# owner having written it in Edit job, which is a producer the block gained
# in package 2's fix round: the Description row of the extraction popup
# sends the owner to Edit job when the posting yielded no block, so Edit
# job creates one, and the other three values all claim a machine made it.
DESCRIPTION_STRUCTURED_METHODS = ('llm', 'heuristic', 'raw', 'user')
# Package 2: the groups a stored requirement can belong to, and how much
# the posting insists on it. The vocabulary is fixed by owner decision, so
# a requirement the extractor cannot place lands in 'skills' rather than
# inventing a sixth group (see careeros.ingest.requirement_groups). The
# owner-facing labels are the front end's (Education, Experience, Skills,
# Languages, Certifications); what a record stores is the id.
REQUIREMENT_GROUPS = ('education', 'experience', 'skills', 'languages', 'certifications')
REQUIREMENT_LEVELS = ('must', 'nice')
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


class FunctionSeedResult(NamedTuple):
    """What one seed run did: ids newly added, and ids already present
    whose ESCO identity or keywords it brought up to date."""
    added: list
    updated: list


def _seed_is_esco_backed(entry):
    """Whether a curated seed entry cites a real ESCO concept. An entry
    marked `local: true` never counts, even if someone fills in an
    esco_uri beside the marker: decision 25 makes a local extension an
    owner label with no ESCO parent, so the marker wins over the field
    and the contradiction cannot quietly become a roll-up claim."""
    return bool(entry.get('esco_uri')) and not entry.get('local')


def seed_function_facet(root):
    """Seed and re-seed tags.yaml's function facet from the curated
    esco_occupations.yaml bulk-export (Section 4 engineering items 1 and
    3). esco_occupations.yaml is read here only as an import source and is
    never consulted again at runtime (decision 24); after this call,
    tags.yaml alone is authoritative -- including for the extraction
    prompt, which is built from the facet (`function_facet_options`) and
    not from the seed file, so a change that reaches no vault reaches no
    reading either.

    Only an entry whose esco_uri is present, and which is not marked as a
    local extension, is stored as an ESCO-backed value. An entry without
    one is not a verified ESCO concept and is stored as a local extension
    instead (decision 25), with isco cleared rather than left to imply a
    roll-up guarantee the entry has not earned.

    Re-running is not a no-op (2026-10-16). Until then every id already in
    the facet was skipped, which made the documented way to confirm an
    entry -- fill in its esco_uri and run the seed again -- do nothing at
    all. A re-run now confirms or updates, per id already present:

      * `esco_uri` and `isco`, and the local-extension marker with them,
        because those three are one statement about which ESCO concept an
        entry is, and the import source is where that statement is made.
        An entry the source marks local has all three cleared the same
        way, so a label that loses its concept cannot keep the code.
      * `keywords`, merged: every keyword the source adds is appended and
        none is removed, so an anchor the owner added by hand survives and
        a new one still reaches the prompt.

    Labels are never touched -- `label` and `label_de` are the owner's
    wording, and an entry the source has nothing new to say about is left
    byte-for-byte alone, so a second run in a row reports nothing. An
    entry whose source row is still unverified (no esco_uri and no local
    marker) but which carries a stored esco_uri is left alone too: that
    value can only have come from someone confirming the concept in the
    vault itself, and the import source does not know better.

    Explicit, like migrate_skills_to_tags and backfill_company_kind: it
    never runs automatically, and never duplicates an id."""
    source = yaml.safe_load(_ESCO_SEED_PATH.read_text())
    tags = load_tags(root)
    values = tags['facets']['function']['values']
    stored = {value['id']: value for value in values}
    added, updated = [], []
    for entry in source.get('occupations', []):
        verified = _seed_is_esco_backed(entry)
        current = stored.get(entry['id'])
        if current is None:
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
            stored[entry['id']] = seeded
            added.append(entry['id'])
        elif _update_seeded_function_value(current, entry, verified):
            updated.append(entry['id'])
    if added or updated:
        save_tags(root, tags)
    return FunctionSeedResult(added, updated)


def _update_seeded_function_value(current, entry, verified):
    """Bring one already-stored facet value up to date with its curated
    source row. Returns whether anything changed, so an unchanged run
    writes no file. See seed_function_facet for the rules."""
    before = dict(current)
    # The identity statement: an ESCO-backed row asserts the concept and
    # its code; an explicitly local row asserts there is none. A row that
    # is merely still unverified asserts nothing, so it changes nothing.
    if verified:
        current['esco_uri'] = entry['esco_uri']
        current['isco'] = entry.get('isco')
        current.pop('source', None)
    elif entry.get('local') or not current.get('esco_uri'):
        current['esco_uri'] = None
        current['isco'] = None
        current['source'] = 'local-extension'
    keywords = list(current.get('keywords') or [])
    keywords += [word for word in (entry.get('keywords') or []) if word not in keywords]
    if keywords:
        current['keywords'] = keywords
    return current != before

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
    # Same rule as _save_record's own allowlist, and the same reason for
    # saying so out loud (CAREER-30): a payload key an experience does
    # not store changes nothing, and used to say so nowhere.
    unknown = sorted(key for key in data if key not in defaults and key != 'id')
    if unknown:
        _logger.warning('experiences write %s: dropped %d payload key(s) this record does not store: %s',
                        (existing or {}).get('id') or data.get('id') or 'new', len(unknown), ', '.join(unknown))
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
# The owner's status list (decision D7, 2026-10-15), in the order a job
# moves through it, which is also the order the board shows. Won means the
# owner got the job and Stopped means they quit pursuing it without a
# rejection, replacing the former Withdrawn. There is no Closed status: a
# posting that is gone is a fact about the posting rather than the owner
# decision, so it is the `closed` flag on the record instead.
STATUSES = ('new', 'interested', 'applied', 'interviewing', 'offer', 'won', 'rejected', 'stopped')

# The owner-facing name of every status, for any surface that shows one:
# the board payload, the status select and the history labels all read
# these words from here rather than reformatting the stored id.
STATUS_LABELS = {'new': 'New', 'interested': 'Interested', 'applied': 'Applied',
                 'interviewing': 'Interviewing', 'offer': 'Offer', 'won': 'Won',
                 'rejected': 'Rejected', 'stopped': 'Stopped'}

# The three statuses that end a job: it is no longer something the owner
# can still pursue. Lives here, beside the status vocabulary it is drawn
# from, so every reader of "is this job still open" (the board split, the
# Companies directory count and the filters built on it) shares one
# definition instead of repeating a status tuple of its own.
ENDED_STATUSES = ('won', 'rejected', 'stopped')

# Open means not ended, which is why it is derived here and never typed
# out a second time: the two lists cannot drift apart.
OPEN_STATUSES = tuple(status for status in STATUSES if status not in ENDED_STATUSES)

# The reasons the ending popup offers for the two statuses that have them
# (D7). A reason is always optional, is picked from these words rather
# than typed, and is stored verbatim as the string the owner picked, so no
# second label map has to agree with it. Free text the owner adds beside a
# reason is a dated note on the job (END_NOTE_TITLE), never a second
# stored field. Won has no suggestions: there is nothing to explain about
# getting the job.
STOPPED_REASONS = ('Not interested anymore', 'Salary or conditions', 'Location or commute',
                   'Took another offer', 'Withdrew application', 'Posting closed', 'No response')
REJECTED_REASONS = ('No reason given', 'After interview', 'Experience did not match',
                    'Position filled')
END_REASONS = {'stopped': STOPPED_REASONS, 'rejected': REJECTED_REASONS}
END_REASON_VALUES = frozenset(STOPPED_REASONS + REJECTED_REASONS)

# The title the free-text half of an ending reason is saved under. The
# notes list shows titles, so the free text needs one, and it is decided
# here with the rest of the ending vocabulary rather than by whichever
# surface opens the popup.
END_NOTE_TITLE = 'Why this ended'

def is_open_job(job):
    """True while a job is still open, per ENDED_STATUSES. A record with
    no status at all counts as open: the default status is `new`."""
    return job.get('status') not in ENDED_STATUSES

def ai_status(record):
    """The AI reading state of one record, as a word (CAREER-36).

    A record with no stored ai_status, or one carrying a value this
    vocabulary does not know, reads as AI_ABSENT: never tried. That is
    what keeps every record written before this field from looking like a
    reading that is somehow in flight.
    """
    value = (record or {}).get('ai_status')
    return value if value in AI_STATUSES else AI_ABSENT

def ai_queued():
    """The transition a record takes when its reading is enqueued.

    Each of these four builders returns the keys it is responsible for and
    no others, so a caller hands one straight to save_job/save_company and
    the merge keeps whatever the record already holds. Only the two that
    begin a run clear ai_error and the timestamps: a new attempt must not
    show the previous attempt's reason or the moment it ended.
    """
    return {'ai_status': 'queued', 'ai_error': None, 'ai_started': None, 'ai_finished': None}

def ai_running():
    return {'ai_status': 'running', 'ai_error': None, 'ai_started': timestamp(), 'ai_finished': None}

def ai_done():
    """Deliberately leaves ai_started alone, so a finished run still says
    when it began."""
    return {'ai_status': 'done', 'ai_error': None, 'ai_finished': timestamp()}

def ai_failed(reason):
    """A failed run always carries a reason: a failure with nothing to
    show for it is the silent unknown the product rules forbid."""
    text = str(reason or '').strip()
    return {'ai_status': 'failed', 'ai_error': text or 'Enrichment failed.',
            'ai_finished': timestamp()}

def recover_interrupted_ai(root):
    """Settle every job a stopped process left mid-reading (CAREER-36).

    The queue lives in the process, so a restart takes it with it: a job
    still reading queued or running has nothing left that could finish
    it. Each one becomes failed with AI_RESTART_ERROR, which is a visible
    state with a reason and a Retry rather than a spinner that never
    resolves. Returns the job ids it changed, in the order it changed
    them.

    Jobs only: the reading status is a field of the job record, and the
    company enrichment endpoint records none, so there is no company
    state here that could be left unsettled.

    Runs at startup beside the additive field migrations, and is
    idempotent for the same reason they are: a second pass finds nothing
    unsettled left to settle.

    Each record is isolated the same way the startup field migrations
    isolate theirs (see migrate_job_fields): this runs while the app is
    being built, so one record whose save is refused -- a legacy status
    this vocabulary retired, any other shape written before a validation
    rule existed -- must be reported to stderr and skipped, never allowed
    to take the whole sweep, and with it the server's own startup, down.
    """
    changed = []
    # Materialized before the first save: a save can rewrite the file the
    # generator is walking.
    for record in [data for _, data in _records(root, 'jobs')]:
        if record.get('ai_status') not in AI_UNSETTLED or not record.get('id'):
            continue
        try:
            save_job(root, ai_failed(AI_RESTART_ERROR), record['id'])
        except Exception as error:
            print(f'recover_interrupted_ai: skipped {record["id"]} '
                  f'({type(error).__name__}: {error})', file=sys.stderr)
            continue
        changed.append(record['id'])
    return changed

def _records(root, kind):
    for path in sorted((Path(root) / kind).glob('*.yaml')):
        data = _read(path)
        if data:
            if kind == 'jobs':
                for key in ('sectors', 'industries', 'function'):
                    if data.get(key) is None:
                        data[key] = []
            if kind == 'companies':
                for key in ('sectors', 'review_flags', 'identifiers', 'sources'):
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

# One owner note: a title, a body, and when it was written and last
# changed. Notes live under `note_list` on the job or company record they
# belong to, so a note's association IS containment and needs no separate
# index or back-reference. Ids are generated here and never accepted from
# a client.
NOTE_FIELDS = ('id', 'title', 'body', 'created', 'updated')

# The title a note migrated out of the legacy free-text `notes` string
# gets. That field never had one, and a list of notes shows titles.
LEGACY_NOTE_TITLE = 'Note'

# The id that migrated note is addressable under. It has to be the same on
# every read, or an edit the owner starts on one page load would address
# nothing by the time they save it, so it cannot be generated per read.
LEGACY_NOTE_ID = 'legacy'


def new_note(title, body):
    """One note, stamped now.

    A note with no title is rejected: the list shows titles, so a note
    without one is a row the owner cannot tell from the next.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError('A note needs a title.')
    if not isinstance(body, str):
        raise ValueError('A note body must be text.')
    at = timestamp()
    return dict(id=uuid.uuid4().hex, title=title.strip(), body=body, created=at, updated=at)


def edit_note(note, fields):
    """One note with the carried fields changed and `updated` stamped.

    A key the payload does not carry is left alone, the same merge rule
    every record write here follows. An empty title is rejected on an edit
    too: an edit cannot take away what creation required.
    """
    if not isinstance(fields, dict):
        raise ValueError('Note must be an object.')
    result = dict(note)
    for key in ('title', 'body'):
        if key in fields:
            if not isinstance(fields[key], str):
                raise ValueError(f'A note {key} must be text.')
            result[key] = fields[key].strip() if key == 'title' else fields[key]
    if not result['title'].strip():
        raise ValueError('A note needs a title.')
    result['updated'] = timestamp()
    return result


def notes_view(record):
    """Every note on a record, in stored order.

    A record written before notes became a list keeps its text in the
    legacy `notes` string. That string surfaces here as the record's one
    note, so no note is invisible while both shapes exist. It carries no
    timestamps, because the legacy field never recorded when it was
    written, and an invented date would read as a note written just now.

    This is a read and only a read: nothing is written, and the file keeps
    its legacy shape until the owner's next note write, which persists the
    migrated note and clears the string in the same save (`notes_payload`).
    """
    record = record or {}
    stored = record.get('note_list')
    if isinstance(stored, list) and stored:
        return [note for note in stored if isinstance(note, dict)]
    legacy = record.get('notes')
    if isinstance(legacy, str) and legacy.strip():
        return [dict(id=LEGACY_NOTE_ID, title=LEGACY_NOTE_TITLE, body=legacy,
                     created=None, updated=None)]
    return []


def has_notes(record):
    """Whether the record carries any owner note, in either shape."""
    return bool(notes_view(record))


def notes_payload(notes):
    """The save payload for a record whose notes just changed: the new
    list, and the legacy free-text field cleared.

    Clearing it in the same write is what makes the read-time migration a
    one-way door. Until the owner's first note write the file keeps its
    legacy shape untouched; after it, `note_list` is the only place the
    record's notes live. One write for both halves means a note can never
    exist in two shapes at once.
    """
    return {'note_list': notes, 'notes': ''}


def validate_note_list(notes):
    """Check a stored note list against the one note shape, and return it.

    created and updated may be null: that is the migrated legacy note,
    whose write-time nobody recorded. Ids must be unique within a record,
    since every edit and delete addresses a note by its id.
    """
    if notes is None:
        return []
    if not isinstance(notes, list):
        raise ValueError('note_list must be a list of notes.')
    for note in notes:
        if not isinstance(note, dict) or set(note) != set(NOTE_FIELDS):
            raise ValueError(f'Each note must have {", ".join(NOTE_FIELDS)}.')
        for key in ('id', 'title', 'body'):
            if not isinstance(note[key], str):
                raise ValueError(f'note {key} must be text.')
        if not note['id'] or not note['title'].strip():
            raise ValueError('A note needs an id and a title.')
        for key in ('created', 'updated'):
            if note[key] is not None and not isinstance(note[key], str):
                raise ValueError(f'note {key} must be text or null.')
    ids = [note['id'] for note in notes]
    if len(set(ids)) != len(ids):
        raise ValueError('Note ids must be unique on one record.')
    return notes


def validate_requirement_groups(groups):
    """Check a grouped requirement list against the one stored shape, and
    return it normalized (package 2).

    The invariant is the record's, not one writer's: text stripped, one
    entry per group and text ignoring case, and a must-have winning over a
    nice-to-have for the same line, because the stronger claim is the one
    the posting makes. Entry order is the order the entries arrived in,
    which is the posting's own. Every writer goes through `_save_record`,
    so an owner edit, the extraction callback and the offline rules all
    land the same list; `careeros.ingest.requirement_groups` applies this
    same function to a model answer before it ever gets here.
    """
    if not isinstance(groups, list) or any(
            not isinstance(entry, dict) or set(entry) != {'group', 'level', 'text'}
            or entry['group'] not in REQUIREMENT_GROUPS
            or entry['level'] not in REQUIREMENT_LEVELS
            or not isinstance(entry['text'], str) or not entry['text'].strip()
            for entry in groups):
        raise ValueError('requirement_groups must be a list of {group, level, text}, where group is one of '
                         + ', '.join(REQUIREMENT_GROUPS) + ' and level is must or nice.')
    seen = {}
    for entry in groups:
        normalized = {'group': entry['group'], 'level': entry['level'], 'text': entry['text'].strip()}
        key = (normalized['group'], normalized['text'].casefold())
        if key not in seen or (normalized['level'] == 'must' and seen[key]['level'] == 'nice'):
            seen[key] = normalized
    return list(seen.values())


#: The keys `taxonomy.make_value_record` puts on every value record. A
#: stored value is checked against this rather than re-validated field by
#: field, because the factory is the one place the shape is decided and a
#: second opinion here could only drift from it.
VALUE_RECORD_KEYS = frozenset(('value', 'source', 'confidence', 'evidence',
                               'taxonomy_version', 'standard_version', 'classified_at',
                               'flags', 'guide_version'))


def validate_value_records(values):
    """`values` as the classification pipeline writes it, or a raise.

    A mapping of FIELD name to one D4 value record. The field name is not
    always a dimension name -- `workload_min` and `workload_max` are two
    fields over the one `workload` dimension -- so the key is checked for
    being text and the record for being a record, and the dimension is
    the writer's business.
    """
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise ValueError('values must be an object mapping field names to value records.')
    checked = {}
    for field, record in values.items():
        if not isinstance(field, str) or not field.strip():
            raise ValueError('values keys must be field names.')
        if not isinstance(record, dict):
            raise ValueError(f'values[{field}] must be a value record object.')
        missing = sorted(VALUE_RECORD_KEYS - set(record))
        if missing:
            raise ValueError(f'values[{field}] is missing {", ".join(missing)}; build one with '
                             'careeros.taxonomy.make_value_record.')
        if record['source'] not in taxonomy.SOURCES:
            raise ValueError(f'values[{field}].source must be one of '
                             + ', '.join(taxonomy.SOURCES) + '.')
        if not isinstance(record['value'], str) or not record['value'].strip():
            raise ValueError(f'values[{field}].value must be a code.')
        checked[field] = dict(record)
    return checked


#: What a normalised salary block says. The first six are
#: salary_rules.yaml's own `target.fields`; the rest are the evidence and
#: the provenance every other classified value carries.
SALARY_KEYS = frozenset(('min', 'max', 'currency', 'period_stated', 'months_assumed',
                         'pensum_stated', 'annual_gross_chf_min', 'annual_gross_chf_max',
                         'quote', 'rules', 'needs_review', 'source', 'confidence',
                         'classified_at', 'flags'))


def validate_salary(salary):
    """The normalised pay block, or a raise. Null is the common case: a
    Swiss posting usually states no salary, which is no block at all and
    never a zero."""
    if salary is None:
        return None
    if not isinstance(salary, dict):
        raise ValueError('salary must be an object or null.')
    missing = sorted(SALARY_KEYS - set(salary))
    if missing:
        raise ValueError(f'salary is missing {", ".join(missing)}; build one with '
                         'careeros.classify.salary.normalise.')
    if salary['source'] not in taxonomy.SOURCES:
        raise ValueError('salary.source must be one of ' + ', '.join(taxonomy.SOURCES) + '.')
    for key in ('annual_gross_chf_min', 'annual_gross_chf_max'):
        if salary[key] is not None and not isinstance(salary[key], (int, float)):
            raise ValueError(f'salary.{key} must be a number or null.')
    return dict(salary)


def _record_defaults(kind):
    """Every field a record of this kind stores, with its empty value.

    `_save_record` builds each saved record from this dict and silently
    drops payload keys it does not name, which makes it the one true list
    of fields a write can persist. Callers that need that list (the API
    PUTs, which must not stamp provenance for keys they drop) read it
    through `job_field_names` / `company_field_names` rather than keeping a
    second copy that could drift.
    """
    job = kind == 'jobs'
    return (dict(company_id=None, title='', url='', original_url=None, source='', status='new', posted_date=None,
                 added=date.today().isoformat(), salary_info=False, salary_note='', location='', remote_ok=None,
                 notes='', note_list=[], enriched=False, employment_type='', valid_through='', custom={},
                 description='', company='', seniority='', keywords=[], summary='', contact_email='',
                 ingest_source='', sector=None, sectors=[], industry=None, industries=[],
                 background='', skills=[], certifications=[], responsibilities=[], summary_source='', refresh='skipped',
                 employee_count=None, function=[], tags=[],
                 normalized_url=None, in_pipeline=True, origin='manual', source_id=None,
                 ingest_state='complete', ingest_error=None, field_provenance={},
                 ats_provider=None, ats_tenant=None, ats_posting_id=None,
                 company_link_state='pending', company_link_reason=None,
                 employer_named_in_posting=None, company_review=None,
                 field_status={}, field_status_reason={}, posting_quality=None, description_structured=None,
                 requirement_groups=[],
                 # CAREER-57: the coded half of the record. `values` is
                 # {field name -> D4 value record} and `salary` is the
                 # normalised pay block; both are written by the
                 # classification pipeline and by the owner, never by a
                 # feed directly. Additive on purpose: the free-text
                 # fields they are meant to replace (seniority,
                 # employment_type, location, salary_note) are untouched
                 # here, and `field_provenance` keeps its dict[str, str]
                 # shape, because a value record carries its own source
                 # and has no business inside a mapping of field name to
                 # one word. See docs/runbooks/migrate-job-value-records.md.
                 values={}, salary=None,
                 # D7: the posting being gone is a fact about the posting,
                 # so it is this flag and never a status. closed_at is the
                 # day it was found gone, closed_reviewed_at the day the
                 # owner kept the job anyway (which stops the closed-
                 # postings review suggesting it again), and end_reason the
                 # optional suggestion behind an ended job.
                 closed=False, closed_at=None, closed_reviewed_at=None, end_reason=None,
                 occupation_code=None, skill_codes=None,
                 # CAREER-36: where this record's AI reading stands. Null
                 # means never tried, which is what every record written
                 # before this field carries, so no migration is needed.
                 ai_status=None, ai_error=None, ai_started=None, ai_finished=None) if job else
            dict(name='', name_source='owner', website=None, size=None, locations=[], sector=None,
                 contact_email='', notes='', note_list=[], custom={}, enrichment={},
                 kind='employer', sectors=[], size_range=None, size_class=None, review_flags=[],
                 identifiers=[], sources=[], field_provenance={}))


def job_field_names():
    """Payload keys `save_job` persists. Any other key is dropped."""
    return frozenset(_record_defaults('jobs'))


def company_field_names():
    """Payload keys `save_company` persists. Any other key is dropped."""
    return frozenset(_record_defaults('companies'))


def _save_record(root, kind, data, identifier=None, *, correction_detail=None, history_event=None):
    from careeros.intake import check_url_format
    if not isinstance(data, dict):
        raise ValueError('Record must be an object.')
    existing = next(((p,d) for p,d in _records(root, kind) if d.get('id') == identifier), None) if identifier else None
    if identifier and not existing:
        raise KeyError(identifier)
    job = kind == 'jobs'
    defaults = _record_defaults(kind)
    result = defaults | (existing[1] if existing else {})
    result.update({k:v for k,v in data.items() if k in defaults})
    # The allowlist above is the one true list of fields a write can
    # persist, so a payload key missing from it changes nothing on the
    # record. That is the right outcome and used to be an invisible one:
    # a renamed field, a client typo or a retired field (`fit`) left no
    # sign anywhere that a caller had asked for a value and been ignored
    # (CAREER-30). Keys only, never values, because a payload can carry
    # anything.
    unknown = sorted(key for key in data if key not in defaults and key != 'id')
    if unknown:
        _logger.warning('%s write %s: dropped %d payload key(s) this record does not store: %s',
                        kind, identifier or 'new', len(unknown), ', '.join(unknown))
    if not isinstance(result['field_provenance'], dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in result['field_provenance'].items()):
        raise ValueError('field_provenance must be an object mapping field names to text.')
    # Jobs and companies hold notes in the same shape, so this check is
    # outside the per-kind branches below.
    result['note_list'] = validate_note_list(result['note_list'])
    # CAREER-36: the AI reading lifecycle. A job field only, because the
    # reading a caller polls is a job's. A company's own enrichment is
    # queued the same way and answers the same 202, but it records no
    # status, so a company write carries none of these keys at all --
    # except on a record that happens to hold one from before the fields
    # were scoped to the job, which loads and is preserved untouched.
    if job:
        if result['ai_status'] is not None and result['ai_status'] not in AI_STATUSES:
            raise ValueError('ai_status must be one of ' + ', '.join(AI_STATUSES) + ' or null.')
        if result['ai_error'] is not None and (not isinstance(result['ai_error'], str)
                                               or not result['ai_error'].strip()):
            raise ValueError('ai_error must be non-empty text or null.')
        for key in ('ai_started', 'ai_finished'):
            if result[key] is not None and not isinstance(result[key], str):
                raise ValueError(f'{key} must be text or null.')
        # A reason only ever explains a failure, the same rule ingest_error
        # and field_status_reason already follow: whatever moves the status
        # on takes the reason with it, so no writer has to remember to
        # clear it and a finished reading can never still show why the last
        # one failed.
        if result['ai_status'] != 'failed':
            result['ai_error'] = None
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
        if type(result['closed']) is not bool:
            raise ValueError('closed must be boolean.')
        # A reason is one of the words the popup offers, checked against
        # the union of both vocabularies rather than against the job
        # current status: a job dragged from Stopped to Rejected keeps the
        # reason it was given until the owner changes it, and a record is
        # not rewritten behind their back.
        if result['end_reason'] is not None and result['end_reason'] not in END_REASON_VALUES:
            raise ValueError('Invalid end_reason.')
        result['values'] = validate_value_records(result['values'])
        result['salary'] = validate_salary(result['salary'])
        if result['ingest_state'] not in INGEST_STATES:
            raise ValueError('Invalid ingest_state.')
        if result['origin'] not in ('manual', 'discovered'):
            raise ValueError('Invalid job origin.')
        if type(result['in_pipeline']) is not bool:
            raise ValueError('in_pipeline must be boolean.')
        for key in ('normalized_url', 'source_id', 'ats_provider', 'ats_tenant', 'ats_posting_id'):
            if result[key] is not None and not isinstance(result[key], str):
                raise ValueError(f'{key} must be text or null.')
        if result['ingest_error'] is not None:
            error = result['ingest_error']
            if (not isinstance(error, dict) or set(error) != {'stage', 'reason', 'at'}
                    or any(not isinstance(v, str) for v in error.values())):
                raise ValueError('ingest_error must be an object with stage, reason, at text fields.')
            if error['stage'] not in ('fetch', 'extract'):
                raise ValueError('ingest_error.stage must be fetch or extract.')
            # N3: a failure stage that contradicts the failure state it is
            # attached to (e.g. fetch_failed carrying stage: extract) is as
            # dishonest as having no stage vocabulary check at all.
            expected_stage = {'fetch_failed': 'fetch', 'extract_failed': 'extract'}.get(result['ingest_state'])
            if expected_stage and error['stage'] != expected_stage:
                raise ValueError(f'ingest_error.stage must be {expected_stage} when ingest_state is '
                                 f'{result["ingest_state"]}.')
        # A failure state is meaningless without a reason, and a reason left
        # over from a past failure must never linger once the state no
        # longer says failed (e.g. a retry that reaches fetched/complete).
        if result['ingest_state'] in ('fetch_failed', 'extract_failed') and result['ingest_error'] is None:
            raise ValueError('ingest_error is required when ingest_state is a failure state.')
        if result['ingest_state'] not in ('fetch_failed', 'extract_failed') and result['ingest_error'] is not None:
            raise ValueError('ingest_error must be null unless ingest_state is a failure state.')
        if result['company_link_state'] not in ('linked', 'pending', 'needs_review'):
            raise ValueError('Invalid company_link_state.')
        if result['company_link_reason'] is not None and result['company_link_reason'] not in COMPANY_LINK_REASONS:
            raise ValueError('Invalid company_link_reason.')
        if result['employer_named_in_posting'] is not None and not isinstance(result['employer_named_in_posting'], str):
            raise ValueError('employer_named_in_posting must be text or null.')
        if not isinstance(result['field_status'], dict) or any(
                not isinstance(k, str) or v not in FIELD_STATUS_VALUES for k, v in result['field_status'].items()):
            raise ValueError('field_status must map field names to pending, done, failed, or not_evidenced.')
        if not isinstance(result['field_status_reason'], dict) or any(
                not isinstance(k, str) or not isinstance(v, str) or not v.strip()
                for k, v in result['field_status_reason'].items()):
            raise ValueError('field_status_reason must map field names to non-empty text.')
        # A reason only ever explains a field field_status reports as
        # not_evidenced: the reader covered the field and the record still
        # has no value, and the reason is the one thing that says why. So
        # whatever moves that field on -- a later reading that fills it, an
        # owner edit, a retry putting it back to pending -- takes the
        # reason with it, the same rule ingest_error follows for the
        # record's own failure states. Nothing has to remember to clear it.
        result['field_status_reason'] = {
            field: reason for field, reason in result['field_status_reason'].items()
            if result['field_status'].get(field) == 'not_evidenced'}
        if result['posting_quality'] is not None and result['posting_quality'] not in POSTING_QUALITY_VALUES:
            raise ValueError('Invalid posting_quality.')
        if result['description_structured'] is not None:
            structured = result['description_structured']
            if (not isinstance(structured, dict) or set(structured) != {'summary', 'requirements', 'nice_to_have', 'method'}
                    or not isinstance(structured['summary'], str)
                    or not isinstance(structured['requirements'], list)
                    or any(not isinstance(x, str) for x in structured['requirements'])
                    or not isinstance(structured['nice_to_have'], list)
                    or any(not isinstance(x, str) for x in structured['nice_to_have'])
                    or structured['method'] not in DESCRIPTION_STRUCTURED_METHODS):
                raise ValueError('description_structured must have summary, requirements, nice_to_have, method.')
        # Package 2: grouped requirements. The flat lists above stay as
        # they are for every job written before the groups existed, which
        # is what keeps a pre-package-2 record readable without a rewrite
        # (owner decision: migration is the per-job Re-extract action, and
        # nothing else).
        result['requirement_groups'] = validate_requirement_groups(result['requirement_groups'])
        if result['occupation_code'] is not None and not isinstance(result['occupation_code'], str):
            raise ValueError('occupation_code must be text or null.')
        if result['skill_codes'] is not None and (
                not isinstance(result['skill_codes'], list)
                or any(not isinstance(x, str) for x in result['skill_codes'])):
            raise ValueError('skill_codes must be a list of text values or null.')
        if result['company_review'] is not None:
            review = result['company_review']
            if not isinstance(review, dict) or set(review) != {'candidates', 'at', 'token'}:
                raise ValueError('company_review must be an object with candidates, at, token.')
            if not isinstance(review['at'], str):
                raise ValueError('company_review.at must be text.')
            if not isinstance(review['token'], str) or not review['token']:
                raise ValueError('company_review.token must be text.')
            candidates = review['candidates']
            if not isinstance(candidates, list):
                raise ValueError('company_review.candidates must be a list.')
            for candidate in candidates:
                if (not isinstance(candidate, dict) or not {'company_id', 'name', 'score', 'basis'} <= set(candidate)
                        or set(candidate) - {'company_id', 'name', 'score', 'basis', 'current'}
                        or ('current' in candidate and type(candidate['current']) is not bool)
                        or not isinstance(candidate['company_id'], str)
                        or not isinstance(candidate['name'], (str, type(None)))
                        or not isinstance(candidate['score'], (int, float))
                        or not isinstance(candidate['basis'], (str, type(None)))):
                    raise ValueError('Each company_review candidate must have company_id, name, score, basis.')
        for key in ('salary_info', 'enriched', 'remote_ok'):
            if type(result[key]) is not bool and not (key == 'remote_ok' and result[key] is None):
                raise ValueError(f'{key} must be boolean' + (' or null.' if key == 'remote_ok' else '.'))
        for key in ('posted_date', 'added', 'closed_at', 'closed_reviewed_at'):
            value = result[key]
            # `added` is the one date every job has; the other three are
            # null until the thing they date happens.
            if value is None and key != 'added':
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
            # A job the owner is pursuing again is watched again, so the
            # gone verdict is dropped and the next scan decides afresh.
            # The statuses that qualify are the watcher's own list, imported
            # here rather than repeated so the two cannot disagree (inside
            # the function: the watcher imports this module at its top).
            from careeros.watcher import WATCH_STATUSES
            if (result['status'] in WATCH_STATUSES
                    and result.get('watch', {}).get('watch_status') == 'gone'):
                result['watch'] = {}
        # D7: the optional ending reason, in the words the owner picked.
        # Its own event rather than part of the status move, because the
        # reason usually arrives after the move: the popup opens from the
        # Undo message or from an ended card, and Skip saves nothing at
        # all, so a move may carry no reason for days or ever.
        if result['end_reason'] and result['end_reason'] != (existing[1].get('end_reason') if existing else None):
            append_event(result, 'end_reason_set', f"{result['status']}: {result['end_reason']}")
        if correction_detail:
            append_event(result, 'company_correction', correction_detail)
        if history_event:
            append_event(result, *history_event)
        # JOZ-267 Section 4.1: every ingest_state transition is history-
        # logged. Callers that already describe the transition (fetched,
        # fetch_failed, extract_failed, ...) pass history_event above; this
        # is the backstop for any save that changes ingest_state without
        # one, so no transition can land silently.
        if existing and not history_event and result['ingest_state'] != existing[1].get('ingest_state'):
            append_event(result, result['ingest_state'],
                        f"Ingest state: {existing[1].get('ingest_state')} -> {result['ingest_state']}.")
        if not existing:
            append_event(result, 'created', 'Job created')
        # The first note on a job is history, whichever shape it arrives
        # in: the legacy free-text field a pre-note_list client still
        # writes, or the note list the Notes section writes now. Reading
        # both through has_notes is what keeps the first note in the list
        # from going unlogged, and keeps the owner's first note write on a
        # record that already had legacy text from logging a second time.
        if has_notes(result) and not (existing and has_notes(existing[1])):
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
        if result['identifiers'] is None:
            result['identifiers'] = []
        if not isinstance(result['identifiers'], list):
            raise ValueError('identifiers must be a list.')
        for ident in result['identifiers']:
            if (not isinstance(ident, dict) or set(ident) != {'type', 'value', 'provenance'}
                    or ident['type'] not in IDENTIFIER_TYPES
                    or not isinstance(ident['value'], str) or not ident['value']
                    or not isinstance(ident['provenance'], str)):
                raise ValueError('Each identifier must have type, value, provenance.')
        if result['sources'] is None:
            result['sources'] = []
        if not isinstance(result['sources'], list):
            raise ValueError('sources must be a list.')
        for source in result['sources']:
            if (not isinstance(source, dict) or set(source) != {'id', 'kind', 'url', 'ats_provider', 'active', 'last_polled'}
                    or not isinstance(source['id'], str)
                    or source['kind'] not in SOURCE_KINDS
                    or not isinstance(source['url'], str) or not source['url']
                    or not isinstance(source['ats_provider'], (str, type(None)))
                    or type(source['active']) is not bool
                    or not isinstance(source['last_polled'], (str, type(None)))):
                raise ValueError('Each source must have id, kind, url, ats_provider, active, last_polled.')
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
    # Unresolved employer corrections retain email on the job until review links it.
    if (result.get('company_link_state') != 'needs_review'
            and is_valid_contact_email(result.get('contact_email')) and result.get('company_id')):
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
    """Translate a legacy sector string into sectors on the raw incoming
    payload, before _save_record validates and persists it, per decision 6:
    the new-shape field always wins when a payload carries both. The
    new-shape value already stored on the record wins too, so a legacy
    signal never clobbers owner-set or previously derived sectors.

    The legacy size half of that translation is gone (owner decision
    2026-10-15): it produced a `size_range`, which is the scale the class
    retired, and the raw employee count a `size_class` needs is not in a
    legacy payload. A legacy `size` string is persisted as itself and
    translated into nothing. See _drop_retired_size_range."""
    if not isinstance(data, dict):
        return data
    stored = load_company(root, identifier) if identifier else None
    data = dict(data)
    new_sectors = 'sectors' in data or (stored or {}).get('sectors')
    if 'sector' in data and not new_sectors and isinstance(data.get('sector'), str) and data['sector']:
        matched = match_sectors(data['sector'])
        if matched:
            data['sectors'] = matched
    return data

def _drop_retired_size_range(data):
    """Never persist a numeric size_range value again (owner decision
    2026-10-15: size_class is the only size scale).

    Nothing derives a range to be dropped any more: since 2026-10-16
    (CAREER-33) `org_intake.classify.derive_size` and the size cascade
    answer with the class alone, and only read a stored range to check
    evidence against it. This gate stays because it guards the payload
    rather than any one producer -- a legacy write that names the retired
    field itself (the `sector`/`size` form translation, an owner PUT, a
    future signal nobody has written yet) passes through here, and
    stopping it at the one gate every company write crosses is what keeps
    the second scale from coming back through a path nobody remembered.

    Clearing a range an older record still carries (an explicit null) is
    let through: that is what scripts/migrate_company_size_scale.py and
    the re-kind path in careeros/enrich.py do, and retiring the stored
    values needs it."""
    if isinstance(data, dict) and data.get('size_range') is not None:
        return {key: value for key, value in data.items() if key != 'size_range'}
    return data

def save_company(root, data, identifier=None):
    data = _drop_retired_size_range(_translate_legacy_company_fields(root, data, identifier))
    result, _ = _save_record(root, 'companies', data, identifier)
    return result

def _migrate_one_job(data):
    """Backfill every Journey 1 field this record is still missing,
    independently of the others, so a record that already has some of them
    (e.g. one touched by an unrelated save_job call, which always writes
    the full schema, present-but-null) still gets the rest. normalized_url
    and the ats_* fields are purely derived, never owner-set through any
    API, so a falsy stored value is treated the same as an absent key for
    those; in_pipeline/origin/source_id/ingest_state/ingest_error can carry
    a real, final, possibly falsy value (in_pipeline: false), so those use
    setdefault semantics (only a genuinely absent key is filled)."""
    changed = False
    if not data.get('normalized_url'):
        normalized = normalize_url(data.get('url') or '')
        if normalized != data.get('normalized_url'):
            data['normalized_url'] = normalized
            changed = True
    for key, default in (('in_pipeline', True), ('origin', 'manual'), ('source_id', None),
                         ('ingest_state', 'complete'), ('ingest_error', None), ('field_provenance', {})):
        if key not in data:
            data[key] = default
            changed = True
    # O3 (round 2): save_job always writes the full schema, so an
    # unrelated save on a legacy record can leave these three present but
    # null -- a shape identical, for this gate's purposes, to never having
    # run detection at all. `key not in data` alone missed that case and
    # left the record permanently undetected; a null value is "unknown,
    # backfill it" exactly like a missing key, while an explicit non-null
    # value (a real previous detection, never owner-set through any API)
    # is still left untouched.
    if any(data.get(key) is None for key in ('ats_provider', 'ats_tenant', 'ats_posting_id')):
        ats_match = posting_ats(data.get('url') or '')
        for key, value in (('ats_provider', ats_match.provider if ats_match else None),
                           ('ats_tenant', ats_match.tenant if ats_match else None),
                           ('ats_posting_id', ats_match.posting_id if ats_match else None)):
            if data.get(key) is None:
                # Still register a real change even when the detector also
                # comes back empty: a record where the key was genuinely
                # absent must end up with it present (null is itself the
                # schema-complete, "nothing detected" answer); a record
                # where it was already present-and-null stays a no-op, so a
                # second migration pass never reports spurious churn.
                if key not in data or data[key] != value:
                    changed = True
                data[key] = value
    # JOZ-266: company_link_state derives from whatever company_id this
    # legacy record already carries (linked when set, else pending);
    # company_link_reason/employer_named_in_posting/company_review have no
    # derivable value for a pre-ladder record, so they backfill to null,
    # exactly like the other Journey 1 additive fields above.
    if 'company_link_state' not in data:
        data['company_link_state'] = 'linked' if data.get('company_id') else 'pending'
        changed = True
    for key in ('company_link_reason', 'employer_named_in_posting', 'company_review'):
        if key not in data:
            data[key] = None
            changed = True
    review = data.get('company_review')
    if review is None and data.get('company_link_state') == 'needs_review':
        review = data['company_review'] = {'candidates': [], 'at': timestamp()}
        changed = True
    if isinstance(review, dict) and not review.get('token'):
        review['token'] = uuid.uuid4().hex
        changed = True
    # JOZ-267: per-field status/provenance, posting_quality and the
    # structured description block are additive, like every field above;
    # occupation_code/skill_codes are reserved (Section 5) and stay null
    # for a pre-JOZ-267 record exactly as for a brand new one.
    # requirement_groups (package 2) backfills to an empty list for the
    # same reason: an existing job keeps its flat must/nice lists until
    # the owner re-extracts it, and an empty list is how a reader tells
    # "not grouped yet" from "grouped, and the posting asked for nothing".
    # D7 adds closed/closed_at/closed_reviewed_at/end_reason on the same
    # terms: an existing job has no closed posting recorded and no ending
    # reason until something says so, and `closed: false` is the complete
    # answer rather than a missing key.
    for key, default in (('field_status', {}), ('posting_quality', None),
                         ('description_structured', None), ('requirement_groups', []),
                         ('closed', False), ('closed_at', None),
                         ('closed_reviewed_at', None), ('end_reason', None),
                         ('occupation_code', None), ('skill_codes', None)):
        if key not in data:
            data[key] = default
            changed = True
    return changed


def _migrate_one_company(data):
    """Backfill JOZ-266's additive company fields: identifiers derives one
    domain identifier from the stored website, when present (provenance
    'derived', since it predates any ladder match); sources backfills to an
    empty list, since a pre-ladder company never recorded a careers-page or
    ATS-feed source. Both use setdefault semantics (a genuinely absent key
    only), matching _migrate_one_job's treatment of in_pipeline/origin/etc:
    an empty list is itself a valid, final, previously-derived answer."""
    changed = False
    if 'identifiers' not in data:
        identifiers = []
        website = data.get('website')
        if website:
            from careeros import intake
            try:
                domain = intake.domain(website)
            except Exception:
                domain = ''
            if domain:
                identifiers.append({'type': 'domain', 'value': domain, 'provenance': 'derived'})
        data['identifiers'] = identifiers
        changed = True
    if 'sources' not in data:
        data['sources'] = []
        changed = True
    return changed


def migrate_company_fields(root):
    """One-time idempotent migration (JOZ-266), the company-side counterpart
    of migrate_job_fields: every company gains identifiers and sources.
    Reads and writes the YAML directly, isolating one malformed record from
    the rest of the sweep, for the same reasons migrate_job_fields does."""
    migrated = []
    for path in sorted((Path(root) / 'companies').glob('*.yaml')):
        # m9: read, transform, AND write all sit inside one isolation
        # boundary per record -- a write failure (e.g. a transient OSError)
        # must report to stderr and let the sweep continue onto the next
        # record, not abort every record after it.
        data = None
        try:
            data = _read(path)
            if not data:
                continue
            changed = _migrate_one_company(data)
            if changed:
                _write(path, data)
                migrated.append(data.get('id'))
        except Exception as error:
            label = data.get('id', path.name) if isinstance(data, dict) else path.name
            print(f'migrate_company_fields: skipped {label} '
                  f'({type(error).__name__}: {error})', file=sys.stderr)
            continue
    return migrated


def migrate_job_fields(root):
    """One-time idempotent migration (JOZ-265): every job gains normalized_url
    plus the Journey 1 two-phase ingest fields. Reads and writes the YAML
    directly, like save_watch_result, instead of going through save_job's
    full validation: a legacy record may have a shape (e.g. an empty url)
    that predates validation rules introduced since it was written, and
    this migration must not refuse to backfill additive fields just because
    an unrelated existing field would fail today's stricter checks.

    Each record is isolated: one record whose url cannot be normalized (a
    malformed legacy value) is left completely untouched on disk and
    reported to stderr with its id and the reason, instead of taking down
    the whole sweep (and, since this runs at app startup, the whole app)."""
    migrated = []
    for path in sorted((Path(root) / 'jobs').glob('*.yaml')):
        # m9: see migrate_company_fields -- read, transform, and write all
        # sit inside the same per-record isolation boundary now.
        data = None
        try:
            data = _read(path)
            if not data:
                continue
            changed = _migrate_one_job(data)
            if changed:
                _write(path, data)
                migrated.append(data.get('id'))
        except Exception as error:
            label = data.get('id', path.name) if isinstance(data, dict) else path.name
            print(f'migrate_job_fields: skipped {label} '
                  f'({type(error).__name__}: {error})', file=sys.stderr)
            continue
    return migrated

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
    # Size evidence a company's own postings carry (owner decision
    # 2026-10-16): the count the capability's zero-network promotion tier
    # reads, and the record of which posting stated it. Evidence toward
    # size_class and nothing else -- neither key is a size scale, and the
    # two retired ones stay unwritten.
    count = block.get('employee_count')
    if count is not None and (type(count) is not int or count < 1):
        raise ValueError('enrichment.employee_count must be a positive integer or null.')
    evidence = block.get('employee_count_evidence')
    if evidence is not None and not isinstance(evidence, dict):
        raise ValueError('enrichment.employee_count_evidence must be an object or null.')
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
