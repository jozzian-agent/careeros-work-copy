import { Text } from 'gestalt';
import { usePhoneLayout } from '../layout.js';
import './SegmentedControl.css';

// The 1px border is on both states, transparent while unselected, so
// selecting an item never changes its width and the track never reflows
// -- the same trick FilterChip uses. box-sizing keeps the height the
// stated 32px (or 44px at phone width) rather than that plus two borders.
//
// Geometry per the export (docs/design/components/SegmentedControl/
// preview.html, `.i`): 32px high, 2px/16px padding, pill radius, 14px
// bold label. The two grounds and the border colour are NOT here: they
// are the item's two states and an inline declaration would outrank the
// stylesheet, so they live in SegmentedControl.css beside the track.
//
// Line height follows the font size, not the component: 14px text is
// 20px (docs/decisions/design-system.md, "Line heights"), which is what
// Gestalt Text size="200" resolves to in this repo -- so the label is a
// Text rather than a hand-set `font` shorthand, exactly as in FilterChip.
const ITEM_STYLE = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '2px 16px',
  borderWidth: 1,
  borderStyle: 'solid',
  borderRadius: 999,
  boxSizing: 'border-box',
  cursor: 'pointer',
  color: 'var(--color-text-default)',
  fontFamily: 'inherit',
};

// The one control for switching how a list is shown: Board and List,
// Tiles and List (docs/design/components/SegmentedControl/README.md). It
// changes the layout only, never the data, which is why it never carries
// the brand wash a FilterChip uses for a selected filter: the two read as
// different kinds of control.
//
// Built here rather than taken from Gestalt: Gestalt's own
// SegmentedControl renders role="tablist"/role="tab", and the export asks
// for a role="group" labelled "View" whose items each carry aria-pressed
// -- a set of toggles, not a set of tabs. Same reason FilterChip is local.
//
// `items` is [{ value, label, dataTestId }]; `value` says which one is
// pressed and `onChange` is called with the chosen item's value. The
// phone height is read from usePhoneLayout() inside the component rather
// than passed in, so neither call site has to repeat the rule (CAREER-118:
// 44px targets at phone width).
export default function SegmentedControl({ items, value, onChange, ariaLabel }) {
  const isPhone = usePhoneLayout();
  const minHeight = isPhone ? 44 : 32;

  return (
    <div className="segmented-control" role="group" aria-label={ariaLabel}>
      {items.map((item) => {
        const selected = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            className={
              selected ? 'segmented-control-item segmented-control-item-selected' : 'segmented-control-item'
            }
            data-testid={item.dataTestId}
            aria-pressed={selected}
            onClick={() => onChange(item.value)}
            style={{ ...ITEM_STYLE, minHeight }}
          >
            <Text weight="bold" size="200">
              {item.label}
            </Text>
          </button>
        );
      })}
    </div>
  );
}
