import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const FIXTURE_PATH = fileURLToPath(new URL('./fixtures/board.json', import.meta.url));

export function loadBoardFixture() {
  return JSON.parse(readFileSync(FIXTURE_PATH, 'utf8'));
}

export function loadFixture(name) {
  return JSON.parse(readFileSync(fileURLToPath(new URL(`./fixtures/${name}.json`, import.meta.url)), 'utf8'));
}

// Mocks GET /api/jobs/<id>?view=page (the Job detail page's load).
export async function mockJobPage(page, body) {
  await page.route('**/api/jobs/*?view=page', (route) => route.fulfill({ json: body }));
}

// Mocks GET/PUT /api/jobs/<id>/taxonomy (the Edit criteria popup).
export async function mockJobTaxonomy(page, body) {
  await page.route('**/api/jobs/*/taxonomy', (route) => {
    if (route.request().method() !== 'GET') {
      route.fallback();
      return;
    }
    route.fulfill({ json: body });
  });
}

// Mocks GET /api/experiences?view=page (the Experiences list page). The
// glob excludes the detail route's own /api/experiences/<id>?view=page
// (no extra path segment between "experiences" and the query string).
export async function mockExperiencesPage(page, body) {
  await page.route('**/api/experiences?view=page', (route) => route.fulfill({ json: body }));
}

// Mocks GET /api/experiences/<id>?view=page (the Experience detail page).
export async function mockExperiencePage(page, body) {
  await page.route('**/api/experiences/*?view=page', (route) => route.fulfill({ json: body }));
}

// Mocks GET /api/experiences/new (the Edit position popup's tag registry).
export async function mockExperienceTagsRegistry(page, body) {
  await page.route('**/api/experiences/new', (route) => route.fulfill({ json: body }));
}

// Mocks GET /api/companies?view=page (the Companies list page). The glob
// excludes the detail route's own /api/companies/<id>?view=page.
export async function mockCompaniesPage(page, body) {
  await page.route('**/api/companies?view=page', (route) => route.fulfill({ json: body }));
}

// Mocks GET /api/companies/<id>?view=page (the Company detail page).
export async function mockCompanyPage(page, body) {
  await page.route('**/api/companies/*?view=page', (route) => route.fulfill({ json: body }));
}

// Mocks GET /api/search?view=page (the Search criteria page's load).
export async function mockSearchPage(page, body) {
  await page.route('**/api/search?view=page', (route) => {
    if (route.request().method() !== 'GET') {
      route.fallback();
      return;
    }
    route.fulfill({ json: body });
  });
}

// Mocks POST /api/search (Create criteria, and Done in edit mode),
// recording each request's parsed body.
export async function mockSaveSearch(page, { status = 200, body = {} } = {}) {
  const requests = [];
  await page.route('**/api/search', (route) => {
    if (route.request().method() !== 'POST') {
      route.fallback();
      return;
    }
    requests.push(route.request().postDataJSON());
    route.fulfill({ status, json: body });
  });
  return requests;
}

// Mocks PUT /api/jobs/<id>, PUT /api/experiences/<id> or PUT
// /api/companies/<id> (every edit popup's save), recording each request.
export async function mockUpdate(page, urlGlob, { status = 200, body = {} } = {}) {
  const requests = [];
  await page.route(urlGlob, (route) => {
    if (route.request().method() !== 'PUT') {
      route.fallback();
      return;
    }
    requests.push(route.request().postDataJSON());
    route.fulfill({ status, json: body });
  });
  return requests;
}

// Mocks DELETE /api/jobs/<id>, /api/experiences/<id> or /api/companies/<id>.
export async function mockDelete(page, urlGlob, { status = 200, body = { deleted: true } } = {}) {
  await page.route(urlGlob, (route) => {
    if (route.request().method() !== 'DELETE') {
      route.fallback();
      return;
    }
    route.fulfill({ status, json: body });
  });
}

function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

// Drives StatusSelect (sm Button + Dropdown, JOZ-278): open the card's status
// control and pick a status, the same way a user would. Mirrors the shape
// of the old native-select `.selectOption()` call it replaced.
export async function selectStatus(page, card, jobTitle, newStatus) {
  await card.getByRole('button', { name: `Move ${jobTitle} to` }).click();
  await page.getByRole('menuitem', { name: titleCase(newStatus), exact: true }).click();
}

