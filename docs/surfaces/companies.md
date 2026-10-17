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
  the scale's own order (micro → xl), so the panel never offers a class
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
3. **Open jobs.** A job is open unless its status is won, rejected or
   stopped (`vault.ENDED_STATUSES` / `vault.is_open_job`, the one place
   that says so, which the count and the Open jobs filter both read).
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

Settled 2026-10-15 (M0-7), replacing the follow-up this section used to
record: no product write persists the range any more.
`vault._drop_retired_size_range` takes it
off every payload at `save_company`, the one gate every company write
passes through, so a new signal cannot reintroduce the second scale
through a path nobody remembered. An explicit null still gets through,
because clearing a range an older record carries is what this migration
and the re-kind path in `careeros/enrich.py` do. A newly enriched company
therefore stays on the class scale, and the migration no longer has to be
re-runnable to keep it there.

Finished 2026-10-16 (CAREER-33) at the other end of the same path: the
capability's own derivation stopped offering the range, so there is
nothing left for the write gate to drop on an enrichment result.
`org_intake.classify.derive_size` answers with `size_class` alone, and
`fill_size_updates`/`size_cascade` propose only the class; both still
READ a stored range, since a record written before the decision carries
one and evidence that contradicts it is a conflict to flag. The gate
stays as the guard for a legacy payload that names the range itself.
This moved the pinned submodule, see the capability contract's rule 8.

Two consequences at the product's own size write sites, both so the
remaining scale stays coherent rather than coming back under another
name. **The posting's own bucket string is gone**: `intake._extract` no
longer derives one, and `fill_company_metadata` no longer fills the
legacy `size` field from it, so a posting's headcount fills the class and
nothing else. That field is now read-only as far as the product is
concerned — an owner PUT can still set one, an older record still shows
what it carries (`careeros/web/pages/companies.py`), and
`scripts/migrate_company_size_scale.py` reports it rather than touching
it. And the enrichment cascade's "this field is filled" accounting reads
`size_class` alone, since a company with a class and no range has a known
size.

The headcount itself is kept rather than dropped (owner decision
2026-10-16). It stays on the job record as the raw `employee_count` it
was extracted into, and `careeros.enrich.enrich_company` aggregates it
onto the company as `enrichment.employee_count`, beside an
`employee_count_evidence` record naming the posting that stated it and
its date. That is the zero-network tier of the size cascade
(`org_intake.enrich.promote_aggregated_size`, rule 9/R4), so a company
whose only size signal is one of its own postings can have a class
derived from it on any later size run instead of the number being read
once at intake and then forgotten. It is evidence toward `size_class`
and only that: the existing rules apply unchanged, so it never overwrites
a stored class, a count that contradicts one raises
`FLAG_SIZE_INCONSISTENT` instead, and neither retired scale is written.
Where several postings state different counts, the most recently posted
one wins, and failing any dated posting the first that states a count —
the rule [enrichment evidence](../decisions/enrichment-evidence.md)
already settled for dated Wikidata statements. Section 1's field-group
matrix still applies: a non-employer gets no size, so the re-kind path
deletes this evidence the same way it deletes the nested
`enrichment.sectors` rollup.

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
- Should the legacy free-text `size` field go the same way as
  `size_range`? A posting that states a size still fills it on a company
  with no class, and the detail page prefers it over the class, so the
  two scales can still disagree on a record written that way. M0-7 was
  scoped to `size_range`.
