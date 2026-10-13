import { useState } from 'react';
import { BannerSlim, Button, Flex, Modal, TextArea } from 'gestalt';

// Fetch failure resume path (spec Section 3 step 5): the job stays visible
// as fetch_failed with Retry fetch and Paste posting text manually.
// Pasting text here resumes extraction through the same worker /extract
// uses (POST /api/jobs/<id>/paste-description).
export default function PasteDescriptionPopup({ onSave, onDismiss }) {
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      await onSave(description.trim());
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      accessibilityModalLabel="Paste posting text"
      heading="Paste posting text"
      size={480}
      onDismiss={onDismiss}
      footer={
        <Flex gap={2} justifyContent="end">
          <Button text="Cancel" onClick={onDismiss} />
          <Button
            text="Save and extract"
            color="red"
            disabled={busy || !description.trim()}
            onClick={handleSave}
          />
        </Flex>
      }
    >
      <Flex direction="column" gap={3}>
        {error ? <BannerSlim type="error" message={error} /> : null}
        <TextArea
          id="paste-description-text"
          label="Posting text"
          placeholder="Paste the job posting text here"
          rows={10}
          value={description}
          onChange={({ value }) => setDescription(value)}
        />
      </Flex>
    </Modal>
  );
}
