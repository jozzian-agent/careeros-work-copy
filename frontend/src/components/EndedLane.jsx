import { useState } from 'react';
import { Badge, Box, Button, Flex, Heading, Text } from 'gestalt';
import { jobCount } from '../counts.js';

const LANE_WIDTH = 320;
// The collapsed lane's width, per the brief (2026-10-18, section 4). The
// artboard draws 120px; the brief's 168px wins, and it is what the three
// count rows need before "Rejected" and its number share a line.
const STRIP_WIDTH = 168;

// How many jobs a group shows before it offers the rest (D7).
const GROUP_PREVIEW = 3;

// What makes the lane the board's right-hand edge, in either state
// (brief 2026-10-18, section 4).
//
// The lane is the LAST CELL of the board's outer flex row (KanbanBoard),
// a sibling of the scrolling columns area: it reserves its own width,
// the scroller gets what is left, and `align-self: stretch` gives it the
// board's full height. Columns therefore END before the lane and never
// slide under it — the brief's rule. An earlier sticky-inside-scroller
// design passed the "full height" check but painted over the Interview
// column at 1280px; a first sticky attempt (D7) had to be reverted
// because it covered the More filters panel. Both problems are gone with
// plain flex layout — no positioning, no z-index.
const PINNED_STYLE = {
  flex: 'none',
  boxSizing: 'border-box',
  alignSelf: 'stretch',
};

// The counts the lane heads with (D7). Every number is counted over
// history in the backend, so an ended job still counts for the interview
// it got; this component only names the lines. The most common reason is
// absent from the payload while no stopped job carries one, because a line
// reading "none" would be a fact about the field rather than the search.
function SearchSoFar({ searchSoFar }) {
  const rows = [
    ['Applied to', searchSoFar.applied_to, 'applied_to'],
    ['Interviews', searchSoFar.interviews, 'interviews'],
    ['Offers', searchSoFar.offers, 'offers'],
  ];
  const top = searchSoFar.top_stopped_reason;
  return (
    <Box
      data-testid="search-so-far"
      padding={3}
      rounding={3}
      marginBottom={3}
      dangerouslySetInlineStyle={{ __style: { background: 'var(--color-background-secondary-base)' } }}
    >
      <Flex direction="column" gap={2}>
        <Text weight="bold" size="200">
          Your search so far
        </Text>
        {rows.map(([label, value, key]) => (
          <Box key={label} data-testid={`search-so-far-${key}`}>
            <Flex justifyContent="between" alignItems="center" gap={2}>
              <Text size="200" color="subtle">
                {label}
              </Text>
              <Text size="200" weight="bold">
                {String(value)}
              </Text>
            </Flex>
          </Box>
        ))}
        {top ? (
          <Box data-testid="search-so-far-top-reason">
            <Flex justifyContent="between" alignItems="center" gap={2}>
              <Text size="200" color="subtle">
                Most common reason to stop
              </Text>
              <Text size="200" weight="bold">
                {`${top.reason} (${top.count})`}
              </Text>
            </Flex>
          </Box>
        ) : null}
      </Flex>
    </Box>
  );
}

// One outcome inside the expanded lane. Dropping a card straight on a
// group picks that outcome without asking, which is why each group is its
// own drop target rather than the lane being one big one.
function EndedGroup({ group, renderCard }) {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? group.jobs : group.jobs.slice(0, GROUP_PREVIEW);
  const hidden = group.jobs.length - shown.length;
  const outline = group.isOver ? '2px dashed var(--color-brand-primary)' : '2px solid transparent';

  return (
    <Box
      data-testid={`ended-group-${group.status}`}
      marginBottom={4}
      padding={1}
      rounding={4}
      role="group"
      aria-label={`${group.label}, ${jobCount(group.jobs.length)}`}
      onDragOver={group.onDragOver}
      onDrop={group.onDrop}
      dangerouslySetInlineStyle={{ __style: { outline, outlineOffset: '-2px' } }}
    >
      <Flex direction="column" gap={2}>
        <Flex alignItems="center" gap={2}>
          <Text weight="bold" size="200">
            {group.label}
          </Text>
          <Badge type="neutral" text={String(group.jobs.length)} />
        </Flex>
        {group.jobs.length === 0 ? (
          <Text size="200" color="subtle">
            {group.isOver ? 'Drop here' : `Nothing ${group.label.toLowerCase()} yet`}
          </Text>
        ) : (
          <Box>
            {shown.map(renderCard)}
            {hidden > 0 ? (
              <Button
                size="sm"
                color="transparent"
                text={`Show all ${group.jobs.length}`}
                onClick={() => setShowAll(true)}
              />
            ) : showAll && group.jobs.length > GROUP_PREVIEW ? (
              <Button
                size="sm"
                color="transparent"
                text="Show fewer"
                onClick={() => setShowAll(false)}
              />
            ) : null}
          </Box>
        )}
      </Flex>
    </Box>
  );
}

