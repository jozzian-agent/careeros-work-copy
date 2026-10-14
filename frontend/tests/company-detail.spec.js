// Protects the Company detail page's layout and actions: the one ask it
// makes of its owner (and the three cases that raise it), where each
// classification value came from, the linked records and the editing
// paths.
import { expect, test } from '@playwright/test';
import { loadFixture, mockCompanyPage, mockUpdate, mockDelete } from './helpers.js';

const fixture = loadFixture('company-detail');

// The ask: a classification field that is empty and that automation has
// run out of ideas on.
const needsSector = {
  ...fixture,
  company: { ...fixture.company, sectors: [], sector: null },
  sector_labels: [],
  classification: {
    sector: { value: null, source: null },
    size: fixture.classification.size,
  },
  needs_input: { field: 'sector', tried: ['jsonld', 'wikidata', 'llm'] },
};

test.beforeEach(async ({ page }) => {
  await mockCompanyPage(page, fixture);
});

test('header renders type label, title, subtitle, location, website and actions', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await expect(page.getByText('COMPANY', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: fixture.company.name })).toBeVisible();
  await expect(page.getByText('Information and communication · 51-200').first()).toBeVisible();
  await expect(page.getByText('Zurich, CH')).toBeVisible();
  await expect(page.getByRole('link', { name: new RegExp(fixture.company.website) })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit company' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete' })).toBeVisible();
});

test('back link navigates to the companies list', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await page.getByRole('link', { name: 'Back to Companies' }).click();
  await expect(page).toHaveURL('/companies');
});

test('sections render in the canvas order, with no Details section and no Name row', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('heading', { name: fixture.company.name })).toBeVisible();
  const headings = await page.getByRole('heading').allTextContents();
  const order = ['Jobs', 'Experiences', 'Classification', 'Notes'];
  const positions = order.map((label) => headings.indexOf(label));
  expect(positions.every((index) => index !== -1)).toBe(true);
  expect(positions).toEqual([...positions].sort((a, b) => a - b));
  // The Details card repeated the title as a Name row and the website
  // that is now in the header.
  await expect(page.getByRole('heading', { name: 'Details', exact: true })).toHaveCount(0);
  await expect(page.getByText('Name', { exact: true })).toHaveCount(0);
});

test('linked jobs and positions render as links with their state', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('link', { name: fixture.jobs[0].title })).toBeVisible();
  await expect(page.getByTestId('section-jobs').getByText('Interested')).toBeVisible();
  await expect(page.getByRole('link', { name: fixture.experiences[0].title })).toBeVisible();
  await expect(page.getByTestId('section-experiences').getByText('Past')).toBeVisible();
});

test('empty related-items sections show the dashed empty state', async ({ page }) => {
  await mockCompanyPage(page, { ...fixture, jobs: [], experiences: [] });
  await page.goto('/companies/CO-001');
  await expect(page.getByText('No jobs linked yet')).toBeVisible();
  await expect(page.getByText('No linked experience yet')).toBeVisible();
});

test('Classification names where the sector and the size came from', async ({ page }) => {
  await page.goto('/companies/CO-001');
  const classification = page.getByTestId('section-classification');
  await expect(classification.getByText('Found on Wikidata')).toBeVisible();
  await expect(classification.getByText("Found on the company's website")).toBeVisible();
});

test('an owner-set field says so instead of crediting a source', async ({ page }) => {
  await mockCompanyPage(page, {
    ...fixture,
    classification: {
      sector: { value: 'Information and communication', source: 'user' },
      size: { value: '51-200', source: 'llm' },
    },
  });
  await page.goto('/companies/CO-001');
  const classification = page.getByTestId('section-classification');
  await expect(classification.getByText('Set by you')).toBeVisible();
  await expect(classification.getByText('Found by AI')).toBeVisible();
});

// --- The one ask ---

test('no needs-input chip or card when both fields are known', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('heading', { name: 'Classification' })).toBeVisible();
  await expect(page.getByText('Needs your input')).toHaveCount(0);
});

test('an empty field automation gave up on raises the chip and the card it links to', async ({ page }) => {
  await mockCompanyPage(page, needsSector);
  await page.goto('/companies/CO-001');
  const chip = page.getByRole('link', { name: 'Needs your input' });
  await expect(chip).toBeVisible();
  await expect(chip).toHaveAttribute('href', '#needs-your-input');
  await expect(page.getByRole('heading', { name: 'Needs your input' })).toBeVisible();
  await expect(page.getByText('This company has no sector yet.')).toBeVisible();
  await expect(page.getByText("Tried: the company's website, Wikidata, AI.")).toBeVisible();
});

