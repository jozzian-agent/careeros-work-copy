import { expect, test } from '@playwright/test';
import { loadFixture, mockTaxonomy } from './helpers.js';

const fixture = loadFixture('taxonomy');

test.beforeEach(async ({ page }) => {
  await mockTaxonomy(page, fixture);
});

test('renders the page header and every section heading', async ({ page }) => {
  await page.goto('/taxonomy');
  await expect(page.getByRole('heading', { name: 'Taxonomy', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Skills', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Industries', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Company size', exact: true })).toBeVisible();
});

test('skills table reflects every fixture row and its count', async ({ page }) => {
  await page.goto('/taxonomy');
  for (const row of fixture.skills) {
    const tableRow = page.locator('tr', { hasText: row.skill });
    await expect(tableRow).toBeVisible();
    await expect(tableRow.getByText(String(row.count), { exact: true })).toBeVisible();
  }
});

test('industries table shows human ISIC labels, not bare codes', async ({ page }) => {
  await page.goto('/taxonomy');
  for (const row of fixture.industries) {
    const tableRow = page.locator('tr', { hasText: row.label });
    await expect(tableRow).toBeVisible();
    await expect(tableRow.getByText(String(row.count), { exact: true })).toBeVisible();
  }
});

// CAREER-71: the row's label is the taxonomy's own word for the class,
// sent with the count. Title-casing the code read "Xl" for `xl`, whose
// label is "Very large" -- the one class the two readings disagree on.
test('company size table shows the taxonomy label for every class, including the unknown bucket', async ({ page }) => {
  await page.goto('/taxonomy');
  // One cell per class, matched exactly: "Large" and "Very large" are two
  // rows, and a substring match would not tell them apart.
  for (const row of fixture.sizes) {
    await expect(page.getByRole('cell', { name: row.label, exact: true })).toBeVisible();
  }
  await expect(page.getByText('Xl', { exact: true })).toHaveCount(0);
});

test('the page is read-only: no edit, save or delete controls', async ({ page }) => {
  await page.goto('/taxonomy');
  await expect(page.getByRole('button', { name: /edit|save|delete/i })).toHaveCount(0);
});

test('a load failure shows the error with a Retry that recovers', async ({ page }) => {
  let fail = true;
  await page.route('**/api/taxonomy', (route) => {
    if (fail) {
      route.fulfill({ status: 500, json: { error: 'down' } });
      return;
    }
    route.fulfill({ json: fixture });
  });

  await page.goto('/taxonomy');
  await expect(page.getByText('Could not load taxonomy.')).toBeVisible();

  fail = false;
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByRole('heading', { name: 'Taxonomy', exact: true })).toBeVisible();
});

test('empty sections render a quiet per-section message instead of a header-only table', async ({ page }) => {
  const empty = loadFixture('taxonomy-empty');
  await mockTaxonomy(page, empty);
  await page.goto('/taxonomy');
  await expect(page.getByText('No skills recorded yet.')).toBeVisible();
  await expect(page.getByText('No companies with industry data yet.')).toBeVisible();
  await expect(page.getByText('No companies yet.')).toBeVisible();
  await expect(page.getByRole('table')).toHaveCount(0);
});

test('nav links to /taxonomy and marks it current', async ({ page }) => {
  await page.goto('/taxonomy');
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(nav.getByRole('link', { name: 'Taxonomy', exact: true })).toHaveAttribute('aria-current', 'page');
});
