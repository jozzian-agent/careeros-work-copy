import { Badge, Box, Flex, Heading, Text } from 'gestalt';
import EndedLane from './EndedLane.jsx';
import { jobCount } from '../counts.js';

// The board row: fixed 320px columns, horizontal scroll on the row, vertical
// scroll inside each column body past ~720px, sticky column headers (kept
// outside the scrolling body so they never scroll with the cards).
// Consumer provides: columns, cards per column, drag handlers (README).
//
// D7 (2026-10-15): the columns are the five open statuses, and the Ended
// lane sits beside the scrolling box rather than inside it, so it stays at
// the right edge while the columns scroll (see EndedLane). `canDrag` is
// false in the phone layout, where cards move with the status select
// instead, so the empty column stops inviting a gesture that is not there.
export default function KanbanBoard({ columns, lane, canDrag = true }) {
  return (
    <Box display="flex" alignItems="start">
      {/* The columns scroll sideways; the Ended lane does not, because it
          sits OUTSIDE the scrolling box rather than inside it. That is
          what keeps it at the right edge and always a drop target. The
          first attempt pinned it inside the row with position: sticky,
          which worked, but a sticky element is a positioned one, and it
          then painted over anything rendered in a Gestalt Layer that
          carries no z-index of its own (the More filters panel),
          swallowing that panel's own buttons. Staying out of the
          scroller needs no stacking rules at all. */}
      <Box
        data-testid="board-row"
        overflow="scrollX"
        marginStart={-6}
        paddingX={6}
        paddingY={1}
        flex="grow"
        minWidth={0}
      >
        <Flex direction="row" wrap={false} gap={4} alignItems="start">
        {columns.map((column) => (
          <div
            key={column.status}
            data-testid={`board-column-${column.status}`}
            role="group"
            aria-label={`${column.title}, ${jobCount(column.count)}`}
            onDragOver={column.onDragOver}
            onDrop={column.onDrop}
          >
            <Box width={320} minWidth={320} flex="none">
              <Box
                data-testid={`column-header-${column.status}`}
                marginBottom={3}
                paddingY={2}
                dangerouslySetInlineStyle={{ __style: { borderBottom: '2px solid var(--color-brand-primary)' } }}
              >
                <Flex alignItems="center" gap={2}>
                  <Heading size="400">{column.title}</Heading>
                  <Badge type="neutral" text={String(column.count)} />
                </Flex>
              </Box>
              <Box
                data-testid={`column-body-${column.status}`}
                minHeight={96}
                maxHeight={720}
                overflow="scrollY"
                rounding={4}
                padding={1}
                dangerouslySetInlineStyle={{
                  __style: {
                    outline: column.isOver ? '2px dashed var(--color-brand-primary)' : '2px solid transparent',
                    outlineOffset: '-2px',
                  },
                }}
              >
                {column.isEmpty ? (
                  <Box
                    padding={4}
                    rounding={4}
                    dangerouslySetInlineStyle={{ __style: { border: '2px dashed var(--color-border-default)' } }}
                  >
                    <Text align="center" size="200" color="subtle">
                      {column.isOver
                        ? 'Drop here'
                        : canDrag
                          ? 'No jobs here yet. Drag a job here.'
                          : 'No jobs here yet.'}
                    </Text>
                  </Box>
                ) : (
                  column.children
                )}
              </Box>
            </Box>
          </div>
        ))}
        </Flex>
      </Box>
      {lane ? <EndedLane {...lane} /> : null}
    </Box>
  );
}
