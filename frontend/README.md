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

`src/theme.js` overrides Gestalt's default red accent with the blue and
purple pair already used by the Flask dashboard
(`careeros/web/theme.py`: `--accent-indigo` for primary actions,
`--accent-violet`, the page's link accent, for links and hover). The
competing rule is not stylesheet chunk load order: `ColorSchemeProvider`
(wrapping the app in `App.jsx`) renders its own `<style>` tag with a fresh
`:root` block containing Gestalt's default tokens, every time it renders.
That tag lives inside `#root` in `<body>`, always later in document order
than this override's `<head>` style, so without `!important` it would win
the cascade on every mount and every `ColorSchemeProvider` re-render (e.g.
a `prefers-color-scheme` change). `!important` makes the override win
regardless of DOM order.
