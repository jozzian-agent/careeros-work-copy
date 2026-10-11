---
type: Surface
title: "Kanban interactions"
description: "Describe interactions on the Jinja job board."
timestamp: 2026-10-11
---

# Kanban interactions

Drag a card into a status column, or use its compact “Move <title> to” select
with a keyboard or touch. Cards are focusable; columns stack on mobile.
A drop highlights the destination using theme tokens. Same-status moves do nothing.

Moves immediately relocate the card, recount columns, and synchronize the list
row and select. Each move PUTs a sparse payload containing only the new status.
The vault merges partial payloads against the freshly persisted record, so
fields outside the card and a concurrent background write (such as LLM
enrichment) are never overwritten. The select and dragging are disabled for
that card during saving. A failed PUT restores its original position, status,
list row and counts, and shows an error toast.

A persisted pageshow event refreshes a restored board; returning to a tab after
more than 30 seconds also fetches fresh HTML without the HTTP cache. Refreshes
wait for active moves or drags, discard outdated responses, and retain view,
filter and sorting. Delegated handlers survive replacement of the board.

Test hooks: `.job-card[data-id][data-status]`, `.job-status`, `[data-column]`,
`.column-count`, `.drag-over`, and `.job-row[data-id][data-status]`.
`tests/test_jobs.py` checks rendered controls, event hooks, token-only styles,
title clamping, and sparse-payload status persistence. For browser checks, move into
an empty column, fail a PUT to check rollback, use the select by keyboard,
and return from a detail edit using Back.

Lifecycle: delete with the Jinja page at cutover.
