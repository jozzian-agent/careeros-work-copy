import { useState } from 'react';
import { Box, Button, Dropdown } from 'gestalt';

function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

// The compact status control on every job card: a sm Button that opens a
// Dropdown, per the component README (SelectList has no size small enough
// for a 112px card control). This is also the keyboard/screen-reader route
// for moving a card, since drag-and-drop is not accessible.
export default function StatusSelect({ id, jobTitle, status, statuses, onChange }) {
  const [anchor, setAnchor] = useState(null);
  const [open, setOpen] = useState(false);

  return (
    <Box width={112} flex="none">
      <Button
        ref={setAnchor}
        accessibilityLabel={`Move ${jobTitle} to`}
        color="gray"
        size="sm"
        text={titleCase(status)}
        fullWidth
        onClick={() => setOpen((value) => !value)}
      />
      {open && anchor ? (
        <Dropdown id={`status-dropdown-${id}`} anchor={anchor} onDismiss={() => setOpen(false)}>
          {statuses.map((option) => (
            <Dropdown.Item
              key={option}
              option={{ value: option, label: titleCase(option) }}
              selected={{ value: status, label: titleCase(status) }}
              onSelect={({ item }) => {
                setOpen(false);
                if (item.value !== status) onChange(item.value);
              }}
            />
          ))}
        </Dropdown>
      ) : null}
    </Box>
  );
}
