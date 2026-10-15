import { useState } from 'react';
import { Badge, Box, Button, Flex, Heading, Text } from 'gestalt';
import { jobCount } from '../counts.js';

const LANE_WIDTH = 320;
const STRIP_WIDTH = 72;

// How many jobs a group shows before it offers the rest (D7).
const GROUP_PREVIEW = 3;

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
// Collapsed it is a narrow strip that is still a drop target. It sits
// beside the scrolling columns rather than inside them, so it keeps the
// right edge and never scrolls out of reach. Expanded it is
// one 320px column and not three: "Your search so far" on top, then Won,
// Rejected and Stopped as groups.
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
    const border = isOver
      ? '2px dashed var(--color-brand-primary)'
      : '2px solid var(--color-border-container)';
    return (
      <div
        data-testid="ended-lane-collapsed"
        role="region"
        aria-label={label}
        onDragOver={laneDragHandlers.onDragOver}
        onDrop={laneDragHandlers.onDrop}
      >
        <Box
          width={STRIP_WIDTH}
          minWidth={STRIP_WIDTH}
          flex="none"
          padding={2}
          rounding={4}
          dangerouslySetInlineStyle={{ __style: { border } }}
        >
          <Flex direction="column" gap={2} alignItems="center">
            <Text weight="bold" size="200" align="center">
              Ended
            </Text>
            <Badge type="neutral" text={String(total)} />
            {groups.map((group) => (
              <Text key={group.status} size="100" color="subtle" align="center">
                {`${group.label} ${group.jobs.length}`}
              </Text>
            ))}
            <Button size="sm" color="gray" text="Show" accessibilityLabel="Show ended jobs" onClick={onToggle} />
            <Text size="100" color="subtle" align="center">
              {isOver ? 'Drop to end it' : 'Drop a job here to end it'}
            </Text>
          </Flex>
        </Box>
      </div>
    );
  }

  return (
    <div data-testid="ended-lane" role="region" aria-label={label}>
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
