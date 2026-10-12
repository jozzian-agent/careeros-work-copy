import { Icon, Text } from 'gestalt';

const CHEVRON_PATH = 'M3 6l5 5 5-5';

// Gestalt's icon library (per BUILD_NOTES.md) has no plain down chevron,
// only circled variants that do not match the filter bar mockup's shape;
// raw SVG here follows the same precedent as FitChip's hand-rolled icons.
function Chevron() {
  return (
    <svg
      aria-hidden="true"
      width="12"
      height="12"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flex: 'none' }}
    >
      <path d={CHEVRON_PATH} />
    </svg>
  );
}

const BASE_STYLE = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  height: 40,
  padding: '0 12px',
  border: 0,
  borderRadius: 999,
  cursor: 'pointer',
  color: 'var(--color-text-default)',
  fontFamily: 'inherit',
};

// The chip shared by every control in the filter bar - Fit, Function,
// Location, More filters, Needs attention - per the FilterBar README:
// "same chip, a count badge, filled only when active." A native <button>
// rather than Gestalt's Button or TapArea, because the chip's content
// (label + count pill + chevron) is composite and neither component can
// hold that while still exposing plain aria-pressed/aria-haspopup; the
// count pill is aria-hidden so each chip's accessible name stays just its
// label (e.g. "Needs attention", not "Needs attention 3").
export default function FilterChip({
  label,
  count,
  countColor = 'var(--color-brand-primary)',
  icon,
  chevron = false,
  selected = false,
  pressed,
  expanded,
  haspopup,
  onClick,
  dataTestId,
  anchorRef,
}) {
  return (
    <button
      ref={anchorRef}
      type="button"
      data-testid={dataTestId}
      aria-pressed={pressed}
      aria-haspopup={haspopup ? 'true' : undefined}
      aria-expanded={haspopup ? expanded : undefined}
      onClick={onClick}
      style={{
        ...BASE_STYLE,
        background: selected ? 'var(--color-brand-wash-blue)' : 'var(--color-background-secondary-base)',
        boxShadow: selected ? 'inset 0 0 0 2px var(--color-brand-primary)' : 'none',
      }}
    >
      {icon ? <Icon icon={icon} accessibilityLabel="" color="default" size={16} /> : null}
      <Text weight="bold" size="200">
        {label}
      </Text>
      {count > 0 ? (
        <span
          aria-hidden="true"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            minWidth: 20,
            height: 20,
            padding: '0 6px',
            borderRadius: 999,
            background: countColor,
            color: 'var(--color-brand-on-color)',
            fontSize: 12,
            lineHeight: '16px',
            fontWeight: 700,
          }}
        >
          {count}
        </span>
      ) : null}
      {chevron ? <Chevron /> : null}
    </button>
  );
}
