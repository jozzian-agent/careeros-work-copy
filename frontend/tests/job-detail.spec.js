// Protects the Job detail page's layout and every action on it: the one
// ask it makes of its owner, the AI provenance labels, the extraction
// detail popup, the read-only Fit placeholder and the editing paths.
import { expect, test } from '@playwright/test';
import {
  loadFixture,
  loadBoardFixture,
  mockBoard,
  mockCheckPosting,
  mockJobPage,
  mockJobTaxonomy,
  mockPasteDescription,
  mockResolveReview,
  mockRetry,
  mockUpdate,
  mockDelete,
} from './helpers.js';

const fixture = loadFixture('job-detail');
const taxonomy = loadFixture('job-taxonomy');
const review = loadFixture('job-review-candidates');

// A job whose company is unresolved, with the three candidates the canvas
// layout has to survive.
const companyReview = {
  ...fixture,
  job: { ...fixture.job, company_link_state: 'needs_review', company_review: review, employer_named_in_posting: 'Northwind' },
  needs_input: { kind: 'company', review },
};

const readFailed = {
  ...fixture,
  job: {
    ...fixture.job,
    description: '',
    ingest_state: 'fetch_failed',
    ingest_error: { stage: 'fetch', reason: 'HTTPError', at: '2026-10-14T12:00:00+00:00' },
  },
  has_description: false,
  needs_input: { kind: 'read_failed', error_reason: 'HTTPError' },
};

// The other reading failure: the posting text arrived and extraction
// still produced nothing out of it, so the sections are empty and only a
// retry can fill them.
const extractFailed = {
  ...fixture,
  job: {
    ...fixture.job,
    summary: '',
    description_structured: null,
    skills: [],
    responsibilities: [],
    ingest_state: 'extract_failed',
    ingest_error: { stage: 'extract', reason: 'empty_content', at: '2026-10-14T12:00:00+00:00' },
  },
  summary_effective: '',
  needs_input: { kind: 'read_failed', error_reason: 'empty_content' },
};

test.beforeEach(async ({ page }) => {
  await mockJobPage(page, fixture);
  await mockJobTaxonomy(page, taxonomy);
});

test('header renders type label, title, subtitle and actions', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('JOB', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: fixture.job.title })).toBeVisible();
  await expect(page.getByRole('link', { name: fixture.company.name })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open posting' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit job' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete' })).toBeVisible();
});

test('back link navigates to the jobs board', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await page.getByRole('link', { name: 'Back to Jobs' }).click();
  await expect(page).toHaveURL('/jobs');
});

test('sections render in the canvas order', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: fixture.job.title })).toBeVisible();
  const headings = await page.getByRole('heading').allTextContents();
  const order = ['Summary', 'Requirements', 'Responsibilities', 'Classification', 'Notes', 'History'];
  const positions = order.map((label) => headings.indexOf(label));
  expect(positions.every((index) => index !== -1)).toBe(true);
  expect(positions).toEqual([...positions].sort((a, b) => a - b));
});

test('the retired sections are gone: no Extraction card, no Content wrapper, no Background required', async ({
  page,
}) => {
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: fixture.job.title })).toBeVisible();
  for (const heading of ['Extraction', 'Content', 'Background required', 'Skills', 'Posting status']) {
    await expect(page.getByRole('heading', { name: heading, exact: true })).toHaveCount(0);
  }
});

test('Status dropdown moves the job', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: { ...fixture.job, status: 'interested' } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: /Move Senior Platform Engineer to/ }).click();
  await page.getByRole('menuitem', { name: 'Interested', exact: true }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ status: 'interested' });
});

// Fit is a placeholder until scoring exists: the dropdown this replaces
// wrote a value nothing ever read, and an editable control stood for a
// feature the product does not have.
test('Fit reads as not calculated, with no control to set it', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: fixture.job });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('Not calculated yet')).toBeVisible();
  await expect(page.getByRole('button', { name: /Set fit for/ })).toHaveCount(0);
  expect(requests.length).toBe(0);
});

// --- The one ask: needs_input ---

test('no needs-input chip or card when the page asks for nothing', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: 'Summary' })).toBeVisible();
  await expect(page.getByText('Needs your input')).toHaveCount(0);
});

