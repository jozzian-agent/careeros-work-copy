import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard, mockMove, mockRetry, selectStatus } from './helpers.js';

const fixture = loadBoardFixture();

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('board columns render, one per status, with baseline card count', async ({ page }) => {
  await page.goto('/jobs');
  for (const status of fixture.statuses) {
    const label = status.charAt(0).toUpperCase() + status.slice(1);
    await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible();
  }
  const cardTitles = fixture.entries.map((entry) => entry.title);
  for (const title of cardTitles) {
    await expect(page.getByText(title, { exact: true })).toBeVisible();
  }
  // At least one status has no entries in the fixture (withdrawn); its
  // column still renders, just with a zero count chip, never missing.
  const unusedStatus = fixture.statuses.find((status) => !fixture.entries.some((entry) => entry.status === status));
  expect(unusedStatus).toBeTruthy();
  await expect(page.getByTestId(`board-column-${unusedStatus}`).getByText('0', { exact: true })).toBeVisible();
});

test('list view switch shows the same entries in a table', async ({ page }) => {
  await page.goto('/jobs');
  await expect(page.getByRole('table')).toHaveCount(0);
  await page.getByRole('button', { name: 'List', exact: true }).click();
  await expect(page.getByRole('button', { name: 'List', exact: true })).toHaveAttribute('aria-pressed', 'true');
  const table = page.getByRole('table');
  await expect(table).toBeVisible();
  await expect(table.getByRole('row')).toHaveCount(fixture.entries.length + 1); // +1 header row
});

test('needs attention toggle filters to needs_attention entries and back', async ({ page }) => {
  await page.goto('/jobs');
  const toggle = page.getByRole('button', { name: 'Needs attention', exact: true });
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');

  const baselineCount = fixture.entries.length;
  const needsAttentionTitles = fixture.entries.filter((entry) => entry.needs_attention).map((entry) => entry.title);
  const notNeedsAttentionTitles = fixture.entries.filter((entry) => !entry.needs_attention).map((entry) => entry.title);
  expect(needsAttentionTitles.length).toBeGreaterThan(0);
  expect(needsAttentionTitles.length).toBeLessThan(baselineCount);

  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  for (const title of needsAttentionTitles) {
    await expect(page.getByText(title, { exact: true })).toBeVisible();
  }
  for (const title of notNeedsAttentionTitles) {
    await expect(page.getByText(title, { exact: true })).toHaveCount(0);
  }

  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  for (const title of notNeedsAttentionTitles) {
    await expect(page.getByText(title, { exact: true })).toBeVisible();
  }
});

// The Function chip's own filtering behaviour (and Fit/Location/Industry/
// Company size/Clear all/result count) moved to tests/filter-bar.spec.js
// with the JOZ-279 filter bar rebuild; it is no longer a SelectList here.

test('empty state renders the empty message from the API', async ({ page }) => {
  const emptyBoard = { ...fixture, entries: [], empty: 'No jobs match this test fixture.' };
  await mockBoard(page, emptyBoard);
  await page.goto('/jobs');
  await expect(page.getByText('No jobs match this test fixture.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry' })).toHaveCount(0);
});

