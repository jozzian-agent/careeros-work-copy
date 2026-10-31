The layout every list page shares: Companies, All jobs, My Jobs, Notes and Experiences.

- **Heading row:** the page title at the left and the one primary action at the right ("Add a note", "Add a company", "Add a job", "Add position"). It is the only primary fill on the page.
- **Toolbar row, one line:** filter chips and a plain count at the left; the View switch (SegmentedControl: Tiles and List, or Board and List) at the right. Never two toolbar rows for these controls.
- **Content:** tiles in a grid of 280 to 360px columns, or a table. The view choice only changes the layout, never what is listed.
- **Empty state:** one SectionCard-style box with a sentence and a gray button repeating the action. The heading keeps the primary button.
- Filter and toggle chips are 32px high (44px at phone widths) with 14px bold text; see FilterChip.
