The Jobs board: five open columns of 320px each, in payload order, scrolling horizontally, with the Ended lane as the last cell of the outer row.

- The columns are the open statuses only (`statuses` minus `ended_statuses`), taken from the payload, so the board cannot disagree with the vault.
- **Column header:** title (heading-xs), a neutral count badge, and a 2px `brand` rule underneath.
- **Empty column:** a dashed box reading "No jobs here yet. Drag a job here." The invitation is dropped on phone layouts, where nothing is draggable.
- **Labelled column:** `role="group"` named "Status, N jobs", singular at one.
- **Drag-over:** `brand-wash` ground and a 2px dashed `brand` outline.
- The board row is a plain flex row, not Gestalt's `Flex`, so the lane can stretch to the board's full height.
- Never a column per status for the All jobs page; that is a grid of cards.
