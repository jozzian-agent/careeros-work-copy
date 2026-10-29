# Frontend build notes

## Gestalt 160 → 177 delta

JOZ-277 pinned `gestalt` to exactly `177.0.12` (from `^160.0.0`) to match the
owner's approved design brief, which states its component facts were checked against
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
approved design brief's `--color-background-card`. So the nav and the cards are `#ffffff` in
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

### Checked against BRIEF.md's "Gestalt facts"

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

The approved design brief ships both `tokens.json` (version 3) and a `tokens.css` generated
from it. The repo vendors **only the CSS**, as `src/design/tokens.css`, because
the CSS is the form the app actually consumes; keeping the JSON as well would
mean two sources of truth that could drift. Values are a verbatim port. The
only deviations, both documented in the file's own header:

1. `!important` on every declaration — required to beat the
   `DesignTokensProvider` tag, as above.
2. `font-display: swap` added to the two `@font-face` rules, so text is not
   invisible while the woff2 files load.

Dark mode keys off `:root[data-theme="dark"]`, exactly as the approved design
brief's CSS specifies. `ThemeProvider.jsx` sets that attribute from Gestalt's own
`useColorScheme()` context in a layout effect, so `ColorSchemeProvider` stays
the single control point for the scheme (including `userPreference`) and a dark
mount never flashes light values before paint. `:root[data-theme="dark"]`
(specificity 0,2,0) also outranks the plain `:root` light block (0,1,0).

### Fonts

`src/design/fonts/` holds `atkinson-hyperlegible-latin-{400,700}-normal.woff2`,
self-hosted and referenced by `@font-face` in `tokens.css` — no external font
service. Vite fingerprints and emits both into `dist/assets/`.

**Provenance note.** The sandbox blocks reads and copies across the
approved design brief's directory boundary, so the two binaries could not be
copied out of it directly (the text files there are readable, which is how the
tokens, README, brief and licence were ported). The brief's own licence file
names its source exactly — "packaged by Fontsource
(@fontsource/atkinson-hyperlegible 5.3.0, latin subset)" — so the identical
files were taken from that exact package and version instead, which ships them
under the same filenames. The package was installed with `--no-save`, the two
files copied out, and the package then pruned by a plain `npm install`, so it
is not a dependency of this app.

`src/design/LICENSE-atkinson-hyperlegible.md` carries the approved design
brief's own licence paragraph verbatim plus the full SIL OFL 1.1 text, copyright 2020 Braille
Institute of America, Inc.

### Typeface and line heights

Gestalt classic resolves every non-code `font-family` through a single token,
`--font-family-default-latin`, so overriding that one token carries Atkinson
Hyperlegible across every Gestalt component. `--font-family-default-japanese`
is deliberately left alone: the bundled subset is latin-only.
`--font-weight-semibold` is set to `700` because only 400 and 700 exist in the
typeface and Gestalt classic sets headings and standalone links to semibold —
this is the approved design brief's "Gestalt's classic headings are semibold,
so here they are bold".

Line heights were the one genuinely awkward part. Gestalt classic defines
**no** line-height for `Text` or `Heading` (it has `--font-lineheight-*` only
for the datepicker), which is what the approved design brief means by "Line
heights 44, 36, 28, 24, 20 — Gestalt classic sets none of its own in the type
CSS". Two
approaches were tried and rejected before the one that shipped:

1. **Keyed on heading tag** (`h1 { line-height: 44px }` …). Rejected: Gestalt's
   `PageHeader` renders its title as an `h1` at 20px, so the board's own page
   title would have got a 44px line height on 20px text. The approved design
   brief pairs each line height with a font *size*, not with a heading level.
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
piecewise `min()` reproduces the approved design brief's entire type scale
exactly:

| font-size | `1em + 8px` | `2em - 8px` | result | brief style |
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
in the brand colour because the primary-button tokens are the brand.

The table below is kept current rather than frozen at JOZ-277: the brand was
blue when this section was written and has been Matchacado green since the
2026-10-26 handover, and the 2026-10-29 batch (see "Gestalt bridge and restyle"
at the end of this file) added the box-\* and badge-\* names and the one
dialog-scoped red.

| Brief token | Bound to |
| --- | --- |
| `color-brand-primary` / `-strong` | `--color-background-button-primary-{default,hover,active}`, `--color-background-button-selected-default`, `--color-background-primary-{base,strong}`, `--color-background-info-{base,strong}`, `--color-background-box-info-base`, `--color-background-badge-info-{default,hover}`, `--color-icon-info`, `--color-icon-brand-primary` |
| `color-brand-violet` | `--color-background-recommendation-base`, `--color-icon-recommendation` |
| `color-brand-wash` / `-violet` | `--color-background-{primary,info}-weak`, `--color-background-box-info-weak`, `--color-background-recommendation-weak` |
| `color-background-{warning,error}-weak`, `color-text-{warning,error}` | `--color-background-box-{warning,error}-weak`, `--color-icon-{warning,error}` |
| `color-text-error`, `color-background-danger-hover` | `--color-background-button-primary-{default}` / `{hover,active}`, scoped to `[role="alertdialog"]` — the one red fill, see "Gestalt bridge and restyle (2026-10-29)" |
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

The approved design brief already has the answer in `color-brand-on-color`, the foreground it
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

### Brief tokens NOT wired, and why

- **`color-brand-accent` (teal) and `color-brand-wash-teal`.** Defined and
  available, but not bound to any Gestalt component token. The approved design
  brief uses teal for the Live badge, filled fit segments and completed rounds
  — none of which exist on the current board. Binding it to Gestalt's
  `success` tokens was considered and rejected: the brief explicitly inherits
  Gestalt's status colours ("spacing, rounding, elevation, status colours and
  borders" from `gestalt-design-tokens`) and `tokens.json` does not redefine
  success, so turning the "Salary disclosed" badge teal would be a design
  decision this batch has no mandate for. It lands with the components that
  need it in JOZ-278.
- **Focus ring geometry.** The *colour* is wired
  (`--color-border-focus`, the brief's solid value replacing Gestalt's 50%
  blue). The brief's "3px with a 2px offset" geometry is not: Gestalt draws
  its own focus outline widths per component, and changing them globally would
  be a visual change beyond the token swap this batch is scoped to.
- **`space-*` / `rounding-*` / `elevation-*`.** Declared, and they override
  Gestalt's identically-named tokens, but every value the brief specifies is
  already Gestalt's own value, so they are no-ops today. They exist so JOZ-278
  can reference them, and so a future divergence is a one-line edit.
- **Density modes** ("Guided" vs "Workbench" from `directions.md`) are not
  tokenised at all — the brief lists that as an open decision.

## Jobs board rebuild (JOZ-278)

### Drag-and-drop: hand-rolled, not a library

The brief says "Gestalt has no kanban and no drag and drop, so use a drag
library." This batch hand-rolls native HTML5 drag-and-drop instead, for
three reasons:

1. **It was already load-bearing.** The pre-rebuild board already used native
   `draggable`/`onDragStart`/`onDragOver`/`onDrop` for its single
   column-to-column move, proven reliable under Playwright's `dragTo()` in
   this exact dev-server setup (two passing drag specs in the old
   `tests/jobs-board.spec.js`). JOZ-277's own BUILD_NOTES entry above records
   how fragile that wiring is — a global `line-height` rule on structural
   wrappers once stopped `dragstart` from firing at all — which is a reason to
   touch it minimally, not a reason to add a second, unproven drag
   implementation on top of it.
2. **React 19 peer risk.** The obvious off-the-shelf choice,
   `react-beautiful-dnd`, is unmaintained and was never updated for React 18
   strict mode, let alone the React 19 this app now runs (JOZ-277). `dnd-kit`
   would work but is a new dependency, with its own sensor/collision-detection
   model to learn and audit, to replace code that already existed and worked.
