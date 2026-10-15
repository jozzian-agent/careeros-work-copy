// Protects the phone layout (D7): below 720px the board shows one column
// at a time, picked from a chip row with Ended last, nothing is dragged,
// and a job can still be ended through the status select.
import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard, mockMove, selectStatus } from './helpers.js';

const fixture = loadBoardFixture();
const openStatuses = fixture.statuses.filter((status) => !fixture.ended_statuses.includes(status));

test.use({ viewport: { width: 390, height: 844 } });

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('one column at a time, with a status chip per column and Ended last', async ({ page }) => {
  await page.goto('/jobs');

  const chips = page.locator('[data-testid^="status-chip-"]');
  await expect(chips).toHaveCount(openStatuses.length + 1);
  const testIds = await chips.evaluateAll((nodes) => nodes.map((node) => node.dataset.testid));
  expect(testIds).toEqual([...openStatuses.map((status) => `status-chip-${status}`), 'status-chip-ended']);

  // New is the column showing, and no other column is on the page.
  await expect(page.getByTestId('board-column-new')).toBeVisible();
  for (const status of openStatuses.slice(1)) {
    await expect(page.getByTestId(`board-column-${status}`)).toHaveCount(0);
  }
  await expect(page.getByTestId('status-chip-new')).toHaveAttribute('aria-pressed', 'true');
});

test('a chip switches which column shows', async ({ page }) => {
  await page.goto('/jobs');

  await page.getByTestId('status-chip-applied').click();
  await expect(page.getByTestId('board-column-applied')).toBeVisible();
  await expect(page.getByTestId('board-column-new')).toHaveCount(0);

  const applied = fixture.entries.find((entry) => entry.status === 'applied');
  await expect(page.getByTestId(`job-card-${applied.id}`)).toBeVisible();
});

test('the Ended chip shows the lane, already open and with no Show button', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByTestId('status-chip-ended').click();

  const lane = page.getByTestId('ended-lane');
  await expect(lane).toBeVisible();
  await expect(page.getByTestId('ended-lane-collapsed')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Show ended jobs' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Hide ended jobs' })).toHaveCount(0);
  await expect(page.getByTestId('search-so-far')).toBeVisible();

  const ended = fixture.entries.find((entry) => entry.status === 'stopped');
  await expect(lane.getByTestId(`job-card-${ended.id}`)).toBeVisible();
});

test('no card is draggable and an empty column does not invite a drag', async ({ page }) => {
  await page.goto('/jobs');

  const card = page.getByTestId('job-card-JOB-001');
  await expect(card).toHaveAttribute('draggable', 'false');

  await page.getByTestId('status-chip-interviewing').click();
  const column = page.getByTestId('board-column-interviewing');
  await expect(column.getByText('No jobs here yet.', { exact: true })).toBeVisible();
  await expect(column.getByText('Drag a job here')).toHaveCount(0);
});

test('a job is ended through the status select, which runs the same flow', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');

  await page.getByTestId('status-chip-applied').click();
  const job = fixture.entries.find((entry) => entry.status === 'applied');
  await selectStatus(page, page.getByTestId(`job-card-${job.id}`), job.title, 'stopped');

  await expect(page.getByText('Moved to Stopped')).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0].body).toEqual({ status: 'stopped' });

  // And it is in the lane now, reached through the Ended chip.
  await page.getByTestId('status-chip-ended').click();
  await expect(page.getByTestId('ended-group-stopped').getByTestId(`job-card-${job.id}`)).toBeVisible();
});

test('the banner shortens on a phone', async ({ page }) => {
  await page.goto('/jobs');
  const banner = page.getByTestId('closed-postings-banner');
  await expect(banner.getByText('1 closed posting to review')).toBeVisible();
  await expect(banner.getByText(/have had a closed posting/)).toHaveCount(0);
});

test('every popup opens as a full-width sheet', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Add a job', exact: true }).click();

  const sheet = page.getByRole('dialog');
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole('heading', { name: 'Add a job' })).toBeVisible();
  // A sheet, not a modal card: Gestalt's mobile adaptation gives the
  // popup its own dismiss control in the sheet header, which the desktop
  // Modal does not have.
  await expect(sheet.getByRole('button', { name: 'Dismiss bottom sheet' })).toBeVisible();
  const box = await sheet.boundingBox();
  expect(box.width).toBe(390);
});
