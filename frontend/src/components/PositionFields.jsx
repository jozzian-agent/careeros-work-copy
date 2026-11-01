import { Box, Button, Checkbox, Fieldset, Flex, SelectList, Text, TextArea, TextField } from 'gestalt';
import SectionCard from './SectionCard.jsx';
import { COMPANY_NOT_LINKED, EXPERIENCE_TYPE_FACET, taggableFacets } from '../positions.js';

// The one field set a position is written with, so the Add position page
// and (follow-up: "move edit to the same page") the edit page cannot drift
// apart. It owns the fields and nothing else: the caller holds the values,
// the errors and every write, which is what lets one set of fields serve a
// create (POST, no record yet) and an edit (PUT, a record to link against).
//
// Three cards, per the approved Add position artboard (2026-11-01): Role,
// What you did, Tags. Shaped as SectionCards rather than one long form,
// which is the same frame the detail pages read in.
//
// The field set is the old Jinja experience_form.html's, minus the salary
// row the owner dropped: compensation stays vault-file-only and no surface
// asks for it. Function tags are governed by their own proposal flow and
// are never editable here, which is why this component never shows the
// `function` facet and the caller round-trips the record's own function
// tags through the payload untouched.
//
// The rules that have nothing to do with drawing a field -- the facet
// filter, the company match, and the payload a write sends -- live in
// `src/positions.js`, so they can be tested without a browser.

