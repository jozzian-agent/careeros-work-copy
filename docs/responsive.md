# Responsive breakpoint convention

One breakpoint drives every mobile layout change: `MOBILE_BREAKPOINT` in
`careeros/web/theme.py`, currently 640px. `theme.BASE_CSS` and `ui.CSS` both
substitute this constant into their own `@media (max-width: ...)` blocks, so
a page never stacks to single column at one width while its controls still
expect two.

## What changes below the breakpoint

- Grids (`.grid`, `.custom-row`) collapse to a single column.
- The job board stacks its kanban columns full width instead of scrolling
  them side by side.
- The jobs table reflows from rows into labeled cards; any other table
  falls back to horizontal scroll rather than breaking its layout.
- Base text and `h1` size up slightly, and primary controls (`button`,
  `.button`, `input`, `select`, nav links) gain a 44px minimum tap target.

## Adding a new breakpoint-sensitive rule

Write the rule inside the existing `@media` block in `theme.py` (shared,
page-independent styles) or `ui.py` (shared controls), using
`__MOBILE_BREAKPOINT__px` as the literal width so it keeps tracking the
shared constant. Do not hard-code a pixel width in a new media query.

The `__MOBILE_BREAKPOINT__` placeholder is substituted only inside the CSS
strings in `theme.py` and `ui.py`. New CSS elsewhere should use an f-string
with `MOBILE_BREAKPOINT` to insert the shared width.
