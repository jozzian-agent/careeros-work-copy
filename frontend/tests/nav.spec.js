import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard } from './helpers.js';

const fixture = loadBoardFixture();
const NAV_PAGES = [
  ['search', 'Search'],
  ['experiences', 'Experiences'],
  ['jobs', 'Jobs'],
  ['companies', 'Companies'],
];

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('wordmark links to /search', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'CareerOS', exact: true })).toHaveAttribute('href', '/search');
});

test('nav shows all four links in order with correct hrefs', async ({ page }) => {
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Main' });
  const links = nav.getByRole('link');
  await expect(links).toHaveCount(NAV_PAGES.length);
  for (const [index, [slug, label]] of NAV_PAGES.entries()) {
    const link = links.nth(index);
    await expect(link).toHaveText(label);
    await expect(link).toHaveAttribute('href', `/${slug}`);
  }
});

test('Jobs is marked as the current page, others are not', async ({ page }) => {
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(nav.getByRole('link', { name: 'Jobs', exact: true })).toHaveAttribute('aria-current', 'page');
  for (const label of ['Search', 'Experiences', 'Companies']) {
    await expect(nav.getByRole('link', { name: label, exact: true })).not.toHaveAttribute('aria-current');
  }
});