test('company review shows the chip, the card it links to, and all three candidates as radios', async ({ page }) => {
  await mockJobPage(page, companyReview);
  await page.goto('/jobs/JOB-001');
  const chip = page.getByRole('link', { name: 'Needs your input' });
  await expect(chip).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Needs your input' })).toBeVisible();
  await expect(page.getByText('This posting names Northwind.')).toBeVisible();
  for (const candidate of review.candidates) {
    await expect(page.getByRole('radio', { name: new RegExp(candidate.name) })).toBeVisible();
  }
  await expect(chip).toHaveAttribute('href', '#needs-your-input');
});

test('linking a candidate posts the pick with the review token and clears the ask', async ({ page }) => {
  // The page reloads after resolving, so the second load is the resolved
  // job: the chip and the card have to go away on their own.
  let resolved = false;
  const requests = [];
  await page.route('**/api/jobs/*?view=page', (route) => route.fulfill({ json: resolved ? fixture : companyReview }));
  await page.route('**/api/jobs/*/resolve-review', (route) => {
    requests.push(route.request().postDataJSON());
    resolved = true;
    route.fulfill({ json: { ...fixture.job } });
  });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('radio', { name: /Northwind Labs/ }).click();
  await page.getByRole('button', { name: 'Link to this company' }).click();
  await expect.poll(() => requests.length).toBeGreaterThan(0);
  expect(requests[0]).toEqual({ company_id: 'CO-002', review_token: review.token });
  await expect(page.getByRole('heading', { name: 'Needs your input' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Needs your input' })).toHaveCount(0);
});

test('None of these creates a company from the name the posting carried', async ({ page }) => {
  await mockJobPage(page, companyReview);
  const requests = await mockResolveReview(page, { body: { ...fixture.job } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'None of these, create new' }).click();
  const name = page.getByRole('textbox', { name: 'Company name' });
  await expect(name).toHaveValue('Northwind');
  await name.fill('Northwind Systems Zurich');
  await page.getByRole('button', { name: 'Create and link' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ create: { name: 'Northwind Systems Zurich' }, review_token: review.token });
});

test('a stale review token surfaces the reload message instead of linking', async ({ page }) => {
  await mockJobPage(page, companyReview);
  await mockResolveReview(page, { status: 409, body: { error: 'This review is out of date. Reload and try again.' } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Link to this company' }).click();
  await expect(page.getByText('This review is out of date. Reload and try again.')).toBeVisible();
});

test('a review replaced under the open card links a company still on screen', async ({ page }) => {
  // The page polls while extraction runs, so the candidates can change
  // under an open card. The pick is state, and a pick the owner can no
  // longer see must not be the one that gets linked.
  const laterReview = {
    token: 'rev-1-candidate',
    at: '2026-10-14T13:00:00+00:00',
    candidates: [{ company_id: 'CO-009', name: 'Southwind Logistics', score: 0.88 }],
  };
  let calls = 0;
  await page.route('**/api/jobs/*?view=page', (route) => {
    calls += 1;
    // The mount effect runs twice under React StrictMode, so the first two
    // calls are the original review and only the poll brings the new one.
    const current = calls <= 2 ? review : laterReview;
    route.fulfill({
      json: {
        ...companyReview,
        llm_pending: calls <= 2,
        job: { ...companyReview.job, company_review: current },
        needs_input: { kind: 'company', review: current },
      },
    });
  });
  const requests = await mockResolveReview(page, { body: { ...fixture.job } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('radio', { name: /Northwind Retail Group/ }).click();
  await expect(page.getByRole('radio', { name: /Southwind Logistics/ })).toBeVisible({ timeout: 10000 });
  await expect(page.getByRole('radio', { name: /Northwind Retail Group/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Link to this company' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ company_id: 'CO-009', review_token: 'rev-1-candidate' });
});

test('a reading failure asks for the posting text and offers another try', async ({ page }) => {
  await mockJobPage(page, readFailed);
  const requests = await mockPasteDescription(page, { body: { ok: true } });
  await mockRetry(page, { body: { ok: true } });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: 'Needs your input' })).toBeVisible();
  await expect(page.getByText('The posting page could not be reached.')).toBeVisible();
  await page.getByRole('button', { name: 'Paste the posting text' }).click();
  const modal = page.getByRole('dialog', { name: 'Paste posting text' });
  await modal.getByRole('textbox', { name: 'Posting text' }).fill('Senior Engineer role. Build things.');
  await modal.getByRole('button', { name: 'Save and extract' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ description: 'Senior Engineer role. Build things.' });
});

test('a failed extraction over stored posting text still offers a retry', async ({ page }) => {
  await mockJobPage(page, extractFailed);
  const retries = await mockRetry(page, { body: { ok: true } });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: 'Needs your input' })).toBeVisible();
  await expect(page.getByText('The posting text is here, but no details could be read out of it.')).toBeVisible();
  // Pasting is not one of the ways out here: the endpoint only accepts a
  // paste while the posting itself was never fetched.
  await expect(page.getByRole('button', { name: 'Paste the posting text' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect.poll(() => retries.length).toBe(1);
  expect(retries[0]).toContain('/api/jobs/JOB-001/extract');
});

// --- While the posting is being read ---

test('the reading strip and pending sections show while the posting is read, and only then', async ({ page }) => {
  await mockJobPage(page, {
    ...fixture,
    reading: true,
    llm_pending: true,
    summary_effective: '',
    job: { ...fixture.job, summary: '', description_structured: null, skills: [], responsibilities: [] },
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText(/Reading the posting now/)).toBeVisible();
  await expect(page.getByText('Being read from the posting.')).toHaveCount(3);
});

test('the reading strip is absent once the posting has been read', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: 'Summary' })).toBeVisible();
  await expect(page.getByText(/Reading the posting now/)).toHaveCount(0);
  await expect(page.getByText('Being read from the posting.')).toHaveCount(0);
});

// --- AI provenance labels ---

test('the AI labels say which sections a machine wrote', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('AI-generated')).toHaveCount(1);
  await expect(page.getByText('AI-extracted')).toHaveCount(2);
});

test('a heuristic summary and heuristic requirements carry no AI label', async ({ page }) => {
  await mockJobPage(page, {
    ...fixture,
    job: {
      ...fixture.job,
      summary_source: '',
      ingest_source: 'heuristic',
      description_structured: { ...fixture.job.description_structured, method: 'heuristic' },
    },
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: 'Requirements' })).toBeVisible();
  await expect(page.getByText('AI-generated')).toHaveCount(0);
  await expect(page.getByText('AI-extracted')).toHaveCount(0);
});

test('an owner-corrected section loses its AI label', async ({ page }) => {
  await mockJobPage(page, {
    ...fixture,
    job: {
      ...fixture.job,
      field_provenance: { ...fixture.job.field_provenance, description_structured: 'user', summary: 'user' },
    },
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: 'Requirements' })).toBeVisible();
  await expect(page.getByText('AI-generated')).toHaveCount(0);
  await expect(page.getByText('AI-extracted')).toHaveCount(1); // responsibilities only
});

