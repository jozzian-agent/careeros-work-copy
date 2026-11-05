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
        universe = jobs_page.universe_context(root, owner, is_admin=True)
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


def test_a_dry_run_writes_nothing(root, people, files, capsys):
    before = sorted(path.name for path in root.rglob('*'))
    counts = script.run(files['pool'], files['classification'], root,
                        base=files['stores'], dry_run=True)
    assert counts['imported'] == 3
    assert counts['company_created'] == 2
    assert sorted(path.name for path in root.rglob('*')) == before
    assert vault.list_owned_jobs(root) == []
    assert vault.list_companies(root) == []
    # The rehearsal names the postings it would create, so "would create
    # 796" is five readable rows and not only a number.
    printed = capsys.readouterr().out
    assert 'sample (first 3):' in printed
    assert POOL_KEY in printed and SLUG_KEY in printed


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


# --- 5. the shipped descriptions (the VPS import path) -------------------
# On the VPS there are no frozen snapshots -- the export generation
# carries the text as data instead (descriptions.yaml, written by
# scripts/export_jobs_for_prod.py on the LAN host). These tests are about
# that file: what it is allowed to look like, which rows its coverage is
# measured over, and the floor an APPLY will not cross without being told
# to. The `--stores` path above is untouched by all of it.

def descriptions_file(tmp_path, mapping, *, wrapped=True, name='descriptions.yaml'):
    """One generation's descriptions.yaml. `wrapped` writes the shape the
    exporter writes (`day` + `descriptions`); False writes the bare
    mapping the loader also accepts."""
    path = tmp_path / name
    body = {'day': '2026-10-19', 'descriptions': mapping} if wrapped else mapping
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding='utf-8')
    return path


def test_load_descriptions_refuses_a_missing_file(tmp_path):
    """A caller that named a file meant it: the wrapper passes
    --descriptions only for a generation that carries one, so a missing
    file is a broken generation and not an empty mapping."""
    with pytest.raises(SystemExit) as refusal:
        script.load_descriptions(tmp_path / 'nothing-here.yaml')
    assert 'no such descriptions file' in str(refusal.value)


@pytest.mark.parametrize('wrapped', [True, False])
def test_load_descriptions_reads_either_shape(tmp_path, wrapped):
    path = descriptions_file(tmp_path, {POOL_KEY: POOL_DESCRIPTION}, wrapped=wrapped)
    assert script.load_descriptions(path) == {POOL_KEY: POOL_DESCRIPTION}


def test_load_descriptions_allows_an_empty_mapping(tmp_path):
    assert script.load_descriptions(descriptions_file(tmp_path, {})) == {}


@pytest.mark.parametrize('body', ['just a string\n', '- one\n- two\n',
                                  'descriptions:\n- one\n- two\n'])
def test_load_descriptions_refuses_content_that_is_not_a_mapping(tmp_path, body):
    path = tmp_path / 'descriptions.yaml'
    path.write_text(body)
    with pytest.raises(SystemExit):
        script.load_descriptions(path)


@pytest.mark.parametrize('value', [{'description': 'nested'}, ['one', 'two'],
                                   7, 1.5, None, True])
def test_load_descriptions_refuses_a_value_that_is_not_text(tmp_path, value):
    """Posting text is a string. `str()`-ing whatever else turned up would
    put `{'description': 'nested'}` or `None` on a job AS its posting
    text -- fake text no reader would recognise as a bug -- so the file
    is refused instead, naming the key that is wrong."""
    path = descriptions_file(tmp_path, {POOL_KEY: value})
    with pytest.raises(SystemExit) as refusal:
        script.load_descriptions(path)
    assert POOL_KEY in str(refusal.value)
    assert 'not text' in str(refusal.value)


