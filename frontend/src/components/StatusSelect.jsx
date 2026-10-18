import { useState } from 'react';
import { Dropdown } from 'gestalt';
import './StatusSelect.css';

// The control's own measurements, from the approved board artboard
// (2026-10-18): 112px wide, 32px high, an 8px radius, a hairline border,
// a white ground and 12px bold text, with a chevron on the right. It
// replaces the large grey pill a Gestalt sm Button drew, which read as a
// filled chip rather than as a select.
const CONTROL_STYLE = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 'var(--space-200)',
  width: 112,
  minWidth: 112,
  height: 32,
  flex: 'none',
  padding: '0 10px',
  boxSizing: 'border-box',
  border: '1px solid var(--color-border-default)',
  borderRadius: 'var(--rounding-200)',
  background: 'var(--color-background-card)',
  color: 'var(--color-text-default)',
  cursor: 'pointer',
  fontFamily: 'inherit',
  fontSize: 12,
  lineHeight: '16px',
  fontWeight: 700,
  textAlign: 'start',
};

// Gestalt's icon set has no plain down chevron (BUILD_NOTES.md), so the
// shape is drawn here, the same way FilterChip and FitChip draw theirs.
function Chevron() {
  return (
    <svg
      aria-hidden="true"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flex: 'none' }}
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

// The fallback for a caller whose payload predates `status_labels`.
function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

// The compact status control on every job card: a native button that
// opens a Gestalt Dropdown, per the component README (SelectList has no
// size small enough for a 112px card control, and Gestalt's Button draws
// a filled pill with no room for a chevron). This is also the
// keyboard/screen-reader route for moving a card, since drag-and-drop is
// not, so it carries the ending flow as well: picking Won, Rejected or
// Stopped here runs exactly what dropping the card on the Ended lane
// runs.
//
// D7 (2026-10-15): the list is the open statuses, a divider, then the three
// that end a job. Which words, and which three, come from the board payload
// (status_labels, ended_statuses) rather than from a copy kept here. The
// divider is a labelled Dropdown.Section, so the grouping is announced and
// not only drawn; StatusSelect.css draws its rule, which Dropdown.Section
// does not draw by itself.
//
// Both props are defaulted, the way every new payload key on this board is:
// a caller that cannot say which statuses end a job gets the flat list it
// had before rather than a crash. The Job detail page is such a caller
// today, since its payload carries `status_labels` but not
// `ended_statuses`.
export default function StatusSelect({
  id,
  jobTitle,
  status,
  statuses,
  statusLabels = {},
  endedStatuses = [],
  onChange,
}) {
  const [anchor, setAnchor] = useState(null);
  const [open, setOpen] = useState(false);
  const label = (value) => statusLabels[value] || titleCase(value);
  const endedOptions = statuses.filter((value) => endedStatuses.includes(value));
  const openOptions = statuses.filter((value) => !endedStatuses.includes(value));

  function option(value) {
    return (
      <Dropdown.Item
        key={value}
        option={{ value, label: label(value) }}
        selected={{ value: status, label: label(status) }}
        onSelect={({ item }) => {
          setOpen(false);
          if (item.value !== status) onChange(item.value);
        }}
      />
    );
  }

  return (
    <div className="status-select-control">
      <button
        ref={setAnchor}
        type="button"
        data-testid={`status-select-${id}`}
        aria-label={`Move ${jobTitle} to, current status ${label(status)}`}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        style={CONTROL_STYLE}
      >
        <span
          style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          {label(status)}
        </span>
        <Chevron />
      </button>
      {open && anchor ? (
        <Dropdown id={`status-dropdown-${id}`} anchor={anchor} onDismiss={() => setOpen(false)}>
          {openOptions.map(option)}
          {endedOptions.length > 0 ? (
            <Dropdown.Section label="Ended">{endedOptions.map(option)}</Dropdown.Section>
          ) : null}
        </Dropdown>
      ) : null}
    </div>
  );
}
