import { Badge, Box, Flex, Heading, Text } from 'gestalt';
import EndedLane from './EndedLane.jsx';
import { jobCount } from '../counts.js';

// The board row: fixed 320px columns, horizontal scroll on the row, vertical
// scroll inside each column body past ~720px, sticky column headers (kept
// outside the scrolling body so they never scroll with the cards).
// Consumer provides: columns, cards per column, drag handlers (README).
//
// D7 (2026-10-15): the columns are the five open statuses, and the Ended
// lane is the last item of the row. `canDrag` is false in the phone
// layout, where cards move with the status select instead, so the empty
// column stops inviting a gesture that is not there.
//
// 2026-10-18: the lane is a SIBLING of the scrolling row, not an item of
// it. A sticky item inside the scroller paints over the columns it
// passes (the Interview column at 1280px), which the brief forbids: the
// columns end before the lane and never slide under it. As the last cell
// of an outer flex row the lane reserves its own width, the scroller
// takes what is left, and `align-self: stretch` still gives the lane the
// board's full height -- the height the scroller's columns define.
const BOARD_STYLE = {
  display: 'flex',
  flexDirection: 'row',
  flexWrap: 'nowrap',
  gap: 'var(--space-400)',
  alignItems: 'stretch',
  minWidth: 0,
  padding: '4px 0',
};
const ROW_STYLE = {
  display: 'flex',
  flexDirection: 'row',
  flexWrap: 'nowrap',
  gap: 'var(--space-400)',
  alignItems: 'flex-start',
};

export default function KanbanBoard({ columns, lane, canDrag = true }) {
  return (
    <div style={BOARD_STYLE}>
      <Box
        data-testid="board-row"
        overflow="scrollX"
        minWidth={0}
        flex="grow"
      >
        {/* A plain flex row, not Gestalt's Flex: Flex wraps every child in
            a block div of its own to space them, and a wrapped child
            cannot be stretched to the row's height. The artboard draws
            the same thing. */}
        <div style={ROW_STYLE}>
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
        </div>
      </Box>
      {lane ? <EndedLane {...lane} /> : null}
    </div>
  );
}
