"""The classification pipeline: three layers, one precedence order, one
record shape.

CAREER-57. CAREER-55 shipped the taxonomy files and the value-record
factory and wrote, in the module docstring of `careeros.taxonomy`, that
it "deliberately does NOT classify anything". This package is what does,
and it is the first writer of the records that factory makes.

## The three layers (owner-approved architecture, 2026-10-18)

  1. **Rules** (`rules`), deterministic and free. Keyword tables and
     formulas over the title, the department and the text. Runs first and
     answers most fields of most postings.
  2. **Local model** (`llm`), on the owner's own Ollama host, asked ONLY
     about the fields the rules layer left open, because `llm` is the
     last word in the precedence order and an answer about a settled
     field would lose anyway. Not run live in this build; fixtures only.
  3. **Escalation**, which is not a layer that runs but a queue that
     fills: a value that fails validation or falls under the confidence
     floor is stored as `unknown` carrying `needs_review` and the reason.
     A cheap hosted fallback plugs into `llm.classify`'s signature later.

## Precedence, and the one thing it does not mean

`admin > user > feed > rule > llm` (value_record.yaml). A stored value is
never replaced by one from a weaker source -- that is the data-side half
of "human edits always win", and `taxonomy.source_wins` is the one place
it is decided.

The one reading that had to be settled here: **a weaker source may fill a
stronger source's `unknown`, and may never contradict its value.** An ATS
feed that carries no contract field stores `unknown` with the reason "the
feed states no contract"; that record says the feed was asked and had
nothing, not that the question is closed. Refusing the rules layer there
would make the whole pipeline a no-op on the 45 pool postings whose feed
states no contract. A value that fills an `unknown` this way keeps its
own source and says so in its evidence (`filled_unknown_from`), so the
chain stays readable. Overwriting a stronger source's real VALUE is
still refused outright, whatever the confidences say.

## What a classified posting carries

    values   {field: value record}   -- D4 shape, one per dimension
    salary   the normalised block    -- see `salary`; no dimension exists
    review   {field: reason}         -- what a human is owed, with why
    metrics  per-call tokens and latency (M1-3), empty without layer 2

`values` keys are FIELD names, not dimension names: `workload_min` and
`workload_max` are two fields over the one `workload` dimension, and
`isco_unit_group` is derived from `occupation_family` rather than read.

## The two inputs

`from_feed_posting` reads a mapped ATS posting, whose feed-stated value
records are already in the D4 shape and are PRESERVED rather than
re-derived (the brief's own rule). `from_vault_job` reads a stored job,
whose free-text fields and `field_provenance` are translated into value
records of the right source, so an owner edit made before this pipeline
existed still outranks everything a machine reads today.
"""
import logging

from careeros import taxonomy
from careeros.classify import llm, rules, salary
from careeros.classify.rules import review_reason

_logger = logging.getLogger(__name__)

#: The layers a caller may ask for, in the order they run.
LAYERS = ('rules', 'llm')

#: What a legacy `field_provenance` word means in D4's source vocabulary.
#: The vault has written these three since long before value records
#: existed, and the whole point of reading them is that an owner edit
#: ('user') outranks anything this pipeline derives.
LEGACY_SOURCES = {'user': 'user', 'owner': 'admin', 'llm': 'llm', 'scrape': 'rule',
                  'feed': 'feed'}

#: Which stored job field answers which dimension. The free-text half of
#: the migration note: these are the fields coded value records replace.
LEGACY_FIELDS = {'seniority': 'seniority', 'employment_type': 'contract',
                 'location': 'municipality'}


def subject(*, title='', department='', text='', employer_name='', location_text='',
            values=None, key=None):
    """One posting as every layer wants to see it.

    Deliberately not a class: the layers read it and never write it, and
    the two builders below are the only things that make one.
    """
    return {'key': key, 'title': title or '', 'department': department or '',
            'text': text or '', 'employer_name': employer_name or '',
            'location_text': location_text or '', 'values': dict(values or {})}


