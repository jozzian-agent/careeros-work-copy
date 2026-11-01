The row of filters above a list page: facet filters (Function, Location, More filters), a divider, toggle chips and a count.

- Toggles are a list of FilterChips after the divider. The board passes "Needs attention" and "Hide closed postings"; Companies passes its own.
- The divider renders only when the bar has at least one toggle.
- Count: an optional summary while no filter is on (the board shows the open and ended split). Once a filter is on, "N of M" wins, because the count must describe what is shown.
- A surface may hang one control off the right end of the row — in practice the View switch, so the CollectionPage toolbar is one line. The count then sits beside the chips at the left, since the right end belongs to that control. With nothing passed, the count keeps the right end.
- "Clear all" resets every toggle and group.
- The Fit facet is removed until scoring exists.