test('requirements render as must-have and nice-to-have, skills as tags', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  const requirements = page.getByTestId('section-requirements');
  await expect(requirements.getByText('Must have', { exact: true })).toBeVisible();
  await expect(requirements.getByText('Nice to have', { exact: true })).toBeVisible();
  await expect(requirements.getByText('Strong Kubernetes skills')).toBeVisible();
  await expect(requirements.getByText('Rust experience')).toBeVisible();
  await expect(requirements.getByText('Skills', { exact: true })).toBeVisible();
  await expect(requirements.getByText('Python', { exact: true })).toBeVisible();
});

// --- The extraction row and its popup ---

test('the extraction row says when the posting was read and what was not found', async ({ page }) => {
  await mockJobPage(page, {
    ...fixture,
    job: { ...fixture.job, field_status: { ...fixture.job.field_status, seniority: 'not_evidenced' } },
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText(/Read from the posting on 14 Oct 2026/)).toBeVisible();
  await expect(page.getByText(/Not found: Seniority\./)).toBeVisible();
});

test('the extraction popup lists each field with its result and source', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'How this was extracted' }).click();
  const modal = page.getByRole('dialog', { name: 'How this was extracted' });
  await expect(modal).toBeVisible();
  await expect(modal.getByText('Title')).toBeVisible();
  await expect(modal.getByText('Found · AI').first()).toBeVisible();
  await expect(modal.getByText('Found · Not recorded').first()).toBeVisible();
});

