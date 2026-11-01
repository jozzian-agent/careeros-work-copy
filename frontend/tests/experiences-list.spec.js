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

test('Add position links to the Add position page', async ({ page }) => {
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

// CAREER-118 PR 3, CollectionPage README: the box repeats the action in
// gray, and the heading row keeps the page's one primary fill. Two "Add
// position" links on an empty page -- the heading row's and the box's --
// and only the first is the brand green.
test('the empty-state Add position is gray, and only the heading row carries the primary fill', async ({ page }) => {
  await mockExperiencesPage(page, { ...fixture, entries: [] });
  await page.goto('/experiences');

  const links = page.getByRole('link', { name: 'Add position' });
  await expect(links).toHaveCount(2);
  // Gestalt paints a ButtonLink's ground on the anchor itself or on its
  // inner element depending on the variant, so this reads whichever of
  // the two actually carries one rather than assuming the nesting.
  const ground = (locator) =>
    locator.evaluate((el) => {
      const painted = [el, ...el.querySelectorAll('*')]
        .map((node) => getComputedStyle(node).backgroundColor)
        .filter((color) => color !== 'rgba(0, 0, 0, 0)' && color !== 'transparent');
      return painted[0] || 'rgba(0, 0, 0, 0)';
    });
  expect(await ground(links.nth(0))).toBe('rgb(0, 135, 83)'); // --color-brand-primary
  expect(await ground(links.nth(1))).not.toBe('rgb(0, 135, 83)');
});

test('a load failure shows a visible error with Retry', async ({ page }) => {
  await page.route('**/api/experiences?view=page', (route) => route.fulfill({ status: 500, json: { error: 'nope' } }));
  await page.goto('/experiences');
  await expect(page.getByText('Could not load your experiences.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
});
