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

// The More filters side panel (Industry, Company size), per the
// FilterPanels README: OverlayPanel, one Fieldset per group, "(estimated)"
// on fields CareerOS classifies rather than ones the posting states
// directly. Checking a box filters the board immediately, same as the
// single-chip Popovers; "Show N jobs" and the panel's own dismiss button
// just close it.
export default function MoreFiltersPanel({
  industryOptions,
  companySizeOptions,
  selectedIndustry,
  selectedCompanySize,
  onToggleIndustry,
  onToggleCompanySize,
  onClearAll,
  onDismiss,
  resultCount,
}) {
  return (
    <OverlayPanel
      accessibilityLabel="More filters"
      heading="More filters"
      onDismiss={onDismiss}
      footer={
        <Flex justifyContent="between" alignItems="center">
          <Button text="Clear all" color="transparent" onClick={onClearAll} />
          <Button text={`Show ${resultCount} jobs`} color="red" onClick={onDismiss} />
        </Flex>
      }
    >
      <Flex direction="column" gap={4}>
        <GroupFieldset
          groupKey="industry"
          legend="Industry (estimated)"
          options={industryOptions}
          selected={selectedIndustry}
          onToggle={onToggleIndustry}
        />
        <GroupFieldset
          groupKey="companySize"
          legend="Company size (estimated)"
          options={companySizeOptions}
          selected={selectedCompanySize}
          onToggle={onToggleCompanySize}
        />
      </Flex>
    </OverlayPanel>
  );
}
