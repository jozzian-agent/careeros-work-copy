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

test('Classification section links nowhere now the taxonomy page is retired', async ({ page }) => {
  // The /companies/<id>/taxonomy route and its JSON endpoint were removed,
  // so the old "Edit classification" link pointed at a 404. Classification
  // editing returns in a later round.
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('heading', { name: 'Classification' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Edit classification' })).toHaveCount(0);
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

test('Delete confirmation succeeds and performs a full navigation that actually reaches the companies list page', async ({
  page,
}) => {
  // /companies is the server-rendered Jinja list page, not an App.jsx
  // route -- a client-side navigate() would leave the SPA on a blank page
  // with no matching Route while still showing the new URL. Fulfilling the
  // real document request here proves a full-document navigation actually
  // happened, not just that the URL string changed.
  await mockDelete(page, '**/api/companies/CO-001');
  await page.route('**/companies', (route) => {
    if (route.request().resourceType() !== 'document') {
      route.fallback();
      return;
    }
    route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: '<!doctype html><html><body><h1>Companies (mock list page)</h1></body></html>',
    });
  });
  await page.goto('/companies/CO-001');
  await page.getByRole('button', { name: 'Delete' }).click();
  const alert = page.getByRole('alertdialog', { name: 'Delete this company?' });
  await alert.getByRole('button', { name: 'Delete company' }).click();
  await expect(page).toHaveURL('/companies');
  await expect(page.getByRole('heading', { name: 'Companies (mock list page)' })).toBeVisible();
});

test('Retry failure shows a visible error', async ({ page }) => {
  await mockCompanyPage(page, { ...fixture, company: { ...fixture.company, website: null, sectors: [], size_range: null, size_class: null } });
  await page.route('**/api/companies/*/retry', (route) => route.fulfill({ status: 500, json: { error: 'nope' } }));
  await page.goto('/companies/CO-001');
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByText('Retry failed.')).toBeVisible();
});

test('Retry success surfaces retry_applied and outcome details, and keeps showing once the company is no longer retry-eligible', async ({ page }) => {
  // Starts retry-eligible (no sectors/size), same as the other Retry tests.
  // The mocked retry call then refreshes `current` to a fully-enriched
  // record -- sectors and size filled, no review flags -- so the
  // subsequent load() makes retryState(company) return null and the
  // Retry button/eligibility text disappear. The outcome banner must stay
  // visible regardless, since it no longer depends on retry eligibility.
  let current = { ...fixture, company: { ...fixture.company, website: null, sectors: [], size_range: null, size_class: null } };
  await page.route('**/api/companies/*?view=page', (route) => route.fulfill({ json: current }));
  await page.route('**/api/companies/*/retry', (route) => {
    current = {
      ...current,
      company: {
        ...current.company,
        sectors: ['J'],
        size_range: '51-200',
        enrichment: { field_states: { sectors: { state: 'filled' }, size: { state: 'filled' } } },
      },
    };
    route.fulfill({
      json: {
        ...current.company,
        retry_applied: ['sectors'],
        field_provenance: {},
      },
    });
  });
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByText('Retry updated the company. Sector: filled')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry' })).toHaveCount(0);
  await expect(page.getByText('Retry updated the company. Sector: filled')).toBeVisible();
});
