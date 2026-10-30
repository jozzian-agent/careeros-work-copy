// Protects the react-intl wiring (CAREER-116): the app renders its words
// through the catalog, every id it asks for is answered, and no id ever
// reaches the screen in place of the string it stands for.
//
// The other 27 specs are the real regression net -- they assert the English
// itself, hundreds of times over, and they would fail first if a value
// changed. This one covers the thing they cannot see: react-intl falling
// back to the id, which looks like a string to a text assertion written
// against the id but like a bug to a person.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard } from './helpers.js';

const catalog = JSON.parse(
  readFileSync(fileURLToPath(new URL('../src/i18n/en.json', import.meta.url)), 'utf8'),
);
const fixture = loadBoardFixture();

// A missing id is reported to the browser console ("Missing message: ...")
// by react-intl's own error handler before it falls back, so one page load
// answers both halves: nothing complained, and nothing shows a key.
function missingMessageErrors(page) {
  const errors = [];
  page.on('console', (message) => {
    if (message.type() === 'error' && message.text().includes('Missing message')) {
      errors.push(message.text());
    }
  });
  return errors;
}

test.beforeEach(async ({ page }) => {
  await mockBoard(page, fixture);
});

test('the shell renders its labels out of the catalog, and asks for nothing it lacks', async ({ page }) => {
  const errors = missingMessageErrors(page);
  await page.goto('/jobs');

  const nav = page.getByRole('navigation', { name: catalog['shell.nav.ariaLabel'] });
  await expect(nav.getByRole('link', { name: catalog['shell.nav.jobs'], exact: true })).toBeVisible();
  await expect(nav.getByRole('link', { name: catalog['shell.nav.companies'], exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: catalog['shell.logOut'] })).toBeVisible();
  await expect(page.getByRole('heading', { name: catalog['board.title'], level: 1 })).toBeVisible();

  expect(errors).toEqual([]);
});

test('no catalog id is rendered in place of its string', async ({ page }) => {
  await page.goto('/jobs');
  await expect(page.getByRole('heading', { name: catalog['board.title'], level: 1 })).toBeVisible();

  const shown = await page.locator('body').innerText();
  expect(Object.keys(catalog).filter((id) => shown.includes(id))).toEqual([]);
});
