import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard, mockMove, mockRetry } from './helpers.js';

const fixture = loadBoardFixture();

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

function columnOrder(column) {
  return column.evaluate((el) => [...el.querySelectorAll('[data-testid^="job-card-"]')].map((node) => node.dataset.testid));
}

// Dispatches the same DOM events a real drag produces, straight at the
// handlers under test, rather than relying on page.dragTo()'s bounding-box
// gesture (which targets a geometric point and can land on a different
// element than intended once a destination column already holds a card).
async function fireDrop(page, source, target) {
  const dataTransfer = await page.evaluateHandle(() => new DataTransfer());
  await source.dispatchEvent('dragstart', { dataTransfer });
  await target.dispatchEvent('dragover', { dataTransfer });
  await target.dispatchEvent('drop', { dataTransfer });
  await source.dispatchEvent('dragend', { dataTransfer });
}

test('dropping a card in another column toasts "Moved to X" with an Undo that restores the original column and slot', async ({
  page,
}) => {
  const requests = await mockMove(page);
  await page.goto('/');

  const moved = fixture.entries.find((entry) => entry.status === 'new');
  const originalOrder = fixture.entries.filter((entry) => entry.status === moved.status).map((entry) => `job-card-${entry.id}`);
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

  // Not just back in the right column - back in its original slot too.
  await expect(columnOrder(page.getByTestId(`board-column-${moved.status}`))).resolves.toEqual(originalOrder);

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

  const order = await columnOrder(column);
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

test('a failed move only rolls back its own card, leaving a different concurrent move intact', async ({ page }) => {
  const requests = [];
  await page.route('**/api/jobs/*', async (route) => {
    if (route.request().method() !== 'PUT') {
      route.fallback();
      return;
    }
    const body = route.request().postDataJSON();
    const id = route.request().url().split('/').pop();
    requests.push({ id, body });
    if (id === 'JOB-004') {
      // Resolves after the other move below has already succeeded, so its
      // failure rollback runs against a board that has already changed.
      await new Promise((resolve) => setTimeout(resolve, 150));
      route.fulfill({ status: 500, json: { error: 'nope' } });
    } else {
      route.fulfill({ status: 200, json: { ok: true } });
    }
  });
  await page.goto('/');

  const slow = fixture.entries.find((entry) => entry.id === 'JOB-004'); // status: applied
  const fast = fixture.entries.find((entry) => entry.id === 'JOB-001'); // status: new

  await fireDrop(page, page.getByTestId(`job-card-${slow.id}`), page.getByTestId('board-column-rejected'));
  await fireDrop(page, page.getByTestId(`job-card-${fast.id}`), page.getByTestId('board-column-interested'));

  await expect(page.getByText('Moved to Interested')).toBeVisible();
  await expect(page.getByTestId('board-column-interested').getByTestId(`job-card-${fast.id}`)).toBeVisible();

  // The slow move's failure lands after the fast one succeeded. It must
  // only revert JOB-004 - a whole-board-snapshot rollback would also wipe
  // out JOB-001's already-confirmed move.
  await expect(page.getByText('Status update failed.')).toBeVisible();
  await expect(page.getByTestId(`board-column-${slow.status}`).getByTestId(`job-card-${slow.id}`)).toBeVisible();
  await expect(page.getByTestId('board-column-rejected').getByTestId(`job-card-${slow.id}`)).toHaveCount(0);

  await expect(page.getByTestId('board-column-interested').getByTestId(`job-card-${fast.id}`)).toBeVisible();
  await expect(page.getByTestId(`board-column-${fast.status}`).getByTestId(`job-card-${fast.id}`)).toHaveCount(0);
});

test('a failed Undo reconciles the card to the moved state and shows a persistent error', async ({ page }) => {
  let calls = 0;
  await page.route('**/api/jobs/*', (route) => {
    if (route.request().method() !== 'PUT') {
      route.fallback();
      return;
    }
    calls += 1;
    if (calls === 1) {
      route.fulfill({ status: 200, json: { ok: true } }); // the move itself
    } else {
      route.fulfill({ status: 500, json: { error: 'nope' } }); // the Undo's own PUT
    }
  });
  await page.goto('/');

  const moved = fixture.entries.find((entry) => entry.status === 'new');
  await page.getByTestId(`job-card-${moved.id}`).dragTo(page.getByTestId('board-column-interested'));
  await expect(page.getByTestId('board-column-interested').getByTestId(`job-card-${moved.id}`)).toBeVisible();

  await page.getByRole('button', { name: 'Undo', exact: true }).click();

  // The Undo PUT failed server-side, so the server still has the job at the
  // moved-to status. The card must be reconciled back there, not left
  // displaying the pre-Undo column the server never actually restored.
  await expect(page.getByTestId('board-column-interested').getByTestId(`job-card-${moved.id}`)).toBeVisible();
  await expect(page.getByTestId(`board-column-${moved.status}`).getByTestId(`job-card-${moved.id}`)).toHaveCount(0);
  await expect(page.getByText('Status update failed.')).toBeVisible();
});

test('a persistent error is not replaced or removed by a later success toast', async ({ page }) => {
  await page.clock.install();
  await mockMove(page, { status: 500, body: { error: 'nope' } });
  await mockRetry(page);
  await page.goto('/');

  const moved = fixture.entries.find((entry) => entry.status === 'new');
  await page.getByTestId(`job-card-${moved.id}`).dragTo(page.getByTestId('board-column-interested'));

  const errorMessage = page.getByText('Status update failed.');
  await expect(errorMessage).toBeVisible();

  const retryable = fixture.entries.find((entry) => entry.ingest_state === 'extract_failed');
  await page.getByTestId(`job-card-${retryable.id}`).getByRole('button', { name: 'Retry' }).click();

  const successMessage = page.getByText('Retry started');
  await expect(successMessage).toBeVisible();
  await expect(errorMessage).toBeVisible();

  // The success toast auto-hides on its own timer; the error must still be
  // there afterwards - neither event may have cleared it as a side effect.
  await page.clock.fastForward(4500);
  await expect(successMessage).toHaveCount(0);
  await expect(errorMessage).toBeVisible();
});
