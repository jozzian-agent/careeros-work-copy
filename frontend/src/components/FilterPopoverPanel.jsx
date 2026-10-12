import { useMemo, useState } from 'react';
import { Box, Button, Checkbox, Flex, SearchField, Text } from 'gestalt';

const VISIBLE_LIMIT = 6;

// The Popover body shared by the Fit, Function and Location chips, per the
// FilterPanels README: a search field once the list is long, a checkbox
// list with counts, "Show N more", then Clear and Apply. Checking a box
// filters the board immediately (there is no separate draft to commit);
// Apply and Clear just close/reset this one panel.
export default function FilterPopoverPanel({ groupKey, label, options, selected, onToggle, onClear, onDone }) {
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState(false);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? options.filter((option) => option.label.toLowerCase().includes(needle)) : options;
  }, [options, query]);

  const visible = expanded || query.trim() ? matches : matches.slice(0, VISIBLE_LIMIT);
  const hiddenCount = expanded || query.trim() ? 0 : Math.max(0, matches.length - VISIBLE_LIMIT);

  return (
    <Box width={320} padding={4}>
      <Flex direction="column" gap={3}>
        {options.length > VISIBLE_LIMIT ? (
          <SearchField
            id={`filter-search-${groupKey}`}
            accessibilityLabel={`Search ${label.toLowerCase()}`}
            placeholder={`Search ${label.toLowerCase()}`}
            value={query}
            onChange={({ value }) => setQuery(value)}
          />
        ) : null}
        <Flex direction="column">
          {visible.length === 0 ? (
            <Text color="subtle" size="200">
              No options.
            </Text>
          ) : (
            visible.map((option, index) => (
              <Box key={option.value} minHeight={44} display="flex" alignItems="center">
                <Flex flex="grow" justifyContent="between" alignItems="center" gap={2}>
                  <Checkbox
                    id={`filter-${groupKey}-${index}`}
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
        {hiddenCount > 0 ? (
          <Button text={`Show ${hiddenCount} more`} color="transparent" size="sm" onClick={() => setExpanded(true)} />
        ) : null}
        <Flex justifyContent="between" alignItems="center">
          <Button text="Clear" color="transparent" size="sm" onClick={onClear} />
          <Button text="Apply" color="red" size="sm" onClick={onDone} />
        </Flex>
      </Flex>
    </Box>
  );
}
