import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard } from './helpers.js';

const fixture = loadBoardFixture();

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('chip order is Fit, Function, Location, More filters, Needs attention', async ({ page }) => {
  await page.goto('/jobs');
  const chips = page.locator('[data-testid^="filter-chip-"]');
  await expect(chips).toHaveCount(5);
  const testIds = await chips.evaluateAll((nodes) => nodes.map((node) => node.dataset.testid));
  expect(testIds).toEqual([
    'filter-chip-fit',
    'filter-chip-function',
    'filter-chip-location',
    'filter-chip-more',
    'filter-chip-needs-attention',
  ]);
});

test('a Function chip selection opens its panel, filters the board, and shows a removable active-filter Tag', async ({
  page,
}) => {
  await page.goto('/jobs');
  const [targetId, targetLabel] = fixture.function_options[0];
  const matching = fixture.entries.filter((entry) => entry.function.includes(targetId));
  const nonMatching = fixture.entries.filter((entry) => !entry.function.includes(targetId));
  expect(matching.length).toBeGreaterThan(0);
  expect(nonMatching.length).toBeGreaterThan(0);
  const total = fixture.entries.length;

  await expect(page.getByText(`${total} jobs`, { exact: true })).toBeVisible();

  const chip = page.getByTestId('filter-chip-function');
  await expect(chip).toHaveAttribute('aria-expanded', 'false');
  await chip.click();
  await expect(chip).toHaveAttribute('aria-expanded', 'true');

  await page.getByRole('checkbox', { name: targetLabel }).check();
  for (const entry of matching) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
  for (const entry of nonMatching) {
    await expect(page.getByText(entry.title, { exact: true })).toHaveCount(0);
  }
  await expect(page.getByText(`${matching.length} of ${total} jobs`, { exact: true })).toBeVisible();

  const tagText = `Function: ${targetLabel}`;
  await expect(page.getByText(tagText, { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await expect(chip).toHaveAttribute('aria-expanded', 'false');

  // Removing the Tag clears the filter, restores every card, and drops
  // the result count back to the plain "N jobs" form.
  await page.getByRole('button', { name: `Remove ${tagText}` }).click();
  for (const entry of fixture.entries) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
  await expect(page.getByText(`${total} jobs`, { exact: true })).toBeVisible();
});

test('Location and Fit filters combine, and Clear all resets every group and the result count', async ({ page }) => {
  await page.goto('/jobs');

  await page.getByTestId('filter-chip-fit').click();
  await page.getByRole('checkbox', { name: 'Excellent fit' }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();

  // Location has more than 6 distinct values in the fixture, so the panel's
  // own search field (rather than relying on where it falls in the
  // "Show N more" list) is the robust way to reach any one option.
  const firstLocation = fixture.entries.find((entry) => entry.location)?.location;
  await page.getByTestId('filter-chip-location').click();
  await page.getByRole('searchbox', { name: 'Search location' }).fill(firstLocation);
  await page.getByRole('checkbox', { name: firstLocation }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();

  const expected = fixture.entries.filter((entry) => entry.fit === 'excellent' && entry.location === firstLocation);
  const excluded = fixture.entries.filter((entry) => !(entry.fit === 'excellent' && entry.location === firstLocation));
  for (const entry of expected) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
  for (const entry of excluded) {
    await expect(page.getByText(entry.title, { exact: true })).toHaveCount(0);
  }

  await expect(page.getByText('Active filters')).toBeVisible();
  await page.getByRole('button', { name: 'Clear all', exact: true }).click();

  await expect(page.getByText('Active filters')).toHaveCount(0);
  for (const entry of fixture.entries) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
  await expect(page.getByText(`${fixture.entries.length} jobs`, { exact: true })).toBeVisible();
});

test('Needs attention alone shows Clear all, and clearing it resets the toggle', async ({ page }) => {
  await page.goto('/jobs');
  const toggle = page.getByRole('button', { name: 'Needs attention', exact: true });

  await expect(page.getByText('Active filters')).toHaveCount(0);
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');

  await expect(page.getByText('Active filters')).toBeVisible();
  const clearAll = page.getByRole('button', { name: 'Clear all', exact: true });
  await expect(clearAll).toBeVisible();

  await clearAll.click();

  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByText('Active filters')).toHaveCount(0);
});

test('Clear all resets Needs attention together with a group filter', async ({ page }) => {
  await page.goto('/jobs');
  const toggle = page.getByRole('button', { name: 'Needs attention', exact: true });
  await toggle.click();

  await page.getByTestId('filter-chip-fit').click();
  await page.getByRole('checkbox', { name: 'Excellent fit' }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();

  await expect(page.getByText('Active filters')).toBeVisible();
  await page.getByRole('button', { name: 'Clear all', exact: true }).click();

  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByText('Active filters')).toHaveCount(0);
  for (const entry of fixture.entries) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
  await expect(page.getByText(`${fixture.entries.length} jobs`, { exact: true })).toBeVisible();
});

test('More filters opens Industry and Company size, and a selection narrows the board', async ({ page }) => {
  await page.goto('/jobs');
  const target = fixture.entries.find((entry) => entry.industries?.length);
  expect(target).toBeTruthy();
  const matching = fixture.entries.filter((entry) => (entry.industries || []).includes(target.industries[0]));
  const nonMatching = fixture.entries.filter((entry) => !(entry.industries || []).includes(target.industries[0]));

  await page.getByTestId('filter-chip-more').click();
  await expect(page.getByRole('heading', { name: 'More filters' })).toBeVisible();

  await page.getByRole('checkbox', { name: target.industries[0] }).check();
  for (const entry of matching) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
  for (const entry of nonMatching) {
    await expect(page.getByText(entry.title, { exact: true })).toHaveCount(0);
  }

  await page.getByRole('button', { name: /^Show \d+ jobs$/ }).click();
  await expect(page.getByRole('heading', { name: 'More filters' })).toHaveCount(0);
});

test('a Company size selection in More filters narrows the board by the matching bucket', async ({ page }) => {
  await page.goto('/jobs');
  const target = fixture.entries.find((entry) => typeof entry.employee_count === 'number' && entry.employee_count <= 10);
  expect(target).toBeTruthy();

  await page.getByTestId('filter-chip-more').click();
  await page.getByRole('checkbox', { name: /^Micro/ }).check();

  await expect(page.getByText(target.title, { exact: true })).toBeVisible();
  const outOfBucket = fixture.entries.find(
    (entry) => typeof entry.employee_count === 'number' && entry.employee_count > 10,
  );
  if (outOfBucket) {
    await expect(page.getByText(outOfBucket.title, { exact: true })).toHaveCount(0);
  }
});
