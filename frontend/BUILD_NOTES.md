# Frontend build notes

## Gestalt 160 → 177 delta

JOZ-277 pinned `gestalt` to exactly `177.0.12` (from `^160.0.0`) to match the
owner's design handoff, which states its component facts were checked against
that version's TypeScript definitions. Everything below was verified against
the installed package in `node_modules/gestalt`, not recalled.

### Peer dependency: React 18 → 19 (required, not optional)

`gestalt@177.0.12` declares `peerDependencies: { react: ^19.0.0, react-dom:
^19.0.0 }`. The app was on React 18.3.1, so the Gestalt bump cannot stand
alone: `react`/`react-dom` went to `^19.0.0` (19.3.0 installed) and
`@types/react`/`@types/react-dom` to `^19.0.0`. This is outside the literal
"upgrade gestalt" scope but is a hard requirement of it; installing with
`--legacy-peer-deps` instead would leave Gestalt running against a React it
does not support. No application code needed changing for React 19 — the app
already used `createRoot` from `react-dom/client` and has no legacy APIs
(no string refs, no `ReactDOM.render`, no `defaultProps` on function
components). `npm install` reports 0 vulnerabilities and no peer warnings.

### Breaking API change hit: `Box` lost `color="white"`

`Box`'s `color` prop no longer accepts `"white"`. In 177 the union is:

```
'darkWash' | 'lightWash' | 'transparent' | 'transparentDarkGray' | 'default' |
'infoBase' | 'infoWeak' | 'errorBase' | 'errorWeak' | 'warningBase' |
'warningWeak' | 'successBase' | 'successWeak' | 'recommendationBase' |
'recommendationWeak' | 'shopping' | 'primary' | 'secondary' | 'tertiary' |
'selected' | 'inverse' | 'brand' | 'education' | 'elevationAccent' |
'elevationFloating' | 'elevationRaised' | 'dark' | 'light'
```

Two call sites used it, and both became `color="default"`:

- `src/Nav.jsx` — the app header bar.
- `src/pages/JobsBoard.jsx` — the job card surface.

`"default"` is the right replacement rather than a workaround: it resolves
through `--color-background-default`, which `design/theme.css` maps to the
handoff's `--color-background-card`. So the nav and the cards are `#ffffff` in
light and `#191919` in dark, instead of being pinned to white in both. Because
Vite does not type-check JSX against a dependency's `.d.ts`, this would not
have failed the build — it would have shipped as cards with no background at
all, since the removed value produces no class.

### The theming mechanism moved: `ColorSchemeProvider` → `DesignTokensProvider`

This is the most consequential change for this repo, and it contradicts the
old `src/theme.js` comments, which were correct for 160.

- **160:** `ColorSchemeProvider` itself rendered a `<style>` tag containing a
  fresh `:root { ... }` block of Gestalt's tokens.
- **177:** `ColorSchemeProvider` is pure React context. It renders
  `ThemeContext.Provider` and nothing else — no style tag, no DOM. It only
  publishes `colorSchemeName` (`'lightMode'`/`'darkMode'`) and, for
  `colorScheme="userPreference"`, subscribes to `prefers-color-scheme`.
  The stylesheet injection moved to a separate exported component,
  `DesignTokensProvider`, which reads that context to pick the light or dark
  token set.

`DesignTokensProvider` is **not** rendered by `ColorSchemeProvider`, so this
matters beyond tidiness: an app that only wraps itself in
`ColorSchemeProvider` — which is exactly what `App.jsx` did on 160 — gets no
dark tokens whatsoever. `gestalt/dist/gestalt.css` ships five `:root` blocks
and every one of them is light-mode; dark mode exists only in the tag
`DesignTokensProvider` injects at runtime. `src/design/ThemeProvider.jsx` now
renders both, and deliberately passes no `id` to `DesignTokensProvider`: with
an `id` the tokens are scoped to a wrapper `div` and portal-rendered
components fall out of the theme (the board's `Toast` renders inside a
`Layer`).

