import { Box, Text } from 'gestalt';

// The board's one machine-state notice style (design-system.md "Badge
// usage", owner decision 2026-10-13): subtle text, a secondary-base
// background and a container-level border at most, so an extraction
// failure or a missing company detail reads as informational, never an
// alarm. Deliberately takes no color prop -- every call site renders
// identically regardless of what it is reporting.
export default function QuietChip({ text }) {
  return (
    <Box
      display="inlineBlock"
      rounding="pill"
      paddingX={3}
      dangerouslySetInlineStyle={{
        __style: {
          background: 'var(--color-background-secondary-base)',
          border: '1px solid var(--color-border-container)',
          height: 'var(--space-600)',
          display: 'inline-flex',
          alignItems: 'center',
        },
      }}
    >
      <Text size="100" color="subtle">
        {text}
      </Text>
    </Box>
  );
}