def test_load_descriptions_refuses_a_non_text_value_even_beside_good_ones(tmp_path):
    """One bad value condemns the file rather than being dropped: a
    mapping this shape did not come from the exporter, and the rest of it
    has no more claim to being right."""
    path = descriptions_file(tmp_path, {POOL_KEY: POOL_DESCRIPTION, SIBLING_KEY: 42})
    with pytest.raises(SystemExit) as refusal:
        script.load_descriptions(path)
    assert SIBLING_KEY in str(refusal.value)


def test_load_descriptions_keeps_an_empty_string_value(tmp_path):
    """An empty string IS text (an export that resolved nothing for the
    key), so it loads; the coverage counter is what calls it missing."""
    assert script.load_descriptions(
        descriptions_file(tmp_path, {POOL_KEY: ''})) == {POOL_KEY: ''}


def test_load_descriptions_coerces_a_non_string_key(tmp_path):
    """YAML reads an all-digit key as an int, and a pool key is compared
    as a string, so the coercion stays."""
    path = tmp_path / 'descriptions.yaml'
    path.write_text("descriptions:\n  7001: Acme is hiring.\n")
    assert script.load_descriptions(path) == {'7001': 'Acme is hiring.'}


def test_load_descriptions_refuses_keys_that_collide_once_coerced(tmp_path):
    """`1` and `'1'` are two different YAML values that name one pool key
    after `str()`. Which of the two texts the row got would be an
    accident of mapping order, so the file is refused and both keys are
    named."""
    path = tmp_path / 'descriptions.yaml'
    path.write_text("descriptions:\n  1: 'text for the int key'\n"
                    "  '1': 'text for the string key'\n")
    with pytest.raises(SystemExit) as refusal:
        script.load_descriptions(path)
    message = str(refusal.value)
    assert 'keys 1 and ' in message          # the int key, named as itself
    assert "'1'" in message                  # and the string key
    assert 'accident of ordering' in message


def test_the_key_collision_is_a_real_collision_and_not_a_parse_quirk(tmp_path):
    """Non-vacuous half: YAML really does hand the loader two distinct
    keys here (safe_load collapses IDENTICAL keys, which is its call and
    not ours), so the refusal is about a choice the loader would
    otherwise have had to make."""
    path = tmp_path / 'descriptions.yaml'
    path.write_text("descriptions:\n  1: 'text for the int key'\n"
                    "  '1': 'text for the string key'\n")
    raw = yaml.safe_load(path.read_text())['descriptions']
    assert sorted(map(repr, raw)) == ["'1'", '1']
    assert len(raw) == 2


def test_the_shipped_text_lands_on_the_job(root, people, files, tmp_path, capsys):
    """The whole point: text the VPS could not have resolved itself is on
    the imported record, out of the file the generation carried."""
    shipped = {POOL_KEY: POOL_DESCRIPTION, SIBLING_KEY: 'Backend work in Zurich.',
               SLUG_KEY: 'Research in Zurich.'}
    counts = script.run(files['pool'], files['classification'], root,
                        descriptions_path=descriptions_file(tmp_path, shipped))
    assert counts['imported'] == 3
    assert (counts['descriptions_resolved'], counts['descriptions_missing']) == (3, 0)
    assert counts['descriptions_covered'] == 3
    landed = {job['source_id']: job for job in vault.list_owned_jobs(root)}
    assert {key: landed[key]['description'] for key in shipped} == shipped
    assert 'description coverage:     3/3 postings to import (100%)' in capsys.readouterr().out


def test_coverage_is_measured_over_the_postings_to_import_not_the_pool(
        root, people, files, tmp_path, capsys):
    """A duplicate's description is never read, so a mapping that covers
    every row that WILL be imported is full coverage even though it
    covers only two thirds of the pool -- 67% measured over the pool
    would refuse an apply that has nothing wrong with it."""
    vault.save_job(root, {'title': 'Mine', 'url': POOL_URL, 'status': 'applied',
                          vault.OWNER_FIELD: people['admin']['id']})
    shipped = {SIBLING_KEY: 'Backend work in Zurich.', SLUG_KEY: 'Research in Zurich.'}
    counts = script.run(files['pool'], files['classification'], root,
                        descriptions_path=descriptions_file(tmp_path, shipped))
    assert (counts['imported'], counts['skipped_duplicate']) == (2, 1)
    assert counts['descriptions_covered'] == 2
    assert 'description coverage:     2/2 postings to import (100%)' in capsys.readouterr().out


