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

// Jobs is the page the brief draws in full, top to bottom. CAREER-118
// PR 3 moved the Board/List pair out of the action row and into the
// filter bar's own row, so the stack is the title, the row that carries
// the one primary action, the ONE toolbar row (chips, count, pair), then
// the banner -- and "action row" is now the row with the button in it,
// not the row with the View group.
test('the Jobs header stack is the title, the action row, one toolbar row, then the banner', async ({
  page,
}) => {
  await page.goto('/jobs');
  await expect(page.getByTestId('closed-postings-banner')).toBeVisible();
  const order = await page.evaluate(() => {
    const stack = document.querySelector('[data-testid="page-header"]');
    return [...stack.children].map((row) => {
      if (row.tagName === 'H1') return 'title';
      const hasView = Boolean(row.querySelector('[role="group"][aria-label="View"]'));
      const hasChips = Boolean(row.querySelector('[data-testid^="filter-chip-"]'));
      if (hasView && hasChips) return 'toolbar';
      if (hasView) return 'view row';
      if (hasChips) return 'filter bar';
      if (row.dataset.testid === 'closed-postings-banner') return 'banner';
      if (row.querySelector('button')) return 'action row';
      return row.tagName;
    });
  });
  // One toolbar, not a "view row" and a "filter bar": the two names the
  // old stack had are exactly what must not come back.
  expect(order).toEqual(['title', 'action row', 'toolbar', 'banner']);

  // The action row holds the primary action and nothing else.
  const actionRow = page.getByTestId('page-header').locator('> div').first();
  await expect(actionRow.getByRole('button')).toHaveCount(1);
  await expect(actionRow.getByRole('button', { name: 'Add a job', exact: true })).toBeVisible();
});

// A page with no main action shows the title row and one toolbar row --
// and no primary button. Companies gained the Tiles and List pair in B4;
// CAREER-118 PR 2 moved it from a row of its own into the filter bar's
// row, per the CollectionPage layout, so the stack is now two rows: the
// title, then the one toolbar carrying the chips, the count and the pair.
test('Companies shows one toolbar row with its filters and view pair under the title, with no main action', async ({ page }) => {
  await page.goto('/companies');
  const stack = page.getByTestId('page-header');
  await expect(stack.getByTestId('filter-chip-sector')).toBeVisible();
  await expect(stack.getByRole('group', { name: 'View', exact: true })).toBeVisible();
  const order = await page.evaluate(() => {
    const header = document.querySelector('[data-testid="page-header"]');
    return [...header.children].map((row) => {
      if (row.tagName === 'H1') return 'title';
      const hasView = Boolean(row.querySelector('[role="group"][aria-label="View"]'));
      const hasChips = Boolean(row.querySelector('[data-testid^="filter-chip-"]'));
      if (hasView && hasChips) return 'toolbar';
      if (hasView) return 'view row';
      if (hasChips) return 'filter bar';
      return row.tagName;
    });
  });
  // One toolbar, not a "view row" and a "filter bar": the two names the
  // old stack had are exactly what must not come back.
  expect(order).toEqual(['title', 'toolbar']);

  // The chips and the count at the left, the view pair at the right, all
  // on one line -- which is the layout rule, not just the DOM nesting.
  const geometry = await page.evaluate(() => {
    const chip = document.querySelector('[data-testid="filter-chip-sector"]');
    const count = [...document.querySelectorAll('[data-testid="page-header"] *')].find(
      (node) => node.children.length === 0 && /^\d+ companies$/.test(node.textContent.trim()),
    );
    const viewPair = document.querySelector('[role="group"][aria-label="View"]');
    const box = (el) => el.getBoundingClientRect();
    return {
      chip: box(chip),
      count: box(count),
      view: box(viewPair),
      toolbarWidth: box(chip.closest('[data-testid="page-header"] > *')).width,
    };
  });
  // Same line: every one of the three overlaps the others vertically.
  const sameLine = (a, b) => a.top < b.bottom && b.top < a.bottom;
  expect(sameLine(geometry.chip, geometry.count)).toBe(true);
  expect(sameLine(geometry.chip, geometry.view)).toBe(true);
  // Left to right: chip, then the count, then the pair pushed to the end.
  expect(geometry.count.left).toBeGreaterThan(geometry.chip.left);
  expect(geometry.view.left).toBeGreaterThan(geometry.count.right);
  // "At the right" means at the row's right edge, not merely last.
  expect(geometry.view.right).toBeGreaterThan(geometry.chip.left + geometry.toolbarWidth * 0.8);

  // No primary action anywhere on the page: Companies has none (A1, and
  // owner decision 2026-11-01 -- a company is created from a job).
  await expect(page.getByRole('button', { name: /Add a company/i })).toHaveCount(0);
});
