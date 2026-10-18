// Shared navigation order and labels, mirrored from careeros/web/theme.py
// NAV_PAGES. Kept in sync by hand; this file does not import Python.
// Taxonomy and Notes have no Jinja page at all (React-only, like the
// Search/Experiences/Companies list pages before them), so they are not
// mirrored into theme.py's own NAV_PAGES -- the Jinja /jobs fallback's
// nav bar does not gain a dead link when the React build is unavailable.
//
// M2 (CAREER-39, decision D10): the section is My Jobs, because a board
// now holds the signed-in user's own postings and nobody else's. The
// slug stays "jobs": it is the route and the data attribute, not a word
// anybody reads.
export const NAV_PAGES = [
  ['search', 'Search'],
  ['experiences', 'Experiences'],
  ['jobs', 'My Jobs'],
  ['companies', 'Companies'],
  ['notes', 'Notes'],
  ['taxonomy', 'Taxonomy'],
];
