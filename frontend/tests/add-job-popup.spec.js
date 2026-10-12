import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard } from './helpers.js';

const fixture = loadBoardFixture();

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

// JOZ-278 lands the plus-button popup as a shell only: a title and a close
// affordance. The field, Cancel and Add job button are a later batch; the
// existing posting-URL field below the board stays the working intake path
// until then, so this spec only covers the shell opening/closing, not intake.
test('the plus button opens the add-job popup shell with a title and a close action', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('dialog', { name: 'Add a job' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Add a job', exact: true }).click();

  const dialog = page.getByRole('dialog', { name: 'Add a job' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: 'Add a job' })).toBeVisible();
  // Shell only: no posting-link field or submit action inside the dialog.
  await expect(dialog.getByRole('textbox')).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Add job' })).toHaveCount(0);

  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Add a job' })).toHaveCount(0);
});

test('Escape also dismisses the shell', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Add a job', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Add a job' })).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Add a job' })).toHaveCount(0);
});
