import { expect, test } from '@playwright/test';
import { loadFixture, mockCompanyPage, mockUpdate, mockDelete } from './helpers.js';

const fixture = loadFixture('company-detail');

test.beforeEach(async ({ page }) => {
  await mockCompanyPage(page, fixture);
});

test('header renders type label, title, subtitle and actions', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await expect(page.getByText('COMPANY', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: fixture.company.name })).toBeVisible();
  await expect(page.getByText('Information and communication · 51-200').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit company' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete' })).toBeVisible();
});

test('back link navigates to the companies list', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await page.getByRole('link', { name: 'Back to Companies' }).click();
  await expect(page).toHaveURL('/companies');
});

test('sections render in order: classification, details, notes, jobs, experiences', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('heading', { name: fixture.company.name })).toBeVisible();
  const headings = await page.getByRole('heading').allTextContents();
  const order = ['Classification', 'Details', 'Notes', 'Jobs', 'Experiences'];
  const positions = order.map((label) => headings.indexOf(label));
  expect(positions.every((index) => index !== -1)).toBe(true);
  expect(positions).toEqual([...positions].sort((a, b) => a - b));
});

test('linked jobs and experiences render as links, empty states show otherwise', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('link', { name: fixture.entries[0].title })).toBeVisible();
  await expect(page.getByRole('link', { name: fixture.experiences[0].title })).toBeVisible();
});

test('empty related-items sections show the dashed empty state', async ({ page }) => {
  await mockCompanyPage(page, { ...fixture, entries: [], experiences: [] });
  await page.goto('/companies/CO-001');
  await expect(page.getByText('No jobs linked yet')).toBeVisible();
  await expect(page.getByText('No linked experience yet')).toBeVisible();
});

test('Edit classification link navigates to the full taxonomy page', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await page.getByRole('link', { name: 'Edit classification' }).click();
  await expect(page).toHaveURL('/companies/CO-001/taxonomy');
});

test('Edit company popup opens and saves', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/companies/CO-001', { body: fixture.company });
  await page.goto('/companies/CO-001');
  await page.getByRole('button', { name: 'Edit company' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit company' });
  await expect(modal).toBeVisible();
  await modal.getByRole('textbox', { name: 'Name' }).fill('Renamed Co');
  await modal.getByRole('button', { name: 'Save company' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].name).toBe('Renamed Co');
});

test('Delete confirmation 409 renders inline without closing the alert', async ({ page }) => {
  await mockDelete(page, '**/api/companies/CO-001', {
    status: 409,
    body: { error: 'Still linked to 1 jobs', count: 1 },
  });
  await page.goto('/companies/CO-001');
  await page.getByRole('button', { name: 'Delete' }).click();
  const alert = page.getByRole('alertdialog', { name: 'Delete this company?' });
  await alert.getByRole('button', { name: 'Delete company' }).click();
  await expect(alert.getByText('Still linked to 1 jobs')).toBeVisible();
  await expect(alert).toBeVisible();
});

test('Delete confirmation succeeds and returns to the companies list', async ({ page }) => {
  await mockDelete(page, '**/api/companies/CO-001');
  await page.goto('/companies/CO-001');
  await page.getByRole('button', { name: 'Delete' }).click();
  const alert = page.getByRole('alertdialog', { name: 'Delete this company?' });
  await alert.getByRole('button', { name: 'Delete company' }).click();
  await expect(page).toHaveURL('/companies');
});
