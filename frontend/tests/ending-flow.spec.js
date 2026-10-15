// Protects the ending flows (D7): the chooser a drop on the collapsed lane
// opens, the confirmation Won always asks for, the move-at-once plus Undo
// that Rejected and Stopped get, and the optional reason afterwards.
import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard, mockMove, mockNoteWrites, selectStatus } from './helpers.js';

const fixture = loadBoardFixture();

// Dispatches the same DOM events a real drag produces, straight at the
// handlers under test, rather than relying on page.dragTo()'s bounding-box
// gesture.
async function fireDrop(page, source, target) {
  const dataTransfer = await page.evaluateHandle(() => new DataTransfer());
  await source.dispatchEvent('dragstart', { dataTransfer });
  await target.dispatchEvent('dragover', { dataTransfer });
  await target.dispatchEvent('drop', { dataTransfer });
  await source.dispatchEvent('dragend', { dataTransfer });
}

function openJob(status) {
  return fixture.entries.find((entry) => entry.status === status);
}

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('dropping a card on the collapsed lane asks how it ended', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');

  const job = openJob('applied');
  await fireDrop(page, page.getByTestId(`job-card-${job.id}`), page.getByTestId('ended-lane-collapsed'));

  const chooser = page.getByRole('dialog', { name: `How did ${job.title} end?` });
  await expect(chooser).toBeVisible();
  await expect(chooser.getByText('How did it end?')).toBeVisible();
  for (const status of fixture.ended_statuses) {
    await expect(chooser.getByRole('button', { name: fixture.status_labels[status], exact: true })).toBeVisible();
  }
  // Nothing is written until an outcome is picked.
  expect(requests).toHaveLength(0);
  // The card has not moved either.
  await expect(page.getByTestId(`board-column-${job.status}`).getByTestId(`job-card-${job.id}`)).toBeVisible();
});

test('the chooser can be closed with the keyboard and leaves the job where it was', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');

  const job = openJob('applied');
  await fireDrop(page, page.getByTestId(`job-card-${job.id}`), page.getByTestId('ended-lane-collapsed'));
  const chooser = page.getByRole('dialog', { name: `How did ${job.title} end?` });
  await expect(chooser).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(chooser).toHaveCount(0);
  expect(requests).toHaveLength(0);
  await expect(page.getByTestId(`board-column-${job.status}`).getByTestId(`job-card-${job.id}`)).toBeVisible();
});

test('Stopped moves the card at once, offers a reason and an Undo that puts it back', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');

  const job = openJob('applied');
  await fireDrop(page, page.getByTestId(`job-card-${job.id}`), page.getByTestId('ended-lane-collapsed'));
  await page.getByRole('dialog').getByRole('button', { name: 'Stopped', exact: true }).click();

  await expect(page.getByText('Moved to Stopped')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add a reason', exact: true })).toBeVisible();
  const undo = page.getByRole('button', { name: 'Undo', exact: true });
  await expect(undo).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0].body).toEqual({ status: 'stopped' });

  // The card is in the lane now, which is still collapsed, so the proof is
  // the group it lands in once the lane is opened.
  await page.getByRole('button', { name: 'Show ended jobs' }).click();
  await expect(page.getByTestId('ended-group-stopped').getByTestId(`job-card-${job.id}`)).toBeVisible();

  await undo.click();
  await expect(page.getByTestId(`board-column-${job.status}`).getByTestId(`job-card-${job.id}`)).toBeVisible();
  await expect(page.getByTestId('ended-group-stopped').getByTestId(`job-card-${job.id}`)).toHaveCount(0);
  expect(requests).toHaveLength(2);
  expect(requests[1].body).toEqual({ status: job.status });
});

test('Won asks first, and Cancel leaves every job exactly where it was', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');

  const job = openJob('offer');
  const other = openJob('applied');
  await fireDrop(page, page.getByTestId(`job-card-${job.id}`), page.getByTestId('ended-lane-collapsed'));
  await page.getByRole('dialog').getByRole('button', { name: 'Won', exact: true }).click();

  const confirm = page.getByRole('alertdialog', { name: 'Mark as won' });
  await expect(confirm).toBeVisible();
  await expect(
    confirm.getByText(`${job.title} at ${job.company_name} moves to Won. Your other jobs stay as they are.`),
  ).toBeVisible();

  await confirm.getByRole('button', { name: 'Cancel', exact: true }).click();
  expect(requests).toHaveLength(0);
  await expect(page.getByTestId(`board-column-${job.status}`).getByTestId(`job-card-${job.id}`)).toBeVisible();
  await expect(page.getByTestId(`board-column-${other.status}`).getByTestId(`job-card-${other.id}`)).toBeVisible();
});