3. **The mockup agrees.** `pages/Main.dc.html`'s own reference implementation
   (`support.js` is referenced but does not exist in the approved design
   brief; the drag
   logic is inline in the page's `<script>`) is itself hand-rolled native
   HTML5 drag-and-drop with the identical shape this batch uses: a dragged
   card fades to 40% opacity, the hovered column gets a dashed primary
   outline, dropping on a card inserts before it, dropping on the column body
   appends to the end, and a cross-column move speaks through one `move`
   function also reachable from the status control.

The implementation lives in `JobsBoard.jsx`'s `performMove`/`undoMove` plus
the drag handler factories (`cardDragHandlers`, `columnDragHandlers`), not in
`KanbanBoard.jsx` itself: the component only renders the chrome the handlers
drive (the dashed ring, "Drop here"/"No jobs here yet"), per the README's
"Consumer provides: columns, cards per column, drag handlers." A same-column
drop is a pure client-side reorder (the board API has no concept of card
position, only status); a cross-column drop is the real status mutation,
reusing the same per-job generation counter the status dropdown already had
for overlapping-request safety. Undo rolls back only the one card — its exact
column and slot, read from the live `entries` at undo-time, not a frozen
whole-board snapshot — then fires a second `PUT` to actually revert the
status server-side. If that second `PUT` fails, the generation counter is
checked again before reconciling the card back to the moved-to status: if a
newer move already landed on the same card while the Undo was in flight, the
counter has moved past the Undo's own generation and the stale failure is
not allowed to clobber it.

### Component registry

New files under `src/components/`, one per design-system component this
ticket touches:

| Component | Gestalt building blocks | Notes |
| --- | --- | --- |
| `KanbanBoard.jsx` | `Flex` (`overflow="scrollX"`, `wrap={false}`), `Box` (320px columns), `Heading`, `Badge`, `Text` | Presentational only; drag state and the move/reorder logic stay in `JobsBoard.jsx`. |
| `JobCard.jsx` | `Box`, `Flex`, `Heading`, `Icon`, `Link`, `Text`, `Badge`, `Button` | Also exports `CompanyDisplay`/`IngestIndicator`, reused by the untouched `ListView`, so there is one definition of each, not two. |
| `FitChip.jsx` | `Box`, `Text` | Raw inline SVG for the three rated icons, not Gestalt `Icon` — see "FitChip icon colour" below. |
| `StatusSelect.jsx` | `Box`, `Button` (`size="sm"`), `Dropdown`/`Dropdown.Item` | Replaces the old `SelectList`; see "StatusSelect geometry" below for the one place it does not match the brief's exact pixels. |
| `Message.jsx` | `Box`, `BannerSlim` | One `FloatingMessage` used for every board toast (success and error alike), per the Message README's "Gestalt's Toast is not used." |
| `AddJobPopupShell.jsx` | `Modal`, `Button`, `Flex`, `Text` | Shell only; see "Add-job popup" below. |

### FitChip icon colour

Gestalt's `Icon` `color` prop only reaches Gestalt's own semantic icon tokens
(`--color-icon-error`, `--color-icon-warning`, …), not the brief's specific
`color-text-error` / `color-text-warning` / `color-brand-accent` tokens.
Wiring those would mean extending `design/theme.css` with a per-icon-class
override the way JOZ-277 did for `Button color="red"` — disproportionate for
three small glyphs. `FitChip` instead renders the three rated levels as raw
inline `<svg>` elements using the exact path data from the component README,
filled directly with the right CSS variable. The default ("Needs your input")
state and the "Lucky" clover were always going to be custom paths regardless
(Gestalt has no clover), so this keeps one rendering strategy for all four
chip states instead of mixing `Icon` for two of them and raw SVG for the
other two.

### StatusSelect geometry

The README specifies 112×32px, 8px rounding, 12px bold text,
`color-border-default` border. `StatusSelect` uses a stock Gestalt
`Button size="sm"` (32px tall, Gestalt's own pill rounding and label size)
inside a `Box width={112}`, rather than reproducing the exact rounding/font
via a hashed-class override. The accessible behaviour (opens a `Dropdown`,
`accessibilityLabel="Move <title> to"`, same handler as drag) matches the
brief exactly; only the corner-radius/font-size pixels do not. Flagging this
rather than silently shipping it, since it is the one place this batch traded
visual fidelity for not adding another fragile hashed-class dependency.

### Fit data

The backend has no `fit` field yet (BRIEF.md: "Fit is set by dropdown on the
job detail page until it is calculated automatically" — that dropdown is a
later ticket). `JobCard` reads `job.fit` if present and falls through to the
"Needs your input" default otherwise, so the board is forward-compatible with
no API change. `tests/fixtures/board.json` gives every entry an explicit
`fit` (`no_fit`/`lucky`/`excellent`) so the real board fixture exercises all
three rated chips; the unrated default is covered separately in
`tests/fit-chip.spec.js` against a one-entry fixture override, to keep it
decoupled from the main fixture's existing assertions.

### Kept from the pre-rebuild card, against the JobCard README

The README's anatomy is exactly three groups (fit/status, title/company,
location/dates) and says explicitly "No source tag and no AI-generated tag on
the card." This batch keeps the pre-existing source/salary/function/
AI-generated badges and the ingest-failure "Retry" affordance underneath
those three groups, rather than deleting them:

- Ingest retry is real functionality (the only way to retry a failed
  fetch/extract from the board), not decoration. JOZ-278's scope is the
  fit/status/drag rebuild; deleting a working recovery path is not part of
  that and has no replacement surfaced anywhere else yet.
- The company-match review state (`CompanyDisplay`, the "Needs your input"
  badge for `company_link_state: "needs_review"`) is a different feature
  (company matching, pre-existing) that happens to reuse the same words as
  the brief's fit-chip default. The fixture's one `needs_review` entry
  (`JOB-002`) is given a rated fit (`lucky`) specifically so the two concepts
  never collide on the same card; see `tests/fit-chip.spec.js`.
- Task item 8 ("keep the AI-generated label") was read as applying to this
  existing board badge too, not only the detail-page summary card it
  literally names, since the ticket gave no instruction to remove it and
  removing it would be an unrelated, unprompted content change.

### Add-job popup: shell only, old intake path untouched

The plus button next to Board/List (per BRIEF.md's page-level button, not a
per-column one — "column header plus-button" in the ticket is read as the
board's own header row, where the Board/List toggle already lives) opens
`AddJobPopupShell`: a `Modal` with a heading and a footer "Close" button.
Gestalt's plain `Modal` (unlike `ModalAlert`) renders no dismiss icon of its
own, so the visible "close" the ticket asks for is that footer button; Escape
and an outside click also call `onDismiss` via `Modal`'s own defaults. The
field, validation states and Cancel/Add job buttons are explicitly out of
scope ("popup contents are next batch"). The existing inline "Posting URL"
`TextField` + Add button below the board is left completely alone and stays
the one working intake path — removing it now, before the popup has the same
capability, would be a functional regression this ticket does not ask for.

### Status move copy changed to match the brief

The status-change success toast changed from the old "Status updated" to
"Moved to `<Column>`" with an Undo action, and the toast mechanism itself
changed from Gestalt `Toast` (in a `Layer`) to a `BannerSlim`-based
`FloatingMessage` in the same fixed bottom-centre container, per the Message
README ("Gestalt's Toast is not used"). Both changes are mandated by the
ticket, not incidental: `tests/jobs-board.spec.js` and the new
`tests/drag-undo.spec.js`/`tests/message-lifetime.spec.js` assert the new
copy and the new success/error lifetimes (success auto-hides at ~4s, error
persists until dismissed — the brief lists both as open decisions; the ticket
resolves them this way).

### Test-only fixture change

`tests/fixtures/board.json` gained one field per entry, `fit`. It is additive
and test-only: production API behaviour, the `statuses`/`function_options`
contract and every other field are unchanged, so this is not a backend
contract change, just enough test data to exercise the new chip.

## Filter bar and add-job popup rebuild (JOZ-279)

Fills in the two pieces JOZ-278 deliberately left as a shell: the filter row
and the add-job popup's contents.

### Component registry

| Component | Gestalt building blocks | Notes |
| --- | --- | --- |
| `FilterBar.jsx` | `Box`, `Flex`, `Popover`, `Tag` | Chip order Fit, Function, Location, More filters, a divider, Needs attention, then the result count; the active-filters Tag row with Clear all sits below. One Popover (or the More filters panel) open at a time. |
| `FilterChip.jsx` | `Icon`, `Text` | The one chip shape shared by every filter control, per the README's "same chip, a count badge, filled only when active." A plain `<button>`, not `Button`/`TapArea`: the chip's content (label, count pill, chevron) is composite, and the count pill is `aria-hidden` so the accessible name stays just the label. |
| `FilterPopoverPanel.jsx` | `Box`, `Checkbox`, `SearchField`, `Button` | The Fit/Function/Location popover body: checkbox list with counts, a search field once a group has more than six options, "Show N more", Clear and Apply. Checking a box filters the board immediately — there is no separate draft state, so Apply/Clear only close or reset this one panel. |
| `MoreFiltersPanel.jsx` | `OverlayPanel`, `Fieldset`, `Checkbox` | Industry and Company size, each a `Fieldset` with "(estimated)" in the legend per the README (both are CareerOS-classified, not posting-stated). Same immediate-filter behaviour as the popovers. |
| `AddJobPopup.jsx` | `Modal`, `TextField`, `Spinner`, `BannerSlim`, `Button` | Replaces `AddJobPopupShell.jsx` (deleted). The five README states — ready, reading, not a link, already on your board, couldn't read — map to one `status` prop computed in `JobsBoard.jsx` from `intakeBusy`/`intakeError`/the popup-eligible half of `duplicate`. |

### Needs attention: a count, not just a toggle

The brief upgrades Needs attention from a plain toggle (JOZ-278) to "a toggle
with a count, same chip style as the others." The count is
`board.entries.filter(job => job.needs_attention).length` — the same
client-side field the toggle already filtered on — so no backend change was
needed; only the badge is new.

### Industry and Company size stay client-side

The backend has no per-job industry facet or size bucket, so both "More
filters" groups are computed from each job's existing `industries` array
and raw `employee_count` in `JobsBoard.jsx`. `COMPANY_SIZE_BUCKETS` (see
above) is new in this batch, not carried over from JOZ-278: it mirrors the
same micro/small/medium/large thresholds the backend uses for a company's
`size_class`, since the board's "Company size" facet did not exist before
this filter row did. No API schema change.

### The inline "Posting URL" field is retired

JOZ-278 kept the pre-existing `TextField` + Add button below the board
deliberately, because the popup was a shell with no field yet. Now that
`AddJobPopup` carries the full intake flow (the same `intakeJob` endpoint,
the same duplicate handling, the same force-retry path), the inline field is
a second, redundant entry point to the identical action — fewest-elements
says keep one. It is removed from `JobsBoard.jsx`; intake now lives only in
the popup opened by the plus button. `tests/jobs-board.spec.js`'s intake
specs moved to `tests/add-job-popup.spec.js` and `tests/theme.spec.js`'s two
intake-touching assertions were updated to open the popup first.

### Popover vs. OverlayPanel, and one open panel at a time

`FilterBar` tracks a single `openPanel` key covering both the three
Gestalt `Popover`s (Fit, Function, Location) and the `OverlayPanel` (More
filters): opening one dismisses whichever of the other four was open,
matching the mockup (only one filter surface visible at once) and avoiding
the bookkeeping of independent open/closed state per chip.

### Duplicate states the popup does not name, and why they stay

The README's five named states do not include "a duplicate that is also
eligible for promotion" or "Add anyway." Both predate this ticket (the separate `DuplicateDialog` in `JobsBoard.jsx`,
from the original M0 board) and stay reachable: a duplicate whose existing job is already on the user's board
(`in_pipeline !== false`) is the popup's own "already on your board" state;
one that is only in the shared universe closes the popup and hands off to
`DuplicateDialog`, which still offers Promote/Open existing/Add
anyway/Cancel. Dropping either path, or the popup's own "Add anyway" for the
on-board case, would regress working backend-supported actions with no
replacement — the same reasoning BUILD_NOTES.md already records for
JOZ-278's kept badges and ingest-retry affordance.

## Detail pages rebuild (JOZ-280)

Rebuilds Job, Experience, Company and Company Classification on the shared
DetailHeader/SectionCard skeleton, adds client-side routing
(`react-router-dom`, pinned `^7.18.4`), and cuts the four Jinja detail pages
over to React with no coexistence (owner decision). Phase A (wireframes for
the four edit popups and the delete confirmation) was approved before this
batch started; the four flagged defaults from that approval are honored as
given (Edit job excludes Status/Fit/classification, Edit position carries
the full form into the popup, Edit criteria is job-detail-only with Company
Classification staying a full page, and the company delete 409 renders
inline in the `ModalAlert`).

### Routing: no Jinja fallback for detail pages, unlike the list pages

`server.py` already gated `/jobs` on `CAREEROS_REACT_UI` with a Jinja
fallback whenever the flag is off or the build is missing (JOZ-273). The
owner decision for this batch is narrower for the four detail routes
(`/jobs/<id>`, `/experiences/<id>`, `/companies/<id>`,
`/companies/<id>/taxonomy`): they exist **only** behind the same flag, with
their Jinja routes, view functions and templates removed outright rather
than kept as a fallback. `tests/test_react_ui_flag.py` pins both directions
explicitly (`test_flag_on_serves_react_for_every_detail_route`,
`test_flag_off_detail_routes_404_with_no_jinja_fallback`): flag off means a
genuine 404, not a degraded page. List pages (`jobs.html` and friends) are
untouched and keep the dual-mode behavior.

One bug this surfaced that no existing test caught: the shared
`react_index` lambda the four new `add_url_rule` calls point at took no
arguments, but Flask calls a `<identifier>`-carrying route's view function
with that value as a keyword argument — every detail route 500'd until the
lambda became `lambda **_kwargs: send_from_directory(...)`. Caught by
manually exercising the built `dist/` against the flag before writing the
regression test above, not by the view layer itself.

`/jobs/<id>/taxonomy` (the pre-existing standalone job classification
page) is deliberately **not** part of this cutover and stays Jinja,
unconditionally, regardless of the flag: the routing list this ticket
specifies names only `/jobs`, `/jobs/:id`, `/experiences/:id`,
`/companies/:id` and the company classification route, and the Phase A
wireframe reads job classification as owned by the new Edit criteria popup
instead of a navigated-to sub-page. The page's own JSON API
(`/api/jobs/<id>/taxonomy`) is unchanged and is what the popup actually
reads and writes through — the Jinja page itself is simply no longer
linked from anywhere once `job_detail.html` is gone, not removed.

`/experiences/new` and `/experiences/<id>/edit` (the full-page Jinja
add/edit form) are also untouched: the ticket's routing list doesn't name
them, the Experiences list page (out of scope, still Jinja) links to
`/experiences/new` for Add, and nothing demanded deleting the edit route
just because the Edit position popup now duplicates its fields.

### Backend removal: routes, views and templates, not the context builders

Removed: the four Jinja view functions (`jobs.detail`, `companies.detail`,
`companies.taxonomy`, `experiences.detail`) and their four templates
(`job_detail.html`, `company_detail.html`, `company_taxonomy.html`,
`detail.html`). Kept, because the JSON `view=page`/`/taxonomy` API
endpoints still call them: `detail_context`/`job_context` (jobs),
`detail_context`/`company_context`/`classification_context` (companies),
`detail_context`/`experience_context` (experiences). None of the record
read/write logic changed — only the Jinja-rendering wrapper functions and
their templates are gone.

### Component registry

| Component | Gestalt building blocks | Notes |
| --- | --- | --- |
| `DetailHeader.jsx` | `Link`+`arrow-back` `Icon`, `Heading` size 600, `Text`, `Button`, `location` `Icon` | Back link's accessible name is `Back to <label>` (not the bare label), set via `Link`'s `accessibilityLabel` — the visible text still matches the brief's "← Jobs", but the bare label collides with the Nav tab of the same name for assistive tech and for Playwright's role queries alike. |
| `SectionCard.jsx` | `Box`, `Heading` size 300, `Badge` | Also exports `DividerList`, `KeyValueGrid`, `EmptyState`, the three body shapes the README lists (paragraph is just `Text`, no wrapper needed). One definition of each, reused by every detail page. |
| `FitSelect.jsx` | `Box`, `Button` (`size="sm"`), `Dropdown`/`Dropdown.Item` | The Job detail page's Fit control. No fit-editing UI existed anywhere before this ticket (JOZ-278 left the board's `FitChip` read-only), so this is new, built as the exact same sm-Button-opens-Dropdown recipe as `StatusSelect` rather than inventing a second control shape. The job record's `fit` field gets its first writer here — written through the existing generic `PUT /api/jobs/<id>`, no new endpoint or schema change, since the vault's job record is schema-less. |
| `EditJobPopup.jsx` / `EditCompanyPopup.jsx` / `EditPositionPopup.jsx` / `EditCriteriaPopup.jsx` | `Modal`, `TextField`, `TextArea`, `Checkbox`, `Fieldset`, `SelectList`, `BannerSlim` | One component per approved Phase A wireframe; field sets match the wireframes exactly. All four save through existing PUT endpoints (`/api/jobs/<id>`, `/api/companies/<id>`, `/api/experiences/<id>`); `EditPositionPopup` also calls the existing `POST /api/experiences/<id>/link-company` for its company field, including the fuzzy-match suggestion round-trip (surfaced via `window.confirm`, matching `experience_form.html`'s own prompt rather than inventing a second confirmation UI for one edge case). |
| `DeleteConfirmModal.jsx` | `ModalAlert`, `BannerSlim` | One template, three copy variants (job/experience/company), per the approved wireframe. The company variant's 409 "still linked" response renders as a `BannerSlim` inside the still-open alert rather than closing it — the brief's "failures are visible states" rule, applied literally. |

### Notes editing consolidated into the Edit popup, not left inline too

Earlier reference mockups (not part of the approved design brief, and not
shipped in this repo) show an inline, always-editable Notes `<textarea>`
with its own "Save notes" button directly on the detail page. The approved
JOZ-280 Phase A wireframes
*also* put a notes field in the Edit job and Edit company popups. Gestalt's
`SectionCard` README only lists four body shapes (paragraph, divider list,
key/value grid, empty state) — an inline editable-textarea-with-its-own-save
body is not one of them. Read together, the mockups are describing the
pre-existing Jinja behavior carried into the reference image, not a second
intentional editing surface; this batch picked one editing path (fewest
elements), so the Notes `SectionCard` on Job and Company detail renders the
stored value read-only (job notes rendered from the markdown the backend
already computes; company notes as plain text, since company notes were
never markdown-rendered anywhere even in Jinja), and the popup is the only
way to change it.

### Company detail's "show Retry" decision moves client-side

`company_detail.html`'s Jinja template computed, inline, whether to show a
Retry affordance (any enrichment field `exhausted`/`flagged`, a review flag
present, or the company never enriched at all — three different messages).
None of that decision was exposed as a precomputed field on the JSON
`view=page` payload; `CompanyDetail.jsx`'s `retryState()` reproduces the
exact same condition from the same underlying fields
(`enrichment.field_states`, `review_flags`, `sectors`/`size_range`/
`size_class`), scoped to `kind === 'employer'` like the backend
`retry_company` endpoint already is. `tests/test_sectors.py`'s six
Jinja-button-presence tests were rewritten to pin that the JSON API still
carries exactly those fields, since the rendering decision itself is no
longer backend-testable.

### Known gap, flagged rather than silently dropped: company-review resolution

`job_detail.html` had an inline "Company needs your input" card letting the
owner pick a candidate or create a new company
(`POST /api/jobs/<id>/resolve-review`) when `company_link_state ===
'needs_review'`. This ticket's `JobDetail.jsx` shows that state (so it is
never silently invisible, per the product's "failures and unknowns are
visible states" rule) but does not yet implement picking a candidate or
creating a company from the React page — that resolution UI has its own
candidate list, score display and inline create-company form, which is
scope beyond "rebuild the detail-page skeleton." The API the Jinja page
used is untouched and reachable directly; porting the resolution UI itself
is left for a follow-up ticket.

### Ingest failure/pending states carried over, enrichment retry card too

Unlike the company-review gap above, the job's own ingest-failure/pending
messaging (`fetch_failed`/`extract_failed`/`stub`/`fetched`) and its Retry
button (`POST /api/jobs/<id>/extract`) are implemented in `JobDetail.jsx` —
this is the product's "never silent" rule applied to the one state that
most needed it (a stuck or failed ingest with no visible way to retry would
be a real regression, not just a visual gap). The Jinja page's live-polling
behavior while extraction is pending (`checkEnrichment`'s 4s interval) is
not ported; the page shows the pending state from the loaded snapshot and
the owner can reload or use the Retry button, rather than this batch adding
a second polling mechanism alongside the board's own refresh-on-focus
pattern.

### Test suite: Jinja-rendering tests converted to API-level tests, not just deleted

Removing four templates breaks every existing test that asserted on their
rendered HTML. Per the ticket's explicit instruction, each was handled one
of two ways, never a blanket skip:

- **Converted to assert the same underlying data via the JSON `view=page`/
  `/taxonomy` endpoints**, wherever the Jinja assertion was really pinning
  record state the API exposes unchanged (e.g. `summary_source`,
  `has_description`, `watch_eligible`, `show_remote_chip`, `sector_labels`,
  `enrichment.field_states`). This is the large majority — `test_jobs.py`,
  `test_company_kind.py`, `test_sectors.py`, `test_function_facet.py`,
  `test_watcher.py`, `test_vault.py`, `test_fix261.py`, `test_ingest.py`,
  `test_company_resolve.py`, plus two renamed in place in
  `test_taxonomy_pages.py` (`test_detail_pages_link_to_taxonomy` →
  `test_job_detail_omits_standalone_taxonomy_link`) and `test_jobs.py`
  (`test_job_detail_description_escapes_html` →
  `test_job_detail_description_round_trips_exactly`), each now asserting
  the same underlying fact through the JSON API instead of rendered HTML.
- **Removed outright**, only where the assertion was about Jinja/vanilla-JS
  mechanics with no data-level analog — exact `<dialog>` markup and its
  inline `onclick` strings (`test_delete_detail_buttons`, 2 parametrized
  cases), the idle/pending re-enrich button markup
  (`test_job_detail_no_reenrich_button_when_idle`,
  `test_job_detail_polls_only_while_pending`), the 1200/1201-character
  description-collapse boundary markup
  (`test_job_detail_description_boundary_1200_collapsible`,
  `test_job_detail_description_boundary_1201_reconstructs_exactly`), the
  editable-title markup (`test_job_detail_has_editable_title`), running an
  extracted `<script>` block under Node to test polling logic
  (`test_check_posting_client_behavior`, 3 parametrized cases), and DOM
  element ordering on a page that no longer has Jinja-rendered DOM at all
  (`test_batch_d_job_card_order`, `test_check_posting_summary_placement`).
  Section ordering and the delete flow are covered instead by the new
  Playwright specs below, which test the thing that actually renders them
  now.

Net effect on the suite: 919 → 909. Nine test functions were removed
outright, expanding to twelve collected cases once their
`@pytest.mark.parametrize` lists are counted (`test_delete_detail_buttons`
and `test_check_posting_client_behavior` each cover more than one case);
two cases were added in `test_react_ui_flag.py` for the routing regression
caught during manual verification
(`test_flag_on_serves_react_for_every_detail_route`,
`test_flag_off_detail_routes_404_with_no_jinja_fallback`); the two renames
above are a like-for-like swap and net zero. 12 − 2 = 10, matching
919 − 909. This is moved coverage for the renamed/converted cases, but a
real, uncompensated loss of backend-level coverage for the twelve removed
outright — the Playwright specs that now exercise the equivalent UI mock
every API call (`page.route`), so they confirm the React page renders and
wires up correctly against a scripted response, not that the real Flask
view and vault logic underneath still behaves the way the removed tests
pinned.

### Frontend Playwright specs

New fixtures (`frontend/tests/fixtures/job-detail.json`,
`job-taxonomy.json`, `experience-detail.json`,
`experience-tags-registry.json`, `company-detail.json`,
`company-taxonomy.json`) and four spec files (`job-detail.spec.js`,
`experience-detail.spec.js`, `company-detail.spec.js`,
`company-classification.spec.js`, plus edit/delete coverage folded into
each rather than separate files, since every popup is page-specific),
45 tests total, cover: header rendering (type label, title, subtitle,
chip, actions), the back link's navigation, SectionCard ordering via
heading order, the Status and Fit dropdowns' PUT payloads, every edit
popup's open/fill/save/cancel round-trip, and the delete `ModalAlert`'s
confirm/keep/409-inline-error paths. `tests/helpers.js` gained matching `mockJobPage`/`mockJobTaxonomy`/
`mockExperiencePage`/`mockExperienceTagsRegistry`/`mockCompanyPage`/
`mockCompanyTaxonomy`/`mockUpdate`/`mockDelete` helpers, following the
existing `mockBoard`/`mockMove` pattern (intercept the real fetch path,
never a dev-only mock branch in application code).

Two authoring pitfalls worth recording for the next batch using this same
pattern: a bare `page.getByRole('heading').allTextContents()` right after
`page.goto()` races the mocked fetch's resolution (fixed by waiting for the
title heading first), and reusing a record's bare label text for a visible
back-link ties it to the Nav tab's identical text — both are now avoided
via `DetailHeader`'s `accessibilityLabel` (see the component registry
entry above) plus an explicit wait before reading heading order.