def from_feed_posting(mapped):
    """A mapped ATS posting as a subject, keeping its feed value records.

    The feed's own records are carried through untouched. They are
    already `taxonomy.make_value_record(..., 'feed')` with the provider
    field they came from as evidence (`feeds.base.map_value`), and
    re-deriving them would both cost work and lose the provider's own
    word for the value.
    """
    offices = mapped.get('offices') or []
    return subject(
        key=mapped.get('key'),
        title=mapped.get('title'),
        department=' '.join(filter(None, [mapped.get('department'), mapped.get('team'),
                                          mapped.get('recruiting_category'),
                                          mapped.get('occupation')])),
        text=mapped.get('description') or '',
        employer_name=mapped.get('employer_name') or mapped.get('tenant') or '',
        location_text=offices[0] if offices else (mapped.get('location_raw') or ''),
        values=mapped.get('values') or {})


def from_vault_job(job):
    """A stored job as a subject, with its free-text fields read as value
    records of the source `field_provenance` names.

    This is what makes the migration safe: a `seniority` the owner typed
    becomes a `user`-sourced record, which outranks every machine source,
    so re-running the pipeline over a migrated vault cannot undo an
    owner's edit.
    """
    provenance = job.get('field_provenance') or {}
    existing = {}
    for field, dimension in LEGACY_FIELDS.items():
        stored = job.get(field)
        source = LEGACY_SOURCES.get(provenance.get(field))
        if not stored or not str(stored).strip() or source not in ('admin', 'user'):
            # Only a human's own value is carried across as a value
            # record. A machine-written free-text field is re-read by
            # this pipeline anyway and would otherwise pin a worse
            # answer in place.
            continue
        code = _legacy_code(dimension, stored)
        if code is None:
            continue
        existing[dimension] = taxonomy.make_value_record(
            dimension, code, source, confidence=None,
            evidence={'rule': f'the stored free-text {field} field, which '
                              f'field_provenance marks {provenance.get(field)!r}',
                      'stored': str(stored)})
    text = '\n\n'.join(filter(None, [job.get('summary'), job.get('description'),
                                     ' '.join(job.get('responsibilities') or []),
                                     ' '.join(job.get('skills') or []),
                                     job.get('background')]))
    # No `department`: a stored job has no such field, and the one that
    # looks like it -- `function`, the vault's own function facet -- is a
    # PREVIOUS classification written by the old extraction prompt. Feeding
    # it back in would make this layer's answer depend on a model run it is
    # here to replace, and would quietly launder an `llm` value into a
    # `rule` one.
    return subject(
        key=job.get('id'),
        title=job.get('title'),
        text=text,
        employer_name=job.get('company') or job.get('employer_named_in_posting') or '',
        location_text=job.get('location') or '',
        values=existing)


def _legacy_code(dimension, stored):
    """A free-text legacy value as a taxonomy code, or None when it is
    not one. `seniority` goes through D6's own crosswalk, which is the
    reason that crosswalk is in the taxonomy at all."""
    word = str(stored).strip().casefold()
    if dimension == 'seniority':
        crossed = taxonomy.seniority_crosswalk().get(word)
        return crossed['seniority'] if crossed else None
    if taxonomy.valid_code(dimension, word):
        return word
    return None


# --- precedence ------------------------------------------------------------

def wins(candidate, stored):
    """Whether `candidate` replaces `stored` on one field.

    Two rules and no third: a strictly stronger source always wins, and a
    weaker one wins only against an `unknown` (see the module docstring
    on why). Equal sources never replace each other, so re-running a
    layer is idempotent.
    """
    if stored is None:
        return True
    if taxonomy.source_wins(candidate['source'], stored['source']):
        return True
    if stored['value'] == taxonomy.UNKNOWN and candidate['value'] != taxonomy.UNKNOWN:
        return True
    return False


