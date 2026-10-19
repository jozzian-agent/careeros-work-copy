// Protects the All jobs tab (B2, CAREER-89): every job that is not
// private to another user, each card either showing the status it has on
// my board or offering "Add to my jobs", the board's own filter bar over
// the same facets, and no control that would act on a record this reader
// does not hold.
//
// Which jobs reach the page at all is the server's decision
// (tests/test_record_privacy.py pins it); what this spec protects is that
// the page renders the two kinds of entry differently and adds the right
// one.
import { expect, test } from '@playwright/test';
import { loadFixture, mockMove, mockPromote, mockUniverse } from './helpers.js';

const fixture = loadFixture('all-jobs');
const MINE = 'JOB-001';
const MINE_ENDED = 'JOB-007';
const POOL = 'JOB-010';
const POOL_CLOSED = 'JOB-011';

function card(page, id) {
  return page.getByTestId(`job-card-${id}`);
}

function addButton(page, id) {
  return card(page, id).getByRole('button', { name: /^Add .* to my jobs$/ });
}

test.beforeEach(async ({ page }) => {
  await mockUniverse(page, fixture);
});

test('the page is titled All jobs and holds one card per entry', async ({ page }) => {
  await page.goto('/all-jobs');
  await expect(page.getByRole('heading', { name: 'All jobs', level: 1 })).toBeVisible();
  await expect(page.locator('[data-testid^="job-card-"]')).toHaveCount(fixture.entries.length);
  await expect(card(page, POOL).getByRole('link', { name: 'Pool Platform Engineer' })).toHaveAttribute(
    'href',
    '/jobs/JOB-010',
  );
  // The nav marks this tab as the page, beside My Jobs.
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(nav.getByRole('link', { name: 'All jobs', exact: true })).toHaveAttribute('aria-current', 'page');
});

test('a job on my board shows its status, one that is not offers Add to my jobs', async ({ page }) => {
  await page.goto('/all-jobs');

  await expect(card(page, MINE).getByRole('button', { name: 'Move Senior Platform Engineer to' })).toBeVisible();
  await expect(addButton(page, MINE)).toHaveCount(0);

  await expect(addButton(page, POOL)).toBeVisible();
  await expect(card(page, POOL).getByRole('button', { name: /^Move / })).toHaveCount(0);
});

test('a card for a job that is not mine says nothing about somebody else being asked', async ({ page }) => {
  await page.goto('/all-jobs');
  // The pool entry carries needs_attention and a failed ingest, both of
  // which are about a record this reader does not hold: no chip, and no
  // Retry that would answer not-found.
  await expect(card(page, POOL).getByTestId('needs-input-chip')).toHaveCount(0);
  await expect(card(page, POOL).getByRole('button', { name: 'Retry' })).toHaveCount(0);
  // My own card still carries its chip, because the ask is mine.
  await expect(card(page, MINE).getByTestId('needs-input-chip')).toBeVisible();
  // The posting's own facts still read: location, and a closed posting.
  await expect(card(page, POOL)).toContainText('Zurich');
  await expect(card(page, POOL_CLOSED).getByText('Posting closed')).toBeVisible();
});

test('Add to my jobs posts to that job and reloads the tab', async ({ page }) => {
  const calls = await mockUniverse(page, fixture);
  const promotes = await mockPromote(page, { status: 201, body: { id: 'JOB-012', status: 'new' } });
  await page.goto('/all-jobs');
  await expect(addButton(page, POOL)).toBeVisible();
  // The loads this page has already made, whatever the dev server's own
  // double-invoked effect counts: what matters is that the add causes
  // another one.
  const loaded = calls.count;

  await addButton(page, POOL).click();

  await expect.poll(() => promotes.length).toBe(1);
  expect(promotes[0]).toContain('/api/jobs/JOB-010/promote');
  await expect(page.getByText('Added Pool Platform Engineer to New')).toBeVisible();
  // Reloaded, because the answer is a new record of this reader's own:
  // the list gains an entry and the posting it came from keeps its one.
  await expect.poll(() => calls.count).toBeGreaterThan(loaded);
});

test('a failed add is visible and leaves the button usable', async ({ page }) => {
  await mockPromote(page, { status: 500, body: { error: 'Could not add that job.' } });
  await page.goto('/all-jobs');
  await addButton(page, POOL).click();
  await expect(page.getByText('Could not add that job.')).toBeVisible();
  await expect(addButton(page, POOL)).toBeEnabled();
});

test('the status select on my own card still moves the job', async ({ page }) => {
  const moves = await mockMove(page);
  await page.goto('/all-jobs');
  await card(page, MINE).getByRole('button', { name: 'Move Senior Platform Engineer to' }).click();
  await page.getByRole('menuitem', { name: 'Applied', exact: true }).click();
  await expect.poll(() => moves.length).toBe(1);
  expect(moves[0].body).toEqual({ status: 'applied' });
});

test('the board filter bar narrows the tab, over both kinds of entry', async ({ page }) => {
  await page.goto('/all-jobs');
  await expect(page.getByText('3 open · 1 ended', { exact: true })).toBeVisible();

  await page.getByTestId('filter-chip-function').click();
  await page.getByRole('checkbox', { name: /^Engineering/ }).check();

  // One of each kind is an engineering job.
  await expect(card(page, MINE)).toBeVisible();
  await expect(card(page, POOL)).toBeVisible();
  await expect(card(page, MINE_ENDED)).toHaveCount(0);
  await expect(card(page, POOL_CLOSED)).toHaveCount(0);
  await expect(page.getByText(`2 of ${fixture.entries.length} jobs`, { exact: true })).toBeVisible();
});

test('Hide closed postings hides a closed posting here too', async ({ page }) => {
  await page.goto('/all-jobs');
  const toggle = page.getByTestId('filter-chip-hide-closed');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await toggle.click();
  await expect(card(page, POOL_CLOSED)).toHaveCount(0);
  await expect(card(page, POOL)).toBeVisible();
});

test('the tab offers no intake of its own', async ({ page }) => {
  // Pasting a link belongs on My Jobs, which is where the job a person
  // adds lands: this page has no main action at all (A1/A3).
  await page.goto('/all-jobs');
  await expect(page.getByRole('button', { name: 'Add a job' })).toHaveCount(0);
});

test('an empty universe says so', async ({ page }) => {
  await mockUniverse(page, { ...fixture, entries: [] });
  await page.goto('/all-jobs');
  await expect(page.getByText(fixture.empty)).toBeVisible();
  await expect(page.locator('[data-testid^="filter-chip-"]')).toHaveCount(0);
});
