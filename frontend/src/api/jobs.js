// Production fetch path for the Jobs board. Playwright specs intercept this
// exact request (page.route) and fulfill it with tests/fixtures/board.json;
// see frontend/README.md for why no dev-only mock branch lives here.
export async function fetchBoard() {
  const response = await fetch('/api/jobs?view=board');
  if (!response.ok) {
    throw new Error('Could not load the jobs board.');
  }
  return response.json();
}

export async function moveJobStatus(id, status) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  if (!response.ok) {
    throw new Error('Status update failed.');
  }
  return response.json();
}

// Generic job PUT, shared by the Fit dropdown, the Edit job popup and the
// Edit criteria popup (function/tags). Mirrors careeros/server.py
// job_api(): any submitted field lands with owner provenance. Kept
// separate from moveJobStatus, whose fixed "Status update failed."
// message (and the board specs pinning it) predates this ticket.
export async function updateJob(id, payload) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error || 'Could not save that job.');
  }
  return data;
}

export async function deleteJob(id) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error('Could not delete that job.');
  }
  return response.json();
}

// GET /api/jobs/<id>?view=page: the detail_context payload (job, company,
// statuses, function_labels, markdown, has_description, show_remote_chip,
// watch_eligible, watch_reason, llm_pending) the Job detail page renders.
export async function fetchJobPage(id) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(id)}?view=page`);
  if (!response.ok) {
    throw new Error('Could not load that job.');
  }
  return response.json();
}

// GET /api/jobs/<id>/taxonomy: the classification_context payload the Edit
// criteria popup edits (function/tags; sector is read-only, company-owned).
export async function fetchJobTaxonomy(id) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(id)}/taxonomy`);
  if (!response.ok) {
    throw new Error('Could not load classification.');
  }
  return response.json();
}

// POST /api/watch/scan?job=<id>: the job detail page's "Check posting"
// watcher action (careeros/server.py watch_scan). Returns { events,
// watch_status, reason } -- a non-empty events list means history changed
// and the caller should reload the page.
export async function checkPosting(id) {
  const response = await fetch(`/api/watch/scan?job=${encodeURIComponent(id)}`, {
    method: 'POST',
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error || 'Could not check that posting.');
  }
  return data;
}

export async function retryIngest(id) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(id)}/extract`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error('Retry failed.');
  }
  return response.json();
}

// POST /api/jobs/<id>/paste-description: the fetch_failed "paste posting
// text manually" resume path (careeros/server.py paste_description).
// Resumes extraction through the same worker /extract uses.
export async function pasteDescription(id, description) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(id)}/paste-description`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error || 'Could not save that posting text.');
  }
  return data;
}

// Mirrors careeros/server.py job_intake(): a 200 response whose body has
// duplicate: true is not an error, it is the warning payload
// ({ basis, existing: { id, title, in_pipeline }, actions }) the caller
// must turn into the duplicate dialog. force resubmits past that check.
export async function intakeJob(url, { force = false, origin = 'manual' } = {}) {
  const response = await fetch('/api/jobs/intake', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(force ? { url, force: true, origin } : { url, origin }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(data?.error || 'Could not add that posting.');
    // careeros/server.py job_intake() returns 503 with {job, error} when the
    // stub saved fine but extraction could not even start. The caller needs
    // that job id to retry via the extraction endpoint for the saved record,
    // never a second intake call (which would just hit dedup, or create a
    // duplicate record if forced).
    if (data?.job?.id) error.jobId = data.job.id;
    throw error;
  }
  return data;
}

export async function promoteJob(id) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(id)}/promote`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error('Promote failed.');
  }
  return response.json();
}
