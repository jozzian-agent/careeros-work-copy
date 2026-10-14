import { Box, Text } from 'gestalt';

// The dashed provenance label a detail-page section carries when a machine
// wrote its content: "AI-generated" for text a model composed (the
// summary), "AI-extracted" for text it lifted out of the posting
// (requirements, responsibilities).
//
// Dashed outline rather than a filled Badge, and no colour of its own: a
// provenance marker is not something the owner has to act on, so it must
// not read like the violet "Needs your input" signal or the blue brand
// fill. Colour never carries meaning here; the words and the dashed
// outline do. See docs/decisions/design-system.md "Badge usage".
const TEXTS = { generated: 'AI-generated', extracted: 'AI-extracted' };

export default function AiLabel({ kind = 'generated' }) {
  return (
    <Box
      display="inlineBlock"
      rounding="pill"
      paddingX={2}
      dangerouslySetInlineStyle={{
        __style: {
          background: 'transparent',
          border: '1px dashed var(--color-border-default)',
          height: 'var(--space-600)',
          display: 'inline-flex',
          alignItems: 'center',
        },
      }}
    >
      <Text size="100" color="subtle">
        {TEXTS[kind] || TEXTS.generated}
      </Text>
    </Box>
  );
}
