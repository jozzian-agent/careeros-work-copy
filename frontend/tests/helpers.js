import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const FIXTURE_PATH = fileURLToPath(new URL('./fixtures/board.json', import.meta.url));

export function loadBoardFixture() {
  return JSON.parse(readFileSync(FIXTURE_PATH, 'utf8'));
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

// Mocks POST /api/jobs/<id>/extract (ingest retry).
export async function mockRetry(page, { status = 200, body = { ok: true } } = {}) {
  await page.route('**/api/jobs/*/extract', (route) => route.fulfill({ status, json: body }));
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

// Mocks POST /api/jobs/<id>/promote.
export async function mockPromote(page, { status = 200, body = { ok: true } } = {}) {
  await page.route('**/api/jobs/*/promote', (route) => route.fulfill({ status, json: body }));
}
