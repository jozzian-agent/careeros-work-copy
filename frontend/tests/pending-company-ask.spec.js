// The company ask a pending link raises (owner ruling 2026-11-01). The
// backend answers needs_input {kind: 'company', review: null}, which is
// the shape NeedsInputCard already renders the create-a-company form for,
// so this spec is the proof that no frontend change was needed: the card
// appears, it is prefilled with the employer the posting named, and it
// posts without a review token because a pending link has no review.
import { expect, test } from '@playwright/test';
import { loadFixture, mockJobPage, mockResolveReview } from './helpers.js';

const fixture = loadFixture('job-detail');

// A job whose resolution finished with no company and no ambiguity: no
// review block, an extracted employer name, reading done.
const pendingCompany = {
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

test('a pending link offers creating the company the posting named', async ({ page }) => {
  await mockJobPage(page, pendingCompany);
  await page.goto('/jobs/JOB-001');
  const chip = page.getByRole('link', { name: 'Needs your input' });
  await expect(chip).toBeVisible();
  await expect(chip).toHaveAttribute('href', '#needs-your-input');
  await expect(page.getByRole('heading', { name: 'Needs your input' })).toBeVisible();
  await expect(page.getByText('This posting names Northwind AG.')).toBeVisible();
  // No candidates to pick from, so the create form is the card's whole
  // content rather than something behind a "None of these" button.
  await expect(page.getByRole('textbox', { name: 'Company name' })).toHaveValue('Northwind AG');
  await expect(page.getByRole('button', { name: 'Create and link' })).toBeVisible();
  await expect(page.getByRole('radio')).toHaveCount(0);
});

test('creating the company posts no review token, because there is no review', async ({ page }) => {
  await mockJobPage(page, pendingCompany);
  const requests = await mockResolveReview(page, { body: { ...fixture.job } });
  await page.goto('/jobs/JOB-001');
  const name = page.getByRole('textbox', { name: 'Company name' });
  await name.fill('Northwind Systems Zurich');
  await page.getByRole('button', { name: 'Create and link' }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ create: { name: 'Northwind Systems Zurich' } });
});