def test_descriptions_missing_counts_only_the_uncovered_rows(root, people, files, tmp_path):
    """The report's own counter still means what it always meant, and it
    is now a reading of the shipped mapping rather than of the stores."""
    counts = script.run(
        files['pool'], files['classification'], root, warn=lambda message: None,
        allow_low_descriptions=True,
        descriptions_path=descriptions_file(tmp_path, {POOL_KEY: POOL_DESCRIPTION,
                                                       SIBLING_KEY: 'Backend work.'}))
    assert (counts['descriptions_resolved'], counts['descriptions_missing']) == (2, 1)
    landed = next(job for job in vault.list_owned_jobs(root) if job['source_id'] == SLUG_KEY)
    assert landed['description'] == ''


def test_a_dry_run_at_low_coverage_warns_and_completes(root, people, files, tmp_path, capsys):
    """A rehearsal exists to SHOW this: it reports the collapse and runs
    to the end, so the owner sees the whole report before deciding."""
    warnings = []
    counts = script.run(files['pool'], files['classification'], root, dry_run=True,
                        descriptions_path=descriptions_file(tmp_path, {}),
                        warn=warnings.append)
    assert counts['imported'] == 3
    assert any('LOW DESCRIPTION COVERAGE' in message for message in warnings)
    assert 'description coverage:     0/3 postings to import (0%)' in capsys.readouterr().out
    assert vault.list_owned_jobs(root) == []


def vault_bytes(root):
    """Every file in the vault and its exact bytes.

    Names and record lists are not enough to prove "wrote nothing": an
    index file like `ids.yaml` can be rewritten in place, keeping its
    name and leaving the lists it feeds looking unchanged. Bytes are the
    only reading that cannot be satisfied by a near miss.
    """
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob('*')) if path.is_file()}


def test_an_apply_at_low_coverage_is_refused_and_writes_nothing(root, people, files, tmp_path):
    """The gate: below the floor an apply stops BEFORE the first write,
    so the vault is exactly as it was and a re-run after a fixed export
    is a first import rather than a repair."""
    before = vault_bytes(root)
    # The fixture vault really does carry the files this is about, so the
    # comparison below is not comparing two empty dicts.
    assert before, 'the fixture vault holds no files to compare'
    assert any(name.endswith('ids.yaml') for name in before), sorted(before)
    before_tree = sorted(str(path.relative_to(root)) for path in root.rglob('*'))
    with pytest.raises(SystemExit) as refusal:
        script.run(files['pool'], files['classification'], root,
                   descriptions_path=descriptions_file(tmp_path, {}),
                   warn=lambda message: None)
    assert 'refusing to APPLY' in str(refusal.value)
    assert '--allow-low-descriptions' in str(refusal.value)
    assert sorted(str(path.relative_to(root)) for path in root.rglob('*')) == before_tree
    assert vault_bytes(root) == before
    assert vault.list_owned_jobs(root) == []
    assert vault.list_companies(root) == []


def test_the_low_coverage_refusal_is_the_gate_and_not_the_fixture(
        root, people, files, tmp_path, monkeypatch):
    """The non-vacuous half of the test above: with the floor lowered,
    the SAME fixture imports cleanly. So the refusal is the gate's doing
    and nothing else about this generation is broken."""
    monkeypatch.setattr(script, 'DESCRIPTION_COVERAGE_FLOOR', 0.0)
    counts = script.run(files['pool'], files['classification'], root,
                        descriptions_path=descriptions_file(tmp_path, {}),
                        warn=lambda message: None)
    assert counts['imported'] == 3
    assert counts['descriptions_missing'] == 3
    assert [job['description'] for job in vault.list_owned_jobs(root)] == ['', '', '']


