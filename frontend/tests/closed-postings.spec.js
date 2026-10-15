// Protects the closed-postings banner and its review popup (D7), and that
// a card's closed chip and the banner read the one payload list, so the
// warning and the question can never disagree.
import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard, mockMove } from './helpers.js';

const fixture = loadBoardFixture();
const review = fixture.closed_review;
const asked = review.map((row) => fixture.entries.find((entry) => entry.id === row.id));

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('the banner counts the jobs whose posting has been gone over a week', async ({ page }) => {
  expect(review).toHaveLength(1);
  await page.goto('/jobs');

  const banner = page.getByTestId('closed-postings-banner');
  await expect(banner).toBeVisible();
  await expect(
    banner.getByText('1 job you have not applied to has had a closed posting for over a week.'),
  ).toBeVisible();
  await expect(banner.getByRole('button', { name: 'Review closed postings' })).toBeVisible();
  await expect(banner.getByRole('button', { name: 'Not now', exact: true })).toBeVisible();
});

test('no banner when the payload asks about nothing', async ({ page }) => {
  await mockBoard(page, { ...fixture, closed_review: [] });
  await page.goto('/jobs');
  await expect(page.getByTestId('job-card-JOB-001')).toBeVisible();
  await expect(page.getByTestId('closed-postings-banner')).toHaveCount(0);
});

// The warning chip and the banner are the same list. A job in Applied or
// later keeps the neutral chip however long its posting has been gone,
// because a closed posting does not end an application.
test('the warning chip is on the job the banner asks about, and other closed postings stay neutral', async ({ page }) => {
  await page.goto('/jobs');

  const warned = asked[0];
  const row = review[0];
  await expect(
    page.getByTestId(`job-card-${warned.id}`).getByText(`Closed ${row.days_closed} days ago`, { exact: true }),
  ).toBeVisible();

  const neutral = fixture.entries.filter((entry) => entry.closed && entry.id !== warned.id);
  expect(neutral.length).toBeGreaterThan(0);
  for (const entry of neutral) {
    const card = page.getByTestId(`job-card-${entry.id}`);
    await expect(card.getByText('Posting closed', { exact: true })).toBeVisible();
    await expect(card.getByText(/^Closed \d+ days? ago$/)).toHaveCount(0);
  }
  // One of those is a job in Applied whose posting has been gone far longer
  // than a week, which is exactly the case that must not warn.
  const applied = neutral.find((entry) => entry.status === 'applied');
  expect(applied).toBeTruthy();
});

test('Not now hides the banner until another job crosses the week', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByTestId('closed-postings-banner').getByRole('button', { name: 'Not now', exact: true }).click();
  await expect(page.getByTestId('closed-postings-banner')).toHaveCount(0);

  // Still hidden after a reload: the choice is remembered per job, not per
  // page load.
  await page.reload();
  await expect(page.getByTestId('job-card-JOB-001')).toBeVisible();
  await expect(page.getByTestId('closed-postings-banner')).toHaveCount(0);

  // A different job crossing the threshold brings the banner back.
  const another = fixture.entries.find((entry) => entry.status === 'new' && entry.closed);
  await mockBoard(page, {
    ...fixture,
    closed_review: [...review, { id: another.id, closed_at: another.closed_at, days_closed: 9 }],
  });
  await page.reload();
  await expect(page.getByTestId('closed-postings-banner')).toBeVisible();
});

test('Review lists each job with its company and day count, and Done closes', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Review closed postings' }).click();

  const popup = page.getByRole('dialog', { name: 'Closed postings' });
  await expect(popup).toBeVisible();
  for (const [index, job] of asked.entries()) {
    const row = popup.getByTestId(`closed-review-row-${job.id}`);
    await expect(row.getByText(job.title, { exact: true })).toBeVisible();
    const company = job.company_name || 'Company pending';
    await expect(row.getByText(`${company}, closed ${review[index].days_closed} days ago`)).toBeVisible();
    await expect(row.getByRole('button', { name: `Keep ${job.title}` })).toBeVisible();
    await expect(row.getByRole('button', { name: `Stop ${job.title}` })).toBeVisible();
  }

  await popup.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(popup).toHaveCount(0);
});

