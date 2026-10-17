---
type: Surface
title: "Taxonomy"
description: "Describe the read-only vault-wide taxonomy page."
timestamp: 2026-10-13
---

# Taxonomy

## Purpose

Read-only, vault-wide aggregate counts for the skills used on experiences,
the ISIC industry sections companies sit in, and companies' size classes.
No editing lives here: every count is an aggregate, not a single record a
popup could edit.

## Appears in

Nav → Taxonomy (`/taxonomy`), backed by `GET /api/taxonomy`
([contract](json-api.md)).

## Minimal contents

Three sections, each a two-column count table (label, count): Skills,
Industries, Company size. Skills and Industries are sorted by count desc
then name/label. Skills merges
the legacy free-text `skills` field with tag tokens on the skill facets
(`skill/capability`, `skill/domain`), shown by registry label. Company size
always lists the size vocabulary's own order
(micro/small/medium/large/xl, from the taxonomy code list) plus a trailing
unknown bucket whenever at least one company exists.

## States

Loading, a load error with Retry, and the three tables above. An empty
section (no skills, no companies with industry data, no companies at all)
renders a quiet per-section message instead of a header-only table.

## Open questions

No owner click-test recorded yet for this page; implementation only.
