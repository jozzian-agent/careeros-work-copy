import { Badge, Box, Flex, Heading, Text } from 'gestalt';

// The board row: fixed 320px columns, horizontal scroll on the row, vertical
// scroll inside each column body past ~720px, sticky column headers (kept
// outside the scrolling body so they never scroll with the cards).
// Consumer provides: columns, cards per column, drag handlers (README).
export default function KanbanBoard({ columns }) {
  return (
    <Box
      data-testid="board-row"
      overflow="scrollX"
      marginStart={-6}
      marginEnd={-6}
      paddingX={6}
      paddingY={1}
    >
      <Flex direction="row" wrap={false} gap={4} alignItems="start">
        {columns.map((column) => (
          <div
            key={column.status}
            data-testid={`board-column-${column.status}`}
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
                      {column.isOver ? 'Drop here' : 'No jobs here yet'}
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
  );
}
