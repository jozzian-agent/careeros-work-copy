import { expect, test } from '@playwright/test';
import { loadFixture, mockCompanyTaxonomy, mockUpdate } from './helpers.js';

const fixture = loadFixture('company-taxonomy');

test.beforeEach(async ({ page }) => {
  await mockCompanyTaxonomy(page, fixture);
});

test('header shows no Edit/Delete actions and back links to the company', async ({ page }) => {
  await page.goto('/companies/CO-001/taxonomy');
  await expect(page.getByText('COMPANY CLASSIFICATION', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Classification' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit company' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Delete' })).toHaveCount(0);
  await page.getByRole('link', { name: `Back to ${fixture.company.name}` }).click();
  await expect(page).toHaveURL('/companies/CO-001');
});

test('kind, sectors and size load from the record and save', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/companies/CO-001', { body: fixture.company });
  await page.goto('/companies/CO-001/taxonomy');
  await expect(page.getByRole('checkbox', { name: /Information and communication/ })).toBeChecked();
  await page.getByRole('checkbox', { name: /Manufacturing/ }).check();
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].sectors.sort()).toEqual(['C', 'J']);
  await expect(page).toHaveURL('/companies/CO-001');
});

test('review flags render when present', async ({ page }) => {
  await page.goto('/companies/CO-001/taxonomy');
  await expect(page.getByRole('heading', { name: 'Review flags' })).toBeVisible();
  await expect(page.getByText('size-inconsistent')).toBeVisible();
});

test('Cancel returns to the company without saving', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/companies/CO-001', { body: fixture.company });
  await page.goto('/companies/CO-001/taxonomy');
  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(page).toHaveURL('/companies/CO-001');
  expect(requests.length).toBe(0);
});
