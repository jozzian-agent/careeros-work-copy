"""Import an ATS pool export into a vault as universe jobs (CAREER-72/74).

`careeros/feeds/` stages everything it reads under `data/ats/` and
`data/personio/` and writes no vault record; PROJECT.md has carried "a
job the feed pool holds is in no vault, so it is on no surface" as an
open question since 2026-10-17. This is the step that writes them, so
the All jobs tab (B2) and the Companies directory's open-jobs counts
(B3) have something at scale to show.

## What it writes

ONE JOB PER POOL POSTING, and it is a **universe** job:

* **ownerless** -- `owner_id` is null, which `vault.Owner` reads as a
  record no user owns. `vault.Owner.sees_in_universe`
  puts an ownerless record on every user's All jobs tab and
  `vault.Owner.owns` keeps it off every tester's board; the admin
  inherits ownerless records, which is why the second half matters:
* **`in_pipeline: false`** -- universe-only, so `vault.on_board` answers
  no and `vault.list_jobs` (the board read) leaves it out for every
  reader, admin included. Without that the admin's own board would
  inherit all 704 and their real jobs would drown. "Add to my jobs" is
  the way one reaches a board: `POST /api/jobs/<id>/promote` flips the
  flag for the admin and copies the record for everybody else.

ZERO OR ONE COMPANY PER POSTING, found or created in the shared vault
(CAREER-74). A posting whose company cannot be placed is still
imported; it keeps the employer name as its own free text and sits at
`company_link_state: pending`, which is the state the product already
has for a posting whose employer it could not place.

## What it never writes

* **No existing record is touched.** Not a job: a pool posting that
  duplicates one of the owner's own is skipped whole, and the owner's
  record is not re-stamped, re-dated or re-linked (D4, ownership and
  provenance are stamped once). Not a company: a company this import
  finds is linked and nothing is added to it, so an owner-curated name,
  sector, size or location cannot be overwritten by a bulk import
  nobody has reviewed. Only the companies this run creates are written.
* **No company rollup.** `vault.save_job` skips the shared-company
  regeneration for a record that is on no board, and `enrich.shared_jobs`
  reads boards, so these 704 postings add not one derived fact to the 89
  shared companies they name. When somebody adds one to their board it
  becomes a board entry and rolls up like any other posting -- the
  evidence earning its way in, the same shape the M2 tester gate has.
* **No owner, ever.** Nothing this script writes names a user, and
  nothing it writes moves an owner, so no privacy rule changes.

## Idempotence

Two dedupe keys, both read off what is already stored, so a second run
imports nothing:

1. the pool `key` stored as the job's `source_id`
   (`ashby:Clera:120eb994-...`), which is stable across runs;
2. the posting `url`, compared against both `url` and `normalized_url`
   of every stored job, in normalised form. This is the key that makes
   the owner's 44 real jobs win: a posting one of them already holds is
   skipped rather than imported beside it.

Both indexes grow as the run writes, so the 35 postings that share a
url WITHIN one pool export are imported once each as well.

## Usage

  python scripts/import_pool_to_vault.py --pool data/ats/exports/golden_set_pool_2026-10-19.yaml \\
      --classification data/classification/run_2026-10-19.yaml --vault /path/to/vault --dry-run

`--dry-run` prints the whole report and writes nothing. Unlike the
migration scripts in this directory, the dry run is NOT the default:
this is an import the owner asks for by name after taking a vault
backup, not a one-shot that must never fire by accident. See
docs/runbooks/import-pool.md.
"""
import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from org_intake import identity  # noqa: E402
from org_intake.url import normalize_url  # noqa: E402

from careeros import vault  # noqa: E402
from careeros.feeds import store as store_module  # noqa: E402

#: Where a provider's staging store lives, for resolving a posting's
#: frozen snapshot. The same table `scripts/run_ats_fetch.py` uses:
#: Personio's is an override because CAREER-53 put it there.
DEFAULT_ROOT_BASE = Path('data/ats')
PROVIDER_ROOTS = {'personio': Path('data/personio')}