**The cascade lesson from the old `theme.js` still holds, with a new source.**
The injected tag lives inside `#root` in `<body>`, always later in document
order than the stylesheets in `<head>`, at equal `:root` specificity. So the
token overrides still need `!important` to survive every mount and every
re-render. Verified, not assumed: `tests/theme.spec.js` asserts that the
provider's tag is present, that it is later in document order than our token
stylesheet, that it really does declare Gestalt's own
`--color-background-primary-base`, and that the brand value still wins.

### Unchanged, having been checked

- **CSS entry point:** still `gestalt/dist/gestalt.css` (`"style"` in the
  package manifest). No import path change in `main.jsx`.
- **Component inventory:** every component the board and nav use still exists
  and is still exported from the package root — `Badge`, `Box`, `Button`,
  `ButtonToggle`, `ColorSchemeProvider`, `Flex`, `Heading`, `Layer`, `Link`,
  `Modal`, `PageHeader`, `SelectList` (+ `SelectList.Option`), `Table` (+
  `Header`/`Body`/`Row`/`Cell`/`SortableHeaderCell`), `TapAreaLink`, `Text`,
  `TextField`, `Toast`. Nothing had to be swapped for a replacement.
- **Props:** the rest of the props in use are unchanged in 177 —
  `Box` `borderStyle="raisedBottomShadow"`, `Text` `color`/`overflow`/
  `underline`/`dataTestId`, `Badge` `type` (incl. `recommendation`),
  `Button` `color="red"`/`size`, `ButtonToggle` `text`/`selected`,
  `SelectList` `size="md"`/`labelDisplay="hidden"`, `Heading` `size`,
  `Link` `display="inlineBlock"`, `Modal` `accessibilityModalLabel`/`heading`/
  `footer`/`onDismiss`, `TapAreaLink` `target`/`fullWidth`/
  `accessibilityCurrent`, `Table.SortableHeaderCell` `status`/`sortOrder`/
  `onSortChange`.
- **Component token names:** `--color-background-button-primary-{default,
  hover,active}`, `--color-background-button-selected-default` and
  `--color-text-link` all survive, so the override approach the old
  `theme.js` used still works. Note `--color-background-button-selected-default`
  now defaults to near-black (`--color-background-selected-base`) rather than
  to Gestalt red.
- **`Toast` `type`:** `'default' | 'success' | 'error' | 'progress'`. The board
  passes only `success`/`error`, so it is unaffected.
- **`Table.SortableHeaderCell` still never sets `aria-sort`.** The string
  `aria-sort` appears nowhere in `gestalt.es.js` at 177.0.12, so the
  `SortableHeaderCell` adapter in `JobsBoard.jsx` is still required. Its
  comment was updated from "gestalt@160" to say so.

### Checked against the handoff BRIEF.md "Gestalt facts"

**No contradiction found.** Every fact in the brief's checked-facts list that
this batch touches matches the installed type definitions:

- `Box` `rounding` is `0 | 1 | 2 | ... | 8 | 'circle' | 'pill'`, and the number
  is a step on the rounding scale, so `rounding={4}` is `--rounding-400` =
  16px, as the brief says. (The board keeps its current `rounding={3}` = 12px:
  the visual redesign is JOZ-278.)
- `Heading` sizes are `100 | 200 | 300 | 400 | 600 | 700` — note no `500` —
  mapping to 12/14/16/20/28/36px. `Text` sizes are `100`–`600`, `weight` is
  `'bold' | 'normal'`.
- `Flex` `gap` is a number (times 4px) or a `{ row, column }` pair.
- `SelectList` `size` is `'md' | 'lg'` only.
- `Tag`'s `onRemove` is indeed required, and `Badge` indeed takes `text` only.
- `Modal` takes `heading`, `footer`, `onDismiss`, `accessibilityModalLabel`.

One harmless **omission** (not a contradiction) worth noting for JOZ-278: the
brief lists `Button` colours as "gray, red, blue, transparent, white, dark,
light". 177 also has `semiTransparentWhite` and `transparentWhiteText`. The
brief's substantive point — that `Button` takes no custom colours, so the brand
needs a wrapper or CSS variables — is correct, and this batch took the
CSS-variable route.

