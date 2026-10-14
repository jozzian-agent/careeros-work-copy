import { Box, Flex, Text } from 'gestalt';
import { DividerList } from './SectionCard.jsx';
import LevelTag from './LevelTag.jsx';

// What a posting asks for, as grouped entries: `{group, level, text}`.
//
// The groups are the five the vault stores (careeros/vault.py
// REQUIREMENT_GROUPS); the labels below are the owner-facing words for
// them, and the order is the order the page reads them in. A job written
// before package 2 has no groups at all, so `requirementEntries` adapts
// its two flat lists plus its skills list into the same shape with no
// group on the prose lines, which is the legacy path and the only thing
// that renders an ungrouped block.
const GROUP_ORDER = [null, 'education', 'experience', 'skills', 'languages', 'certifications'];
const GROUP_LABELS = {
  education: 'Education',
  experience: 'Experience',
  skills: 'Skills',
  languages: 'Languages',
  certifications: 'Certifications',
};
// Groups whose entries are short facets, shown as tags. The prose groups
// are shown as rows, because a sentence in a pill does not read.
const TAG_GROUPS = ['skills', 'languages', 'certifications'];
const LEVEL_ORDER = ['must', 'nice'];
const LEVEL_LABELS = { must: 'Must have', nice: 'Nice to have' };

function usable(entry) {
  return typeof entry.text === 'string' && entry.text.trim();
}

// The grouped requirements the job stores, or, for a job that has none
// yet, the legacy adapter below. `requirement_groups` is empty until the
// owner re-extracts that job (owner decision: no read migrates a
// record), so an empty list means "not grouped yet" and not "the posting
// asked for nothing".
export function requirementEntries(job) {
  const groups = (job.requirement_groups || []).filter(usable);
  return groups.length ? groups : legacyRequirementEntries(job);
}

// The pre-package-2 shape. `requirements` is what the posting insists on,
// `nice_to_have` what it would like, and an extracted skill is something
// the posting asks for, so it lands as a must-have tag.
export function legacyRequirementEntries(job) {
  const structured = job.description_structured || {};
  return [
    ...(structured.requirements || []).map((text) => ({ group: null, level: 'must', text })),
    ...(structured.nice_to_have || []).map((text) => ({ group: null, level: 'nice', text })),
    ...(job.skills || []).map((text) => ({ group: 'skills', level: 'must', text })),
  ].filter(usable);
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
