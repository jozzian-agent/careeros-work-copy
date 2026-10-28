// Shared by the two surfaces that drive a FilterBar (the Jobs board and
// the Companies directory): counting how many records fall under each
// option, and turning those counts into the {value, label, count} shape
// FilterBar's panels render. `labelPairs` below is the one reader of the
// `[code, label]` vocabulary shape the backend sends, so the pages that
// show a code outside a filter panel read it from here too.

// How many entries carry each value. `getValues` returns the values one
// entry contributes, so a multi-valued field (a job's functions, a
// company's sectors) counts once per value it holds. Null, undefined and
// empty-string values are not options and never counted.
export function countBy(entries, getValues) {
  const counts = new Map();
  entries.forEach((entry) => {
    getValues(entry).forEach((value) => {
      if (value === null || value === undefined || value === '') return;
      counts.set(value, (counts.get(value) || 0) + 1);
    });
  });
  return counts;
}

// Options for a facet whose values come from the data itself (location,
// industry, sector): most-used first, ties alphabetical. `label` maps a
// stored value to the words the panel shows, for a facet stored as a code
// (a company's ISIC sections); by default the value IS the label.
export function sortedOptions(counts, label = (value) => value) {
  return Array.from(counts.entries())
    .map(([value, count]) => ({ value, label: label(value), count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

// A fixed vocabulary the backend sends, as [code, label] pairs whatever
// shape it actually arrived in (CAREER-71). The label is the taxonomy's
// own word for the code -- `xl` is "Very large", which no rule applied to
// the code in the browser could produce -- so nothing here derives one.
//
// Defaulted, not assumed, and that covers the shape as well as the key: a
// bundle loaded against a server that predates the pairs sends bare
// codes, and a bare code stands in as its own label. It reads as "xl"
// rather than as a word, which is the honest answer when the vocabulary
// arrived without its words -- and never a crash, which is what
// `new Map(['xl'])` would be.
export function labelPairs(sent) {
  return (sent || []).map((entry) => (Array.isArray(entry) ? entry : [entry, entry]));
}

// Options for a facet over a fixed vocabulary (the size classes), kept in
// the vocabulary's own order so the panel reads micro → very large rather
// than by popularity, and dropping values no record has, so the panel
// never offers a class that would filter everything away. `options` is
// `labelPairs` output.
export function presentOptions(options, counts) {
  return options
    .filter(([value]) => counts.has(value))
    .map(([value, label]) => ({ value, label, count: counts.get(value) }));
}
