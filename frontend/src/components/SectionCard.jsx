import { Badge, Box, Flex, Heading, Text } from 'gestalt';

// The card every detail page is built from, per the SectionCard README:
// a title (optionally with a label next to it, e.g. "AI-generated") and a
// body. Same frame as the job card -- 16px padding, 16px rounding,
// container border. Body shape (paragraph, divider list, key/value grid,
// empty state) is the caller's choice via `children`; this component only
// owns the frame and the title row.
export default function SectionCard({ title, label, children }) {
  return (
    <Box rounding={4} borderStyle="sm" padding={4} color="default">
      <Flex direction="column" gap={3}>
        <Flex gap={2} alignItems="center">
          <Heading size="300">{title}</Heading>
          {label ? <Badge text={label} /> : null}
        </Flex>
        {children}
      </Flex>
    </Box>
  );
}

// Divider-list body: rows with a 1px divider, used for responsibilities,
// highlights, history entries and criteria lists.
export function DividerList({ items, renderItem }) {
  return (
    <Flex direction="column">
      {items.map((item, index) => (
        <Box
          key={item.key ?? index}
          paddingY={2}
          dangerouslySetInlineStyle={
            index < items.length - 1
              ? { __style: { borderBottom: '1px solid var(--color-border-container)' } }
              : undefined
          }
        >
          {renderItem ? renderItem(item, index) : <Text>{item}</Text>}
        </Box>
      ))}
    </Flex>
  );
}

// Key/value grid body: a subtle 14px label over a 16px value, per entry.
export function KeyValueGrid({ entries }) {
  return (
    <Box display="flex" wrap dangerouslySetInlineStyle={{ __style: { gap: '16px 24px' } }}>
      {entries.map(([label, value]) => (
        <Box key={label} minWidth={160} dangerouslySetInlineStyle={{ __style: { flex: '1 1 220px' } }}>
          <Flex direction="column" gap={1}>
            <Text size="200" color="subtle">
              {label}
            </Text>
            <Text>{value}</Text>
          </Flex>
        </Box>
      ))}
    </Box>
  );
}

// Empty state body: a dashed box, used for "No jobs linked yet" and
// similar related-items placeholders.
export function EmptyState({ text }) {
  return (
    <Box
      padding={4}
      rounding={4}
      display="flex"
      justifyContent="center"
      dangerouslySetInlineStyle={{ __style: { border: '2px dashed var(--color-border-default)' } }}
    >
      <Text color="subtle" align="center">
        {text}
      </Text>
    </Box>
  );
}
