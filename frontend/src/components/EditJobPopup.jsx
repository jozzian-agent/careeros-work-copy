import { useState } from 'react';
import { BannerSlim, Button, Checkbox, Flex, Modal, TextArea, TextField } from 'gestalt';

function linesToList(text) {
  return text.split('\n').map((line) => line.trim()).filter(Boolean);
}

// Edit job: title, posting link, location, remote, notes -- the record's
// directly owner-editable text fields with no dedicated control elsewhere
// on the Job detail page (Status and Fit are their own dropdowns under the
// header; Function/tags are Edit criteria). Per the approved JOZ-280 Phase
// A wireframe (frontend/wireframes/joz280/edit-job.html). Saves via the
// existing PUT /api/jobs/<id>.
//
// JOZ-267 fix round 1 finding 6: generated requirements/nice_to_have have
// no edit surface of their own, so a wrong AI-generated line can never be
// corrected. This is the existing edit surface every other owner-editable
// job field already saves through, extended with the same two lists; only
// description_structured's requirements/nice_to_have change here, so
// summary/method are carried over unchanged and the whole key is omitted
// when neither list actually changed, to avoid marking owner provenance
// on an untouched field.
export default function EditJobPopup({ job, onSave, onDismiss }) {
  const structured = job.description_structured;
  const [title, setTitle] = useState(job.title || '');
  const [url, setUrl] = useState(job.url || '');
  const [location, setLocation] = useState(job.location || '');
  const [remoteOk, setRemoteOk] = useState(Boolean(job.remote_ok));
  const [notes, setNotes] = useState(job.notes || '');
  const [requirements, setRequirements] = useState((structured?.requirements || []).join('\n'));
  const [niceToHave, setNiceToHave] = useState((structured?.nice_to_have || []).join('\n'));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      const payload = { title: title.trim(), url: url.trim(), location, remote_ok: remoteOk, notes };
      if (structured) {
        const newRequirements = linesToList(requirements);
        const newNiceToHave = linesToList(niceToHave);
        if (newRequirements.join('\n') !== (structured.requirements || []).join('\n')
            || newNiceToHave.join('\n') !== (structured.nice_to_have || []).join('\n')) {
          payload.description_structured = {
            ...structured, requirements: newRequirements, nice_to_have: newNiceToHave,
          };
        }
      }
      await onSave(payload);
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
        {structured ? (
          <TextArea
            id="edit-job-requirements"
            label="Requirements"
            helperText="One requirement per line."
            rows={4}
            value={requirements}
            onChange={({ value }) => setRequirements(value)}
          />
        ) : null}
        {structured ? (
          <TextArea
            id="edit-job-nice-to-have"
            label="Nice to have"
            helperText="One item per line."
            rows={3}
            value={niceToHave}
            onChange={({ value }) => setNiceToHave(value)}
          />
        ) : null}
      </Flex>
    </Modal>
  );
}

