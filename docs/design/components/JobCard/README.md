A job on the board or in the All jobs grid. Same card in both places. `surface`, 1px `border-decorative`, `radius-400`, 16px padding, 320px wide in the grid and 300px in a board column.

- **Fixed height, 232px.** Every card in a row is the same height, whatever it holds. A long title stops at two lines and ends with an ellipsis; the company and location stop at one line.
- **Content, top to bottom:** title (bold, black, underlined link), company (14px bold link), a pin and the location, then a clock and the workload when the posting states one (a missing workload leaves no line and no gap).
- **Footer, with a hairline above:** the time at the left ("Added today", "Added yesterday", then "Added 14 Oct"; the year only when it is not the current one), the control at the right.
- **The control** is the status select (112px, 32px high, 8px radius, 12px bold) when the job is in My Jobs. A job that is not saved shows a small gray button "Save to New" with a bookmark icon in its place. Saving puts the job in New; the bookmark never shows on a card that already has a status.
- **Saved cards** have a 4px `brand` left edge. Unsaved cards have none.
- The "Needs your input" chip, the ingest indicator with Try again, and the Ended-lane compact card keep their old behaviour (see NeedsInputChip, QuietChip, EndedLane).
- No logo, picture or rating. The fit chip stays hidden because fit scoring is not built.
