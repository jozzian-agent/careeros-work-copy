import { expect, test } from '@playwright/test';
import {
  loadFixture,
  loadBoardFixture,
  mockBoard,
  mockCheckPosting,
  mockJobPage,
  mockJobTaxonomy,
  mockUpdate,
  mockDelete,
} from './helpers.js';

const fixture = loadFixture('job-detail');
const taxonomy = loadFixture('job-taxonomy');

test.beforeEach(async ({ page }) => {
  await mockJobPage(page, fixture);
  await mockJobTaxonomy(page, taxonomy);
});

test('header renders type label, title, subtitle, chip and actions', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('JOB', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: fixture.job.title })).toBeVisible();
  await expect(page.getByRole('link', { name: fixture.company.name })).toBeVisible();
  await expect(page.getByText('Lucky').first()).toBeVisible();
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

test('Fit dropdown sets the job fit', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/jobs/JOB-001', { body: { ...fixture.job, fit: 'excellent' } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: /Set fit for Senior Platform Engineer/ }).click();
  await page.getByRole('menuitem', { name: 'Excellent fit', exact: true }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ fit: 'excellent' });
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

test('Fit dropdown failure shows a visible error', async ({ page }) => {
  await mockUpdate(page, '**/api/jobs/JOB-001', { status: 500, body: { error: 'Fit save failed.' } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: /Set fit for Senior Platform Engineer/ }).click();
  await page.getByRole('menuitem', { name: 'Excellent fit', exact: true }).click();
  await expect(page.getByText('Fit save failed.')).toBeVisible();
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
