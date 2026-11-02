// Protects the Contract facet of the jobs filter (CAREER-134): the group
// list carries it after Location, the options are the backend's whole
// [code, label] vocabulary (owner ruling 2026-11-02: all ten codes even
// at a count of zero), and the predicate filters on the entry's derived
// `contract` code.
//
// A plain node:test file like location.test.js. Run with:
//   cd frontend && npm run test:unit
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  JOB_FILTER_GROUPS,
  EMPTY_JOB_FILTERS,
  jobFilterOptions,
  filterJobs,
} from './jobFilters.js';

const CONTRACT_OPTIONS = [
  ['permanent', 'Permanent'],
  ['fixed_term', 'Fixed term'],
  ['internship', 'Internship'],
  ['working_student', 'Working student'],
];

test('the contract group sits after location, before the More-filters groups', () => {
  const keys = JOB_FILTER_GROUPS.map((g) => g.key);
  assert.deepEqual(keys, ['function', 'location', 'contract', 'industry', 'companySize']);
  assert.equal(EMPTY_JOB_FILTERS.contract.length, 0);
});

test('every vocabulary code is an option, in order, with its own words', () => {
  const options = jobFilterOptions({
    contract_options: CONTRACT_OPTIONS,
    entries: [
      { contract: 'internship' },
      { contract: 'internship' },
      { contract: 'permanent' },
    ],
  }).contract;
  assert.deepEqual(options.map((o) => o.value),
                   ['permanent', 'fixed_term', 'internship', 'working_student']);
  assert.deepEqual(options.map((o) => o.label),
                   ['Permanent', 'Fixed term', 'Internship', 'Working student']);
  // Zero counts stay options: the panel shows what the filter understands,
  // not only what the current postings happen to carry.
  assert.deepEqual(options.map((o) => o.count), [1, 0, 2, 0]);
});

test('a payload from a server without contract_options loses the facet, not the page', () => {
  const options = jobFilterOptions({ entries: [{ contract: 'internship' }] });
  assert.deepEqual(options.contract, []);
});

test('an entry with no contract code matches no contract selection', () => {
  const entries = [{ id: 1, contract: 'internship' }, { id: 2, contract: null }];
  const selected = filterJobs(entries, { ...EMPTY_JOB_FILTERS, contract: ['internship'] });
  assert.deepEqual(selected.map((e) => e.id), [1]);
});

test('an unchecked contract group filters nothing', () => {
  const entries = [{ id: 1, contract: 'internship' }, { id: 2, contract: null }];
  assert.equal(filterJobs(entries, EMPTY_JOB_FILTERS).length, 2);
});

test('several checked codes match any of them, like every other group', () => {
  const entries = [
    { id: 1, contract: 'internship' },
    { id: 2, contract: 'working_student' },
    { id: 3, contract: 'permanent' },
  ];
  const selected = filterJobs(entries, {
    ...EMPTY_JOB_FILTERS,
    contract: ['internship', 'working_student'],
  });
  assert.deepEqual(selected.map((e) => e.id), [1, 2]);
});
