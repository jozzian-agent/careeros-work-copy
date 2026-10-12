import { useState } from 'react';
import { BannerSlim, Box, Button, Checkbox, Fieldset, Flex, Modal, Text, TextArea, TextField } from 'gestalt';
import { linkExperienceCompany } from '../api/experiences.js';

function slugify(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function matchCompanyByName(companies, name) {
  const target = name.trim().toLowerCase();
  return Object.values(companies).find((c) => (c.name || '').trim().toLowerCase() === target) || null;
}

// Edit position: the full experience_form.html field set ported into a
// popup (owner-approved default: carry the full form in, not a trimmed
// subset). Company is a text field with live match-or-create status, same
// as today's form. Tag facets exclude "function" (governed by its own
// proposal flow, never hand-edited here). Salary stays read-only. Per the
// approved JOZ-280 Phase A wireframe
// (frontend/wireframes/joz280/edit-position.html). Saves via the existing
// PUT /api/experiences/<id>; a pending company create goes through the
// existing POST .../link-company the same way the current form does it.
export default function EditPositionPopup({ exp, companies, tagRegistry, onSave, onDismiss }) {
  const [title, setTitle] = useState(exp.title || '');
  const [start, setStart] = useState(exp.start || '');
  const [end, setEnd] = useState(exp.end || '');
  const [location, setLocation] = useState(exp.location || '');
  const [companyName, setCompanyName] = useState(exp.company || '');
  const [companyId, setCompanyId] = useState(exp.company_id || null);
  const [peopleLed, setPeopleLed] = useState(exp.people_led ?? '');
  const [summary, setSummary] = useState(exp.summary || '');
  const [highlights, setHighlights] = useState((exp.highlights || []).join('\n'));
  const [detail, setDetail] = useState(exp.detail || '');
  const functionTags = (exp.tags || []).filter((tag) => tag.startsWith('function:'));
  const [tags, setTags] = useState((exp.tags || []).filter((tag) => !tag.startsWith('function:')));
  const [newSkill, setNewSkill] = useState('');
  const [custom, setCustom] = useState(
    Object.entries(exp.custom || {}).map(([key, value]) => ({
      key,
      value: typeof value === 'string' ? value : JSON.stringify(value),
    })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const matched = matchCompanyByName(companies, companyName);
  const linkStatus = companyId
    ? `Linked to ${companies[companyId]?.name || companyName}`
    : matched
      ? `Linked to ${matched.name}`
      : 'Not linked';

  function handleCompanyNameChange(value) {
    setCompanyName(value);
    const match = matchCompanyByName(companies, value);
    setCompanyId(match ? match.id : null);
  }

  async function handleCreateCompany() {
    const name = companyName.trim();
    if (!name) return;
    try {
      let response = await linkExperienceCompany(exp.id, { create: { name } });
      if (response.suggestion) {
        const useSuggestion = window.confirm(
          `Did you mean "${response.suggestion.name}"? Choose OK to link to it, or Cancel to create a new company named "${name}".`,
        );
        response = useSuggestion
          ? await linkExperienceCompany(exp.id, { company_id: response.suggestion.id })
          : await linkExperienceCompany(exp.id, { create: { name }, confirm_create: true });
      }
      setCompanyId(response.company_id || null);
    } catch (err) {
      setError(err.message);
    }
  }

  function toggleTag(token, checked) {
    setTags((prev) => (checked ? [...prev, token] : prev.filter((v) => v !== token)));
  }

  function addSkill() {
    const raw = slugify(newSkill.trim());
    if (!raw) return;
    const token = `skill/capability:${raw}`;
    if (!tags.includes(token)) setTags((prev) => [...prev, token]);
    setNewSkill('');
  }

  function addCustomRow() {
    setCustom((prev) => [...prev, { key: '', value: '' }]);
  }

  function updateCustomRow(index, field, value) {
    setCustom((prev) => prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  }

  function removeCustomRow(index) {
    setCustom((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      const customObject = {};
      for (const row of custom) {
        const key = row.key.trim();
        if (!key) continue;
        let value = row.value;
        try {
          value = JSON.parse(row.value);
        } catch {
          // Plain text value; keep as given.
        }
        customObject[key] = value;
      }
      await onSave({
        title: title.trim(),
        start,
        end,
        location,
        company: companyName.trim(),
        company_id: companyId,
        people_led: peopleLed === '' ? null : Number(peopleLed),
        summary,
        highlights: highlights.split('\n').map((line) => line.trim()).filter(Boolean),
        detail,
        tags: [...tags, ...functionTags],
        custom: customObject,
      });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      accessibilityModalLabel="Edit position"
      heading="Edit position"
      size={720}
      onDismiss={onDismiss}
      footer={
        <Flex gap={2} justifyContent="end">
          <Button text="Cancel" onClick={onDismiss} />
          <Button text="Save position" color="red" disabled={busy || !title.trim()} onClick={handleSave} />
        </Flex>
      }
    >
      <Flex direction="column" gap={4}>
        {error ? <BannerSlim type="error" message={error} /> : null}
        <Flex gap={3} wrap>
          <Box minWidth={220} flex="grow">
            <TextField id="edit-position-title" label="Title" value={title} onChange={({ value }) => setTitle(value)} />
          </Box>
          <Box minWidth={160}>
            <TextField id="edit-position-start" label="Start (YYYY-MM)" value={start} onChange={({ value }) => setStart(value)} />
          </Box>
          <Box minWidth={160}>
            <TextField
              id="edit-position-end"
              label="End (YYYY-MM or present)"
              value={end}
              onChange={({ value }) => setEnd(value)}
            />
          </Box>
          <Box minWidth={160}>
            <TextField id="edit-position-location" label="Location" value={location} onChange={({ value }) => setLocation(value)} />
          </Box>
        </Flex>
        <Flex direction="column" gap={2}>
          <TextField
            id="edit-position-company"
            label="Company"
            value={companyName}
            onChange={({ value }) => handleCompanyNameChange(value)}
          />
          <Flex gap={2} alignItems="center">
            <Text color="subtle">{linkStatus}</Text>
            {!companyId && companyName.trim() ? (
              <Button text="Create &amp; link new company" size="sm" onClick={handleCreateCompany} />
            ) : null}
          </Flex>
        </Flex>
        <Box maxWidth={220}>
          <TextField
            id="edit-position-people-led"
            type="number"
            label="People led"
            value={String(peopleLed)}
            onChange={({ value }) => setPeopleLed(value)}
          />
        </Box>
        <TextArea
          id="edit-position-summary"
          label="Summary (2–4 sentences)"
          rows={3}
          value={summary}
          onChange={({ value }) => setSummary(value)}
        />
        <TextArea
          id="edit-position-highlights"
          label="Highlights (one per line)"
          rows={4}
          value={highlights}
          onChange={({ value }) => setHighlights(value)}
        />
        <TextArea
          id="edit-position-detail"
          label="Detail (paragraphs, lists, **bold** and *italic*)"
          rows={6}
          value={detail}
          onChange={({ value }) => setDetail(value)}
        />
        <Fieldset legend="Skills">
          <Flex direction="column" gap={3}>
            <Flex gap={3} wrap>
              {tags.map((token) => {
                const [facet] = token.split(':');
                const info = tagRegistry.facets[facet];
                const value = info?.values?.find((v) => token === `${facet}:${v.id}`);
                return (
                  <Checkbox
                    key={token}
                    id={`edit-position-tag-${token}`}
                    label={value?.label || token}
                    checked
                    onChange={({ checked }) => toggleTag(token, checked)}
                  />
                );
              })}
            </Flex>
            <Flex gap={2} alignItems="end">
              <Box minWidth={220}>
                <TextField
                  id="edit-position-new-skill"
                  label="Propose a new skill tag"
                  placeholder="e.g. Public speaking"
                  value={newSkill}
                  onChange={({ value }) => setNewSkill(value)}
                />
              </Box>
              <Button text="Add" onClick={addSkill} disabled={!newSkill.trim()} />
            </Flex>
          </Flex>
        </Fieldset>
        <Fieldset legend="Custom fields" helperText="Values may be plain text or JSON for structured data.">
          <Flex direction="column" gap={2}>
            {custom.map((row, index) => (
              <Flex key={index} gap={2}>
                <TextField
                  id={`edit-position-custom-key-${index}`}
                  label="Key"
                  labelDisplay="hidden"
                  value={row.key}
                  onChange={({ value }) => updateCustomRow(index, 'key', value)}
                />
                <TextField
                  id={`edit-position-custom-value-${index}`}
                  label="Value"
                  labelDisplay="hidden"
                  value={row.value}
                  onChange={({ value }) => updateCustomRow(index, 'value', value)}
                />
                <Button text="Remove" size="sm" onClick={() => removeCustomRow(index)} />
              </Flex>
            ))}
            <Box>
              <Button text="Add custom field" onClick={addCustomRow} />
            </Box>
          </Flex>
        </Fieldset>
        <TextField
          id="edit-position-salary"
          label="Salary"
          value="Managed in the vault file only"
          disabled
          helperText="Compensation is private and cannot be changed here."
          onChange={() => {}}
        />
      </Flex>
    </Modal>
  );
}
