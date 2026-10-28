import { useMemo, useState } from 'react';
import {
  BannerSlim, Box, Button, Checkbox, Fieldset, Flex, Modal, SelectList, Text, TextField,
} from 'gestalt';

function slugify(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

// Edit classification: one popup, two variants.
//
//   mode="job"     function (ESCO) and tags, with the linked company's
//                  sector shown read-only, because sector belongs to the
//                  company and not to one of its postings.
//   mode="company" the company's own sector and size, which is what the
//                  retired /companies/<id>/taxonomy page used to edit.
//
// One component rather than two: both variants ask "what kind of work is
// this, and in which industry", both save through an existing PUT
// (`/api/jobs/<id>`, `/api/companies/<id>`), and a second popup would be
// a second place to keep the same question's wording.
export default function EditClassificationPopup({
  mode = 'job', taxonomy, company, sectorOptions = [], sizeOptions = [], onSave, onDismiss,
}) {
  const isJob = mode === 'job';
  // M2 (CAREER-39, decision D3): the tag registry is shared vocabulary,
  // so adding a value to it is the admin's. Picking a value already in
  // it is a write to this job alone and stays open to everybody, which
  // is why only the propose half below is behind this flag.
  const { job, company: linkedCompany, function_options: functionOptions, isic_labels: isicLabels,
    tags: knownTags, tag_labels: tagLabels, tag_registry: tagRegistry,
    can_edit_shared: canProposeTags = false } = taxonomy || {};

  const [selectedFunctions, setSelectedFunctions] = useState(job?.function || []);
  const [tags, setTags] = useState(knownTags || []);
  const [registryPick, setRegistryPick] = useState('');
  const [newFacet, setNewFacet] = useState(
    Object.keys(tagRegistry?.facets || {}).find((facet) => facet !== 'function') || '',
  );
  const [newTagId, setNewTagId] = useState('');
  const [sector, setSector] = useState((company?.sectors || [])[0] || '');
  const [sizeClass, setSizeClass] = useState(company?.size_class || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const sectorChips = useMemo(
    () => (linkedCompany?.sectors || []).map((code) => isicLabels?.[code] || code),
    [linkedCompany, isicLabels],
  );

  function toggleFunction(id, checked) {
    setSelectedFunctions((prev) => (checked ? [...prev, id] : prev.filter((value) => value !== id)));
  }

  function toggleTag(token, checked) {
    setTags((prev) => (checked ? [...prev, token] : prev.filter((value) => value !== token)));
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
      if (isJob) {
        const proposedTags = tags.filter((tag) => !(knownTags || []).includes(tag));
        await onSave({ function: selectedFunctions, tags, proposed_tags: proposedTags });
      } else {
        // The company record keeps the ISIC list and the EU size class;
        // both are sent as the owner's answer, empty meaning "clear it".
        await onSave({ sectors: sector ? [sector] : [], size_class: sizeClass || null });
      }
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  const registryOptions = Object.entries(tagRegistry?.facets || {})
    .filter(([facet]) => facet !== 'function')
    .flatMap(([facet, info]) => (info.values || [])
      .filter((value) => !tags.includes(`${facet}:${value.id}`))
      .map((value) => ({ value: `${facet}:${value.id}`, label: value.label || value.id })));

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
        {isJob ? (
          <>
            <Fieldset legend="Function (ESCO)" helperText="What the role actually does. Pick one or more.">
              <Flex direction="column" gap={2}>
                {(functionOptions || []).map(([id, label]) => (
                  <Checkbox
                    key={id}
                    id={`classification-function-${id}`}
                    label={label}
                    checked={selectedFunctions.includes(id)}
                    onChange={({ checked }) => toggleFunction(id, checked)}
                  />
                ))}
              </Flex>
            </Fieldset>
            <Fieldset
              legend="Sector"
              helperText={linkedCompany
                ? `Sector belongs to the company, not the job. Shown from ${linkedCompany.name}, where it is also edited.`
                : 'This job has no linked company.'}
            >
              <Flex gap={2} wrap>
                {sectorChips.length
                  ? sectorChips.map((chip) => <Text key={chip}>{chip}</Text>)
                  : <Text color="subtle">Not found in posting</Text>}
              </Flex>
            </Fieldset>
            <Fieldset
              legend="Tags"
              helperText={canProposeTags
                ? 'Controlled vocabulary: pick from the registry, or propose a new value.'
                : 'Controlled vocabulary: pick from the registry. Only the admin adds new values.'}
            >
              <Flex direction="column" gap={3}>
                <Flex gap={3} wrap>
                  {tags.map((token) => (
                    <Checkbox
                      key={token}
                      id={`classification-tag-${token}`}
                      label={tagLabels?.[token]?.label || token}
                      checked
                      onChange={({ checked }) => toggleTag(token, checked)}
                    />
                  ))}
                </Flex>
                <Flex gap={3} wrap>
                  <Box minWidth={220}>
                    <SelectList
                      id="classification-tag-registry"
                      label="Add from registry"
                      value={registryPick}
                      onChange={({ value }) => setRegistryPick(value)}
                    >
                      <SelectList.Option value="" label="Select a tag" />
                      {registryOptions.map((option) => (
                        <SelectList.Option key={option.value} value={option.value} label={option.label} />
                      ))}
                    </SelectList>
                  </Box>
                  {canProposeTags ? (
                    <Box minWidth={160}>
                      <SelectList
                        id="classification-new-tag-facet"
                        label="Facet"
                        value={newFacet}
                        onChange={({ value }) => setNewFacet(value)}
                      >
                        {Object.entries(tagRegistry?.facets || {})
                          .filter(([facet]) => facet !== 'function')
                          .map(([facet, info]) => (
                            <SelectList.Option key={facet} value={facet} label={info.label} />
                          ))}
                      </SelectList>
                    </Box>
                  ) : null}
                  {canProposeTags ? (
                    <Box minWidth={160}>
                      <TextField
                        id="classification-new-tag"
                        label="New tag id"
                        placeholder="e.g. machine-learning"
                        value={newTagId}
                        onChange={({ value }) => setNewTagId(value)}
                      />
                    </Box>
                  ) : null}
                </Flex>
                <Flex gap={2}>
                  <Button text="+ Add from registry" onClick={addFromRegistry} disabled={!registryPick} />
                  {canProposeTags ? (
                    <Button text="+ Add tag" onClick={addNewTag} disabled={!newTagId.trim()} />
                  ) : null}
                </Flex>
              </Flex>
            </Fieldset>
          </>
        ) : (
          <>
            <SelectList
              id="classification-company-sector"
              label="Sector"
              helperText="The industry section this company belongs to."
              value={sector}
              onChange={({ value }) => setSector(value)}
            >
              <SelectList.Option value="" label="Not set" />
              {sectorOptions.map((section) => (
                <SelectList.Option key={section.code} value={section.code} label={section.label} />
              ))}
            </SelectList>
            <SelectList
              id="classification-company-size"
              label="Size"
              helperText="How many people work there."
              value={sizeClass}
              onChange={({ value }) => setSizeClass(value)}
            >
              <SelectList.Option value="" label="Not set" />
              {/* [code, label] pairs, the shape functionOptions above
                  uses: the words are the taxonomy's and are not derived
                  from the code here, because `xl` is "Very large". */}
              {sizeOptions.map(([code, label]) => (
                <SelectList.Option key={code} value={code} label={label} />
              ))}
            </SelectList>
          </>
        )}
      </Flex>
    </Modal>
  );
}
