import { apiFetch } from './client.js';

// GET /api/experiences?view=page: the library_context payload (entries,
// empty, companies, labels, tag_labels) the Experiences list page reads.
export async function fetchExperiencesPage() {
  const response = await apiFetch('/api/experiences?view=page');
  if (!response.ok) {
    throw new Error('Could not load your experiences.');
  }
  return response.json();
}

// GET /api/experiences/<id>?view=page: the experience_context payload
// (exp, label, companies, tag_labels, markdown) the Experience detail page
// and the Edit position popup both read.
export async function fetchExperiencePage(id) {
  const response = await apiFetch(`/api/experiences/${encodeURIComponent(id)}?view=page`);
  if (!response.ok) {
    throw new Error('Could not load that position.');
  }
  return response.json();
}

export async function updateExperience(id, payload) {
  const response = await apiFetch(`/api/experiences/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error || 'Could not save that position.');
  }
  return data;
}

// GET /api/experiences/new: the form context -- the visible companies, the
// shared tag registry, and whether this user may add a value to that
// registry at all (M2). One request, two readers, so the failure message
// is the caller's: the Add position page could not load its form, and the
// Edit position popup could not load the registry it came for.
async function formContext(failure) {
  const response = await apiFetch('/api/experiences/new');
  if (!response.ok) {
    throw new Error(failure);
  }
  return response.json();
}

// The whole context, for the Add position page.
export function fetchExperienceFormContext() {
  return formContext('Could not load the position form.');
}

// The registry half of it, shaped for the Edit position popup, which
// already has the record and the companies from its own page payload.
export async function fetchExperienceTagsRegistry() {
  const data = await formContext('Could not load the tag registry.');
  return { tags: data.tags, canEditShared: Boolean(data.can_edit_shared) };
}

// POST /api/experiences: creates one position and stamps the caller as its
// owner. The one and only path that creates one (M2, decision D4).
export async function createExperience(payload) {
  const response = await apiFetch('/api/experiences', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error || 'Could not save that position.');
  }
  return data;
}

export async function deleteExperience(id) {
  const response = await apiFetch(`/api/experiences/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error('Could not delete that position.');
  }
  return response.json();
}

// POST /api/experiences/<id>/link-company: the Edit position popup's
// company field re-link/create flow (mirrors experience_form.html's own
// create-company-btn handling, including the fuzzy-match suggestion).
export async function linkExperienceCompany(id, payload) {
  const response = await apiFetch(`/api/experiences/${encodeURIComponent(id)}/link-company`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error || 'Could not link that company.');
  }
  return data;
}