def merge(stored, candidates):
    """Fold one layer's answers into what a posting already carries.

    Returns a new mapping; neither argument is modified. A value that
    filled a stronger source's `unknown` records which source it filled,
    so the chain is readable afterwards.
    """
    merged = dict(stored or {})
    for field, candidate in (candidates or {}).items():
        previous = merged.get(field)
        if not wins(candidate, previous):
            continue
        if previous is not None and not taxonomy.source_wins(candidate['source'],
                                                             previous['source']):
            candidate = _note_fill(candidate, previous)
        merged[field] = candidate
    return merged


def _note_fill(candidate, previous):
    evidence = candidate.get('evidence')
    evidence = dict(evidence) if isinstance(evidence, dict) else {'rule': evidence}
    evidence['filled_unknown_from'] = previous['source']
    return dict(candidate, evidence=evidence)


# --- the pipeline ----------------------------------------------------------

def open_fields(values):
    """The fields a weaker layer is still allowed to answer.

    A field with a settled value from any source is closed: the local
    model is last in the precedence order, so asking it about a field a
    table already answered would spend tokens on a value that cannot win.
    A field holding `unknown` from a stronger source IS open, for the
    same reason `wins` lets it be filled.
    """
    return tuple(field for field in rules.FIELDS
                 if (values.get(field) or {}).get('value', taxonomy.UNKNOWN) == taxonomy.UNKNOWN)


def review(values, salary_block=None):
    """Every field a human is owed, with why.

    Read off the records themselves rather than tracked beside them: a
    value record that needs review says so in its own evidence, so a
    record copied into a vault carries its reason with it.
    """
    owed = {field: review_reason(record) for field, record in values.items()
            if review_reason(record)}
    if salary_block and salary_block.get('needs_review'):
        owed['salary'] = salary_block['needs_review']
    return owed


def classify(subject_dict, *, layer='rules', client=None, config=None, at=None):
    """One posting through the layers asked for.

    `layer` is 'rules', 'llm' or 'all'. 'llm' alone still runs the rules
    first -- not to store their answers twice, but because the local
    model is only asked about what the rules could not settle, and that
    set does not exist until they have run.

    Returns `{values, salary, review, metrics, layers}`.
    """
    if layer not in LAYERS and layer != 'all':
        raise ValueError(f"unknown layer {layer!r}; use one of: {', '.join(LAYERS)}, all")
    values = dict(subject_dict.get('values') or {})
    values = merge(values, rules.classify(subject_dict, at=at))
    salary_block = salary.classify(subject_dict, at=at)
    metrics = []
    ran = ['rules']
    if layer in ('llm', 'all'):
        if client is None or config is None:
            raise ValueError('the llm layer needs a client and a config; '
                             'see careeros.classify.llm.Config.from_env()')
        fields = open_fields(values)
        answers, call_metrics = llm.classify(subject_dict, fields, client=client,
                                             config=config, at=at)
        values = merge(values, answers)
        metrics.append(call_metrics)
        ran.append('llm')
    return {'key': subject_dict.get('key'), 'values': values, 'salary': salary_block,
            'review': review(values, salary_block), 'metrics': metrics, 'layers': ran}


def coverage(results, fields=rules.FIELDS):
    """How many postings each field was settled for, and by which source.

    The number the accuracy report opens with, because a dimension
    nothing fills is a different problem from one that is filled wrongly.
    """
    table = {}
    for field in fields:
        row = {'settled': 0, 'unknown': 0, 'needs_review': 0, 'by_source': {}}
        for result in results:
            record = (result.get('values') or {}).get(field)
            if not record:
                continue
            if record['value'] == taxonomy.UNKNOWN:
                row['unknown'] += 1
            else:
                row['settled'] += 1
                row['by_source'][record['source']] = row['by_source'].get(record['source'], 0) + 1
            if review_reason(record):
                row['needs_review'] += 1
        table[field] = row
    return table
