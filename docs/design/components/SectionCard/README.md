The card every detail page section sits in. White `surface`, 1px `border-decorative`, `radius-400`, 24px padding.

- Header: title (heading-sm) with an optional AiLabel beside it.
- Variant `needs-input`: `violet-wash` ground with a `violet` border and exactly one action. Rendered only when there is something to ask. A page never shows two at once; the backend context decides which ask wins, not section order.
- Empty state: a dashed outline box with one optional action inside ("Add a note"). Reuse it; do not invent one per section.
- Replaces the plain label badge with the dashed AiLabel.