// Owner round C1: the row's "when" was only on the row, so the popup
// answered how each field was read without saying when the posting was.
test('the extraction popup carries the read timestamp above the field rows', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'How this was extracted' }).click();
  const modal = page.getByRole('dialog', { name: 'How this was extracted' });
  await expect(modal.getByText(/^Read from the posting on 14 Oct 2026, \d\d:\d\d\.$/)).toBeVisible();
});

test('a not-found field links to where it can be set, and that surface opens', async ({ page }) => {
  await mockJobPage(page, {
    ...fixture,
    job: { ...fixture.job, field_status: { ...fixture.job.field_status, location: 'not_evidenced' } },
  });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'How this was extracted' }).click();
  const modal = page.getByRole('dialog', { name: 'How this was extracted' });
  await expect(modal.getByText('Not found in posting').first()).toBeVisible();
  await modal.getByRole('button', { name: 'Set it in Edit job' }).click();
  await expect(page.getByRole('dialog', { name: 'Edit job' })).toBeVisible();
});

test('a job that was never read says so in the row and in the popup', async ({ page }) => {
  await mockJobPage(page, { ...fixture, history: [], job: { ...fixture.job, field_status: {} } });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('This posting has not been read yet.')).toBeVisible();
  await page.getByRole('button', { name: 'How this was extracted' }).click();
  await expect(
    page.getByRole('dialog', { name: 'How this was extracted' }).getByText('This posting has not been read yet.'),
  ).toBeVisible();
});

// --- Collapsed sections ---

test('the original posting is one collapsed card that opens with its paragraphs', async ({ page }) => {
  await mockJobPage(page, {
    ...fixture,
    job: { ...fixture.job, description: 'First fictional paragraph.\n\nSecond fictional paragraph.' },
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('First fictional paragraph.')).not.toBeVisible();
  await page.getByRole('button', { name: 'Show the original posting' }).click();
  await expect(page.getByText('First fictional paragraph.')).toBeVisible();
  await expect(page.getByText('Second fictional paragraph.')).toBeVisible();
});

test('Details is collapsed and holds the source, the posted date and the online check', async ({ page }) => {
  await mockCheckPosting(page, { body: { events: [], watch_status: 'unchanged' } });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('careers-page')).not.toBeVisible();
  await page.getByRole('button', { name: 'Show details' }).click();
  await expect(page.getByText('careers-page')).toBeVisible();
  await expect(page.getByText(fixture.job.posted_date)).toBeVisible();
  await page.getByRole('button', { name: 'Check if still online' }).click();
  await expect(page.getByText('Unchanged')).toBeVisible();
});

// Bug 7: the page used to promise a retry on the next scan, which no
// scanner ever performs for a job that is not watched.
test('an unreachable posting is reported without promising a retry', async ({ page }) => {
  await mockCheckPosting(page, { body: { events: [], watch_status: 'error' } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Show details' }).click();
  await page.getByRole('button', { name: 'Check if still online' }).click();
  await expect(page.getByText('Error: posting unreachable.')).toBeVisible();
  await expect(page.getByText(/will retry on the next scan/)).toHaveCount(0);
});

test('Check if still online is disabled with its reason when the job is not watch-eligible', async ({ page }) => {
  await mockJobPage(page, { ...fixture, watch_eligible: false, watch_reason: 'Not eligible for some reason.' });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Show details' }).click();
  await expect(page.getByRole('button', { name: 'Not eligible for some reason.' })).toBeDisabled();
});

test('Check if still online reloads the page when new events are found', async ({ page }) => {
  // Counts relative to the pre-click baseline, not an absolute total:
  // React StrictMode (src/main.jsx) double-invokes the mount effect in
  // dev, so the initial load already fires more than once before any
  // click happens.
  let calls = 0;
  await page.route('**/api/jobs/*?view=page', (route) => {
    calls += 1;
    route.fulfill({ json: fixture });
  });
  await mockCheckPosting(page, { body: { events: [{ event: 'posting_changed', detail: 'changed' }] } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Show details' }).click();
  const before = calls;
  await page.getByRole('button', { name: 'Check if still online' }).click();
  await expect.poll(() => calls).toBeGreaterThan(before);
});

// --- Classification, Notes, History ---

test('Classification shows the inherited sector, the function and the tags in owner words', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  const classification = page.getByTestId('section-classification');
  await expect(classification.getByText('Information and communication')).toBeVisible();
  await expect(classification.getByText('From the company')).toBeVisible();
  await expect(classification.getByText('Engineering')).toBeVisible();
  await expect(classification.getByText('Python', { exact: true })).toBeVisible();
  await expect(page.getByText('tool:python')).toHaveCount(0);
});

test('an unclassified job says the posting did not name one', async ({ page }) => {
  await mockJobPage(page, {
    ...fixture,
    classification: { sector: { value: null, source: null }, function: [], tags: [] },
  });
  await page.goto('/jobs/JOB-001');
  const classification = page.getByTestId('section-classification');
  await expect(classification.getByText('Not found in posting')).toHaveCount(3);
  await expect(classification.getByText('From the company')).toHaveCount(0);
});

test('Edit classification opens the shared popup and saves function and tags', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: fixture.job });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Edit classification' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit classification' });
  await expect(modal).toBeVisible();
  await modal.getByRole('checkbox', { name: 'Design' }).check();
  await modal.getByRole('button', { name: 'Save changes' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].function).toContain('design');
});