### Build warnings (pre-existing, upstream)

`npm run build` succeeds and emits one `lightningcss` warning:

```
[lightningcss minify] 'import' is not recognized as a valid pseudo-class.
... .RMk{cursor:grabbing}:import("./Focus.css"){...
```

This comes from `gestalt/dist/gestalt.css` itself: the published bundle leaks a
CSS-modules `:import("./Focus.css")` rule (one occurrence). It is a warning
from a dependency's own stylesheet, not from this app's CSS, and the build
output is correct. The separate "chunks larger than 500 kB" notice is also
pre-existing and is about bundling Gestalt as one chunk.

## Design tokens and typography wiring (JOZ-277)

### One canonical token form

The handoff ships both `tokens.json` (version 3) and a `tokens.css` generated
from it. The repo vendors **only the CSS**, as `src/design/tokens.css`, because
the CSS is the form the app actually consumes; keeping the JSON as well would
mean two sources of truth that could drift. Values are a verbatim port. The
only deviations, both documented in the file's own header:

1. `!important` on every declaration — required to beat the
   `DesignTokensProvider` tag, as above.
2. `font-display: swap` added to the two `@font-face` rules, so text is not
   invisible while the woff2 files load.

Dark mode keys off `:root[data-theme="dark"]`, exactly as the handoff's CSS
specifies. `ThemeProvider.jsx` sets that attribute from Gestalt's own
`useColorScheme()` context in a layout effect, so `ColorSchemeProvider` stays
the single control point for the scheme (including `userPreference`) and a dark
mount never flashes light values before paint. `:root[data-theme="dark"]`
(specificity 0,2,0) also outranks the plain `:root` light block (0,1,0).

### Fonts

`src/design/fonts/` holds `atkinson-hyperlegible-latin-{400,700}-normal.woff2`,
self-hosted and referenced by `@font-face` in `tokens.css` — no external font
service. Vite fingerprints and emits both into `dist/assets/`.

**Provenance note.** The sandbox blocks reads and copies across the
design-handoff directory boundary, so the two binaries could not be copied out
of the handoff directly (the text files there are readable, which is how the
tokens, README, brief and licence were ported). The handoff's own licence file
names its source exactly — "packaged by Fontsource
(@fontsource/atkinson-hyperlegible 5.3.0, latin subset)" — so the identical
files were taken from that exact package and version instead, which ships them
under the same filenames. The package was installed with `--no-save`, the two
files copied out, and the package then pruned by a plain `npm install`, so it
is not a dependency of this app.

`src/design/LICENSE-atkinson-hyperlegible.md` carries the handoff's own licence
paragraph verbatim plus the full SIL OFL 1.1 text, copyright 2020 Braille
Institute of America, Inc.

### Typeface and line heights

Gestalt classic resolves every non-code `font-family` through a single token,
`--font-family-default-latin`, so overriding that one token carries Atkinson
Hyperlegible across every Gestalt component. `--font-family-default-japanese`
is deliberately left alone: the bundled subset is latin-only.
`--font-weight-semibold` is set to `700` because only 400 and 700 exist in the
typeface and Gestalt classic sets headings and standalone links to semibold —
this is the handoff's "Gestalt's classic headings are semibold, so here they
are bold".

Line heights were the one genuinely awkward part. Gestalt classic defines
**no** line-height for `Text` or `Heading` (it has `--font-lineheight-*` only
for the datepicker), which is what the handoff means by "Line heights 44, 36,
28, 24, 20 — Gestalt classic sets none of its own in the type CSS". Two
approaches were tried and rejected before the one that shipped:

1. **Keyed on heading tag** (`h1 { line-height: 44px }` …). Rejected: Gestalt's
   `PageHeader` renders its title as an `h1` at 20px, so the board's own page
   title would have got a 44px line height on 20px text. The handoff pairs each
   line height with a font *size*, not with a heading level.
