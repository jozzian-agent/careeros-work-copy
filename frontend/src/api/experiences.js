// GET /api/experiences?view=page: the library_context payload (entries,
// empty, companies, labels, tag_labels) the Experiences list page reads.
export async function fetchExperiencesPage() {
  const response = await fetch('/api/experiences?view=page');
  if (!response.ok) {
    throw new Error('Could not load your experiences.');
  }
  return response.json();
}

// GET /api/experiences/<id>?view=page: the experience_context payload
// (exp, label, companies, tag_labels, markdown) the Experience detail page
// and the Edit position popup both read.
export async function fetchExperiencePage(id) {
  const response = await fetch(`/api/experiences/${encodeURIComponent(id)}?view=page`);
  if (!response.ok) {
    throw new Error('Could not load that position.');
  }
  return response.json();
}

export async function updateExperience(id, payload) {
  const response = await fetch(`/api/experiences/${encodeURIComponent(id)}`, {
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

// GET /api/experiences/new: reused only for its `tags` registry (the same
// facet/value list experience_form.html populates its Skills checkboxes
// from), so the Edit position popup can offer the same options without a
// new backend endpoint.
export async function fetchExperienceTagsRegistry() {
  const response = await fetch('/api/experiences/new');
  if (!response.ok) {
    throw new Error('Could not load the tag registry.');
  }
  const data = await response.json();
  return data.tags;
}

export async function deleteExperience(id) {
  const response = await fetch(`/api/experiences/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error('Could not delete that position.');
  }
  return response.json();
}

// POST /api/experiences/<id>/link-company: the Edit position popup's
// company field re-link/create flow (mirrors experience_form.html's own
// create-company-btn handling, including the fuzzy-match suggestion).
export async function linkExperienceCompany(id, payload) {
  const response = await fetch(`/api/experiences/${encodeURIComponent(id)}/link-company`, {
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
