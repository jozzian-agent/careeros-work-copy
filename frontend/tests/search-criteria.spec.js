import { expect, test } from '@playwright/test';
import { loadFixture, mockSearchPage, mockSaveSearch } from './helpers.js';

const fixture = loadFixture('search-criteria');

const SAVED_RECORD = {
  roles: ['Platform engineering lead', 'Staff engineer'],
  must_haves: [],
  nice_to_haves: [],
  avoid: ['On-call rotation'],
  notes: 'Updated notes',
  updated: '2026-10-13',
};

test.beforeEach(async ({ page }) => {
  await mockSearchPage(page, fixture);
});

test('renders one section per criteria group plus Notes, read-only', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Search' })).toBeVisible();
  for (const label of ['Roles', 'Must-haves', 'Nice-to-haves', 'Avoid', 'Notes']) {
    await expect(page.getByRole('heading', { name: label })).toBeVisible();
  }
  await expect(page.getByText('Platform engineering lead')).toBeVisible();
  await expect(page.getByText('Prefer teams that ship in small batches.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit criteria' })).toBeVisible();
});

test('Edit criteria enters edit mode, Done saves, and the returned record stays displayed', async ({ page }) => {
  const requests = await mockSaveSearch(page, { body: SAVED_RECORD });
  await page.goto('/');
  await page.getByRole('button', { name: 'Edit criteria' }).click();
  await expect(page.getByRole('button', { name: 'Done' })).toBeVisible();

  await page.getByRole('button', { name: 'Remove Remote-friendly' }).click();
  await expect(page.getByText('Remote-friendly')).toHaveCount(0);

  await page.getByLabel('New roles item').fill('Staff engineer');
  await page.getByRole('button', { name: 'Add' }).first().click();
  await expect(page.getByText('Staff engineer')).toBeVisible();

  await page.getByLabel('Notes').fill('Updated notes');

  await page.getByRole('button', { name: 'Done' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].roles).toContain('Staff engineer');
  expect(requests[0].must_haves).toEqual([]);
  expect(requests[0].notes).toBe('Updated notes');

  await expect(page.getByRole('button', { name: 'Edit criteria' })).toBeVisible();
  await expect(page.getByText('Staff engineer')).toBeVisible();
  await expect(page.getByText('On-call rotation')).toBeVisible();
  await expect(page.getByText('Updated notes')).toBeVisible();
});

test('Done and Cancel are disabled while the save request is in flight, and exactly one request fires', async ({ page }) => {
  const requests = [];
  let releaseResponse;
  const held = new Promise((resolve) => {
    releaseResponse = resolve;
  });
  await page.route('**/api/search', async (route) => {
    if (route.request().method() !== 'POST') {
      route.fallback();
      return;
    }
    requests.push(route.request().postDataJSON());
    await held;
    route.fulfill({ json: SAVED_RECORD });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Edit criteria' }).click();
  await page.getByRole('button', { name: 'Done' }).click();

  await expect(page.getByRole('button', { name: 'Done' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Cancel' })).toBeDisabled();

  releaseResponse();
  await expect(page.getByRole('button', { name: 'Edit criteria' })).toBeVisible();
  expect(requests.length).toBe(1);
});

test('Cancel restores the pre-edit backup without saving', async ({ page }) => {
  const requests = await mockSaveSearch(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Edit criteria' }).click();
  await page.getByRole('button', { name: 'Remove Remote-friendly' }).click();
  await expect(page.getByText('Remote-friendly')).toHaveCount(0);

  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('button', { name: 'Edit criteria' })).toBeVisible();
  await expect(page.getByText('Remote-friendly')).toBeVisible();
  expect(requests.length).toBe(0);
});

test('a save failure keeps the edits, shows an error banner, and a retry succeeds', async ({ page }) => {
  const requests = [];
  let failNext = true;
  await page.route('**/api/search', (route) => {
    if (route.request().method() !== 'POST') {
      route.fallback();
      return;
    }
    requests.push(route.request().postDataJSON());
    if (failNext) {
      failNext = false;
      route.fulfill({ status: 500, json: { error: 'Save failed.' } });
    } else {
      route.fulfill({ json: SAVED_RECORD });
    }
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Edit criteria' }).click();
  await page.getByLabel('Notes').fill('Changed but not saved');
  await page.getByRole('button', { name: 'Done' }).click();
  await expect(page.getByText('Save failed.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Done' })).toBeVisible();
  await expect(page.getByLabel('Notes')).toHaveValue('Changed but not saved');

  await page.getByRole('button', { name: 'Done' }).click();
  await expect.poll(() => requests.length).toBe(2);
  await expect(page.getByRole('button', { name: 'Edit criteria' })).toBeVisible();
});

test('no criteria yet shows the empty state with Create criteria', async ({ page }) => {
  await mockSearchPage(page, { ...fixture, data: null });
  const requests = await mockSaveSearch(page, { body: { roles: [], must_haves: [], nice_to_haves: [], avoid: [], notes: '' } });
  await page.goto('/');
  await expect(page.getByText(fixture.empty)).toBeVisible();
  await mockSearchPage(page, fixture);
  await page.getByRole('button', { name: 'Create criteria' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({});
  await expect(page.getByRole('heading', { name: 'Roles' })).toBeVisible();
});