#: What a job record's `field_provenance` says about a field this import
#: filled. `values`/`salary` carry their own per-value provenance (D4);
#: this is the free-text half, and it is the feed's word in every case --
#: never a reading of the posting and never a person's.
FEED_PROVENANCE = 'feed'

#: The job fields this import fills from the pool row, for the
#: provenance stamp above. Listed rather than derived from the payload so
#: a field that happens to be empty on one posting still records who
#: would have filled it.
FEED_FILLED_FIELDS = ('title', 'url', 'source', 'location', 'posted_date',
                      'salary_info', 'description')

#: The provenance one of this import's `ats_tenant` identifiers carries.
#: `org_intake.identity` writes 'scrape' for one read off a posting page;
#: a feed is a different and better source and says so.
IDENTIFIER_PROVENANCE = 'feed'

#: How this import's own company-resolution outcomes read as a job's
#: `company_link_reason` (`vault.COMPANY_LINK_REASONS`), so a pool job
#: says why it is linked in the same words an intake-linked job does.
#: `ambiguous_exact` is absent on purpose: it links nothing, and a reason
#: is only stored beside a link.
LINK_REASONS = {'name_exact': 'name_exact', 'ats_tenant': 'ats_tenant',
                'created': 'new_company'}

#: Stands in for the id a company this run would create, so a dry run
#: can count the jobs that would link to one. Never written anywhere: a
#: dry run builds every payload and saves none.
DRY_RUN_COMPANY_ID = 'CO-(would be created)'

_LEADING_DATE = re.compile(r'^(\d{4}-\d{2}-\d{2})')


def store_root(provider, base=None):
    """The staging store directory one provider's snapshots live under.

    `base` is `--stores`, which exists so a test can point the lookup at
    a fixture tree; under it every provider is one subdirectory, with no
    Personio override, because the override only exists to keep
    CAREER-53's real snapshots where it put them.
    """
    if base:
        return Path(base) / str(provider)
    return PROVIDER_ROOTS.get(provider, DEFAULT_ROOT_BASE / str(provider))


def posted_date(value):
    """The day a posting was published, or None.

    The six adapters state it in two shapes -- an ISO-8601 timestamp with
    an offset, and Greenhouse's `2026-10-13 14:05:35 UTC` -- and the
    vault stores a day (`posted_date` is YYYY-MM-DD). So the leading date
    is read and the clock time is dropped rather than parsed: every
    reading in the pool is UTC or +00:00, and inventing a timezone
    policy to move a publication day by a few hours would be a guess
    about something no surface shows.
    """
    match = _LEADING_DATE.match(str(value or ''))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        return None


def tenant_label(slug):
    """A readable company name for a tenant that states no employer name.

    The same fallback `careeros.intake` already uses for an ATS posting
    whose page never named its employer (`slug.replace('-', ' ').title()`),
    with one correction: a slug that carries its own capitals (`AFRY`,
    `OpenAI`, `NormalComputing`) keeps them, because `.title()` would
    turn a name the tenant typed itself into `Afry` and `Openai`. A
    lower-case slug has each word's first LETTER raised, so
    `60secondstonapoli` stays as it is rather than becoming
    `60Secondstonapoli`.

    Recorded as `name_source: 'auto'` on the company, which is the
    vault's own word for a name nobody confirmed.
    """
    text = str(slug or '').replace('_', ' ').replace('-', ' ').strip()
    if not text:
        return ''
    if any(character.isupper() for character in text):
        return text
    return ' '.join(word[0].upper() + word[1:] if word[:1].isalpha() else word
                    for word in text.split())


def load_yaml(path):
    data = store_module.read_yaml(Path(path))
    if not isinstance(data, dict):
        raise SystemExit(f'{path} does not hold a pool/classification document')
    return data


def classification_index(document):
    """`key` -> the classification row, from a run file."""
    rows = document.get('postings') or []
    return {row['key']: row for row in rows if isinstance(row, dict) and row.get('key')}


