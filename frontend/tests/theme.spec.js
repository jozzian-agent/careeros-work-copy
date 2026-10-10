import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard } from './helpers.js';

const fixture = loadBoardFixture();

// Matches ACCENT_INDIGO in src/theme.js (#5e6ad2), the same --accent-indigo
// token careeros/web/theme.py uses for the Flask dashboard's primary accent.
const ACCENT_INDIGO_RGB = 'rgb(94, 106, 210)';

test('primary button accent matches the themed indigo token', async ({ page }) => {
  await mockBoard(page, fixture);
  await page.goto('/');
  const boardButton = page.getByRole('button', { name: 'Board', exact: true });
  await expect(boardButton).toHaveAttribute('aria-pressed', 'true');
  const background = await boardButton.evaluate((el) => getComputedStyle(el.firstElementChild).backgroundColor);
  expect(background).toBe(ACCENT_INDIGO_RGB);
});
