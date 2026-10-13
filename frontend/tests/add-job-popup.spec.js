import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard, mockIntake, mockPromote } from './helpers.js';

const fixture = loadBoardFixture();

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

function openPopup(page) {
  return page.getByRole('button', { name: 'Add a job', exact: true }).click();
}

function dialog(page) {
  return page.getByRole('dialog', { name: 'Add a job' });
}

test('the plus button opens the add-job popup with a link field, Cancel and Add job', async ({ page }) => {
  await page.goto('/jobs');
  await expect(dialog(page)).toHaveCount(0);

  await openPopup(page);
  const box = dialog(page);
  await expect(box).toBeVisible();
  await expect(box.getByRole('heading', { name: 'Add a job' })).toBeVisible();
  await expect(box.getByLabel('Posting link')).toHaveValue('');
  await expect(box.getByRole('button', { name: 'Add job', exact: true })).toBeDisabled();
  await expect(box.getByRole('button', { name: 'Cancel', exact: true })).toBeEnabled();

  await box.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(dialog(page)).toHaveCount(0);
});

test('Escape dismisses the popup, and reopening preserves the typed link', async ({ page }) => {
  await page.goto('/jobs');
  await openPopup(page);
  await dialog(page).getByLabel('Posting link').fill('https://example.com/careers/role');

  await page.keyboard.press('Escape');
  await expect(dialog(page)).toHaveCount(0);

  await openPopup(page);
  await expect(dialog(page).getByLabel('Posting link')).toHaveValue('https://example.com/careers/role');
});

test('a non-link value shows the field error and does not call the intake API', async ({ page }) => {
  const requests = await mockIntake(page, [{ body: { id: 'JOB-NEW', duplicate: false } }]);
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('not a link');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();

  await expect(box.getByText("This doesn't look like a link. Check it and try again.")).toBeVisible();
  await expect(box.getByRole('button', { name: 'Add job', exact: true })).toBeEnabled();
  expect(requests).toHaveLength(0);
});

test('submitting shows "Reading this posting" with the field disabled', async ({ page }) => {
  let release;
  const held = new Promise((resolve) => {
    release = resolve;
  });
  await page.route('**/api/jobs/intake', async (route) => {
    await held;
    route.fulfill({ status: 200, json: { id: 'JOB-NEW', duplicate: false } });
  });
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/role');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();

  await expect(box.getByText('Reading this posting')).toBeVisible();
  await expect(box.getByLabel('Posting link')).toBeDisabled();

  release();
  await expect(page.getByText('Added to New')).toBeVisible();
});

test('intake success closes the popup, clears the field, and toasts "Added to New"', async ({ page }) => {
  const requests = await mockIntake(page, [{ body: { id: 'JOB-NEW', duplicate: false } }]);
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/new-role');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();

  await expect(page.getByText('Added to New')).toBeVisible();
  await expect(dialog(page)).toHaveCount(0);
  expect(requests).toHaveLength(1);
  expect(requests[0].body).toEqual({ url: 'https://example.com/careers/new-role', origin: 'manual' });

  await openPopup(page);
  await expect(dialog(page).getByLabel('Posting link')).toHaveValue('');
});

test('a fetch failure shows the "couldn\'t read" error state with Try again, which resubmits the same URL', async ({
  page,
}) => {
  const requests = await mockIntake(page, [
    { status: 500, body: { error: 'Could not reach that posting.' } },
    { body: { id: 'JOB-NEW', duplicate: false } },
  ]);
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/flaky-role');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();

  await expect(box.getByText('Could not reach that posting.')).toBeVisible();
  const retry = box.getByRole('button', { name: 'Try again', exact: true });
  await expect(retry).toBeVisible();

  await retry.click();
  await expect(page.getByText('Added to New')).toBeVisible();

  expect(requests).toHaveLength(2);
  expect(requests[0].body).toEqual({ url: 'https://example.com/careers/flaky-role', origin: 'manual' });
  expect(requests[1].body).toEqual({ url: 'https://example.com/careers/flaky-role', origin: 'manual' });
});

