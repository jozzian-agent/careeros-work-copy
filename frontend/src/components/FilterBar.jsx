import { useRef, useState } from 'react';
import { Box, Button, Flex, Popover, Tag, Text } from 'gestalt';
import FilterChip from './FilterChip.jsx';
import FilterPopoverPanel from './FilterPopoverPanel.jsx';
import MoreFiltersPanel from './MoreFiltersPanel.jsx';

const POPOVER_GROUPS = [
  { key: 'fit', label: 'Fit' },
  { key: 'function', label: 'Function' },
  { key: 'location', label: 'Location' },
];
const MORE_GROUPS = [
  { key: 'industry', label: 'Industry' },
  { key: 'companySize', label: 'Company size' },
];
const ALL_GROUPS = [...POPOVER_GROUPS, ...MORE_GROUPS];

// The filter row above the board/list, per the FilterBar README: chip
// order Fit, Function, Location, More filters, a divider, Needs
// attention, then the result count on the right, plus the active-filters
// Tag row with Clear all. One Popover (or the More filters OverlayPanel)
// is open at a time, anchored off the chip that opened it.
export default function FilterBar({
  optionsByGroup,
  selected,
  onToggleValue,
  onClearGroup,
  onClearGroups,
  needsAttention,
  needsAttentionCount,
  onToggleNeedsAttention,
  resultCount,
  totalCount,
}) {
  const [openPanel, setOpenPanel] = useState(null);
  const anchors = useRef({});

  function setAnchor(key) {
    return (node) => {
      anchors.current[key] = node;
    };
  }

  function togglePanel(key) {
    setOpenPanel((current) => (current === key ? null : key));
  }

  const anyGroupActive = ALL_GROUPS.some(({ key }) => selected[key].length > 0);
  const filtersActive = anyGroupActive || needsAttention;
  const moreCount = MORE_GROUPS.reduce((sum, { key }) => sum + selected[key].length, 0);

  return (
    <Box marginBottom={4}>
      <Flex gap={3} alignItems="center" wrap>
        {POPOVER_GROUPS.map(({ key, label }) => (
          <FilterChip
            key={key}
            label={label}
            count={selected[key].length}
            selected={selected[key].length > 0}
            haspopup
            expanded={openPanel === key}
            chevron
            anchorRef={setAnchor(key)}
            onClick={() => togglePanel(key)}
            dataTestId={`filter-chip-${key}`}
          />
        ))}
        <FilterChip
          label="More filters"
          icon="filter"
          count={moreCount}
          selected={moreCount > 0}
          haspopup
          expanded={openPanel === 'more'}
          anchorRef={setAnchor('more')}
          onClick={() => togglePanel('more')}
          dataTestId="filter-chip-more"
        />
        <Box width={1} height={24} dangerouslySetInlineStyle={{ __style: { background: 'var(--color-border-container)' } }} />
        <FilterChip
          label="Needs attention"
          count={needsAttentionCount}
          countColor="var(--color-brand-violet)"
          dataTestId="filter-chip-needs-attention"
          selected={needsAttention}
          pressed={needsAttention}
          onClick={onToggleNeedsAttention}
        />
        <Box marginStart="auto">
          <Text color="subtle" size="200">
            {filtersActive ? `${resultCount} of ${totalCount} jobs` : `${totalCount} jobs`}
          </Text>
        </Box>
      </Flex>

      {filtersActive ? (
        <Box marginTop={3}>
          <Flex gap={2} alignItems="center" wrap>
            <Text color="subtle" size="200">
              Active filters
            </Text>
            {ALL_GROUPS.flatMap(({ key, label }) =>
              selected[key].map((value) => {
                const option = optionsByGroup[key].find((candidate) => candidate.value === value);
                const text = `${label}: ${option ? option.label : value}`;
                return (
                  <Tag
                    key={`${key}:${value}`}
                    text={text}
                    accessibilityRemoveIconLabel={`Remove ${text}`}
                    onRemove={() => onToggleValue(key, value)}
                  />
                );
              }),
            )}
            {needsAttention ? (
              <Tag
                text="Needs attention"
                accessibilityRemoveIconLabel="Remove Needs attention"
                onRemove={onToggleNeedsAttention}
              />
            ) : null}
            <Button
              text="Clear all"
              color="transparent"
              size="sm"
              onClick={() => {
                onClearGroups(ALL_GROUPS.map(({ key }) => key));
                if (needsAttention) onToggleNeedsAttention();
              }}
            />
          </Flex>
        </Box>
      ) : null}

      {openPanel && openPanel !== 'more' ? (
        <Popover anchor={anchors.current[openPanel]} onDismiss={() => setOpenPanel(null)} idealDirection="down" size="flexible">
          <FilterPopoverPanel
            groupKey={openPanel}
            label={POPOVER_GROUPS.find((group) => group.key === openPanel).label}
            options={optionsByGroup[openPanel]}
            selected={selected[openPanel]}
            onToggle={(value) => onToggleValue(openPanel, value)}
            onClear={() => onClearGroup(openPanel)}
            onDone={() => setOpenPanel(null)}
          />
        </Popover>
      ) : null}

      {openPanel === 'more' ? (
        <MoreFiltersPanel
          industryOptions={optionsByGroup.industry}
          companySizeOptions={optionsByGroup.companySize}
          selectedIndustry={selected.industry}
          selectedCompanySize={selected.companySize}
          onToggleIndustry={(value) => onToggleValue('industry', value)}
          onToggleCompanySize={(value) => onToggleValue('companySize', value)}
          onClearAll={() => onClearGroups(['industry', 'companySize'])}
          onDismiss={() => setOpenPanel(null)}
          resultCount={resultCount}
        />
      ) : null}
    </Box>
  );
}
