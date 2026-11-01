// The one place the front end talks to the API, so the answer to "your
// session is gone" is given once rather than per endpoint (M1).
//
// Every module under src/api/ calls apiFetch instead of fetch. A 401 from
// any of them means the same thing: the cookie is missing, expired, or
// belongs to an account that has been turned off, and the only useful next
// step is the login page.

export const LOGIN_PATH = '/login';

// What a call rejected after the session ended says. It is not shown as a
// page error in the normal case, because the browser is already on its way
// to the login page by the time a caller could render it.
export const SESSION_ENDED = 'Your session has ended. Log in again.';

// Latched on the first 401 and never cleared: the redirect is a full page
// load, so a fresh module instance starts clean. While it is set, no call
// reaches the network at all. That is what keeps a poll loop from turning
// into a request storm against a server that has already said no.
let ended = false;

export function sessionEnded() {
  return ended;
}

export async function apiFetch(input, init) {
  if (ended) {
    throw new Error(SESSION_ENDED);
  }
  const response = await fetch(input, init);
  if (response.status === 401) {
    // The login page's own 401 is the answer to a sign-in attempt, not a
    // lost session, so redirecting on it would be a loop that never shows
    // the message the person needs to read.
    if (window.location.pathname !== LOGIN_PATH) {
      ended = true;
      window.location.assign(LOGIN_PATH);
    }
    const data = await response.json().catch(() => null);
    throw new Error(data?.error || SESSION_ENDED);
  }
  return response;
}

// POST /login. Answers 401 with the one message the server gives for every
// failed attempt, which is the message the page shows.
export async function logIn(email, password) {
  const response = await apiFetch(LOGIN_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  return response.json();
}

// GET /api/me: who this request is signed in as, the safe subset the
// server will say (id, name, email, role, locale). The nav reads it for
// one thing only -- whether this is the admin, which decides whether the
// Company requests tab is there at all.
//
// A failure answers null rather than throwing. The nav is chrome on every
// page, and a tab that cannot be drawn must not be able to take the page
// with it; the endpoints behind an admin-only surface are gated on the
// server regardless of what the nav shows.
export async function fetchMe() {
  try {
    const response = await apiFetch('/api/me');
    if (!response.ok) {
      return null;
    }
    return await response.json();
  } catch {
    return null;
  }
}

// POST /logout. The JSON body is what asks for a JSON answer rather than
// the form redirect the no-build fallback page gets.
export async function logOut() {
  const response = await apiFetch('/logout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  });
  return response.json();
}
