import { useRef, useState } from 'react';
import { Box, Button, Flex, Popover, Tag, Text } from 'gestalt';
import FilterChip from './FilterChip.jsx';
import FilterPopoverPanel from './FilterPopoverPanel.jsx';
import MoreFiltersPanel from './MoreFiltersPanel.jsx';

// The filter row above the board/list, per the FilterBar README: one chip
// per filter group in the order given, then "More filters" when any group
// lives in that panel, a divider, the needs-your-input toggle, and the
// result count on the right, plus the active-filters Tag row with Clear
// all. One Popover (or the More filters OverlayPanel) is open at a time,
// anchored off the chip that opened it.
//
// The groups, the word the count counts ("jobs", "companies") and the
// toggle's label are the surface's to name, so the same bar serves the
// Jobs board and the Companies directory: a group with `inMore` moves
// from its own chip into the More filters panel, where `legend` is the
// fieldset's wording.
export default function FilterBar({
  groups,
  countNoun,
  needsLabel,
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

  const popoverGroups = groups.filter((group) => !group.inMore);
  const moreGroups = groups.filter((group) => group.inMore);
  const anyGroupActive = groups.some(({ key }) => selected[key].length > 0);
  const filtersActive = anyGroupActive || needsAttention;
  const moreCount = moreGroups.reduce((sum, { key }) => sum + selected[key].length, 0);

  return (
    <Box marginBottom={4}>
      <Flex gap={3} alignItems="center" wrap>
        {popoverGroups.map(({ key, label }) => (
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
        {moreGroups.length > 0 ? (
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
        ) : null}
        <Box width={1} height={24} dangerouslySetInlineStyle={{ __style: { background: 'var(--color-border-container)' } }} />
        <FilterChip
          label={needsLabel}
          count={needsAttentionCount}
          countColor="var(--color-brand-violet)"
          dataTestId="filter-chip-needs-attention"
          selected={needsAttention}
          pressed={needsAttention}
          onClick={onToggleNeedsAttention}
        />
        <Box marginStart="auto">
          <Text color="subtle" size="200">
            {filtersActive ? `${resultCount} of ${totalCount} ${countNoun}` : `${totalCount} ${countNoun}`}
          </Text>
        </Box>
      </Flex>

      {filtersActive ? (
        <Box marginTop={3}>
          <Flex gap={2} alignItems="center" wrap>
            <Text color="subtle" size="200">
              Active filters
            </Text>
            {groups.flatMap(({ key, label }) =>
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
                text={needsLabel}
                accessibilityRemoveIconLabel={`Remove ${needsLabel}`}
                onRemove={onToggleNeedsAttention}
              />
            ) : null}
            <Button
              text="Clear all"
              color="transparent"
              size="sm"
              onClick={() => {
                onClearGroups(groups.map(({ key }) => key));
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
            label={popoverGroups.find((group) => group.key === openPanel).label}
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
          groups={moreGroups}
          optionsByGroup={optionsByGroup}
          selected={selected}
          onToggle={onToggleValue}
          onClearAll={() => onClearGroups(moreGroups.map(({ key }) => key))}
          onDismiss={() => setOpenPanel(null)}
          resultCount={resultCount}
          countNoun={countNoun}
        />
      ) : null}
    </Box>
  );
}
