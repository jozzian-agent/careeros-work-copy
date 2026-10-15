import { Box, Button, Checkbox, Fieldset, Flex, OverlayPanel, Text } from 'gestalt';

function GroupFieldset({ groupKey, legend, options, selected, onToggle }) {
  return (
    <Fieldset legend={legend}>
      <Flex direction="column">
        {options.length === 0 ? (
          <Text color="subtle" size="200">
            No data yet.
          </Text>
        ) : (
          options.map((option, index) => (
            <Box key={option.value} minHeight={44} display="flex" alignItems="center">
              <Flex flex="grow" justifyContent="between" alignItems="center" gap={2}>
                <Checkbox
                  id={`more-filter-${groupKey}-${index}`}
                  label={option.label}
                  checked={selected.includes(option.value)}
                  onChange={() => onToggle(option.value)}
                />
                <Text size="200" color="subtle">
                  {option.count}
                </Text>
              </Flex>
            </Box>
          ))
        )}
      </Flex>
    </Fieldset>
  );
}

// The More filters side panel, per the FilterPanels README: OverlayPanel,
// one Fieldset per group it is given, in that order, with the group's own
// `legend` wording ("(estimated)" on fields CareerOS classifies rather
// than ones the posting states directly). Checking a box filters
// immediately, same as the single-chip Popovers; "Show N jobs" and the
// panel's own dismiss button just close it.
export default function MoreFiltersPanel({
  groups,
  optionsByGroup,
  selected,
  onToggle,
  onClearAll,
  onDismiss,
  resultCount,
  countNoun,
}) {
  return (
    <OverlayPanel
      accessibilityLabel="More filters"
      heading="More filters"
      onDismiss={onDismiss}
      footer={
        <Flex justifyContent="between" alignItems="center">
          <Button text="Clear all" color="transparent" onClick={onClearAll} />
          <Button text={`Show ${resultCount} ${countNoun}`} color="red" onClick={onDismiss} />
        </Flex>
      }
    >
      <Flex direction="column" gap={4}>
        {groups.map(({ key, label, legend }) => (
          <GroupFieldset
            key={key}
            groupKey={key}
            legend={legend || label}
            options={optionsByGroup[key]}
            selected={selected[key]}
            onToggle={(value) => onToggle(key, value)}
          />
        ))}
      </Flex>
    </OverlayPanel>
  );
}
