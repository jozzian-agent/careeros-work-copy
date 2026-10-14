import { useEffect, useRef, useState } from 'react';
import { BannerSlim, Button, Checkbox, Flex, Modal, Tag, Text, TextArea, TextField } from 'gestalt';

function linesToList(text) {
  return text.split('\n').map((line) => line.trim()).filter(Boolean);
}

// Edit job: every owner-editable field of a job record that has no
// dedicated control elsewhere on the Job detail page (Status is its own
// control under the header; function and tags are Edit classification).
//
// The page labels the machine-made fields (summary, requirements,
// responsibilities, skills) as AI-made, so the owner must be able to
// correct every one of them: an AI label on a field with no edit surface
// is a dead end. The label disappears on its own once a correction saves,
// because the PUT stamps owner provenance on the keys it carries.
//
// Only description_structured's requirement lists change here, so
// summary/method are carried over unchanged and the whole key is omitted
// when neither list actually changed, to avoid marking owner provenance
// on an untouched field. The same rule applies to the summary,
// responsibilities and skills.
//
// `focus` names the field the page wants the owner to land on ('notes'
// from the empty Notes section's "Add a note").
export default function EditJobPopup({ job, focus, onSave, onDismiss }) {
  const structured = job.description_structured;
  const [title, setTitle] = useState(job.title || '');
  const [url, setUrl] = useState(job.url || '');
  const [location, setLocation] = useState(job.location || '');
  const [remoteOk, setRemoteOk] = useState(Boolean(job.remote_ok));
  const [notes, setNotes] = useState(job.notes || '');
  const [summary, setSummary] = useState(job.summary || '');
  const [requirements, setRequirements] = useState((structured?.requirements || []).join('\n'));
  const [niceToHave, setNiceToHave] = useState((structured?.nice_to_have || []).join('\n'));
  const [responsibilities, setResponsibilities] = useState((job.responsibilities || []).join('\n'));
  const [skills, setSkills] = useState(job.skills || []);
  const [newSkill, setNewSkill] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const notesRef = useRef(null);

  useEffect(() => {
    if (focus === 'notes' && notesRef.current) notesRef.current.focus();
  }, [focus]);

  function addSkill() {
    const value = newSkill.trim();
    if (!value || skills.includes(value)) return;
    setSkills((prev) => [...prev, value]);
    setNewSkill('');
  }

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      const payload = { title: title.trim(), url: url.trim(), location, remote_ok: remoteOk, notes };
      if (summary !== (job.summary || '')) payload.summary = summary;
      const newResponsibilities = linesToList(responsibilities);
      if (newResponsibilities.join('\n') !== (job.responsibilities || []).join('\n')) {
        payload.responsibilities = newResponsibilities;
      }
      if (skills.join('\n') !== (job.skills || []).join('\n')) payload.skills = skills;
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
          id="edit-job-summary"
          label="Summary"
          helperText="What the role is, in your own words."
          rows={3}
          value={summary}
          onChange={({ value }) => setSummary(value)}
        />
        {structured ? (
          <TextArea
            id="edit-job-requirements"
            label="Requirements, must have"
            helperText="One requirement per line."
            rows={4}
            value={requirements}
            onChange={({ value }) => setRequirements(value)}
          />
        ) : null}
        {structured ? (
          <TextArea
            id="edit-job-nice-to-have"
            label="Requirements, nice to have"
            helperText="One item per line."
            rows={3}
            value={niceToHave}
            onChange={({ value }) => setNiceToHave(value)}
          />
        ) : null}
        <TextArea
          id="edit-job-responsibilities"
          label="Responsibilities"
          helperText="One responsibility per line."
          rows={3}
          value={responsibilities}
          onChange={({ value }) => setResponsibilities(value)}
        />
        <Flex direction="column" gap={2}>
          <Text size="200" weight="bold">
            Skills
          </Text>
          {skills.length ? (
            <Flex gap={2} wrap>
              {skills.map((skill) => (
                <Tag
                  key={skill}
                  text={skill}
                  accessibilityRemoveIconLabel={`Remove ${skill}`}
                  onRemove={() => setSkills((prev) => prev.filter((value) => value !== skill))}
                />
              ))}
            </Flex>
          ) : (
            <Text color="subtle" size="200">
              No skills yet.
            </Text>
          )}
          <Flex gap={2} alignItems="end">
            <TextField
              id="edit-job-new-skill"
              label="Add a skill"
              value={newSkill}
              onChange={({ value }) => setNewSkill(value)}
            />
            <Button text="Add" color="gray" disabled={!newSkill.trim()} onClick={addSkill} />
          </Flex>
        </Flex>
        <TextArea
          ref={notesRef}
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
