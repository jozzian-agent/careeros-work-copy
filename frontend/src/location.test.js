// Protects displayLocation: a stored location string shows each part once
// and leaves the home country out while anything else is left.
//
// A plain node:test file rather than a new test runner: the repository has
// Playwright for behaviour through the browser and nothing for a pure
// function, and `node --test` is already in the toolchain (see
// frontend/README.md, "Tests"). Run it with:
//
//   cd frontend && npm run test:unit
import assert from 'node:assert/strict';
import test from 'node:test';
import { displayLocation } from './location.js';

const CASES = [
  // The brief's own example (vault JOB-048, a Workday posting).
  ['Switzerland, Zug, Zug, Switzerland', 'Zug'],
  // Nothing to do.
  ['Zurich', 'Zurich'],
  ['Berlin, Germany', 'Berlin, Germany'],
  // Repeats only.
  ['Zug, Zug', 'Zug'],
  ['Zurich, ZURICH, zurich', 'Zurich'],
  // The home country in each of its spellings, and only when something
  // else survives it.
  ['Zurich, Switzerland', 'Zurich'],
  ['Zürich, Schweiz', 'Zürich'],
  ['Genève, Suisse', 'Genève'],
  ['Lugano, Svizzera', 'Lugano'],
  ['Bern, CH', 'Bern'],
  ['Switzerland', 'Switzerland'],
  ['Schweiz, Switzerland', 'Schweiz'],
  // Padding, empty parts and the empty record.
  ['  Zug ,  , Switzerland ', 'Zug'],
  ['', ''],
  [null, ''],
  [undefined, ''],
  // Order is the record's, not alphabetical or most-specific-first.
  ['Switzerland, Zug, Zurich', 'Zug, Zurich'],
  // A part that merely contains the country name is not the country.
  ['Switzerland Tourism', 'Switzerland Tourism'],
];

test('displayLocation shows each part once, without the home country', () => {
  CASES.forEach(([input, expected]) => {
    assert.equal(displayLocation(input), expected, `displayLocation(${JSON.stringify(input)})`);
  });
});

test('displayLocation is idempotent', () => {
  CASES.forEach(([input]) => {
    const once = displayLocation(input);
    assert.equal(displayLocation(once), once, `displayLocation(${JSON.stringify(input)}) twice`);
  });
});
