import { expect, test } from '@playwright/test';
import {
  loadFixture,
  loadBoardFixture,
  mockBoard,
  mockCheckPosting,
  mockJobPage,
  mockJobTaxonomy,
  mockPasteDescription,
  mockRetry,
  mockUpdate,
  mockDelete,
} from './helpers.js';

const fixture = loadFixture('job-detail');
const taxonomy = loadFixture('job-taxonomy');

test.beforeEach(async ({ page }) => {
  await mockJobPage(page, fixture);
  await mockJobTaxonomy(page, taxonomy);
});

test('header renders type label, title, subtitle and actions', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('JOB', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: fixture.job.title })).toBeVisible();
  await expect(page.getByRole('link', { name: fixture.company.name })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit job' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete' })).toBeVisible();
});

test('back link navigates to the jobs board', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await page.getByRole('link', { name: 'Back to Jobs' }).click();
  await expect(page).toHaveURL('/jobs');
});

test('sections render in the skeleton order: summary, content, classification, details, notes, history', async ({
  page,
}) => {
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: fixture.job.title })).toBeVisible();
  const headings = await page.getByRole('heading').allTextContents();
  const order = ['Summary', 'Content', 'Classification', 'Details', 'Notes', 'History'];
  const positions = order.map((label) => headings.indexOf(label));
  expect(positions.every((index) => index !== -1)).toBe(true);
  expect(positions).toEqual([...positions].sort((a, b) => a - b));
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

test('Edit job popup opens, edits and saves', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: fixture.job });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Edit job' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit job' });
  await expect(modal).toBeVisible();
  const title = modal.getByRole('textbox', { name: 'Title' });
  await title.fill('Updated Title');
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

test('Edit criteria popup opens from Classification, saves function and tags', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: fixture.job });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Edit classification' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit classification' });
  await expect(modal).toBeVisible();
  await expect(modal.getByText('Design')).toBeVisible();
  await modal.getByRole('checkbox', { name: 'Design' }).check();
  await modal.getByRole('button', { name: 'Save changes' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].function).toContain('design');
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

test('Status dropdown failure shows a visible error', async ({ page }) => {
  await mockUpdate(page, '**/api/jobs/JOB-001', { status: 500, body: { error: 'Status save failed.' } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: /Move Senior Platform Engineer to/ }).click();
  await page.getByRole('menuitem', { name: 'Interested', exact: true }).click();
  await expect(page.getByText('Status save failed.')).toBeVisible();
});

test('Posting Retry failure shows a visible error', async ({ page }) => {
  await mockJobPage(page, { ...fixture, job: { ...fixture.job, ingest_state: 'fetch_failed' } });
  await page.route('**/api/jobs/*/extract', (route) => route.fulfill({ status: 500, json: { error: 'nope' } }));
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByText('Retry failed.')).toBeVisible();
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

test('Check posting is disabled with its reason when the job is not watch-eligible', async ({ page }) => {
  await mockJobPage(page, { ...fixture, watch_eligible: false, watch_reason: 'Not eligible for some reason.' });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('button', { name: 'Not eligible for some reason.' })).toBeDisabled();
});

test('Check posting shows Unchanged when nothing changed', async ({ page }) => {
  await mockCheckPosting(page, { body: { events: [], watch_status: 'unchanged' } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Check posting' }).click();
  await expect(page.getByText('Unchanged')).toBeVisible();
});

test('Check posting reloads the page when new events are found', async ({ page }) => {
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
  await expect(page.getByRole('heading', { name: fixture.job.title })).toBeVisible();
  const before = calls;
  await page.getByRole('button', { name: 'Check posting' }).click();
  await expect.poll(() => calls).toBeGreaterThan(before);
});

test('Delete confirmation Keep job closes without deleting', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Delete' }).click();
  const alert = page.getByRole('alertdialog', { name: 'Delete this job?' });
  await alert.getByRole('button', { name: 'Keep job' }).click();
  await expect(alert).not.toBeVisible();
});

// --- JOZ-267: per-field status, posting_quality, retry, manual paste ---

test('Extraction section shows a status badge per covered field', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: 'Extraction' })).toBeVisible();
  await expect(page.getByText('Done').first()).toBeVisible();
});

test('Thin posting_quality shows a limited-extraction notice', async ({ page }) => {
  await mockJobPage(page, { ...fixture, job: { ...fixture.job, posting_quality: 'thin' } });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('This posting has very little text; extraction will be limited.')).toBeVisible();
});