2. **A single `em` formula on `#root *`.** Correct typographically, but
   declaring `line-height` on the structural wrappers as well perturbed layout
   enough that **Chromium stopped starting a native drag on the job cards
   altogether** — no `dragstart` event fired at all and the board's
   drag-and-drop silently died. Caught by the two drag specs in
   `tests/jobs-board.spec.js`, and confirmed by instrumenting the drag events.

What shipped pairs the line height with each element's own font size and is
scoped to leaf elements, which is where text actually sits (Gestalt's `Text`
renders a div holding a string, `Heading` an `h1`–`h6` holding a string).
Leaves exclude the draggable card wrapper, the columns and every `Box`/`Flex`,
so the behaviour freeze holds:

```css
#root *:not(:has(*)),
body > div:not(#root) *:not(:has(*)) {
  line-height: min(calc(1em + 8px), calc(2em - 8px));
}
```

The second selector is for portals. `Layer` mounts its children in a `div` it
creates and appends to `document.body` (`gestalt.es.js` lines 2643–2653; the
div carries a class only when `Layer` is given a `zIndex`, which the board's
`Toast` is not), so portalled text is not inside `#root` and a `#root`-only
rule left `Toast` text at `line-height: normal`. The leaf-only constraint is
what keeps drag-and-drop alive, not the `#root` prefix, so it is repeated
verbatim on the portal selector — this declaration must never land on a
structural wrapper, whatever the scope. The two drag specs in
`tests/jobs-board.spec.js` still pass.

`em` in `line-height` resolves against the element's own font size, and the
piecewise `min()` reproduces the handoff's entire type scale exactly:

| font-size | `1em + 8px` | `2em - 8px` | result | handoff style |
| --- | --- | --- | --- | --- |
| 12px | 20 | **16** | 16px | text-100 |
| 14px | 22 | **20** | 20px | text-200 |
| 16px | **24** | 24 | 24px | text-300 / heading-300 |
| 20px | **28** | 32 | 28px | heading-400 |
| 28px | **36** | 48 | 36px | heading-600 |
| 36px | **44** | 64 | 44px | heading-700 |

It has to be declared per element rather than inherited from `body`: a
line-height given in `em` computes to an absolute length where it is declared,
and descendants would inherit that length instead of recomputing from their own
font size. `tests/theme.spec.js` asserts all six pairs.

### What the brand tokens are bound to

`design/theme.css` maps Gestalt's component-level tokens onto the brand, so the
board picks up the brand with no markup change — a `Button color="red"` renders
brand blue because the primary-button tokens are brand blue:

| Handoff token | Bound to |
| --- | --- |
| `color-brand-primary` / `-strong` | `--color-background-button-primary-{default,hover,active}`, `--color-background-button-selected-default`, `--color-background-primary-{base,strong}`, `--color-background-info-{base,strong}`, `--color-icon-info` |
| `color-brand-violet` | `--color-background-recommendation-base`, `--color-icon-recommendation` |
| `color-brand-wash-blue` / `-violet` | `--color-background-{primary,info}-weak`, `--color-background-recommendation-weak` |
| `color-brand-on-color` | `--color-text-inverse` **and** `--color-text-default`, both scoped to Button's primary fill — see "Dark-mode primary buttons" below |
| `color-background-card` | `--color-background-default` (so `Box color="default"`, `Modal` and `Popover` follow the theme) |
| `color-background-page` | `html`/`body` background |
| `color-text-{default,subtle,link,warning,error}`, `color-border-{default,container,focus}`, `space-*`, `rounding-*`, `elevation-*` | Gestalt's own token names — these re-skin Gestalt directly from `tokens.css`, no bridge needed |

### Dark-mode primary buttons: the one place Gestalt picks text colour in JS

Rebinding the primary-button *fill* to brand blue is not enough on its own,
because Gestalt chooses the label colour in JavaScript rather than in CSS, and
one of its choices is a dark-mode special case for red:

```js
const isDarkModeRed = isDarkMode && color === 'red';
const textColor = (disabled && 'disabled') || (selected && 'inverse') ||
                  (isDarkModeRed && 'default') || DEFAULT_TEXT_COLORS[color];
```

