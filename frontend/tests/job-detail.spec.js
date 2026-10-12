import { expect, test } from '@playwright/test';
import { loadFixture, mockJobPage, mockJobTaxonomy, mockUpdate, mockDelete } from './helpers.js';

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

test('Delete confirmation opens, deletes and returns to the jobs board', async ({ page }) => {
  await mockDelete(page, '**/api/jobs/JOB-001');
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Delete' }).click();
  const alert = page.getByRole('alertdialog', { name: 'Delete this job?' });
  await expect(alert).toBeVisible();
  await alert.getByRole('button', { name: 'Delete job' }).click();
  await expect(page).toHaveURL('/jobs');
});

test('Delete confirmation Keep job closes without deleting', async ({ page }) => {
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Delete' }).click();
  const alert = page.getByRole('alertdialog', { name: 'Delete this job?' });
  await alert.getByRole('button', { name: 'Keep job' }).click();
  await expect(alert).not.toBeVisible();
});
