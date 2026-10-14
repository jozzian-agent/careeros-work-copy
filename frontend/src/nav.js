// Shared navigation order and labels, mirrored from careeros/web/theme.py
// NAV_PAGES. Kept in sync by hand; this file does not import Python.
// Taxonomy and Notes have no Jinja page at all (React-only, like the
// Search/Experiences/Companies list pages before them), so they are not
// mirrored into theme.py's own NAV_PAGES -- the Jinja /jobs fallback's
// nav bar does not gain a dead link when the React build is unavailable.
export const NAV_PAGES = [
  ['search', 'Search'],
  ['experiences', 'Experiences'],
  ['jobs', 'Jobs'],
  ['companies', 'Companies'],
  ['notes', 'Notes'],
  ['taxonomy', 'Taxonomy'],
];