def test_allow_low_descriptions_applies_anyway(root, people, files, tmp_path):
    """The owner's explicit confirmation: import them with no text, which
    is a decision and not a default."""
    warnings = []
    counts = script.run(files['pool'], files['classification'], root,
                        descriptions_path=descriptions_file(tmp_path, {}),
                        allow_low_descriptions=True, warn=warnings.append)
    assert counts['imported'] == 3
    # Still loud about it: confirmed is not the same as fine.
    assert any('LOW DESCRIPTION COVERAGE' in message for message in warnings)
    assert len(vault.list_owned_jobs(root)) == 3


def test_coverage_at_the_floor_applies_without_confirmation(root, people, files, tmp_path):
    """95% is the floor and not a wall: a mapping at or above it is a
    normal import with no flag and no refusal."""
    document = yaml.safe_load(files['pool'].read_text())
    # 20 postings, 19 of them covered: exactly the floor.
    rows = [dict(document['postings'][0], key=f'greenhouse:acme:8{index:03d}',
                 url=f'https://job-boards.greenhouse.io/acme/jobs/8{index:03d}',
                 posting_id=f'8{index:03d}') for index in range(20)]
    files['pool'].write_text(yaml.safe_dump({'day': '2026-10-19', 'postings': rows},
                                            allow_unicode=True))
    shipped = {row['key']: POOL_DESCRIPTION for row in rows[:19]}
    counts = script.run(files['pool'], files['classification'], root,
                        descriptions_path=descriptions_file(tmp_path, shipped),
                        warn=lambda message: None)
    assert counts['imported'] == 20
    assert counts['descriptions_covered'] == 19


#: Three shipped values that are whitespace and nothing else, one per
#: fixture posting. Spaces, a tab-and-newlines run, and a single space:
#: all of them are "no posting text" however they are spelled.
WHITESPACE_ONLY = {POOL_KEY: '   ', SIBLING_KEY: '\n\t\n', SLUG_KEY: ' '}


def test_whitespace_only_text_is_missing_for_the_coverage_counter(
        root, people, files, tmp_path, capsys):
    """ONE rule for "has text", shared by the coverage counter and the
    per-row resolved/missing counters: non-empty after `.strip()`. A
    generation whose every value is whitespace is 0% coverage, not 100%,
    so a dry run says so instead of reporting a full house of blanks."""
    warnings = []
    counts = script.run(files['pool'], files['classification'], root, dry_run=True,
                        descriptions_path=descriptions_file(tmp_path, WHITESPACE_ONLY),
                        warn=warnings.append)
    assert counts['imported'] == 3
    assert counts['descriptions_covered'] == 0
    assert (counts['descriptions_resolved'], counts['descriptions_missing']) == (0, 3)
    assert any('LOW DESCRIPTION COVERAGE' in message for message in warnings)
    assert 'description coverage:     0/3 postings to import (0%)' in capsys.readouterr().out
    assert vault.list_owned_jobs(root) == []


def test_an_apply_on_whitespace_only_text_is_refused(root, people, files, tmp_path):
    """And the APPLY refuses, exactly as it does for an absent key: a
    mapping full of spaces is the same broken export, spelled with
    characters that happen to be non-empty."""
    before = vault_bytes(root)
    with pytest.raises(SystemExit) as refusal:
        script.run(files['pool'], files['classification'], root,
                   descriptions_path=descriptions_file(tmp_path, WHITESPACE_ONLY),
                   warn=lambda message: None)
    assert 'refusing to APPLY' in str(refusal.value)
    assert vault_bytes(root) == before


def test_whitespace_only_text_lands_as_an_empty_description(
        root, people, files, tmp_path, monkeypatch):
    """With the floor out of the way, the row still lands with an EMPTY
    description rather than three spaces: a job's body is text or it is
    nothing, and "nothing" is what the report already counted."""
    monkeypatch.setattr(script, 'DESCRIPTION_COVERAGE_FLOOR', 0.0)
    counts = script.run(files['pool'], files['classification'], root,
                        descriptions_path=descriptions_file(tmp_path, WHITESPACE_ONLY),
                        warn=lambda message: None)
    assert counts['descriptions_missing'] == 3
    assert [job['description'] for job in vault.list_owned_jobs(root)] == ['', '', '']


