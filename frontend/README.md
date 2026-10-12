---
type: Surface
title: "frontend"
description: "Describe the frontend build and development commands."
timestamp: 2026-10-11
---

# frontend

React and Gestalt single page application for the CareerOS dashboard
(owner decision JOZ-273, option C: Flask becomes a JSON API, the dashboard
becomes a React front end). M0 scope is the toolchain and the Jobs board
page only; every other page stays on the existing Jinja templates until its
own milestone.

## Build

```
npm install
npm run build
```

Output goes to `dist/`. `dist/` and `node_modules/` are gitignored; both are
produced locally or on the server, never committed.

## Development

```
npm run dev
```

Starts the Vite dev server. The app always fetches `/api/jobs?view=board`
(see `src/api/jobs.js`); in dev that request only succeeds once the Flask
API is reachable at the same origin or proxied to it. No dev-only fetch
mock exists in the application code.

## Tests

```
npx playwright install chromium
npx playwright test
```

The Jobs board JSON endpoint is not merged yet, so Playwright specs
intercept `GET /api/jobs?view=board` with `page.route` and fulfill it from
`tests/fixtures/board.json` (see `tests/helpers.js`). This keeps the
production fetch path identical between dev and test; only the test
harness injects data, never the application.

## Serving plan (prep only, no backend change in this task)

Owner default (2026-10-10): `dist/` is built on the server, not committed,
and Flask serves it behind an environment variable feature flag so friends
never see a half migrated UI. The flag reads roughly as: when set, the
`/jobs` route serves `frontend/dist/index.html` and its assets instead of
the Jinja template; when unset, the Jinja page keeps serving as it does
today. Wiring the flag into `careeros/server.py` lands with the M1 API
parity merge; no Python file changes in this task.

## Theme

The theme is the owner's design handoff, wired in `src/design/` (JOZ-277,
superseding the ad-hoc indigo/violet `src/theme.js`):

- `design/tokens.css` — the handoff tokens, light and dark. Single source of
  truth; the handoff's `tokens.json` is deliberately not vendored.
- `design/theme.css` — maps Gestalt's component-level tokens onto the brand
  tokens, and applies the typeface and line heights.
- `design/fonts/` + `design/LICENSE-atkinson-hyperlegible.md` — Atkinson
  Hyperlegible 400/700, self-hosted, SIL OFL 1.1.
- `design/ThemeProvider.jsx` — `ColorSchemeProvider` + `DesignTokensProvider`,
  and it mirrors the active scheme onto `html[data-theme]`.

Gestalt has no runtime brand-colour prop, so re-theming means redeclaring its
CSS custom properties, and that needs `!important`. The competing rule is not
stylesheet load order: `DesignTokensProvider` renders a `<style>` tag with a
fresh `:root` block of Gestalt's stock tokens on every render, and that tag
lives inside `#root` in `<body>`, always later in document order than the
stylesheets in `<head>`. Without `!important` it would win on every mount and
every re-render (e.g. a `prefers-color-scheme` change).

On Gestalt 160 the injected tag came from `ColorSchemeProvider` itself; in 177
that component is pure React context and injects nothing, so
`DesignTokensProvider` has to be rendered explicitly or there is no dark mode
at all. See `BUILD_NOTES.md` for the full 160 → 177 delta.