// Per-record scoped assertions: each fixture entry gets its own test, and
// every assertion is scoped to that card's own testid, never page-wide, so
// a dropped field on one card cannot hide behind another card's content.
for (const entry of fixture.entries) {
  test(`board card ${entry.id} reflects every fixture field for "${entry.title}"`, async ({ page }) => {
    await page.goto('/jobs');
    const card = page.getByTestId(`job-card-${entry.id}`);
    await expect(card).toBeVisible();

    await expect(card.getByRole('link', { name: entry.title, exact: true })).toHaveAttribute(
      'href',
      `/jobs/${entry.id}`,
    );

    if (entry.company_link_state === 'needs_review') {
      await expect(card.getByText('Needs your input')).toBeVisible();
      await expect(card.getByText('Company: pending')).toHaveCount(0);
      if (entry.company_name && entry.company_id) {
        await expect(card.getByRole('link', { name: entry.company_name, exact: true })).toHaveAttribute(
          'href',
          `/companies/${entry.company_id}`,
        );
      }
    } else if (entry.company_name && entry.company_id) {
      await expect(card.getByRole('link', { name: entry.company_name, exact: true })).toHaveAttribute(
        'href',
        `/companies/${entry.company_id}`,
      );
      await expect(card.getByText('Company: pending')).toHaveCount(0);
      await expect(card.getByText('Needs your input')).toHaveCount(0);
    } else {
      await expect(card.getByText('Company: pending')).toBeVisible();
      await expect(card.getByText('Needs your input')).toHaveCount(0);
    }

    await expect(card.getByText(`added ${entry.added}`, { exact: false })).toBeVisible();

    if (entry.posted_date) {
      await expect(card.getByText(`Posted ${entry.posted_date}`, { exact: true })).toBeVisible();
    } else {
      await expect(card.getByText(/^Posted /)).toHaveCount(0);
    }

    await expect(card.getByText(entry.source, { exact: true })).toBeVisible();

    if (entry.salary_info) {
      await expect(card.getByText('Salary disclosed')).toBeVisible();
    } else {
      await expect(card.getByText('Salary disclosed')).toHaveCount(0);
    }

    if (entry.summary_source === 'ai') {
      await expect(card.getByText('AI-generated')).toBeVisible();
    } else {
      await expect(card.getByText('AI-generated')).toHaveCount(0);
    }

    for (const [functionId, label] of fixture.function_options) {
      if (entry.function.includes(functionId)) {
        await expect(card.getByText(label, { exact: true })).toBeVisible();
      }
    }

    if (entry.ingest_state === 'fetch_failed' || entry.ingest_state === 'extract_failed') {
      await expect(card.getByText(entry.ingest_error.reason, { exact: false })).toBeVisible();
      await expect(card.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
    } else {
      await expect(card.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0);
    }

    if (!entry.enriched && ['stub', 'fetched'].includes(entry.ingest_state)) {
      await expect(card.getByText('Details filling in…')).toBeVisible();
    }
  });
}

test('a tentative company_name + company_id alongside needs_review renders both the link and the review chip', async ({ page }) => {
  const tentative = fixture.entries.find(
    (entry) => entry.company_link_state === 'needs_review' && entry.company_name && entry.company_id,
  );
  expect(tentative).toBeTruthy();

  await page.goto('/jobs');
  const card = page.getByTestId(`job-card-${tentative.id}`);
  await expect(card.getByRole('link', { name: tentative.company_name, exact: true })).toHaveAttribute(
    'href',
    `/companies/${tentative.company_id}`,
  );
  await expect(card.getByText('Needs your input')).toBeVisible();
  await expect(card.getByText('Company: pending')).toHaveCount(0);
});

test('list view links point job titles at /jobs/<id> and company names at /companies/<id>', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'List', exact: true }).click();

  const linked = fixture.entries.find((entry) => entry.company_name && entry.company_id);
  const linkedRow = page.locator('tr', { hasText: linked.title });
  await expect(linkedRow.getByRole('link', { name: linked.title, exact: true })).toHaveAttribute(
    'href',
    `/jobs/${linked.id}`,
  );
  await expect(linkedRow.getByRole('link', { name: linked.company_name, exact: true })).toHaveAttribute(
    'href',
    `/companies/${linked.company_id}`,
  );

  const needsReview = fixture.entries.find((entry) => entry.company_link_state === 'needs_review');
  const reviewRow = page.locator('tr', { hasText: needsReview.title });
  await expect(reviewRow.getByText('Needs your input')).toBeVisible();
});

test('list rows show ingest failure, reason, and Retry like board cards', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'List', exact: true }).click();

  const failed = fixture.entries.find((entry) => ['fetch_failed', 'extract_failed'].includes(entry.ingest_state));
  const row = page.locator('tr', { hasText: failed.title });
  await expect(row.getByText(failed.ingest_error.reason, { exact: false })).toBeVisible();
  await expect(row.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
});

test('list rows render on a mobile viewport (390x844), not just the sort select', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'List', exact: true }).click();

  await expect(page.getByLabel('Sort by')).toBeVisible();
  const table = page.getByRole('table');
  await expect(table).toBeVisible();
  await expect(table.getByRole('row')).toHaveCount(fixture.entries.length + 1);
  for (const entry of fixture.entries) {
    await expect(page.locator('tr', { hasText: entry.title })).toBeVisible();
  }
});

test('list header cells expose aria-sort through the adapter', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'List', exact: true }).click();

  const titleHeader = page.locator('th', { hasText: 'Title' });
  const companyHeader = page.locator('th', { hasText: 'Company' });
  await expect(titleHeader).toHaveAttribute('aria-sort', 'none');
  await expect(companyHeader).toHaveAttribute('aria-sort', 'none');

  await titleHeader.getByText('Title', { exact: true }).click();
  await expect(titleHeader).toHaveAttribute('aria-sort', 'ascending');

  await titleHeader.getByText('Title', { exact: true }).click();
  await expect(titleHeader).toHaveAttribute('aria-sort', 'descending');

  await companyHeader.getByText('Company', { exact: true }).click();
  await expect(companyHeader).toHaveAttribute('aria-sort', 'ascending');
  await expect(titleHeader).toHaveAttribute('aria-sort', 'none');
});

