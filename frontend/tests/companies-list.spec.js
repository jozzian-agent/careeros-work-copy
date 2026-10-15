// Protects the Companies directory: one equal-sized card per company
// with a truthful open-jobs chip, the shared FilterBar's four filters over
// it, and a grid that stays a grid at 1280px and 390px.
import { expect, test } from '@playwright/test';
import { loadFixture, mockCompaniesPage } from './helpers.js';

const fixture = loadFixture('companies-list');
const TOTAL = fixture.entries.length;
const LONG_NAME = fixture.entries.find((entry) => entry.name.length > 30).name;
// The owner's rule, applied here rather than hard-coded, so the spec says
// what the rule is: 30 characters of the name, then one ellipsis.
const TRUNCATED = `${LONG_NAME.slice(0, 30)}…`;

function card(page, id) {
  return page.getByTestId(`company-card-${id}`);
}

async function boxes(page) {
  return Promise.all(fixture.entries.map((entry) => card(page, entry.id).boundingBox()));
}

test.beforeEach(async ({ page }) => {
  await mockCompaniesPage(page, fixture);
});

test('a card per company carries its sector line, size line and open-jobs chip', async ({ page }) => {
  await page.goto('/companies');
  await expect(page.getByRole('heading', { name: 'Companies' })).toBeVisible();

  await expect(card(page, 'CO-001')).toContainText('Information and communication');
  await expect(card(page, 'CO-001')).toContainText('Small');
  // The class is the one size scale: CO-004 still carries a stored
  // "1000+" range, and the card must read its class instead.
  await expect(card(page, 'CO-004')).toContainText('Large');
  await expect(card(page, 'CO-004')).not.toContainText('1000+');
  // No sectors and no size class each say so rather than going blank.
  await expect(card(page, 'CO-005')).toContainText('Sector unknown');
  await expect(card(page, 'CO-005')).toContainText('Size unknown');
  // A record with a range and no class (what the migration deliberately
  // leaves alone, and what enrichment can write back) reads "Size
  // unknown" rather than falling back to the range: the class is the one
  // size scale the card speaks.
  await expect(card(page, 'CO-006')).toContainText('Size unknown');
  await expect(card(page, 'CO-006')).not.toContainText('51-250');
  await expect(page.getByRole('link', { name: /Lantern Peak/ })).toHaveAttribute('href', '/companies/CO-003');
});

test('the open-jobs chip counts only open jobs, in singular, plural and none', async ({ page }) => {
  await page.goto('/companies');
  // Exact text: "1 open jobs" would pass a substring check.
  await expect(card(page, 'CO-001').getByText('3 open jobs', { exact: true })).toBeVisible();
  await expect(card(page, 'CO-002').getByText('1 open job', { exact: true })).toBeVisible();
  await expect(card(page, 'CO-003').getByText('No open jobs', { exact: true })).toBeVisible();
  await expect(card(page, 'CO-004').getByText('No open jobs', { exact: true })).toBeVisible();
});

test('a name longer than 30 characters is cut with one ellipsis and keeps the full name as its tooltip', async ({
  page,
}) => {
  await page.goto('/companies');
  const name = page.getByTitle(LONG_NAME, { exact: true });
  expect(await name.textContent()).toBe(TRUNCATED);
  // Short names are left exactly as stored, tooltip and all.
  expect(await page.getByTitle('Harbor Labs', { exact: true }).textContent()).toBe('Harbor Labs');
});

test('every card is the same width and height at 1280px, however long its sector label', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/companies');
  const measured = await boxes(page);

  const heights = new Set(measured.map((box) => box.height));
  const widths = new Set(measured.map((box) => box.width));
  expect(heights.size).toBe(1);
  expect(widths.size).toBe(1);
  // More than one column, so "equal" is not just one card per row.
  expect(new Set(measured.map((box) => box.y)).size).toBeLessThan(fixture.entries.length);
});

test('at 390px the grid is one equal-height column and nothing scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/companies');
  const measured = await boxes(page);

  expect(new Set(measured.map((box) => box.height)).size).toBe(1);
  expect(new Set(measured.map((box) => box.x)).size).toBe(1);
  expect(new Set(measured.map((box) => box.y)).size).toBe(fixture.entries.length);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await expect(card(page, 'CO-001')).toContainText('3 open jobs');
});

