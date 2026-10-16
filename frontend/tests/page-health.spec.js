// Every page loads without an uncaught script error and without asking
// any origin but this one for anything.
//
// CAREER-32: these two guards are what `scripts/verify.py` held that no
// spec did. That script asserted them once, over a Jinja app, from a
// browser run nobody could execute any more (it clicked an Enrich button
// removed in M1 and counted eight kanban columns the D7 board replaced
// with five and a lane). The guards themselves outlive it: a page that
// throws is broken whatever it renders, and a page that reaches out to a
// CDN breaks the offline-by-default rule the whole front end is built on
// (frontend/README.md). Checked per route rather than once, since each
// page loads its own chunks.
import { expect, test } from '@playwright/test';
import {
  loadBoardFixture,
  loadFixture,
  mockBoard,
  mockCompaniesPage,
  mockCompanyPage,
  mockExperiencePage,
  mockExperiencesPage,
  mockJobPage,
  mockNotesPage,
  mockSearchPage,
  mockTaxonomy,
} from './helpers.js';

const ROUTES = ['/', '/jobs', '/jobs/JOB-001', '/companies', '/companies/CO-001',
                '/experiences', '/experiences/EXP-001', '/notes', '/taxonomy'];

test.beforeEach(async ({ page }) => {
  await mockBoard(page, loadBoardFixture());
  await mockSearchPage(page, loadFixture('search-criteria'));
  await mockJobPage(page, loadFixture('job-detail'));
  await mockCompaniesPage(page, loadFixture('companies-list'));
  await mockCompanyPage(page, loadFixture('company-detail'));
  await mockExperiencesPage(page, loadFixture('experiences-list'));
  await mockExperiencePage(page, loadFixture('experience-detail'));
  await mockNotesPage(page, loadFixture('notes'));
  await mockTaxonomy(page, loadFixture('taxonomy'));
});

for (const route of ROUTES) {
  test(`${route} loads with no uncaught error and no external request`, async ({ page, baseURL }) => {
    const errors = [];
    const external = [];
    const origin = new URL(baseURL).origin;
    page.on('pageerror', (error) => errors.push(`${route}: ${error.message}`));
    page.on('request', (request) => {
      if (!request.url().startsWith(origin) && !request.url().startsWith('data:')) {
        external.push(`${route}: ${request.url()}`);
      }
    });

    await page.goto(route);
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();

    expect(errors).toEqual([]);
    expect(external).toEqual([]);
  });
}
