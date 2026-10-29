// Protects the shared page header (brief 2026-10-18, section 3): no list
// page draws the white title band Gestalt's PageHeader drew, the title is
// the page's H1 on the page ground, and the title, the toolbar and the
// content share one left edge.
import { expect, test } from '@playwright/test';
import {
  loadBoardFixture,
  loadFixture,
  mockBoard,
  mockCompaniesPage,
  mockExperiencesPage,
  mockNotesPage,
  mockSearchPage,
  mockTaxonomy,
} from './helpers.js';

const PAGE_GROUND = 'rgb(246, 253, 245)'; // --color-background-page, #f6fdf5
const CARD = 'rgb(255, 255, 255)'; // --color-background-card, the band's old fill

const PAGES = [
  { route: '/jobs', title: 'My Jobs' },
  { route: '/companies', title: 'Companies' },
  { route: '/experiences', title: 'Experiences' },
  { route: '/notes', title: 'Notes' },
  { route: '/taxonomy', title: 'Taxonomy' },
  { route: '/', title: 'Search' },
];

test.beforeEach(async ({ page }) => {
  await mockBoard(page, loadBoardFixture());
  await mockSearchPage(page, loadFixture('search-criteria'));
  await mockCompaniesPage(page, loadFixture('companies-list'));
  await mockExperiencesPage(page, loadFixture('experiences-list'));
  await mockNotesPage(page, loadFixture('notes'));
  await mockTaxonomy(page, loadFixture('taxonomy'));
});

for (const { route, title } of PAGES) {
  test(`${route} has no white title band and one left edge`, async ({ page }) => {
    await page.goto(route);
    const heading = page.getByRole('heading', { name: title, exact: true, level: 1 });
    await expect(heading).toBeVisible();

    // The title sits on the page ground: nothing between it and <body>
    // paints a card-coloured band.
    const bandGrounds = await heading.evaluate((el) => {
      const grounds = [];
      let node = el;
      while (node && node !== document.body) {
        grounds.push(getComputedStyle(node).backgroundColor);
        node = node.parentElement;
      }
      return grounds;
    });
    expect(bandGrounds).not.toContain(CARD);
    const bodyGround = await page.evaluate(
      () => getComputedStyle(document.body).backgroundColor,
    );
    expect(bodyGround).toBe(PAGE_GROUND);

    // 28px bold, per the artboard, and the page's one top-level heading.
    const type = await heading.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { tag: el.tagName, fontSize: cs.fontSize, lineHeight: cs.lineHeight, weight: cs.fontWeight };
    });
    expect(type).toEqual({ tag: 'H1', fontSize: '28px', lineHeight: '31px', weight: '700' });

    // The title, the header stack's own rows and the main content all
    // start at the same x: one left edge, which is the whole point of
    // retiring the band.
    const edges = await page.evaluate(() => {
      const stack = document.querySelector('[data-testid="page-header"]');
      const main = document.querySelector('main');
      const inset = (el) => Math.round(el.getBoundingClientRect().left)
        + Number.parseFloat(getComputedStyle(el).paddingLeft);
      return {
        title: Math.round(document.querySelector('h1').getBoundingClientRect().left),
        stack: inset(stack),
        stackPadding: getComputedStyle(stack).paddingLeft,
        main: inset(main),
        mainPadding: getComputedStyle(main).paddingLeft,
      };
    });
    expect(edges.stackPadding).toBe('32px');
    expect(edges.mainPadding).toBe('32px');
    expect(edges.title).toBe(edges.stack);
    expect(edges.main).toBe(edges.title);
  });
}

// Jobs is the page the brief draws in full, top to bottom.
test('the Jobs header stack is the title, the action row, the filter bar, then the banner', async ({
  page,
}) => {
  await page.goto('/jobs');
  await expect(page.getByTestId('closed-postings-banner')).toBeVisible();
  const order = await page.evaluate(() => {
    const stack = document.querySelector('[data-testid="page-header"]');
    return [...stack.children].map((row) => {
      if (row.tagName === 'H1') return 'title';
      if (row.querySelector('[role="group"][aria-label="View"]')) return 'action row';
      if (row.querySelector('[data-testid^="filter-chip-"]')) return 'filter bar';
      if (row.dataset.testid === 'closed-postings-banner') return 'banner';
      return row.tagName;
    });
  });
  expect(order).toEqual(['title', 'action row', 'filter bar', 'banner']);
});

// A page with no main action shows the title row, its view pair and its
// filters -- and no primary button. Companies gained the Tiles and List
// pair in B4, placed where Board and List sit on Jobs, so its header
// stack is the same three rows minus the action.
test('Companies shows its view pair and filter bar under the title, with no main action', async ({ page }) => {
  await page.goto('/companies');
  const stack = page.getByTestId('page-header');
  await expect(stack.getByTestId('filter-chip-sector')).toBeVisible();
  await expect(stack.getByRole('group', { name: 'View', exact: true })).toBeVisible();
  const order = await page.evaluate(() => {
    const header = document.querySelector('[data-testid="page-header"]');
    return [...header.children].map((row) => {
      if (row.tagName === 'H1') return 'title';
      if (row.querySelector('[role="group"][aria-label="View"]')) return 'view row';
      if (row.querySelector('[data-testid^="filter-chip-"]')) return 'filter bar';
      return row.tagName;
    });
  });
  expect(order).toEqual(['title', 'view row', 'filter bar']);
});