test('Edit classification load failure shows a visible error without opening the popup', async ({ page }) => {
  await page.route('**/api/jobs/*/taxonomy', (route) => {
    if (route.request().method() !== 'GET') {
      route.fallback();
      return;
    }
    route.fulfill({ status: 500, json: { error: 'nope' } });
  });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Edit classification' }).click();
  await expect(page.getByText('Could not load classification.')).toBeVisible();
  await expect(page.getByRole('dialog', { name: 'Edit classification' })).not.toBeVisible();
});

test('empty Notes offer the dashed Add a note box, which opens Edit job at the notes field', async ({ page }) => {
  await mockJobPage(page, { ...fixture, markdown: '', job: { ...fixture.job, notes: '' } });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('No notes yet.')).toBeVisible();
  await page.getByRole('button', { name: 'Add a note' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit job' });
  await expect(modal).toBeVisible();
  await expect(modal.getByRole('textbox', { name: 'Notes' })).toBeFocused();
});

test('History shows the resolved labels with local dates, newest first', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  const history = page.getByTestId('section-history');
  await expect(history.getByText('Details read from the posting')).toBeVisible();
  await expect(history.getByText(/14 Oct 2026, \d\d:\d\d/)).toBeVisible();
  const labels = await history.getByText(/^(Job added|Details read from the posting)$/).allTextContents();
  expect(labels).toEqual(['Details read from the posting', 'Job added']);
});

// --- Editing ---

test('Edit job popup opens, edits and saves', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: fixture.job });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Edit job' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit job' });
  await expect(modal).toBeVisible();
  await modal.getByRole('textbox', { name: 'Title' }).fill('Updated Title');
  await modal.getByRole('button', { name: 'Save job' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].title).toBe('Updated Title');
  await expect(modal).not.toBeVisible();
});

test('Edit job popup closes on Cancel without saving', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: fixture.job });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Edit job' }).click();
  await page.getByRole('dialog', { name: 'Edit job' }).getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('dialog', { name: 'Edit job' })).not.toBeVisible();
  expect(requests.length).toBe(0);
});

test('Edit job popup corrects every AI-made field the page labels', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: fixture.job });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Edit job' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit job' });
  await modal.getByRole('textbox', { name: 'Summary' }).fill('A corrected summary.');
  const requirements = modal.getByRole('textbox', { name: 'Requirements, must have' });
  await expect(requirements).toHaveValue('5+ years of platform experience\nStrong Kubernetes skills');
  await requirements.fill('5+ years of platform experience\nOwns incident response');
  await modal.getByRole('textbox', { name: 'Responsibilities' }).fill('Own the platform roadmap');
  await modal.getByRole('button', { name: 'Remove Kubernetes' }).click();
  await modal.getByRole('textbox', { name: 'Add a skill' }).fill('Terraform');
  await modal.getByRole('button', { name: 'Add', exact: true }).click();
  await modal.getByRole('button', { name: 'Save job' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].summary).toBe('A corrected summary.');
  expect(requests[0].description_structured.requirements).toEqual([
    '5+ years of platform experience', 'Owns incident response',
  ]);
  expect(requests[0].description_structured.nice_to_have).toEqual(['Rust experience']);
  expect(requests[0].responsibilities).toEqual(['Own the platform roadmap']);
  expect(requests[0].skills).toEqual(['Python', 'Terraform']);
});