export default function PositionFields({
  values,
  errors = {},
  onChange,
  // The company field is one text field here: which record a typed name
  // resolves to, and what to do when it resolves to none, is the caller's
  // (`positions.js` matchCompanyByName), because only the caller knows
  // whether there is a record to link against yet.
  companyLinkStatus,
  companyAction,
  tagRegistry = { facets: {} },
  canProposeTags = false,
  // Per-facet "propose a new value" drafts, held by the caller so that a
  // re-render of the page cannot lose a half-typed tag.
  tagDrafts = {},
  onTagDraftChange,
  onProposeTag,
  onRegistryPick,
  registryPicks = {},
}) {
  const facets = taggableFacets(tagRegistry);
  const tags = values.tags || [];
  const set = (field) => ({ value }) => onChange(field, value);

  function tagsOf(facet) {
    return tags.filter((token) => token.startsWith(`${facet}:`));
  }

  function toggleTag(token, checked) {
    onChange('tags', checked ? [...tags, token] : tags.filter((value) => value !== token));
  }

  function labelFor(facet, token) {
    const info = tagRegistry.facets[facet];
    const value = (info?.values || []).find((entry) => token === `${facet}:${entry.id}`);
    return value?.label || token.split(':').slice(1).join(':');
  }

  return (
    <Flex direction="column" gap={5}>
      <SectionCard title="Role">
        <Flex direction="column" gap={4}>
          <Flex gap={3} wrap>
            <Box minWidth={240} flex="grow">
              <TextField
                id="position-title"
                label="Title"
                value={values.title || ''}
                errorMessage={errors.title}
                onChange={set('title')}
              />
            </Box>
            <Box minWidth={240} flex="grow">
              <TextField
                id="position-company"
                label="Company"
                value={values.company || ''}
                onChange={set('company')}
              />
            </Box>
          </Flex>
          {/* The same status line the Edit position popup shows: whether
              this position resolves to a company record, and the one way
              to make it so when it does not. */}
          <Flex gap={2} alignItems="center" wrap>
            <Text color="subtle">{companyLinkStatus || COMPANY_NOT_LINKED}</Text>
            {companyAction}
          </Flex>
          <Flex gap={3} wrap>
            <Box minWidth={160}>
              <TextField
                id="position-start"
                label="Start (YYYY-MM)"
                value={values.start || ''}
                errorMessage={errors.start}
                onChange={set('start')}
              />
            </Box>
            <Box minWidth={160}>
              <TextField
                id="position-end"
                label="End (YYYY-MM or present)"
                value={values.end || ''}
                onChange={set('end')}
              />
            </Box>
            <Box minWidth={160}>
              <TextField
                id="position-location"
                label="Location"
                value={values.location || ''}
                errorMessage={errors.location}
                onChange={set('location')}
              />
            </Box>
            <Box minWidth={160}>
              <TextField
                id="position-people-led"
                type="number"
                label="People led"
                value={String(values.people_led ?? '')}
                onChange={set('people_led')}
              />
            </Box>
          </Flex>
        </Flex>
      </SectionCard>

      <SectionCard title="What you did">
        <Flex direction="column" gap={4}>
          <TextArea
            id="position-summary"
            label="Summary (2–4 sentences)"
            rows={3}
            value={values.summary || ''}
            onChange={set('summary')}
          />
          <TextArea
            id="position-highlights"
            label="Highlights (one per line)"
            rows={4}
            value={values.highlights || ''}
            onChange={set('highlights')}
          />
          <TextArea
            id="position-detail"
            label="Detail (paragraphs, lists, **bold** and *italic*)"
            rows={6}
            value={values.detail || ''}
            onChange={set('detail')}
          />
        </Flex>
      </SectionCard>

      <SectionCard title="Tags">
        <Flex direction="column" gap={4}>
          {facets.map(([facet, info]) => {
            const chosen = tagsOf(facet);
            // The experience type is a fixed list the registry ships
            // pre-populated, so every value is offered at once rather than
            // through a picker built for a vocabulary that grows.
            if (facet === EXPERIENCE_TYPE_FACET) {
              return (
                <Fieldset key={facet} legend={info.label}>
                  <Flex gap={3} wrap>
                    {(info.values || []).map((value) => {
                      const token = `${facet}:${value.id}`;
                      return (
                        <Checkbox
                          key={token}
                          id={`position-tag-${token}`}
                          label={value.label || value.id}
                          checked={tags.includes(token)}
                          onChange={({ checked }) => toggleTag(token, checked)}
                        />
                      );
                    })}
                  </Flex>
                </Fieldset>
              );
            }
            const options = (info.values || [])
              .filter((value) => !tags.includes(`${facet}:${value.id}`))
              .map((value) => ({ value: `${facet}:${value.id}`, label: value.label || value.id }));
            return (
              <Fieldset
                key={facet}
                legend={info.label}
                helperText={canProposeTags
                  ? 'Controlled vocabulary — pick from the registry, or propose a new value.'
                  : 'Controlled vocabulary — pick from the registry. Only the admin adds new values.'}
              >
                <Flex direction="column" gap={3}>
                  {chosen.length ? (
                    <Flex gap={3} wrap>
                      {chosen.map((token) => (
                        <Checkbox
                          key={token}
                          id={`position-tag-${token}`}
                          label={labelFor(facet, token)}
                          checked
                          onChange={({ checked }) => toggleTag(token, checked)}
                        />
                      ))}
                    </Flex>
                  ) : null}
                  <Flex gap={3} wrap alignItems="end">
                    <Box minWidth={220}>
                      <SelectList
                        id={`position-tag-registry-${facet}`}
                        label={`Add ${info.label.toLowerCase()} from registry`}
                        value={registryPicks[facet] || ''}
                        onChange={({ value }) => onRegistryPick?.(facet, value)}
                      >
                        <SelectList.Option value="" label="Select a tag" />
                        {options.map((option) => (
                          <SelectList.Option key={option.value} value={option.value} label={option.label} />
                        ))}
                      </SelectList>
                    </Box>
                    {canProposeTags ? (
                      <Box minWidth={220}>
                        <TextField
                          id={`position-new-tag-${facet}`}
                          label={`Propose a new ${info.label.toLowerCase()} tag`}
                          placeholder="e.g. Public speaking"
                          value={tagDrafts[facet] || ''}
                          onChange={({ value }) => onTagDraftChange?.(facet, value)}
                        />
                      </Box>
                    ) : null}
                    {canProposeTags ? (
                      // The accessible name carries the facet: a page with
                      // three of these would otherwise offer three buttons
                      // called the same thing.
                      <Button
                        text="+ Add tag"
                        accessibilityLabel={`Add ${info.label.toLowerCase()} tag`}
                        disabled={!(tagDrafts[facet] || '').trim()}
                        onClick={() => onProposeTag?.(facet)}
                      />
                    ) : null}
                  </Flex>
                </Flex>
              </Fieldset>
            );
          })}
          {/* The old form's custom fields, carried over: a position may
              hold key/value detail the schema has no column for. Values
              may be plain text or JSON, which is what the record stores. */}
          <Fieldset legend="Custom fields" helperText="Values may be plain text or JSON for structured data.">
            <Flex direction="column" gap={2}>
              {(values.custom || []).map((row, index) => (
                <Flex key={index} gap={2} alignItems="end">
                  <TextField
                    id={`position-custom-key-${index}`}
                    label="Key"
                    labelDisplay="hidden"
                    placeholder="Key"
                    value={row.key}
                    onChange={({ value }) => onChange('custom', (values.custom || []).map(
                      (entry, i) => (i === index ? { ...entry, key: value } : entry),
                    ))}
                  />
                  <TextField
                    id={`position-custom-value-${index}`}
                    label="Value"
                    labelDisplay="hidden"
                    placeholder="Value"
                    value={row.value}
                    onChange={({ value }) => onChange('custom', (values.custom || []).map(
                      (entry, i) => (i === index ? { ...entry, value } : entry),
                    ))}
                  />
                  <Button
                    text="Remove"
                    size="sm"
                    onClick={() => onChange('custom', (values.custom || []).filter((_, i) => i !== index))}
                  />
                </Flex>
              ))}
              <Box>
                <Button
                  text="Add custom field"
                  onClick={() => onChange('custom', [...(values.custom || []), { key: '', value: '' }])}
                />
              </Box>
            </Flex>
          </Fieldset>
        </Flex>
      </SectionCard>
    </Flex>
  );
}
