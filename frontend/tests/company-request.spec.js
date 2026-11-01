// The company ask, answered by somebody who may not write a company
// (owner ruling 2026-11-01). A company is shared and admin-write, so the
// create form on this card used to answer 403 for every other user. What
// this spec holds is the two halves of the fix on the page: the action
// says what it does and goes to the filing endpoint, and a request on
// file turns the card into a state with no action in it at all.
//
// The branch is driven by `can_edit_shared` on the page payload and by
// `needs_input.request`, both of which the backend sends
// (careeros/web/pages/jobs.py job_context), so nothing here has to know
// anything about sessions.
import { expect, test } from '@playwright/test';
import { loadFixture, mockCompanyRequest, mockJobPage, mockResolveReview } from './helpers.js';

const fixture = loadFixture('job-detail');

// A job whose resolution finished with no company and no ambiguity: no
// review block, an extracted employer name, reading done.
const pending = {
  ...fixture,
  job: {
    ...fixture.job,
    company_id: null,
    company_link_state: 'pending',
    company_link_reason: null,
    company_review: null,
    employer_named_in_posting: 'Northwind AG',
  },
  company: null,
  needs_input: { kind: 'company', review: null },
};

// The same job, read by a user who may not write a company.
const asTester = (payload) => ({ ...payload, can_edit_shared: false });

// The same job once the request is filed, which is what the page reads
// back after the filing: the ask stays, because the company is still
// unresolved, and it carries the name that was asked for.
const asked = {
  ...asTester(pending),
  needs_input: {
    kind: 'company',
    review: null,
    request: { name: 'Northwind Systems Zurich', filed: true },
  },
};

const ASKED_TEXT = 'Asked. We check company requests overnight.';

test('a user who may not write a company is offered asking for one', async ({ page }) => {
  await mockJobPage(page, asTester(pending));
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: 'Needs your input' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ask to add company' })).toBeVisible();
  // The admin-only action is not offered as a button that would answer 403.
  await expect(page.getByRole('button', { name: 'Create and link' })).toHaveCount(0);
  // The form itself is the same: the name the posting gave, editable.
  await expect(page.getByRole('textbox', { name: 'Company name' })).toHaveValue('Northwind AG');
});

test('asking files the name and switches the card to the asked state', async ({ page }) => {
  await mockJobPage(page, asTester(pending));
  const filed = await mockCompanyRequest(page, { body: { id: 'CR-001', name: 'Northwind Systems Zurich' } });
  const resolved = await mockResolveReview(page, { body: { ...pending.job } });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('textbox', { name: 'Company name' }).fill('Northwind Systems Zurich');
  // The reload after the filing reads the state the server is now in.
  await mockJobPage(page, asked);
  await page.getByRole('button', { name: 'Ask to add company' }).click();

  await expect.poll(() => filed.length).toBe(1);
  expect(filed[0]).toEqual({ name: 'Northwind Systems Zurich' });
  // Never the endpoint that writes the shared record.
  expect(resolved).toEqual([]);

  // The card states what was asked and offers nothing: the answer is not
  // the owner's to give.
  const card = page.getByRole('heading', { name: 'Needs your input' });
  await expect(card).toBeVisible();
  await expect(page.getByText(ASKED_TEXT)).toBeVisible();
  await expect(page.getByText('Northwind Systems Zurich').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ask to add company' })).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: 'Company name' })).toHaveCount(0);
});

test('the requested name shows as a pending label and not as a company link', async ({ page }) => {
  await mockJobPage(page, asked);
  await page.goto('/jobs/JOB-001');
  await expect(page.getByText('Northwind Systems Zurich (asked)')).toBeVisible();
  // No company record exists, so nothing on the page pretends one does.
  await expect(page.getByRole('link', { name: /Northwind/ })).toHaveCount(0);
});

test('a refused filing says why, and the card keeps the form', async ({ page }) => {
  await mockJobPage(page, asTester(pending));
  await mockCompanyRequest(page, {
    status: 429,
    body: { error: 'You asked about many companies today. Try again tomorrow.' },
  });
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Ask to add company' }).click();
  await expect(page.getByText('You asked about many companies today. Try again tomorrow.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ask to add company' })).toBeVisible();
});

test('the admin keeps the direct create, and files nothing', async ({ page }) => {
  await mockJobPage(page, pending);
  const filed = await mockCompanyRequest(page);
  const resolved = await mockResolveReview(page, { body: { ...pending.job } });
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('button', { name: 'Ask to add company' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Create and link' }).click();
  await expect.poll(() => resolved.length).toBe(1);
  expect(resolved[0]).toEqual({ create: { name: 'Northwind AG' } });
  expect(filed).toEqual([]);
});
