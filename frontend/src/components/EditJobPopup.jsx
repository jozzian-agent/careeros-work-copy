import { useState } from 'react';
import { BannerSlim, Button, Checkbox, Flex, Modal, Tag, Text, TextArea, TextField } from 'gestalt';
import { FALLBACK_GROUP, LANGUAGES_GROUP, LEVEL_LABELS } from '../requirements.js';

function linesToList(text) {
  return text.split('\n').map((line) => line.trim()).filter(Boolean);
}

function entryKey(entry) {
  return `${entry.group}:${entry.level}:${entry.text}`;
}

// Order-insensitive, because saving rebuilds the list group by group: a
// save that reordered nothing and changed nothing must not send the field
// at all, or an untouched field would pick up owner provenance.
function listKey(entries) {
  return entries.map(entryKey).sort().join('\n');
}

function linesFor(groups, level) {
  return groups.filter((entry) => entry.level === level && entry.group !== LANGUAGES_GROUP)
    .map((entry) => entry.text);
}

function groupFor(groups, text) {
  const match = groups.find((entry) => entry.text.trim().toLowerCase() === text.trim().toLowerCase());
  return match && match.group !== LANGUAGES_GROUP ? match.group : FALLBACK_GROUP;
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
// Which field the requirement controls write depends on what the job
// stores. A job with grouped requirements (package 2) renders those on
// the page, so the two requirement fields and the languages editor write
// `requirement_groups`; a job that has not been re-extracted yet renders
// its flat lists, so they write `description_structured` as before. Only
// the requirement lists change either way: summary and method are
// carried over unchanged, and a key is omitted entirely when nothing in
// it actually changed, so an untouched field never gets owner
// provenance. The same rule applies to the summary, responsibilities and
// skills.
//
// Notes are not here: a note is its own record with its own window
// (NotePopup), opened from the Notes section.
export default function EditJobPopup({ job, onSave, onDismiss }) {
  const structured = job.description_structured;
  const groups = job.requirement_groups || [];
  const grouped = groups.length > 0;
  const storedLanguages = groups.filter((entry) => entry.group === LANGUAGES_GROUP);
  const [title, setTitle] = useState(job.title || '');
  const [url, setUrl] = useState(job.url || '');
  const [location, setLocation] = useState(job.location || '');
  const [remoteOk, setRemoteOk] = useState(Boolean(job.remote_ok));
  const [summary, setSummary] = useState(job.summary || '');
  const [requirements, setRequirements] = useState(
    (grouped ? linesFor(groups, 'must') : structured?.requirements || []).join('\n'),
  );
  const [niceToHave, setNiceToHave] = useState(
    (grouped ? linesFor(groups, 'nice') : structured?.nice_to_have || []).join('\n'),
  );
  const [languages, setLanguages] = useState(storedLanguages);
  const [newLanguage, setNewLanguage] = useState('');
  const [responsibilities, setResponsibilities] = useState((job.responsibilities || []).join('\n'));
  const [skills, setSkills] = useState(job.skills || []);
  const [newSkill, setNewSkill] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  function addSkill() {
    const value = newSkill.trim();
    if (!value || skills.includes(value)) return;
    setSkills((prev) => [...prev, value]);
    setNewSkill('');
  }

  // A language the owner types is one the posting asks for, so it is a
  // must-have; a nice-to-have one keeps the level the extraction gave it
  // for as long as it is not removed.
  function addLanguage() {
    const value = newLanguage.trim();
    if (!value || languages.some((entry) => entry.text.toLowerCase() === value.toLowerCase())) return;
    setLanguages((prev) => [...prev, { group: LANGUAGES_GROUP, level: 'must', text: value }]);
    setNewLanguage('');
  }

  // The grouped requirements this popup would save: the two line fields
  // keep each line's own group, and the languages editor owns the
  // languages block outright.
  function editedGroups() {
    return [
      ...linesToList(requirements).map((text) => ({ group: groupFor(groups, text), level: 'must', text })),
      ...linesToList(niceToHave).map((text) => ({ group: groupFor(groups, text), level: 'nice', text })),
      ...languages,
    ];
  }

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      const payload = { title: title.trim(), url: url.trim(), location, remote_ok: remoteOk };
      if (summary !== (job.summary || '')) payload.summary = summary;
      const newResponsibilities = linesToList(responsibilities);
      if (newResponsibilities.join('\n') !== (job.responsibilities || []).join('\n')) {
        payload.responsibilities = newResponsibilities;
      }
      if (skills.join('\n') !== (job.skills || []).join('\n')) payload.skills = skills;
      if (grouped) {
        const edited = editedGroups();
        if (listKey(edited) !== listKey(groups)) payload.requirement_groups = edited;
      } else if (structured) {
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
        {grouped || structured ? (
          <TextArea
            id="edit-job-requirements"
            label="Requirements, must have"
            helperText="One requirement per line."
            rows={4}
            value={requirements}
            onChange={({ value }) => setRequirements(value)}
          />
        ) : null}
        {grouped || structured ? (
          <TextArea
            id="edit-job-nice-to-have"
            label="Requirements, nice to have"
            helperText="One item per line."
            rows={3}
            value={niceToHave}
            onChange={({ value }) => setNiceToHave(value)}
          />
        ) : null}
        {/* Languages are their own group, and a language is a word rather
            than a sentence, so they are tags like skills instead of
            lines in the two fields above. A job with no grouped
            requirements has nowhere to store them, which is why this
            waits for the first re-extraction of that job. */}
        {grouped ? (
          <Flex direction="column" gap={2}>
            <Text size="200" weight="bold">
              Languages
            </Text>
            {['must', 'nice'].filter((level) => languages.some((entry) => entry.level === level)).map((level) => (
              <Flex key={level} direction="column" gap={1}>
                <Text size="200" color="subtle">
                  {LEVEL_LABELS[level]}
                </Text>
                <Flex gap={2} wrap>
                  {languages.filter((entry) => entry.level === level).map((entry) => (
                    <Tag
                      key={entryKey(entry)}
                      text={entry.text}
                      accessibilityRemoveIconLabel={`Remove ${entry.text} from languages`}
                      onRemove={() => setLanguages((prev) => prev.filter((item) => item !== entry))}
                    />
                  ))}
                </Flex>
              </Flex>
            ))}
            {languages.length ? null : (
              <Text color="subtle" size="200">
                No languages yet.
              </Text>
            )}
            <Flex gap={2} alignItems="end">
              <TextField
                id="edit-job-new-language"
                label="Add a language"
                helperText="A language you add counts as a must-have."
                value={newLanguage}
                onChange={({ value }) => setNewLanguage(value)}
              />
              <Button
                text="Add"
                accessibilityLabel="Add a language"
                color="gray"
                disabled={!newLanguage.trim()}
                onClick={addLanguage}
              />
            </Flex>
          </Flex>
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
      </Flex>
    </Modal>
  );
}
