// Protects the Notes page: every note in one place, each one traceable
// back to the job or company it belongs to, and read-only on purpose.
import { expect, test } from '@playwright/test';
import { loadFixture, mockNotesPage } from './helpers.js';

const fixture = loadFixture('notes');

test.beforeEach(async ({ page }) => {
  await mockNotesPage(page, fixture);
});

test('every note is listed with its title and its one-line preview', async ({ page }) => {
  await page.goto('/notes');
  await expect(page.getByRole('heading', { name: 'Notes' })).toBeVisible();
  for (const note of fixture.notes) {
    await expect(page.getByText(note.title, { exact: true }).first()).toBeVisible();
  }
  await expect(page.getByText('Ask about the rota.')).toBeVisible();
});

test('a note links back to the record it belongs to', async ({ page }) => {
  await page.goto('/notes');
  const jobLink = page.getByRole('link', { name: 'JOB-001 Senior Platform Engineer' });
  await expect(jobLink).toHaveAttribute('href', '/jobs/JOB-001');
  const companyLink = page.getByRole('link', { name: 'CO-001 Northwind Systems' });
  await expect(companyLink).toHaveAttribute('href', '/companies/CO-001');
});

test('the dates say when a note was added, and when it changed only if it did', async ({ page }) => {
  await page.goto('/notes');
  await expect(page.getByText('Added 14 Oct 2026, 12:20')).toBeVisible();
  // The company note was edited after it was written, so it says both.
  await expect(page.getByText('Added 13 Oct 2026, 09:00')).toBeVisible();
  await expect(page.getByText('Updated 14 Oct 2026, 10:00')).toBeVisible();
  // The job note has not been edited, so there is no Updated line for it.
  await expect(page.getByText('Updated 14 Oct 2026, 12:20')).toHaveCount(0);
});

// A note migrated out of the legacy free-text field has no write-time, so
// the page shows no date for it rather than inventing one.
test('a note with no recorded dates shows none, and still names its record', async ({ page }) => {
  await page.goto('/notes');
  await expect(page.getByText('Written before notes were a list.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'JOB-002 Developer Tools Manager' })).toBeVisible();
  await expect(page.getByText('Added Invalid Date')).toHaveCount(0);
});

test('the page is read-only: nothing here edits a note', async ({ page }) => {
  await page.goto('/notes');
  await expect(page.getByRole('heading', { name: 'Notes' })).toBeVisible();
  for (const label of ['Add a note', 'Edit', 'Delete', 'Save note']) {
    await expect(page.getByRole('button', { name: label })).toHaveCount(0);
  }
});

test('no notes anywhere shows the backend message and where notes come from', async ({ page }) => {
  await mockNotesPage(page, { notes: [], empty: fixture.empty });
  await page.goto('/notes');
  await expect(page.getByText(fixture.empty)).toBeVisible();
});

test('a load failure shows a visible error with Retry', async ({ page }) => {
  await page.route('**/api/notes', (route) => route.fulfill({ status: 500, json: { error: 'nope' } }));
  await page.goto('/notes');
  await expect(page.getByText('Could not load your notes.')).toBeVisible();
  await page.route('**/api/notes', (route) => route.fulfill({ json: fixture }));
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByText('On-call rotation')).toBeVisible();
});

test('Notes is marked as the current page on /notes', async ({ page }) => {
  await page.goto('/notes');
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(nav.getByRole('link', { name: 'Notes', exact: true })).toHaveAttribute('aria-current', 'page');
  for (const label of ['Search', 'Experiences', 'My Jobs', 'Companies', 'Taxonomy']) {
    await expect(nav.getByRole('link', { name: label, exact: true })).not.toHaveAttribute('aria-current');
  }
});