// Mocks the production GET /api/jobs?view=board request with a fixture body.
// The application code always fetches the real relative endpoint; only the
// test harness injects data, so dev and prod code paths stay identical. See
// frontend/README.md for the rationale. Returns a counter so auto-refresh
// specs can assert a second fetch happened without depending on timing.
export async function mockBoard(page, body) {
  const calls = { count: 0 };
  await page.route('**/api/jobs?view=board', (route) => {
    calls.count += 1;
    route.fulfill({ json: body });
  });
  return calls;
}

// Mocks PUT /api/jobs/<id> (the status-move mutation shared by the select
// and drag-and-drop paths). Records each request's method and parsed
// body so specs can assert the exact payload sent, not just the outcome.
export async function mockMove(page, { status = 200, body = { ok: true } } = {}) {
  const requests = [];
  await page.route('**/api/jobs/*', (route) => {
    if (route.request().method() !== 'PUT') {
      route.fallback();
      return;
    }
    requests.push({ method: route.request().method(), body: route.request().postDataJSON() });
    route.fulfill({ status, json: body });
  });
  return requests;
}

// Mocks POST /api/jobs/<id>/extract (ingest retry), recording each
// request's URL so a spec can assert the retry reached the endpoint for
// the job it was shown on.
export async function mockRetry(page, { status = 200, body = { ok: true } } = {}) {
  const requests = [];
  await page.route('**/api/jobs/*/extract', (route) => {
    requests.push(route.request().url());
    route.fulfill({ status, json: body });
  });
  return requests;
}

// Mocks POST /api/jobs/intake. `responses` is an array consumed in order,
// one per call, so a test can script "fails once, then succeeds" or
// "duplicate, then force succeeds" without juggling shared mutable state.
// Records each request's method and parsed body (including whether
// force:true was actually sent) so specs can assert the real payload,
// not just the UI outcome.
export async function mockIntake(page, responses) {
  let call = 0;
  const requests = [];
  await page.route('**/api/jobs/intake', (route) => {
    const next = responses[Math.min(call, responses.length - 1)];
    call += 1;
    requests.push({ method: route.request().method(), body: route.request().postDataJSON() });
    route.fulfill({ status: next.status ?? 200, json: next.body });
  });
  return requests;
}

// Mocks POST /api/watch/scan?job=<id> (the Job detail page's Check posting
// watcher action).
export async function mockCheckPosting(page, { status = 200, body = { events: [], watch_status: 'unchanged' } } = {}) {
  await page.route('**/api/watch/scan*', (route) => route.fulfill({ status, json: body }));
}

// Mocks POST /api/jobs/<id>/paste-description (the fetch_failed manual
// paste resume path), recording each request's parsed body.
export async function mockPasteDescription(page, { status = 200, body = { ok: true } } = {}) {
  const requests = [];
  await page.route('**/api/jobs/*/paste-description', (route) => {
    requests.push(route.request().postDataJSON());
    route.fulfill({ status, json: body });
  });
  return requests;
}

// Mocks POST /api/jobs/<id>/resolve-review (the owner settling which
// company a needs_review job belongs to), recording each request's parsed
// body so specs can assert the candidate id and the review token sent.
export async function mockResolveReview(page, { status = 200, body = { ok: true } } = {}) {
  const requests = [];
  await page.route('**/api/jobs/*/resolve-review', (route) => {
    requests.push(route.request().postDataJSON());
    route.fulfill({ status, json: body });
  });
  return requests;
}

// Mocks POST /api/jobs/<id>/promote.
export async function mockPromote(page, { status = 200, body = { ok: true } } = {}) {
  await page.route('**/api/jobs/*/promote', (route) => route.fulfill({ status, json: body }));
}

// Mocks GET /api/notes (the Notes page's load).
export async function mockNotesPage(page, body) {
  await page.route('**/api/notes', (route) => route.fulfill({ json: body }));
}

// Mocks the note write endpoints under a record: POST .../notes and
// PATCH/DELETE .../notes/<note_id>. Records each call's method, URL and
// parsed body, so a spec can assert which note was addressed and what was
// sent, not just that the section redrew. `urlGlob` names the record, so
// a spec can prove a write went to the job and not the company.
export async function mockNoteWrites(page, urlGlob, { status = 200, body = { ok: true } } = {}) {
  const requests = [];
  await page.route(urlGlob, (route) => {
    const request = route.request();
    requests.push({
      method: request.method(),
      url: request.url(),
      body: request.method() === 'DELETE' ? null : request.postDataJSON(),
    });
    route.fulfill({ status, json: body });
  });
  return requests;
}

// Mocks GET /api/taxonomy (the Taxonomy page's load).
export async function mockTaxonomy(page, body) {
  await page.route('**/api/taxonomy', (route) => route.fulfill({ json: body }));
}