test('a duplicate already on the board shows an info message with Show job, which navigates there', async ({ page }) => {
  const existingId = fixture.entries[0].id;
  await mockIntake(page, [
    {
      body: {
        duplicate: true,
        basis: 'same_url',
        existing: { id: existingId, title: fixture.entries[0].title, in_pipeline: true },
        actions: ['open_existing', 'add_anyway'],
      },
    },
  ]);
  await page.route(`**/jobs/${existingId}`, (route) =>
    route.fulfill({ status: 200, contentType: 'text/html', body: '<html><body>job detail stub</body></html>' }),
  );
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/dup');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();

  await expect(box.getByText(`"${fixture.entries[0].title}" is already on your board.`)).toBeVisible();
  await expect(page.getByText('Possible duplicate')).toHaveCount(0);

  await box.getByRole('button', { name: 'Show job', exact: true }).click();
  await page.waitForURL(`**/jobs/${existingId}`);
});

test('Add anyway from the duplicate state forces the create and toasts success', async ({ page }) => {
  const requests = await mockIntake(page, [
    {
      body: {
        duplicate: true,
        basis: 'same_url',
        existing: { id: fixture.entries[0].id, title: fixture.entries[0].title, in_pipeline: true },
        actions: ['open_existing', 'add_anyway'],
      },
    },
    { body: { id: 'JOB-NEW', duplicate: false } },
  ]);
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/dup');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();
  await expect(box.getByText('is already on your board.', { exact: false })).toBeVisible();

  await box.getByRole('button', { name: 'Add anyway', exact: true }).click();

  await expect(dialog(page)).toHaveCount(0);
  await expect(page.getByText('Added to New')).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1].body).toEqual({ url: 'https://example.com/careers/dup', force: true, origin: 'manual' });
});

test('editing the URL after a duplicate response resets the shown actions', async ({ page }) => {
  await mockIntake(page, [
    {
      body: {
        duplicate: true,
        basis: 'same_url',
        existing: { id: fixture.entries[0].id, title: fixture.entries[0].title, in_pipeline: true },
        actions: ['open_existing', 'add_anyway'],
      },
    },
  ]);
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/dup');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();
  await expect(box.getByText('is already on your board.', { exact: false })).toBeVisible();
  await expect(box.getByRole('button', { name: 'Show job', exact: true })).toBeVisible();
  await expect(box.getByRole('button', { name: 'Add anyway', exact: true })).toBeVisible();

  await box.getByLabel('Posting link').fill('https://example.com/careers/different-role');

  await expect(box.getByText('is already on your board.', { exact: false })).toHaveCount(0);
  await expect(box.getByRole('button', { name: 'Add anyway', exact: true })).toHaveCount(0);
  await expect(box.getByRole('button', { name: 'Add job', exact: true })).toBeEnabled();
});

test('editing the URL after a failed forced add clears the force flag on the next submit', async ({ page }) => {
  const requests = await mockIntake(page, [
    {
      body: {
        duplicate: true,
        basis: 'same_url',
        existing: { id: fixture.entries[0].id, title: fixture.entries[0].title, in_pipeline: true },
        actions: ['open_existing', 'add_anyway'],
      },
    },
    { status: 500, body: { error: 'Could not add that posting.' } },
    { body: { id: 'JOB-NEW', duplicate: false } },
  ]);
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/dup');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();
  await expect(box.getByText('is already on your board.', { exact: false })).toBeVisible();

  await box.getByRole('button', { name: 'Add anyway', exact: true }).click();
  await expect(box.getByText('Could not add that posting.')).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1].body).toEqual({ url: 'https://example.com/careers/dup', force: true, origin: 'manual' });

  await box.getByLabel('Posting link').fill('https://example.com/careers/dup-edited');
  await expect(box.getByText('Could not add that posting.')).toHaveCount(0);
  await box.getByRole('button', { name: 'Add job', exact: true }).click();

  await expect(page.getByText('Added to New')).toBeVisible();
  expect(requests).toHaveLength(3);
  expect(requests[2].body).toEqual({ url: 'https://example.com/careers/dup-edited', origin: 'manual' });
});

