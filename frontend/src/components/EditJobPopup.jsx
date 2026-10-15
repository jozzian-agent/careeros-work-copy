import { useState } from 'react';
import { BannerSlim, Button, Checkbox, Flex, Modal, Tag, Text, TextArea, TextField } from 'gestalt';
import { FALLBACK_GROUP, isGrouped, LANGUAGES_GROUP, LEVEL_LABELS } from '../requirements.js';

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

// A list of lines compares as its field shows it, one per line: that is
// the shape the owner edited, so a stored item carrying a newline of its
// own is not an edit they made.
function lineKey(list) {
  return list.join('\n');
}

// A flat block compares by its two lists only: the summary and the method
// a save carries over are not edited here.
function blockKey(block) {
  return JSON.stringify([lineKey(block.requirements), lineKey(block.nice_to_have)]);
}

// The one rule for every key this popup can send: a key belongs in the
// PUT only when its field differs from the value the job seeded it with.
// The PUT stamps owner provenance on every key it carries and marks the
// covered ones done, so a key sent unchanged credits the owner for a
// field they never edited, takes the AI label off it, reads an empty
// value as one they chose, drops the "Not found in posting" row and the
// setter that leads back here, and locks the field against every later
// reading. `shape` is how the key compares, defaulting to the value
// itself; a key whose stored shape says more than its field does passes
// its own (listKey, lineKey, blockKey above).
function addChanged(payload, key, value, seeded, shape = JSON.stringify) {
  if (shape(value) !== shape(seeded)) payload[key] = value;
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
// Which field the two requirement controls write is decided per field,
// not by one flag, because the extraction popup reports on both and
// sends the owner here for either of them: a control that wrote only one
// would leave the other row offering a setter that sets nothing.
//
// `requirement_groups` is written when the section renders the groups, and
// when the job stores no requirements at all, since the groups are the
// shape anything new goes into. It is left alone for a job still
// rendering its flat lists, because regrouping a job is what Re-extract
// is for and not a side effect of an edit, and the fallback group would
// bury every prose line of such a job under Skills.
//
// `description_structured` is written when the section renders its flat
// lists, and when the job has no block at all, so the Description row
// that says "Not found in posting" leads to a control that writes it. A
// block this popup creates records `method: 'user'`.
//
// Only the requirement lists change either way: a block's own summary is
// carried over, and a key is omitted entirely when nothing in it
// actually changed, so an untouched field never gets owner provenance.
// That is the rule for every field this popup holds, the title, the
// posting link, the location and the Remote OK box included: see
// `addChanged`.
//
// Notes are not here: a note is its own record with its own window
// (NotePopup), opened from the Notes section.
export default function EditJobPopup({ job, onSave, onDismiss }) {
  const structured = job.description_structured;
  const groups = job.requirement_groups || [];
  const grouped = isGrouped(job);
  const flatLines = [...(structured?.requirements || []), ...(structured?.nice_to_have || [])];
  const writeGroups = grouped || flatLines.length === 0;
  const writeBlock = !grouped || !structured;
  const storedLanguages = groups.filter((entry) => entry.group === LANGUAGES_GROUP);
  // What the two line fields are seeded with, which is also what a save
  // compares them against. The fields show the grouped lines on a grouped
  // job, so comparing them with the flat block's own lines reported a
  // change on every save of a grouped job that has no block, and sent a
  // block the owner never typed a word into -- which stamped owner
  // provenance on a field they never touched.
  const seededMust = grouped ? linesFor(groups, 'must') : structured?.requirements || [];
  const seededNice = grouped ? linesFor(groups, 'nice') : structured?.nice_to_have || [];
  const [title, setTitle] = useState(job.title || '');
  const [url, setUrl] = useState(job.url || '');
  const [location, setLocation] = useState(job.location || '');
  const [remoteOk, setRemoteOk] = useState(Boolean(job.remote_ok));
  const [summary, setSummary] = useState(job.summary || '');
  const [requirements, setRequirements] = useState(seededMust.join('\n'));
  const [niceToHave, setNiceToHave] = useState(seededNice.join('\n'));
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
  function editedGroups(mustLines, niceLines) {
    return [
      ...mustLines.map((text) => ({ group: groupFor(groups, text), level: 'must', text })),
      ...niceLines.map((text) => ({ group: groupFor(groups, text), level: 'nice', text })),
      ...languages,
    ];
  }

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      const payload = {};
      addChanged(payload, 'title', title.trim(), job.title || '');
      addChanged(payload, 'url', url.trim(), job.url || '');
      addChanged(payload, 'location', location, job.location || '');
      // A job no reading has answered this for stores null, which the
      // checkbox can only show as unchecked; sending the false back would
      // turn "nobody has said" into the owner saying no.
      addChanged(payload, 'remote_ok', remoteOk, Boolean(job.remote_ok));
      addChanged(payload, 'summary', summary, job.summary || '');
      addChanged(payload, 'responsibilities', linesToList(responsibilities),
                 job.responsibilities || [], lineKey);
      addChanged(payload, 'skills', skills, job.skills || [], lineKey);
      const newRequirements = linesToList(requirements);
      const newNiceToHave = linesToList(niceToHave);
      if (writeGroups) {
        addChanged(payload, 'requirement_groups',
                   editedGroups(newRequirements, newNiceToHave), groups, listKey);
      }
      if (writeBlock) {
        addChanged(payload, 'description_structured', {
          // The block's own summary is not edited here (the Summary field
          // above writes the job's summary), so it is carried over. The
          // method is this popup's own: these lines are the owner's now,
          // whoever read the ones they replaced.
          summary: structured?.summary || '', method: 'user',
          requirements: newRequirements, nice_to_have: newNiceToHave,
        }, { requirements: seededMust, nice_to_have: seededNice }, blockKey);
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
        {/* Always here, whatever the job stores. The extraction popup
            sends the owner to Edit job for requirements a posting did not
            yield, so hiding the fields on a job that stores none made
            that button a dead end, which is exactly the case it exists
            for. */}
        <TextArea
          id="edit-job-requirements"
          label="Requirements, must have"
          helperText="One requirement per line."
          rows={4}
          value={requirements}
          onChange={({ value }) => setRequirements(value)}
        />
        <TextArea
          id="edit-job-nice-to-have"
          label="Requirements, nice to have"
          helperText="One item per line."
          rows={3}
          value={niceToHave}
          onChange={({ value }) => setNiceToHave(value)}
        />
        {/* Languages are their own group, and a language is a word rather
            than a sentence, so they are tags like skills instead of
            lines in the two fields above. A language can only be stored
            in the groups, so this editor appears exactly when this popup
            writes them: a job still rendering its flat lists has nowhere
            to put one until the owner re-extracts it. */}
        {writeGroups ? (
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
