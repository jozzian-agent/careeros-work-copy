---
type: Decision
title: "JOZ-273 — Gestalt integration mode: decision note"
description: "Record the approved full React integration of Gestalt."
timestamp: 2026-10-11
status: approved 2026-10-10
---

# JOZ-273 — Gestalt integration mode: decision note

Status: DECIDED. Owner decision 2026-10-10: option C, full React front end
on Gestalt. Recorded in PROJECT.md (Expensive decisions).

Consequences of C:

- Flask becomes a JSON API; the 11 Jinja templates are rewritten as React
  pages using real Gestalt components (blue/purple theme per PROJECT.md).
- A JS build toolchain (npm, bundler) enters the repo for the first time.
- JOZ-274 (cards) and JOZ-275 (buttons/messages) fold into the rewrite as
  Gestalt components (Card, Button, Toast) instead of CSS-only passes.
- verify.py and the Playwright/JS-harness tests need porting page by page.
- Batches A–D remain the source of truth for behavior; the rewrite must
  preserve every owner-approved interaction.

## The situation

The app is server-rendered Jinja with plain CSS and vanilla JS. There is no
build step, no npm, no React anywhere. Styling already lives in one place
(`careeros/web/theme.py` + `ui.py`) as a small CSS-variable token layer
(`--bg-page`, `--accent-indigo`, `--status-success`, ...) plus component
classes (`.card`, `.chip`, `.toast`, `dialog`).

Gestalt (gestalt.pinterest.systems) ships as React components + a design
token package. Its tokens are plain CSS variables and can be used without
React; its components cannot.

## What exists today (registry seed)

| Component | Class/markup in use | Count across templates |
|---|---|---|
| Card | `.card` (+ `.wide`, `.ai-summary`) | 32 |
| Button | `<button>` + `.primary` / `.danger` | ~20 |
| Chip | `.chip` (+ `.chip-local`, `.company-review-chip`) | 29 |
| Toast/message | `.toast` (+ `.toast.error`) | 1 helper |
| Input/label | `label input`, `label textarea` | many |
| Dialog | native `<dialog>` styled once | 2 |
| Layout | `.grid`, `.row`, `.stack`, `.spaced` | 75+ |

Ad-hoc variants that the migrations (JOZ-274/275) must absorb:
`.position` (job-card variant of `.card`), `.empty-state`, `.salary-badge`,
`.retry-ingest`, `.ingest-failed`, `.external`.

## Options

### A) Gestalt tokens + patterns, no React — RECOMMENDED

Adopt Gestalt's design token values (colors, spacing, radii, typography
scale) mapped onto the existing CSS variables, and copy Gestalt's component
*patterns* (card, button, chip, toast states) into the existing CSS
classes. One registry doc lists every component class; new UI picks from
it first.

- Cost: smallest. No new dependency, no build step, no runtime JS added.
  One token-mapping pass in theme.py + registry doc.
- Risk: "visual parity" is pattern-level, not pixel-level; Gestalt updates
  must be ported by hand (we rarely want them anyway).
- Fit: matches AGENTS.md reuse ladder — extends the existing token layer
  (step 3) instead of adding a stack (step 7).
- JOZ-274/275 become pure CSS/markup consolidation passes.

### B) React islands with real Gestalt components

Keep Jinja pages but mount React on interactive spots (edit mode, dialogs,
toasts) using actual Gestalt components.

- Cost: high. npm + bundler into a repo with zero JS build today; two
  rendering models on one page; every migration touches both stacks.
- Risk: mixed-stack complexity contradicts the one-principle (more
  elements, not fewer); Gestalt's React components assume their own layout
  system.
- Fit: only if we expect the interactive surface to grow a lot.

### C) Full React front end on Gestalt

Rewrite all 11 templates as a React SPA against a JSON API.

- Cost: largest by far; every page, every test, every verify.py step
  rewritten. Weeks, not a batch.
- Risk: throws away working, tested, owner-approved surfaces (batches A–D).
- Fit: none at current scale. Park unless the product direction changes.

## Recommendation

Option A. It is the only option that removes elements rather than adding
them, it builds on the token layer that already exists, and it unblocks
JOZ-274/275 immediately as CSS-only passes.

## If A is chosen, the registry section will name these first

card, button, message/toast, input — plus chip, dialog, layout
primitives, each with its allowed variants and the rule: new UI picks from
the registry first; additions need a recorded reason.

## Badge usage

Owner decision 2026-10-13: colored badges are reserved for two cases.
The first is an owner-action signal, such as the "Needs your input"
recommendation badge on a job's company link. The second is a
provenance marker on a detail page, such as the "AI-generated" info
badge on the job detail page.

Board cards carry only neutral information tags, such as industry,
size, function and salary, and quiet chips for machine-state notices,
such as extraction failed, details filling in, and company details
pending. A quiet chip must never alarm: it uses subtle text, a
transparent or secondary-base background, and a container-level border
at most, never a colored badge type.

## Detail-page updates

Owner decision 2026-10-14, approved with the detail-pages canvas: the
entries below are adopted for the Job and Company detail pages. They
change existing components rather than adding a second way to do the
same thing.

| Entry | What it is | Rule |
|---|---|---|
| Dashed AI label (`AiLabel.jsx`) | `AI-generated` for text a model composed, `AI-extracted` for text it lifted out of the posting | A dashed outline and subtle text, no fill and no colour of its own. A provenance marker is not an owner action, so it must not read like the violet "Needs your input" signal. Replaces `SectionCard`'s plain `label` badge. |
| Level tag (`LevelTag.jsx`) | One requirement or skill, filled for a must-have and outlined for a nice-to-have | Colour never carries the must/nice difference: both levels use the same neutral container colours and brand blue is never used for either, because blue is this system's primary-action colour. The fill carries it visually, and a visually hidden "Must-have:" / "Nice to have:" prefix carries it for everyone else. |
| `SectionCard` variant `needs-input` | The one ask a detail page makes of its owner | Violet wash with a violet border, exactly one action set, rendered only when there is something to ask. A page never shows two at once; which ask wins is decided in the backend context, not by section order. |
| `SectionCard` padding | 24px | Was 16px. |
| Detail-page content column | 960px (`DETAIL_MAX_WIDTH`) | Was 880px. One constant, shared by the Job, Company and Experience pages. |
| `DetailHeader` Delete | Gray secondary, same weight as Edit | `color="red"` maps to the brand fill in this theme (see `frontend/src/design/theme.css`), so the page's most destructive action rendered as its primary one. |
| `FitChip` read-only variant | "Not calculated yet" in neutral colours | Fit scoring is not built. The page says so rather than showing a control that stands for a feature that does not exist, and it stays out of violet because nothing is being asked of the owner. The violet "Needs your input" variant is still what the board shows for a missing owner rating. |
| Dashed empty state | `SectionCard`'s `EmptyState`, now with one optional action inside the box | Reused for the Notes section ("Add a note"), not re-invented per section. |

### Recorded token override

`--color-icon-brand-primary` is rebound to `--color-brand-primary` in
`frontend/src/design/theme.css`. Gestalt's brand icon token is still
Pinterest red, so the detail pages' back-link arrow (an `Icon`
`color="brandPrimary"`) rendered red beside its blue link text. The brand
here is blue.
