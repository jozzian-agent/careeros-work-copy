// Protects the M2 read-only half (CAREER-39, owner decision D3): a user
// who may not change shared data is not offered a control that would
// fail. Companies and the tag vocabulary are shared universe, so Edit
// company, Delete, Edit classification, the company notes controls and
// the propose-a-new-tag controls all belong to the admin, while reading
// the same pages stays open to everybody.
//
// The flag is `can_edit_shared` on the page payload, which the backend
// sets from the session user's role (careeros/users.py is_admin). Each
// spec below mocks both answers, so the branch is driven by the payload
// and not by anything this suite has to know about sessions.
import { expect, test } from '@playwright/test';
import {
  loadFixture,
  mockCompanyPage,
  mockExperiencePage,
  mockExperienceTagsRegistry,
  mockJobPage,
  mockJobTaxonomy,
} from './helpers.js';

const company = loadFixture('company-detail');
const job = loadFixture('job-detail');
const taxonomy = loadFixture('job-taxonomy');
const experience = loadFixture('experience-detail');
const tagsRegistry = loadFixture('experience-tags-registry');

const asTester = (fixture) => ({ ...fixture, can_edit_shared: false });

// A company whose sector automation has run out of ideas on, which is
// what raises the one ask the page makes. Only the admin can answer it.
const needsSector = {
  ...company,
  company: { ...company.company, sectors: [], sector: null },
  sector_labels: [],
  classification: {
    sector: { value: null, source: null },
    size: company.classification.size,
  },
  needs_input: { field: 'sector', tried: ['jsonld', 'wikidata', 'llm'] },
};

// --- The company profile -------------------------------------------------

test('the admin is offered every company write', async ({ page }) => {
  await mockCompanyPage(page, company);
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('button', { name: 'Edit company' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Show the classification' }).click();
  await expect(page.getByRole('button', { name: 'Edit classification' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add a note' })).toBeVisible();
});

test('a tester is offered no company write at all', async ({ page }) => {
  await mockCompanyPage(page, asTester(company));
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('heading', { name: company.company.name })).toBeVisible();
  for (const name of ['Edit company', 'Delete', 'Edit classification', 'Add a note']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0);
  }
  for (const label of ['Edit', 'Delete']) {
    await expect(
      page.getByTestId('section-notes').getByRole('button', { name: new RegExp(`^${label} `) }),
    ).toHaveCount(0);
  }
});

test('a tester still reads the whole company profile', async ({ page }) => {
  await mockCompanyPage(page, asTester(company));
  await page.goto('/companies/CO-001');
  // The shared facts, the reader's own linked records, and the notes
  // that are already there: reading is what a tester keeps.
  await expect(page.getByText('Information and communication · 51-200').first()).toBeVisible();
  await expect(page.getByRole('link', { name: company.jobs[0].title })).toBeVisible();
  await expect(page.getByRole('link', { name: company.experiences[0].title })).toBeVisible();
  await expect(page.getByTestId('section-notes').getByText(company.notes[0].title)).toBeVisible();
  await page.getByRole('button', { name: 'Show the classification' }).click();
  await expect(page.getByTestId('section-classification').getByText('Sector')).toBeVisible();
});

test('the company ask is raised for the admin and not for a tester', async ({ page }) => {
  await mockCompanyPage(page, needsSector);
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('button', { name: 'Set it yourself' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();

  // Both of its actions write the shared record, so for a tester the
  // card would be an ask they cannot answer. The chip that jumps to it
  // goes with it.
  await mockCompanyPage(page, asTester(needsSector));
  await page.goto('/companies/CO-001');
  await expect(page.getByRole('button', { name: 'Set it yourself' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Try again' })).toHaveCount(0);
  await expect(page.getByText('Needs your input', { exact: true })).toHaveCount(0);
});

// --- The shared tag vocabulary -------------------------------------------

test('only the admin is offered a new tag in the job classification popup', async ({ page }) => {
  await mockJobPage(page, job);
  await mockJobTaxonomy(page, taxonomy);
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Show the classification' }).click();
  await page.getByRole('button', { name: 'Edit classification' }).click();
  const admin = page.getByRole('dialog', { name: 'Edit classification' });
  await expect(admin.getByRole('button', { name: '+ Add tag' })).toBeVisible();
  await expect(admin.getByLabel('New tag id')).toBeVisible();

  await mockJobTaxonomy(page, asTester(taxonomy));
  await page.goto('/jobs/JOB-001');
  await page.getByRole('button', { name: 'Show the classification' }).click();
  await page.getByRole('button', { name: 'Edit classification' }).click();
  const tester = page.getByRole('dialog', { name: 'Edit classification' });
  await expect(tester).toBeVisible();
  await expect(tester.getByRole('button', { name: '+ Add tag' })).toHaveCount(0);
  await expect(tester.getByLabel('New tag id')).toHaveCount(0);
  await expect(tester.getByText('Only the admin adds new values.')).toBeVisible();
  // Picking a value the registry already holds is a write to this job
  // alone, so it stays.
  await expect(tester.getByLabel('Add from registry')).toBeVisible();
  await expect(tester.getByRole('button', { name: '+ Add from registry' })).toBeVisible();
});

test('only the admin is offered a new tag in the Edit position popup', async ({ page }) => {
  await mockExperiencePage(page, experience);
  await mockExperienceTagsRegistry(page, tagsRegistry);
  await page.goto('/experiences/EXP-001');
  await page.getByRole('button', { name: 'Edit position' }).click();
  const admin = page.getByRole('dialog', { name: 'Edit position' });
  await expect(admin.getByLabel('Propose a new tag')).toBeVisible();
  await admin.getByRole('button', { name: 'Cancel' }).click();

  await mockExperienceTagsRegistry(page, asTester(tagsRegistry));
  await page.goto('/experiences/EXP-001');
  await page.getByRole('button', { name: 'Edit position' }).click();
  const tester = page.getByRole('dialog', { name: 'Edit position' });
  await expect(tester).toBeVisible();
  await expect(tester.getByLabel('Propose a new tag')).toHaveCount(0);
  await expect(tester.getByRole('button', { name: '+ Add tag' })).toHaveCount(0);
  await expect(tester.getByLabel('Add from registry')).toBeVisible();
});
