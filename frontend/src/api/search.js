import { apiFetch } from './client.js';

// GET /api/search?view=page: the criteria_context payload (data, empty,
// sections) the Search criteria page reads. `data` is null when the
// owner has never saved criteria yet.
export async function fetchSearchPage() {
  const response = await apiFetch('/api/search?view=page');
  if (!response.ok) {
    throw new Error('Could not load your criteria.');
  }
  return response.json();
}

// POST /api/search: saves the whole criteria payload (roles, must_haves,
// nice_to_haves, avoid, notes) and returns the stored record, used both
// for the Create criteria action (an empty payload) and for Done in edit
// mode.
export async function saveSearch(payload) {
  const response = await apiFetch('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error || 'Could not save your criteria.');
  }
  return data;
}
