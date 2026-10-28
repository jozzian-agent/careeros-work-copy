---
type: Surface
title: "Companies list"
description: "Describe the Companies list surface."
timestamp: 2026-10-15
---

# Companies list

Surface: `/companies` (React rewrite of `companies.html`).
Status: implemented 2026-10-13 (JOZ-283), reworked 2026-10-15 against the
owner's locked decisions below, and again 2026-10-19 for B3/B4/B5
(universe open-jobs counts, the Tiles and List pair, and no "Needs your
input" anywhere on a company surface). Owner click-test pending.

## Purpose

Scan every company in the shared directory -- as equal tiles or as a
list -- see at a glance which ones have open jobs, narrow either view by
sector, size or open jobs, and reach any one of them.

## Appears in

Nav → Companies. A card → Company detail.

## Minimal contents

The page title "Companies" as the page's H1, on the page ground, and, when
the directory is not empty, the shared [FilterBar](jobs.md) under it, then
a card grid. There is no white title band and no main action: the title,
the filter bar and the grid share one left edge (brief 2026-10-18, section
3; the shared frame is `frontend/src/components/PageLayout.jsx`).

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

**List row.** The same companies as one row each, with the five
owner-approved columns (B4, 2026-10-19):

| Column | What it holds |
|---|---|
| Name | the full stored name, as a link to the profile (not the tile's 30-character cut: a row has the width for it) |
| Sector | the same ISIC section labels the tile shows, "Sector unknown" with none |
| Size | the size class, title-cased, "Size unknown" with none |
| Location | the company's own stored locations, comma-joined, "Location unknown" with none |
| Open jobs | the same chip as the tile, same words |

**Name** and **Open jobs** sort, both ways; the other three do not, by
owner decision. A name sorts through `localeCompare`, the count sorts
numerically. `aria-sort` lands on the `<th>` through the shared
`SortableHeaderCell`, which the Jobs list view uses too -- it moved out
of `JobsBoard.jsx` into its own component in this round rather than being
copied. There is **no column saying where a company came from**: the
owner asked for none, and the list is the same universe whatever the
source.

**Tiles and List** are one `FilterChip` pair in a `role="group"` labelled
"View", 44px, each carrying its own `aria-pressed`, in the one selected
style every toggle in the app uses (A1: wash-blue ground, blue border,
never a fill). They sit where Board and List sit on Jobs -- the first row
under the title -- and Companies still has no main action, so there is no
primary button beside them. The choice is remembered per browser in
`localStorage` under `careerCompaniesView`.

**Filters.** The same `FilterBar` component the Jobs board uses, with this
page's own groups and count noun. They apply to **both views**: one
predicate over the one payload, so the two views can never disagree about
which companies match.

- **Sector**, multi-select: the ISIC section labels companies are actually
  classified under, most-used first. A company matches when ANY of its
  sectors is checked.
- **Size**, multi-select: the size classes companies are actually in, in
  the scale's own order (micro → xl), so the panel never offers a class
  nothing is in.
- **Open jobs**: "With open jobs" and "Without open jobs". Neither checked
  is "Any", which is also what Clear and Clear all leave behind.
- Active-filter Tag chips with Clear all, and the result count
  ("N companies", "N of M companies" once anything is active), per
  FilterBar's existing behavior.

A selected filter on this page carries the one selected-toggle style the
whole app uses since 2026-10-18: the wash-blue ground with a blue border
and the default text colour, never a blue fill. That covers Sector, Size,
Open jobs and the Tiles/List pair. Each filter's popover draws
the card ground with the floating shadow and sits above the grid, for the
same reason and by the same fix as on the Jobs board (see
[My Jobs](jobs.md), "Filter popovers").

Filtering stays client-side over the one `?view=page` payload. Every filter
choice, including the toggle, is remembered per browser in `localStorage`
under `careerCompaniesFilters`; there is no URL state (owner decision).

### Settled decisions (owner, 2026-10-15)

1. **Name length.** 30 characters plus one ellipsis, full name in the
   tooltip, frontend-only.
2. **One size scale.** The classes (`vault.SIZE_CLASSES`) win over the
   numeric `size_range`: a company carrying both reads as its class
   everywhere on this page. The stored ranges are retired by the migration
   below, not by read-time rewriting. A class is shown by the taxonomy's
   own label, which the payload sends beside the code
   (`vault.SIZE_CLASS_OPTIONS`, CAREER-71): the tile, the list row, the
   Size facet and the Size select in Edit classification all read it, so
   `xl` reads "Very large" on each of them instead of the "Xl" that
   title-casing the code produced.
3. **Open jobs.** A job is open unless its status is won, rejected or
   stopped (`vault.ENDED_STATUSES` / `vault.is_open_job`, the one place
   that says so, which the count and the Open jobs filter both read).
4. **Chip.** "N open job(s)" when there are any, "No open jobs" when there
   are none, pinned to the card's bottom.
5. **Grid.** `repeat(auto-fill, minmax(260px, 1fr))`, 16px gap, fixed card
   height.

## Data

`GET /api/companies?view=page` ([contract](json-api.md)). The entry no
longer carries `needs_attention`: the mark and the filter that read it
are gone with B5 below. The company records themselves are shared
universe and are sent to everybody; editing one is the admin's alone, so
the profile page carries `can_edit_shared` and leaves out every control a
tester's own write would refuse.

### B3: why API-added companies looked missing, confirmed

The owner reported that companies added through the API do not appear in
this list. Confirmed, and the report is half right in a way worth
recording, because the fix is not where it was expected:

1. **Nothing was filtering a company out of the read path.**
   `vault.visible_companies` has always answered with every company
   stored in the vault, whatever its source -- no origin, no `source`
   field and no `kind` enters that decision. The only company it leaves
   out is one the admin retired (M2 soft retire, below), and the live
   vault holds none. Of its 54 companies, 12 are linked by no job at all
   and were all on the page already.
2. **What was missing was their open jobs.** The count was the reading
   user's own board (M2, D3), so a company whose postings nobody on this
   board holds read "No open jobs", which is what makes an API-added
   company look like an empty stub -- and makes it vanish outright under
   the "With open jobs" filter.
3. **A company known only to the feed pool is in no list, because it is
   in no vault.** `careeros/feeds/` stages its output under `data/ats/`
   and `data/personio/` and writes no vault record; the merge is a
   separate owner-gated step that does not exist yet (PROJECT.md,
   2026-10-17). That is an upstream gap, not a read-path bug, and this
   round does not close it.

So the fix is the count. `counts` is now the **universe's** open jobs per
company (owner rule 3, 2026-10-19): the ownerless records plus the
reader's own, over the same `vault.is_open_job` as before
(`companies.page_context` reads `vault.list_universe_jobs`). Another
user's private posting is still not counted -- a count is a leak like any
other (D3) -- so two users can still read different numbers, and neither
number is ever evidence about the other's board. The company profile's
own "My Jobs" section is unchanged and still lists the reader's own jobs
only; it says My Jobs and means it.

### B5: no company surface asks for "Needs your input"

Owner decision 2026-10-19. Removed from this page: the "Needs your
input" toggle chip, its count, and the `needs_attention` mark the payload
derived for it. Removed from the profile: the header chip and the violet
needs-input card, with the `needs_input` key that decided when to show
them and the three helpers behind it (`field_state`, `field_flagged`,
`signals_tried` in `careeros/web/pages/companies.py`). A missing sector
or size now reads **Unknown** in the Classification section, beside the
two things that answer it; see [Detail pages](detail-pages.md). The Jobs
board keeps its own "Needs your input" chip, which is about a job.

The superseded tests went in the same change rather than being left
passing against nothing: nine `needs_input` cases in
`tests/test_company_page_context.py`, three directory-mark cases in
`tests/test_companies_directory.py`, and the toggle and card specs in
`frontend/tests/companies-list.spec.js` and `company-detail.spec.js`.
Each place gained an absence pin instead, over the record shape that used
to raise the ask (a company carrying a review flag).

## Retired companies (M2 soft retire)

A company the admin deletes while another user's job or experience still
links it is not removed; it gains the `retired` tombstone (owner
decision 2026-10-18, [schemas](../schemas.md)). The directory, the
profile, the raw list, the Notes page, the Taxonomy breakdowns, the
position form's company picker, the admin-triggered backfill sweep and
the resolution ladder all leave it out, so for the admin it is gone and
their next posting never resurrects it. For the user whose own record
links it nothing changes: the card is in their directory, the profile
loads, the label resolves and their job still saves. Visibility is "my
own record links it", so a user with no link sees it the way the admin
does.

A retired company takes no new link either: `company_id` naming one is
refused on every write with the same answer a deleted id gets, so the
tombstone cannot be read off a write any more than off a read. The link
a record already carried is grandfathered and keeps saving, which is the
whole point of retiring rather than removing.

Nothing un-retires a company through the interface, because the admin
cannot see one to ask about. That is an open question in PROJECT.md.

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
empty directory shows the empty message with no filter controls and no
view pair — the deliberate improvement kept from the 2026-10-13 rework,
since filters with nothing to filter serve no purpose. A filter
combination that matches nothing says so ("No companies match these
filters.") in either view; before the rework it rendered a silently empty
grid. The "Nothing needs your input." variant went with the toggle (B5).

## Routing

No Jinja coexistence (same no-coexist decision as the JOZ-280 detail
pages; see [Detail pages](detail-pages.md)): `/companies` exists only when
`CAREEROS_REACT_UI=1`, with the Jinja `companies.html` template and its
view removed rather than kept as a flag-off fallback
(`tests/test_react_ui_flag.py`).

## Verification

2026-10-19 (B3/B4/B5): `.venv/bin/python -m pytest tests -q` and
`cd frontend && npx playwright test`; counts in the round's own report.
New tests: the universe count and "every company whatever its source" in
`tests/test_companies_directory.py`, the five columns, the two sorts, the
filters over both views and the B5 absence pins in
`frontend/tests/companies-list.spec.js`.

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

- **A company known only to the feed pool is still in no list.** The
  adapters write no vault record, so the merge step is what would put
  those companies in this directory; it does not exist yet. See B3 above.
- Sorting is the list view's own and is not remembered between visits,
  unlike the filters and the view choice. Nothing asked for it to be.
- Does the Company detail page's size value follow the same
  classes-win rule? It still prefers the raw range it was given
  (`companies.field_value`), which only matters until `--apply` runs. What
  it no longer does is show a class as its code: where it reads the class,
  it reads the taxonomy's label for it (CAREER-71).
- Should the legacy free-text `size` field go the same way as
  `size_range`? A posting that states a size still fills it on a company
  with no class, and the detail page prefers it over the class, so the
  two scales can still disagree on a record written that way. M0-7 was
  scoped to `size_range`.
