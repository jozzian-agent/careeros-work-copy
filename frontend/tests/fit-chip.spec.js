import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard } from './helpers.js';

const fixture = loadBoardFixture();

const CHIP_LABEL = {
  no_fit: 'No fit',
  lucky: 'Lucky',
  excellent: 'Excellent fit',
};

test('every rated fit level renders its own label on the board', async ({ page }) => {
  await mockBoard(page, fixture);
  await page.goto('/');

  const levelsPresent = new Set(fixture.entries.map((entry) => entry.fit).filter(Boolean));
  expect(levelsPresent).toEqual(new Set(['no_fit', 'lucky', 'excellent']));

  for (const entry of fixture.entries) {
    const card = page.getByTestId(`job-card-${entry.id}`);
    await expect(card.getByText(CHIP_LABEL[entry.fit], { exact: true })).toBeVisible();
    // The fit chip and the fit-level "Needs your input" are never shown
    // together. (A company-match review badge uses the same words for an
    // unrelated reason; JOB-002 below is the one fixture entry where both
    // concepts coexist, so it is excluded from this specific check.)
    if (entry.company_link_state !== 'needs_review') {
      await expect(card.getByText('Needs your input', { exact: true })).toHaveCount(0);
    }
  }
});

test('an unrated job defaults to the "Needs your input" chip, never a blank fit chip', async ({ page }) => {
  const unrated = { ...fixture, entries: [{ ...fixture.entries[0], fit: undefined }] };
  await mockBoard(page, unrated);
  await page.goto('/');

  const card = page.getByTestId(`job-card-${unrated.entries[0].id}`);
  await expect(card.getByText('Needs your input', { exact: true })).toBeVisible();
  for (const label of Object.values(CHIP_LABEL)) {
    await expect(card.getByText(label, { exact: true })).toHaveCount(0);
  }
});