## List pages rebuild (JOZ-283)

Migrates the three remaining Jinja pages (Search/home, Experiences list
and Companies list) to React, the same no-coexist cutover JOZ-280 used for
the detail pages. No backend API or JSON contract changed: all three read
the existing `view=page` endpoints (`experiences.page_context`,
`companies.page_context`, `search.page_context`) exactly as they stood.

### Component registry

| Component | Gestalt building blocks | Notes |
| --- | --- | --- |
| `ExperiencesList.jsx` | `PageHeader`, `ButtonLink`, `Box`, `Flex`, `Heading`, `Link`, `Badge`, `Text` | Card frame matches `SectionCard`'s own (`rounding={4}`, `borderStyle="sm"`), built inline rather than through `SectionCard` itself, since a card here is a link to a different record, not a titled content section. |
| `CompaniesList.jsx` | `PageHeader`, `SelectList`, `Box`, `Flex`, `Heading`, `Link`, `Badge`, `Text` | The sector/size filters are two plain `SelectList`s, matching the Jinja page's own two `<select>` controls. They are not the Jobs board's Popover-based `FilterBar`/`FilterChip`, which is a different, heavier filter UI this page's brief never asked for. |
| `SearchCriteria.jsx` | `PageHeader`, `SectionCard`, `DividerList`, `TextField`, `TextArea`, `BannerSlim`, `Box`, `Flex`, `Button`, `Text` | One `SectionCard` per criteria section plus a Notes `SectionCard`; the remove-× button is a plain native `<button>` (styled inline), the same precedent `FilterChip`'s chevron and `EditCriteriaPopup`'s tag chips already set for a small custom control with no exact Gestalt equivalent. |

