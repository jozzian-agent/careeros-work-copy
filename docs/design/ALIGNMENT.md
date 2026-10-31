---
type: Note
title: "CAREER-120 — design package vs repo alignment"
description: "Where docs/design/tokens.json and the repo's implementation disagree."
timestamp: 2026-10-31
---

# CAREER-120 — design package vs repo alignment

Package truth: `docs/design/tokens.json`. Repo implementation:
`frontend/src/design/tokens.css` (line heights in
`frontend/src/design/theme.css`). Every value below was read from those files.

The package token name → repo variable pairing is not inferred here: it is the
table `docs/design/HANDOVER.md` PR 1 gives (lines 30–53).

## Table A — colour

Light mode: 21 of the package's 22 colour tokens match the repo. Counting the
additional `ink` → `--color-text-link` mapping gives 22 matching rows.
`text-disabled` has no mapping:

| Token | Package light | Repo |
|---|---|---|
| `text-disabled` | `#969292` | no variable — absent, and absent from HANDOVER's PR 1 table too |

Dark mode is where the set diverges. Package dark vs repo dark, mismatches only:

| Token | Package dark | Repo |
|---|---|---|
| `brand` | `#6bec8c` | `--color-brand-primary` `#75bfff` |
| `brand-hover` | `#a4f9ac` | `--color-brand-primary-strong` `#abdbff` |
| `ink` (link row) | `#ffffff` | `--color-text-link` `#75bfff` |
| `fill-secondary-hover` | `#3a3a3a` | `--color-background-secondary-weak` `#4a4a4a` |
| `brand-wash` | `#003020` | `--color-brand-wash-blue` `#002966` — PR 1's rename not applied in the dark block |
| `text-neutral` | `#e0e0e0` | absent from the dark block |
| `danger-hover` | `#ffa3a3` | absent from the dark block |
| `text-disabled` | `#7a7a7a` | no variable |

15 of 22 dark tokens match. Two variables PR 1 asks to remove are still in the
dark block: `--color-brand-accent` `#48d5c6` and `--color-brand-wash-teal`
`#003440`. This is expected, not drift: `docs/decisions/design-system.md`
("Unchanged, deliberately") records that the dark block was left alone because
launch is light-only, and `frontend/tests/theme.spec.js` asserts the old values.

## Table B — type, spacing, radius

Radius: all 5 package tokens match (`radius-100/200/400/600/pill` →
`--rounding-100/200/400/600/pill`). Spacing: 6 of 9 match. Font family: the
package's `type.families.sans` and the repo's `--font-sans` are the same stack
(quote style differs only). Mismatches:

| Token / style | Package | Repo |
|---|---|---|
| `space-5` | `20px` | no `--space-500` |
| `space-14` | `56px` | no variable |
| `space-18` | `72px` | no variable |
| `body-lg` line height | `20px / 28px` | 20px resolves to `24px` |
| `ui-button` line height | `16px / 19px` | 16px resolves to `22px` |
| `ui-badge` line height | `14px / 17px` | 14px resolves to `20px` |

8 of the package's 11 type styles match. The three that do not are structural
rather than value drift: the repo has no type-scale custom properties at all and
binds line height to font **size** in `theme.css` (12→16, 14→20, 16→22, 20→24,
28→31, 36→40), so a package style whose line height differs from its size's pair
is not supplied by the existing size-based rules and would require an override.
The package README lists seven line heights (16, 20, 22, 24, 28, 31, 40px): it
includes `body-lg`'s 28px but omits `ui-button`'s 19px and `ui-badge`'s 17px, so
`tokens.json` and the package README disagree here too.

## Section C — components

Repo: 33 files in `frontend/src/components/*.jsx`. Package: 30 entries in
`manifest.json`.

**Name-identical (15):** AiLabel, DetailHeader, EndedLane, FilterBar,
FilterChip, FitChip, FloatingPopover, JobCard, KanbanBoard, LevelTag, Message,
PageLayout, QuietChip, SectionCard, StatusSelect

**Package-only (15):** AccountMenu, Badge, Button, Card, CollectionPage,
CompanyTile, Dialog, Divider, GlobalSearch, Link, NeedsInputChip,
OnboardingImport, SearchBand, SegmentedControl, TextField

**Repo-only (18):** AddJobPopup, AiStatusChip, ClosedPostings,
DeleteConfirmModal, EditClassificationPopup, EditCompanyPopup, EditJobPopup,
EditPositionPopup, EndJobFlow, ExtractionPopup, FilterPopoverPanel,
MoreFiltersPanel, NeedsInputCard, NotePopup, NotesSection,
PasteDescriptionPopup, Requirements, SortableHeaderCell

Two notes on reading those lists. Four of the package-only names are Gestalt
primitives the app already consumes from `gestalt` rather than wrapping in a
local file — `Badge` (imported in 8 files), `Button` (32), `Link` (11) and
`TextField` (9) — so for those four, "package-only" means "no local file of
local file", not "unimplemented". Card, Divider and SegmentedControl have no
direct Gestalt imports in `frontend/src`; this does not establish that their
patterns are absent — the package defines Card as a Gestalt `Box` surface,
which the repo already uses (the only `Divider` match is `DividerList`, a
local helper in `SectionCard.jsx`), and `SegmentedControl` is what HANDOVER's
PR 4 introduces. UNVERIFIED: whether each repo-only name is a component the
package drops or one it covers under a different name — deciding that needs a
read of all 30 READMEs against each file's behaviour, which this pass did not
do.

## Section D — the decision record

`docs/decisions/design-system.md` is titled "JOZ-273 — Gestalt integration
mode: decision note" and its body still carries the full options comparison,
in which option A ("Gestalt tokens + patterns, no React") is marked
RECOMMENDED and option C ("full React front end on Gestalt") is marked "Fit:
none at current scale. Park unless the product direction changes." Its status
lines, however, record the opposite outcome: front matter
`status: approved 2026-10-10`, and the body's first paragraph reads "Status:
DECIDED. Owner decision 2026-10-10: option C, full React front end on
Gestalt." — the approved option C decision appears before the retained
comparison and recommendation for option A. Reality matches that decision,
not the recommendation: the repo is a Gestalt-based React app whose theme the
sections below that paragraph document in detail, and which now imports this
package. So the doc is not wrong about what was decided — it is a decision
note that kept its pre-decision argument. Later sections document the
implementation but retain at least one stale value: the Page title row says
28px/36px, while `theme.css` defines 28px/31px. The path forward is
`HANDOVER.md`'s PR plan 1–11, whose PR 3 explicitly includes updating this
document; it is not rewritten here.