test('Edit job popup sends only the fields that actually changed', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: fixture.job });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Edit job' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit job' });
  await modal.getByRole('textbox', { name: 'Title' }).fill('Updated Title');
  await modal.getByRole('button', { name: 'Save job' }).click();
  await expect.poll(() => requests.length).toBe(1);
  for (const key of ['description_structured', 'summary', 'responsibilities', 'skills']) {
    expect(requests[0]).not.toHaveProperty(key);
  }
});

test('Status dropdown failure shows a visible error', async ({ page }) => {
  await mockUpdate(page, '**/api/jobs/JOB-001', { status: 500, body: { error: 'Status save failed.' } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: /Move Senior Platform Engineer to/ }).click();
  await page.getByRole('menuitem', { name: 'Interested', exact: true }).click();
  await expect(page.getByText('Status save failed.')).toBeVisible();
});

test('Retry failure shows a visible error', async ({ page }) => {
  await mockJobPage(page, readFailed);
  await page.route('**/api/jobs/*/extract', (route) => route.fulfill({ status: 500, json: { error: 'nope' } }));
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByText('Retry failed.')).toBeVisible();
});

test('Delete confirmation opens, deletes and returns to the jobs board, which actually renders', async ({ page }) => {
  // /jobs is a React Route (unlike /experiences and /companies), so the
  // client-side navigate() this page uses is correct here -- but still
  // worth pinning that the destination renders, not just the URL.
  await mockDelete(page, '**/api/jobs/JOB-001');
  await mockBoard(page, loadBoardFixture());
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Delete' }).click();
  const alert = page.getByRole('alertdialog', { name: 'Delete this job?' });
  await expect(alert).toBeVisible();
  await alert.getByRole('button', { name: 'Delete job' }).click();
  await expect(page).toHaveURL('/jobs');
  await expect(page.getByRole('heading', { name: 'Jobs' })).toBeVisible();
});

test('Delete confirmation Keep job closes without deleting', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Delete' }).click();
  const alert = page.getByRole('alertdialog', { name: 'Delete this job?' });
  await alert.getByRole('button', { name: 'Keep job' }).click();
  await expect(alert).not.toBeVisible();
});

// --- Extraction progress (JOZ-267, carried over) ---

test('Thin posting_quality shows a limited-extraction notice', async ({ page }) => {
  await mockJobPage(page, { ...fixture, job: { ...fixture.job, posting_quality: 'thin' } });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('This posting has very little text; extraction will be limited.')).toBeVisible();
});

test('a pending field updates to found without a manual reload', async ({ page }) => {
  // React StrictMode (src/main.jsx) double-invokes the mount effect in dev,
  // so the initial load already fires more than once before the poll ever
  // runs; the first two calls stay pending so the assertion below cannot
  // race that double-invoke, and only the poll (call 3+) resolves.
  let calls = 0;
  await page.route('**/api/jobs/*?view=page', (route) => {
    calls += 1;
    if (calls <= 2) {
      route.fulfill({
        json: {
          ...fixture,
          llm_pending: true,
          reading: true,
          job: { ...fixture.job, field_status: { ...fixture.job.field_status, skills: 'pending' } },
        },
      });
      return;
    }
    route.fulfill({ json: fixture });
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText(/Reading the posting now/)).toBeVisible();
  await expect(page.getByText(/Reading the posting now/)).toHaveCount(0, { timeout: 10000 });
  expect(calls).toBeGreaterThan(2);
});

test('a pending field with a terminal ingest_state does not keep polling', async ({ page }) => {
  // JOZ-267 fix round 1 finding 4: once ingest_state is terminal, nothing
  // can ever advance a stray pending field again (a past bug, or a
  // terminal failure that landed between page loads); polling must stop
  // instead of hitting the API forever.
  let calls = 0;
  await page.route('**/api/jobs/*?view=page', (route) => {
    calls += 1;
    route.fulfill({
      json: {
        ...fixture,
        llm_pending: false,
        job: {
          ...fixture.job,
          ingest_state: 'extract_failed',
          field_status: { ...fixture.job.field_status, skills: 'pending' },
        },
      },
    });
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText(/Read from the posting on/)).toBeVisible();
  const afterMount = calls;
  await page.waitForTimeout(4000);
  expect(calls).toBe(afterMount);
});
