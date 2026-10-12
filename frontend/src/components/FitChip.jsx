import { Box, Text } from 'gestalt';

// Icon paths verbatim from the FitChip component README (24x24, filled,
// nonzero rule). Rendered as raw SVG rather than Gestalt's Icon because
// Icon's `color` prop only reaches Gestalt's own semantic icon tokens
// (--color-icon-error/-warning), not the brief's color-text-error/-warning/
// color-brand-accent tokens; see BUILD_NOTES.md for the precedent (Button
// red needed the same kind of CSS-variable workaround).
const ICON_PATHS = {
  no_fit: 'M15.18 16.95 12 13.77l-3.18 3.18a1.25 1.25 0 0 1-1.77-1.77L10.23 12 7.05 8.82a1.25 1.25 0 0 1 1.77-1.77L12 10.23l3.18-3.18a1.25 1.25 0 1 1 1.77 1.77L13.77 12l3.18 3.18a1.25 1.25 0 0 1-1.77 1.77M24 12a12 12 0 1 0-24 0 12 12 0 0 0 24 0',
  lucky:
    'M4 7.9a3.9 3.9 0 1 0 7.8 0 3.9 3.9 0 1 0-7.8 0zM12.2 7.9a3.9 3.9 0 1 0 7.8 0 3.9 3.9 0 1 0-7.8 0zM4 16.1a3.9 3.9 0 1 0 7.8 0 3.9 3.9 0 1 0-7.8 0zM12.2 16.1a3.9 3.9 0 1 0 7.8 0 3.9 3.9 0 1 0-7.8 0zM9 12a3 3 0 1 0 6 0 3 3 0 1 0-6 0zM13.828 21.809L15.372 21.391L12.772 11.791L11.228 12.209z',
  excellent:
    'M12 0a12 12 0 1 0 0 24 12 12 0 0 0 0-24M6.37 11.61a1.25 1.25 0 0 1 1.76 0l2.37 2.36 5.37-5.35a1.25 1.25 0 0 1 1.76 1.76L10.5 17.5l-4.13-4.13a1.25 1.25 0 0 1 0-1.76',
};

const LEVELS = {
  no_fit: { label: 'No fit', background: 'var(--color-background-error-weak)', iconColor: 'var(--color-text-error)' },
  lucky: {
    label: 'Lucky',
    background: 'var(--color-background-warning-weak)',
    iconColor: 'var(--color-text-warning)',
  },
  excellent: {
    label: 'Excellent fit',
    background: 'var(--color-brand-wash-teal)',
    iconColor: 'var(--color-brand-accent)',
  },
};

function LevelIcon({ fit, color }) {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill={color} style={{ flex: 'none' }}>
      <path d={ICON_PATHS[fit]} />
    </svg>
  );
}

const ROW_STYLE = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '6px',
  height: 'var(--space-600)',
  borderRadius: 'var(--rounding-pill)',
  fontSize: 12,
  lineHeight: '16px',
  fontWeight: 700,
};

// The fit chip (read-only, never editable from the board) or "Needs your
// input" when a job has no fit rating yet. The two are never shown together.
export default function FitChip({ fit }) {
  if (!fit || !LEVELS[fit]) {
    return (
      <Box
        dangerouslySetInlineStyle={{
          __style: { ...ROW_STYLE, background: 'var(--color-brand-wash-violet)', padding: '0 10px 0 8px' },
        }}
      >
        <Box
          rounding="circle"
          dangerouslySetInlineStyle={{
            __style: { width: 'var(--space-200)', height: 'var(--space-200)', border: '2px solid var(--color-brand-violet)' },
          }}
        />
        <Text size="100" weight="bold">
          Needs your input
        </Text>
      </Box>
    );
  }

  const level = LEVELS[fit];
  return (
    <Box
      dangerouslySetInlineStyle={{ __style: { ...ROW_STYLE, background: level.background, padding: '0 10px 0 6px' } }}
    >
      <Box display="visuallyHidden">Fit: </Box>
      <LevelIcon fit={fit} color={level.iconColor} />
      <Text size="100" weight="bold">
        {level.label}
      </Text>
    </Box>
  );
}