def tenant_employer_names(rows):
    """(provider, tenant) -> the employer names the pool states for it.

    A tenant can host more than one employer (the capability's rule 6,
    and seven tenants in the 2026-10-19 pool do), so an employer name is
    read per POSTING and this is only used for two things: filling in a
    posting that states no name when its tenant states exactly one, and
    deciding whether the tenant is a safe `ats_tenant` identifier to
    stamp on the company at all.
    """
    names = defaultdict(set)
    for row in rows:
        if row.get('company'):
            names[(row.get('provider'), row.get('tenant'))].add(row['company'])
    return names


def company_name_for(row, stated_names):
    """The employer name one posting is imported under.

    Three sources, strongest first: the name the feed states for this
    posting; the one name its tenant states for every other posting
    (which is the `ats_tenant` evidence the resolution ladder's rung 1
    acts on, read here so the answer does not depend on row order); and
    the tenant slug, as a name nobody confirmed.
    """
    if row.get('company'):
        return row['company'], 'feed'
    siblings = stated_names.get((row.get('provider'), row.get('tenant'))) or set()
    if len(siblings) == 1:
        return next(iter(siblings)), 'tenant'
    return tenant_label(row.get('tenant')), 'slug'


def description_for(row, stores, base=None, warn=None):
    """The posting text, out of the frozen snapshot the pool row names.

    A pool row carries `description_characters` and not the text: the
    export is flat enough to survive a CSV. The snapshot it was frozen
    beside is addressed by (tenant, posting_id, content_hash), all three
    of which the row carries, so this is a lookup and never a guess --
    and never a network call either.

    An empty string when the snapshot is missing, unreadable or holds no
    text, which the caller counts and imports anyway: a posting with no
    description is still a real posting in the universe, and dropping it
    would hide a job from the tab this import exists to fill. The store's
    own reader RAISES for a corrupt file on purpose -- a store that
    quietly forgot a posting would close a whole tenant's board -- so it
    is caught here, where the right answer is one empty description and
    a warning rather than an import that dies 300 postings in.
    """
    provider = row.get('provider')
    store = stores.get(provider)
    if store is None:
        store = stores[provider] = store_module.Store(store_root(provider, base),
                                                      provider=provider)
    try:
        snapshot = store.read_posting_snapshot(row.get('tenant'), row.get('posting_id'),
                                               row.get('content_hash'))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as error:
        if warn:
            warn(f"{row.get('key')}: snapshot unreadable, imported with no description "
                 f"({type(error).__name__})")
        return ''
    return str(((snapshot or {}).get('posting') or {}).get('description') or '')


def coded_half(row, classified, warn):
    """`(values, salary, problems)` for one posting, from the run file.

    The pipeline produced both, so both are expected to pass -- and both
    are validated anyway, because a run file is a file on disk and the
    alternative to checking is a crash 300 postings into an import. A
    block that does not validate is DROPPED with a warning naming the
    posting and the reason, never repaired and never silently kept: the
    job still lands, carrying no coded values rather than invalid ones.
    """
    problems = []
    values, salary = {}, None
    if classified is None:
        return values, salary, problems
    try:
        values = vault.validate_value_records(classified.get('values'))
    except ValueError as error:
        problems.append('values')
        warn(f"{row['key']}: values dropped ({error})")
    try:
        salary = vault.validate_salary(classified.get('salary'))
    except ValueError as error:
        problems.append('salary')
        warn(f"{row['key']}: salary dropped ({error})")
    return values, salary, problems


