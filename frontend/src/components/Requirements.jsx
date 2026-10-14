import { Box, Flex, Text } from 'gestalt';
import { DividerList } from './SectionCard.jsx';
import LevelTag from './LevelTag.jsx';

// What a posting asks for, as grouped entries: `{group, level, text}`.
//
// The component takes the grouped shape from day one, which is the shape
// package 2's extraction round will store (`education`, `experience`,
// `skills`, `languages`, each line must or nice). Today's extractor
// stores two flat lists plus a skills list and cannot say which group a
// line belongs to, so `requirementEntries` below adapts what exists into
// the same shape with no group on the prose lines. Package 2 replaces
// that one function and nothing else here moves.
const GROUP_ORDER = [null, 'education', 'experience', 'skills', 'languages'];
const GROUP_LABELS = {
  education: 'Education',
  experience: 'Experience',
  skills: 'Skills',
  languages: 'Languages',
};
// Groups whose entries are short facets, shown as tags. The prose groups
// are shown as rows, because a sentence in a pill does not read.
const TAG_GROUPS = ['skills', 'languages'];
const LEVEL_ORDER = ['must', 'nice'];
const LEVEL_LABELS = { must: 'Must have', nice: 'Nice to have' };

// Package-1 interim adapter. `requirements` is what the posting insists
// on, `nice_to_have` what it would like, and an extracted skill is
// something the posting asks for, so it lands as a must-have tag.
export function requirementEntries(job) {
  const structured = job.description_structured || {};
  return [
    ...(structured.requirements || []).map((text) => ({ group: null, level: 'must', text })),
    ...(structured.nice_to_have || []).map((text) => ({ group: null, level: 'nice', text })),
    ...(job.skills || []).map((text) => ({ group: 'skills', level: 'must', text })),
  ].filter((entry) => typeof entry.text === 'string' && entry.text.trim());
}

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