test('status select move updates the board, toasts success, and sends the correct method/payload', async ({ page }) => {
  const requests = await mockMove(page);
  await page.goto('/jobs');

  const moved = fixture.entries.find((entry) => entry.status === 'applied');
  const card = page.getByTestId(`job-card-${moved.id}`);
  await selectStatus(page, card, moved.title, 'interviewing');

  await expect(page.getByTestId('board-column-interviewing').getByTestId(`job-card-${moved.id}`)).toBeVisible();
  await expect(page.getByText('Moved to Interviewing')).toBeVisible();

  expect(requests).toHaveLength(1);
  expect(requests[0].method).toBe('PUT');
  expect(requests[0].body).toEqual({ status: 'interviewing' });
});

test('status select failure reverts the move and toasts the error', async ({ page }) => {
  const requests = await mockMove(page, { status: 500, body: { error: 'nope' } });
  await page.goto('/jobs');

  const moved = fixture.entries.find((entry) => entry.status === 'applied');
  const card = page.getByTestId(`job-card-${moved.id}`);
  await selectStatus(page, card, moved.title, 'interviewing');

  await expect(page.getByText('Status update failed.')).toBeVisible();
  await expect(page.getByTestId(`board-column-${moved.status}`).getByTestId(`job-card-${moved.id}`)).toBeVisible();

  expect(requests).toHaveLength(1);
  expect(requests[0].method).toBe('PUT');
  expect(requests[0].body).toEqual({ status: 'interviewing' });
});

test('an older failed move does not overwrite a newer successful move on the same job (overlapping requests)', async ({
  page,
}) => {
  const moved = fixture.entries.find((entry) => entry.status === 'new');
  let releaseFirst;
  const firstHeld = new Promise((resolve) => {
    releaseFirst = resolve;
  });
  await page.route(`**/api/jobs/${moved.id}`, async (route) => {
    if (route.request().method() !== 'PUT') {
      route.fallback();
      return;
    }
    const payload = route.request().postDataJSON();
    if (payload.status === 'interested') {
      // This is the OLDER request: hold it until the newer one below has
      // already resolved successfully, then fail it.
      await firstHeld;
      await route.fulfill({ status: 500, json: { error: 'nope' } });
    } else {
      await route.fulfill({ status: 200, json: { ok: true } });
      releaseFirst();
    }
  });
  await page.goto('/jobs');

  const card = page.getByTestId(`job-card-${moved.id}`);
  await selectStatus(page, card, moved.title, 'interested');
  // Wait for the first move's optimistic update to commit before firing the
  // second, so the two requests are deterministically ordered (older sent
  // first, held; newer sent second, resolves first) instead of racing on
  // React's own commit timing.
  await expect(page.getByTestId('board-column-interested').getByTestId(`job-card-${moved.id}`)).toBeVisible();
  await selectStatus(page, card, moved.title, 'applied');

  await expect(page.getByTestId('board-column-applied').getByTestId(`job-card-${moved.id}`)).toBeVisible();
  await expect(page.getByText('Status update failed.')).toBeVisible();
  // The stale failure for the superseded "interested" move must not have
  // rolled the card back to "new" or "interested".
  await expect(page.getByTestId('board-column-new').getByTestId(`job-card-${moved.id}`)).toHaveCount(0);
  await expect(page.getByTestId('board-column-interested').getByTestId(`job-card-${moved.id}`)).toHaveCount(0);
});

test('drag-and-drop moves a card between columns through the same handler as the select', async ({ page }) => {
  await mockMove(page);
  await page.goto('/jobs');

  const moved = fixture.entries.find((entry) => entry.status === 'new');
  const card = page.getByTestId(`job-card-${moved.id}`);
  const target = page.getByTestId('board-column-interested');
  await card.dragTo(target);

  await expect(page.getByTestId('board-column-interested').getByTestId(`job-card-${moved.id}`)).toBeVisible();
  await expect(page.getByText('Moved to Interested')).toBeVisible();
});

