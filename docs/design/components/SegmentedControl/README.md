Gestalt SegmentedControl. The one control for switching how a list is shown: Tiles and List, Board and List.

- One `fill-secondary` pill track, 4px inside padding, items 32px high with 14px bold text. The selected item is a `surface` pill with a 1px `border-interactive` outline and a small shadow; the others are transparent.
- It sits at the far right of the toolbar row, after the filter chips and the count. Filters use FilterChip (brand-wash with a 2px brand border when selected); the view switch never does, so the two read as different kinds of control.
- Wrapped in `role="group"` labelled "View"; each item carries `aria-pressed`.
- It changes the layout only, never the data. Two or three options at most.
