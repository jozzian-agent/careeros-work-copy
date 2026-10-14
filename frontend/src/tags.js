// Owner-facing words for a controlled-vocabulary tag token.
//
// Tokens are stored as `facet:value` (`tool:python`), which is an internal
// shape no page may show. The registry label is the right answer when a
// page has the registry loaded; the Job detail page's own context does not
// carry it, so the token's value, spelled out, is the honest fallback.
export function prettifyTag(tag) {
  return String(tag)
    .split(':')
    .pop()
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

// The label a page shows for a tag when it does have the registry, which
// mirrors experiences.html's fallback exactly: the registry label when it
// knows the token, otherwise the token's own value, spelled out.
export function tagLabel(tag, tagLabels) {
  return (tagLabels || {})[tag]?.label || prettifyTag(tag);
}
