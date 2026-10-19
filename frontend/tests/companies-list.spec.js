// Protects the Companies directory: one equal-sized tile per company with
// a truthful open-jobs chip, the list view beside it with the owner's five
// columns and its two sorts (B4), the shared FilterBar's three filters over
// both views, a grid that stays a grid at 1280px and 390px, and that no
// company surface asks for "Needs your input" any more (B5).
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

// B5 (owner decision 2026-10-19): an absence pin. The toggle, the chip
// and the count are gone from this page, and the payload no longer
// carries the `needs_attention` mark they read -- two of this fixture's
// companies still hold a review flag, which is exactly the record shape
// that used to raise them.
test('no company surface asks for "Needs your input"', async ({ page }) => {
  await page.goto('/companies');
  expect(fixture.entries.some((entry) => (entry.review_flags || []).length > 0)).toBe(true);
  await expect(page.getByText('Needs your input')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Needs/ })).toHaveCount(0);
  await expect(page.getByTestId('filter-chip-needs-attention')).toHaveCount(0);
  // Three facets and no fourth chip: Sector, Size, Open jobs.
  await expect(page.locator('[data-testid^="filter-chip-"]')).toHaveCount(3);
});

test('Clear all drops every filter together', async ({ page }) => {
  await page.goto('/companies');
  await page.getByTestId('filter-chip-size').click();
  await page.getByRole('checkbox', { name: 'Large' }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await page.getByTestId('filter-chip-openJobs').click();
  await page.getByRole('checkbox', { name: 'With open jobs' }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();

  await expect(page.getByText('Active filters')).toBeVisible();
  await page.getByRole('button', { name: 'Clear all', exact: true }).click();

  await expect(page.getByText('Active filters')).toHaveCount(0);
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


// --- B4: the list view beside the tiles ---------------------------------

// Gestalt's Table.Row renders a plain <tr> and forwards no extra props,
// so the row handle sits on the name cell's own span and the row is
// addressed through it.
function row(page, id) {
  return page.locator('tbody tr', { has: page.getByTestId(`company-row-${id}`) });
}

async function showList(page) {
  await page.getByTestId('view-chip-list').click();
}

test('the Tiles and List pair carries the selected style and nothing else does', async ({ page }) => {
  await page.goto('/companies');
  const tiles = page.getByTestId('view-chip-tiles');
  const list = page.getByTestId('view-chip-list');
  await expect(tiles).toHaveAttribute('aria-pressed', 'true');
  await expect(list).toHaveAttribute('aria-pressed', 'false');
  // One pair, one group, exactly one of them true.
  await expect(page.getByRole('group', { name: 'View' })).toBeVisible();

  await showList(page);
  await expect(list).toHaveAttribute('aria-pressed', 'true');
  await expect(tiles).toHaveAttribute('aria-pressed', 'false');
  // Nothing on this page is a filled primary button: Companies has no
  // main action (A1).
  await expect(page.getByRole('button', { name: 'Add a company' })).toHaveCount(0);
});

test('a list row carries the five approved columns, the name as a link and the tile chip', async ({ page }) => {
  await page.goto('/companies');
  await showList(page);

  const headers = await page.getByRole('columnheader').allInnerTexts();
  expect(headers.map((text) => text.trim())).toEqual(['Name', 'Sector', 'Size', 'Location', 'Open jobs']);

  await expect(row(page, 'CO-001').getByRole('link', { name: 'Harbor Labs' })).toHaveAttribute(
    'href',
    '/companies/CO-001',
  );
  await expect(row(page, 'CO-001')).toContainText('Information and communication');
  await expect(row(page, 'CO-001')).toContainText('Small');
  await expect(row(page, 'CO-001')).toContainText('Zurich, CH');
  // The same chip the tile shows, in the same words.
  await expect(row(page, 'CO-001').getByText('3 open jobs', { exact: true })).toBeVisible();
  await expect(row(page, 'CO-002').getByText('1 open job', { exact: true })).toBeVisible();
  await expect(row(page, 'CO-003').getByText('No open jobs', { exact: true })).toBeVisible();
  // A record with nothing stored says so rather than leaving a blank cell.
  await expect(row(page, 'CO-003')).toContainText('Location unknown');
  await expect(row(page, 'CO-005')).toContainText('Sector unknown');
  await expect(row(page, 'CO-005')).toContainText('Size unknown');
  // The list is the full name, not the tile's 30-character cut.
  await expect(row(page, 'CO-004').getByRole('link', { name: LONG_NAME })).toBeVisible();
});

test('only Name and Open jobs sort, and each sorts both ways', async ({ page }) => {
  await page.goto('/companies');
  await showList(page);

  const sortable = page.getByRole('columnheader').filter({ has: page.getByRole('button') });
  await expect(sortable).toHaveCount(2);
  // Scoped to the table: "Open jobs" is also the name of a filter chip.
  const sortBy = (label) => page.getByRole('table').getByRole('button', { name: label });

  async function names() {
    return (await page.locator('tbody tr td:first-child a').allInnerTexts()).map((t) => t.trim());
  }
  // The Open jobs cell of every row, as the number its chip states.
  async function counts() {
    const cells = await page.locator('tbody tr td:last-child').allInnerTexts();
    return cells.map((text) => Number(text.replace('No open jobs', '0').replace(/[^0-9]/g, '') || 0));
  }

  await sortBy('Name').click();
  const ascending = await names();
  expect(ascending).toEqual([...ascending].sort((a, b) => a.localeCompare(b)));
  await expect(page.getByRole('columnheader').first()).toHaveAttribute('aria-sort', 'ascending');

  await sortBy('Name').click();
  expect(await names()).toEqual([...ascending].reverse());
  await expect(page.getByRole('columnheader').first()).toHaveAttribute('aria-sort', 'descending');

  await sortBy('Open jobs').click();
  const byCount = await counts();
  expect(byCount).toEqual([...byCount].sort((a, b) => a - b));
  await sortBy('Open jobs').click();
  expect(await counts()).toEqual([...byCount].reverse());
});

test('the filters apply to both views, and the view choice survives a reload', async ({ page }) => {
  await page.goto('/companies');
  await page.getByTestId('filter-chip-size').click();
  await page.getByRole('checkbox', { name: 'Large' }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();

  // Tiles first: two companies are Large.
  await expect(card(page, 'CO-002')).toBeVisible();
  await expect(card(page, 'CO-001')).toHaveCount(0);

  await showList(page);
  await expect(row(page, 'CO-002')).toBeVisible();
  await expect(row(page, 'CO-004')).toBeVisible();
  await expect(row(page, 'CO-001')).toHaveCount(0);
  await expect(page.getByText(`2 of ${TOTAL} companies`, { exact: true })).toBeVisible();

  await page.reload();
  expect(new URL(page.url()).search).toBe('');
  await expect(page.getByTestId('view-chip-list')).toHaveAttribute('aria-pressed', 'true');
  await expect(row(page, 'CO-002')).toBeVisible();
  await expect(row(page, 'CO-001')).toHaveCount(0);
});

test('a filter that matches nothing says so in the list view too', async ({ page }) => {
  await page.goto('/companies');
  await showList(page);
  await page.getByTestId('filter-chip-size').click();
  await page.getByRole('checkbox', { name: 'Small' }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await page.getByTestId('filter-chip-sector').click();
  await page.getByRole('checkbox', { name: 'Financial and insurance activities' }).check();

  await expect(page.getByText('No companies match these filters.')).toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(0);
});
