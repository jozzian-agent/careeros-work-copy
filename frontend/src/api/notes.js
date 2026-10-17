import { apiFetch } from './client.js';

// The notes API (contract: docs/surfaces/json-api.md). A note belongs to
// exactly one record, so every write names the kind of record it lives in
// ('jobs' or 'companies') instead of this file carrying two
// near-identical clients that could drift.
function notesUrl(kind, recordId, noteId) {
  const base = `/api/${kind}/${encodeURIComponent(recordId)}/notes`;
  return noteId ? `${base}/${encodeURIComponent(noteId)}` : base;
}

async function send(url, method, failure, body) {
  const response = await apiFetch(url, {
    method,
    ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    // The endpoint's own message is the one worth showing: a blank title
    // and a note that is no longer there need different answers.
    throw new Error(data?.error || failure);
  }
  return data;
}

export function createNote(kind, recordId, fields) {
  return send(notesUrl(kind, recordId), 'POST', 'Could not add that note.', fields);
}

export function updateNote(kind, recordId, noteId, fields) {
  return send(notesUrl(kind, recordId, noteId), 'PATCH', 'Could not save that note.', fields);
}

export function deleteNote(kind, recordId, noteId) {
  return send(notesUrl(kind, recordId, noteId), 'DELETE', 'Could not delete that note.');
}

// GET /api/notes: every note in the vault with the record it belongs to,
// newest first, as {notes, empty}. Read-only; the Notes page links
// through to the record that holds a note rather than editing it.
export async function fetchNotes() {
  const response = await apiFetch('/api/notes');
  if (!response.ok) {
    throw new Error('Could not load your notes.');
  }
  return response.json();
}
