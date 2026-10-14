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
// The group a short skill belongs in, which is also where a line nothing
// else fits goes: a line the extractor cannot place, and a line the owner
// has just written or reworded. One fallback, the extractor's own, so no
// surface can invent a sixth heading.
export const SKILLS_GROUP = 'skills';
export const FALLBACK_GROUP = SKILLS_GROUP;
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

// Whether this job's requirements are the grouped ones. The one answer,
// because the section renders one shape, Edit job writes the shape the
// section renders, and the AI label answers for that same shape.
//
// The stored list alone cannot say. Every job carries the key, empty
// until something writes it, so an owner who clears the list in Edit job
// would watch the flat lists their edit was meant to replace come back,
// and pressing Save would write the field they had just emptied. What
// tells "emptied on purpose" from "not grouped yet" is whether anything
// ever wrote the field, and field_provenance is the record of that: it
// only carries a key some writer stamped.
export function isGrouped(job) {
  return Boolean(groupedEntries(job).length || (job.field_provenance || {}).requirement_groups);
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

// A stored skill no group carries, as a must-have tag in the Skills
// group, because a skill the posting names is something it asks for.
//
// The job's `skills` list and the Skills group overlap on purpose (the
// extraction fills both) but they are edited by two different controls,
// so they drift. Reading the group alone left a skill that is in the
// list and not in the group stored and invisible, which is the one thing
// the page must never do with a value it holds.
//
// Every group's lines are matched, not the Skills group's alone: a skill
// the model placed under Experience or Certifications is already on the
// page, and adding it again rendered the same word twice under two
// headings.
export function unplacedSkills(job, groups = groupedEntries(job)) {
  const placed = new Set(groups.map((entry) => entry.text.trim().toLowerCase()));
  return (job.skills || [])
    .filter((text) => typeof text === 'string' && text.trim() && !placed.has(text.trim().toLowerCase()))
    .map((text) => ({ group: SKILLS_GROUP, level: 'must', text }));
}

export function requirementEntries(job) {
  if (!isGrouped(job)) return legacyRequirementEntries(job);
  const groups = groupedEntries(job);
  return [...groups, ...unplacedSkills(job, groups)];
}