test('Mark as won moves only that job and leaves the other open ones alone', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');

  const job = openJob('offer');
  const others = fixture.entries.filter(
    (entry) => entry.id !== job.id && !fixture.ended_statuses.includes(entry.status),
  );
  await fireDrop(page, page.getByTestId(`job-card-${job.id}`), page.getByTestId('ended-lane-collapsed'));
  await page.getByRole('dialog').getByRole('button', { name: 'Won', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Mark as won', exact: true }).click();

  await expect(page.getByText('Moved to Won')).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0].body).toEqual({ status: 'won' });
  // Won has no reason suggestions, so the message offers no reason either.
  await expect(page.getByRole('button', { name: 'Add a reason', exact: true })).toHaveCount(0);

  for (const entry of others) {
    await expect(page.getByTestId(`board-column-${entry.status}`).getByTestId(`job-card-${entry.id}`)).toBeVisible();
  }
});

test('dropping on a group of the expanded lane picks that outcome without asking', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Show ended jobs' }).click();

  const job = openJob('interested');
  await fireDrop(page, page.getByTestId(`job-card-${job.id}`), page.getByTestId('ended-group-rejected'));

  await expect(page.getByRole('dialog', { name: /How did/ })).toHaveCount(0);
  await expect(page.getByText('Moved to Rejected')).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0].body).toEqual({ status: 'rejected' });
  await expect(page.getByTestId('ended-group-rejected').getByTestId(`job-card-${job.id}`)).toBeVisible();
});

test('the status select runs the same ending flow as a drop', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');

  const job = openJob('applied');
  const card = page.getByTestId(`job-card-${job.id}`);
  await selectStatus(page, card, job.title, 'stopped');

  await expect(page.getByText('Moved to Stopped')).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0].body).toEqual({ status: 'stopped' });
});

test('the status select asks before marking a job won', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');

  const job = openJob('offer');
  const card = page.getByTestId(`job-card-${job.id}`);
  await selectStatus(page, card, job.title, 'won');

  await expect(page.getByRole('alertdialog', { name: 'Mark as won' })).toBeVisible();
  expect(requests).toHaveLength(0);
});

test('an ended job can be dragged back to an open column, with Undo', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Show ended jobs' }).click();

  const ended = fixture.entries.find((entry) => entry.status === 'rejected');
  await fireDrop(page, page.getByTestId(`job-card-${ended.id}`), page.getByTestId('board-column-applied'));

  await expect(page.getByText('Moved to Applied')).toBeVisible();
  await expect(page.getByTestId('board-column-applied').getByTestId(`job-card-${ended.id}`)).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0].body).toEqual({ status: 'applied' });
  await expect(page.getByRole('button', { name: 'Undo', exact: true })).toBeVisible();
});

test('the reason popup saves a suggestion through the job PUT and the free text as a dated note', async ({ page }) => {
  const puts = await mockMove(page);
  const notes = await mockNoteWrites(page, '**/api/jobs/*/notes', { status: 201, body: { id: 'n1' } });
  await page.goto('/jobs');

  const job = openJob('applied');
  const card = page.getByTestId(`job-card-${job.id}`);
  await selectStatus(page, card, job.title, 'stopped');
  await page.getByRole('button', { name: 'Add a reason', exact: true }).click();

  const popup = page.getByRole('dialog', { name: 'Add a reason' });
  await expect(popup).toBeVisible();
  const suggestion = fixture.end_reasons.stopped[1];
  for (const option of fixture.end_reasons.stopped) {
    await expect(popup.getByRole('radio', { name: option })).toBeVisible();
  }
  await popup.getByRole('radio', { name: suggestion }).check();
  await popup.getByRole('textbox', { name: 'Anything else?' }).fill('They never called back.');
  await popup.getByRole('button', { name: 'Save', exact: true }).click();

  await expect(popup).toHaveCount(0);
  await expect(page.getByText('Reason saved')).toBeVisible();

  // The move, then the reason, both through the one job PUT.
  expect(puts.map((request) => request.body)).toEqual([{ status: 'stopped' }, { end_reason: suggestion }]);
  expect(notes).toHaveLength(1);
  expect(notes[0].method).toBe('POST');
  expect(notes[0].url).toContain(`/api/jobs/${job.id}/notes`);
  expect(notes[0].body).toEqual({ title: fixture.end_note_title, body: 'They never called back.' });

  // The ended card now says why.
  await page.getByRole('button', { name: 'Show ended jobs' }).click();
  await expect(page.getByTestId('ended-group-stopped').getByTestId(`job-card-${job.id}`).getByText(suggestion)).toBeVisible();
});