test('a real posting-read failure (201 with a failed ingest_state) keeps the popup open and retries via extract', async ({
  page,
}) => {
  const intakeRequests = await mockIntake(page, [
    {
      status: 201,
      body: {
        job: {
          id: 'JOB-NEW',
          ingest_state: 'fetch_failed',
          ingest_error: { stage: 'fetch', reason: 'ConnectionError', at: '2026-10-12T00:00:00Z' },
        },
        company: null,
      },
    },
  ]);
  const extractRequests = [];
  await page.route('**/api/jobs/*/extract', (route) => {
    extractRequests.push(route.request().url());
    route.fulfill({ status: 202, json: { id: 'JOB-NEW', llm_pending: true, accepted: true } });
  });
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/unreachable');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();

  // The HTTP request succeeded (201), but the saved job could not actually
  // be read, so this must show the popup's error state and keep it open,
  // not the "Added to New" success toast a bare response.ok check would give.
  await expect(box).toBeVisible();
  await expect(page.getByText('Added to New')).toHaveCount(0);
  const retry = box.getByRole('button', { name: 'Try again', exact: true });
  await expect(retry).toBeVisible();
  expect(intakeRequests).toHaveLength(1);

  await retry.click();

  await expect(dialog(page)).toHaveCount(0);
  await expect(page.getByText('Retry started')).toBeVisible();
  expect(extractRequests).toHaveLength(1);
  expect(extractRequests[0]).toContain('/api/jobs/JOB-NEW/extract');
  // The retry must hit the extraction endpoint for the saved record, never
  // a second intake call (which would just hit dedup against itself).
  expect(intakeRequests).toHaveLength(1);
});

test('a 503 (saved job, extraction could not start) keeps the popup open and retries via extract, not intake', async ({
  page,
}) => {
  const intakeRequests = await mockIntake(page, [
    {
      status: 503,
      body: {
        job: { id: 'JOB-NEW', ingest_state: 'extract_failed' },
        company: null,
        error: 'Could not start extraction.',
      },
    },
  ]);
  const extractRequests = [];
  await page.route('**/api/jobs/*/extract', (route) => {
    extractRequests.push(route.request().url());
    route.fulfill({ status: 202, json: { id: 'JOB-NEW', llm_pending: true, accepted: true } });
  });
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/no-worker');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();

  // The HTTP request failed (503), but the job was already saved, so this
  // must show the popup's error state and keep it open, not the generic
  // "failed" state whose retry would resubmit to intake and risk a
  // duplicate record once forced.
  await expect(box).toBeVisible();
  await expect(page.getByText('Added to New')).toHaveCount(0);
  const retry = box.getByRole('button', { name: 'Try again', exact: true });
  await expect(retry).toBeVisible();
  expect(intakeRequests).toHaveLength(1);

  await retry.click();

  await expect(dialog(page)).toHaveCount(0);
  await expect(page.getByText('Retry started')).toBeVisible();
  expect(extractRequests).toHaveLength(1);
  expect(extractRequests[0]).toContain('/api/jobs/JOB-NEW/extract');
  expect(intakeRequests).toHaveLength(1);
});