def test_text_that_has_text_keeps_its_own_bytes(root, people, files, tmp_path):
    """The other half of the rule: `.strip()` decides whether a value
    COUNTS, it does not rewrite a value that counts. A posting whose text
    opens and closes on a blank line arrives as the exporter shipped
    it."""
    padded = '\nAcme is hiring a platform engineer in Zurich.\n'
    shipped = dict(WHITESPACE_ONLY, **{POOL_KEY: padded})
    counts = script.run(files['pool'], files['classification'], root,
                        descriptions_path=descriptions_file(tmp_path, shipped),
                        allow_low_descriptions=True, warn=lambda message: None)
    assert (counts['descriptions_resolved'], counts['descriptions_missing']) == (1, 2)
    landed = next(job for job in vault.list_owned_jobs(root) if job['source_id'] == POOL_KEY)
    assert landed['description'] == padded


def test_a_whitespace_only_snapshot_is_missing_on_the_store_path_too(
        root, people, files, tmp_path):
    """The same rule on the LAN path, so the two halves of the system
    cannot disagree about what counts as a description: a snapshot
    holding only whitespace is a missing description there as well."""
    store = store_module.Store(files['stores'] / 'greenhouse', provider='greenhouse')
    path = store.posting_snapshot_path('acme', '7002', SIBLING_HASH)
    # Snapshots are immutable by design, so the fixture's one is removed
    # rather than rewritten.
    store_module.stored_path(path).unlink()
    store.write_snapshot(path, yaml.safe_dump({'snapshot_id': SIBLING_KEY,
                                               'content_hash': SIBLING_HASH,
                                               'posting': {'description': '   \n  '}}))
    counts = script.run(files['pool'], files['classification'], root,
                        base=files['stores'], warn=lambda message: None)
    # Was (2, 1) with the sibling's real text: the whitespace snapshot
    # moved it from resolved to missing.
    assert (counts['descriptions_resolved'], counts['descriptions_missing']) == (1, 2)
    landed = next(job for job in vault.list_owned_jobs(root) if job['source_id'] == SIBLING_KEY)
    assert landed['description'] == ''


def test_the_store_path_is_untouched_when_no_descriptions_are_shipped(root, people, files,
                                                                     capsys):
    """The LAN import reads snapshots exactly as before: no coverage
    line, no gate, no flag -- the new code is reached only by a caller
    that names a descriptions file."""
    counts = script.run(files['pool'], files['classification'], root, base=files['stores'],
                        warn=lambda message: None)
    assert (counts['descriptions_resolved'], counts['descriptions_missing']) == (2, 1)
    assert 'descriptions_covered' not in counts
    printed = capsys.readouterr().out
    assert 'description coverage:' not in printed
    landed = next(job for job in vault.list_owned_jobs(root) if job['source_id'] == POOL_KEY)
    assert landed['description'] == POOL_DESCRIPTION


def test_main_wires_the_descriptions_flags(root, people, files, tmp_path):
    """The two flags the VPS wrapper passes, through argparse and into
    run(): the path is read, and the confirmation gets through."""
    path = descriptions_file(tmp_path, {POOL_KEY: POOL_DESCRIPTION})
    assert script.main(['--pool', str(files['pool']),
                        '--classification', str(files['classification']),
                        '--vault', str(root), '--descriptions', str(path),
                        '--allow-low-descriptions']) == 0
    landed = {job['source_id']: job for job in vault.list_owned_jobs(root)}
    assert landed[POOL_KEY]['description'] == POOL_DESCRIPTION
    assert landed[SLUG_KEY]['description'] == ''


