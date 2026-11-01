// The pure half of writing a position: the facets a position may be tagged
// with, the company match, and the payload a write sends. Separate from
// `components/PositionFields.jsx` so the rules the old Jinja form carried
// in its inline script are a function that can be tested on its own
// (`positions.test.js`), the way `tags.js` and `jobFilters.js` already are.

// `facet:value`, the stored token shape. A proposed value is slugified the
// same way the registry's own ids are, so "Public speaking" and
// "public-speaking" are one tag and not two.
export function slugify(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

// The facet that is a fixed three-value list rather than a growing
// vocabulary, so a surface offers all of it at once instead of a picker.
// Its values still come from the registry -- nothing here invents one.
export const EXPERIENCE_TYPE_FACET = 'experience-type';

// What a position with no company record behind it reads as.
export const COMPANY_NOT_LINKED = 'Not linked';

// Every facet a position may be tagged with, in registry order. `function`
// is governed by its own proposal flow and is never hand-edited on a
// position, so it is never one of them.
export function taggableFacets(tagRegistry) {
  return Object.entries(tagRegistry?.facets || {}).filter(([facet]) => facet !== 'function');
}

// Every token the shared registry already holds. What is NOT in it is what
// `proposed_tags` has to carry, because `vault.validate_tags` refuses a
// token the registry does not know unless the write proposes it.
export function registryTokens(tagRegistry) {
  return Object.entries(tagRegistry?.facets || {}).flatMap(([facet, info]) =>
    (info.values || []).map((value) => `${facet}:${value.id}`));
}

// The company record a typed name resolves to, or null. Case- and
// whitespace-insensitive on the stored name, which is what the Jinja form's
// own `companyByName` map did and what the Edit position popup still does.
export function matchCompanyByName(companies, name) {
  const target = (name || '').trim().toLowerCase();
  if (!target) return null;
  return (companies || []).find(
    (company) => (company.name || '').trim().toLowerCase() === target) || null;
}

// The payload a position write takes, built from the field set's own state.
// Here rather than in the page, because the edit form the follow-up moves
// onto the same field set has to send the same shape -- including the two
// things the Add position artboard does not mention and the record keeps:
// the custom fields, and the function tags that round-trip untouched
// (`functionTags`, which a create has none of and an edit has the stored
// record's).
//
// Throws for a custom row with no key or a duplicate key, which is the one
// thing a caller has to catch: the old form raised the same two messages.
export function positionPayload(values, { functionTags = [], knownTags = [] } = {}) {
  const custom = {};
  for (const row of values.custom || []) {
    const key = row.key.trim();
    if (!key) throw new Error('Each custom field needs a key.');
    if (Object.hasOwn(custom, key)) throw new Error('Custom field keys must be unique.');
    let value = row.value;
    try {
      value = JSON.parse(row.value);
    } catch {
      // Plain text value; keep as given.
    }
    custom[key] = value;
  }
  const tags = values.tags || [];
  const peopleLed = values.people_led;
  return {
    title: (values.title || '').trim(),
    company: (values.company || '').trim(),
    company_id: values.company_id || null,
    start: values.start || '',
    end: values.end || '',
    location: values.location || '',
    people_led: peopleLed === '' || peopleLed === null || peopleLed === undefined
      ? null : Number(peopleLed),
    summary: values.summary || '',
    highlights: (values.highlights || '').split('\n').map((line) => line.trim()).filter(Boolean),
    detail: values.detail || '',
    tags: [...tags, ...functionTags],
    proposed_tags: tags.filter((token) => !knownTags.includes(token)),
    custom,
  };
}
