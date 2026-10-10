# Gestalt React Front End — Implementation Plan (JOZ-273 follow-through)

> **For Hermes:** Use subagent-driven-development skill to implement this plan
> task-by-task. Owner gate before starting build: approval of this plan and of
> the M0 sketch.

**Goal:** The whole dashboard is a React front end on Gestalt (blue/purple),
served from the existing Flask app as a JSON API, with every owner-approved
behavior from batches A–D preserved and click-tested page by page.

**Architecture:** Flask keeps the vault, ingest, enrichment and AI logic and
exposes JSON. A React SPA (Vite build, `frontend/`) consumes it. Migration is
incremental: the Jinja page stays live until its React replacement passes the
owner click-test, then it is deleted in the same change (AGENTS.md: an element
that stops earning its place is removed in the same change).

**Tech Stack:** React 18, Gestalt + gestalt-tokens, Vite, Flask JSON API,
pytest (API) + Playwright (SPA), existing verify.py ported per page.

**Owner decision on record:** PROJECT.md, Expensive decisions, 2026-10-10,
option C (docs/joz-273-gestalt-decision.md).

---

## Intent anchor

The app is built to prove, with five friends in Zurich, whether a per-user
board over shared jobs and companies is useful. The front end exists to make
that test easy to run. A design system was chosen early and left proposed;
the owner has now decided it: Gestalt with React. This plan turns that
decision into the product without inventing new features. Anything here that
does not preserve an existing approved behavior or serve the first test is a
side quest and gets surfaced for accept or cut.

## Current context

- 11 Jinja templates in `careeros/templates/`; styling in
  `careeros/web/theme.py` + `ui.py` (CSS variables, no build step).
- JSON API already exists for the core records:
  `/api/jobs/intake` (POST), `/api/jobs/<id>` (GET/PUT/DELETE),
  `/api/companies/<id>` (GET/PUT/DELETE), `/api/search` (GET/POST),
  `/api/experiences` (GET/POST), `/api/experiences/<id>` (GET/PUT/POST/DELETE).
- Missing as JSON: the board view, companies list, company taxonomy pages,
  job taxonomy pages, and whatever `search.py`/`jobs.py`/`companies.py`
  currently render only server-side.
- Node v22.23.1 and npm 10.9.8 already installed on the host.
- 896 pytest tests green. JS-harness tests in `tests/test_jobs.py` assert
  template DOM/JS; those move to Playwright against the SPA.
