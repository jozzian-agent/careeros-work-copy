# How the pool decides "in area", and what hygiene drops (CAREER-133)

Written 2026-11-02 from the live stores and the 2026-11-01 export
(833 pool rows, 6 providers, 170 tenants). Read-only investigation; the
only code change that came out of it is the hygiene filter in
`careeros/feeds/export.py`.

## The in-area rule, as built

`careeros/feeds/geocode.py` decides per OFFICE, and
`careeros/feeds/export.py:build_pool` decides per POSTING:

1. **Per office.** Each office line the feed states is geocoded against
   the BFS municipality register. An office is `zurich` (IN_AREA) when it
   resolves to a municipality in canton Zurich (ZH canton code 1);
   `out_of_area` when it resolves elsewhere in CH or its own prefix names
   a foreign country ("DE - Berlin" needs no human); `needs_review` when
   it resolves to nothing or ambiguously.
2. **Per posting.** A posting is in scope when **ANY** of its offices is
   IN_AREA. The posting then records the best Zurich office — one with a
   municipality beats one without, corroborated beats name-only.
3. **No office at all** → `needs_review`, and the export skips it unless
   `--include-out-of-area`.

Out-of-area postings stay in the snapshots either way; they are only
included in the pool export when asked for, which is how the excluded
half can be counted without being sampled.

## The owner's observation: 15 of 150 sampled postings show a first
## location abroad — this is correct, and why

A posting's `offices_raw` is the feed's own list, in the feed's own
order. Multi-location postings often list a foreign office first and a
Zurich office later ("London … Zurich", "New York, NY, USA … Zurich,
Switzerland"). The rule above keys on ANY office in Zurich, not the
first one, so such a posting is genuinely in scope — the employer has a
Zurich office and the posting records the Zurich municipality.

Measured on the 2026-11-01 export: **64 of 833 rows (7.7%) have a
foreign first office**. All 64 carry `municipality_label: Zürich` and an
`office_matched` in Zurich; the geocode method is `name+stated_country`
(the confident one). Examples: ElevenLabs "Infrastructure Engineer"
(London first, Zurich matched), Mistral "Research Engineer, Machine
Learning" (Paris first, Zurich matched), Snowflake "Principal Software
Engineer - AI Poland" (`PL-Poland-Remote` first, `CH-Zurich-MSO`
matched). These are real Zurich-market postings for a person who can
work from Zurich, which is what the pool is for.

**No change was made to the in-area rule.** The one thing a reader of
the pool should know is that `offices_raw[0]` is not the posting's home;
`office_matched` / `municipality_label` is.

## What hygiene drops, and why

Two kinds of row are not the owner's market (owner item 2026-11-02):

| Kind | Measured 2026-11-01 | Gate |
|---|---|---|
| Demo tenant rows | 15 (all from `demorecruiting`, Personio's own demo board — "sdf", "asdasfd", "Daanish Test 3", but also innocent-looking "Marketing Manager") | tenant slug, pinned in `export.DEMO_TENANTS` |
| Open applications | 21 across real tenants ("Initiativbewerbung" ×4, "Open Application", "Spontanbewerbung", "Talent Pool", "Unsolicited application", …) | title phrase, pinned in `export.OPEN_APPLICATION_PATTERNS` |

Both drop through the export's existing `skipped` list with their own
reason, so `skipped_reasons` in the export file tallies them and the
pool size stays explainable. Snapshots are never deleted — the junk rows
stay in the store, they just do not reach the pool.

### The false positive that shaped the rule

A broad title match on "test" would have eaten **"Software Engineer in
Test, Robotics Middleware & Systems"** (neura-robotics) — a real SDET
role, twice in the pool (DE/EN). So: demo junk is gated by TENANT, never
by title, and open applications are gated by whole phrases with word
boundaries ("Open Source Program Manager" and "Initiative Manager" are
not open applications). Pinned by
`test_a_real_role_is_never_dropped_by_the_hygiene_rule`.

### Left for the owner

* `Wildcard (Exceptional Talent)` (genpeach, 1 row) reads like a talent
  pool but the word "wildcard" is too ambiguous to pin by title. Not
  dropped; named here instead.
* `demorecruiting` stays in the local tenants store and keeps being
  fetched (15 snapshots' worth of polite traffic per run) — only the
  export drops it. Setting its stored status to `skipped` would stop the
  fetching too; that edits local store data, not the repo, so it is the
  owner's call.
