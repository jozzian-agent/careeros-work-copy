// Protects the Ended lane (D7, rebuilt 2026-10-18): that it starts
// collapsed on every load, is the grey full-height strip at the right
// edge with one count row per outcome, heads with "Your search so far"
// once opened, and groups Won, Rejected and Stopped with compact cards
// that carry a reason.
import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard } from './helpers.js';

const fixture = loadBoardFixture();
const endedEntries = fixture.entries.filter((entry) => fixture.ended_statuses.includes(entry.status));

function endedOf(status) {
  return endedEntries.filter((entry) => entry.status === status);
}

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('the lane is collapsed on load, shows the split, and no ended card is on the board', async ({ page }) => {
  await page.goto('/jobs');

  const strip = page.getByTestId('ended-lane-collapsed');
  await expect(strip).toBeVisible();
  await expect(page.getByTestId('ended-lane')).toHaveCount(0);
  await expect(strip).toHaveAttribute('aria-label', `Ended, ${endedEntries.length} jobs`);
  await expect(strip.getByText('Ended', { exact: true })).toBeVisible();
  await expect(strip.getByText(String(endedEntries.length), { exact: true })).toBeVisible();
  // One row per outcome, the label on the left and the number on the
  // right, instead of the wrapped "Won 1" pairs the strip used to stack.
  for (const status of fixture.ended_statuses) {
    const row = strip.getByTestId(`ended-count-${status}`);
    await expect(row.getByText(fixture.status_labels[status], { exact: true })).toBeVisible();
    await expect(row.getByText(String(endedOf(status).length), { exact: true })).toBeVisible();
  }
  await expect(strip.getByRole('button', { name: 'Show ended jobs' })).toBeVisible();
  await expect(strip.getByText('Drop a job here to end it')).toBeVisible();

  for (const entry of endedEntries) {
    await expect(page.getByText(entry.title, { exact: true })).toHaveCount(0);
  }
});

test('Show opens the lane, Hide closes it, and a reload collapses it again', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Show ended jobs' }).click();

  const lane = page.getByTestId('ended-lane');
  await expect(lane).toBeVisible();
  await expect(page.getByTestId('ended-lane-collapsed')).toHaveCount(0);
  for (const entry of endedEntries) {
    await expect(lane.getByText(entry.title, { exact: true })).toBeVisible();
  }

  await page.getByRole('button', { name: 'Hide ended jobs' }).click();
  await expect(page.getByTestId('ended-lane-collapsed')).toBeVisible();

  await page.getByRole('button', { name: 'Show ended jobs' }).click();
  await expect(page.getByTestId('ended-lane')).toBeVisible();

  // Remembering the choice is on the brief's deferred list, so a reload
  // deliberately collapses it again.
  await page.reload();
  await expect(page.getByTestId('ended-lane-collapsed')).toBeVisible();
  await expect(page.getByTestId('ended-lane')).toHaveCount(0);
});

test('the lane heads with Your search so far, read from the payload', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Show ended jobs' }).click();

  const stats = page.getByTestId('search-so-far');
  await expect(stats.getByText('Your search so far')).toBeVisible();
  for (const [label, key] of [
    ['Applied to', 'applied_to'],
    ['Interviews', 'interviews'],
    ['Offers', 'offers'],
  ]) {
    const row = page.getByTestId(`search-so-far-${key}`);
    await expect(row.getByText(label, { exact: true })).toBeVisible();
    await expect(row.getByText(String(fixture.search_so_far[key]), { exact: true })).toBeVisible();
  }
  const top = fixture.search_so_far.top_stopped_reason;
  const topRow = page.getByTestId('search-so-far-top-reason');
  await expect(topRow.getByText('Most common reason to stop', { exact: true })).toBeVisible();
  await expect(topRow.getByText(`${top.reason} (${top.count})`, { exact: true })).toBeVisible();
});

// The line is absent, not zeroed, while no stopped job carries a reason:
// "none" would be a fact about the field rather than about the search.
test('the most common reason line is absent when the payload has none', async ({ page }) => {
  const withoutTop = { ...fixture, search_so_far: { ...fixture.search_so_far } };
  delete withoutTop.search_so_far.top_stopped_reason;
  await mockBoard(page, withoutTop);
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Show ended jobs' }).click();

  await expect(page.getByTestId('search-so-far')).toBeVisible();
  await expect(page.getByText('Most common reason to stop')).toHaveCount(0);
});