class VaultIndex:
    """The stored records this import has to avoid colliding with.

    Built once and kept up to date as the run writes, so the second
    posting that carries a url the first one already claimed is a
    duplicate of it. Unscoped reads (`owner=None`): an import is not a
    surface anybody reads, and a posting the vault holds for ANY user is
    a posting this import must not add again.
    """

    def __init__(self, root):
        self.root = root
        self.source_ids = set()
        self.urls = set()
        for job in vault.list_owned_jobs(root):
            if job.get('source_id'):
                self.source_ids.add(job['source_id'])
            for key in ('url', 'normalized_url'):
                self.urls |= self.url_keys(job.get(key))
        # Retired companies are left out, the same answer
        # `org_store.list_organisations` gives the resolution ladder: a
        # retired company takes no new link from anybody, so matching one
        # would only produce a link `vault.save_job` then refuses.
        self.companies = [company for company in vault.list_companies(root)
                          if not vault.is_retired(company)]

    @staticmethod
    def url_keys(value):
        """Every form of one url worth comparing: as stored and
        normalised. Both, because the vault holds a `normalized_url` only
        on records intake wrote, and a pool row's raw url has to be
        comparable to a pasted link either way."""
        text = str(value or '').strip()
        if not text:
            return set()
        keys = {text}
        try:
            keys.add(normalize_url(text))
        except Exception:
            # A url the normaliser cannot read is still compared in the
            # form it is stored in. Refusing the whole posting over it
            # would be the import deciding a malformed link is worse
            # than a missing job, which it is not.
            pass
        return keys

    def duplicate_of(self, row):
        """Why this posting is already in the vault, or None."""
        if row.get('source_id') in self.source_ids:
            return 'source_id'
        if self.url_keys(row.get('url')) & self.urls:
            return 'url'
        return None

    def record(self, job):
        if job.get('source_id'):
            self.source_ids.add(job['source_id'])
        for key in ('url', 'normalized_url'):
            self.urls |= self.url_keys(job.get(key))

    def add_company(self, company):
        self.companies.append(company)


def plan_companies(rows, stated_names):
    """One plan entry per company identity the importable rows name.

    Keyed on the NORMALISED name, which is the key the match below runs
    on (`identity.find_all_by_exact_name` is case- and
    punctuation-insensitive), so two spellings of one employer plan one
    company and not two.

    Everything a created record will carry is gathered here, so a company
    is written ONCE with every location and every feed its postings name,
    rather than created and then edited back open five times.
    """
    plans = {}
    for row in rows:
        name, basis = company_name_for(row, stated_names)
        if not name:
            continue
        key = identity._normalize_name(name)
        if not key:
            continue
        plan = plans.setdefault(key, {
            'name': name, 'basis': basis, 'names': Counter(), 'locations': set(),
            'tenants': [], 'sources': {}, 'rows': 0,
        })
        plan['rows'] += 1
        plan['names'][name] += 1
        if row.get('municipality_label'):
            plan['locations'].add(row['municipality_label'])
        tenant = (row.get('provider'), row.get('tenant'))
        if tenant not in plan['tenants']:
            plan['tenants'].append(tenant)
        # One source per TENANT, not per feed url. A paginated provider
        # states a different url for every page of one board
        # (SmartRecruiters' `postings?offset=...`), and eight pages of
        # AFRY's feed are not eight places to poll -- which is what a
        # source is for. The SHORTEST url wins, ties broken
        # alphabetically: a paging parameter only ever makes a url
        # longer, so the shortest of a tenant's feed urls is the closest
        # thing to its board without this script having to know one
        # provider's paging scheme from another's. Deterministic either
        # way, so a re-run writes the same record.
        if row.get('feed_url'):
            held = plan['sources'].get(tenant)
            candidate = row['feed_url']
            if held is None or (len(candidate), candidate) < (len(held[0]), held[0]):
                plan['sources'][tenant] = (candidate, row.get('provider'))
    for plan in plans.values():
        # The spelling the most postings use, ties going to the
        # alphabetically first, so the same pool always writes the same
        # name rather than whichever row happened to come first.
        plan['name'] = min(plan['names'].items(), key=lambda pair: (-pair[1], pair[0]))[0]
    return plans


def tenant_is_shared(tenant, stated_names, plans):
    """Whether this (provider, tenant) states more than one employer.

    A shared tenant is not an identity: the capability's rule 6 says one
    ATS tenant can host more than one employer and an `ats_tenant`
    identifier is never taken over from the record that holds it. So a
    tenant whose postings name two employers is stamped on neither,
    rather than on whichever company this run happened to create first.
    """
    if len(stated_names.get(tenant) or set()) > 1:
        return True
    holders = sum(1 for plan in plans.values() if tenant in plan['tenants'])
    return holders > 1


