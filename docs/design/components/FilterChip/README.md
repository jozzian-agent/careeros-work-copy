The one selected style for every filter and toggle chip: Needs attention, Hide closed postings, Following, and the facet filters.

- **Selected:** `brand-wash` ground, a 2px `brand` border, default text. A selected filter is a state, never an action, so it never takes the primary fill.
- **Unselected:** `fill-secondary` ground with a 2px transparent border, so selecting a chip never changes its size and the row never reflows.
- Pill radius, 32px high (44px at phone widths), 14px bold. A filter with a menu shows a chevron; one that is on shows its value and an x.
- **On a brand panel (the All jobs search band)** the wash would disappear against the green, so the rule inverts: unselected chips are `surface` with a chevron, selected chips are solid `ink` with `surface` text and an x.
- The Board, List and Tiles views are not chips: see SegmentedControl.
- A count pill inside a chip is aria-hidden decoration.