test('drag-and-drop failure reverts the card to its origin column and toasts the error', async ({ page }) => {
  await mockMove(page, { status: 500, body: { error: 'nope' } });
  await page.goto('/jobs');

  const moved = fixture.entries.find((entry) => entry.status === 'new');
  const card = page.getByTestId(`job-card-${moved.id}`);
  const origin = page.getByTestId(`board-column-${moved.status}`);
  const target = page.getByTestId('board-column-interested');
  await card.dragTo(target);

  await expect(page.getByText('Status update failed.')).toBeVisible();
  await expect(origin.getByTestId(`job-card-${moved.id}`)).toBeVisible();
});

test('ingest Retry on a card re-fetches the board and toasts success', async ({ page }) => {
  await mockRetry(page);
  await page.goto('/jobs');

  const failed = fixture.entries.find((entry) => entry.ingest_state === 'fetch_failed');
  const card = page.getByTestId(`job-card-${failed.id}`);
  await card.getByRole('button', { name: 'Retry', exact: true }).click();

  await expect(page.getByText('Retry started')).toBeVisible();
});

test('Board/List view and Needs attention persist across reload via localStorage', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'List', exact: true }).click();
  await page.getByRole('button', { name: 'Needs attention', exact: true }).click();

  await page.reload();

  await expect(page.getByRole('button', { name: 'List', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Board', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('button', { name: 'Needs attention', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByRole('table')).toBeVisible();
});

// Baseline-relative, not an exact count: React StrictMode (main.jsx) double-
// invokes mount effects in dev, so the initial load may already fire more
// than once before the test ever touches visibility/pageshow.
test('auto-refreshes when the tab regains focus after more than 30s hidden', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-01-01T00:00:00Z') });
  let fetchCount = 0;
  await page.route('**/api/jobs?view=board', (route) => {
    fetchCount += 1;
    route.fulfill({ json: fixture });
  });

  await page.goto('/jobs');
  await expect(page.getByText(fixture.entries[0].title, { exact: true })).toBeVisible();
  const baseline = fetchCount;

  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.fastForward(35000);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    document.dispatchEvent(new Event('visibilitychange'));
  });

  await expect.poll(() => fetchCount).toBeGreaterThan(baseline);
});

test('does not refresh when the tab regains focus after less than 30s hidden', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-01-01T00:00:00Z') });
  let fetchCount = 0;
  await page.route('**/api/jobs?view=board', (route) => {
    fetchCount += 1;
    route.fulfill({ json: fixture });
  });

  await page.goto('/jobs');
  await expect(page.getByText(fixture.entries[0].title, { exact: true })).toBeVisible();
  const baseline = fetchCount;

  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.fastForward(5000);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    document.dispatchEvent(new Event('visibilitychange'));
  });

  await page.waitForTimeout(200);
  expect(fetchCount).toBe(baseline);
});

test('auto-refreshes on pageshow with persisted (bfcache) restore', async ({ page }) => {
  let fetchCount = 0;
  await page.route('**/api/jobs?view=board', (route) => {
    fetchCount += 1;
    route.fulfill({ json: fixture });
  });

  await page.goto('/jobs');
  await expect(page.getByText(fixture.entries[0].title, { exact: true })).toBeVisible();
  const baseline = fetchCount;

  await page.evaluate(() => {
    window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
  });

  await expect.poll(() => fetchCount).toBeGreaterThan(baseline);
});

// The failure is forced on a *background* refresh (pageshow restore), well
// after the initial mount settled, so this is immune to StrictMode's
// double-invoked mount effect: there is nothing racing the assertion.
test('load failure (including background refresh) shows the error with a Retry that recovers', async ({ page }) => {
  let fail = false;
  await page.route('**/api/jobs?view=board', (route) => {
    if (fail) {
      route.fulfill({ status: 500, json: { error: 'down' } });
      return;
    }
    route.fulfill({ json: fixture });
  });

  await page.goto('/jobs');
  await expect(page.getByText(fixture.entries[0].title, { exact: true })).toBeVisible();

  fail = true;
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));

  await expect(page.getByText('Could not load the jobs board.')).toBeVisible();
  const retry = page.getByRole('button', { name: 'Retry', exact: true });
  await expect(retry).toBeVisible();

  fail = false;
  await retry.click();
  await expect(page.getByText(fixture.entries[0].title, { exact: true })).toBeVisible();
});

// Intake (success, failure+retry, duplicate "already on your board" and
// "eligible for promotion", Add anyway) moved to tests/add-job-popup.spec.js
// with the JOZ-279 popup rebuild: the inline "Posting URL" field and the
// unconditional duplicate dialog these tests drove no longer exist.
