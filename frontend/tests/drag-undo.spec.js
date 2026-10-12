import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard, mockMove } from './helpers.js';

const fixture = loadBoardFixture();

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('dropping a card in another column toasts "Moved to X" with an Undo that restores the original column', async ({
  page,
}) => {
  const requests = await mockMove(page);
  await page.goto('/');

  const moved = fixture.entries.find((entry) => entry.status === 'new');
  const card = page.getByTestId(`job-card-${moved.id}`);
  await card.dragTo(page.getByTestId('board-column-interested'));

  await expect(page.getByTestId('board-column-interested').getByTestId(`job-card-${moved.id}`)).toBeVisible();
  await expect(page.getByText('Moved to Interested')).toBeVisible();
  const undo = page.getByRole('button', { name: 'Undo', exact: true });
  await expect(undo).toBeVisible();

  await undo.click();

  await expect(page.getByTestId(`board-column-${moved.status}`).getByTestId(`job-card-${moved.id}`)).toBeVisible();
  await expect(page.getByTestId('board-column-interested').getByTestId(`job-card-${moved.id}`)).toHaveCount(0);
  await expect(page.getByText('Moved to Interested')).toHaveCount(0);

  // The original move plus the Undo's own revert, both real status writes.
  expect(requests).toHaveLength(2);
  expect(requests[0].body).toEqual({ status: 'interested' });
  expect(requests[1].body).toEqual({ status: moved.status });
});

test('reordering two cards within the same column is a pure client-side move: no request, no toast', async ({
  page,
}) => {
  const requests = await mockMove(page);
  await page.goto('/');

  const sameColumn = fixture.entries.filter((entry) => entry.status === 'new');
  expect(sameColumn.length).toBeGreaterThan(1);
  const [first, second] = sameColumn;

  const column = page.getByTestId(`board-column-${first.status}`);
  await column.getByTestId(`job-card-${second.id}`).dragTo(column.getByTestId(`job-card-${first.id}`));

  const order = await column.evaluate((el) =>
    [...el.querySelectorAll('[data-testid^="job-card-"]')].map((node) => node.dataset.testid),
  );
  expect(order).toEqual([`job-card-${second.id}`, `job-card-${first.id}`]);

  expect(requests).toHaveLength(0);
  await expect(page.getByText(/^Moved to /)).toHaveCount(0);
});

test('dragging a card over a column highlights it, and an empty column invites the drop', async ({ page }) => {
  await mockMove(page);
  await page.goto('/');

  const moved = fixture.entries.find((entry) => entry.status === 'new');
  const emptyStatus = fixture.statuses.find((status) => !fixture.entries.some((entry) => entry.status === status));
  const card = page.getByTestId(`job-card-${moved.id}`);
  const body = page.getByTestId(`column-body-${emptyStatus}`);

  // A real OS-level drag gesture (page.mouse down/move) never starts a
  // native HTML5 drag from synthetic input the way page.dragTo does, so the
  // dragover-driven highlight is exercised by dispatching the same DOM
  // events the browser would during an actual drag, directly on the
  // elements our onDragStart/onDragOver handlers are attached to.
  const dataTransfer = await page.evaluateHandle(() => new DataTransfer());
  await card.dispatchEvent('dragstart', { dataTransfer });
  await body.dispatchEvent('dragover', { dataTransfer });

  await expect(body).toHaveCSS('outline-color', 'rgb(0, 95, 203)');
  await expect(page.getByTestId(`board-column-${emptyStatus}`).getByText('Drop here')).toBeVisible();

  await card.dispatchEvent('dragend', { dataTransfer });
});
