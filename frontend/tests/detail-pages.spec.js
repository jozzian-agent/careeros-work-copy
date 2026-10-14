// Protects what the Job and Company detail pages must have in common:
// Delete reading as the secondary action it is, a back link that is blue
// on both, a 390px layout that does not scroll sideways, and no trace of
// the retired company classification page.
import { expect, test } from '@playwright/test';
import { loadFixture, mockCompanyPage, mockJobPage, mockJobTaxonomy } from './helpers.js';

const job = loadFixture('job-detail');
const taxonomy = loadFixture('job-taxonomy');
const company = loadFixture('company-detail');

const BRAND_PRIMARY = 'rgb(0, 95, 203)'; // #005fcb, src/design/tokens.css

const PAGES = [
  { name: 'job', url: '/jobs/JOB-001', editLabel: 'Edit job', title: job.job.title },
  { name: 'company', url: '/companies/CO-001', editLabel: 'Edit company', title: company.company.name },
];

async function openPage(page, which) {
  await mockJobPage(page, job);
  await mockJobTaxonomy(page, taxonomy);
  await mockCompanyPage(page, company);
  await page.goto(which.url);
  await expect(page.getByRole('heading', { name: which.title })).toBeVisible();
}

function buttonBackground(locator) {
  // Gestalt classic puts the colour class on the button's inner div.
  return locator.evaluate((el) => getComputedStyle(el.firstElementChild).backgroundColor);
}

for (const which of PAGES) {
  // Delete used to be Button color="red", which this theme binds to the
  // brand fill, so the most destructive action on the page rendered as
  // its primary one.
  test(`${which.name} page: Delete is the same gray secondary as Edit, never the brand fill`, async ({ page }) => {
    await openPage(page, which);
    const deleteBackground = await buttonBackground(page.getByRole('button', { name: 'Delete' }));
    const editBackground = await buttonBackground(page.getByRole('button', { name: which.editLabel }));
    expect(deleteBackground).toBe(editBackground);
    expect(deleteBackground).not.toBe(BRAND_PRIMARY);
  });

  // Bug 5: the arrow is an Icon color="brandPrimary", which reads
  // Gestalt's own brand icon token and rendered Pinterest red beside its
  // blue link text until the theme rebound it.
  test(`${which.name} page: the back-link arrow is brand blue`, async ({ page }) => {
    await openPage(page, which);
    const fill = await page
      .getByRole('link', { name: /^Back to/ })
      .locator('svg')
      .evaluate((el) => getComputedStyle(el).fill);
    expect(fill).toBe(BRAND_PRIMARY);
  });

  test(`${which.name} page: at 390px the header actions wrap and nothing scrolls sideways`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    await openPage(page, which);
    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);

    // Wrapped means the actions sit below the title, not beside it.
    const heading = await page.getByRole('heading', { name: which.title }).boundingBox();
    const action = await page.getByRole('button', { name: which.editLabel }).boundingBox();
    expect(action.y).toBeGreaterThanOrEqual(heading.y + heading.height);
  });
}

test('the retired company classification route renders no page', async ({ page }) => {
  // The route and its JSON endpoint are gone server-side
  // (tests/test_taxonomy_pages.py::test_company_taxonomy_page_is_retired
  // pins both 404s). The SPA must not answer for it either.
  await mockCompanyPage(page, company);
  await page.goto('/companies/CO-001/taxonomy');
  await expect(page.getByText('COMPANY', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: company.company.name })).toHaveCount(0);
});
