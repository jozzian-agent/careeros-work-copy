A native button that opens the status list: 112px wide, 32px high, `radius-200`, a hairline `border-interactive` border, `surface` ground, 12px bold text and a chevron. Grows to 44px high at phone widths.

- The list holds the eight statuses with a labelled "Ended" section (a divider before Won, Rejected and Stopped). The grouping is announced to screen readers, not only drawn.
- Picking an ending status runs the same flow as dropping a job on the Ended lane.
- A caller whose payload cannot say which statuses end a job gets the flat list.
- It stays on compact cards in the Ended lane, so moving a job back has a keyboard route.
