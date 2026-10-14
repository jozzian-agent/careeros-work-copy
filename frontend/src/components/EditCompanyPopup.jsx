import { useEffect, useRef, useState } from 'react';
import { BannerSlim, Button, Flex, Modal, TextArea, TextField } from 'gestalt';

// Edit company: name, website, locations, notes -- mirrors the current
// company profile form exactly (sector and size are Edit classification,
// not here). Per the approved JOZ-280 Phase A wireframe
// (frontend/wireframes/joz280/edit-company.html). Saves via the existing
// PUT /api/companies/<id>.
//
// `focus` names the field the page wants the owner to land on ('notes'
// from the empty Notes section's "Add a note").
export default function EditCompanyPopup({ company, focus, onSave, onDismiss }) {
  const [name, setName] = useState(company.name || '');
  const [website, setWebsite] = useState(company.website || '');
  const [locations, setLocations] = useState((company.locations || []).join('\n'));
  const [notes, setNotes] = useState(company.notes || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const notesRef = useRef(null);

  useEffect(() => {
    if (focus === 'notes' && notesRef.current) notesRef.current.focus();
  }, [focus]);

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      await onSave({
        name: name.trim(),
        website: website.trim() || null,
        locations: locations.split('\n').map((line) => line.trim()).filter(Boolean),
        notes,
      });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      accessibilityModalLabel="Edit company"
      heading="Edit company"
      size={480}
      onDismiss={onDismiss}
      footer={
        <Flex gap={2} justifyContent="end">
          <Button text="Cancel" onClick={onDismiss} />
          <Button text="Save company" color="red" disabled={busy || !name.trim()} onClick={handleSave} />
        </Flex>
      }
    >
      <Flex direction="column" gap={3}>
        {error ? <BannerSlim type="error" message={error} /> : null}
        <TextField id="edit-company-name" label="Name" value={name} onChange={({ value }) => setName(value)} />
        <TextField
          id="edit-company-website"
          type="url"
          label="Website"
          value={website}
          onChange={({ value }) => setWebsite(value)}
        />
        <TextArea
          id="edit-company-locations"
          label="Locations"
          helperText="One per line"
          rows={3}
          value={locations}
          onChange={({ value }) => setLocations(value)}
        />
        <TextArea
          ref={notesRef}
          id="edit-company-notes"
          label="Notes"
          placeholder="Your private notes about this company"
          rows={4}
          value={notes}
          onChange={({ value }) => setNotes(value)}
        />
      </Flex>
    </Modal>
  );
}
