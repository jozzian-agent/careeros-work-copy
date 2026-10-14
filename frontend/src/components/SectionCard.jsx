import { Box, Flex, Heading, Text } from 'gestalt';
import AiLabel from './AiLabel.jsx';

// The width of a detail page's content column (2026-10-14 canvas). One
// constant so the Job and Company pages cannot drift apart.
export const DETAIL_MAX_WIDTH = 960;

// The card every detail page is built from, per the SectionCard README:
// a title (optionally with the dashed AI provenance label next to it) and a
// body. Same frame as the job card -- 16px rounding, container border --
// with the canvas's 24px padding. Body shape (paragraph, divider list,
// key/value grid, empty state) is the caller's choice via `children`; this
// component owns the frame, the title row and, at most, one action row.
//
// variant="needs-input" is the one ask the page makes of its owner: a
// violet wash card (the same violet that marks "Needs your input"
// everywhere else) with exactly one action set, rendered only when there
// is something to ask. A page never shows two of them.
export default function SectionCard({ title, aiLabel, variant = 'default', actions, anchorId, children }) {
  const needsInput = variant === 'needs-input';
  return (
    <Box
      id={anchorId}
      rounding={4}
      borderStyle={needsInput ? 'none' : 'sm'}
      padding={6}
      color="default"
      dangerouslySetInlineStyle={
        needsInput
          ? {
            __style: {
              background: 'var(--color-brand-wash-violet)',
              border: '1px solid var(--color-brand-violet)',
            },
          }
          : undefined
      }
    >
      <Flex direction="column" gap={3}>
        <Flex gap={2} alignItems="center" wrap>
          <Heading size="300">{title}</Heading>
          {aiLabel ? <AiLabel kind={aiLabel} /> : null}
        </Flex>
        {children}
        {actions ? (
          <Flex gap={2} wrap>
            {actions}
          </Flex>
        ) : null}
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

// Empty state body: a dashed box, used for "No jobs linked yet", for the
// Notes section's "Add a note" and for any other empty section. `action`
// is the one thing the owner can do about the emptiness, rendered inside
// the same dashed box rather than beside it, so an empty section is one
// element and not two.
export function EmptyState({ text, action }) {
  return (
    <Box
      padding={4}
      rounding={4}
      display="flex"
      justifyContent="center"
      dangerouslySetInlineStyle={{ __style: { border: '2px dashed var(--color-border-default)' } }}
    >
      <Flex direction="column" gap={2} alignItems="center">
        <Text color="subtle" align="center">
          {text}
        </Text>
        {action}
      </Flex>
    </Box>
  );
}
