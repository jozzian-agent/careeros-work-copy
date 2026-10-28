// Protects M1 in the browser: the app has a door. A lost session takes
// the person to the login page, the right credentials land them on the
// board, the logout affordance brings them back out, and a 401 while the
// board is polling ends the polling instead of hammering a server that
// has already said no.
import { expect, test } from '@playwright/test';
import {
  loadBoardFixture,
  mockBoard,
  mockBoardUnauthorized,
  mockLogin,
  mockLogout,
} from './helpers.js';

const fixture = loadBoardFixture();
const openEntries = fixture.entries.filter((entry) => !fixture.ended_statuses.includes(entry.status));
const reading = openEntries[0];

// The board with one job's reading still owed, which is what gives the
// page a reason to keep asking.
const stillReading = {
  ...fixture,
  entries: fixture.entries.map((entry) => (
    entry.id === reading.id ? { ...entry, ai_status: 'running', ai_error: null } : entry)),
};

// The password field is addressed by role rather than by label: Gestalt's
// password TextField ships its own "Show password" control, which carries
// a label of its own.
async function fillAndSubmit(page, email = 'owner@example.test', password = 'a long phrase') {
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill(email);
  await page.getByRole('textbox', { name: 'Password', exact: true }).fill(password);
  await page.getByRole('button', { name: 'Log in' }).click();
}

test('a visit with no session ends on the login page', async ({ page }) => {
  await mockBoardUnauthorized(page);
  await page.goto('/jobs');
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('heading', { name: 'Log in' })).toBeVisible();
  // Nothing of the board is left on screen, nav included.
  await expect(page.getByRole('navigation', { name: 'Main' })).toHaveCount(0);
});

test('the login page links to the forgot-password page (CAREER-97)', async ({ page }) => {
  await mockBoardUnauthorized(page);
  await page.goto('/login');
  const link = page.getByRole('link', { name: 'Forgot password?' });
  await expect(link).toBeVisible();
  // Same-origin relative href, no absolute URL, no new env var.
  await expect(link).toHaveAttribute('href', '/forgot-password');
});

test('the right credentials land on the board', async ({ page }) => {
  await mockBoard(page, fixture);
  const attempts = await mockLogin(page);
  await page.goto('/login');
  await fillAndSubmit(page);
  await expect(page).toHaveURL(/\/jobs$/);
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
  await expect(page.getByTestId(`job-card-${reading.id}`)).toBeVisible();
  expect(attempts).toEqual([{ email: 'owner@example.test', password: 'a long phrase' }]);
});

test('a refused sign-in shows one message and stays on the page', async ({ page }) => {
  // The login page's own 401 is the answer to this attempt, not a lost
  // session, so it must not start the redirect that would loop.
  await mockLogin(page, { status: 401, body: { error: 'Wrong email or password.' } });
  await page.goto('/login');
  await fillAndSubmit(page, 'owner@example.test', 'not the password');
  await expect(page.getByText('Wrong email or password.')).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
  // Still usable: a second attempt is possible, which a redirect loop
  // would have made impossible.
  await expect(page.getByRole('button', { name: 'Log in' })).toBeEnabled();
});

test('Log out asks the server to end the session and returns to the login page', async ({ page }) => {
  await mockBoard(page, fixture);
  const calls = await mockLogout(page);
  await page.goto('/jobs');
  await page.getByRole('button', { name: 'Log out' }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(calls).toEqual(['POST']);
});

test('a 401 while polling asks nothing more', async ({ page }) => {
  // The navigation to the login page is aborted on purpose, so the board
  // stays mounted and the polling has every chance to carry on. What is
  // under test is the polling itself ending on a 401, not the redirect
  // covered above: a loop that re-armed would keep asking a server that
  // has already refused, once every interval, for as long as the tab is
  // open.
  let gone = false;
  let askedWhileGone = 0;
  await page.route('**/api/jobs?view=board', (route) => {
    if (!gone) {
      route.fulfill({ json: stillReading });
      return;
    }
    askedWhileGone += 1;
    route.fulfill({ status: 401, json: { error: 'login required' } });
  });
  await page.route('**/login', (route) => route.abort());

  await page.goto('/jobs');
  const card = page.getByTestId(`job-card-${reading.id}`);
  await expect(card.getByText('Details filling in…', { exact: true })).toBeVisible();

  gone = true;
  await expect.poll(() => askedWhileGone, { timeout: 20000 }).toBe(1);
  // Two polling intervals with the session gone: not one further ask.
  await page.waitForTimeout(11000);
  expect(askedWhileGone).toBe(1);
});
