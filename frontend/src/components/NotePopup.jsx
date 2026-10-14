import { useEffect, useRef, useState } from 'react';
import { BannerSlim, Button, Flex, Modal, TextArea, TextField } from 'gestalt';

// One note, in its own window. The owner asked for adding a note to open
// a separate editing window rather than the whole Edit job form, so this
// is the one surface a note is written on: the same window adds a new
// note and edits an existing one (`note` is null when adding), because
// writing a note and rewriting it are the same act.
//
// Same Gestalt Modal shape as EditJobPopup, since it is the same kind of
// thing: one record, a couple of fields, Save and Cancel.
export default function NotePopup({ note, onSave, onDismiss }) {
  const [title, setTitle] = useState(note?.title || '');
  const [body, setBody] = useState(note?.body || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const titleRef = useRef(null);
  const heading = note ? 'Edit note' : 'Add a note';

  // The window exists to be typed into, and the title is the field it
  // cannot be saved without.
  useEffect(() => {
    if (titleRef.current) titleRef.current.focus();
  }, []);

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      await onSave({ title: title.trim(), body });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      accessibilityModalLabel={heading}
      heading={heading}
      size={480}
      onDismiss={onDismiss}
      footer={
        <Flex gap={2} justifyContent="end">
          <Button text="Cancel" onClick={onDismiss} />
          <Button text="Save note" color="red" disabled={busy || !title.trim()} onClick={handleSave} />
        </Flex>
      }
    >
      <Flex direction="column" gap={3}>
        {error ? <BannerSlim type="error" message={error} /> : null}
        <TextField
          ref={titleRef}
          id="note-title"
          label="Title"
          value={title}
          onChange={({ value }) => setTitle(value)}
        />
        <TextArea
          id="note-body"
          label="Note"
          placeholder="What you want to remember about this"
          rows={8}
          value={body}
          onChange={({ value }) => setBody(value)}
        />
      </Flex>
    </Modal>
  );
}