test('Skip saves nothing at all', async ({ page }) => {
  const puts = await mockMove(page);
  const notes = await mockNoteWrites(page, '**/api/jobs/*/notes', { status: 201, body: { id: 'n1' } });
  await page.goto('/jobs');

  const job = openJob('applied');
  await selectStatus(page, page.getByTestId(`job-card-${job.id}`), job.title, 'stopped');
  await page.getByRole('button', { name: 'Add a reason', exact: true }).click();

  const popup = page.getByRole('dialog', { name: 'Add a reason' });
  await popup.getByRole('radio', { name: fixture.end_reasons.stopped[0] }).check();
  await popup.getByRole('button', { name: 'Skip', exact: true }).click();

  await expect(popup).toHaveCount(0);
  expect(puts.map((request) => request.body)).toEqual([{ status: 'stopped' }]);
  expect(notes).toHaveLength(0);
});

test('an ended card with no reason opens the same popup, and Rejected offers its own suggestions', async ({ page }) => {
  const puts = await mockMove(page);
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Show ended jobs' }).click();

  const unexplained = fixture.entries.find((entry) => fixture.end_reasons[entry.status] && !entry.end_reason);

  await page.getByRole('button', { name: `Add a reason ${unexplained.title} ended` }).click();
  const popup = page.getByRole('dialog', { name: 'Add a reason' });
  for (const option of fixture.end_reasons[unexplained.status]) {
    await expect(popup.getByRole('radio', { name: option })).toBeVisible();
  }
  await popup.getByRole('radio', { name: fixture.end_reasons[unexplained.status][0] }).check();
  await popup.getByRole('button', { name: 'Save', exact: true }).click();

  expect(puts).toHaveLength(1);
  expect(puts[0].body).toEqual({ end_reason: fixture.end_reasons[unexplained.status][0] });

  // Reaching the rejected vocabulary through a real move, so the popup is
  // asserted to offer the rejected list and not some other outcome's: the
  // fixture's only rejected job already has a reason, so its "Add a reason"
  // entry point is gone and comparing fixture values to themselves would
  // prove nothing. The lane is still expanded from the click above.
  const job = openJob('interested');
  await fireDrop(page, page.getByTestId(`job-card-${job.id}`), page.getByTestId('ended-group-rejected'));
  await expect(page.getByText('Moved to Rejected')).toBeVisible();
  await page.getByRole('button', { name: 'Add a reason', exact: true }).click();
  const reasonPopup = page.getByRole('dialog', { name: 'Add a reason' });
  for (const option of fixture.end_reasons.rejected) {
    await expect(reasonPopup.getByRole('radio', { name: option })).toBeVisible();
  }
  for (const option of fixture.end_reasons.stopped) {
    await expect(reasonPopup.getByRole('radio', { name: option })).toHaveCount(0);
  }
});

test('a failed reason save keeps the popup open and says why', async ({ page }) => {
  await mockMove(page, { status: 400, body: { error: 'Invalid end_reason.' } });
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Show ended jobs' }).click();

  const unexplained = fixture.entries.find((entry) => fixture.end_reasons[entry.status] && !entry.end_reason);
  await page.getByRole('button', { name: `Add a reason ${unexplained.title} ended` }).click();
  const popup = page.getByRole('dialog', { name: 'Add a reason' });
  await popup.getByRole('radio', { name: fixture.end_reasons[unexplained.status][0] }).check();
  await popup.getByRole('button', { name: 'Save', exact: true }).click();

  await expect(popup).toBeVisible();
  await expect(popup.getByText('Invalid end_reason.')).toBeVisible();
});
