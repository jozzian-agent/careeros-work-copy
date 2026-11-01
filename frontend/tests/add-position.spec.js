// Protects the Add position page (owner-approved artboard, 2026-11-01),
// which replaced the Jinja experience form: the page loads its three
// cards, the three required fields refuse an empty save with the owner's
// own three messages, a save reaches POST /api/experiences with everything
// the old form sent -- the custom fields and the function-tag round-trip
// included -- a pending company goes through link-company after the
// create, and Cancel goes back without writing anything.
import { expect, test } from '@playwright/test';
import {
  loadFixture,
  mockCreateExperience,
  mockExperienceTagsRegistry,
  mockExperiencesPage,
  mockLinkCompany,
} from './helpers.js';

const form = loadFixture('experience-form');

test.beforeEach(async ({ page }) => {
  await mockExperienceTagsRegistry(page, form);
  // The page Cancel and a finished save navigate to.
  await mockExperiencesPage(page, loadFixture('experiences-list'));
});

async function fillRequired(page) {
  await page.getByLabel('Title').fill('Platform Lead');
  await page.getByLabel('Start (YYYY-MM)').fill('2022-01');
  await page.getByLabel('Location').fill('Zurich');
}

test('the page loads with the back link, the H1 and the three cards', async ({ page }) => {
  await page.goto('/experiences/new');
  await expect(page.getByRole('heading', { name: 'Add position', level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Back to Professional experiences' }))
    .toHaveAttribute('href', '/experiences');
  for (const handle of ['section-role', 'section-what-you-did', 'section-tags']) {
    await expect(page.getByTestId(handle)).toBeVisible();
  }
  await expect(page.getByRole('button', { name: 'Save position' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();
});

test('the Role card carries every field the old form had, and no salary', async ({ page }) => {
  await page.goto('/experiences/new');
  const role = page.getByTestId('section-role');
  for (const label of ['Title', 'Company', 'Start (YYYY-MM)', 'End (YYYY-MM or present)',
                       'Location', 'People led']) {
    await expect(role.getByLabel(label)).toBeVisible();
  }
  // Owner decision: compensation is vault-file-only and this page does not
  // mention it at all, unlike the form it replaced.
  await expect(page.getByLabel('Salary')).toHaveCount(0);
  await expect(page.getByText('Managed in the vault file only')).toHaveCount(0);
});

test('an empty save shows the three required-field messages and writes nothing', async ({ page }) => {
  const requests = await mockCreateExperience(page);
  await page.goto('/experiences/new');
  await page.getByRole('button', { name: 'Save position' }).click();

  await expect(page.getByText('Enter a title.')).toBeVisible();
  await expect(page.getByText('Enter a start date.')).toBeVisible();
  await expect(page.getByText('Enter a location.')).toBeVisible();
  expect(requests).toEqual([]);
});

test('a required-field message clears once the field is filled in', async ({ page }) => {
  await page.goto('/experiences/new');
  await page.getByRole('button', { name: 'Save position' }).click();
  await expect(page.getByText('Enter a title.')).toBeVisible();
  await page.getByLabel('Title').fill('Platform Lead');
  await expect(page.getByText('Enter a title.')).toHaveCount(0);
  // The two that are still empty keep saying so.
  await expect(page.getByText('Enter a start date.')).toBeVisible();
});

test('the happy path creates the position and lands on its detail page', async ({ page }) => {
  const requests = await mockCreateExperience(page, { body: { id: 'EXP-009' } });
  await page.route('**/api/experiences/EXP-009?view=page', (route) => route.fulfill({
    json: {
      ...loadFixture('experience-detail'),
      exp: { ...loadFixture('experience-detail').exp, id: 'EXP-009', title: 'Platform Lead' },
    },
  }));
  await page.goto('/experiences/new');
  await fillRequired(page);
  await page.getByLabel('End (YYYY-MM or present)').fill('present');
  await page.getByLabel('People led').fill('6');
  await page.getByLabel('Summary (2–4 sentences)').fill('Ran the platform team.');
  await page.getByLabel('Highlights (one per line)').fill('Shipped the thing\n\n  Hired four people  ');
  await page.getByLabel('Detail (paragraphs, lists, **bold** and *italic*)').fill('**Bold** detail.');

  await page.getByRole('button', { name: 'Save position' }).click();

  await expect(page).toHaveURL(/\/experiences\/EXP-009$/);
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({
    title: 'Platform Lead',
    start: '2022-01',
    end: 'present',
    location: 'Zurich',
    people_led: 6,
    summary: 'Ran the platform team.',
    // One per line, trimmed, blanks dropped -- the old form's own rule.
    highlights: ['Shipped the thing', 'Hired four people'],
    detail: '**Bold** detail.',
  });
});

test('Cancel goes back to Experiences without writing', async ({ page }) => {
  const requests = await mockCreateExperience(page);
  await page.goto('/experiences/new');
  await page.getByLabel('Title').fill('Half-typed position');
  await page.getByRole('button', { name: 'Cancel' }).click();

  await expect(page).toHaveURL(/\/experiences$/);
  await expect(page.getByRole('heading', { name: 'Experiences', level: 1 })).toBeVisible();
  expect(requests).toEqual([]);
});

// --- The behaviours the artboard does not mention, carried over ----------

test('a typed company that matches a record reads as linked and is saved as a company_id', async ({ page }) => {
  const requests = await mockCreateExperience(page);
  await page.goto('/experiences/new');
  await fillRequired(page);
  await expect(page.getByText('Not linked')).toBeVisible();

  await page.getByLabel('Company').fill('fictional university');
  await expect(page.getByText('Linked to Fictional University')).toBeVisible();
  // A matched company needs no creating, so the offer is not there.
  await expect(page.getByRole('button', { name: 'Create & link new company' })).toHaveCount(0);

  await page.getByRole('button', { name: 'Save position' }).click();
  expect(requests[0]).toMatchObject({ company: 'fictional university', company_id: 'CO-002' });
});

test('a company no record matches is created through link-company after the save', async ({ page }) => {
  const created = await mockCreateExperience(page, { body: { id: 'EXP-009' } });
  const links = await mockLinkCompany(page, [{ status: 201, body: { company_id: 'CO-010' } }]);
  await page.route('**/api/experiences/EXP-009?view=page',
                   (route) => route.fulfill({ json: loadFixture('experience-detail') }));
  await page.goto('/experiences/new');
  await fillRequired(page);
  await page.getByLabel('Company').fill('Brand New Co');
  await expect(page.getByText('Not linked')).toBeVisible();
  await page.getByRole('button', { name: 'Create & link new company' }).click();
  // Nothing is created yet: there is no position to link it to.
  await expect(page.getByText('Will create "Brand New Co" on save')).toBeVisible();
  expect(links).toEqual([]);

  await page.getByRole('button', { name: 'Save position' }).click();
  await expect(page).toHaveURL(/\/experiences\/EXP-009$/);
  expect(created[0]).toMatchObject({ company: 'Brand New Co', company_id: null });
  expect(links).toHaveLength(1);
  expect(links[0].url).toContain('/api/experiences/EXP-009/link-company');
  expect(links[0].body).toEqual({ create: { name: 'Brand New Co' } });
});

test('a near-match suggestion is confirmed before a second company is created', async ({ page }) => {
  await mockCreateExperience(page, { body: { id: 'EXP-009' } });
  const links = await mockLinkCompany(page, [
    { body: { suggestion: { id: 'CO-002', name: 'Fictional University' } } },
    { body: { company_id: 'CO-002' } },
  ]);
  await page.route('**/api/experiences/EXP-009?view=page',
                   (route) => route.fulfill({ json: loadFixture('experience-detail') }));
  // OK on the confirm means "link to the suggestion", which is what the
  // Edit position popup's own flow does.
  page.on('dialog', (dialog) => dialog.accept());

  await page.goto('/experiences/new');
  await fillRequired(page);
  await page.getByLabel('Company').fill('Fictional Universty');
  await page.getByRole('button', { name: 'Create & link new company' }).click();
  await page.getByRole('button', { name: 'Save position' }).click();

  await expect(page).toHaveURL(/\/experiences\/EXP-009$/);
  expect(links.map((link) => link.body)).toEqual([
    { create: { name: 'Fictional Universty' } },
    { company_id: 'CO-002' },
  ]);
});

test('a failed company link is visible, and the position it did create is reachable', async ({ page }) => {
  await mockCreateExperience(page, { body: { id: 'EXP-009' } });
  await mockLinkCompany(page, [{ status: 403, body: { error: 'Only the owner changes shared records.' } }]);
  await page.route('**/api/experiences/EXP-009?view=page',
                   (route) => route.fulfill({ json: loadFixture('experience-detail') }));
  await page.goto('/experiences/new');
  await fillRequired(page);
  await page.getByLabel('Company').fill('Brand New Co');
  await page.getByRole('button', { name: 'Create & link new company' }).click();
  await page.getByRole('button', { name: 'Save position' }).click();

  await expect(page.getByText(/The position is saved, but the company link failed/)).toBeVisible();
  // Save is gone, so the position cannot be created twice.
  await expect(page.getByRole('button', { name: 'Save position' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Open the position' }).click();
  await expect(page).toHaveURL(/\/experiences\/EXP-009$/);
});

test('every facet but function is offered, with experience type as its three choices', async ({ page }) => {
  await page.goto('/experiences/new');
  const tags = page.getByTestId('section-tags');
  for (const label of ['Employment', 'Guest lecture / teaching', 'Volunteer']) {
    await expect(tags.getByLabel(label)).toBeVisible();
  }
  for (const facet of ['capability', 'domain knowledge', 'tool']) {
    await expect(tags.getByLabel(`Add ${facet} from registry`)).toBeVisible();
  }
  // Function tags have their own proposal flow and are never hand-edited
  // on a position, so the facet is not offered here at all.
  await expect(tags.getByLabel('Add job function from registry')).toHaveCount(0);
  await expect(tags.getByLabel('Propose a new job function tag')).toHaveCount(0);
  // One propose button per facet, each named after its own facet.
  await expect(tags.getByRole('button', { name: /^Add .* tag$/ })).toHaveCount(3);
});

test('a registry tag and a proposed tag both reach the payload, the new one as a proposal', async ({ page }) => {
  const requests = await mockCreateExperience(page);
  await page.goto('/experiences/new');
  await fillRequired(page);

  await page.getByTestId('section-tags').getByLabel('Employment').check();
  await page.getByLabel('Add capability from registry').selectOption('skill/capability:public-speaking');
  await page.getByLabel('Propose a new tool tag').fill('Terraform Cloud');
  await page.getByRole('button', { name: 'Add tool tag' }).click();

  await page.getByRole('button', { name: 'Save position' }).click();
  expect(requests[0].tags).toEqual([
    'experience-type:employment',
    'skill/capability:public-speaking',
    'tool:terraform-cloud',
  ]);
  // Only the token the registry does not hold is proposed.
  expect(requests[0].proposed_tags).toEqual(['tool:terraform-cloud']);
});

test('a tester is offered the registry and not the propose control', async ({ page }) => {
  await mockExperienceTagsRegistry(page, { ...form, can_edit_shared: false });
  await page.goto('/experiences/new');
  const tags = page.getByTestId('section-tags');
  await expect(tags.getByLabel('Add capability from registry')).toBeVisible();
  await expect(tags.getByLabel('Propose a new capability tag')).toHaveCount(0);
  await expect(tags.getByRole('button', { name: /^Add .* tag$/ })).toHaveCount(0);
  await expect(tags.getByText('Only the admin adds new values.').first()).toBeVisible();
});

test('custom fields reach the payload, as text and as parsed JSON', async ({ page }) => {
  const requests = await mockCreateExperience(page);
  await page.goto('/experiences/new');
  await fillRequired(page);
  const tags = page.getByTestId('section-tags');

  await tags.getByRole('button', { name: 'Add custom field' }).click();
  await tags.getByPlaceholder('Key').fill('Clearance');
  await tags.getByPlaceholder('Value').fill('None');
  await tags.getByRole('button', { name: 'Add custom field' }).click();
  await tags.getByPlaceholder('Key').nth(1).fill('Nested');
  await tags.getByPlaceholder('Value').nth(1).fill('{"a": [1, 2]}');

  await page.getByRole('button', { name: 'Save position' }).click();
  expect(requests[0].custom).toEqual({ Clearance: 'None', Nested: { a: [1, 2] } });
});

test('a custom field with no key is refused before anything is written', async ({ page }) => {
  const requests = await mockCreateExperience(page);
  await page.goto('/experiences/new');
  await fillRequired(page);
  const tags = page.getByTestId('section-tags');
  await tags.getByRole('button', { name: 'Add custom field' }).click();
  await tags.getByPlaceholder('Value').fill('orphan value');

  await page.getByRole('button', { name: 'Save position' }).click();
  await expect(page.getByText('Each custom field needs a key.')).toBeVisible();
  expect(requests).toEqual([]);
});

test('the error the server gives for a refused write is what the page shows', async ({ page }) => {
  await mockCreateExperience(page, { status: 400, body: { error: 'Start must be YYYY-MM.' } });
  await page.goto('/experiences/new');
  await fillRequired(page);
  await page.getByLabel('Start (YYYY-MM)').fill('2022-13');
  await page.getByRole('button', { name: 'Save position' }).click();
  await expect(page.getByText('Start must be YYYY-MM.')).toBeVisible();
  await expect(page).toHaveURL(/\/experiences\/new$/);
});

test('a load failure shows a visible error with Retry', async ({ page }) => {
  await page.route('**/api/experiences/new',
                   (route) => route.fulfill({ status: 500, json: { error: 'nope' } }));
  await page.goto('/experiences/new');
  await expect(page.getByText('Could not load the position form.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
});