test('the lane is one column with a group per ended status, each labelled with its count', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Show ended jobs' }).click();

  for (const status of fixture.ended_statuses) {
    const group = page.getByTestId(`ended-group-${status}`);
    await expect(group).toBeVisible();
    const count = endedOf(status).length;
    await expect(group).toHaveAttribute(
      'aria-label',
      `${fixture.status_labels[status]}, ${count} ${count === 1 ? 'job' : 'jobs'}`,
    );
    for (const entry of endedOf(status)) {
      await expect(group.getByText(entry.title, { exact: true })).toBeVisible();
    }
  }
  // One 320px column, not three side by side.
  const box = await page.getByTestId('ended-lane').boundingBox();
  expect(box.width).toBeGreaterThan(300);
  expect(box.width).toBeLessThan(341);
});

test('an ended card shows its reason, or offers to add one', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Show ended jobs' }).click();

  const withReason = endedEntries.find((entry) => entry.end_reason);
  // Won carries no reason vocabulary, so the card that offers to add one
  // is an ended job in a status that has suggestions.
  const withoutReason = endedEntries.find((entry) => fixture.end_reasons[entry.status] && !entry.end_reason);
  expect(withReason && withoutReason).toBeTruthy();

  const explained = page.getByTestId(`job-card-${withReason.id}`);
  await expect(explained.getByText(withReason.end_reason, { exact: true })).toBeVisible();
  await expect(explained.getByRole('button', { name: `Add a reason ${withReason.title} ended` })).toHaveCount(0);

  const unexplained = page.getByTestId(`job-card-${withoutReason.id}`);
  await expect(unexplained.getByRole('button', { name: `Add a reason ${withoutReason.title} ended` })).toBeVisible();

  // Compact: an ended card says nothing about the posting or its company
  // details, only title, company and the reason.
  await expect(explained.getByText('Salary disclosed')).toHaveCount(0);
  await expect(explained.getByText(/^Posted /)).toHaveCount(0);
});

test('an empty group says so rather than showing an empty box', async ({ page }) => {
  const openOnly = {
    ...fixture,
    entries: fixture.entries.filter((entry) => !fixture.ended_statuses.includes(entry.status)),
    counts: { open: fixture.counts.open, ended: 0 },
  };
  await mockBoard(page, openOnly);
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Show ended jobs' }).click();

  for (const [status, text] of [
    ['won', 'Nothing won yet'],
    ['rejected', 'Nothing rejected yet'],
    ['stopped', 'Nothing stopped yet'],
  ]) {
    await expect(page.getByTestId(`ended-group-${status}`).getByText(text, { exact: true })).toBeVisible();
  }
});

test('a group shows its latest three jobs and offers the rest', async ({ page }) => {
  const stopped = endedOf('stopped')[0];
  const extra = [1, 2, 3].map((index) => ({
    ...stopped,
    id: `JOB-90${index}`,
    title: `Extra stopped job ${index}`,
    status_changed: `2026-09-0${index}`,
  }));
  const many = { ...fixture, entries: [...fixture.entries, ...extra] };
  await mockBoard(page, many);
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Show ended jobs' }).click();

  const group = page.getByTestId('ended-group-stopped');
  const totalStopped = endedOf('stopped').length + extra.length;
  await expect(group.locator('[data-testid^="job-card-"]')).toHaveCount(3);
  // Latest first, by the day the status changed, so the three shown are
  // the three most recently ended.
  await expect(group.getByText(endedOf('stopped')[0].title, { exact: true })).toBeVisible();

  const showAll = group.getByRole('button', { name: `Show all ${totalStopped}` });
  await expect(showAll).toBeVisible();
  await showAll.click();
  await expect(group.locator('[data-testid^="job-card-"]')).toHaveCount(totalStopped);

  // And a way back to the three-card preview.
  const showFewer = group.getByRole('button', { name: 'Show fewer' });
  await expect(showFewer).toBeVisible();
  await showFewer.click();
  await expect(group.locator('[data-testid^="job-card-"]')).toHaveCount(3);
  await expect(group.getByRole('button', { name: `Show all ${totalStopped}` })).toBeVisible();
});

test('the lane keeps the right edge while the columns scroll sideways', async ({ page }) => {
  await page.goto('/jobs');
  const strip = page.getByTestId('ended-lane-collapsed');
  const before = (await strip.boundingBox()).x;
  const row = page.getByTestId('board-row');

  // The lane is a sibling of the scrolling row, not an item of it, so
  // scrolling the columns moves nothing about the lane.
  const scrolled = await row.evaluate((el) => {
    el.scrollBy(400, 0);
    return el.scrollLeft;
  });
  expect(scrolled).toBeGreaterThan(0);

  const after = (await strip.boundingBox()).x;
  expect(Math.abs(after - before)).toBeLessThan(2);
  // And it is on screen, not past the right edge.
  const viewport = page.viewportSize();
  expect(after).toBeLessThan(viewport.width);

  // The whole scrolling area ends before the lane begins, so no column
  // can slide under it at any scroll position, not only at the end.
  const rowRight = (await row.boundingBox()).x + (await row.boundingBox()).width;
  expect(rowRight).toBeLessThanOrEqual(after + 1);
});