- Behavior contract (must survive the port): batch A audit removals,
  experience-company link (PR #7), batch D Search edit mode + summary-first
  job page (0f0d88c).

## Milestones

Each milestone is checkable and states what is out of scope. Owner gate at the
end of each: click-test the live LAN build, verdict recorded in PROJECT.md.

| # | Milestone | Outcome (true when done) | Verified by | Out of scope |
|---|---|---|---|---|
| M0 | Toolchain + one page proof | `frontend/` builds; Gestalt theme (blue/purple) applied; Jobs board rendered from `/api/jobs` with identical behavior; Jinja `jobs.html` deleted | Playwright port of the Jobs checks from verify.py + owner click-test on LAN | Every other page; no new features |
| M1 | JSON API parity | Every page the SPA needs has a JSON endpoint with a pytest contract test; no template-only data paths remain | New `tests/test_api_*.py` green; endpoint list recorded in docs | Any visual work |
| M2 | Search page | React Search with batch D edit mode (local edits, Cancel restores, failed save keeps edit mode); `search.html` deleted | Playwright edit-mode checks + owner click-test | Job detail internals beyond links |
| M3 | Job detail | Summary-first card order, collapsible source description, AI-labeled summary, Retry; `job_detail.html` deleted | Playwright + owner click-test | Taxonomy pages |
| M4 | Companies + company detail | Both pages on Gestalt Card; templates deleted | Playwright + owner click-test | Experiences |
| M5 | Experiences + form + taxonomy pages | All remaining templates ported and deleted; `careeros/templates/` empty; theme.py/ui.py CSS deleted | Full Playwright suite + owner click-test | Design polish beyond registry |
| M6 | Component registry + retire JOZ-274/275 | DESIGN_SYSTEM.md lists every Gestalt component in use with allowed variants; JOZ-274/275 closed as absorbed | grep verification: zero ad-hoc card/button/toast markup | New components |

Ordering rule: M1 may run in parallel with M0 (AGENTS.md allows backend work
while design advances), but no user-visible surface ships without an approved
sketch first.

## Design gate before M0 build

Per AGENTS.md, a clickable HTML mockup is the wireframe gate. Before any React
code: produce `docs/m0-jobs-board-sketch.md` with a text/HTML sketch of the
Jobs board in Gestalt (Card, Button, Chip, Toast, blue/purple tokens), listing
what is deferred. Owner approves with a dated line. Then build.

---

## M0 detailed tasks

### Task 1: Scaffold the frontend package

**Objective:** A buildable Vite + React + Gestalt app under `frontend/`,
served by Flask in dev and mounted as static in prod.

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.js`,
  `frontend/index.html`, `frontend/src/main.jsx`, `frontend/src/App.jsx`
- Create: `.gitignore` entry `frontend/node_modules/`, `frontend/dist/`

**Steps:**
1. `cd /root/work/careeros-dashboard && npm create vite@latest frontend -- --template react`
2. `cd frontend && npm i gestalt gestalt-tokens && npm i -D @playwright/test`
3. Run `npm run build`; expected: `dist/` created, exit 0.
4. Commit: `chore(frontend): scaffold Vite React app with Gestalt`

**Verification:** `npm run build` exits 0; `frontend/dist/index.html` exists.

### Task 2: Blue/purple Gestalt theme

**Objective:** Replace Gestalt's default red accent with the owner's blue and
purple (PROJECT.md design system line).

**Files:**
- Create: `frontend/src/theme.js` (token overrides)
- Modify: `frontend/src/main.jsx` (Provider + theme)

**Steps:**
1. Wrap App in `<Provider>` with a custom theme object overriding the
   primary/secondary token values to the blue/purple pair already used in
   `theme.py` (`--accent-indigo` and the page accent).
2. Add a Playwright test asserting the computed accent color on a rendered
   `<Button color="red">`-equivalent primary button matches the token.
3. Run `npx playwright test`; expected: 1 passed.
4. Commit: `feat(frontend): blue/purple Gestalt theme`

### Task 3: JSON endpoint for the board

**Objective:** `GET /api/jobs?view=board` returns the exact data
`jobs.html`/`job_cards.html` render today (columns, chips, status flags,
needs-attention, function facet).

**Files:**
- Modify: `careeros/web/pages/jobs.py`
- Test: `tests/test_api_jobs_board.py`

**Steps (TDD):**
1. Write failing test asserting board JSON shape equals the dict currently
   passed to the template (capture it from the existing route).
2. Run `pytest tests/test_api_jobs_board.py -v`; expected: FAIL.
3. Extract the template context builder into a pure function, add the JSON
   route reusing it (reuse ladder step 3: extend, don't duplicate).
4. Run test; expected: PASS. Full `pytest -q`; expected: 897+ passed.
5. Commit: `feat(api): board JSON endpoint`

### Task 4: React Jobs board page

**Objective:** The board renders from `/api/jobs?view=board` using Gestalt
Card/Button/Chip, behaviorally identical to the Jinja page (batch A: columns
are the filter, one control per card, Needs attention toggle, Function kept,
Board/List switch kept).

**Files:**
- Create: `frontend/src/pages/JobsBoard.jsx`
- Create: `frontend/tests/jobs-board.spec.js`

**Steps:**
1. Port each interaction from verify.py's Jobs steps into a Playwright spec
   (board columns, list view, needs-attention toggle, function filter,
   retry button, toast on success/error).
2. Run spec; expected: FAIL (page not built).
3. Implement the page.
4. Run spec; expected: PASS.
5. Serve `frontend/dist` from Flask at `/` behind a feature flag
   (`?ui=react` or env var) so the Jinja page stays reachable.
6. Commit: `feat(frontend): Jobs board on Gestalt behind ui flag`

### Task 5: Owner click-test and cutover

**Objective:** The owner approves the React board on the live LAN server; the
Jinja board is deleted in the same change.

**Steps:**
1. Commit locally, restart the LAN server (`bash /root/careeros-server.sh`)
   with the flag defaulting to React for `/jobs`.
2. Give the owner the written check list (from verify.py Jobs steps) and the
   URL http://192.168.1.203:8788/jobs.
3. On approval: delete `careeros/templates/jobs.html`, `job_cards.html`,
   their JS-harness tests, and the flag branch for this page. Update
   PROJECT.md milestone row + verify.py note.
4. Commit: `refactor: retire Jinja jobs board after React cutover`

**Verification:** `pytest -q` green; `npx playwright test` green; grep shows
no remaining reference to the deleted templates; owner verdict recorded.

---

## Files likely to change (whole plan)

- New: `frontend/**` (package, vite config, src/pages/*, tests/*)
- Modified: `careeros/server.py`, `careeros/web/pages/*.py` (JSON extraction)
- Deleted progressively: all 11 `careeros/templates/*.html`, then
  `careeros/web/theme.py` + `ui.py` CSS strings, JS-harness tests in
  `tests/test_jobs.py`
- New: `DESIGN_SYSTEM.md` (M6 registry), `docs/m0-jobs-board-sketch.md`
- Modified: `PROJECT.md` (milestone rows, design system section),
  `scripts/verify.py` (per-page port)

## Tests / validation

- API: pytest contract tests per endpoint (`tests/test_api_*.py`).
- UI: Playwright specs mirroring every verify.py step for the page being
  ported; old JS-harness tests deleted with their template.
- Live: owner click-test on the LAN server is the acceptance gate
  (AGENTS.md: done means live). Use fixture vaults for automated probes;
  never point automation at /root/career-os.
- Grep verification at M6: zero ad-hoc card/button/toast markup.

## Risks and tradeoffs

- **Scale:** weeks, not a batch. Mitigation: per-page milestones, each
  independently shippable and revertible; Jinja stays live until cutover.
- **Two UIs in flight:** the flag period doubles surface area temporarily.
  Mitigation: cutover deletes the old page in the same change; never more
  than one page flagged at a time.
- **Gestalt fit:** Gestalt assumes its own layout system; our dense board may
  need Box/Flex compositions. Mitigation: M0 sketch settles this before code.
- **Test churn:** JS-harness tests assert template DOM; they must be ported,
  not deleted blindly. Mitigation: port first, delete with the template.
- **Build in prod:** `frontend/dist` must be committed or built on deploy.
  Decision needed at M0: commit dist (simplest, no build on the host) vs
  build step in careeros-server.sh. Flag for owner.

## Open questions for the owner

1. Commit `frontend/dist` or build on the server? (Recommend: build on the
   server via careeros-server.sh, keeps the repo clean.)
2. Feature-flag mechanism: query param `?ui=react` or env var? (Recommend:
   env var, so friends never see a half-migrated UI.)
3. Should M1 (API parity) be delegated to Codex in parallel with M0?
   (Recommend: yes, backend-only, cross-reviewed per our loop.)