No new files under `src/components/`; every new piece above is either a
direct Gestalt primitive or an existing shared component (`SectionCard`,
`DividerList`), reused rather than duplicated.

### API shape: no flattening, despite the suggestion to consider it

The ticket brief suggested flattening `experiences.page_context`'s
`companies` field from an id→record dict to an id→name dict, mirroring
the Jobs board's own `view=board` flattening. This batch did not: the
list page only ever needs to know whether a given `company_id` resolves
to a real record (to decide whether to render a link), and the `labels`
field already carries the exact display text, and the dict's values are
never read for anything else. Flattening would have been a backend
change with no behavioral benefit, and would have broken the pinned
`test_api_experiences.py` contract (`LIBRARY_SHAPE`'s `companies` field)
for no reason beyond the suggestion itself. Reuse ladder step 1 ("is it
needed at all?") says no.

### Routing: "/" retires the redundant "/search" URL, not a dual-mode fallback

Unlike `/jobs` (JOZ-273's own dual-mode cutover, kept as-is and untouched
by this ticket), Search, Experiences list and Companies list get the same
no-coexist treatment JOZ-280 gave the four detail pages: `server.py`
mounts the SPA index at `/`, `/experiences` and `/companies` only when
`CAREEROS_REACT_UI=1`, with the three Jinja `add_url_rule` registrations
(the module loop's `search`/`experiences`/`companies` entries, plus the
separate `/` → `search.build_page` index rule) removed outright rather
than kept as a flag-off fallback. With the flag off, all three now 404;
`tests/test_react_ui_flag.py` pins both directions, mirroring the detail
pages' own two tests.

The Jinja `search.html` template answered to both `/` and `/search` (the
module loop registered the second). That redundancy is retired, not
carried over: the Search page's only URL is now `/`. `Nav.jsx` (and the
Jinja `nav_html()`/`page_shell()` wordmark link in `theme.py`, still used
by `/jobs` when the flag is off and by the untouched `/experiences/new`,
`/experiences/<id>/edit` and `/jobs/<id>/taxonomy` pages) both special-case
the `search` slug's href to `/` instead of `/{slug}`, since fewest-elements
says one URL per page rather than two that happen to render the same
thing. One consequence, flagged rather than silently accepted: with the
flag off, those Jinja pages' own Search nav link now points at `/`, which
404s (no Jinja fallback), the same already-accepted degradation the
JOZ-280 detail-page links carry when the flag is off.

The three now-unused Jinja view functions (`search.build_page`,
`experiences.build_page`, `companies.build_page`) are deleted, along with
their now-unused imports (`flask.current_app`/`flask.render_template` via
`careeros.web.ui.page`). The `page_context`/`library_context`/
`directory_context`/`criteria_context` functions they called stay, since
the JSON API routes still call them directly.

### Companies list: client-side filtering, no "no results" state

The Jinja `companies.html` filter script never rendered a dedicated empty
state for a filter combination that matches nothing. It simply hid every
non-matching card via `card.hidden = true`, leaving a blank grid. The
React page reproduces this exactly (it renders the filtered subset, not
the full list with a `hidden` flag, since there is no requirement for the
non-matching DOM nodes to persist) rather than inventing a "no results"
message the Jinja page never had. The filter semantics themselves, that
sector matches ANY of the company's sectors and size matches `size_class`
exactly, are also copied verbatim from the Jinja inline script.

### Search criteria: edit/save/cancel ported verbatim from the Jinja script

`SearchCriteria.jsx`'s state machine (`backup`/`editing`/`busy`) is a
direct port of `search.html`'s own inline script: Edit snapshots a
`structuredClone` backup; Cancel restores it with no network call; Done
POSTs the whole payload and, on failure, keeps the edits and stays in
edit mode rather than reverting, so the owner can retry (the JOZ-280
round-3 lesson about never dismissing/reverting a view while its own save
request is still in flight, applied here to Cancel-and-Done rather than a
popup's dismiss). Edit/Done/Cancel are all disabled while `busy`, exactly
as `editButton.disabled=doneButton.disabled=cancelButton.disabled=busy`
did.

### Test suite: Jinja-rendering tests converted or removed, same policy as JOZ-280

Removing the three templates breaks every test asserting their rendered
HTML. Each was handled the same two ways BUILD_NOTES already documents
for JOZ-280:

- **Converted to assert the same underlying data via the JSON `view=page`
  endpoints**: `test_vault.py` (criteria/empty-library checks),
  `test_company_kind.py` (live company-label resolution, now read from
  `labels`), `test_jobs.py` (`/companies` open-jobs count, now read from
  `counts`), `test_sectors.py` (directory sector labels resolve to human
  text, now read from `sector_labels`; added as a new focused test rather
  than silently dropped, since the removed Jinja test was the only place
  pinning the directory-level *value*, not just its shape).
- **Removed outright**: `test_shell.py`'s `test_routes` parametrization
  for `search`/`experiences`/`companies` (folded down to `/jobs` only,
  with the nav-ordering assertion taught the `/` exception),
  `test_sectors.py`'s three Jinja-filter-markup tests (`id="sector-filter"`,
  `data-sectors`, the no-backfill-button check), and `test_jobs.py`'s
  `test_search_one_edit_affordance` and
  `test_search_local_edits_cancel_save_and_rollback` (the latter extracted
  `search.html`'s inline `<script>` and ran it under Node, the exact
  precedent JOZ-280 set for `test_check_posting_client_behavior`). The
  equivalent behavior for all of these is now exercised by the three new
  Playwright specs below, against the real React page instead of
  extracted/reimplemented markup.

Net effect on the pytest suite: two tests removed with a replacement
added in the same batch (`test_sectors.py`), plus `test_routes`'s three
removed parametrize cases and the two whole-test removals in
`test_jobs.py`, a real, uncompensated loss of backend-level coverage for
those two, exactly as JOZ-280 recorded for its own twelve removed cases.
The new Playwright specs confirm only that the React pages render and
behave correctly against mocked data, not that the Flask view layer
underneath still behaves identically in every edge case the removed
tests pinned: all three specs intercept their own GET `view=page` read
with `page.route` (`mockExperiencesPage`/`mockCompaniesPage`/
`mockSearchPage`), and the Search criteria spec also intercepts every
POST `/api/search` write (`mockSaveSearch` and the spec's own
in-flight/failure routes), so none of the three specs exercises the real
Flask view layer at all.

Separately, and against the real Flask app rather than a mock: a
synthetic vault was served on a throwaway port with `CAREEROS_REACT_UI=1`
to confirm `/`, `/experiences` and `/experiences/new` (still Jinja),
`/companies`, and `/jobs` each answered with the expected content before
this batch was called done. This is a manual, one-time check, not part
of the automated suite, and carries no route-level regression coverage
of its own going forward.

### Frontend Playwright specs

New fixtures (`frontend/tests/fixtures/experiences-list.json`,
`companies-list.json`, `search-criteria.json`) and three spec files
(`experiences-list.spec.js`, `companies-list.spec.js`,
`search-criteria.spec.js`) cover: the Experiences card list (title,
company link only when `company_id` resolves, skill/tag chips, the local
tag's tooltip marker, the people-led chip, the empty state) and its own
Add position links; the Companies filters (sector alone, size alone,
both together, and a combination matching nothing); and Search's full
edit flow (add an item, remove an item, edit notes, Done posts the saved
payload, Cancel restores the pre-edit backup, a save failure keeps the
edits and stays in edit mode, and the Create criteria empty state).
`tests/helpers.js` gained `mockExperiencesPage`/`mockCompaniesPage`/
`mockSearchPage`/`mockSaveSearch`, following the existing
`mockJobPage`/`mockCompanyPage` pattern.

### `moveJobStatus` deliberately not refactored onto the new generic `updateJob`

The Fit dropdown and the edit popups needed a generic job PUT helper
(`updateJob`, added to `frontend/src/api/jobs.js`), and the obvious
simplification was to make the existing `moveJobStatus` call it instead of
duplicating the fetch. That broke three pre-existing JOZ-278 specs
(`jobs-board.spec.js`, `drag-undo.spec.js`, `message-lifetime.spec.js`):
they mock a failing move with `{ error: 'nope' }` and assert the fixed
toast text `"Status update failed."`, which `moveJobStatus` has always
thrown verbatim regardless of the response body. `updateJob` instead
surfaces the server's actual `error` message, which is the right behavior
for a popup save but would have silently changed the board's own toast
copy to `"nope"`. Reverted to keeping `moveJobStatus` self-contained with
its own fixed message; `updateJob` is a separate function for the new call
sites only.

## Detail pages realignment, package 1 (2026-10-14 canvas)

Rebuilds the Job and Company detail pages to the approved canvas, lands
the design-system updates it needs, and fixes the three frontend bugs the
code check found (3, 5, 7). The backend contexts these pages read landed
first, in the same round's backend packages; their keys are documented in
`docs/surfaces/json-api.md` and the page layouts in
`docs/surfaces/detail-pages.md`.

### Component registry

| Component | Gestalt building blocks | Notes |
| --- | --- | --- |
| `AiLabel.jsx` | `Box`, `Text` | The dashed provenance label, "AI-generated" for text a model composed and "AI-extracted" for text it lifted out of the posting. Custom rather than a `Badge`: every Badge type carries a fill and a colour, and this label must not read as a state the owner has to act on. Replaces `SectionCard`'s plain `label` badge, whose one caller moved to `aiLabel`. |
| `LevelTag.jsx` | `Box`, `Text` | A must-have (filled) or nice-to-have (outlined) requirement or skill. Custom for the same reason, plus Gestalt's `Tag` is a dismissible input affordance. The level is carried by the fill and by a visually hidden prefix, never by colour. |
| `NeedsInputCard.jsx` | `SectionCard` (`needs-input`), `RadioGroup`, `TextField`, `Button`, `Badge`, `Link` | The Job page's one ask, in two variants (company, read-failed), plus the `NeedsInputChip` both pages put in their header. Candidates are `RadioGroup.RadioButton` rows, which hold up at three. Which ask is shown is the backend's `needs_input`, never section order. |
| `Requirements.jsx` | `Flex`, `Text`, `DividerList`, `LevelTag` | Takes grouped entries `{group, level, text}` from day one; `requirementEntries` is the package-1 adapter over today's two flat lists plus skills. Package 2 swaps the adapter alone. Prose groups render as rows, facet groups (skills, languages) as tags. |
| `ExtractionPopup.jsx` | `Modal`, `DividerList`, `Button`, `Text` | "How this was extracted": one row per covered field with its result (`field_status`) and its source (`field_provenance`), and a link to the surface that can set a field the posting did not mention. Replaces the permanent Extraction card and its eight status badges. |
| `EditClassificationPopup.jsx` | `Modal`, `Fieldset`, `Checkbox`, `SelectList`, `TextField`, `Button` | One popup with a job variant (function, tags, the company's sector read-only) and a company variant (sector, size). Replaces `EditCriteriaPopup.jsx` (job only) and stands in for the retired `/companies/<id>/taxonomy` page. |

Removed with their last caller: `FitSelect.jsx` (the Fit dropdown wrote a
value nothing read; Fit is now the read-only "Not calculated yet"
placeholder) and `EditCriteriaPopup.jsx` (superseded above).

### Why the two collapsed sections are `Accordion.Expandable`, one each

Gestalt's plain `Accordion` is a static card with a title: the previous
page wrapped the posting text in one and it was never collapsible. The
collapsible component is `Accordion.Expandable`, and one instance keeps at
most one item open, so Original posting and Details are separate instances
rather than two items of one accordion: opening the posting must not close
Details. Both get their own `accessibilityExpandLabel`, because Gestalt
names every toggle "Expand section" by default, which is ambiguous with
two of them on a page (and is what the specs address them by).

### The one frontend string the backend owns

The extraction row says when the posting was last read, which it finds by
matching the resolved history entry whose label is "Details read from the
posting". That label belongs to `careeros/history.py` (`READ_LABEL`), so
`tests/test_history_registry.py::test_read_label_is_the_words_the_job_page_matches_on`
pins the value the page matches on; rewording the label without the page
would otherwise silently empty that line.

### Fields with no setter, named rather than linked

The extraction popup links a not-found field to where it can be set. Three
covered fields have no owner-editing surface anywhere in the product:
company (the link is settled by the needs-input card, not by a field),
seniority and employment type (no form has ever carried them). Those rows
show their result and no link, instead of pointing at a surface that
cannot set them. Adding fields for them was not in this package's brief.

### Languages are not editable yet, because nothing stores them

The brief's Edit job list names "skills and languages as removable tags".
Skills are a stored job field and are implemented. There is no `languages`
field on a job record (`careeros/vault.py` `_record_defaults`) and nothing
extracts one, so no languages editor ships here: it would be an interface
element standing for a feature that does not exist. Languages arrive with
package 2's requirement groups, which the `Requirements` component already
renders.

## Companies list rework (2026-10-15)

Surface-level summary and the owner's locked decisions:
`docs/surfaces/companies.md`. This is the implementation rationale.

### FilterBar stopped being jobs-only

The brief asked the Companies list to reuse the board's filter bar, which
held three jobs-only constants (`POPOVER_GROUPS`, `MORE_GROUPS`, the word
"jobs" in the result count) and a hard-coded "Needs attention" label.
Those are now three props — `groups`, `countNoun`, `needsLabel` — passed
by each page, with `inMore: true` on a group marking it as living inside
the More filters panel and `legend` carrying that panel's own wording.
`MoreFiltersPanel` went the same way: it took `industryOptions`,
`companySizeOptions` and a toggle per group, and now renders one
`GroupFieldset` per group it is handed. The Companies page passes no
`inMore` group, so it gets no More filters chip at all (the chip renders
only when some group lives there).

`countBy` and `sortedOptions` moved out of `JobsBoard.jsx` into
`src/filters.js`, which both pages import, plus one new helper,
`presentOptions`: options over a fixed vocabulary, kept in the
vocabulary's order and dropping values no record has. That is what keeps
the Size panel reading Small → Large (never micro, which no company is
in) rather than ordering size classes by popularity.

### Open jobs is a tri-state facet on a two-checkbox model

The owner asked for "Any / With open jobs / Without open jobs". FilterBar's
model is a list of checked values per group, so the facet ships as two
checkboxes whose cleared state IS "Any": nothing checked matches every
company, and so does checking both. This reuses the existing panel and
active-filter machinery instead of adding a radio-group concept (and its
own Tag/Clear semantics) to a component two pages now share.

### The grid, and why the card height is a constant

`repeat(auto-fill, minmax(260px, 1fr))` with a 16px gap, through Box's
`dangerouslySetInlineStyle` (Gestalt has no grid primitive; same escape
hatch FilterBar's divider uses). Equal width comes from `1fr`; equal
height cannot, because a grid row sizes to its tallest item and one ISIC
section label ("Public administration and defence; compulsory social
security") is 61 characters. So the card carries a fixed height with
`overflow="hidden"`, the text rows are `lineClamp`ed, and the chip row is
pinned with `marginTop="auto"`. The spec measures bounding boxes at 1280px
and 390px and asserts one distinct height across every card, so a future
content change that stretches a card fails rather than quietly raggedizing
the grid again.

### Name truncation and the tooltip

30 characters plus one ellipsis, per the owner's decision, applied in the
frontend only. `Heading`'s own `lineClamp` sets `title` to its children
when they are a string — which would have put the *truncated* name in the
tooltip — so the name renders as a `<span title={fullName}>` child, which
leaves Heading's auto-title off and keeps the clamp. The sector line uses
`Text`'s own `title` prop for the same reason, since its labels are what
actually overflow two lines.

### Company size on the board now reads the company's class

`COMPANY_SIZE_BUCKETS` and `companySizeBucket()` are gone. They
re-implemented `org_intake.classify.SIZE_CLASS_THRESHOLDS` in JS over each
job's raw `employee_count`, which meant the facet disagreed with the
card's own size badge (that badge has always read `company_size_class`)
for every posting that stated no headcount but whose company is
classified. The board payload now carries `size_classes`, the same
vocabulary key the Companies contracts already had, so the order the panel
lists classes in also comes from the backend rather than a literal array
in JS.

## Fit chip removed from the board card (M0-4, 2026-10-15)

Owner decision Q14: the board card says nothing about fit until fit
scoring exists. `JobCard.jsx` no longer renders `FitChip`, so its top row
holds the status select alone (`justifyContent="end"` in place of
`"between"`, since there is no left-hand element left to space against).
No board payload or contract changed: `job.fit` was never a stored field
(it is not in `vault.job_field_names()`, so even the JOZ-280 Fit dropdown's
`PUT` never persisted one), which is exactly why every card showed the
unrated state.

`FitChip.jsx` stays, because the Job detail page renders it with the
backend's `fit_placeholder` ("Not calculated yet"). Its second, violet
"Needs your input" state is gone with the board: that branch only ran for
a caller that passed no `placeholder`, the board card was the only such
caller, and the words asked the owner for a rating they have no way to
give. The three rated levels are kept as they are, so the chip is ready
for the scoring milestone.

Tests: `tests/fit-chip.spec.js` is deleted, since both of its cases
asserted board-card chips. `tests/jobs-board.spec.js` gains one case that
fails if any rated label or the placeholder reappears on a card; the
fixture entries still carry `fit` values, so the assertion has something
to catch. The detail page's own placeholder case in
`tests/job-detail.spec.js` is untouched and still covers the surviving
rendering path. The filter bar's Fit facet is left in place (see
[jobs surface](../docs/surfaces/jobs.md) open questions): it renders and
works, and dropping a working control was not this task's decision to
make.

## Jobs board D7 frontend (2026-10-15)

The frontend half of owner decision D7, against the canvas approved
2026-10-15 (claude.ai artifact 7PBPPwtEXZEmQdeNXd4b8S). Surface summary in
[docs/surfaces/jobs.md](../docs/surfaces/jobs.md), component entries and
recorded overrides in
[docs/decisions/design-system.md](../docs/decisions/design-system.md).
No backend contract changed.

### Everything comes from the payload

The board holds no copy of the status vocabulary. Columns are
`statuses` minus `ended_statuses`, the words are `status_labels`, the lane
groups are `ended_statuses`, the reason suggestions are `end_reasons` per
status, the note title is `end_note_title`, the split in the filter bar is
`counts`, and the Ended lane stats are `search_so_far`. The one place this
used to be decided in JS was `titleCase(status)` for a column heading,
which now only survives as the fallback for a payload that predates
`status_labels`.

`closed_review` carries the whole decision about the closed posting: the
rows the banner asks about, and the `days_closed` each card's warning chip
prints. A card never subtracts dates, so the chip and the banner cannot
disagree and the threshold lives in one place (the backend's
`CLOSED_REVIEW_DAYS`).

### The Ended lane keeps the right edge by staying out of the scroller

`EndedLane.jsx` renders beside the horizontally scrolling columns box, not
inside it, so the columns scroll under nothing and the lane simply keeps
the right edge of the content column. `KanbanBoard.jsx` is therefore a flex
row of two things: the scrolling box (`flex="grow"`, `minWidth={0}`, which
is what lets it shrink below its content width) and the lane.

The first attempt put the lane at the end of the scrolling row with
`position: sticky; right: 0`. That needed two fixes and still ended up
wrong:

1. It did not stick at all, because Gestalt's `Flex` wraps every child in a
   `FlexItem` div exactly as wide as the child, and a sticky element can
   only be offset within its own containing block. Replacing the row with a
   plain flex `div` made it stick.
2. Sticking made the lane a *positioned* element, and a positioned element
   paints above anything rendered in a Gestalt `Layer` that carries no
   z-index of its own. The More filters panel is such a Layer, so the lane
   covered that panel's own footer buttons, and clicking "Show N jobs" hung
   on an obscured element. Removing the lane's own `z-index` did not help,
   since `auto` on a positioned element is still enough.

Staying outside the scroller needs no stacking rules, no sticky, and no
plain-div override, so the columns row is Gestalt's `Flex` again.

The lane is collapsed on every load and nothing is stored: remembering it
is on the brief's own deferred list, and a reload collapsing it again is
the behaviour the brief asks for, not an oversight.

### One ending flow, three entrances

`requestEnd(id, status)` is the single door into an ended status. The
status select, a drop on a lane group and the chooser the collapsed lane
opens all call it, so Won confirms from every route and Rejected and
Stopped move at once from every route. The chooser is a `Popover`
anchored to the strip the card was dropped on, taken from the drop event
rather than a ref, with `role="dialog"` and `shouldFocus`, so it is
reachable and dismissable from the keyboard;
dropping is not keyboard-reachable at all, which is why the status select
carries the same three options under a labelled `Dropdown.Section`.

`performMove` gained an optional `fields` argument, merged into the same
`PUT` and into the optimistic card. Its one caller is the review popup's
Stop, which is one owner decision (stop this, because the posting closed)
and so one write rather than a move plus a second request that could fail
on its own. A rollback restores those fields to what the record carried
before, so a failed Stop does not leave a reason behind on a card that
never moved.

### The reason popup reads the status the job has now

`reasonForId` is state, not the job record. The message that offers "Add a
reason" is created inside `performMove`'s success handler, which closes
over the board as it was BEFORE the move landed; storing the record there
made the popup offer the suggestions of the status the job was leaving
(and, with an open status, none at all). The popup derives its job from
the current `board.entries` on every render instead.

A saved reason updates that one card rather than reloading the board.
A reload here would discard any other card's in-flight optimistic move,
which is the bug class this board was already fixed for once (PROJECT.md
2026-10-12). Keep and Stop are optimistic for the same reason, and both
restore the row they removed if the write fails.

### FilterBar toggles became a list

The bar took one fixed needs-attention pair of props. D7 adds "Hide closed
postings" beside it, so the four props are now one `toggles` array of
`{key, label, count, countColor, pressed, onToggle}`; `CompaniesList.jsx`
passes its own single entry. Clear all resets every toggle with the groups,
and each pressed toggle renders its own removable Tag. The Fit facet is
gone from `FILTER_GROUPS`, with `fitValue`, `FIT_LABELS` and the fit
filter branch deleted.

`summaryText` is a new optional prop: the text the count shows while no
filter is on, which the board uses for the open and ended split. Once a
filter is on the existing "N of M" form wins, because the count has to
describe what is shown.

### Phone layout

`src/layout.js` holds `PHONE_MAX_WIDTH` (719) and `usePhoneLayout()`, a
`matchMedia` subscription whose first value is read synchronously so the
first paint is already the right layout. Below that width the board
renders one column, picked from a chip row of the same `FilterChip` the
filter bar uses, with Ended last; the lane renders with
`collapsible={false}`, which drops the Show and Hide buttons and the
sticky pinning, since one column shows at a time.

Nothing is draggable there: `cardDragHandlers` and the column handlers are
simply not passed, so `JobCard` renders `draggable="false"` and the empty
column stops inviting a drag it cannot take. The whole board is wrapped in
Gestalt's `DeviceTypeProvider deviceType="mobile"`, which is how Modal,
Dropdown and Popover become full-width sheets without a second set of
mobile components. The cost is recorded as an open question on the surface
doc: Gestalt's `Modal` does not pass `accessibilityModalLabel` through to
`SheetMobile`, so a sheet is named "Bottom sheet" and its own heading
carries the identification.

### Announced counts are singular at one

`src/counts.js` holds `jobCount`, the one place that turns a number into
the words a screen reader hears beside a column, the lane or a lane group.
The live check read back "Interested, 1 jobs" before it existed.

### The stale fixture

`tests/fixtures/job-detail.json` was stale in the same way and now carries
the eight statuses, `status_labels`, and the four D7 job fields, which is
what `JobDetail.jsx` reads to label its own status control.

`tests/fixtures/board.json` still described the pre-D7 board (rejected,
closed and withdrawn as columns, none of the new keys), so every spec was
exercising a contract the backend no longer serves. It now carries the
real payload: the eight statuses with `status_labels`, `ended_statuses`,
`counts`, `end_reasons`, `end_note_title`, `closed_review` and
`search_so_far`, and every entry carries `closed`, `closed_at`,
`closed_reviewed_at` and `end_reason`. The nine entries cover what the
flows need: an empty open column (Interviewing), a closed posting under
the week (neutral chip), one over it in Interested (warning chip and the
banner), one in Applied that is long closed (neutral, no banner, which is
the case that must not warn), a won job whose history still carries its
interview and offer, a rejected job with a reason, a stopped job with a
reason and one without.

Specs: `ended-lane.spec.js`, `ending-flow.spec.js`,
`closed-postings.spec.js` and `board-phone.spec.js` are new.
`jobs-board.spec.js`, `kanban-board.spec.js`, `drag-undo.spec.js` and
`filter-bar.spec.js` were updated to the open-column board (the Fit facet
cases are gone, the per-card loop runs over the open jobs, and the ended
cards are covered by `ended-lane.spec.js` instead).

### Withdrawn lives on as a Stopped reason (owner click-test, 2026-10-16)

The click-test asked where Withdrawn went: D7 renamed the status to
Stopped, and both "never pursued" and "pulled out of a live
application" landed there with nothing to tell them apart. Owner chose
a reason rather than a new status, so `vault.STOPPED_REASONS` gained
"Withdrew application" between "Took another offer" and "Posting
closed". Vocabulary-only change: the popup renders the payload's list,
the board fixture and `test_board_d7.py`'s pinned tuple were updated
with it, and `end_reason` keeps storing the picked string verbatim.

## AI status chip and polling (CAREER-37, 2026-10-17)

The backend half (CAREER-36) moved every AI call off the request path:
`POST /api/jobs/<id>/enrich`, `/extract`, `/re-extract` and
`POST /api/companies/<id>/enrich` answer `202 {"status": "queued"}` and
the work runs on a queue inside the Flask process, one unit at a time.
Where that work stands is written on the record itself, as `ai_status`
(queued, running, done, failed), `ai_error` when it failed, and
`ai_started` / `ai_finished`. A record with no `ai_status` never tried,
which is every record written before the field existed.

### No new visible element

The component gate landed on reuse. `QuietChip` is already the board's
one machine-state notice (design-system.md "Badge usage", owner decision
2026-10-13: subtle text, secondary-base ground, a container border at
most, never an alarm), and the gray `Retry` beside a failure is the
button `IngestIndicator` already offered. So `AiStatusChip.jsx` composes
those two plus Gestalt's own `Spinner` and adds no visual element of its
own. The three words are the ones the board already used for the same
three facts: "Enrichment pending" for a reading that has not started,
"Details filling in…" for one under way, "Extraction failed, <reason>"
for one that did not land. A finished reading gets no chip: success is
already carried by what the reading wrote.

Two things the brief asked for are not as it drew them, both because the
design system record governs that call:

- The failed chip is a quiet chip, not an error tone. The owner's badge
  decision reserves colour for an owner-action signal and a provenance
  marker, and names a failed extraction as the case that must never
  alarm. The one recorded exception is the warning closed chip, which the
  canvas asked for by name.
- The reason is on the surface beside the chip rather than behind a
  hover. A tooltip is out of reach on a touch screen and for a keyboard,
  and the card already shows an ingest failure's reason this way.

### Where it shows

`IngestIndicator` (inside `JobCard`) checks the record's own AI status
first and falls through to what it always inferred from `ingest_state`
when there is none, so an old vault reads exactly as it did. The Job
detail page puts the same chip in the extraction row, which is already
the row about the reading, and its Retry is the same extraction retry as
the button beside it.

### Polling

`aiStatus.js` holds the vocabulary and `anyReading(jobs)`, so the chip
and the polling cannot disagree about what counts as in flight. The board
reloads `/api/jobs?view=board` every five seconds while at least one job
is queued or running; the effect simply does not re-arm once none is,
which is how it stops itself. The Job detail page already polled on
`llm_pending` and pending fields, so the AI status joined that condition
rather than adding a second timer.

What re-arms the board's own effect is a `pollTick` counter it bumps
after every attempt, not the board payload (fix round C4). The first
version depended on `[board]` alone, and a poll whose fetch failed leaves
the board exactly as it was: the effect never re-ran, so one bad response
ended the polling for the life of the page and left the chip saying
"Details filling in…" forever. Counting the attempt rather than the
result costs a transient failure one interval and no more, and cannot
storm the server either way, since the effect holds one timer at a time
and clears it on every re-run. A failed poll still shows the board's
ordinary load error with its Retry, per the product rule that a failure
is a visible state with a reason; the difference is that it now also
recovers on its own.

Specs: `tests/ai-status.spec.js` is new (the three chip states, the
no-chip-on-done case, Retry hitting `/extract`, polling starting and
stopping, polling surviving one failed request, and the chip on the job
page). No fixture changed: each case builds its board payload from
`fixtures/board.json` with the field under test set on one entry, so a
chip can only come from that field.

## Login page and the 401 rule (M1, 2026-10-17)

Every page and every API call now needs a session. The backend half is
one `before_request` in `careeros/server.py` plus `careeros/users.py`;
this note is the front end's half.

### Component gate: two new visible elements, both from adopted components

The login page is `pages/Login.jsx`: a `Heading`, one `Text` line, two
Gestalt `TextField`s (`type="email"` and `type="password"`) and one
primary `Button`, laid out in the `Box`/`Flex` pattern every other page
uses. The design system record asks for plain fields and one primary
button with no new visual language, which is exactly that, so nothing
here is custom
and the gate needs no exception. The password field shows Gestalt's own
"Show password" control, which comes with the component rather than
being an element this page added.

The logout affordance is one `Button size="sm" color="transparent"` in
`Nav.jsx`, the chrome every page already renders. It is not a settings
page and not a menu, because a menu holding one action is a container
earning nothing.

The login page is the one route outside `App.jsx`'s `Page` wrapper, so it
carries no nav: every link the nav could show leads back to the login
page until there is a session.

### The no-build fallback is a second rendering, not a second page

`GET /login` serves the built React page when the front end is built and
the same form rendered from `careeros/web/theme.py`'s shell when it is
not. `/jobs` has had exactly this fallback since the React migration
started, and the one page a person must be able to reach before they have
a session cannot be the one page that needs a build. Both post to the
same endpoint, which content-negotiates on the request body: a JSON body
gets JSON, a form post gets a redirect. The fallback page carries no CSS
of its own. The shared control styles in `careeros/web/ui.py` already
cover a label, an input and a primary button.

### One home for the 401

`src/api/client.js` is new and holds `apiFetch`, which every function in
`src/api/` now calls instead of `fetch`. A 401 from any endpoint means
the same thing, so the answer is given once: take the browser to
`/login`, and latch a module flag that makes every later call reject
without touching the network. The latch is what keeps a lost session from
turning into a request storm, and it needs no reset, because the redirect
is a page load and a fresh module starts clean.

Two deliberate exceptions:

- No redirect while the page is already `/login`. The login page's own
  401 is the answer to a sign-in attempt, not a lost session, and
  redirecting on it would loop past the message the person needs to read.
- The board's polling effect also checks `sessionEnded()` before arming
  its timer. The latch already stops the requests, so this is about the
  loop itself: without it the effect would keep re-arming every five
  seconds on a page that is navigating away. It is covered by the same
  spec as the latch rather than by one of its own, because a timer that
  issues no request has nothing a browser test can observe.

### Known limits, accepted rather than solved

Both are the brief's own calls, for a test of five people.

- No CSRF token. What the app has is `SameSite=Lax` on the session
  cookie plus same-origin JSON writes, which stops the ordinary
  cross-site form post. A token is the real answer and is not here.
- No rate limiting on `POST /login`. Five testers and one admin-created
  account list make an online guessing attack cheap to notice and
  pointless to run, but nothing in the app slows one down.

### Specs

`tests/login.spec.js` is new: a 401 sends the visitor to the login page,
the right credentials land on the board, a refused sign-in shows one
message and stays put (the no-loop case), Log out asks the server before
navigating, and a 401 while the board is polling asks nothing more. That
last one aborts the navigation to `/login` on purpose, so the board stays
mounted and the polling has every chance to carry on; what it asserts is
that exactly one request met the 401 and none followed.
`tests/page-health.spec.js` gained `/login`, with its own landmark since
it is the one route with no nav. No fixture changed.

## Gestalt bridge and restyle (2026-10-29)

The brand went green in the 2026-10-26 handover (`src/design/tokens.css`).
This batch is the half that makes Gestalt follow it everywhere, plus the
restyle of four components the owner's brief names. No layout, component
structure, copy, behaviour or API changed; the decisions are recorded in
`docs/decisions/design-system.md`, "Tokens, the bridge and the restyle,
2026-10-29".

### The alias trap, found twice more

`gestalt.css` ships a `:root` block that aliases its component tokens to
its semantic ones:

```css
--color-background-box-info-weak: var(--color-background-info-weak);
--color-background-badge-info-default: var(--color-background-info-base);
--color-background-badge-info-hover: var(--color-background-info-strong);
```

Read as CSS, binding `--color-background-info-weak` to the brand wash
carries all three. Read as what actually runs, it does not:
`DesignTokensProvider` re-emits **every** token as a resolved literal on
`:root` from inside `<body>`, later in document order, so the alias is
replaced by Gestalt's own hex before any of our values can flow through
it. This is the same trap `design/theme.css` already recorded for the
popover ground; this batch found two more components standing in it.

- `BannerSlim type="info"` takes its ground from
  `--color-background-box-info-weak` (`MESSAGING_TYPE_ATTRIBUTES` maps
  `info` to `Box color="infoWeak"`, and `.Am_` in `gestalt.css` is
  `background-color:var(--color-background-box-info-weak)`), so the
  closed-postings banner was still `#d7edff`.
- Every `Badge type="info"` — "AI-generated" on the Job page, the function
  chips — takes its fill from `--color-background-badge-info-default`, so
  they were still `#0074e8`.

All eight info names are now bound in `design/theme.css`, and
`tests/theme.spec.js` asserts the eight resolved values **and** that no
element on the board is painted in any of Gestalt's three info blues, so
a ninth alias appearing in a future Gestalt would fail here rather than
render blue. The same binding is applied to
`--color-background-box-{warning,error}-weak` and
`--color-icon-{warning,error}`: Gestalt's stock light values already equal
the handover's, so nothing moved on screen, but the agreement is now this
theme's instead of a coincidence of two palettes.

### The one red fill: scoping by role, not by prop

Rebinding `--color-background-button-primary-*` to the brand is what makes
`Button color="red"` green with no markup change. The one place that is
wrong is a destructive confirmation.

Gestalt builds a `ModalAlert`'s primary action as `Button color="red"`
(`ModalAlertAction`, `gestalt.es.js` line 18059: `const color = type ===
'primary' ? 'red' : 'gray'`) and renders the alert with
`role="alertdialog"`. `ModalAlert` has exactly one caller in this app,
`components/DeleteConfirmModal.jsx`, and every use of it is a delete — so
the role *is* the destructive case and no component had to grow a prop:

```css
[role='alertdialog'] {
  --color-background-button-primary-default: var(--color-text-error);
  --color-background-button-primary-hover: var(--color-background-danger-hover);
  --color-background-button-primary-active: var(--color-background-danger-hover);
}
[role='alertdialog'] .Il7 {
  --color-text-inverse: var(--color-background-card);
  --color-text-default: var(--color-background-card);
}
```

No `!important`, for the reason the `.Il7` block already gives: these land
on the dialog element, and a custom property declared on an element beats
one inherited from `:root` whatever the root's importance. Both label
tokens are bound because Gestalt picks between them in JS. Measured:
`#ffffff` on `#cc0000` is 5.25:1. The secondary action is
`Button color="gray"` and reads none of these, so "Keep job" is untouched.

### Links: excluding the button that is an anchor

`#root a { text-decoration-line: underline }` underlined every anchor,
including a Gestalt `ButtonLink` — an `<a>` wearing a button's chrome,
which the Experiences page's "Add position" is. The rule now skips
`.USg`. That class is the `button` entry of both of Gestalt 177.0.12's
button style maps (`styles$U`, used by Button/ButtonLink, and `styles$E`)
and appears in no other map, so it names "this element is a button"
rather than a shape something else might also want; `.USg{min-width:60px}`
is all it draws. Once the rule stops matching, Gestalt's own
`.NtY{text-decoration:none}` on the same anchor takes over. Same
pinned-version precedent as `.Il7` and the typography classes, with
`tests/theme.spec.js` asserting both halves on one page.

Nav items are `TapAreaLink`s and carry no `.USg`: they are links and keep
the underline. No chip needed excluding — every chip in the app is a
`<button>` or a `<div>`.

### FilterChip: two grounds, one of them with a hover

The brief's B2 is 32px high (it was 40), 14px bold, pill radius,
`--color-background-secondary-base` unselected with a darker hover, brand
wash plus a 2px brand border selected.

The hover is why the two grounds moved out of the component's inline
style into the new `components/FilterChip.css` (the `StatusSelect.css`
precedent). A hover cannot be written inline at all, and splitting it —
inline ground, hover in the stylesheet — is worse than either, because an
inline declaration outranks every rule in a stylesheet and the hover would
need `!important` just to reach the element. The geometry stays inline,
where the height is a prop.

`.filter-chip-selected:hover` repeats the selected values on purpose:
`.filter-chip:hover` is (0,2,0) and `.filter-chip-selected` is (0,1,0), so
without it the chosen view greyed out under the pointer.

The brief names the hover "fill-secondary-hover". The token set ported
from the handoff has no name of that form; `--color-background-secondary-
weak` (`#d6d4cd`) is its one darker partner to the base, so the hover
binds to that rather than to a token invented here.

The two view pairs (Jobs' Board/List, Companies' Tiles/List) pass
`height={44}` explicitly and keep it: that is the height of the primary
button beside them (artboard 2026-10-18). 32px is the default, so it is
the filter row's height. **Known gap:** at 32px the filter chips are under
WCAG 2.5.5's 44px touch target at phone widths, as they were at 40px.
`StatusSelect.css` has the precedent for fixing that with a media query;
the brief did not ask for one, so none was added.

### What this batch did not touch

`LevelTag` and the Ended lane were both already compliant: the level tag's
three colours are `--color-background-secondary-base`, transparent and
`--color-border-container`, and the lane is the secondary ground with a
brand-wash drag-over. Only their comments changed, which said "blue".

### Specs

`tests/theme.spec.js` gains four tests: the ButtonLink exclusion against
an ordinary link on the same page, the info banner's rendered ground, icon
and text contrast plus all eight info tokens and a no-blue sweep, the
destructive confirm's fill/hover/active/label against the brand primary
outside the dialog, and AA for ink on the brand wash and on the info wash
with the two grounds asserted equal. `tests/filter-bar.spec.js` gains the
chip's metrics and its three grounds including the hover, and one test
pinning the view pair at 44px while the filter row is 32px. No other spec
changed: nothing else pinned a colour this batch moved.
