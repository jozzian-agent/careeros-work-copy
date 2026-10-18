// The one place a stored location string becomes the words a card shows.
//
// A posting's jobLocation is assembled from whatever the schema block
// listed, in whatever order, with no promise that the parts differ:
// careeros/intake.py joins addressLocality, addressRegion and
// addressCountry per place, so a Workday posting that names the country
// twice and the town twice stores "Switzerland, Zug, Zug, Switzerland".
// That is the record's own statement and is left exactly as it is; this
// is display only (the same rule the Companies directory's name limit
// follows).
//
// Two rules, both from the 2026-10-18 brief, section 5:
//
// 1. Each part shows once. Deduped case-insensitively, keeping the first
//    spelling the record used, so "Zürich, zurich" does not become two
//    places and the record's own capitalisation survives.
// 2. The country is left out when it is Switzerland, and only while
//    something else is left: "Switzerland" on its own is still the only
//    thing the posting said, so it is shown rather than replaced by
//    nothing.
//
// Nothing else is dropped. A foreign country stays (a Berlin posting
// reads "Berlin, Germany"), because that is the part a reader of a Swiss
// board actually needs.

// The country whose name adds nothing on this board, in the three
// languages a Swiss posting writes it in.
const HOME_COUNTRY = new Set(['switzerland', 'schweiz', 'suisse', 'svizzera', 'ch']);

export function displayLocation(value) {
  const parts = String(value || '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
  const unique = [];
  const seen = new Set();
  parts.forEach((part) => {
    const key = part.toLocaleLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    unique.push(part);
  });
  const withoutHome = unique.filter((part) => !HOME_COUNTRY.has(part.toLocaleLowerCase()));
  // Nothing but the home country left means that IS the location, and
  // "Schweiz, Switzerland" is one country said twice rather than two
  // places, so the first spelling the record used stands for all of them.
  return (withoutHome.length ? withoutHome : unique.slice(0, 1)).join(', ');
}
