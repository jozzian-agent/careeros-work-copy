// Shared by the two surfaces that drive a FilterBar (the Jobs board and
// the Companies directory): counting how many records fall under each
// option, and turning those counts into the {value, label, count} shape
// FilterBar's panels render.

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

// Options for a facet over a fixed vocabulary (the size classes), kept in
// the vocabulary's own order so the panel reads micro → large rather than
// by popularity, and dropping values no record has, so the panel never
// offers a class that would filter everything away.
export function presentOptions(values, counts, label = (value) => value) {
  return values
    .filter((value) => counts.has(value))
    .map((value) => ({ value, label: label(value), count: counts.get(value) }));
}
