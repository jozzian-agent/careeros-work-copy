import { expect, test } from '@playwright/test';
import {
  loadFixture,
  mockExperiencePage,
  mockExperienceTagsRegistry,
  mockUpdate,
  mockDelete,
} from './helpers.js';

const fixture = loadFixture('experience-detail');
const tagsRegistry = loadFixture('experience-tags-registry');

test.beforeEach(async ({ page }) => {
  await mockExperiencePage(page, fixture);
  await mockExperienceTagsRegistry(page, tagsRegistry);
});

test('header renders type label, title, subtitle and actions', async ({ page }) => {
  await page.goto('/experiences/EXP-001');
  await expect(page.getByText('EXPERIENCE', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: fixture.exp.title })).toBeVisible();
  await expect(page.getByRole('link', { name: fixture.label }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit position' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete' })).toBeVisible();
});

test('back link navigates to the experiences list', async ({ page }) => {
  await page.goto('/experiences/EXP-001');
  await page.getByRole('link', { name: 'Back to Experiences' }).click();
  await expect(page).toHaveURL('/experiences');
});

test('sections render in order: summary, content, details', async ({ page }) => {
  await page.goto('/experiences/EXP-001');
  await expect(page.getByRole('heading', { name: fixture.exp.title })).toBeVisible();
  const headings = await page.getByRole('heading').allTextContents();
  const order = ['Summary', 'Highlights', 'Content', 'Details'];
  const positions = order.map((label) => headings.indexOf(label));
  expect(positions.every((index) => index !== -1)).toBe(true);
  expect(positions).toEqual([...positions].sort((a, b) => a - b));
});

test('Edit position popup opens with the full form and saves', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/experiences/EXP-001', { body: fixture.exp });
  await page.goto('/experiences/EXP-001');
  await page.getByRole('button', { name: 'Edit position' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit position' });
  await expect(modal).toBeVisible();
  await expect(modal.getByRole('textbox', { name: 'Title' })).toHaveValue(fixture.exp.title);
  await expect(modal.getByRole('textbox', { name: 'Salary' })).toHaveValue('Managed in the vault file only');
  await modal.getByRole('textbox', { name: 'Summary (2–4 sentences)' }).fill('Updated summary.');
  await modal.getByRole('button', { name: 'Save position' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].summary).toBe('Updated summary.');
});

test('Delete confirmation deletes and performs a full navigation that actually reaches the experiences list page', async ({ page }) => {
  // /experiences is the server-rendered Jinja list page, not an App.jsx
  // route -- a client-side navigate() would leave the SPA on a blank page
  // with no matching Route while still showing the new URL. Fulfilling the
  // real document request here proves a full-document navigation actually
  // happened, not just that the URL string changed.
  await mockDelete(page, '**/api/experiences/EXP-001');
  await page.route('**/experiences', (route) => {
    if (route.request().resourceType() !== 'document') {
      route.fallback();
      return;
    }
    route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: '<!doctype html><html><body><h1>Experiences (mock list page)</h1></body></html>',
    });
  });
  await page.goto('/experiences/EXP-001');
  await page.getByRole('button', { name: 'Delete' }).click();
  const alert = page.getByRole('alertdialog', { name: 'Delete this position?' });
  await alert.getByRole('button', { name: 'Delete position' }).click();
  await expect(page).toHaveURL('/experiences');
  await expect(page.getByRole('heading', { name: 'Experiences (mock list page)' })).toBeVisible();
});

test('Tag registry load failure shows a visible error and does not open the Edit position popup', async ({ page }) => {
  await page.route('**/api/experiences/new', (route) => route.fulfill({ status: 500, json: { error: 'nope' } }));
  await page.goto('/experiences/EXP-001');
  await page.getByRole('button', { name: 'Edit position' }).click();
  await expect(page.getByText('Could not load the tag registry.')).toBeVisible();
  await expect(page.getByRole('dialog', { name: 'Edit position' })).not.toBeVisible();
});

test('a structured salary value renders instead of crashing the page', async ({ page }) => {
  await mockExperiencePage(page, { ...fixture, exp: { ...fixture.exp, salary: { amount: 42000, currency: 'CHF' } } });
  await page.goto('/experiences/EXP-001');
  await expect(page.getByRole('heading', { name: 'Salary' })).toBeVisible();
  await expect(page.getByText('amount: 42000')).toBeVisible();
  await expect(page.getByText('currency: CHF')).toBeVisible();
});

