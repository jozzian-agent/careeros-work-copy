import { Icon, Text } from 'gestalt';
import './FilterChip.css';

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
// box-sizing keeps the height the stated 32px (or 44px) rather than
// 32px plus two borders.
//
// The two grounds and the border colour are NOT here: they are the
// chip's two states and one of them has a hover, which inline style
// cannot express, so they live in FilterChip.css. Pill radius and the
// 14px bold label (the Text below, size="200" weight="bold") are the
// other two halves of the 2026-10-29 brief's B2.
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
  // primary button and matches its height (artboard 2026-10-18); 32px
  // for the filter row itself (2026-10-29 brief, B2; it was 40px).
  height = 32,
}) {
  return (
    <button
      ref={anchorRef}
      type="button"
      className={selected ? 'filter-chip filter-chip-selected' : 'filter-chip'}
      data-testid={dataTestId}
      aria-pressed={pressed}
      aria-haspopup={haspopup ? 'true' : undefined}
      aria-expanded={haspopup ? expanded : undefined}
      onClick={onClick}
      style={{ ...BASE_STYLE, height }}
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