// Section 4 of the brief: grey, no border, the full height of the board,
// 168px wide, with "Ended" on the column titles' baseline under a grey
// rule rather than the columns' blue one.
test('the collapsed lane is the grey full-height strip, 168px wide, aligned with the column headers', async ({
  page,
}) => {
  await page.goto('/jobs');
  const strip = page.getByTestId('ended-lane-collapsed');
  await expect(strip).toBeVisible();

  const style = await strip.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { background: cs.backgroundColor, border: cs.borderTopWidth, radius: cs.borderTopLeftRadius };
  });
  expect(style.background).toBe('rgb(232, 231, 225)'); // --color-background-secondary-base
  expect(style.border).toBe('0px');
  expect(style.radius).toBe('16px');

  const box = await strip.boundingBox();
  expect(Math.round(box.width)).toBe(168);

  // The board's own height, not the strip's content height: the tallest
  // column decides it.
  const tallest = await page.evaluate(() => {
    const columns = [...document.querySelectorAll('[data-testid^="board-column-"]')];
    return Math.max(...columns.map((el) => el.getBoundingClientRect().height));
  });
  expect(box.height).toBeGreaterThanOrEqual(tallest);

  // "Ended" shares a baseline with the column titles, and its rule is
  // grey where theirs is blue.
  const header = page.getByTestId('ended-lane-header');
  const firstColumn = page.getByTestId(`column-header-${fixture.statuses[0]}`);
  const headerBox = await header.boundingBox();
  const columnBox = await firstColumn.boundingBox();
  expect(Math.abs(headerBox.y - columnBox.y)).toBeLessThan(2);
  expect(Math.abs(headerBox.height - columnBox.height)).toBeLessThan(2);
  const rule = await header.evaluate((el) => getComputedStyle(el).borderBottomColor);
  expect(rule).toBe('rgb(199, 198, 193)'); // --color-border-container
  const columnRule = await firstColumn.evaluate((el) => getComputedStyle(el).borderBottomColor);
  expect(columnRule).toBe('rgb(0, 135, 83)'); // --color-brand-primary
});

// At either width the owner works at, the lane covers no column once the
// row is scrolled to its end (brief outcome 4).
for (const width of [1280, 1920]) {
  test(`at ${width}px the lane covers no column when the row is scrolled to the end`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/jobs');
    const strip = page.getByTestId('ended-lane-collapsed');
    await expect(strip).toBeVisible();
    await page.getByTestId('board-row').evaluate((el) => el.scrollBy(el.scrollWidth, 0));

    const laneLeft = (await strip.boundingBox()).x;
    const rights = await page.evaluate(() =>
      [...document.querySelectorAll('[data-testid^="board-column-"]')].map(
        (el) => el.getBoundingClientRect().right,
      ),
    );
    expect(rights.length).toBeGreaterThan(0);
    rights.forEach((right) => expect(right).toBeLessThanOrEqual(laneLeft + 1));
  });
}

// Chromium does not start a native HTML5 drag from synthetic input the
// way page.dragTo does, so the dragover state is exercised by
// dispatching the same DOM events, as tests/drag-undo.spec.js does.
test('dragging a card over the collapsed lane turns it blue and says Drop to end', async ({ page }) => {
  await page.goto('/jobs');
  const open = fixture.entries.find((entry) => !fixture.ended_statuses.includes(entry.status));
  const card = page.getByTestId(`job-card-${open.id}`);
  const strip = page.getByTestId('ended-lane-collapsed');

  const dataTransfer = await page.evaluateHandle(() => new DataTransfer());
  await card.dispatchEvent('dragstart', { dataTransfer });
  await strip.dispatchEvent('dragover', { dataTransfer });

  await expect(strip.getByText('Drop to end', { exact: true })).toBeVisible();
  const dragStyle = await strip.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { background: cs.backgroundColor, outline: cs.outlineStyle, outlineWidth: cs.outlineWidth };
  });
  expect(dragStyle.background).toBe('rgb(227, 250, 225)'); // --color-brand-wash
  expect(dragStyle.outline).toBe('dashed');
  expect(dragStyle.outlineWidth).toBe('2px');

  await card.dispatchEvent('dragend', { dataTransfer });
  await expect(strip.getByText('Drop a job here to end it')).toBeVisible();
});
