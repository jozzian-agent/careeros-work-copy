import { expect, test } from '@playwright/test';
import { loadFixture, mockExperiencesPage } from './helpers.js';

const fixture = loadFixture('experiences-list');

test.beforeEach(async ({ page }) => {
  await mockExperiencesPage(page, fixture);
});

test('renders a card per position with title, company link, dates and chips', async ({ page }) => {
  await page.goto('/experiences');
  await expect(page.getByRole('heading', { name: 'Experiences' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Platform Lead' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Renamed Harbor Labs' })).toHaveAttribute('href', '/companies/CO-001');
  await expect(page.getByText('2022-01 – present · Zurich')).toBeVisible();
  await expect(page.getByText('Kubernetes')).toBeVisible();
  await expect(page.getByText('Led 6 people')).toBeVisible();
});

test('a company that does not resolve renders as plain text, not a link', async ({ page }) => {
  await page.goto('/experiences');
  await expect(page.getByRole('heading', { name: 'Freelance Builder' })).toBeVisible();
  await expect(page.getByText('Cached Text Studio')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Cached Text Studio' })).toHaveCount(0);
});

test('a local tag renders its label chip plus a visible local marker', async ({ page }) => {
  await page.goto('/experiences');
  await expect(page.getByText('Local Extension')).toBeVisible();
  const marker = page.locator('[title="Local extension, not mapped to an ISCO group"]');
  await expect(marker).toBeVisible();
  await expect(marker.getByText('local', { exact: true })).toBeVisible();
});

test('Add position links to the existing new-position form', async ({ page }) => {
  await page.goto('/experiences');
  const addButtons = page.getByRole('link', { name: 'Add position' });
  await expect(addButtons.first()).toHaveAttribute('href', '/experiences/new');
});

test('empty library shows the empty message and Add position instead of the list', async ({ page }) => {
  await mockExperiencesPage(page, { ...fixture, entries: [] });
  await page.goto('/experiences');
  await expect(page.getByText(fixture.empty)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Platform Lead' })).toHaveCount(0);
});

test('a load failure shows a visible error with Retry', async ({ page }) => {
  await page.route('**/api/experiences?view=page', (route) => route.fulfill({ status: 500, json: { error: 'nope' } }));
  await page.goto('/experiences');
  await expect(page.getByText('Could not load your experiences.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
});
