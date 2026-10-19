"""The ATS pool in a vault: universe-only jobs and the board filter.

Two halves of CAREER-72/74, in the order a reader needs them.

1. **The board filter.** An imported posting is ownerless AND carries
   `in_pipeline: false`. Ownerless alone is not enough: the admin
   inherits every ownerless record (`vault.Owner`), so without the
   second half their own board would hold 704 postings nobody added.
   `vault.on_board` is the one reading of that flag and
   `vault.list_jobs` is the one board read; every caller that wants
   something else says so by name. These tests pin each caller's
   choice, because "which list does this surface read" is exactly the
   kind of decision that drifts.

2. **The import itself** (`scripts/import_pool_to_vault.py`): what it
   writes, what it refuses to touch, and that running it twice imports
   nothing the second time.

Every vault here is a tmp_path vault. Nothing in this file reads or
writes the live one.
"""
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from careeros import dedupe, enrich, server, taxonomy, users, vault, watcher
from careeros.feeds import store as store_module
from careeros.web.pages import companies as companies_page
from careeros.web.pages import jobs as jobs_page
from careeros.web.pages import notes as notes_page

PASSWORD = 'correct horse battery staple'

#: One pool posting's identity, repeated across the fixtures below.
POOL_KEY = 'greenhouse:acme:7001'
POOL_URL = 'https://job-boards.greenhouse.io/acme/jobs/7001'
POOL_HASH = 'a' * 64
POOL_DESCRIPTION = 'Acme is hiring a platform engineer in Zurich.'

#: A second posting at the same tenant that states no employer name, so
#: the tenant-name inference and the one-company-per-tenant answer are
#: both exercised.
SIBLING_KEY = 'greenhouse:acme:7002'
SIBLING_URL = 'https://job-boards.greenhouse.io/acme/jobs/7002'
SIBLING_HASH = 'b' * 64

#: A posting whose tenant states no name at all anywhere in the pool, so
#: the company it creates is named from the tenant slug.
SLUG_KEY = 'ashby:NormalComputing:9001'
SLUG_URL = 'https://jobs.ashbyhq.com/NormalComputing/9001'
SLUG_HASH = 'c' * 64


