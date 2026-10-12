import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard } from './helpers.js';

const fixture = loadBoardFixture();

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('the board holds one fixed 320px column per status and never wraps', async ({ page }) => {
  await page.goto('/');

  for (const status of fixture.statuses) {
    const box = await page.getByTestId(`column-header-${status}`).boundingBox();
    expect(box.width).toBeGreaterThan(300);
    expect(box.width).toBeLessThan(321);
  }

  const row = page.getByTestId('board-row');
  const wrap = await row.evaluate((el) => getComputedStyle(el.querySelector(':scope > div')).flexWrap);
  expect(wrap).toBe('nowrap');
});

test('the row scrolls horizontally instead of wrapping the columns', async ({ page }) => {
  await page.goto('/');

  const row = page.getByTestId('board-row');
  const overflowX = await row.evaluate((el) => getComputedStyle(el).overflowX);
  expect(['auto', 'scroll']).toContain(overflowX);

  const { scrollWidth, clientWidth } = await row.evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }));
  // 8 columns at 320px plus 16px gaps is wider than any reasonable viewport.
  expect(scrollWidth).toBeGreaterThan(clientWidth);
});

test('each column header sits outside its own scrolling body', async ({ page }) => {
  await page.goto('/');

  const status = fixture.statuses[0];
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

test('an empty column renders "No jobs here yet" and still shows its status heading', async ({ page }) => {
  await page.goto('/');

  const emptyStatus = fixture.statuses.find((status) => !fixture.entries.some((entry) => entry.status === status));
  const column = page.getByTestId(`board-column-${emptyStatus}`);
  await expect(column.getByText('No jobs here yet')).toBeVisible();
});
