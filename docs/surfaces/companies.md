---
type: Surface
title: "Companies list"
description: "Describe the Companies list surface."
timestamp: 2026-10-15
---

# Companies list

Surface: `/companies` (React rewrite of `companies.html`).
Status: implemented 2026-10-13 (JOZ-283), reworked 2026-10-15 against the
owner's locked decisions below. Owner click-test pending.

## Purpose

Scan every company in the shared directory in a straight grid, see at a
glance which ones have open jobs, narrow the grid by sector, size, open
jobs or a pending review, and reach any one of them.

## Appears in

Nav → Companies. A card → Company detail.

## Minimal contents

A page header (Companies) and, when the directory is not empty, the shared
[FilterBar](jobs.md) above a card grid.

**Card.** One card per company, every card the same width and the same
height (content that does not fit is clipped, never allowed to stretch one
card past its neighbours):

- the company name, at most 30 characters followed by one ellipsis
  character, over at most two lines, with the full stored name as the
  element's tooltip. Display only: the stored name is never changed.
- a muted sector line, the company's ISIC section labels joined by commas,
  clipped at two lines ("Sector unknown" with no sectors)
- a muted size line, the company's size class, title-cased ("Size unknown"
  when it has none)
- bottom-pinned, one chip: a blue info Badge reading "N open job" or
  "N open jobs", or a neutral Badge reading "No open jobs"

**Filters.** The same `FilterBar` component the Jobs board uses, with this
page's own groups, count noun and toggle label:

- **Sector**, multi-select: the ISIC section labels companies are actually
  classified under, most-used first. A company matches when ANY of its
  sectors is checked.
- **Size**, multi-select: the size classes companies are actually in, in
  the scale's own order (micro → large), so the panel never offers a class
  nothing is in.
- **Open jobs**: "With open jobs" and "Without open jobs". Neither checked
  is "Any", which is also what Clear and Clear all leave behind.
- **Needs your input**, a toggle chip with a count: companies that carry
  any review flag. Deliberately broader than the Company detail page's
  one-field `needs_input` ask.
- Active-filter Tag chips with Clear all, and the result count
  ("N companies", "N of M companies" once anything is active), per
  FilterBar's existing behavior.

Filtering stays client-side over the one `?view=page` payload. Every filter
choice, including the toggle, is remembered per browser in `localStorage`
under `careerCompaniesFilters`; there is no URL state (owner decision).

### Settled decisions (owner, 2026-10-15)

1. **Name length.** 30 characters plus one ellipsis, full name in the
   tooltip, frontend-only.
2. **One size scale.** The classes (`vault.SIZE_CLASSES`) win over the
   numeric `size_range`: a company carrying both reads as its class
   everywhere on this page. The stored ranges are retired by the migration
   below, not by read-time rewriting.
3. **Open jobs.** A job is open unless its status is rejected, closed or
   withdrawn — `vault.ENDED_STATUSES` / `vault.is_open_job`, the one place
   that says so, which the count and the Open jobs filter both read.
4. **Chip.** "N open job(s)" when there are any, "No open jobs" when there
   are none, pinned to the card's bottom.
5. **Grid.** `repeat(auto-fill, minmax(260px, 1fr))`, 16px gap, fixed card
   height.

## Data

`GET /api/companies?view=page` ([contract](json-api.md)), unchanged in
shape except that each entry now carries `needs_attention` (any review
flag), derived server-side the same way the board derives it for a job.
`counts` is the open-jobs count per company, over the one rule above.

## Migration: one size scale

`scripts/migrate_company_size_scale.py` normalizes what is stored so the
class scale is the only one left: a company with both keeps its class and
loses the range; a company with only a range gains the class its headcount
implies (up to 50 small, up to 250 medium, above that large) and loses the
range; any other stored range is reported and left exactly as it is. Only
the vault's own bucket grammar (`51-250`, `1000+`) reads as a headcount —
`size_range` is free text on the way in, so a separator, an abbreviation
or prose (`10,000+`, `10k+`, `Fortune 500`) is unreadable rather than a
number to guess a class from. Provenance follows the value: a
`field_provenance['size_range']` entry is dropped when the range is
cleared, and moves onto `size_class` when the class is derived from that
range.

It is a **dry run by default** and reports by record id, never by company
name. `--apply` is owner-gated: only the owner runs it, after reading the
dry-run report. An apply writes through `vault.save_company`, which
rebuilds the record from the full schema, so an older record's YAML diff
can be wider than the reported size change: it also gains any schema key
it is missing (`note_list: []`, `field_provenance: {}`). A write refused
by validation is reported on stderr and the run exits non-zero.

```
.venv/bin/python scripts/migrate_company_size_scale.py --vault /path/to/vault
.venv/bin/python scripts/migrate_company_size_scale.py --vault /path/to/vault --apply
```

Known follow-up: the org-intake capability derives `size_range` and
`size_class` together (`org_intake.classify.derive_size`), so a newly
enriched company gets a range again and the migration is re-runnable by
design, per the owner's "manual single run, not lazy migration on read"
convention.

## States

Loading and load-error states (plain text, a Retry on load failure). An
empty directory shows the empty message with no filter controls — the
deliberate improvement kept from the 2026-10-13 rework, since filters with
nothing to filter serve no purpose. A filter combination that matches
nothing now says so ("No companies match these filters.", or "Nothing
needs your input." when the toggle alone is on), the same way the board
does; before the rework it rendered a silently empty grid.

## Routing

No Jinja coexistence (same no-coexist decision as the JOZ-280 detail
pages; see [Detail pages](detail-pages.md)): `/companies` exists only when
`CAREEROS_REACT_UI=1`, with the Jinja `companies.html` template and its
view removed rather than kept as a flag-off fallback
(`tests/test_react_ui_flag.py`).

## Verification

- `.venv/bin/python -m pytest tests -q` (1161 passed, was 1138, 2026-10-15:
  9 tests for the open-jobs rule and the review-flag mark in
  `tests/test_companies_directory.py`, 14 for the migration in
  `tests/test_migrate_company_size_scale.py` — the bucket grammar, the
  provenance move, the exit code and the footer came in with the review
  round).
- `cd frontend && npx playwright test` (251 passed, was 243, 2026-10-15:
  `tests/companies-list.spec.js` is 14 tests, was 6, and covers 1280px and
  390px).
- `cd frontend && npm run build`.
- Owner click-test on the live instance: pending.

## Open questions

- Does the Company detail page's size value follow the same
  classes-win rule? It still prefers the raw range it was given
  (`companies.field_value`), which only matters until `--apply` runs.
- Should `careeros` stop storing `size_range` at its own write sites, so
  the unified scale survives the next enrichment without a re-run?
