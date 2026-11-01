// Protects positionPayload: a position write carries everything the old
// Jinja form sent, including the three things no artboard mentions and a
// record would silently lose -- the custom fields, the function tags that
// round-trip untouched, and the proposal a tag the registry does not hold
// yet needs to be accepted at all.
//
// A plain node:test file, like location.test.js beside it: Playwright
// covers the page, and this covers the function the page and the later
// edit form both build their payload with. Run it with:
//
//   cd frontend && npm run test:unit
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  matchCompanyByName, positionPayload, registryTokens, slugify, taggableFacets,
} from './positions.js';

const REGISTRY = {
  facets: {
    'skill/capability': { label: 'Capability', values: [{ id: 'public-speaking' }] },
    function: { label: 'Job function', values: [{ id: 'platform-lead' }] },
    'experience-type': { label: 'Experience type', values: [{ id: 'employment' }] },
  },
};

const FILLED = {
  title: '  Platform Lead  ',
  company: '  Harbor Labs  ',
  company_id: 'CO-001',
  start: '2022-01',
  end: 'present',
  location: 'Zurich',
  people_led: '6',
  summary: 'Ran the platform team.',
  highlights: 'Shipped the thing\n\n   Hired four people   \n',
  detail: '**Bold** detail.',
  tags: ['skill/capability:public-speaking', 'tool:terraform-cloud'],
  custom: [{ key: ' Clearance ', value: 'None' }, { key: 'Nested', value: '{"a": [1, 2]}' }],
};

test('every field reaches the payload, trimmed where the old form trimmed', () => {
  const payload = positionPayload(FILLED, { knownTags: registryTokens(REGISTRY) });
  assert.equal(payload.title, 'Platform Lead');
  assert.equal(payload.company, 'Harbor Labs');
  assert.equal(payload.company_id, 'CO-001');
  assert.equal(payload.start, '2022-01');
  assert.equal(payload.end, 'present');
  assert.equal(payload.location, 'Zurich');
  assert.equal(payload.people_led, 6);
  assert.equal(payload.detail, '**Bold** detail.');
  // One highlight per line, trimmed, blank lines dropped.
  assert.deepEqual(payload.highlights, ['Shipped the thing', 'Hired four people']);
});

test('a custom field is plain text or parsed JSON, and its key is trimmed', () => {
  const payload = positionPayload(FILLED);
  assert.deepEqual(payload.custom, { Clearance: 'None', Nested: { a: [1, 2] } });
});

test('a custom row with no key, or a key twice, is refused', () => {
  assert.throws(() => positionPayload({ custom: [{ key: '  ', value: 'x' }] }),
                /Each custom field needs a key\./);
  assert.throws(
    () => positionPayload({ custom: [{ key: 'a', value: '1' }, { key: 'a', value: '2' }] }),
    /Custom field keys must be unique\./);
});

test('only a tag the registry does not hold is proposed', () => {
  const payload = positionPayload(FILLED, { knownTags: registryTokens(REGISTRY) });
  assert.deepEqual(payload.proposed_tags, ['tool:terraform-cloud']);
});

test('function tags round-trip untouched and are never proposed', () => {
  // The case the edit form needs: the record already carries a function
  // tag the surface does not offer, and an ordinary save must not erase it.
  const payload = positionPayload(FILLED, {
    functionTags: ['function:platform-lead'],
    knownTags: registryTokens(REGISTRY),
  });
  assert.deepEqual(payload.tags, [
    'skill/capability:public-speaking',
    'tool:terraform-cloud',
    'function:platform-lead',
  ]);
  assert.ok(!payload.proposed_tags.includes('function:platform-lead'));
});

test('an empty position is every field empty rather than a field missing', () => {
  const payload = positionPayload({});
  assert.deepEqual(payload, {
    title: '', company: '', company_id: null, start: '', end: '', location: '',
    people_led: null, summary: '', highlights: [], detail: '', tags: [],
    proposed_tags: [], custom: {},
  });
});

test('people led is null when left blank and a number when given', () => {
  assert.equal(positionPayload({ people_led: '' }).people_led, null);
  assert.equal(positionPayload({ people_led: null }).people_led, null);
  assert.equal(positionPayload({ people_led: '0' }).people_led, 0);
  assert.equal(positionPayload({ people_led: 12 }).people_led, 12);
});

test('the function facet is never offered on a position', () => {
  assert.deepEqual(taggableFacets(REGISTRY).map(([facet]) => facet),
                   ['skill/capability', 'experience-type']);
  assert.deepEqual(taggableFacets(undefined), []);
});

test('a typed company matches a record whatever its case and spacing', () => {
  const companies = [{ id: 'CO-001', name: 'Harbor Labs' }];
  assert.equal(matchCompanyByName(companies, '  harbor LABS ')?.id, 'CO-001');
  assert.equal(matchCompanyByName(companies, 'Harbor Lab'), null);
  assert.equal(matchCompanyByName(companies, '   '), null);
  assert.equal(matchCompanyByName([], 'Harbor Labs'), null);
});

test('a proposed value is slugified to the registry id shape', () => {
  assert.equal(slugify('Public speaking'), 'public-speaking');
  assert.equal(slugify('  Terraform Cloud!  '), 'terraform-cloud');
  assert.equal(slugify('already-a-slug'), 'already-a-slug');
  assert.equal(slugify('!!!'), '');
});
