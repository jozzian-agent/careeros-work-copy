import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard } from './helpers.js';

const fixture = loadBoardFixture();
const openStatuses = fixture.statuses.filter((status) => !fixture.ended_statuses.includes(status));

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('the board holds one fixed 320px column per open status and never wraps', async ({ page }) => {
  await page.goto('/jobs');

  for (const status of openStatuses) {
    const box = await page.getByTestId(`column-header-${status}`).boundingBox();
    expect(box.width).toBeGreaterThan(300);
    expect(box.width).toBeLessThan(321);
  }

  const row = page.getByTestId('board-row');
  const wrap = await row.evaluate((el) => getComputedStyle(el.querySelector(':scope > div')).flexWrap);
  expect(wrap).toBe('nowrap');
});

test('the row scrolls horizontally instead of wrapping the columns', async ({ page }) => {
  await page.goto('/jobs');

  const row = page.getByTestId('board-row');
  const overflowX = await row.evaluate((el) => getComputedStyle(el).overflowX);
  expect(['auto', 'scroll']).toContain(overflowX);

  const { scrollWidth, clientWidth } = await row.evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }));
  // 5 columns at 320px plus gaps is wider than what the row is left
  // once the Ended lane has taken its own width beside it, which is what
  // makes the row scroll at all.
  expect(scrollWidth).toBeGreaterThan(clientWidth);
});

test('each column header sits outside its own scrolling body', async ({ page }) => {
  await page.goto('/jobs');

  const status = openStatuses[0];
  const body = page.getByTestId(`column-body-${status}`);

  const bodyStyle = await body.evaluate((el) => getComputedStyle(el).overflowY);
  expect(['auto', 'scroll']).toContain(bodyStyle);
  expect(await body.evaluate((el) => getComputedStyle(el).maxHeight)).toBe('720px');

  // The header is a sibling of the body, never a descendant, so scrolling
  // the body can never carry the header along with it.
  const headerIsOutside = await page.evaluate(
    ([headerTestId, bodyTestId]) => {
      const header = document.querySelector(`[data-testid="${headerTestId}"]`);
      const body = document.querySelector(`[data-testid="${bodyTestId}"]`);
      return !body.contains(header) && !header.contains(body);
    },
    [`column-header-${status}`, `column-body-${status}`],
  );
  expect(headerIsOutside).toBe(true);
});

test('an empty column invites a drop and still shows its status heading', async ({ page }) => {
  await page.goto('/jobs');

  const emptyStatus = openStatuses.find((status) => !fixture.entries.some((entry) => entry.status === status));
  const column = page.getByTestId(`board-column-${emptyStatus}`);
  await expect(column.getByText('No jobs here yet. Drag a job here.')).toBeVisible();
  await expect(column.getByRole('heading', { name: fixture.status_labels[emptyStatus], exact: true })).toBeVisible();
});
