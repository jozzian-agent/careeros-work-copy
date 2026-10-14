// The fixed requirement vocabulary, and what a reader asks of a job
// about it.
//
// One home, because three surfaces have to agree: the Requirements
// section renders the groups, Edit job writes them, and the page's AI
// label answers for whichever shape the section is showing. Each of them
// used to keep its own copy of the words.
//
// The groups and the levels are the vault's (careeros/vault.py
// REQUIREMENT_GROUPS, REQUIREMENT_LEVELS); the labels here are the
// owner-facing words for them, and GROUP_ORDER is the order the page
// reads them in. The leading null is the pre-package-2 block: a job
// written before the groups has prose lines with no group at all.
export const GROUP_ORDER = [null, 'education', 'experience', 'skills', 'languages', 'certifications'];
export const GROUP_LABELS = {
  education: 'Education',
  experience: 'Experience',
  skills: 'Skills',
  languages: 'Languages',
  certifications: 'Certifications',
};
// Groups whose entries are short facets, shown as tags. The prose groups
// are shown as rows, because a sentence in a pill does not read.
export const TAG_GROUPS = ['skills', 'languages', 'certifications'];
// Where a line the extractor cannot place goes, and with it a line the
// owner has just written or reworded: one fallback group, so no surface
// can invent a sixth heading.
export const FALLBACK_GROUP = 'skills';
// Languages have their own editor in Edit job, because a language is a
// word rather than a sentence, so they are never one of the lines in its
// two requirement fields.
export const LANGUAGES_GROUP = 'languages';
export const LEVEL_ORDER = ['must', 'nice'];
export const LEVEL_LABELS = { must: 'Must have', nice: 'Nice to have' };

// A stored entry with something in it. A record a hand edit broke is read
// as stored and never rewritten by a read (owner decision), so the page
// is what skips the unreadable line.
export function usableEntry(entry) {
  return Boolean(entry) && typeof entry.text === 'string' && Boolean(entry.text.trim());
}

export function groupedEntries(job) {
  return (job.requirement_groups || []).filter(usableEntry);
}

// The grouped requirements the job stores, or, for a job that has none,
// the pre-package-2 adapter. `requirements` is what the posting insists
// on, `nice_to_have` what it would like, and an extracted skill is
// something the posting asks for, so it lands as a must-have tag.
function legacyRequirementEntries(job) {
  const structured = job.description_structured || {};
  return [
    ...(structured.requirements || []).map((text) => ({ group: null, level: 'must', text })),
    ...(structured.nice_to_have || []).map((text) => ({ group: null, level: 'nice', text })),
    ...(job.skills || []).map((text) => ({ group: 'skills', level: 'must', text })),
  ].filter(usableEntry);
}

export function requirementEntries(job) {
  const groups = groupedEntries(job);
  return groups.length ? groups : legacyRequirementEntries(job);
}
