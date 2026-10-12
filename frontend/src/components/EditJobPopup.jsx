import { useState } from 'react';
import { BannerSlim, Button, Checkbox, Flex, Modal, TextArea, TextField } from 'gestalt';

// Edit job: title, posting link, location, remote, notes -- the record's
// directly owner-editable text fields with no dedicated control elsewhere
// on the Job detail page (Status and Fit are their own dropdowns under the
// header; Function/tags are Edit criteria). Per the approved JOZ-280 Phase
// A wireframe (frontend/wireframes/joz280/edit-job.html). Saves via the
// existing PUT /api/jobs/<id>.
export default function EditJobPopup({ job, onSave, onDismiss }) {
  const [title, setTitle] = useState(job.title || '');
  const [url, setUrl] = useState(job.url || '');
  const [location, setLocation] = useState(job.location || '');
  const [remoteOk, setRemoteOk] = useState(Boolean(job.remote_ok));
  const [notes, setNotes] = useState(job.notes || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      await onSave({ title: title.trim(), url: url.trim(), location, remote_ok: remoteOk, notes });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      accessibilityModalLabel="Edit job"
      heading="Edit job"
      size={480}
      onDismiss={onDismiss}
      footer={
        <Flex gap={2} justifyContent="end">
          <Button text="Cancel" onClick={onDismiss} />
          <Button text="Save job" color="red" disabled={busy || !title.trim()} onClick={handleSave} />
        </Flex>
      }
    >
      <Flex direction="column" gap={3}>
        {error ? <BannerSlim type="error" message={error} /> : null}
        <TextField id="edit-job-title" label="Title" value={title} onChange={({ value }) => setTitle(value)} />
        <TextField
          id="edit-job-url"
          type="url"
          label="Posting link"
          value={url}
          onChange={({ value }) => setUrl(value)}
        />
        <TextField
          id="edit-job-location"
          label="Location"
          value={location}
          onChange={({ value }) => setLocation(value)}
        />
        <Checkbox
          id="edit-job-remote"
          label="Remote OK"
          checked={remoteOk}
          onChange={({ checked }) => setRemoteOk(checked)}
        />
        <TextArea
          id="edit-job-notes"
          label="Notes"
          placeholder="Your private notes about this job"
          rows={4}
          value={notes}
          onChange={({ value }) => setNotes(value)}
        />
      </Flex>
    </Modal>
  );
}