def company_payload(plan, stated_names, plans):
    """The company record one plan entry creates, in one write."""
    identifiers = []
    for tenant in plan['tenants']:
        provider, slug = tenant
        if not provider or not slug or tenant_is_shared(tenant, stated_names, plans):
            continue
        identifiers.append({'type': 'ats_tenant',
                            'value': identity.ats_tenant_value({'provider': provider,
                                                                'tenant': slug}),
                            'provenance': IDENTIFIER_PROVENANCE})
    sources = []
    for index, (url, provider) in enumerate(plan['sources'].values(), start=1):
        sources.append({'id': f'SRC-{index}', 'kind': 'ats_feed', 'url': url,
                        'ats_provider': provider, 'active': True, 'last_polled': None})
    return {
        'name': plan['name'],
        # Nobody confirmed this name: it is the feed's word or, for a
        # tenant that states none, a reading of its slug. The vault's own
        # vocabulary for that is `auto`, which is what
        # `org_intake.identity._create_record` writes too.
        'name_source': 'auto',
        'kind': 'employer',
        'locations': sorted(plan['locations']),
        'identifiers': identifiers,
        'sources': sources,
    }


def resolve_company(plan, index, stated_names, plans, dry_run, warn):
    """`(company_id, reason)` for one plan entry, creating at most once.

    The order is the one CAREER-74 asks for, with the one rung the pool
    cannot reach left out rather than written as dead code: a pool row
    carries no website and no domain, so a domain match is impossible
    here and the `ats_tenant` identifier takes its place as the second
    key -- which is the identity the ladder's own rung 1 reads.

    1. exactly one existing company matches the name -> link it;
    2. more than one does -> ambiguous (the owner's own 2026-10-12
       ruling: duplicate exact names are a review and never a
       first-wins), so the postings keep the employer name as free text
       and link nothing;
    3. an existing company holds this tenant's `ats_tenant` identifier
       -> link it, so a bulk import cannot create a second record for a
       company intake already placed under a different spelling;
    4. otherwise create one.
    """
    matches = identity.find_all_by_exact_name(index.companies, plan['name'])
    if len(matches) == 1:
        return matches[0]['id'], 'name_exact'
    if len(matches) > 1:
        warn(f"{plan['name']}: {len(matches)} companies share this name "
             f"({', '.join(company['id'] for company in matches)}); linking none")
        return None, 'ambiguous_exact'
    for tenant in plan['tenants']:
        provider, slug = tenant
        if not provider or not slug:
            continue
        held = identity.find_by_identifier(
            index.companies, 'ats_tenant',
            identity.ats_tenant_value({'provider': provider, 'tenant': slug}))
        if held:
            return held['id'], 'ats_tenant'
    payload = company_payload(plan, stated_names, plans)
    if dry_run:
        # A sentinel, so the rehearsal counts the jobs that WOULD link
        # instead of reporting 669 postings with no company. It reaches
        # no record: a dry run builds every job payload and saves none.
        return DRY_RUN_COMPANY_ID, 'created'
    company = vault.save_company(index.root, payload)
    index.add_company(company)
    return company['id'], 'created'


