// Protects the board's filter bar: which chips it offers, that a choice
// filters the board and shows a removable active-filter Tag, and that the
// count on the right tells the open/ended split until a filter is on.
import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard } from './helpers.js';

const fixture = loadBoardFixture();
const total = fixture.entries.length;
const SPLIT = `${fixture.counts.open} open · ${fixture.counts.ended} ended`;

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('chip order is Function, Location, More filters, Needs attention, Hide closed postings', async ({ page }) => {
  await page.goto('/jobs');
  const chips = page.locator('[data-testid^="filter-chip-"]');
  await expect(chips).toHaveCount(5);
  const testIds = await chips.evaluateAll((nodes) => nodes.map((node) => node.dataset.testid));
  expect(testIds).toEqual([
    'filter-chip-function',
    'filter-chip-location',
    'filter-chip-more',
    'filter-chip-needs-attention',
    'filter-chip-hide-closed',
  ]);
});

// D7 removes the Fit facet outright: fit is not calculated, so the bar
// offers no filter for it (M0-4 had only taken the chip off the card).
test('there is no Fit facet', async ({ page }) => {
  await page.goto('/jobs');
  await expect(page.getByTestId('filter-chip-fit')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Fit', exact: true })).toHaveCount(0);
});

test('the count reads the open and ended split until a filter is on', async ({ page }) => {
  await page.goto('/jobs');
  await expect(page.getByText(SPLIT, { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Needs attention', exact: true }).click();
  await expect(page.getByText(SPLIT, { exact: true })).toHaveCount(0);
  const needing = fixture.entries.filter((entry) => entry.needs_attention).length;
  await expect(page.getByText(`${needing} of ${total} jobs`, { exact: true })).toBeVisible();
});

test('a Function chip selection opens its panel, filters the board, and shows a removable active-filter Tag', async ({
  page,
}) => {
  await page.goto('/jobs');
  const [targetId, targetLabel] = fixture.function_options[0];
  const matching = fixture.entries.filter((entry) => entry.function.includes(targetId));
  const nonMatching = fixture.entries.filter((entry) => !entry.function.includes(targetId));
  expect(matching.length).toBeGreaterThan(0);
  expect(nonMatching.length).toBeGreaterThan(0);

  const chip = page.getByTestId('filter-chip-function');
  await expect(chip).toHaveAttribute('aria-expanded', 'false');
  await chip.click();
  await expect(chip).toHaveAttribute('aria-expanded', 'true');

  await page.getByRole('checkbox', { name: targetLabel }).check();
  for (const entry of matching) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
  for (const entry of nonMatching) {
    await expect(page.getByText(entry.title, { exact: true })).toHaveCount(0);
  }
  await expect(page.getByText(`${matching.length} of ${total} jobs`, { exact: true })).toBeVisible();

  const tagText = `Function: ${targetLabel}`;
  await expect(page.getByText(tagText, { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await expect(chip).toHaveAttribute('aria-expanded', 'false');

  // Removing the Tag clears the filter, restores every open card, and
  // drops the result count back to the open/ended split.
  await page.getByRole('button', { name: `Remove ${tagText}` }).click();
  await expect(page.getByText(SPLIT, { exact: true })).toBeVisible();
});

test('Location and Function filters combine, and Clear all resets every group and the count', async ({ page }) => {
  await page.goto('/jobs');

  // An open job, so the card the filters keep is in a column rather than
  // in the collapsed Ended lane.
  const open = fixture.entries.filter((entry) => !fixture.ended_statuses.includes(entry.status));
  const [functionId, functionLabel] = fixture.function_options.find(([id]) =>
    open.some((entry) => entry.function.includes(id) && entry.location),
  );
  const location = open.find((entry) => entry.function.includes(functionId) && entry.location).location;

  await page.getByTestId('filter-chip-function').click();
  await page.getByRole('checkbox', { name: functionLabel }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();

  // Location has more than 6 distinct values in the fixture, so the panel's
  // own search field (rather than relying on where it falls in the
  // "Show N more" list) is the robust way to reach any one option.
  await page.getByTestId('filter-chip-location').click();
  await page.getByRole('searchbox', { name: 'Search location' }).fill(location);
  await page.getByRole('checkbox', { name: location }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();

  const expected = open.filter((entry) => entry.function.includes(functionId) && entry.location === location);
  const excluded = fixture.entries.filter(
    (entry) => !(entry.function.includes(functionId) && entry.location === location),
  );
  for (const entry of expected) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
  for (const entry of excluded) {
    await expect(page.getByText(entry.title, { exact: true })).toHaveCount(0);
  }

  await expect(page.getByText('Active filters')).toBeVisible();
  await page.getByRole('button', { name: 'Clear all', exact: true }).click();

  await expect(page.getByText('Active filters')).toHaveCount(0);
  await expect(page.getByText(SPLIT, { exact: true })).toBeVisible();
});

test('Needs attention alone shows Clear all, and clearing it resets the toggle', async ({ page }) => {
  await page.goto('/jobs');
  const toggle = page.getByRole('button', { name: 'Needs attention', exact: true });

  await expect(page.getByText('Active filters')).toHaveCount(0);
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');

  await expect(page.getByText('Active filters')).toBeVisible();
  const clearAll = page.getByRole('button', { name: 'Clear all', exact: true });
  await expect(clearAll).toBeVisible();

  await clearAll.click();

  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByText('Active filters')).toHaveCount(0);
});

test('Clear all resets both toggles together with a group filter', async ({ page }) => {
  await page.goto('/jobs');
  const needs = page.getByRole('button', { name: 'Needs attention', exact: true });
  const hideClosed = page.getByRole('button', { name: 'Hide closed postings', exact: true });
  await needs.click();
  await hideClosed.click();

  await page.getByTestId('filter-chip-function').click();
  await page.getByRole('checkbox', { name: fixture.function_options[0][1] }).check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();

  await expect(page.getByText('Active filters')).toBeVisible();
  await page.getByRole('button', { name: 'Clear all', exact: true }).click();

  await expect(needs).toHaveAttribute('aria-pressed', 'false');
  await expect(hideClosed).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByText('Active filters')).toHaveCount(0);
  await expect(page.getByText(SPLIT, { exact: true })).toBeVisible();
});

// D7: the toggle is off on every load, and it hides a flagged job wherever
// it sits, which is why it is a filter and not a per-column rule.
test('Hide closed postings hides every flagged job and is off again after reload', async ({ page }) => {
  await page.goto('/jobs');
  const toggle = page.getByRole('button', { name: 'Hide closed postings', exact: true });
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');

  const closed = fixture.entries.filter((entry) => entry.closed);
  const openPosting = fixture.entries.filter(
    (entry) => !entry.closed && !fixture.ended_statuses.includes(entry.status),
  );
  expect(closed.length).toBeGreaterThan(0);
  for (const entry of closed) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }

  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  for (const entry of closed) {
    await expect(page.getByText(entry.title, { exact: true })).toHaveCount(0);
  }
  for (const entry of openPosting) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
  await expect(page.getByText(`${total - closed.length} of ${total} jobs`, { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByRole('button', { name: 'Hide closed postings', exact: true })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  for (const entry of closed) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
});

test('More filters opens Industry and Company size, and a selection narrows the board', async ({ page }) => {
  await page.goto('/jobs');
  const target = fixture.entries.find(
    (entry) => entry.industries?.length && !fixture.ended_statuses.includes(entry.status),
  );
  expect(target).toBeTruthy();
  const matching = fixture.entries.filter(
    (entry) => (entry.industries || []).includes(target.industries[0]) && !fixture.ended_statuses.includes(entry.status),
  );
  const nonMatching = fixture.entries.filter((entry) => !(entry.industries || []).includes(target.industries[0]));

  await page.getByTestId('filter-chip-more').click();
  await expect(page.getByRole('heading', { name: 'More filters' })).toBeVisible();

  await page.getByRole('checkbox', { name: target.industries[0] }).check();
  for (const entry of matching) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
  for (const entry of nonMatching) {
    await expect(page.getByText(entry.title, { exact: true })).toHaveCount(0);
  }

  await page.getByRole('button', { name: /^Show \d+ jobs$/ }).click();
  await expect(page.getByRole('heading', { name: 'More filters' })).toHaveCount(0);
});

// Company size filters on the linked company's own size class (the one
// scale the Companies directory uses too), not on the posting's raw
// employee count: a job whose posting never stated a headcount still
// filters by the class its company carries.
test('a Company size selection in More filters narrows the board by the company size class', async ({ page }) => {
  await page.goto('/jobs');
  const medium = fixture.entries.filter((entry) => entry.company_size_class === 'medium');
  const matching = medium.filter((entry) => !fixture.ended_statuses.includes(entry.status));
  const nonMatching = fixture.entries.filter((entry) => entry.company_size_class !== 'medium');
  expect(matching.length).toBeGreaterThan(0);
  expect(medium.some((entry) => typeof entry.employee_count !== 'number')).toBe(true);

  await page.getByTestId('filter-chip-more').click();
  await page.getByRole('checkbox', { name: 'Medium', exact: true }).check();

  for (const entry of matching) {
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
  }
  for (const entry of nonMatching) {
    await expect(page.getByText(entry.title, { exact: true })).toHaveCount(0);
  }
});

// CAREER-71: the facet shows each class by the taxonomy's own label,
// which the backend sends beside the code. `xl` is the case that proves
// it -- its label is "Very large", and title-casing the code in the
// browser read "Xl".
test('the Company size facet names the xl class "Very large", not "Xl"', async ({ page }) => {
  await page.goto('/jobs');
  expect(fixture.entries.some((entry) => entry.company_size_class === 'xl')).toBe(true);

  await page.getByTestId('filter-chip-more').click();
  await expect(page.getByRole('checkbox', { name: 'Very large', exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'Xl', exact: true })).toHaveCount(0);
});

// --- popovers are opaque and on top (brief 2026-10-18, section 2) --------
//
// The panel was never transparent: Gestalt's Popover renders inline with
// no z-index, and Gestalt's own <table> carries `isolation: isolate`,
// which makes it a stacking context painted in the same pass, later in
// tree order. So the table drew over the panel, which reads exactly like
// seeing the table through it. Every overlay now mounts in a Gestalt
// Layer (src/components/FloatingPopover.jsx), so the guard is the same
// in both views and at both scroll positions: the element under the
// panel's own centre is part of the panel.

// What is actually painted at a point, named.
async function topmostAt(page, locator) {
  return locator.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return {
      insidePanel: Boolean(top) && (node === top || node.contains(top)),
      background: getComputedStyle(node).backgroundColor,
      what: top ? `${top.tagName}.${String(top.className).slice(0, 30)}` : 'nothing',
    };
  });
}

for (const view of ['Board', 'List']) {
  for (const scrolled of [false, true]) {
    const where = scrolled ? 'scrolled down' : 'at the top';
    test(`in ${view} view ${where}, every filter popover is opaque and on top`, async ({ page }) => {
      await page.goto('/jobs');
      await page.getByRole('button', { name: view, exact: true }).click();
      if (scrolled) await page.mouse.wheel(0, 400);

      for (const chip of ['function', 'location']) {
        await page.getByTestId(`filter-chip-${chip}`).click();
        const panel = page.getByRole('dialog');
        await expect(panel).toBeVisible();
        const result = await topmostAt(page, panel);
        expect(result.background).toBe('rgb(255, 255, 255)'); // the card ground
        expect(result).toMatchObject({ insidePanel: true });
        await page.keyboard.press('Escape');
      }

      // The More filters panel is an OverlayPanel, which mounts in its
      // own Layer; it is checked here because the owner saw the same bug
      // on it.
      await page.getByTestId('filter-chip-more').click();
      const more = page.getByRole('dialog', { name: 'More filters' });
      await expect(more).toBeVisible();
      // Its own footer button is what to check rather than the dialog's
      // centre: the dialog is the full-screen container and the sheet is
      // only its right-hand side. The check is a real click, which
      // Playwright refuses to land when another element would receive
      // it -- which is exactly what the sticky lane used to do to this
      // button.
      const apply = more.getByRole('button', { name: /^Show \d+ jobs$/ });
      await expect(apply).toBeVisible();
      await apply.click({ timeout: 5000 });
      await expect(more).toHaveCount(0);
    });
  }
}

// The two other layered controls the brief names.
test("the card's status dropdown is opaque and on top of the board", async ({ page }) => {
  await page.goto('/jobs');
  const card = page.getByTestId(`job-card-${fixture.entries[0].id}`);
  await card.getByTestId(`status-select-${fixture.entries[0].id}`).click();
  const menu = page.getByRole('menu');
  await expect(menu).toBeVisible();
  expect(await topmostAt(page, menu)).toMatchObject({ insidePanel: true });
});

test('the "How did it end?" chooser is opaque and on top of the board', async ({ page }) => {
  await page.goto('/jobs');
  const open = fixture.entries.find((entry) => !fixture.ended_statuses.includes(entry.status));
  const card = page.getByTestId(`job-card-${open.id}`);
  const strip = page.getByTestId('ended-lane-collapsed');

  const dataTransfer = await page.evaluateHandle(() => new DataTransfer());
  await card.dispatchEvent('dragstart', { dataTransfer });
  await strip.dispatchEvent('drop', { dataTransfer });

  const chooser = page.getByRole('dialog', { name: `How did ${open.title} end?` });
  await expect(chooser).toBeVisible();
  expect(await topmostAt(page, chooser)).toMatchObject({ insidePanel: true });
});

// 2026-10-29 brief, B2: the chip is 32px high (it was 40px), 14px bold,
// pill radius; unselected is the secondary fill and darkens on hover,
// selected is the brand wash behind a 2px brand border.
test('a filter chip is 32px, 14px bold and a pill, and its ground follows the state', async ({
  page,
}) => {
  await page.goto('/jobs');
  const chip = page.getByTestId('filter-chip-needs-attention');
  await expect(chip).toBeVisible();

  const metrics = await chip.evaluate((el) => {
    const cs = getComputedStyle(el);
    const label = [...el.querySelectorAll('*')].find(
      (node) => node.children.length === 0 && node.textContent.trim() === 'Needs attention',
    );
    const labelStyle = getComputedStyle(label);
    return {
      height: cs.height,
      radius: cs.borderTopLeftRadius,
      borderWidth: cs.borderTopWidth,
      background: cs.backgroundColor,
      border: cs.borderTopColor,
      fontSize: labelStyle.fontSize,
      fontWeight: labelStyle.fontWeight,
    };
  });

  // Height is the content box plus the two borders, which is what
  // box-sizing: border-box in FilterChip.jsx is there to keep true.
  expect(metrics.height).toBe('32px');
  expect(metrics.radius).toBe('999px');
  expect(metrics.borderWidth).toBe('2px');
  expect(metrics.fontSize).toBe('14px');
  expect(metrics.fontWeight).toBe('700');

  // Unselected: the secondary fill behind a border that is present but
  // transparent, so selecting it never reflows the row.
  expect(metrics.background).toBe('rgb(232, 231, 225)'); // --color-background-secondary-base
  expect(metrics.border).toBe('rgba(0, 0, 0, 0)');

  // Hover darkens the unselected ground to the secondary weak.
  await chip.hover();
  await expect(chip).toHaveCSS('background-color', 'rgb(214, 212, 205)'); // --color-background-secondary-weak

  // Selected: the brand wash behind a 2px brand border, and the hover
  // does not take that away while the pointer is still on it.
  await chip.click();
  await expect(chip).toHaveAttribute('aria-pressed', 'true');
  await expect(chip).toHaveCSS('background-color', 'rgb(227, 250, 225)'); // --color-brand-wash
  await expect(chip).toHaveCSS('border-top-color', 'rgb(0, 135, 83)'); // --color-brand-primary
  await expect(chip).toHaveCSS('height', '32px');
});

// CAREER-118 PR 1: the view pair is a SegmentedControl now, and the
// export puts its items at 32px -- the same height as the filter row, no
// longer the 44px the FilterChip pair borrowed from the button beside it.
// 44px comes back at phone width, where every target is 44px.
test('the view items are 32px like the filter row, and 44px at phone width', async ({ page }) => {
  await page.goto('/jobs');
  await expect(page.getByTestId('view-chip-board')).toHaveCSS('height', '32px');
  await expect(page.getByTestId('view-chip-list')).toHaveCSS('height', '32px');
  await expect(page.getByTestId('filter-chip-function')).toHaveCSS('height', '32px');

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId('view-chip-board')).toHaveCSS('height', '44px');
  await expect(page.getByTestId('view-chip-list')).toHaveCSS('height', '44px');
});
