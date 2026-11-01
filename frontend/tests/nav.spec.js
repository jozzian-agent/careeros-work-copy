import { expect, test } from '@playwright/test';
import { loadBoardFixture, loadFixture, mockBoard, mockSearchPage } from './helpers.js';

const boardFixture = loadBoardFixture();
const searchFixture = loadFixture('search-criteria');
// JOZ-283: the Search tab's own URL is "/", the one slug whose href does
// not match its own name. M2 (CAREER-39, decision D10) renamed the Jobs
// tab to My Jobs; its slug and href stay /jobs.
// B2 (CAREER-89): "All jobs" sits next to My Jobs, at its own URL --
// /jobs/<id> is the job detail page, so it could not be a segment under
// /jobs.
const NAV_PAGES = [
  ['search', 'Search', '/'],
  ['experiences', 'Experiences', '/experiences'],
  ['jobs', 'My Jobs', '/jobs'],
  ['all-jobs', 'All jobs', '/all-jobs'],
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

// Company requests is the admin's tab and the one nav entry that is not
// everybody's: answering a request writes a shared company, which is the
// admin's alone (M2, decision D3). The nav asks /api/me who this is; the
// tests above run without that route mocked, which is a failed read and
// therefore the not-admin answer -- so they already pin its absence.
test('the Company requests tab is the admin only', async ({ page }) => {
  await page.route('**/api/me', (route) => route.fulfill({ json: { id: 'USER-001', role: 'admin' } }));
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Main' });
  const tab = nav.getByRole('link', { name: 'Company requests', exact: true });
  await expect(tab).toBeVisible();
  await expect(tab).toHaveAttribute('href', '/company-requests');
  await expect(nav.getByRole('link')).toHaveCount(NAV_PAGES.length + 1);
});

test('a tester gets the nav without it', async ({ page }) => {
  await page.route('**/api/me', (route) => route.fulfill({ json: { id: 'USER-002', role: 'tester' } }));
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(nav.getByRole('link')).toHaveCount(NAV_PAGES.length);
  await expect(nav.getByRole('link', { name: 'Company requests', exact: true })).toHaveCount(0);
});

test('Search is marked as the current page on /, others are not', async ({ page }) => {
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(nav.getByRole('link', { name: 'Search', exact: true })).toHaveAttribute('aria-current', 'page');
  for (const label of ['My Jobs', 'All jobs', 'Experiences', 'Companies', 'Notes', 'Taxonomy']) {
    await expect(nav.getByRole('link', { name: label, exact: true })).not.toHaveAttribute('aria-current');
  }
});

test('My Jobs is marked as the current page on /jobs', async ({ page }) => {
  await page.goto('/jobs');
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(nav.getByRole('link', { name: 'My Jobs', exact: true })).toHaveAttribute('aria-current', 'page');
  for (const label of ['Search', 'All jobs', 'Experiences', 'Companies', 'Notes', 'Taxonomy']) {
    await expect(nav.getByRole('link', { name: label, exact: true })).not.toHaveAttribute('aria-current');
  }
});
