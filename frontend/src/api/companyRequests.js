import { apiFetch } from './client.js';

// The admin review list for company requests (contract:
// docs/surfaces/json-api.md). All three endpoints are admin only; a
// non-admin gets the server's own 403 and its message, which is what the
// page renders rather than inventing one of its own.

async function send(url, method, failure, body) {
  const response = await apiFetch(url, {
    method,
    ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error || failure);
  }
  return data;
}

// GET /api/company-requests: the requests the nightly pass could not
// settle, as {requests: [...]}. Each row carries the requested name, who
// asked, the job it came from and scored company suggestions.
export async function fetchCompanyRequests() {
  const response = await apiFetch('/api/company-requests');
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error || 'Could not load the company requests.');
  }
  return data;
}

// POST /api/company-requests/<id>/approve. With a companyId it links to
// that company; without one it creates a company with the requested name.
export function approveCompanyRequest(id, companyId) {
  return send(`/api/company-requests/${encodeURIComponent(id)}/approve`, 'POST',
    'Could not approve that request.', companyId ? { company_id: companyId } : null);
}

// POST /api/company-requests/<id>/reject. The note is optional and is
// stored on the request as the reason.
export function rejectCompanyRequest(id, note) {
  return send(`/api/company-requests/${encodeURIComponent(id)}/reject`, 'POST',
    'Could not reject that request.', note ? { note } : null);
}