// The Ended lane, to the right of Offer (D7).
//
// Collapsed is the state on every load, deliberately: the brief's whole
// point is that the ended jobs are not in the way of the ones still being
// pursued. Remembering the choice is on the deferred list, so nothing is
// stored and a reload always collapses it again.
//
// Collapsed (2026-10-18) it is a grey strip the full height of the board:
// the "Ended" heading on the column titles' own baseline under a grey
// rule, one row per outcome with the label left and the number right, a
// white Show button, and the line that says a card can be dropped on it.
// It is still a drop target, and pinned to the right edge while the
// columns scroll (PINNED_STYLE). Expanded it is one 320px column and not
// three: "Your search so far" on top, then Won, Rejected and Stopped as
// groups.
//
// `collapsible` is false in the phone layout, where the lane is reached
// through the status chip row instead of a Show button, and where it is
// the whole board area, because one column shows at a time.
export default function EndedLane({
  expanded,
  collapsible = true,
  total,
  groups,
  searchSoFar,
  isOver,
  laneDragHandlers,
  onToggle,
  renderCard,
}) {
  const open = expanded || !collapsible;
  const label = `Ended, ${jobCount(total)}`;

  if (!open) {
    return (
      <div
        data-testid="ended-lane-collapsed"
        role="region"
        aria-label={label}
        onDragOver={laneDragHandlers.onDragOver}
        onDrop={laneDragHandlers.onDrop}
        style={{
          ...PINNED_STYLE,
          width: STRIP_WIDTH,
          minWidth: STRIP_WIDTH,
          borderRadius: 'var(--rounding-400)',
          // No top padding: the lane's own header carries the same
          // vertical padding a column header does, so the two titles and
          // their rules land on one line.
          padding: '0 var(--space-300) var(--space-400)',
          // No border in either state: the ground is what the lane is
          // drawn with, and the drag-over state swaps that ground and
          // adds the dashed outline the columns use.
          background: isOver ? 'var(--color-brand-wash)' : 'var(--color-background-secondary-base)',
          outline: isOver ? '2px dashed var(--color-brand-primary)' : 'none',
          outlineOffset: '-2px',
        }}
      >
        <Flex direction="column" gap={3}>
          {/* Same wrapper as a column header in KanbanBoard, so "Ended"
              and a column title share a baseline; the rule under it is
              grey rather than the columns' blue, because the lane is not
              one of the statuses being worked. */}
          <Box
            data-testid="ended-lane-header"
            paddingY={2}
            dangerouslySetInlineStyle={{
              __style: { borderBottom: '2px solid var(--color-border-container)' },
            }}
          >
            <Flex alignItems="center" gap={2}>
              <Heading size="400">Ended</Heading>
              <Badge type="neutral" text={String(total)} />
            </Flex>
          </Box>
          <Flex direction="column" gap={1}>
            {groups.map((group) => (
              <Box key={group.status} data-testid={`ended-count-${group.status}`}>
                <Flex justifyContent="between" alignItems="center" gap={2}>
                  <Text size="200" color="subtle">
                    {group.label}
                  </Text>
                  <Text size="200" weight="bold">
                    {String(group.jobs.length)}
                  </Text>
                </Flex>
              </Box>
            ))}
          </Flex>
          <Button
            size="sm"
            color="white"
            text="Show"
            accessibilityLabel="Show ended jobs"
            fullWidth
            onClick={onToggle}
          />
          <Text size="100" color="subtle">
            {isOver ? 'Drop to end' : 'Drop a job here to end it'}
          </Text>
        </Flex>
      </div>
    );
  }

  return (
    <div
      data-testid="ended-lane"
      role="region"
      aria-label={label}
      // Pinned the same way as the collapsed strip, with the page ground
      // behind it so a column scrolling past is not seen through it.
      style={{ ...PINNED_STYLE, background: 'var(--color-background-page)' }}
    >
      <Box width={LANE_WIDTH} minWidth={LANE_WIDTH} flex="none">
        <Box
          marginBottom={3}
          paddingY={2}
          dangerouslySetInlineStyle={{ __style: { borderBottom: '2px solid var(--color-brand-primary)' } }}
        >
          <Flex alignItems="center" gap={2}>
            <Heading size="400">Ended</Heading>
            <Badge type="neutral" text={String(total)} />
            {collapsible ? (
              <Box marginStart="auto">
                <Button size="sm" color="gray" text="Hide" accessibilityLabel="Hide ended jobs" onClick={onToggle} />
              </Box>
            ) : null}
          </Flex>
        </Box>
        <Box maxHeight={collapsible ? 720 : undefined} overflow={collapsible ? 'scrollY' : 'visible'} padding={1}>
          <SearchSoFar searchSoFar={searchSoFar} />
          {groups.map((group) => (
            <EndedGroup key={group.status} group={group} renderCard={renderCard} />
          ))}
        </Box>
      </Box>
    </div>
  );
}
