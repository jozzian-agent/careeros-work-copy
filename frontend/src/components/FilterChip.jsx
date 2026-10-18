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

// The 2px border is on both states, transparent while unselected, so
// selecting a chip never changes its size and the row never reflows.
// box-sizing keeps the height the stated 40px (or 44px) rather than
// 40px plus two borders.
const BASE_STYLE = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  padding: '0 12px',
  borderWidth: 2,
  borderStyle: 'solid',
  borderRadius: 999,
  boxSizing: 'border-box',
  cursor: 'pointer',
  color: 'var(--color-text-default)',
  fontFamily: 'inherit',
};

// The one style a selected toggle has, anywhere in the app (brief
// 2026-10-18, section 1): the wash-blue ground and the blue border the
// Function filter already had when active, with the default text colour.
// A primary blue FILL is reserved for the one main action on a screen and
// is never a selected state, which is what Board/List used to look like.
// Recorded in docs/decisions/design-system.md.
const SELECTED_TOGGLE_STYLE = {
  background: 'var(--color-brand-wash-blue)',
  borderColor: 'var(--color-brand-primary)',
};

const UNSELECTED_TOGGLE_STYLE = {
  background: 'var(--color-background-secondary-base)',
  borderColor: 'transparent',
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
  // 44px for the Board/List view pair, which stands beside the page's
  // primary button and matches its height (artboard 2026-10-18); 40px
  // for the filter row itself.
  height = 40,
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
        height,
        ...(selected ? SELECTED_TOGGLE_STYLE : UNSELECTED_TOGGLE_STYLE),
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
