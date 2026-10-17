// Protects CAREER-37: the board says where a job's AI reading stands, and
// it keeps asking only while a reading is owed.
import { expect, test } from '@playwright/test';
import { loadBoardFixture, loadFixture, mockBoard, mockJobPage, mockRetry } from './helpers.js';

const fixture = loadBoardFixture();
const openEntries = fixture.entries.filter((entry) => !fixture.ended_statuses.includes(entry.status));

// One board payload with the first open job's reading in the given state.
// Everything else is the D7 fixture untouched, so a chip can only come
// from the field under test.
function boardWith(ai) {
  const target = openEntries[0];
  return {
    ...fixture,
    entries: fixture.entries.map((entry) => (entry.id === target.id ? { ...entry, ...ai } : entry)),
  };
}

const target = openEntries[0];

test('a queued reading shows the pending chip on its own card', async ({ page }) => {
  await mockBoard(page, boardWith({ ai_status: 'queued', ai_error: null }));
  await page.goto('/jobs');
  const card = page.getByTestId(`job-card-${target.id}`);
  await expect(card.getByText('Enrichment pending', { exact: true })).toBeVisible();
});

test('a running reading shows the filling-in chip, not the queued one', async ({ page }) => {
  await mockBoard(page, boardWith({ ai_status: 'running', ai_error: null }));
  await page.goto('/jobs');
  const card = page.getByTestId(`job-card-${target.id}`);
  await expect(card.getByText('Details filling in…', { exact: true })).toBeVisible();
  // The two in-flight states are told apart, which is what the owner is
  // reading the chip for. The motion beside this one is a visual detail
  // the click-test covers.
  await expect(card.getByText('Enrichment pending', { exact: true })).toHaveCount(0);
});

test('a failed reading shows its reason and offers Retry', async ({ page }) => {
  await mockBoard(page, boardWith({ ai_status: 'failed', ai_error: 'Could not reach the reader. Try again.' }));
  const retries = await mockRetry(page);
  await page.goto('/jobs');
  const card = page.getByTestId(`job-card-${target.id}`);
  await expect(card.getByText('Could not reach the reader. Try again.', { exact: false })).toBeVisible();
  await card.getByRole('button', { name: 'Retry' }).click();
  await expect.poll(() => retries.length).toBeGreaterThan(0);
  expect(retries[0]).toContain(`/api/jobs/${target.id}/extract`);
});

test('a finished reading adds no chip of its own', async ({ page }) => {
  await mockBoard(page, boardWith({ ai_status: 'done', ai_error: null, enriched: true }));
  await page.goto('/jobs');
  const card = page.getByTestId(`job-card-${target.id}`);
  await expect(card.getByText('Enrichment pending', { exact: true })).toHaveCount(0);
  await expect(card.getByText('Details filling in…', { exact: true })).toHaveCount(0);
  await expect(card.getByText('Extraction failed', { exact: false })).toHaveCount(0);
});

test('the board keeps asking while a reading is owed and stops once it lands', async ({ page }) => {
  const running = boardWith({ ai_status: 'running', ai_error: null });
  const settled = boardWith({ ai_status: 'done', ai_error: null, enriched: true });
  let served = 0;
  await page.route('**/api/jobs?view=board', (route) => {
    served += 1;
    // The first two loads are still reading; from the third the reading
    // has landed, which is what has to end the polling.
    route.fulfill({ json: served < 3 ? running : settled });
  });
  await page.goto('/jobs');
  await expect.poll(() => served, { timeout: 20000 }).toBeGreaterThanOrEqual(3);
  const afterSettled = served;
  // Two polling intervals' worth of waiting with nothing owed: no further
  // request may arrive.
  await page.waitForTimeout(11000);
  expect(served).toBe(afterSettled);
});

test('one failed poll does not end the polling', async ({ page }) => {
  // Fix round C4: the polling effect re-armed on the board alone, and a
  // failed ask leaves the board exactly as it was, so one bad response
  // stopped the polling for the life of the page and the chip stayed on
  // "filling in" forever. The ask has to come back on the next interval.
  const running = boardWith({ ai_status: 'running', ai_error: null });
  const settled = boardWith({ ai_status: 'done', ai_error: null, enriched: true });
  // Driven by the test rather than by a request count: the dev server
  // mounts the page twice (StrictMode), so which ask is the first poll is
  // not something a count can say.
  let mode = 'running';
  let served = 0;
  await page.route('**/api/jobs?view=board', (route) => {
    served += 1;
    if (mode === 'fail') {
      mode = 'settled';
      route.fulfill({ status: 500, json: { error: 'Server error.' } });
      return;
    }
    route.fulfill({ json: mode === 'settled' ? settled : running });
  });
  await page.goto('/jobs');
  const card = page.getByTestId(`job-card-${target.id}`);
  await expect(card.getByText('Details filling in…', { exact: true })).toBeVisible();

  const beforeFailure = served;
  mode = 'fail';
  // The failure is a visible state with a Retry, per the product rules,
  // and it is not the end of the polling: the next tick asks again.
  await expect(page.getByText('Could not load the jobs board.', { exact: true })).toBeVisible({ timeout: 20000 });
  await expect.poll(() => served, { timeout: 30000 }).toBeGreaterThan(beforeFailure + 1);
  // The board is back, which is the recovery itself: the ask that
  // followed the failed one landed, and its answer is on screen.
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card.getByText('Details filling in…', { exact: true })).toHaveCount(0);
  // And it stops once the reading has landed, exactly as before: the
  // recovered poll must not have left a second timer running.
  const afterSettled = served;
  await page.waitForTimeout(11000);
  expect(served).toBe(afterSettled);
});

test('the job page shows the reading state in the extraction row', async ({ page }) => {
  const detail = loadFixture('job-detail');
  await mockJobPage(page, {
    ...detail,
    job: { ...detail.job, ai_status: 'failed', ai_error: 'Unable to fetch and parse posting.' },
  });
  await page.goto(`/jobs/${detail.job.id}`);
  await expect(page.getByText('Unable to fetch and parse posting.', { exact: false })).toBeVisible();
});
