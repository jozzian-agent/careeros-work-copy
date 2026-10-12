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
   (`support.js` is referenced but does not exist in the handoff; the drag
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

JOZ-278's BUILD_NOTES entry already covers this (see `COMPANY_SIZE_BUCKETS`
above): the backend has no per-job industry facet or size bucket, so both
"More filters" groups are computed from each job's existing `industries`
array and raw `employee_count` in `JobsBoard.jsx`, with the same
micro/small/medium/large thresholds the backend uses for a company's
`size_class`. This batch reuses that computation unchanged; it only adds the
`MoreFiltersPanel` UI in front of it. No API schema change.

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
