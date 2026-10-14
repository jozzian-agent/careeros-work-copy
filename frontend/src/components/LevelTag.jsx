import { Box, Text } from 'gestalt';

// One requirement or skill, tagged with how much the posting insists on
// it: a must-have is filled, a nice-to-have is outlined.
//
// The difference is carried by the fill and by a visually hidden prefix,
// never by colour: both levels use the same neutral container colours, and
// brand blue is never used for either, because blue is the primary-action
// colour in this system and a requirement is not an action. A reader who
// cannot see the fill still hears "Must-have:" before the text. See
// docs/decisions/design-system.md "Badge usage".
const LEVELS = {
  must: { prefix: 'Must-have: ', background: 'var(--color-background-secondary-base)' },
  nice: { prefix: 'Nice to have: ', background: 'transparent' },
};

export default function LevelTag({ level = 'must', text }) {
  const style = LEVELS[level] || LEVELS.must;
  return (
    <Box
      display="inlineBlock"
      rounding="pill"
      paddingX={3}
      dangerouslySetInlineStyle={{
        __style: {
          background: style.background,
          border: '1px solid var(--color-border-container)',
          minHeight: 'var(--space-600)',
          display: 'inline-flex',
          alignItems: 'center',
        },
      }}
    >
      <Box display="visuallyHidden">{style.prefix}</Box>
      <Text size="200">{text}</Text>
    </Box>
  );
}
