import { expect, test } from '@playwright/test';
import {
  loadFixture,
  mockExperiencePage,
  mockExperienceTagsRegistry,
  mockUpdate,
  mockDelete,
} from './helpers.js';

const fixture = loadFixture('experience-detail');
const tagsRegistry = loadFixture('experience-tags-registry');

test.beforeEach(async ({ page }) => {
  await mockExperiencePage(page, fixture);
  await mockExperienceTagsRegistry(page, tagsRegistry);
});

test('header renders type label, title, subtitle and actions', async ({ page }) => {
  await page.goto('/experiences/EXP-001');
  await expect(page.getByText('EXPERIENCE', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: fixture.exp.title })).toBeVisible();
  await expect(page.getByRole('link', { name: fixture.label }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit position' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete' })).toBeVisible();
});

test('back link navigates to the experiences list', async ({ page }) => {
  await page.goto('/experiences/EXP-001');
  await page.getByRole('link', { name: 'Back to Experiences' }).click();
  await expect(page).toHaveURL('/experiences');
});

test('sections render in order: summary, content, details', async ({ page }) => {
  await page.goto('/experiences/EXP-001');
  await expect(page.getByRole('heading', { name: fixture.exp.title })).toBeVisible();
  const headings = await page.getByRole('heading').allTextContents();
  const order = ['Summary', 'Highlights', 'Content', 'Details'];
  const positions = order.map((label) => headings.indexOf(label));
  expect(positions.every((index) => index !== -1)).toBe(true);
  expect(positions).toEqual([...positions].sort((a, b) => a - b));
});

test('Edit position popup opens with the full form and saves', async ({ page }) => {
  const requests = await mockUpdate(page, '**/api/experiences/EXP-001', { body: fixture.exp });
  await page.goto('/experiences/EXP-001');
  await page.getByRole('button', { name: 'Edit position' }).click();
  const modal = page.getByRole('dialog', { name: 'Edit position' });
  await expect(modal).toBeVisible();
  await expect(modal.getByRole('textbox', { name: 'Title' })).toHaveValue(fixture.exp.title);
  await expect(modal.getByRole('textbox', { name: 'Salary' })).toHaveValue('Managed in the vault file only');
  await modal.getByRole('textbox', { name: 'Summary (2–4 sentences)' }).fill('Updated summary.');
  await modal.getByRole('button', { name: 'Save position' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].summary).toBe('Updated summary.');
});

test('Delete confirmation deletes and returns to the experiences list', async ({ page }) => {
  await mockDelete(page, '**/api/experiences/EXP-001');
  await page.goto('/experiences/EXP-001');
  await page.getByRole('button', { name: 'Delete' }).click();
  const alert = page.getByRole('alertdialog', { name: 'Delete this position?' });
  await alert.getByRole('button', { name: 'Delete position' }).click();
  await expect(page).toHaveURL('/experiences');
});
