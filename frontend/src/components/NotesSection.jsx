import { useState } from 'react';
import { Button, Flex, Text } from 'gestalt';
import SectionCard, { DividerList, EmptyState } from './SectionCard.jsx';
import NotePopup from './NotePopup.jsx';
import DeleteConfirmModal from './DeleteConfirmModal.jsx';
import { createNote, deleteNote, updateNote } from '../api/notes.js';
import { localDate } from '../dates.js';

// A note's body on a row is its first line. The whole body lives in the
// note's own window, which the row's Edit opens, so the row says which
// note this is rather than trying to show it.
export function notePreview(body) {
  return String(body || '').split('\n').map((line) => line.trim()).find(Boolean) || '';
}

// The whole Notes section of a detail page: the rows, the window a note
// is written in, and the delete confirmation. The Job page's notes and
// the Company page's notes are the same thing on the same endpoints, so
// they are one component and not two copies that can drift.
//
// `kind` is the record kind the endpoints take ('jobs' or 'companies'),
// `notes` is the record context's migrated notes list, and `onChanged`
// reloads that context: this component holds no copy of the list, so what
// the section shows after a save is always what the backend stored.
export default function NotesSection({ kind, recordId, notes, onChanged }) {
  // null when no window is open, the note when editing one, and the empty
  // object when adding: a new note is a note without an id yet.
  const [editing, setEditing] = useState(null);
  const [removing, setRemoving] = useState(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState(null);

  async function handleSave(fields) {
    if (editing?.id) await updateNote(kind, recordId, editing.id, fields);
    else await createNote(kind, recordId, fields);
    setEditing(null);
    onChanged();
  }

  async function handleRemove() {
    setRemoveBusy(true);
    setRemoveError(null);
    try {
      await deleteNote(kind, recordId, removing.id);
      setRemoving(null);
      onChanged();
    } catch (err) {
      setRemoveError(err.message);
    } finally {
      setRemoveBusy(false);
    }
  }

  const addButton = <Button text="Add a note" size="sm" color="gray" onClick={() => setEditing({})} />;

  return (
    <SectionCard title="Notes">
      {notes.length ? (
        <Flex direction="column" gap={3}>
          <DividerList
            items={notes.map((note) => ({ ...note, key: note.id }))}
            renderItem={(note) => (
              <Flex gap={3} justifyContent="between" alignItems="start" wrap>
                <Flex direction="column" gap={1}>
                  <Text weight="bold">{note.title}</Text>
                  {notePreview(note.body) ? (
                    <Text color="subtle" lineClamp={1}>
                      {notePreview(note.body)}
                    </Text>
                  ) : null}
                  {/* A note migrated out of the legacy notes field has no
                      write-time, so the row carries no date for it
                      rather than an invented one. */}
                  {localDate(note.created) ? (
                    <Text size="200" color="subtle">
                      {localDate(note.created)}
                    </Text>
                  ) : null}
                </Flex>
                <Flex gap={2}>
                  <Button
                    text="Edit"
                    size="sm"
                    color="gray"
                    accessibilityLabel={`Edit ${note.title}`}
                    onClick={() => setEditing(note)}
                  />
                  <Button
                    text="Delete"
                    size="sm"
                    color="transparent"
                    accessibilityLabel={`Delete ${note.title}`}
                    onClick={() => {
                      setRemoveError(null);
                      setRemoving(note);
                    }}
                  />
                </Flex>
              </Flex>
            )}
          />
          <Flex>{addButton}</Flex>
        </Flex>
      ) : (
        <EmptyState text="No notes yet." action={addButton} />
      )}
      {editing ? (
        <NotePopup
          note={editing.id ? editing : null}
          onSave={handleSave}
          onDismiss={() => setEditing(null)}
        />
      ) : null}
      {removing ? (
        <DeleteConfirmModal
          kind="note"
          name={removing.title}
          busy={removeBusy}
          error={removeError}
          onConfirm={handleRemove}
          onDismiss={() => {
            setRemoving(null);
            setRemoveError(null);
          }}
        />
      ) : null}
    </SectionCard>
  );
}