test('Not-evidenced fields show their own badge, not a guess', async ({ page }) => {
  await mockJobPage(page, {
    ...fixture,
    job: {
      ...fixture.job,
      field_status: { ...fixture.job.field_status, employment_type: 'not_evidenced' },
    },
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('Not evidenced')).toBeVisible();
});

test('Pending fields show a pending badge while extraction is still in flight', async ({ page }) => {
  await mockJobPage(page, {
    ...fixture,
    llm_pending: true,
    job: {
      ...fixture.job,
      ingest_state: 'fetched',
      field_status: { ...fixture.job.field_status, skills: 'pending' },
    },
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('Pending')).toBeVisible();
});

test('Per-field status updates from pending to done without a manual reload', async ({ page }) => {
  // React StrictMode (src/main.jsx) double-invokes the mount effect in dev,
  // so the initial load already fires more than once before the poll ever
  // runs; the first two calls stay pending so the assertion below cannot
  // race that double-invoke, and only the poll (call 3+) resolves to done.
  let calls = 0;
  await page.route('**/api/jobs/*?view=page', (route) => {
    calls += 1;
    if (calls <= 2) {
      route.fulfill({
        json: {
          ...fixture,
          llm_pending: true,
          job: { ...fixture.job, field_status: { ...fixture.job.field_status, skills: 'pending' } },
        },
      });
      return;
    }
    route.fulfill({ json: fixture });
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('Pending')).toBeVisible();
  await expect(page.getByText('Pending')).not.toBeVisible({ timeout: 10000 });
  expect(calls).toBeGreaterThan(2);
});

test('A pending field with a terminal ingest_state does not keep polling', async ({ page }) => {
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
  await expect(page.getByText('Pending')).toBeVisible();
  const afterMount = calls;
  await page.waitForTimeout(4000);
  expect(calls).toBe(afterMount);
});

test('Extraction labels LLM-generated requirements and nice-to-have as AI-generated', async ({ page }) => {
  // The fixture already has description_structured.method 'llm' and
  // summary_source 'ai', so both the Summary card and the Extraction
  // card's generated lists show the badge.
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('AI-generated')).toHaveCount(2);
});

test('Heuristic requirements are not mislabeled as AI-generated', async ({ page }) => {
  await mockJobPage(page, {
    ...fixture,
    job: {
      ...fixture.job,
      summary_source: '',
      description_structured: { ...fixture.job.description_structured, method: 'heuristic' },
    },
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('Requirements')).toBeVisible();
  await expect(page.getByText('AI-generated')).toHaveCount(0);
});

test('User-edited requirements and nice-to-have lose the AI-generated label', async ({ page }) => {
  // R2-D: method stays 'llm' (it records how the text was originally
  // produced), but once the owner has edited it, field_provenance says
  // so -- the badge must follow provenance, not the untouched method.
  await mockJobPage(page, {
    ...fixture,
    job: {
      ...fixture.job,
      field_provenance: { ...fixture.job.field_provenance, description_structured: 'user' },
    },
  });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('Requirements')).toBeVisible();
  await expect(page.getByText('AI-generated')).toHaveCount(1); // only the Summary card's badge remains
});

test('Edit job popup corrects generated requirements and nice-to-have', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: fixture.job });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Edit job' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit job' });
  const requirements = modal.getByRole('textbox', { name: 'Requirements' });
  await expect(requirements).toHaveValue('5+ years of platform experience\nStrong Kubernetes skills');
  await requirements.fill('5+ years of platform experience\nStrong Kubernetes skills\nOwns incident response');
  await modal.getByRole('button', { name: 'Save job' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].description_structured.requirements).toEqual([
    '5+ years of platform experience', 'Strong Kubernetes skills', 'Owns incident response',
  ]);
  expect(requests[0].description_structured.nice_to_have).toEqual(['Rust experience']);
  expect(requests[0].description_structured.method).toBe('llm');
});

test('Edit job popup omits description_structured when nothing in it changed', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: fixture.job });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Edit job' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit job' });
  await modal.getByRole('textbox', { name: 'Title' }).fill('Updated Title');
  await modal.getByRole('button', { name: 'Save job' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).not.toHaveProperty('description_structured');
});

test('Posting Retry succeeds and reloads the job', async ({ page }) => {
  await mockJobPage(page, { ...fixture, job: { ...fixture.job, ingest_state: 'extract_failed' } });
  await mockRetry(page, { body: { ok: true } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByText('Extraction failed.')).toBeVisible();
});

test('Fetch failure offers a manual paste affordance that resumes extraction', async ({ page }) => {
  await mockJobPage(page, { ...fixture, job: { ...fixture.job, ingest_state: 'fetch_failed' } });
  const requests = await mockPasteDescription(page, { body: { ok: true } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Paste posting text manually' }).click();
  const modal = page.getByRole('dialog', { name: 'Paste posting text' });
  await expect(modal).toBeVisible();
  await modal.getByRole('textbox', { name: 'Posting text' }).fill('Senior Engineer role. Build things.');
  await modal.getByRole('button', { name: 'Save and extract' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ description: 'Senior Engineer role. Build things.' });
  await expect(modal).not.toBeVisible();
});

test('Manual paste failure shows a visible error without closing the popup', async ({ page }) => {
  await mockJobPage(page, { ...fixture, job: { ...fixture.job, ingest_state: 'fetch_failed' } });
  await mockPasteDescription(page, { status: 500, body: { error: 'Could not save that posting text.' } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Paste posting text manually' }).click();
  const modal = page.getByRole('dialog', { name: 'Paste posting text' });
  await modal.getByRole('textbox', { name: 'Posting text' }).fill('Some posting text here.');
  await modal.getByRole('button', { name: 'Save and extract' }).click();
  await expect(page.getByText('Could not save that posting text.')).toBeVisible();
  await expect(modal).toBeVisible();
});
