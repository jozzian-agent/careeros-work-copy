// The admin review list for company requests (owner ruling 2026-11-01).
//
// A user who may not write a shared company asks for the one their
// posting names (PR #44), the nightly pass answers what it can match, and
// this page is where the rest is answered. What this spec holds is the
// three answers a row offers, that each one goes to the right endpoint
// with the right body, and that the page shows the server's own refusal
// to anybody who is not the admin rather than a sentence of its own.
import { expect, test } from '@playwright/test';
import {
  mockAnswerCompanyRequest,
  mockCompanyRequestsPage,
  mockMe,
} from './helpers.js';

const ROW = {
  id: 'CR-001',
  name: 'Northwind AG',
  created_at: '2026-10-30',
  requester: { id: 'USER-002', name: 'Tester One' },
  job: { id: 'JOB-007', title: null },
  suggestions: [{ company_id: 'CO-004', name: 'Northwind Systems', score: 0.82 }],
};

const PAYLOAD = { requests: [ROW] };

test.beforeEach(async ({ page }) => {
  await mockMe(page);
});

test('the queue lists the requested name, who asked and the posting it came from', async ({ page }) => {
  await mockCompanyRequestsPage(page, PAYLOAD);
  await page.goto('/company-requests');
  await expect(page.getByRole('heading', { name: 'Company requests', exact: true })).toBeVisible();
  await expect(page.getByText('Northwind AG', { exact: true })).toBeVisible();
  await expect(page.getByText('Tester One', { exact: true })).toBeVisible();
  // The job id and no title: a request comes from somebody else's private
  // posting, so the server sends a title only where the admin may read
  // one (careeros/company_requests.py admin_rows).
  await expect(page.getByText('JOB-007', { exact: true })).toBeVisible();
});

test('Approve with no choice asks the endpoint to create the company', async ({ page }) => {
  await mockCompanyRequestsPage(page, PAYLOAD);
  const approvals = await mockAnswerCompanyRequest(page, 'approve');
  await page.goto('/company-requests');

  await page.getByRole('button', { name: 'Approve', exact: true }).click();

  await expect.poll(() => approvals.length).toBe(1);
  expect(approvals[0].url).toContain('/api/company-requests/CR-001/approve');
  // No body at all, which is what says "create one with the requested
  // name" rather than naming a company to link to.
  expect(approvals[0].body).toBeNull();
});

test('a suggestion chip approves against that company', async ({ page }) => {
  await mockCompanyRequestsPage(page, PAYLOAD);
  const approvals = await mockAnswerCompanyRequest(page, 'approve');
  await page.goto('/company-requests');

  // The chip says the name and the score, so the admin can tell how
  // close it is before clicking. It is a hint, never a link the pass
  // would have made itself.
  await page.getByRole('button', { name: 'Northwind Systems (0.82)' }).click();

  await expect.poll(() => approvals.length).toBe(1);
  expect(approvals[0].body).toEqual({ company_id: 'CO-004' });
});

test('Reject sends the note that was typed', async ({ page }) => {
  await mockCompanyRequestsPage(page, PAYLOAD);
  const rejections = await mockAnswerCompanyRequest(page, 'reject');
  await page.goto('/company-requests');

  await page.getByRole('button', { name: 'Reject', exact: true }).click();
  await page.getByLabel('Why (optional)').fill('Not a real employer.');
  await page.getByRole('button', { name: 'Confirm reject', exact: true }).click();

  await expect.poll(() => rejections.length).toBe(1);
  expect(rejections[0].url).toContain('/api/company-requests/CR-001/reject');
  expect(rejections[0].body).toEqual({ note: 'Not a real employer.' });
});

test('answering a request reloads the queue', async ({ page }) => {
  const calls = await mockCompanyRequestsPage(page, PAYLOAD);
  await mockAnswerCompanyRequest(page, 'approve');
  await page.goto('/company-requests');
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeVisible();
  // Counted as "more than before", not as an exact number: StrictMode
  // runs the load effect twice in dev, the same way all-jobs.spec.js
  // reads its own counter.
  const loaded = calls.count;

  await page.getByRole('button', { name: 'Approve', exact: true }).click();

  await expect.poll(() => calls.count).toBeGreaterThan(loaded);
});

test('an empty queue says so instead of showing an empty table', async ({ page }) => {
  await mockCompanyRequestsPage(page, { requests: [] });
  await page.goto('/company-requests');
  await expect(page.getByTestId('company-requests-empty')).toBeVisible();
  await expect(page.getByRole('table')).toHaveCount(0);
});

test('a row with nothing close to it says that rather than offering nothing', async ({ page }) => {
  await mockCompanyRequestsPage(page, { requests: [{ ...ROW, suggestions: [] }] });
  await page.goto('/company-requests');
  await expect(page.getByText('Nothing close', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeVisible();
});

test('a non-admin is shown the refusal the server gives', async ({ page }) => {
  await page.route('**/api/company-requests', (route) => route.fulfill({
    status: 403,
    json: { error: 'Only the admin can change companies and vocabulary.' },
  }));
  await page.goto('/company-requests');
  await expect(page.getByText('Only the admin can change companies and vocabulary.')).toBeVisible();
  await expect(page.getByRole('table')).toHaveCount(0);
});
