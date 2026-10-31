Gestalt TextField, large, with the label inside the field (visual-refresh style): 56px high, 16px radius, 1px `border-interactive` border.

- The label is a real `label` tied to the input, 12px at weight 700, in `text-subtle`, above the value.
- Value text is 16px in `ink`.
- Hover darkens the border to `#626260` (Gestalt's hover grey); focus shows the white-plus-blue ring.
- Disabled: `fill-secondary` background, `border-decorative` border, `text-disabled` label. Use it only when you also say why (for example "Invite only").
- Always provide a label and a unique id.