def load_script():
    """The import script, loaded by path: `scripts/` is not a package."""
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'import_pool_to_vault.py'
    spec = importlib.util.spec_from_file_location('import_pool_to_vault', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = load_script()


# --- fixtures: a vault, two people, and a pool to import -----------------

@pytest.fixture
def root(tmp_path):
    root = tmp_path / 'vault'
    (root / 'jobs').mkdir(parents=True)
    return root


@pytest.fixture
def people(root):
    return {
        'admin': users.create_user(root, email='owner@example.test', name='Owner',
                                   role='admin', password=PASSWORD),
        'tester': users.create_user(root, email='friend@example.test', name='Friend',
                                    role='tester', password=PASSWORD),
    }


@pytest.fixture
def owners(people):
    return {key: users.owner(user) for key, user in people.items()}


@pytest.fixture
def clients(root, people, raw_session):
    """One signed-in client per user, through the real login, because
    "for the admin too" is the whole point of the board filter."""
    app = server.create_app(root)
    app.config['TESTING'] = True
    built = {}
    for key, user in people.items():
        client = app.test_client()
        assert client.post('/login', json={'email': user['email'],
                                           'password': PASSWORD}).status_code == 200
        built[key] = client
    return built


def pool_row(key, url, content_hash, *, tenant, provider, posting_id, company=None, **extra):
    """One pool export row, with the fields the import reads."""
    return {
        'key': key, 'url': url, 'content_hash': content_hash,
        'provider': provider, 'tenant': tenant, 'posting_id': posting_id,
        'company': company, 'title': extra.pop('title', 'Platform Engineer'),
        'municipality_label': extra.pop('municipality_label', 'Zürich'),
        'published_at': extra.pop('published_at', '2026-10-15T17:05:29.750+00:00'),
        'has_salary': extra.pop('has_salary', False),
        'feed_url': extra.pop('feed_url', f'https://boards.example/{tenant}/jobs'),
        **extra,
    }


@pytest.fixture
def pool_rows():
    return [
        pool_row(POOL_KEY, POOL_URL, POOL_HASH, provider='greenhouse', tenant='acme',
                 posting_id='7001', company='Acme Industries AG'),
        pool_row(SIBLING_KEY, SIBLING_URL, SIBLING_HASH, provider='greenhouse', tenant='acme',
                 posting_id='7002', title='Backend Engineer'),
        pool_row(SLUG_KEY, SLUG_URL, SLUG_HASH, provider='ashby', tenant='NormalComputing',
                 posting_id='9001', title='Research Engineer', has_salary=True),
    ]


def value_records():
    """A small but real `values` block, built by the one factory (D4)."""
    return {
        'language': taxonomy.make_value_record('language', 'en', 'feed', confidence=0.9),
        'municipality': taxonomy.make_value_record('municipality', '261', 'feed',
                                                   confidence=0.9),
    }


def salary_block():
    return {
        'min': 120000.0, 'max': 140000.0, 'currency': 'CHF', 'period_stated': 'year',
        'months_assumed': 12, 'pensum_stated': [100, 100],
        'annual_gross_chf_min': 120000.0, 'annual_gross_chf_max': 140000.0,
        'quote': 'CHF 120 000 - 140 000', 'rules': [], 'needs_review': None,
        'source': 'rule', 'confidence': 0.8, 'classified_at': '2026-10-19T08:47:36+00:00',
        'flags': [],
    }


@pytest.fixture
def files(tmp_path, pool_rows):
    """The two run files and the snapshot store the import reads.

    Written through `store_module` itself rather than by hand, so the
    snapshot path the import resolves is the one the fetch pipeline
    writes and the test cannot pass against a layout nothing produces.
    """
    stores = tmp_path / 'stores'
    for provider, tenant, posting_id, content_hash, text in (
            ('greenhouse', 'acme', '7001', POOL_HASH, POOL_DESCRIPTION),
            ('greenhouse', 'acme', '7002', SIBLING_HASH, 'Backend work in Zurich.'),
            # NormalComputing's snapshot is deliberately absent, so the
            # "import it anyway with an empty description" path is
            # covered rather than assumed.
    ):
        store = store_module.Store(stores / provider, provider=provider)
        store.write_snapshot(store.posting_snapshot_path(tenant, posting_id, content_hash),
                             yaml.safe_dump({'snapshot_id': f'{provider}:{tenant}:{posting_id}',
                                             'content_hash': content_hash,
                                             'posting': {'description': text}}))
    pool = tmp_path / 'pool.yaml'
    pool.write_text(yaml.safe_dump({'day': '2026-10-19', 'postings': pool_rows},
                                   allow_unicode=True))
    classification = tmp_path / 'classification.yaml'
    classification.write_text(yaml.safe_dump({'day': '2026-10-19', 'postings': [
        {'key': POOL_KEY, 'values': value_records(), 'salary': None},
        {'key': SIBLING_KEY, 'values': value_records(), 'salary': None},
        {'key': SLUG_KEY, 'values': value_records(), 'salary': salary_block()},
    ]}, allow_unicode=True))
    return {'pool': pool, 'classification': classification, 'stores': stores}


def run_import(root, files, *, dry_run=False):
    argv = ['--pool', str(files['pool']), '--classification', str(files['classification']),
            '--vault', str(root), '--stores', str(files['stores'])]
    if dry_run:
        argv.append('--dry-run')
    assert script.main(argv) == 0
    return vault.list_owned_jobs(root)


@pytest.fixture
def imported(root, people, files):
    run_import(root, files)
    return {job['source_id']: job for job in vault.list_owned_jobs(root) if job.get('source_id')}


# --- 1. the board filter -------------------------------------------------

def test_an_imported_job_is_ownerless_and_universe_only(imported):
    for job in imported.values():
        assert vault.OWNER_FIELD in job and job[vault.OWNER_FIELD] is None
        assert job['in_pipeline'] is False
        assert vault.on_board(job) is False
        assert job['origin'] == 'discovered'


def test_the_board_excludes_universe_only_records_for_every_reader(root, owners, imported):
    """Including the admin's. D3 is privacy and not hierarchy, and this
    is not even privacy: an ownerless record IS the admin's, and it
    still does not belong on a board nobody put it on."""
    for key, owner in owners.items():
        assert vault.list_jobs(root, owner) == [], key
    # Unscoped too, which is what the migration scripts and the cron
    # watcher read under.
    assert vault.list_jobs(root) == []


def test_all_jobs_includes_universe_only_records_for_every_reader(root, owners, imported):
    for key, owner in owners.items():
        listed = {job['source_id'] for job in vault.list_universe_jobs(root, owner)}
        assert listed == set(imported), key


def test_the_board_payload_is_empty_and_the_all_jobs_payload_is_not(clients, imported):
    for key, client in clients.items():
        board = client.get('/api/jobs?view=board').get_json()
        universe = client.get('/api/jobs?view=universe').get_json()
        assert board['entries'] == [], key
        assert {entry['source_id'] for entry in universe['entries']} == set(imported), key


def test_a_real_board_job_survives_the_filter(root, owners, people, imported, clients):
    """The filter is about the flag and nothing else: the reader's own
    board job is still there, and still the only thing on the board."""
    mine = vault.save_job(root, {'title': 'My Own Role', 'url': 'https://example.test/mine',
                                 vault.OWNER_FIELD: people['tester']['id']})
    assert [job['id'] for job in vault.list_jobs(root, owners['tester'])] == [mine['id']]
    assert [job['id'] for job in vault.list_jobs(root, owners['admin'])] == []
    entries = clients['tester'].get('/api/jobs?view=board').get_json()['entries']
    assert [entry['id'] for entry in entries] == [mine['id']]


def test_all_jobs_offers_add_to_my_jobs_on_a_pool_posting_even_to_the_admin(clients, imported):
    """The admin owns an ownerless record by inheritance, so ownership
    alone would tell them a posting they have never seen is already on
    their board -- and would offer a status select in place of the one
    action that actually puts it there."""
    for key, client in clients.items():
        entries = client.get('/api/jobs?view=universe').get_json()['entries']
        assert {entry['on_my_board'] for entry in entries} == {False}, key


def test_adding_a_pool_posting_puts_it_on_the_admins_board(clients, root, imported, owners):
    job = imported[POOL_KEY]
    response = clients['admin'].post(f"/api/jobs/{job['id']}/promote")
    assert response.status_code == 200
    assert response.get_json()['in_pipeline'] is True
    assert [stored['id'] for stored in vault.list_jobs(root, owners['admin'])] == [job['id']]
    # And it is still on everybody's All jobs tab, still ownerless.
    assert vault.load_job(root, job['id'])[vault.OWNER_FIELD] is None
    assert job['id'] in [entry['id'] for entry in
                         clients['tester'].get('/api/jobs?view=universe').get_json()['entries']]


def test_adding_a_pool_posting_copies_it_for_a_tester(clients, root, imported, owners, people):
    job = imported[POOL_KEY]
    response = clients['tester'].post(f"/api/jobs/{job['id']}/promote")
    assert response.status_code == 201
    copy = response.get_json()
    assert copy['id'] != job['id']
    assert copy[vault.OWNER_FIELD] == people['tester']['id']
    assert copy['in_pipeline'] is True
    assert [stored['id'] for stored in vault.list_jobs(root, owners['tester'])] == [copy['id']]
    # The posting it copied is untouched: still ownerless, still
    # universe-only (D4, ownership never moves).
    stored = vault.load_job(root, job['id'])
    assert (stored[vault.OWNER_FIELD], stored['in_pipeline']) == (None, False)


# --- 2. every other list_jobs caller, pinned ----------------------------

def test_the_company_open_jobs_count_is_the_universe_and_counts_pool_jobs(root, owners, imported):
    """B3: the chip on a company card counts the universe's open jobs, so
    an imported posting counts. It is the one count that should."""
    company_id = imported[POOL_KEY]['company_id']
    assert company_id
    for key, owner in owners.items():
        counts = companies_page.page_context(root, owner)['counts']
        assert counts[company_id] == 2, key


def test_the_company_profile_job_section_stays_the_readers_own_board(root, owners, imported):
    """It says My Jobs and means it (B3), so a universe-only posting at
    this company is not listed there even though the card counts it."""
    company_id = imported[POOL_KEY]['company_id']
    for key, owner in owners.items():
        context = companies_page.detail_context(root, company_id, owner)
        assert context['entries'] == [], key


def test_closed_review_and_search_so_far_never_count_a_universe_only_record(root, owners,
                                                                           imported):
    """Both are about one person's own search. A posting nobody added has
    no closed posting to ask about and never applied to anything."""
    long_ago = (date.today() - timedelta(days=30)).isoformat()
    for job in imported.values():
        vault.save_job(root, {'closed': True, 'closed_at': long_ago,
                              'status': 'interviewing'}, job['id'])
    for key, owner in owners.items():
        universe = jobs_page.universe_context(root, owner)
        assert universe['closed_review'] == [], key
        assert universe['search_so_far'] == {'applied_to': 0, 'interviews': 0, 'offers': 0}, key
        # And the open/ended split, which IS about the postings in front
        # of the reader, still counts every one of them.
        assert universe['counts'] == {'open': len(imported), 'ended': 0}, key


def test_the_notes_page_job_half_is_the_board(root, owners, imported):
    for job in imported.values():
        vault.save_job(root, vault.notes_payload(
            [vault.new_note('Pool note', 'Body.')]), job['id'])
    for key, owner in owners.items():
        assert notes_page.page_context(root, owner)['notes'] == [], key


def test_the_watcher_sweeps_boards_and_not_the_pool(root, imported):
    """A watch event notifies a person about their own job and sets a
    flag on their card. A universe-only record has neither, and the feed
    pipeline already tracks whether a pool posting is live."""
    def never(url):
        raise AssertionError(f'the watcher fetched a universe-only posting: {url}')

    assert watcher.scan(root, fetch=never) == []


def test_the_duplicate_check_still_finds_a_universe_only_record(root, owners, imported):
    """The one caller that must see past the board filter: a pasted link
    matching a pool posting is offered for promotion, never added twice."""
    job = imported[POOL_KEY]
    found, basis = dedupe.find_duplicate(root, job['normalized_url'], None, owners['admin'])
    assert (found['id'], basis) == (job['id'], 'same_url')
    assert dedupe.duplicate_payload(found, basis)['actions'] == [
        'promote', 'open_existing', 'add_anyway']


def test_the_company_rollup_derives_nothing_from_a_universe_only_record(root, imported):
    """`enrich.shared_jobs` reads boards, so 704 postings nobody has
    looked at add not one derived fact to a shared company -- and
    `vault.save_job` skips the regeneration it could not change."""
    assert enrich.shared_jobs(root) == []
    company = vault.load_company(root, imported[POOL_KEY]['company_id'])
    assert company.get('enrichment') in (None, {})


def test_deleting_a_company_the_pool_links_tombstones_it(root, clients, imported):
    """The admin's own links decide the 409 and every stored record
    decides tombstone against hard delete. A pool posting is not a
    conflict they can act on, and is exactly what the tombstone exists
    for: a hard delete would leave it pointing at nothing."""
    company_id = imported[POOL_KEY]['company_id']
    response = clients['admin'].delete(f'/api/companies/{company_id}')
    assert response.status_code == 200, response.get_data(as_text=True)
    stored = vault.load_company(root, company_id)
    assert stored is not None and vault.is_retired(stored)
    # The imported job still resolves its link and still saves.
    assert vault.save_job(root, {'status': 'interested'}, imported[POOL_KEY]['id'])


# --- 3. what the import writes -------------------------------------------

def test_the_import_creates_a_job_and_its_company(root, people, files):
    jobs = {job['source_id']: job for job in run_import(root, files)}
    assert sorted(jobs) == sorted([POOL_KEY, SIBLING_KEY, SLUG_KEY])
    job = jobs[POOL_KEY]
    assert job['title'] == 'Platform Engineer'
    assert job['url'] == POOL_URL
    assert job['location'] == 'Zürich'
    assert job['posted_date'] == '2026-10-15'
    assert job['source'] == 'greenhouse:acme'
    assert job['status'] == 'new'
    assert job['added'] == date.today().isoformat()
    assert job['ingest_state'] == 'complete'
    assert job['description'] == POOL_DESCRIPTION
    assert job['salary_info'] is False
    assert job['ats_provider'] == 'greenhouse'
    assert job['ats_tenant'] == 'acme'
    assert job['ats_posting_id'] == '7001'
    assert job['normalized_url']
    company = vault.load_company(root, job['company_id'])
    assert company['name'] == 'Acme Industries AG'
    assert company['kind'] == 'employer'
    assert company['name_source'] == 'auto'
    assert company['locations'] == ['Zürich']
    assert {identifier['value'] for identifier in company['identifiers']} == {
        'greenhouse:acme'}
    assert [source['kind'] for source in company['sources']] == ['ats_feed']
    assert job['company_link_state'] == 'linked'


def test_values_validate_and_salary_attaches(root, people, files):
    jobs = {job['source_id']: job for job in run_import(root, files)}
    assert sorted(jobs[POOL_KEY]['values']) == ['language', 'municipality']
    assert jobs[POOL_KEY]['values']['language']['value'] == 'en'
    assert jobs[POOL_KEY]['salary'] is None
    assert jobs[SLUG_KEY]['salary']['annual_gross_chf_min'] == 120000.0
    # Validated on the way in, so a stored record always holds a legal
    # block: the vault would refuse one that is not.
    assert vault.validate_value_records(jobs[POOL_KEY]['values'])
    assert vault.validate_salary(jobs[SLUG_KEY]['salary'])


def test_an_invalid_values_block_is_dropped_with_a_warning_and_the_job_still_lands(
        root, people, files):
    """The pipeline produced these blocks, so they are expected to pass.
    The run must not die 300 postings in if one does not."""
    document = yaml.safe_load(files['classification'].read_text())
    document['postings'][0]['values'] = {'language': {'value': 'en'}}
    files['classification'].write_text(yaml.safe_dump(document, allow_unicode=True))
    warnings = []
    counts = script.run(files['pool'], files['classification'], root,
                        base=files['stores'], warn=warnings.append)
    assert counts['invalid_values_skipped'] == 1
    assert counts['imported'] == 3
    assert any(POOL_KEY in message for message in warnings)
    landed = next(job for job in vault.list_owned_jobs(root) if job['source_id'] == POOL_KEY)
    assert landed['values'] == {}
    assert landed['title'] == 'Platform Engineer'


def test_a_posting_with_no_snapshot_is_imported_with_an_empty_description(root, people, files):
    counts = script.run(files['pool'], files['classification'], root, base=files['stores'],
                        warn=lambda message: None)
    assert counts['descriptions_resolved'] == 2
    assert counts['descriptions_missing'] == 1
    landed = next(job for job in vault.list_owned_jobs(root) if job['source_id'] == SLUG_KEY)
    assert landed['description'] == ''


def test_a_tenant_that_states_one_employer_name_lends_it_to_its_other_postings(root, people,
                                                                              files):
    """Two postings on one tenant, one of which names the employer: both
    land on that one company rather than one of them inventing a second
    named after the slug."""
    jobs = {job['source_id']: job for job in run_import(root, files)}
    assert jobs[SIBLING_KEY]['company_id'] == jobs[POOL_KEY]['company_id']
    assert len(vault.list_companies(root)) == 2


def test_a_tenant_that_states_no_name_is_named_from_its_slug(root, people, files):
    jobs = {job['source_id']: job for job in run_import(root, files)}
    company = vault.load_company(root, jobs[SLUG_KEY]['company_id'])
    # The slug's own capitals are kept: .title() would write Normalcomputing.
    assert company['name'] == 'NormalComputing'
    assert company['name_source'] == 'auto'


def test_an_existing_company_is_linked_and_never_written_to(root, people, files):
    """CAREER-74's find half, and the D4 half of it: a company this
    import finds keeps every field exactly as the owner left it."""
    existing = vault.save_company(root, {'name': 'ACME Industries AG', 'sectors': ['J'],
                                         'size_class': 'small', 'locations': ['Bern'],
                                         'notes': 'Owner notes'})
    before = vault.load_company(root, existing['id'])
    counts = script.run(files['pool'], files['classification'], root, base=files['stores'])
    assert counts['company_name_exact'] == 1
    jobs = {job['source_id']: job for job in vault.list_owned_jobs(root)}
    assert jobs[POOL_KEY]['company_id'] == existing['id']
    assert jobs[POOL_KEY]['company_link_reason'] == 'name_exact'
    assert vault.load_company(root, existing['id']) == before


def test_a_name_more_than_one_stored_company_holds_links_nothing(root, people, files):
    """The owner's 2026-10-12 ruling: duplicate exact names are a review
    and never a first-wins. With nobody to review 704 rows the import
    links neither, and the posting keeps the employer name as free text."""
    vault.save_company(root, {'name': 'Acme Industries AG'})
    vault.save_company(root, {'name': 'ACME Industries  AG'})
    counts = script.run(files['pool'], files['classification'], root, base=files['stores'],
                        warn=lambda message: None)
    assert counts['company_ambiguous_exact'] == 1
    job = next(job for job in vault.list_owned_jobs(root) if job['source_id'] == POOL_KEY)
    assert job['company_id'] is None
    assert job['company_link_state'] == 'pending'
    assert job['company'] == 'Acme Industries AG'


def test_a_company_holding_the_ats_tenant_identifier_is_linked_not_duplicated(root, people,
                                                                              files):
    """The rung the pool can reach in place of the domain match it
    cannot: a company intake already placed under another spelling is
    found by its tenant rather than doubled."""
    existing = vault.save_company(root, {
        'name': 'Acme Group', 'identifiers': [
            {'type': 'ats_tenant', 'value': 'greenhouse:acme', 'provenance': 'scrape'}]})
    counts = script.run(files['pool'], files['classification'], root, base=files['stores'])
    assert counts['company_ats_tenant'] == 1
    jobs = {job['source_id']: job for job in vault.list_owned_jobs(root)}
    assert jobs[POOL_KEY]['company_id'] == existing['id']
    assert jobs[POOL_KEY]['company_link_reason'] == 'ats_tenant'


def test_a_retired_company_is_not_matched(root, people, files):
    """A retired company takes no new link from anybody (M2 soft
    retire), so matching one would only produce a link save_job refuses."""
    retired = vault.save_company(root, {'name': 'Acme Industries AG'})
    vault.retire_company(root, retired['id'])
    counts = script.run(files['pool'], files['classification'], root, base=files['stores'])
    assert counts['company_created'] == 2
    job = next(job for job in vault.list_owned_jobs(root) if job['source_id'] == POOL_KEY)
    assert job['company_id'] != retired['id']


# --- 4. idempotence and safety ------------------------------------------

def test_a_second_run_imports_nothing(root, people, files):
    first = run_import(root, files)
    companies_before = vault.list_companies(root)
    counts = script.run(files['pool'], files['classification'], root, base=files['stores'])
    assert counts['imported'] == 0
    assert counts['skipped_duplicate'] == 3
    assert counts['skipped_source_id'] == 3
    assert vault.list_companies(root) == companies_before
    assert [job['id'] for job in vault.list_owned_jobs(root)] == [job['id'] for job in first]


def test_a_second_run_dedupes_on_the_url_when_the_source_id_is_gone(root, people, files):
    """Both keys, independently: a record that lost its `source_id` (a
    hand edit, an older import) is still found by its link."""
    run_import(root, files)
    job = next(job for job in vault.list_owned_jobs(root) if job['source_id'] == POOL_KEY)
    vault.save_job(root, {'source_id': None}, job['id'])
    counts = script.run(files['pool'], files['classification'], root, base=files['stores'])
    assert counts['imported'] == 0
    assert (counts['skipped_source_id'], counts['skipped_url']) == (2, 1)


def test_two_pool_rows_sharing_one_url_land_once(root, people, files, pool_rows):
    """35 of the 2026-10-19 export's 704 rows are one posting read under
    two spellings of its tenant, so they carry two keys and one url."""
    document = yaml.safe_load(files['pool'].read_text())
    twin = dict(document['postings'][0], key='greenhouse:ACME:7001', tenant='ACME')
    document['postings'].append(twin)
    files['pool'].write_text(yaml.safe_dump(document, allow_unicode=True))
    counts = script.run(files['pool'], files['classification'], root, base=files['stores'])
    assert (counts['imported'], counts['skipped_url']) == (3, 1)
    assert [job['url'] for job in vault.list_owned_jobs(root)].count(POOL_URL) == 1


def test_an_owner_job_with_the_same_url_wins_and_is_not_touched(root, people, files, owners):
    """D4: the owner's own 44 real jobs win. Their record keeps its
    owner, its status, its date and its text, and no second record for
    the same posting appears beside it."""
    mine = vault.save_job(root, {
        'title': 'My own reading of this posting', 'url': POOL_URL, 'status': 'applied',
        'description': 'The owner read this one themselves.',
        vault.OWNER_FIELD: people['admin']['id']})
    before = vault.load_job(root, mine['id'])
    counts = script.run(files['pool'], files['classification'], root, base=files['stores'])
    assert counts['imported'] == 2
    assert counts['skipped_url'] == 1
    assert vault.load_job(root, mine['id']) == before
    assert [job['url'] for job in vault.list_owned_jobs(root)].count(POOL_URL) == 1
    # And it is still on their board and still theirs.
    assert [job['id'] for job in vault.list_jobs(root, owners['admin'])] == [mine['id']]


def test_a_dry_run_writes_nothing(root, people, files):
    before = sorted(path.name for path in root.rglob('*'))
    counts = script.run(files['pool'], files['classification'], root,
                        base=files['stores'], dry_run=True)
    assert counts['imported'] == 3
    assert counts['company_created'] == 2
    assert sorted(path.name for path in root.rglob('*')) == before
    assert vault.list_owned_jobs(root) == []
    assert vault.list_companies(root) == []


def test_the_import_stamps_no_owner_on_anything(root, people, files):
    run_import(root, files)
    for job in vault.list_owned_jobs(root):
        assert job[vault.OWNER_FIELD] is None
    # And nothing it wrote is visible on a tester's board by any route.
    assert vault.list_jobs(root, users.owner(people['tester'])) == []


def test_the_report_prints_the_numbers_the_ticket_asks_for(root, people, files, capsys):
    script.run(files['pool'], files['classification'], root, base=files['stores'])
    printed = capsys.readouterr().out
    for line in ('imported:', 'skipped-duplicate:', 'companies created:', 'companies linked:',
                 'descriptions resolved:', 'values attached:', 'invalid-values skipped:'):
        assert line in printed


# --- 5. the small readings the rest of this rests on --------------------

@pytest.mark.parametrize('stored, expected', [
    ({}, True),
    ({'in_pipeline': True}, True),
    ({'in_pipeline': None}, True),
    ({'in_pipeline': False}, False),
])
def test_on_board_reads_only_an_explicit_false(stored, expected):
    """Every record written before the flag, and every record the vault
    writes with its own default, is a board entry."""
    assert vault.on_board(stored) is expected


@pytest.mark.parametrize('value, expected', [
    ('2026-10-15T17:05:29.750+00:00', '2026-10-15'),
    ('2026-10-13 14:05:35 UTC', '2026-10-13'),
    ('2026-10-13', '2026-10-13'),
    (None, None),
    ('', None),
    ('not a date', None),
    ('2026-13-99T00:00:00+00:00', None),
])
def test_posted_date_reads_the_day_out_of_either_shape(value, expected):
    assert script.posted_date(value) == expected


@pytest.mark.parametrize('slug, expected', [
    ('AFRY', 'AFRY'),
    ('OpenAI', 'OpenAI'),
    ('NormalComputing', 'NormalComputing'),
    ('blp-digital', 'Blp Digital'),
    ('air_apps', 'Air Apps'),
    ('60secondstonapoli', '60secondstonapoli'),
    ('', ''),
])
def test_tenant_label_keeps_a_slugs_own_capitals(slug, expected):
    assert script.tenant_label(slug) == expected
