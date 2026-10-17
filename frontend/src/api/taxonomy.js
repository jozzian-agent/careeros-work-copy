import { apiFetch } from './client.js';

// GET /api/taxonomy: the read-only vault-wide methodology breakdown
// (skills, industries, sizes, tag_labels) the Taxonomy page renders.
export async function fetchTaxonomy() {
  const response = await apiFetch('/api/taxonomy');
  if (!response.ok) {
    throw new Error('Could not load taxonomy.');
  }
  return response.json();
}
