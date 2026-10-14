// GET /api/companies?view=page: the directory_context payload (entries,
// counts, empty, isic_sections, sector_labels, size_classes) the
// Companies list page reads.
export async function fetchCompaniesPage() {
  const response = await fetch('/api/companies?view=page');
  if (!response.ok) {
    throw new Error('Could not load your companies.');
  }
  return response.json();
}

// GET /api/companies/<id>?view=page: the company_context payload (company,
// sector_labels, entries, jobs, experiences, companies, classification,
// needs_input, isic_sections, size_classes, kinds) the Company detail
// page reads. Contract: docs/surfaces/json-api.md.
export async function fetchCompanyPage(id) {
  const response = await fetch(`/api/companies/${encodeURIComponent(id)}?view=page`);
  if (!response.ok) {
    throw new Error('Could not load that company.');
  }
  return response.json();
}

export async function updateCompany(id, payload) {
  const response = await fetch(`/api/companies/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error || 'Could not save that company.');
  }
  return data;
}

// DELETE /api/companies/<id>: careeros/server.py company_api() returns 409
// with {error, count} when jobs/experiences are still linked, which the
// delete confirmation renders inline rather than treating as a generic
// failure.
export async function deleteCompany(id) {
  const response = await fetch(`/api/companies/${encodeURIComponent(id)}`, { method: 'DELETE' });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(data?.error || 'Could not delete that company.');
    error.status = response.status;
    throw error;
  }
  return data;
}

// POST /api/companies/<id>/retry: the owner-only sector/size enrichment
// retry (careeros/server.py retry_company).
export async function retryCompany(id) {
  const response = await fetch(`/api/companies/${encodeURIComponent(id)}/retry`, { method: 'POST' });
  if (!response.ok) {
    throw new Error('Retry failed.');
  }
  return response.json();
}