def job_payload(row, *, company_id, company_name, link_reason, description, values,
                salary, today):
    """The one job record a pool posting becomes.

    Every field is the feed's own word or a code the classification run
    produced. What is deliberately absent is as much of the record as
    what is here:

    * no owner: the payload names none, so the record stores the vault's
      own null and `vault.Owner` reads it as nobody's;
    * no `employer_named_in_posting`: that field is text extracted from a
      posting and the resolution ladder ACTS on it, so filling it from a
      feed would let 704 imported rows move what the admin's next pasted
      link resolves to. The tenant evidence reaches the ladder the right
      way round instead, as the company's own `ats_tenant` identifier;
    * no summary, requirement groups, skills or keywords: nothing has
      read these postings, and an empty field is honest where a copied
      one would claim a reading that never happened.
    """
    return {
        'title': str(row.get('title') or ''),
        'url': str(row.get('url') or ''),
        # Filled here rather than left to the first reader that needs it:
        # a record written straight through the vault carries none, and
        # it is the key both the hard duplicate check and a later
        # "Add to my jobs" compare a pasted link against.
        'normalized_url': normalize_url(str(row.get('url') or '')),
        'location': str(row.get('municipality_label') or ''),
        'posted_date': posted_date(row.get('published_at')),
        # The provider and the tenant, which is what "where this posting
        # came from" means for a feed, in the shape the job schema's
        # `source` field already holds for an ATS posting.
        'source': f"{row.get('provider')}:{row.get('tenant')}",
        'status': 'new',
        'added': today,
        'salary_info': bool(row.get('has_salary')),
        'salary': salary,
        'values': values,
        'description': description,
        'ingest_state': 'complete',
        # A legal `origin` and the honest one: nobody pasted these.
        # `vault._save_record` accepts 'manual' and 'discovered' only.
        'origin': 'discovered',
        'in_pipeline': False,
        'source_id': str(row.get('key') or ''),
        'ats_provider': row.get('provider'),
        'ats_tenant': row.get('tenant'),
        'ats_posting_id': str(row.get('posting_id') or '') or None,
        'company_id': company_id,
        'company_link_state': 'linked' if company_id else 'pending',
        'company_link_reason': link_reason if company_id else None,
        # The employer label, as the free-text field the card falls back
        # to when no company record is behind the job -- which is the
        # state a posting whose employer could not be placed already has.
        # The name this import resolved rather than only the one the feed
        # stated, so a tenant that named no employer still reads as its
        # own slug instead of blank, the same fallback `careeros.intake`
        # writes for a posting page that named none.
        'company': company_name,
        'field_provenance': {field: FEED_PROVENANCE for field in FEED_FILLED_FIELDS},
    }


def run(pool_path, classification_path, root, *, dry_run=False, base=None,
        out=None, warn=None):
    """Import one pool export. Returns the report counters.

    `out` and `warn` are resolved here rather than defaulted to
    `sys.stdout`/`sys.stderr` in the signature, because a default is
    bound once at import and a caller that replaced the streams
    afterwards (a test, a wrapper) would be writing to the old ones.
    """
    def _warn(message):
        print(f'  ! {message}', file=sys.stderr)
    warn = warn or _warn
    out = out if out is not None else sys.stdout
    pool = load_yaml(pool_path)
    rows = [row for row in (pool.get('postings') or []) if isinstance(row, dict)]
    classified = classification_index(load_yaml(classification_path))
    today = date.today().isoformat()

    counts = Counter()
    counts['postings'] = len(rows)
    index = VaultIndex(root)
    stated_names = tenant_employer_names(rows)

    # Which postings are new, decided before anything is written so the
    # company plan covers exactly the postings that will land.
    fresh, skipped_reasons = [], Counter()
    for row in rows:
        row = dict(row, source_id=row.get('key'))
        reason = index.duplicate_of(row)
        if reason:
            skipped_reasons[reason] += 1
            continue
        # Recorded as the run goes, so two pool postings sharing a url
        # (35 of them in the 2026-10-19 export) land once.
        index.record({'source_id': row.get('key'), 'url': row.get('url')})
        fresh.append(row)
    counts['skipped_duplicate'] = sum(skipped_reasons.values())
    counts['skipped_source_id'] = skipped_reasons['source_id']
    counts['skipped_url'] = skipped_reasons['url']

    plans = plan_companies(fresh, stated_names)
    resolved, reasons = {}, {}
    for key, plan in sorted(plans.items()):
        company_id, reason = resolve_company(plan, index, stated_names, plans, dry_run, warn)
        resolved[key], reasons[key] = company_id, reason
        counts[f'company_{reason}'] += 1

    counts['new_postings'] = len(fresh)
    stores = {}
    for row in fresh:
        name, _basis = company_name_for(row, stated_names)
        key = identity._normalize_name(name)
        company_id, reason = resolved.get(key), reasons.get(key)
        description = description_for(row, stores, base, warn)
        values, salary, problems = coded_half(row, classified.get(row.get('key')), warn)
        if description:
            counts['descriptions_resolved'] += 1
        else:
            counts['descriptions_missing'] += 1
        if values:
            counts['values_attached'] += 1
        if 'values' in problems:
            counts['invalid_values_skipped'] += 1
        if 'salary' in problems:
            counts['invalid_salary_skipped'] += 1
        if salary:
            counts['salary_attached'] += 1
        if company_id:
            counts['jobs_with_company'] += 1
        else:
            counts['jobs_without_company'] += 1
        payload = job_payload(row, company_id=company_id, company_name=name,
                              # The vault's own vocabulary
                              # (`vault.COMPANY_LINK_REASONS`), so a pool
                              # job says why it is linked in the same
                              # words an intake-linked job does.
                              link_reason=LINK_REASONS.get(reason),
                              description=description, values=values, salary=salary,
                              today=today)
        if dry_run:
            counts['imported'] += 1
            continue
        try:
            job = vault.save_job(root, payload)
        except Exception as error:
            counts['failed'] += 1
            warn(f"{row['key']}: not imported ({type(error).__name__}: {error})")
            continue
        index.record(job)
        counts['imported'] += 1

    report(counts, root, dry_run, out)
    return counts


