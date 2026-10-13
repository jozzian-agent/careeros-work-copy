import { useState } from 'react';
import { Box, Button, Dropdown } from 'gestalt';

const OPTIONS = [
  { value: null, label: 'Not rated' },
  { value: 'no_fit', label: 'No fit' },
  { value: 'lucky', label: 'Lucky' },
  { value: 'excellent', label: 'Excellent fit' },
];

function labelFor(value) {
  return OPTIONS.find((option) => option.value === value)?.label || 'Not rated';
}

// The job detail page's Fit control (BRIEF.md: "Fit is set by dropdown on
// the job detail page until it is calculated automatically"). No fit
// dropdown existed before this page (JOZ-278 left the board's FitChip
// read-only), so this is new, built as the same sm Button + Dropdown
// recipe as StatusSelect for one consistent compact-control pattern.
export default function FitSelect({ jobTitle, fit, onChange }) {
  const [anchor, setAnchor] = useState(null);
  const [open, setOpen] = useState(false);
  const value = OPTIONS.some((option) => option.value === fit) ? fit : null;

  return (
    <Box width={160}>
      <Button
        ref={setAnchor}
        accessibilityLabel={`Set fit for ${jobTitle}, current fit ${labelFor(value)}`}
        accessibilityHaspopup
        accessibilityExpanded={open}
        color="gray"
        size="sm"
        text={labelFor(value)}
        fullWidth
        onClick={() => setOpen((prev) => !prev)}
      />
      {open && anchor ? (
        <Dropdown id="fit-dropdown" anchor={anchor} onDismiss={() => setOpen(false)}>
          {OPTIONS.map((option) => (
            <Dropdown.Item
              key={option.label}
              option={option}
              selected={{ value, label: labelFor(value) }}
              onSelect={({ item }) => {
                setOpen(false);
                if (item.value !== value) onChange(item.value);
              }}
            />
          ))}
        </Dropdown>
      ) : null}
    </Box>
  );
}
