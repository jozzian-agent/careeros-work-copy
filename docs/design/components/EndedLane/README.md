A collapsible lane pinned to the right edge of the board for jobs that are Won, Rejected or Stopped. Collapsed on every load; nothing remembers the choice.

- 168px wide, `fill-secondary` ground, no border, `radius-400`, the full height of the board. It is the last cell of the board's outer flex row (`align-self: stretch`), not a sticky item, so columns end before it and never slide under it.
- Header: "Ended" and a count on the column titles' baseline, under a 2px grey rule (grey, because the lane is not a status being worked).
- Won, Rejected and Stopped: one row each, label left and number right.
- A white "Show" button, then "Drop a job here to end it" in 12px `text-subtle`.
- Drag-over: `brand-wash` ground, a 2px dashed `brand` outline, "Drop to end".