def test_main_refuses_a_low_coverage_apply_without_the_flag(root, people, files, tmp_path):
    path = descriptions_file(tmp_path, {})
    with pytest.raises(SystemExit):
        script.main(['--pool', str(files['pool']),
                     '--classification', str(files['classification']),
                     '--vault', str(root), '--descriptions', str(path)])
    assert vault.list_owned_jobs(root) == []


def load_exporter():
    """scripts/export_jobs_for_prod.py, loaded by path like the import
    script above. Used by the one end-to-end test below, which is the
    only place the two scripts meet."""
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'export_jobs_for_prod.py'
    spec = importlib.util.spec_from_file_location('export_jobs_for_prod', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_snapshot_reaches_the_vault_through_a_real_export_generation(
        root, people, files, tmp_path):
    """The whole path this change exists for, end to end: a frozen ATS
    snapshot on the LAN host -> the exporter's descriptions.yaml -> an
    import that is given NO store tree at all (the VPS's world) -> the
    posting text on the job.

    Each half has its own tests above; this one is the seam between
    them, which is where a disagreement about key shape, field name or
    document wrapper would hide and nothing else would catch it.
    """
    exporter = load_exporter()
    lan_vault = tmp_path / 'lan-vault'           # nothing owned yet, so nothing is excluded
    (lan_vault / 'jobs').mkdir(parents=True)
    generation = tmp_path / 'generation'
    assert exporter.main(['--pool', str(files['pool']),
                          '--classification', str(files['classification']),
                          '--vault', str(lan_vault), '--out', str(generation),
                          '--stores', str(files['stores'])]) == 0

    shipped = yaml.safe_load((generation / 'descriptions.yaml').read_text())
    assert shipped['descriptions'][POOL_KEY] == POOL_DESCRIPTION

    # The import runs with no `base=`: the default store roots resolve
    # against this test's working directory and hold nothing, which is
    # the VPS's situation. Any text that lands came from the generation.
    counts = script.run(generation / 'pool.yaml', generation / 'classification.yaml', root,
                        descriptions_path=generation / 'descriptions.yaml',
                        allow_low_descriptions=True, warn=lambda message: None)
    assert counts['imported'] == 3
    landed = {job['source_id']: job for job in vault.list_owned_jobs(root)}
    assert landed[POOL_KEY]['description'] == POOL_DESCRIPTION
    assert landed[SIBLING_KEY]['description'] == 'Backend work in Zurich.'
    # NormalComputing's snapshot is deliberately absent from the fixture
    # store, so the generation carries no text for it and prod says so
    # rather than borrowing another posting's.
    assert landed[SLUG_KEY]['description'] == ''
    assert (counts['descriptions_resolved'], counts['descriptions_missing']) == (2, 1)


def test_the_end_to_end_text_really_came_from_the_generation(root, people, files, tmp_path):
    """Non-vacuous half of the test above: the same import with the
    generation's descriptions.yaml emptied lands three blank
    descriptions. So the text in that test travelled through the file
    and was not resolved locally by some fallback."""
    exporter = load_exporter()
    lan_vault = tmp_path / 'lan-vault'
    (lan_vault / 'jobs').mkdir(parents=True)
    generation = tmp_path / 'generation'
    assert exporter.main(['--pool', str(files['pool']),
                          '--classification', str(files['classification']),
                          '--vault', str(lan_vault), '--out', str(generation),
                          '--stores', str(files['stores'])]) == 0
    (generation / 'descriptions.yaml').write_text(
        yaml.safe_dump({'day': '2026-10-19', 'descriptions': {}}))
    counts = script.run(generation / 'pool.yaml', generation / 'classification.yaml', root,
                        descriptions_path=generation / 'descriptions.yaml',
                        allow_low_descriptions=True, warn=lambda message: None)
    assert counts['descriptions_resolved'] == 0
    assert [job['description'] for job in vault.list_owned_jobs(root)] == ['', '', '']


# --- 6. the small readings the rest of this rests on --------------------

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
