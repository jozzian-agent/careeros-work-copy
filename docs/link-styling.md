# Link styling convention

Two link treatments exist, selected by where the link goes rather than by
page or feature.

## Internal links

A link to another page inside the same application gets no extra class. It
inherits the default anchor color token, `--accent-violet`, and opens in the
current tab. Use this for navigation between the application's own pages,
such as a job pointing at its linked company profile.

## External links

A link that leaves the application, such as a job posting URL or any other
third-party address, gets three things together, always as a set:

- The `external` class, which switches the color to the `--link-external`
  token (a muted tone, distinct from the internal accent) and appends a
  small arrow glyph after the link text through a CSS `::after` rule. No
  icon font or external image is used for the glyph.
- `target="_blank"`, so the destination opens in a new tab instead of
  replacing the current page.
- `rel="noopener"` (additional `rel` values such as `noreferrer` may be
  combined with it), so the new tab cannot reach back into the page that
  opened it.

## Adding a new link

When a template adds an anchor, first decide whether the destination is
part of this application or outside it. Internal destinations need no
markup beyond the `href`. External destinations need the `external` class
plus `target="_blank"` and `rel="noopener"` together; do not apply only
one of the three.

## Tokens

Both treatments are driven by CSS custom properties defined once in the
shared theme module, not by literal color values in templates or page
styles:

| Token | Purpose |
| --- | --- |
| `--accent-violet` | Default anchor color, used by internal links |
| `--link-external` | Muted color for the `external` class |

A new page or a new tool built on this pattern should reuse these two
tokens rather than introducing its own link colors, so that internal and
external links stay visually distinct everywhere they appear.
