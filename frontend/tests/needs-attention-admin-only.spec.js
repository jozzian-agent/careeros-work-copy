// Needs-attention is the admin's alone (owner ruling 2026-11-01: "needs
// your input should not be displayed to non-admins at all. Not on cards,
// not on the filter and so on").
//
// The server is where that is answered: for a non-admin it sends
// needs_attention false on every entry and is_admin false in the payload
// (careeros/web/pages/jobs.py board_context, pinned in
// tests/test_job_page_context.py and tests/test_record_privacy.py). So
// the card chip needs no front-end rule at all and this spec asserts its
// absence rather than adding logic for it; what the front end does add is
// leaving the filter chip out, because a chip with a count of zero would
// still render.
import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard } from './helpers.js';

const fixture = loadBoardFixture();

// The payload the server really sends a non-admin: the flag off on every
// entry, and is_admin saying who this is.
const asTester = {
  ...fixture,
  is_admin: false,
  entries: fixture.entries.map((entry) => ({ ...entry, needs_attention: false })),
};

const asAdmin = { ...fixture, is_admin: true };

const flagged = fixture.entries.filter((entry) => entry.needs_attention);

test('the fixture has a flagged entry, or this spec proves nothing', () => {
  expect(flagged.length).toBeGreaterThan(0);
});

test('an admin keeps the chip and the filter', async ({ page }) => {
  await mockBoard(page, asAdmin);
  await page.goto('/jobs');
  await expect(page.getByTestId('filter-chip-needs-attention')).toBeVisible();
  await expect(page.getByTestId(`job-card-${flagged[0].id}`).getByTestId('needs-input-chip')).toBeVisible();
});

test('a non-admin gets no Needs attention filter chip at all', async ({ page }) => {
  await mockBoard(page, asTester);
  await page.goto('/jobs');
  // The rest of the filter bar is untouched, so this is the one chip
  // missing rather than a bar that failed to render.
  await expect(page.getByTestId('filter-chip-hide-closed')).toBeVisible();
  await expect(page.getByTestId('filter-chip-needs-attention')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Needs attention', exact: true })).toHaveCount(0);
});

test('a non-admin card carries no Needs your input chip', async ({ page }) => {
  await mockBoard(page, asTester);
  await page.goto('/jobs');
  for (const entry of flagged) {
    const card = page.getByTestId(`job-card-${entry.id}`);
    await expect(card).toBeVisible();
    await expect(card.getByTestId('needs-input-chip')).toHaveCount(0);
  }
});

test('a remembered Needs attention toggle does not empty a non-admin board', async ({ page }) => {
  // The toggle is kept in localStorage, so somebody who had it on before
  // the ruling would otherwise hold a filter they can no longer see,
  // against a flag the server now answers false: an empty board with
  // nothing on screen explaining it.
  await mockBoard(page, asTester);
  await page.addInitScript(() => {
    window.localStorage.setItem('careerNeedsAttention', 'true');
  });
  await page.goto('/jobs');
  await expect(page.getByText(flagged[0].title, { exact: true })).toBeVisible();
  await expect(page.getByTestId('filter-chip-needs-attention')).toHaveCount(0);
});