test('Keep marks the job reviewed, drops its row and the banner, and turns the chip neutral', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Review closed postings' }).click();

  const job = asked[0];
  const popup = page.getByRole('dialog', { name: 'Closed postings' });
  await popup.getByRole('button', { name: `Keep ${job.title}` }).click();

  await expect(popup.getByTestId(`closed-review-row-${job.id}`)).toHaveCount(0);
  await expect(popup.getByText('Nothing left to review.')).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0].method).toBe('PUT');
  expect(Object.keys(requests[0].body)).toEqual(['closed_reviewed_at']);
  expect(requests[0].body.closed_reviewed_at).toMatch(/^\d{4}-\d{2}-\d{2}$/);

  await popup.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(page.getByTestId('closed-postings-banner')).toHaveCount(0);

  // The posting is still gone, so the card still says so, just without the
  // warning: Keep quiets the question, it does not clear the flag.
  const card = page.getByTestId(`job-card-${job.id}`);
  await expect(card.getByText('Posting closed', { exact: true })).toBeVisible();
  await expect(card.getByText(/^Closed \d+ days? ago$/)).toHaveCount(0);
});

test('a failed Keep puts the row back and says so', async ({ page }) => {
  await mockMove(page, { status: 500, body: { error: 'nope' } });
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Review closed postings' }).click();

  const job = asked[0];
  const popup = page.getByRole('dialog', { name: 'Closed postings' });
  await popup.getByRole('button', { name: `Keep ${job.title}` }).click();

  await expect(popup.getByTestId(`closed-review-row-${job.id}`)).toBeVisible();
  await expect(page.getByText('nope')).toBeVisible();
});

test('a failed Stop puts the row back with its day count and the chip keeps warning', async ({ page }) => {
  // Regression: Stop used to drop the review row optimistically and the
  // failed-write rollback never restored it, so a job the owner never ended
  // vanished from the question.
  await mockMove(page, { status: 500, body: { error: 'nope' } });
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Review closed postings' }).click();

  const job = asked[0];
  const row = review[0];
  const popup = page.getByRole('dialog', { name: 'Closed postings' });
  await popup.getByRole('button', { name: `Stop ${job.title}` }).click();

  const restored = popup.getByTestId(`closed-review-row-${job.id}`);
  await expect(restored).toBeVisible();
  await expect(restored.getByText(`closed ${row.days_closed} days ago`)).toBeVisible();
  // Stop rides on moveJobStatus, whose fixed message the board specs pin
  // (unlike Keep's updateJob, which surfaces the server's own error).
  await expect(page.getByText('Status update failed.')).toBeVisible();

  await popup.getByRole('button', { name: 'Done', exact: true }).click();
  const card = page.getByTestId(`job-card-${job.id}`);
  await expect(card.getByText(`Closed ${row.days_closed} days ago`, { exact: true })).toBeVisible();
});

test('Stop moves the job to Stopped with the Posting closed reason, in one write', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Review closed postings' }).click();

  const job = asked[0];
  const popup = page.getByRole('dialog', { name: 'Closed postings' });
  await popup.getByRole('button', { name: `Stop ${job.title}` }).click();

  expect(requests).toHaveLength(1);
  expect(requests[0].body).toEqual({ status: 'stopped', end_reason: 'Posting closed' });
  await expect(popup.getByTestId(`closed-review-row-${job.id}`)).toHaveCount(0);

  await popup.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(page.getByText('Moved to Stopped')).toBeVisible();
  await page.getByRole('button', { name: 'Show ended jobs' }).click();
  const card = page.getByTestId('ended-group-stopped').getByTestId(`job-card-${job.id}`);
  await expect(card).toBeVisible();
  await expect(card.getByText('Posting closed', { exact: true })).toBeVisible();
});

test('Undo after Stop brings the review row back and reverts with the status alone', async ({ page }) => {
  // Regression: Undo used to clear the extra fields on the card locally
  // while the server kept them (end_reason in the vault, no reason on the
  // card), and the review row stayed gone even though the job was back
  // before Applied, closed and unkept.
  const requests = await mockMove(page);
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Review closed postings' }).click();

  const job = asked[0];
  const row = review[0];
  const popup = page.getByRole('dialog', { name: 'Closed postings' });
  await popup.getByRole('button', { name: `Stop ${job.title}` }).click();
  await popup.getByRole('button', { name: 'Done', exact: true }).click();

  await expect(page.getByText('Moved to Stopped')).toBeVisible();
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByText('Moved to Stopped')).toHaveCount(0);

  expect(requests).toHaveLength(2);
  // The documented policy: an undone ending keeps its reason on the
  // record, so the Undo PUT reverts the status and sends no field
  // reverts.
  expect(requests[1].body.status).toBe(job.status);
  expect(Object.keys(requests[1].body)).toEqual(['status']);

  // The question the banner asked comes back, with its day count intact.
  await expect(page.getByTestId('closed-postings-banner')).toBeVisible();
  await page.getByRole('button', { name: 'Review closed postings' }).click();
  const restored = page.getByRole('dialog', { name: 'Closed postings' })
    .getByTestId(`closed-review-row-${job.id}`);
  await expect(restored).toBeVisible();
  await expect(restored.getByText(`closed ${row.days_closed} days ago`)).toBeVisible();
});
