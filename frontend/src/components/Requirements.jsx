import { Box, Flex, Text } from 'gestalt';
import { DividerList } from './SectionCard.jsx';
import LevelTag from './LevelTag.jsx';
import {
  GROUP_LABELS, GROUP_ORDER, LEVEL_LABELS, LEVEL_ORDER, TAG_GROUPS,
} from '../requirements.js';

// What a posting asks for, as grouped entries: `{group, level, text}`.
// Which entries those are, and what each group is called, is the fixed
// vocabulary in ../requirements.js; this renders them.
export default function Requirements({ entries }) {
  const groups = GROUP_ORDER.filter((group) => entries.some((entry) => (entry.group || null) === group));
  return (
    <Flex direction="column" gap={4}>
      {groups.map((group) => {
        const rows = entries.filter((entry) => (entry.group || null) === group);
        return (
          <Flex key={group || 'ungrouped'} direction="column" gap={2}>
            {group ? (
              <Text weight="bold" size="200">
                {GROUP_LABELS[group]}
              </Text>
            ) : null}
            {TAG_GROUPS.includes(group) ? (
              <Flex gap={2} wrap>
                {rows.map((entry) => (
                  <LevelTag key={`${entry.level}-${entry.text}`} level={entry.level} text={entry.text} />
                ))}
              </Flex>
            ) : (
              LEVEL_ORDER.filter((level) => rows.some((entry) => entry.level === level)).map((level) => (
                <Box key={level}>
                  <Text size="200" color="subtle">
                    {LEVEL_LABELS[level]}
                  </Text>
                  <DividerList items={rows.filter((entry) => entry.level === level).map((entry) => entry.text)} />
                </Box>
              ))
            )}
          </Flex>
        );
      })}
    </Flex>
  );
}