test('a forced-then-503 retry on the same URL does not resubmit intake a second time', async ({ page }) => {
  const intakeRequests = await mockIntake(page, [
    {
      body: {
        duplicate: true,
        basis: 'same_url',
        existing: { id: fixture.entries[0].id, title: fixture.entries[0].title, in_pipeline: true },
        actions: ['open_existing', 'add_anyway'],
      },
    },
    {
      status: 503,
      body: {
        job: { id: 'JOB-NEW', ingest_state: 'extract_failed' },
        company: null,
        error: 'Could not start extraction.',
      },
    },
  ]);
  const extractRequests = [];
  await page.route('**/api/jobs/*/extract', (route) => {
    extractRequests.push(route.request().url());
    route.fulfill({ status: 202, json: { id: 'JOB-NEW', llm_pending: true, accepted: true } });
  });
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/dup-no-worker');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();
  await expect(box.getByText('is already on your board.', { exact: false })).toBeVisible();

  await box.getByRole('button', { name: 'Add anyway', exact: true }).click();
  expect(intakeRequests).toHaveLength(2);

  const retry = box.getByRole('button', { name: 'Try again', exact: true });
  await expect(retry).toBeVisible();
  await retry.click();

  await expect(page.getByText('Retry started')).toBeVisible();
  expect(extractRequests).toHaveLength(1);
  // The forced attempt that hit the 503 still saved the stub, so the retry
  // must stay on the extraction endpoint and never resubmit intake, which
  // would create a second duplicate record.
  expect(intakeRequests).toHaveLength(2);
});

test('a failed "Add anyway" from the off-board duplicate dialog shows the popup error state, and retry preserves force', async ({
  page,
}) => {
  const existingId = fixture.entries[2].id;
  const requests = await mockIntake(page, [
    {
      body: {
        duplicate: true,
        basis: 'same_ats_posting_id',
        existing: { id: existingId, title: fixture.entries[2].title, in_pipeline: false },
        actions: ['promote', 'open_existing', 'add_anyway'],
      },
    },
    { status: 500, body: { error: 'Could not add that posting.' } },
    { body: { id: 'JOB-NEW', duplicate: false } },
  ]);
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/off-board-dup');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();

  await expect(dialog(page)).toHaveCount(0);
  await expect(page.getByText('Possible duplicate')).toBeVisible();

  await page.getByRole('button', { name: 'Add anyway', exact: true }).click();

  // Both dialogs must not silently vanish: the forced add runs through the
  // popup's own reading/error flow, so a failure is visible there.
  await expect(page.getByText('Possible duplicate')).toHaveCount(0);
  await expect(dialog(page)).toBeVisible();
  await expect(dialog(page).getByText('Could not add that posting.')).toBeVisible();

  await dialog(page).getByRole('button', { name: 'Try again', exact: true }).click();

  await expect(page.getByText('Added to New')).toBeVisible();
  expect(requests).toHaveLength(3);
  expect(requests[1].body).toEqual({ url: 'https://example.com/careers/off-board-dup', force: true, origin: 'manual' });
  expect(requests[2].body).toEqual({ url: 'https://example.com/careers/off-board-dup', force: true, origin: 'manual' });
});

test('a duplicate eligible for promotion closes the popup and opens the separate duplicate dialog', async ({ page }) => {
  const existingId = fixture.entries[2].id;
  await mockIntake(page, [
    {
      body: {
        duplicate: true,
        basis: 'same_ats_posting_id',
        existing: { id: existingId, title: fixture.entries[2].title, in_pipeline: false },
        actions: ['promote', 'open_existing', 'add_anyway'],
      },
    },
  ]);
  await mockPromote(page);
  await page.goto('/jobs');
  await openPopup(page);
  const box = dialog(page);
  await box.getByLabel('Posting link').fill('https://example.com/careers/dup');
  await box.getByRole('button', { name: 'Add job', exact: true }).click();

  await expect(dialog(page)).toHaveCount(0);
  await expect(page.getByText('Possible duplicate')).toBeVisible();
  const promote = page.getByRole('button', { name: 'Promote to pipeline', exact: true });
  await expect(promote).toBeVisible();

  await promote.click();
  await expect(page.getByText('Promoted to pipeline')).toBeVisible();
  await expect(page.getByText('Possible duplicate')).toHaveCount(0);
});
