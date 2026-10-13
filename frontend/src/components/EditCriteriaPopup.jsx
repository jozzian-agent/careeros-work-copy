import { useMemo, useState } from 'react';
import { BannerSlim, Box, Button, Checkbox, Fieldset, Flex, Modal, SelectList, Text, TextField } from 'gestalt';

function slugify(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

// Edit criteria (job classification): function (ESCO) and tags, with the
// company's sector shown read-only. Per the approved JOZ-280 Phase A
// wireframe (frontend/wireframes/joz280/edit-criteria.html): this popup is
// scoped to job classification only -- Company Detail's own "Edit
// classification" link instead navigates to the full
// /companies/<id>/taxonomy page, which already has its own inline
// Save/Cancel. Saves via the existing PUT /api/jobs/<id> with
// function/tags/proposed_tags, the same payload shape job_taxonomy.html
// already sends.
export default function EditCriteriaPopup({ taxonomy, onSave, onDismiss }) {
  const { job, company, function_options: functionOptions, isic_labels: isicLabels,
    tags: knownTags, tag_labels: tagLabels, tag_registry: tagRegistry } = taxonomy;
  const [selectedFunctions, setSelectedFunctions] = useState(job.function || []);
  const [tags, setTags] = useState(knownTags || []);
  const [registryPick, setRegistryPick] = useState('');
  const [newFacet, setNewFacet] = useState(Object.keys(tagRegistry.facets).find((f) => f !== 'function') || '');
  const [newTagId, setNewTagId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const sectorChips = useMemo(
    () => (company?.sectors || []).map((code) => `${code} · ${isicLabels[code] || code}`),
    [company, isicLabels],
  );

  function toggleFunction(id, checked) {
    setSelectedFunctions((prev) => (checked ? [...prev, id] : prev.filter((v) => v !== id)));
  }

  function toggleTag(token, checked) {
    setTags((prev) => (checked ? [...prev, token] : prev.filter((v) => v !== token)));
  }

  function addFromRegistry() {
    if (!registryPick || tags.includes(registryPick)) return;
    setTags((prev) => [...prev, registryPick]);
    setRegistryPick('');
  }

  function addNewTag() {
    const raw = slugify(newTagId.trim());
    if (!raw) return;
    const token = `${newFacet}:${raw}`;
    if (tags.includes(token)) return;
    setTags((prev) => [...prev, token]);
    setNewTagId('');
  }

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      const proposedTags = tags.filter((tag) => !(knownTags || []).includes(tag));
      await onSave({ function: selectedFunctions, tags, proposed_tags: proposedTags });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  const registryOptions = Object.entries(tagRegistry.facets)
    .filter(([facet]) => facet !== 'function')
    .flatMap(([facet, info]) =>
      (info.values || [])
        .filter((v) => !tags.includes(`${facet}:${v.id}`))
        .map((v) => ({ value: `${facet}:${v.id}`, label: v.label || v.id })),
    );

  return (
    <Modal
      accessibilityModalLabel="Edit classification"
      heading="Edit classification"
      size={600}
      onDismiss={onDismiss}
      footer={
        <Flex gap={2} justifyContent="end">
          <Button text="Cancel" onClick={onDismiss} />
          <Button text="Save changes" color="red" disabled={busy} onClick={handleSave} />
        </Flex>
      }
    >
      <Flex direction="column" gap={4}>
        {error ? <BannerSlim type="error" message={error} /> : null}
        <Fieldset legend="Function (ESCO)" helperText="What the role actually does. Pick one or more.">
          <Flex direction="column" gap={2}>
            {functionOptions.map(([id, label]) => (
              <Checkbox
                key={id}
                id={`criteria-function-${id}`}
                label={label}
                checked={selectedFunctions.includes(id)}
                onChange={({ checked }) => toggleFunction(id, checked)}
              />
            ))}
          </Flex>
        </Fieldset>
        <Fieldset
          legend="Sector"
          helperText={
            company
              ? `Sector belongs to the company, not the job. Shown from ${company.name} — edit it on the company's Classification page.`
              : 'This job has no linked company.'
          }
        >
          <Flex gap={2} wrap>
            {sectorChips.length ? (
              sectorChips.map((chip) => <Text key={chip}>{chip}</Text>)
            ) : (
              <Text color="subtle">(not set)</Text>
            )}
          </Flex>
        </Fieldset>
        <Fieldset legend="Tags" helperText="Controlled vocabulary — pick from the registry, or propose a new value.">
          <Flex direction="column" gap={3}>
            <Flex gap={3} wrap>
              {tags.map((token) => (
                <Checkbox
                  key={token}
                  id={`criteria-tag-${token}`}
                  label={tagLabels[token]?.label || token}
                  checked
                  onChange={({ checked }) => toggleTag(token, checked)}
                />
              ))}
            </Flex>
            <Flex gap={3} wrap>
              <Box minWidth={220}>
                <SelectList
                  id="criteria-tag-registry"
                  label="Add from registry"
                  value={registryPick}
                  onChange={({ value }) => setRegistryPick(value)}
                >
                  <SelectList.Option value="" label="— select a tag —" />
                  {registryOptions.map((option) => (
                    <SelectList.Option key={option.value} value={option.value} label={option.label} />
                  ))}
                </SelectList>
              </Box>
              <Box minWidth={160}>
                <SelectList
                  id="criteria-new-tag-facet"
                  label="Facet"
                  value={newFacet}
                  onChange={({ value }) => setNewFacet(value)}
                >
                  {Object.entries(tagRegistry.facets)
                    .filter(([facet]) => facet !== 'function')
                    .map(([facet, info]) => (
                      <SelectList.Option key={facet} value={facet} label={info.label} />
                    ))}
                </SelectList>
              </Box>
              <Box minWidth={160}>
                <TextField
                  id="criteria-new-tag"
                  label="New tag id"
                  placeholder="e.g. machine-learning"
                  value={newTagId}
                  onChange={({ value }) => setNewTagId(value)}
                />
              </Box>
            </Flex>
            <Flex gap={2}>
              <Button text="+ Add from registry" onClick={addFromRegistry} disabled={!registryPick} />
              <Button text="+ Add tag" onClick={addNewTag} disabled={!newTagId.trim()} />
            </Flex>
          </Flex>
        </Fieldset>
      </Flex>
    </Modal>
  );
}
