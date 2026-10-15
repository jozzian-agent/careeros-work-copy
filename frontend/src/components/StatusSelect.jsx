import { useState } from 'react';
import { Box, Button, Dropdown } from 'gestalt';
import './StatusSelect.css';

// The fallback for a caller whose payload predates `status_labels`.
function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

// The compact status control on every job card: a sm Button that opens a
// Dropdown, per the component README (SelectList has no size small enough
// for a 112px card control). This is also the keyboard/screen-reader route
// for moving a card, since drag-and-drop is not, so it carries the ending
// flow as well: picking Won, Rejected or Stopped here runs exactly what
// dropping the card on the Ended lane runs.
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
    <Box width={112} flex="none">
      <div className="status-select-control">
        <Button
          ref={setAnchor}
          accessibilityLabel={`Move ${jobTitle} to, current status ${label(status)}`}
          accessibilityHaspopup
          accessibilityExpanded={open}
          color="gray"
          size="sm"
          text={label(status)}
          fullWidth
          onClick={() => setOpen((value) => !value)}
        />
      </div>
      {open && anchor ? (
        <Dropdown id={`status-dropdown-${id}`} anchor={anchor} onDismiss={() => setOpen(false)}>
          {openOptions.map(option)}
          {endedOptions.length > 0 ? (
            <Dropdown.Section label="Ended">{endedOptions.map(option)}</Dropdown.Section>
          ) : null}
        </Dropdown>
      ) : null}
    </Box>
  );
}