test('Cancelling after linking a new company keeps the link even when reopened before the refresh GET resolves', async ({ page }) => {
  let current = fixture;
  // The initial mount's load() fires its view=page GET straight through
  // below (React StrictMode double-invokes that effect in dev, so this can
  // be more than one request). Only once the page has actually rendered
  // does `holdRefresh` flip on, so the one GET that matters -- the
  // Cancel-triggered refresh from handleEditDismiss -- is queued instead of
  // fulfilled, and can be held open for as long as the test likes.
  let holdRefresh = false;
  const pending = [];
  await page.route('**/api/experiences/*?view=page', (route) => {
    if (!holdRefresh) {
      route.fulfill({ json: current });
      return;
    }
    pending.push(route);
  });
  await page.route('**/api/experiences/EXP-001/link-company', (route) => {
    current = {
      ...current,
      exp: { ...current.exp, company_id: 'CO-999', company: 'New Startup Co' },
      label: 'New Startup Co',
      companies: { ...current.companies, 'CO-999': { id: 'CO-999', name: 'New Startup Co' } },
    };
    route.fulfill({ json: { company_id: 'CO-999' } });
  });
  await mockExperienceTagsRegistry(page, tagsRegistry);
  const saveRequests = await mockUpdate(page, '**/api/experiences/EXP-001', { body: fixture.exp });

  await page.goto('/experiences/EXP-001');
  await expect(page.getByRole('heading', { name: fixture.exp.title })).toBeVisible();
  holdRefresh = true;

  await page.getByRole('button', { name: 'Edit position' }).click();
  let modal = page.getByRole('dialog', { name: 'Edit position' });
  await modal.getByRole('textbox', { name: 'Company' }).fill('New Startup Co');
  await modal.getByRole('button', { name: /link new company/i }).click();
  await expect(modal.getByText('Linked to New Startup Co')).toBeVisible();
  await modal.getByRole('button', { name: 'Cancel' }).click();
  await expect(modal).not.toBeVisible();

  // The Cancel-triggered refresh (handleEditDismiss -> load()) is now in
  // flight but deliberately left unfulfilled below -- reopening here must
  // show the linked company from ExperienceDetail's synchronous
  // handleCompanyLinked update, not from this still-pending GET.
  await expect.poll(() => pending.length).toBe(1);

  await page.getByRole('button', { name: 'Edit position' }).click();
  modal = page.getByRole('dialog', { name: 'Edit position' });
  await expect(modal.getByRole('textbox', { name: 'Company' })).toHaveValue('New Startup Co');
  await modal.getByRole('textbox', { name: 'Title' }).fill('Updated Title');
  await modal.getByRole('button', { name: 'Save position' }).click();
  await expect.poll(() => saveRequests.length).toBe(1);
  expect(saveRequests[0].company_id).toBe('CO-999');

  // Release the held refresh so the page/context can tear down cleanly.
  pending.shift().fulfill({ json: current });
});

test('adding a proposed skill tag sends it in both tags and proposed_tags', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/experiences/EXP-001', { body: fixture.exp });
  await page.goto('/experiences/EXP-001');
  await page.getByRole('button', { name: 'Edit position' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit position' });
  await modal.getByRole('textbox', { name: 'Propose a new tag' }).fill('Public speaking coaching');
  await modal.getByRole('button', { name: '+ Add tag' }).click();
  // Unregistered yet, so it renders under its raw facet:id token (the
  // registry has no label for it to show instead).
  await expect(modal.getByRole('checkbox', { name: 'skill/capability:public-speaking-coaching' })).toBeChecked();
  await modal.getByRole('button', { name: 'Save position' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].tags).toContain('skill/capability:public-speaking-coaching');
  expect(requests[0].proposed_tags).toEqual(['skill/capability:public-speaking-coaching']);
});

test('the full skills registry is selectable, including a tag removed from this experience', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/experiences/EXP-001', { body: fixture.exp });
  await page.goto('/experiences/EXP-001');
  await page.getByRole('button', { name: 'Edit position' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit position' });
  // Not yet selected on this experience, but present in the registry.
  await modal.getByRole('combobox', { name: 'Add from registry' }).selectOption({ label: 'Stakeholder management' });
  await modal.getByRole('button', { name: '+ Add from registry' }).click();
  await expect(modal.getByRole('checkbox', { name: 'Stakeholder management' })).toBeChecked();
  // Removing the pre-existing selected tag must make it reappear in the
  // registry dropdown rather than vanish with no way back. The checkbox
  // itself unmounts once unchecked (it is only rendered while selected),
  // so a plain click -- not .uncheck(), which waits for the same element
  // to report unchecked -- is the right action here.
  await modal.getByRole('checkbox', { name: 'Public speaking' }).click();
  await expect(
    modal.getByRole('combobox', { name: 'Add from registry' }).getByRole('option', { name: 'Public speaking' }),
  ).toHaveCount(1);
  await modal.getByRole('button', { name: 'Save position' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].tags).toContain('skill/capability:stakeholder-management');
  expect(requests[0].tags).not.toContain('skill/capability:public-speaking');
});

test('a blank custom-field key blocks save with a visible message', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/experiences/EXP-001', { body: fixture.exp });
  await page.goto('/experiences/EXP-001');
  await page.getByRole('button', { name: 'Edit position' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit position' });
  await modal.getByRole('button', { name: 'Add custom field' }).click();
  await modal.getByRole('textbox', { name: 'Value', exact: true }).last().fill('some value');
  await modal.getByRole('button', { name: 'Save position' }).click();
  await expect(modal.getByText('Each custom field needs a key.')).toBeVisible();
  expect(requests.length).toBe(0);
});

test('duplicate custom-field keys block save with a visible message', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/experiences/EXP-001', { body: fixture.exp });
  await page.goto('/experiences/EXP-001');
  await page.getByRole('button', { name: 'Edit position' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit position' });
  await modal.getByRole('button', { name: 'Add custom field' }).click();
  const keys = modal.getByRole('textbox', { name: 'Key', exact: true });
  await keys.nth(0).fill('Clearance');
  await keys.nth(1).fill('Clearance');
  await modal.getByRole('button', { name: 'Save position' }).click();
  await expect(modal.getByText('Custom field keys must be unique.')).toBeVisible();
  expect(requests.length).toBe(0);
});