(`gestalt.es.js` lines 8034 and 8077–8081 at 177.0.12; `ButtonLink` and
`ButtonToggle` carry the same branch.) So `Button color="red"` renders
`Text color="inverse"` → `--color-text-inverse` in light mode, but
`Text color="default"` → `--color-text-default` in dark mode, which Gestalt
means as *more* contrast against its own washed-out dark-mode red. Against the
brand fill it is the opposite: dark `--color-text-default` is `#ffffff` and the
dark brand blue is `#75bfff`, i.e. **1.97:1**, far under WCAG AA's 4.5:1. An
earlier version of this file claimed the stock pairings were already correct in
both schemes; that was wrong — only the light one was.

The handoff already has the answer in `color-brand-on-color`, the foreground it
pairs with brand fills (`#ffffff` light, `#111111` dark). `design/theme.css`
binds *both* tokens Button can reach for to it, scoped to the fill itself:

```css
.Il7 {
  --color-text-inverse: var(--color-brand-on-color);
  --color-text-default: var(--color-brand-on-color);
}
```

Binding both means the pairing is right whichever branch Gestalt takes, in
either scheme, with no knowledge of the branch encoded here. `.Il7` is Gestalt
177.0.12's class for Button's `red` colour (the styles map at `gestalt.es.js`
line 6686; `.Il7{background-color:var(--color-background-button-primary-default)}`
in `gestalt.css`), so the declaration lands on exactly the element carrying the
brand fill, and the custom property inherits down to the label and no further.
Naming a hashed class is acceptable because `gestalt` is pinned to an exact
version and `tests/theme.spec.js` asserts the rendered colours *and* a computed
contrast ratio in both schemes, so a class that moved could not pass silently.
No `!important`, unlike the token files: this declaration is on the button
element, where nothing competes, and a custom property set on an element beats
one inherited from `:root` whatever the selectors' specificity.

Measured: `#111111` on `#75bfff` is 9.58:1 dark, `#ffffff` on `#005fcb` is
6.0:1 light. The board's three primary buttons — Add, Retry and "Add anyway" —
are all `Button color="red"`, so all three are covered.

**Testing dark mode needs a second mount point.** The app is pinned to
`colorScheme="light"`, and because the label colour is a JS decision, setting
`html[data-theme="dark"]` from a test proves nothing about it: the stylesheet
would flip while React stayed in light mode. `tests/theme-harness.html` is a
test-only page, served by the Vite dev server and not an entry point of
`vite build`, that mounts `design/ThemeProvider.jsx` and switches its
`colorScheme` prop through React state. That is the real transition —
`ColorSchemeProvider`, `DesignTokensProvider` and the `Button` all re-render —
and it is what the dark-mode specs drive.

### Handoff tokens NOT wired, and why

- **`color-brand-accent` (teal) and `color-brand-wash-teal`.** Defined and
  available, but not bound to any Gestalt component token. The handoff uses
  teal for the Live badge, filled fit segments and completed rounds — none of
  which exist on the current board. Binding it to Gestalt's `success` tokens
  was considered and rejected: the handoff explicitly inherits Gestalt's status
  colours ("spacing, rounding, elevation, status colours and borders" from
  `gestalt-design-tokens`) and `tokens.json` does not redefine success, so
  turning the "Salary disclosed" badge teal would be a design decision this
  batch has no mandate for. It lands with the components that need it in
  JOZ-278.
- **Focus ring geometry.** The *colour* is wired
  (`--color-border-focus`, the handoff's solid value replacing Gestalt's 50%
  blue). The handoff's "3px with a 2px offset" geometry is not: Gestalt draws
  its own focus outline widths per component, and changing them globally would
  be a visual change beyond the token swap this batch is scoped to.
- **`space-*` / `rounding-*` / `elevation-*`.** Declared, and they override
  Gestalt's identically-named tokens, but every value the handoff specifies is
  already Gestalt's own value, so they are no-ops today. They exist so JOZ-278
  can reference them, and so a future divergence is a one-line edit.
- **Density modes** ("Guided" vs "Workbench" from `directions.md`) are not
  tokenised at all — the handoff lists that as an open decision.
