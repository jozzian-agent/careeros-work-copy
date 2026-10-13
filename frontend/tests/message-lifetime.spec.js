import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard, mockMove } from './helpers.js';

const fixture = loadBoardFixture();

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('a success message auto-hides after about 4 seconds', async ({ page }) => {
  await page.clock.install();
  await mockMove(page);
  await page.goto('/jobs');

  const moved = fixture.entries.find((entry) => entry.status === 'new');
  const card = page.getByTestId(`job-card-${moved.id}`);
  await card.dragTo(page.getByTestId('board-column-interested'));

  await expect(page.getByText('Moved to Interested')).toBeVisible();
  await page.clock.fastForward(3000);
  await expect(page.getByText('Moved to Interested')).toBeVisible();
  await page.clock.fastForward(1500);
  await expect(page.getByText('Moved to Interested')).toHaveCount(0);
});

test('an error message stays until the user dismisses it, however long it waits', async ({ page }) => {
  await page.clock.install();
  await mockMove(page, { status: 500, body: { error: 'nope' } });
  await page.goto('/jobs');

  const moved = fixture.entries.find((entry) => entry.status === 'new');
  const card = page.getByTestId(`job-card-${moved.id}`);
  await card.dragTo(page.getByTestId('board-column-interested'));

  const message = page.getByText('Status update failed.');
  await expect(message).toBeVisible();
  await page.clock.fastForward(60000);
  await expect(message).toBeVisible();

  await page.getByRole('button', { name: 'Dismiss Banner' }).click();
  await expect(message).toHaveCount(0);
});
