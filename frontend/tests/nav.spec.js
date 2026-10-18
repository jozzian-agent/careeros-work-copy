import { expect, test } from '@playwright/test';
import { loadBoardFixture, loadFixture, mockBoard, mockSearchPage } from './helpers.js';

const boardFixture = loadBoardFixture();
const searchFixture = loadFixture('search-criteria');
// JOZ-283: the Search tab's own URL is "/", the one slug whose href does
// not match its own name. M2 (CAREER-39, decision D10) renamed the Jobs
// tab to My Jobs; its slug and href stay /jobs.
const NAV_PAGES = [
  ['search', 'Search', '/'],
  ['experiences', 'Experiences', '/experiences'],
  ['jobs', 'My Jobs', '/jobs'],
  ['companies', 'Companies', '/companies'],
  ['notes', 'Notes', '/notes'],
  ['taxonomy', 'Taxonomy', '/taxonomy'],
];

test.beforeEach(async ({ page }) => {
  await mockBoard(page, boardFixture);
  await mockSearchPage(page, searchFixture);
});

test('wordmark links to /', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'CareerOS', exact: true })).toHaveAttribute('href', '/');
});

test('nav shows every link in order with correct hrefs', async ({ page }) => {
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Main' });
  const links = nav.getByRole('link');
  await expect(links).toHaveCount(NAV_PAGES.length);
  for (const [index, [, label, href]] of NAV_PAGES.entries()) {
    const link = links.nth(index);
    await expect(link).toHaveText(label);
    await expect(link).toHaveAttribute('href', href);
  }
});

test('Search is marked as the current page on /, others are not', async ({ page }) => {
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(nav.getByRole('link', { name: 'Search', exact: true })).toHaveAttribute('aria-current', 'page');
  for (const label of ['My Jobs', 'Experiences', 'Companies', 'Notes', 'Taxonomy']) {
    await expect(nav.getByRole('link', { name: label, exact: true })).not.toHaveAttribute('aria-current');
  }
});

test('My Jobs is marked as the current page on /jobs', async ({ page }) => {
  await page.goto('/jobs');
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(nav.getByRole('link', { name: 'My Jobs', exact: true })).toHaveAttribute('aria-current', 'page');
  for (const label of ['Search', 'Experiences', 'Companies', 'Notes', 'Taxonomy']) {
    await expect(nav.getByRole('link', { name: label, exact: true })).not.toHaveAttribute('aria-current');
  }
});