test('the Sector filter matches any of a company sectors and shows a removable active-filter tag', async ({ page }) => {
  await page.goto('/companies');
  await expect(page.getByText(`${TOTAL} companies`, { exact: true })).toBeVisible();

  await page.getByTestId('filter-chip-sector').click();
  await page.getByRole('checkbox', { name: 'Manufacturing' }).check();

  // CO-003 matches on its second sector, which is what "any" means.
  await expect(card(page, 'CO-002')).toBeVisible();
  await expect(card(page, 'CO-003')).toBeVisible();
  await expect(card(page, 'CO-001')).toHaveCount(0);
  await expect(page.getByText(`2 of ${TOTAL} companies`, { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await page.getByRole('button', { name: 'Remove Sector: Manufacturing' }).click();
  await expect(page.getByText(`${TOTAL} companies`, { exact: true })).toBeVisible();
});

test('the Size filter offers only the classes companies are in, and filters by class', async ({ page }) => {
  await page.goto('/companies');
  await page.getByTestId('filter-chip-size').click();

  // Small, Medium, Large and no Micro: no company is in that class, so
  // the panel does not offer a box that would empty the grid.
  await expect(page.getByRole('checkbox')).toHaveCount(3);
  for (const label of ['Small', 'Medium', 'Large']) {
    await expect(page.getByRole('checkbox', { name: label })).toBeVisible();
  }

  await page.getByRole('checkbox', { name: 'Large' }).check();
  await expect(card(page, 'CO-002')).toBeVisible();
  await expect(card(page, 'CO-004')).toBeVisible();
  await expect(card(page, 'CO-001')).toHaveCount(0);
  await expect(card(page, 'CO-005')).toHaveCount(0);
});

test('the Open jobs filter separates companies with open jobs from those without', async ({ page }) => {
  await page.goto('/companies');
  await page.getByTestId('filter-chip-openJobs').click();

  await page.getByRole('checkbox', { name: 'With open jobs' }).check();
  await expect(card(page, 'CO-001')).toBeVisible();
  await expect(card(page, 'CO-002')).toBeVisible();
  await expect(card(page, 'CO-005')).toBeVisible();
  await expect(card(page, 'CO-003')).toHaveCount(0);
  await expect(card(page, 'CO-004')).toHaveCount(0);

  await page.getByRole('checkbox', { name: 'With open jobs' }).uncheck();
  await page.getByRole('checkbox', { name: 'Without open jobs' }).check();
  await expect(card(page, 'CO-003')).toBeVisible();
  await expect(card(page, 'CO-004')).toBeVisible();
  await expect(card(page, 'CO-001')).toHaveCount(0);
});

test('checking both Open jobs boxes asks for both, which is Any', async ({ page }) => {
  // Deliberate: the facet's two boxes are match-ANY like every other
  // group, so asking for both is asking for every company -- the same
  // thing as asking for neither. A refactor to a radio group would
  // silently change that.
  await page.goto('/companies');
  await page.getByTestId('filter-chip-openJobs').click();
  await page.getByRole('checkbox', { name: 'With open jobs' }).check();
  await page.getByRole('checkbox', { name: 'Without open jobs' }).check();

  await expect(page.getByText(`${TOTAL} of ${TOTAL} companies`, { exact: true })).toBeVisible();
  for (const entry of fixture.entries) {
    await expect(card(page, entry.id)).toBeVisible();
  }
});

test('Needs your input counts the flagged companies and narrows to them, at 390px too', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/companies');
  const flagged = fixture.entries.filter((entry) => entry.needs_attention);
  const toggle = page.getByRole('button', { name: 'Needs your input', exact: true });

  await expect(toggle).toHaveText(new RegExp(`${flagged.length}$`));
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');

  for (const entry of flagged) {
    await expect(card(page, entry.id)).toBeVisible();
  }
  await expect(card(page, 'CO-001')).toHaveCount(0);
  await expect(page.getByText(`${flagged.length} of ${TOTAL} companies`, { exact: true })).toBeVisible();
});

test('Clear all drops every filter and the toggle together', async ({ page }) => {
  await page.goto('/companies');
  await page.getByRole('button', { name: 'Needs your input', exact: true }).click();
  await page.getByTestId('filter-chip-size').click();
  await page.getByRole('checkbox', { name: 'Large' }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();

  await expect(page.getByText('Active filters')).toBeVisible();
  await page.getByRole('button', { name: 'Clear all', exact: true }).click();

  await expect(page.getByText('Active filters')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Needs your input', exact: true })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  await expect(page.getByText(`${TOTAL} companies`, { exact: true })).toBeVisible();
});

test('a filter choice survives a reload (localStorage, no URL state)', async ({ page }) => {
  await page.goto('/companies');
  await page.getByTestId('filter-chip-size').click();
  await page.getByRole('checkbox', { name: 'Large' }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();

  await page.reload();

  expect(new URL(page.url()).search).toBe('');
  await expect(page.getByText('Size: Large', { exact: true })).toBeVisible();
  await expect(card(page, 'CO-002')).toBeVisible();
  await expect(card(page, 'CO-001')).toHaveCount(0);
});

test('a filter combination that matches nothing says so', async ({ page }) => {
  await page.goto('/companies');
  await page.getByTestId('filter-chip-size').click();
  await page.getByRole('checkbox', { name: 'Small' }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await page.getByTestId('filter-chip-sector').click();
  await page.getByRole('checkbox', { name: 'Financial and insurance activities' }).check();

  await expect(page.getByText('No companies match these filters.')).toBeVisible();
  await expect(page.getByText(`0 of ${TOTAL} companies`, { exact: true })).toBeVisible();
});

test('an empty directory shows the empty message with no filter controls', async ({ page }) => {
  await mockCompaniesPage(page, { ...fixture, entries: [] });
  await page.goto('/companies');
  await expect(page.getByText(fixture.empty)).toBeVisible();
  await expect(page.locator('[data-testid^="filter-chip-"]')).toHaveCount(0);
});
