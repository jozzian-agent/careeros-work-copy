import { expect, test } from '@playwright/test';
import { loadFixture, mockCompaniesPage } from './helpers.js';

const fixture = loadFixture('companies-list');

test.beforeEach(async ({ page }) => {
  await mockCompaniesPage(page, fixture);
});

test('renders a card per company with sector/size line and open-jobs chip', async ({ page }) => {
  await page.goto('/companies');
  await expect(page.getByRole('heading', { name: 'Companies' })).toBeVisible();
  await expect(page.getByRole('link', { name: /Harbor Labs/ })).toBeVisible();
  await expect(page.getByText('Information and communication · Small')).toBeVisible();
  await expect(page.getByText('3 open jobs')).toBeVisible();
  await expect(page.getByRole('link', { name: /Lantern Peak/ })).toHaveAttribute('href', '/companies/CO-003');
});

test('filtering by sector alone shows only matching companies', async ({ page }) => {
  await page.goto('/companies');
  await page.getByLabel('Sector').selectOption('J');
  await expect(page.getByRole('heading', { name: 'Harbor Labs' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Lantern Peak' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Fern Robotics' })).toHaveCount(0);
});

test('filtering by size alone shows only matching companies', async ({ page }) => {
  await page.goto('/companies');
  await page.getByLabel('Size').selectOption('large');
  await expect(page.getByRole('heading', { name: 'Fern Robotics' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Harbor Labs' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Lantern Peak' })).toHaveCount(0);
});

test('combining sector and size filters narrows to the intersection', async ({ page }) => {
  await page.goto('/companies');
  await page.getByLabel('Sector').selectOption('J');
  await page.getByLabel('Size').selectOption('medium');
  await expect(page.getByRole('heading', { name: 'Lantern Peak' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Harbor Labs' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Fern Robotics' })).toHaveCount(0);
});

test('a filter combination matching nothing shows an empty grid, not an error', async ({ page }) => {
  await page.goto('/companies');
  await page.getByLabel('Sector').selectOption('C');
  await page.getByLabel('Size').selectOption('small');
  await expect(page.getByRole('heading', { name: 'Harbor Labs' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Fern Robotics' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Lantern Peak' })).toHaveCount(0);
});

test('an empty directory shows the empty message with no filter controls', async ({ page }) => {
  await mockCompaniesPage(page, { ...fixture, entries: [] });
  await page.goto('/companies');
  await expect(page.getByText(fixture.empty)).toBeVisible();
  await expect(page.getByLabel('Sector')).toHaveCount(0);
});
