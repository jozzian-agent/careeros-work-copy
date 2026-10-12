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

export async function retryIngest(id) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(id)}/extract`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error('Retry failed.');
  }
  return response.json();
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