test('the size case names the size, not the sector', async ({ page }) => {
  await mockCompanyPage(page, {
    ...fixture,
    classification: { sector: fixture.classification.sector, size: { value: null, source: null } },
    needs_input: { field: 'size', tried: ['wikidata'] },
  });
  await page.goto('/companies/CO-001');
  await expect(page.getByText('This company has no size yet.')).toBeVisible();
  await expect(page.getByText('Tried: Wikidata.')).toBeVisible();
});

test('a field nothing has been tried for says that, rather than naming no sources', async ({ page }) => {
  await mockCompanyPage(page, { ...needsSector, needs_input: { field: 'sector', tried: [] } });
  await page.goto('/companies/CO-001');
  await expect(page.getByText('No source has been tried yet.')).toBeVisible();
});

// Bug 3: the card used to be raised by the page itself, from a review
// flag alone, which kept asking for a value the record already had.
test('a review flag on a field that has a value does not raise the card', async ({ page }) => {
  await mockCompanyPage(page, {
    ...fixture,
    company: { ...fixture.company, review_flags: ['sector-ambiguous'] },
  });
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('heading', { name: 'Classification' })).toBeVisible();
  await expect(page.getByText('Needs your input')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Try again' })).toHaveCount(0);
});

test('Set it yourself opens Edit classification and saves the sector and size', async ({ page }) => {
  await mockCompanyPage(page, needsSector);
  const requests = await mockUpdate(page, '**/api/companies/CO-001', { body: fixture.company });
  await page.goto('/companies/CO-001');
  await page.getByRole('button', { name: 'Set it yourself' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit classification' });
  await expect(modal).toBeVisible();
  await modal.getByLabel('Sector').selectOption('C');
  await modal.getByLabel('Size').selectOption('small');
  await modal.getByRole('button', { name: 'Save changes' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ sectors: ['C'], size_class: 'small' });
});

test('Try again runs the enrichment retry and reports what it did', async ({ page }) => {
  let current = needsSector;
  await page.route('**/api/companies/*?view=page', (route) => route.fulfill({ json: current }));
  await page.route('**/api/companies/*/retry', (route) => {
    current = fixture;
    route.fulfill({
      json: { ...fixture.company, retry_applied: ['sectors'], field_provenance: {} },
    });
  });
  await page.goto('/companies/CO-001');
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByText('Retry updated the company. Sector: filled')).toBeVisible();
  // The ask is answered, so the card and the chip go away on their own.
  await expect(page.getByRole('heading', { name: 'Needs your input' })).toHaveCount(0);
});

test('Try again failure shows a visible error', async ({ page }) => {
  await mockCompanyPage(page, needsSector);
  await page.route('**/api/companies/*/retry', (route) => route.fulfill({ status: 500, json: { error: 'nope' } }));
  await page.goto('/companies/CO-001');
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByText('Retry failed.')).toBeVisible();
});

// --- Editing ---

test('Edit classification opens from the Classification card too', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await page.getByRole('button', { name: 'Edit classification' }).click();
  await expect(page.getByRole('dialog', { name: 'Edit classification' })).toBeVisible();
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

test('empty Notes offer the dashed Add a note box, which opens Edit company at the notes field', async ({ page }) => {
  await mockCompanyPage(page, { ...fixture, company: { ...fixture.company, notes: '' } });
  await page.goto('/companies/CO-001');
  await expect(page.getByText('No notes yet.')).toBeVisible();
  await page.getByRole('button', { name: 'Add a note' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit company' });
  await expect(modal).toBeVisible();
  await expect(modal.getByRole('textbox', { name: 'Notes' })).toBeFocused();
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
  // /companies is the server-rendered list page, not an App.jsx route --
  // a client-side navigate() would leave the SPA on a blank page with no
  // matching Route while still showing the new URL. Fulfilling the real
  // document request here proves a full-document navigation actually
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

// The /companies/<id>/taxonomy page and its JSON endpoint are gone
// (tests/test_taxonomy_pages.py pins the 404s); nothing in the app may
// stand for it either.
test('nothing links to the retired company classification page', async ({ page }) => {
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('heading', { name: 'Classification' })).toBeVisible();
  await expect(page.getByRole('link', { name: /classification/i })).toHaveCount(0);
  // The nav's own /taxonomy tab is a different page and stays.
  await expect(page.locator('a[href*="companies"][href*="taxonomy"]')).toHaveCount(0);
});