def report(counts, root, dry_run, out=None):
    """The whole run in the numbers CAREER-72 asks for, plus the ones a
    reader needs to tell a clean import from a lucky one."""
    out = out if out is not None else sys.stdout
    total = counts['postings']
    created = counts['company_created']
    print(f"vault={root}  mode={'DRY RUN' if dry_run else 'WRITE'}", file=out)
    print('-' * 78, file=out)
    print(f"pool postings:            {total}", file=out)
    print(f"imported:                 {counts['imported']}", file=out)
    print(f"skipped-duplicate:        {counts['skipped_duplicate']}"
          f"  (source_id {counts['skipped_source_id']}, url {counts['skipped_url']})", file=out)
    print(f"companies created:        {created}", file=out)
    print(f"companies linked:         {counts['company_name_exact'] + counts['company_ats_tenant']}"
          f"  (by name {counts['company_name_exact']}, by ats tenant"
          f" {counts['company_ats_tenant']})", file=out)
    print(f"companies ambiguous:      {counts['company_ambiguous_exact']}"
          f"  (name shared by more than one stored company; linked none)", file=out)
    print(f"descriptions resolved:    {counts['descriptions_resolved']}/"
          f"{counts['new_postings']} new  ({counts['descriptions_missing']} imported with"
          f" none; of {total} pool postings, {counts['skipped_duplicate']} were duplicates"
          f" and not read)", file=out)
    print(f"values attached:          {counts['values_attached']}", file=out)
    print(f"invalid-values skipped:   {counts['invalid_values_skipped']}", file=out)
    print(f"salary attached:          {counts['salary_attached']}"
          f"  ({counts['invalid_salary_skipped']} invalid, dropped)", file=out)
    print(f"jobs linked to a company: {counts['jobs_with_company']}"
          f"  ({counts['jobs_without_company']} with none, employer name kept as free text)",
          file=out)
    if counts['failed']:
        print(f"FAILED to import:         {counts['failed']}  (see the warnings above)", file=out)
    print('-' * 78, file=out)
    print('every imported job is ownerless and in_pipeline: false -- All jobs for '
          'everyone, on nobody\'s board', file=out)
    if dry_run:
        print('DRY RUN: nothing was written.', file=out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--pool', required=True, help='the golden-set pool export YAML')
    parser.add_argument('--classification', required=True,
                        help='the classification run YAML keyed by the same pool `key`')
    parser.add_argument('--vault', required=True, help='vault path to import into')
    parser.add_argument('--stores', default=None,
                        help='base directory holding the per-provider staging stores '
                             '(default: data/ats/<provider>, data/personio)')
    parser.add_argument('--dry-run', action='store_true',
                        help='print the report and write nothing')
    args = parser.parse_args(argv)

    root = Path(args.vault)
    if not (root / 'jobs').is_dir():
        raise SystemExit(f'{root} does not look like a CareerOS vault (missing jobs/)')

    with vault.WriteLock(root):
        counts = run(args.pool, args.classification, root,
                     dry_run=args.dry_run, base=args.stores)
    return 1 if counts['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
