# CareerOS Concept Taxonomy Brief

This document is a conceptual design artifact only. It proposes no code changes. Every item below is a proposal for owner review before any engineering ticket is opened. Field names, file names, and endpoint paths are concrete proposals, not commitments; the owner decision sheet at the end lists every open choice.

All examples use synthetic company, person, and posting data. No real owner career content appears anywhere in this document.

---

## 1. Company Unification

### Current state

`companies/` holds CO-### records (`name`, `website`, `size`, `sector`, `locations`, `enrichment`). `jobs/` link to companies via `company_id`. `experiences/` store `company` as a free-text string with no link at all. Of 7 experience records, only 1 has a company name that matches an existing CO-### record by text. The other 6 are either unmatched real companies, an aggregate entry ("Early Career"), or a non-company entity (a university guest-lectureship).

Company writes and experience writes do not behave the same way today. `vault.save_company`/`_save_record` (`vault.py` around :166-183) start from a `defaults` dict, merge the existing stored record on top, then merge in whatever the caller sent, so any field the caller omits is preserved from the existing record. `vault.save_experience` (`vault.py` around :106-119) instead calls `validate_experience(data)` directly on the incoming payload and writes exactly what that function returns, plus `id` and the untouched `salary`; there is no merge with the existing stored record for any other field. This asymmetry matters for every migration below.

### OPTIONS

| Option | Description | Tradeoffs |
| --- | --- | --- |
| A. Hard link only | Add `company_id` to experiences, require it, migrate or drop free text | Clean model, but breaks on any experience that has no sensible company record (aggregates, guest talks) |
| B. Soft link, dual field | Add optional `company_id` alongside the existing free-text `company`; `company` becomes a display fallback when `company_id` is null | Backwards compatible, handles edge cases gracefully, but risks the two fields drifting apart if the UI does not enforce which one wins |
| C. Typed records with a record-type flag | Companies become `type: employer | institution | aggregate`; experiences always carry `company_id`, pointing at whichever type fits | Most unified data model (one source of truth for every past entry), but requires classifying every existing record once, and "aggregate" is a modeling compromise, not a real company |

### RECOMMENDATION

Option C, implemented as an additive migration on top of B's compatibility story. Concretely:

- Add a `kind` field to company records: `employer`, `institution` (universities, non-profits, government bodies), `aggregate` (placeholder entries like "Early Career" or "Freelance / Various" that intentionally have no website, size, or sector).
- Add `company_id` (nullable string) to experience records. An experience with `company_id: null` is the explicit "not linked yet" state, not an error, since the owner may defer linking.
- Company detail page shows two sections: **Jobs** (existing behavior, via `job.company_id`) and **Experience** (new, via `experience.company_id`).

### Behavior matrix by `kind`

The original draft of this section said institutions were "enrichable" and then excluded them from enrichment with a single `kind != 'employer'` guard, which is self-contradictory and also too blunt: a guard that excludes institutions from *all* enrichment also blocks harmless, low-risk lookups (confirming a university's official website) that have nothing to do with sector or size. Replace the single boolean guard with a field-group matrix:

| `kind` | Enrichment eligibility | Companies-grid visibility (default) | Sector/size filter participation | Job-derived aggregation (`enrich.py`) |
| --- | --- | --- | --- | --- |
| `employer` | All field groups: name/website lookups and sector/size lookups | Visible | Included | Included |
| `institution` | Name/location/website lookups only; sector and size are not derived, since neither concept applies cleanly to a university, non-profit, or government body | Visible | Excluded | Included for non-sector rollups (`top_keywords`, `hiring_activity`, `locations_seen`, `seniority_range`) if any linked JOB supplies them; `enrichment.sectors` is explicitly removed during regeneration, same as the top-level field (see note below), not merely omitted from what gets newly derived |
| `aggregate` | None; no website, sector, or size by design | Hidden by default, with a "Show all" toggle | Excluded | Included for the same non-sector rollups as `institution`, so a placeholder like "Early Career" can still show `hiring_activity`/`top_keywords` from whatever jobs link to it; `enrichment.sectors` is explicitly removed here too, not merely omitted |

Two corrections to the aggregation column, both load-bearing for approving this matrix. First, `enrich.py`'s aggregator (`regenerate_company`, around :51-65) reads only `vault.list_jobs(root)` filtered by `company_id`; it has no code path for experiences today. Describing an institution's rollup as "included if any job or experience links to it" would be describing new engineering, not existing behavior; this document does not assume experience-derived aggregation exists or should be built, and flags it as out of scope unless the owner separately asks for it. Second, `regenerate_company`/`enrich_company` (`enrich.py` around :17-65) is currently kind-unaware: given any linked job, it aggregates that job's raw `sector`/`sectors`/`industry`/`industries` strings into `enrichment.sectors` regardless of the company's `kind`. The "Sector/size filter participation: Excluded" policy for institutions and aggregates has to cover this nested rollup too, not only the top-level `sectors` field, or a university with one linked job would show sector data in its enrichment block while being excluded from every sector filter that reads the top-level field, an inconsistency an owner would notice immediately on the company detail page. Required engineering: gate `regenerate_company`'s sector aggregation on `kind == 'employer'`, and, for any company whose `kind` is not `employer`, explicitly delete both the top-level `sectors` field and the `enrichment.sectors` key during regeneration, rather than merely leaving the `sectors` key out of the newly derived values that get merged in. This distinction matters because `regenerate_company` (`enrich.py` around :59-60) seeds its working `block` from a *copy of the company's existing* `enrichment` before merging in whatever `enrich_company` newly derives; if the derived dict simply omits a `sectors` key because aggregation was gated off for this `kind`, the pre-existing `enrichment.sectors` value already sitting in that copied block is carried forward untouched. Concretely, a company that was `kind: employer` at some earlier regeneration (so `enrichment.sectors` got populated) and is later re-kinded to `institution` or `aggregate` keeps showing that stale sector data on every subsequent regeneration unless the gate actively deletes it. Every other rollup (`top_keywords`, `hiring_activity`, `locations_seen`, `seniority_range`) is left exactly as the existing merge already handles it, since none of those are sector/size concepts and institutions/aggregates benefit from them the same way employers do. Section 3's backfill action applies this same `kind == 'employer'` scope, so institutions and aggregates are never selected for either the sectors or size backfill cascade.

This table is itself a decision point: see the owner questions below.

### Company-link lifecycle: label display, rename, unlink, deletion

The original draft only covered the link-creation path. It left open what happens when a linked company is renamed, unlinked, or deleted, and `validate_experience` had no way to check that a given `company_id` actually exists.

- **Label display (cache vs read-time resolution).** The original draft proposed caching the company's name into `experience.company` at link time and "keeping it in sync." That cache goes stale the moment the company is renamed, since nothing re-writes every linked experience. Recommendation: once `company_id` is set, every renderer resolves the display label live from the linked company record; the cached `company` text is used only for experiences where `company_id` is still null. This removes the rename-propagation problem entirely for linked records, at the cost of one extra lookup per rendered experience (negligible at this vault's scale). The alternative, propagating renames into every linked `experience.company` field with a rewrite script, is listed as a fallback option on the decision sheet in case the owner prefers a cached value that keeps working if the company record is later deleted.
- **Unlink.** Unlinking (setting `company_id` back to null through the same `link-company` endpoint, or a sibling `unlink` action) freezes the current resolved label into the free-text `company` field at the moment of unlinking, so the experience keeps a readable label afterward instead of reverting to whatever stale text, if any, predated the link.
- **Deletion protection.** `server.py`'s `company_api` DELETE handler (around :433) only counts jobs referencing the company before deleting; `vault.delete_company` (around :295) performs no reference check at all, of any kind, and deletes unconditionally. Once experiences can link to companies, the DELETE handler's count must include experiences with a matching `company_id`, not just jobs, or deleting a company silently leaves dangling `experience.company_id` values pointing at nothing. This is a required change to the existing guard, not new ground.
- **Reference validation for `company_id` on experiences.** `validate_experience(data)` (`vault.py` around :73) takes only `data`, with no vault root, so it cannot call `load_company` to confirm a `company_id` is real. Jobs solve the equivalent problem inside `_save_record`, which already has `root` in scope (around :225). The same approach fits experiences: perform the existence check in `save_experience` (which already has `root`) after `validate_experience` returns, rather than threading a root argument through `validate_experience` itself.

### Record-type flag: is a university a company?

Treat it as a `kind: institution` company record rather than inventing a parallel "organization" vault directory, per the matrix above.

### Aggregate entries ("Early Career")

Represented as `kind: aggregate` company records with `name` set to whatever label the owner used. Hidden from the Companies grid by default (visible via "Show all"), per the matrix above.

### Company create-from-experience flow

New endpoint: `POST /api/experiences/<identifier>/link-company`. Body: `{company_id}` to link an existing company, `{create: {name, kind}}` to create one inline, or `{unlink: true}` to clear the link (freezing the label as described above). Server behavior:

1. If `company_id` given, verify the company exists, set `experience.company_id`.
2. If `create` given, look for an existing company whose name matches by the dedupe rule below; if found, surface that as a suggestion rather than silently merging.
3. Otherwise create a new company record with the given `name` and `kind` (default `employer`), `name_source: owner`, and link it.

### Dedupe / merge

`server.py`'s `find_company` (around :87) does not do casefold-name matching alone. It first tries a casefold name match; if that fails, it falls back to matching the posting's URL (host, or host-plus-first-path-segment for shared ATS hosts such as Greenhouse or Lever) against a company's stored `website` or against the URLs of jobs already linked to a company. Both paths are existing code, used by the job-intake pipeline today.

For experience linking, this document proposes a simpler, deliberate choice: name-only casefold matching, with no URL-based fallback, since an experience record has no posting URL to fall back on. When a near-match exists (for example "Acme AG" vs "Acme"), the UI surfaces it as a suggestion ("Did you mean Acme AG (CO-004)?") rather than auto-merging. Generating that near-match suggestion (a fuzzy comparison beyond exact casefold equality) is new code; nothing in the current pipeline does fuzzy company-name matching today. A full merge tool (combine two CO-### records, re-point all jobs and experiences, delete the loser) remains a separate, later feature.

### UI impact

- `experience_form.html`: replace the free-text "Company" input with a combobox backed by `GET /api/companies`, plus an inline "Create new company" option.
- `company_detail.html`: add an "Experience" section below "Jobs."
- `experiences.html`: each card's company name links to `/companies/<id>` when linked, otherwise renders as plain text.

### API shape

- `GET /api/companies/<id>` (the JSON API, handled by `company_api` in `server.py` around :424) returns the company record only; it does not load jobs. Jobs are loaded separately, in the HTML page handler `careeros/web/pages/companies.py`'s `detail` function (around :17-22), which is page-level code, not the JSON API. The new Experience section belongs in that same page handler, loading experiences by `company_id` the same way it already loads jobs, with no new JSON endpoint required unless a future owner tool needs company-plus-experience data as JSON.
- `GET /api/companies/<id>` response gains `kind` (string enum) alongside existing fields.
- `GET /api/experiences` and detail responses gain `company_id` (nullable string).
- New: `POST /api/experiences/<id>/link-company` as described above.

### Migration / backwards compatibility

- Existing company YAML gains `kind: employer` as a filled-empty-only default on next save; a one-time migration script sets `kind: employer` on all 11 current records.
- Existing experience YAML keeps its `company` field untouched; `company_id` is absent (`None` on load) until the owner links each one through the new UI.
- **Deployment order and write allowlists.** `_save_record`'s `defaults` dict is the complete write-allowlist for jobs and companies: any key the caller sends that is not a key in that dict is silently discarded (`vault.py` around :183), so every field this document adds must be enumerated there, or in `validate_experience`'s explicit key set, before any UI or extraction path starts sending it:
  - Company defaults (`vault.py` around :180-181): add `kind` (this section), plus `sectors`, `size_range`, `size_class` (Section 3, replacing `sector`/`size`).
  - Job defaults (`vault.py` around :174-179): add `function` (Section 4, list of facet ids) and `employee_count` (Section 3, the raw employee count intake must retain instead of discarding it after bucketing).
  - Experience validation (`validate_experience`, `vault.py` around :77-96): add `company_id` (this section) and `tags` (Section 2).

  Because `_save_record` merges onto the existing stored record, an old client that never sends any of these new keys simply leaves them untouched; that payload is safe by construction. `save_experience` does not share this protection until decision 5 below ships (see the next bullet).
- **Section 3's legacy `sector`/`size` rename.** The legacy company form (`careeros/templates/company_detail.html`) still submits bare `sector` (free text) and `size` on every profile save, and `server.py`'s `fill_company_metadata` (around :82-85) still reads and writes those same two keys, fill-empty-only, from posting-derived metadata. Both must keep working, unchanged, until the UI and this helper are updated to the new field names; retiring `sector`/`size` before then would make every existing company-profile save silently drop the owner's typed sector. Sequencing:
  1. Add `sectors`/`size_range`/`size_class` to the company defaults dict (previous bullet) without removing `sector`/`size`; both shapes coexist in the allowlist for the overlap window.
  2. Translate on write: when a payload includes legacy `sector` (a free-text string) but omits `sectors`, run it through Section 3's keyword-match function and set `sectors` only on a confident match; a legacy `size` bucket string is copied verbatim into `size_range`, while `size_class` is left unset, since a bucket label alone cannot yield a confident EU-threshold classification (Section 3's boundary-value correctness requirement; deriving `size_class` needs a raw employee count, and a bucket-only legacy payload never carries one). This translation must happen on the raw incoming payload before `_save_record` validates and persists it, not after. `_save_record` (`vault.py` around :253) calls `_write(path, result)` and the record is on disk by the time it returns; `save_company` (`vault.py` around :276-278) only receives `_save_record`'s return value afterward, so any translation attempted at that point is operating on data that cannot change what was already written. Concretely, `save_company` performs the legacy-to-new-shape translation on `data` itself, then passes the translated payload into `_save_record`.
  3. Precedence when one payload carries both shapes (for example, a half-migrated client sends `sector` and `sectors` together): the new-shape field always wins; the legacy field is consulted only as a fallback source when the new-shape field is absent from that payload, never to override a new-shape value actually sent.
  4. Readers that change: `fill_company_metadata` stops writing bare `sector`/`size` and instead produces `sectors`/`size_range`/`size_class`, reusing the same keyword-match and size-derivation functions Section 3 defines for the external-fetch pipeline, since a posting-derived `sector`/`size` string is just another input to the same normalization step. `company_detail.html`'s template and its inline save script move from the `sector`/`size` text inputs to the chip editor and dropdown in Section 3's engineering breakdown item 7. `careeros/templates/companies.html`'s grid card is a reader too, not only a writer-side form: its card markup renders `{{ company.sector or 'Sector unknown' }} · {{ company.size or 'Size unknown' }}` directly from the legacy fields. It must move to rendering from `sectors`/`size_range` (or `size_class`) in the same release as the schema rename, or every card on the Companies grid silently reverts to "Sector unknown / Size unknown" the moment `sector`/`size` stop being populated.
  5. Retirement order: `sector`/`size` are removed from the company defaults dict and from the template only after steps 1-4 have shipped and the one-time backfill (Section 3) has run against all 11 existing records. Removing them earlier would silently discard any legacy-shaped payload still in flight, the same hazard the next bullet addresses for experiences.
- Experiences do not get that same write-allowlist protection today, because `save_experience` reconstructs the record from `validate_experience(data)` rather than merging with the stored record. A browser tab left open across the deploy, submitting the old field shape, would silently drop any `company_id` or `tags` value the experience already had, since those keys are simply absent from the old payload and nothing merges them back in. Recommendation: change `save_experience` to merge onto the existing stored record the same way `_save_record` already does for companies and jobs, bringing all three record types onto one write pattern, rather than carving out a narrow "absent key means unchanged" exception for just these two new fields. This is listed as a decision point below, since it changes behavior for the existing `highlights`/`skills`/`custom` fields on experiences too (they would also become merge-not-reconstruct), which is a larger change than this section strictly needs but avoids a one-off special case.

### Engineering breakdown

1. Add `kind` to company schema + validation + one-time backfill script. Testable: load every company record, assert `kind` present.
2. Add optional `company_id` to experience schema + existence check in `save_experience` (reusing `load_company`). Testable: save an experience with a bad `company_id`, expect `ValueError`.
3. Change `save_experience` to merge onto the existing stored record (see migration note above), or, if the owner rejects that decision point, add an explicit "absent key means unchanged" carve-out for `company_id` and `tags` only. Testable: PUT a payload missing `company_id`/`tags`, assert the stored values are unchanged.
4. Extend `company_api` DELETE to count linked experiences alongside jobs before deleting. Testable: attempt delete with one linked experience and no jobs, expect 409.
5. `POST /api/experiences/<id>/link-company` endpoint (link, create-and-link, unlink). Testable: link to existing CO-###, create-new path, unlink-and-freeze-label path, dedupe-suggestion path.
6. Company detail page handler (`web/pages/companies.py`): add Experience section. Testable: render page, assert linked experience appears.
7. Experience form: company combobox + create-inline. Manual test on a live instance.
8. Experience card / detail: resolve and link company name live from `company_id` when set, falling back to cached `company` text only when `company_id` is null. Testable: rename a linked company, confirm the experience card's label updates without any experience write.

### Owner questions for this section

1. Institution/aggregate behavior: adopt the field-group matrix above as the enrichment/visibility/filter rule set. Default: yes.
2. Company label display: resolve live from `company_id` at render time, rather than caching a synced label. Default: resolve at read time.
3. Deletion protection: block company deletion when linked experiences exist, same as the existing job-linked guard. Default: yes, block.
4. Experience write pattern: change `save_experience` to merge onto the existing record (like companies/jobs), rather than reconstructing from the payload. Default: yes, switch to merge.
5. Company merge tool (combining two duplicate CO-### records): build now or defer. Default: defer to a later round.

---

## 2. Tag Inventory and Taxonomy

### Current state

27 distinct free-text tags across 7 experience records (`skills` field). One tag used 3 times, one used twice, 25 used once. Tags mix capability language ("Project management", "Team leadership", "Public speaking") with domain/industry language ("Fintech", "Sustainability reporting").

### OPTIONS

| Option | Description | Tradeoffs |
| --- | --- | --- |
| A. Keep free text, add nothing | Status quo | Zero engineering cost, but the tag cloud only grows messier and never becomes filterable/comparable across experiences |
| B. Single flat controlled vocabulary | One `tags.yaml` list, no facets, owner approves additions | Simple, but re-introduces the original problem: "Fintech" and "Project management" are different kinds of things and get muddled together in any filter UI |
| C. Faceted controlled vocabulary | `tags.yaml` with facets (`skill/capability`, `skill/domain`, `function`, `experience-type`, `tool`), owner-governed additions | Slightly more upfront modeling, but lets the UI ask "what capability" vs "what industry" vs "what tool" separately, and reuses the same facet idea needed for Section 4 |

### RECOMMENDATION

Option C. Concretely, a new vault file `tags.yaml` at the root (sibling to `search.yaml`), shaped as:

```yaml
facets:
  skill/capability:
    label: "Capability"
    values:
      - id: project-management
        label: "Project management"
      - id: team-leadership
        label: "Team leadership"
      - id: public-speaking
        label: "Public speaking"
  skill/domain:
    label: "Domain knowledge"
    values:
      - id: fintech
        label: "Fintech"
      - id: sustainability-reporting
        label: "Sustainability reporting"
  function:
    label: "Job function"
    values: []   # populated per Section 4; entries may carry optional esco_uri/isco metadata
  experience-type:
    label: "Experience type"
    values:
      - id: employment
        label: "Employment"
      - id: guest-lecture
        label: "Guest lecture / teaching"
      - id: volunteer
        label: "Volunteer"
  tool:
    label: "Tool"
    values: []   # optional facet, seeded on demand
updated: "2026-10-05"
```

Each experience's `skills` list is replaced (with a compatibility path, see below) by a `tags` list of facet-qualified ids, for example `skill/capability:project-management`. Unknown values are rejected at save time with a clear error naming the nearest facet. The underlying vocabulary values themselves (what counts as a valid "Fintech" tag) are an owner-governed, open-with-review list, not an LLM-enforced constraint; see the validation note below for why the enforcement has to live in code, not just in a prompt.

### Facet id transport rules

A facet-qualified id such as `skill/capability:project-management` parses fine as a YAML scalar, but using it as a token elsewhere (a URL path segment, a query parameter, a form field value) needs explicit rules, since it contains two punctuation characters with special meaning in other contexts:

- Parse by splitting on the **first** colon only (`str.split(':', 1)`). Facet keys may contain a slash (`skill/capability`) but never a colon; value ids never contain a colon or a slash, so the split is unambiguous.
- Allowed characters: facet keys match `[a-z0-9/_-]+`; value ids match `[a-z0-9-]+` (ASCII, kebab-case). This guarantees the first-colon split is safe and that no further escaping is needed inside YAML or JSON.
- Any time a facet:id token is placed in a URL query parameter, it must be percent-encoded on the way out. Plain `urllib.parse.quote('skill/capability:project-management')` is not enough on its own: `quote()`'s default `safe='/'` leaves the slash untouched and only encodes the colon, producing `skill/capability%3Aproject-management`. A single opaque token needs `quote(token, safe='')`, which encodes both punctuation characters, producing `skill%2Fcapability%3Aproject-management`.
- Decode discipline: Flask's routing and `request.args`/`request.view_args` already URL-decode path and query values once before application code ever sees them. Exactly one decode happens, performed by the framework; application code never calls `unquote()` on a value that arrived via a path or query parameter, full stop. A value that happens to contain a literal `%3A` would decode a second time into `:` and corrupt the colon-split, and there is no "deliberately double-encoded" exception to this: if some intermediate layer genuinely requires double-encoding to survive, that layer's own decode step is where the second decode belongs, not a second `unquote()` call in application code.
- Percent-encoding a token does not make it opaque to **Flask/Werkzeug's routing**, even with `safe=''`. Werkzeug decodes `%2F` back into a literal `/` before matching the decoded path against route rules, so a default `<token>` path converter still splits on that now-literal slash: a route defined as `/tag/<token>` given the `safe=''`-encoded value `skill%2Fcapability%3Aproject-management` is matched against the decoded path `/tag/skill/capability:project-management`, which has one segment too many for that route rule, and returns 404. This is a routing-layer behavior, not a flaw in the encoding advice above; `quote(token, safe='')` still correctly produces one opaque *string*, but Werkzeug decodes before routing, so that string is not one opaque *path segment*. Recommendation: transport facet:id tokens as a query parameter (`?tag=skill%2Fcapability%3Aproject-management`, decoded once by `request.args`) rather than a path segment; if a path segment is unavoidable, use a Werkzeug `path` converter (`<path:token>`, which preserves literal slashes instead of treating them as segment breaks) and encode only the colon. Facet:id tokens must not be used in route segments that rely on the default converter.

### Mapping the existing 27 tags (synthetic examples)

| Existing free tag | Proposed facet:id |
| --- | --- |
| "Project management" | `skill/capability:project-management` |
| "Team leadership" | `skill/capability:team-leadership` |
| "Public speaking" | `skill/capability:public-speaking` |
| "Fintech" | `skill/domain:fintech` |
| "Sustainability reporting" | `skill/domain:sustainability-reporting` |
| "Stakeholder communication" | `skill/capability:stakeholder-communication` |
| "Agile delivery" | `skill/capability:agile-delivery` |
| "Budget ownership" | `skill/capability:budget-ownership` |
| "Renewable energy" | `skill/domain:renewable-energy` |
| ... (remaining 18 one-off tags) | each mapped individually by the owner during the governance pass below; most land in `skill/capability` or `skill/domain`, a few (e.g. "Excel", "Figma") land in `tool` |

A full 27-row mapping table is a one-time spreadsheet exercise the owner should do once facets are approved, not something to pre-guess exhaustively here; the categories above are illustrative, not a final mapping.

### Governance

New tags are **not** a free-for-all. Proposed flow:

1. While editing an experience, the owner may type a new tag value. If it does not match an existing `tags.yaml` entry, the UI offers "Propose new tag" with a facet picker, and the save creates the tag in `tags.yaml` and the reference in the same request (a single owner is both proposer and approver here, so a separate approval queue is unnecessary complexity for a one-person vault).
2. Renaming a tag's `label` only (the human-facing text) needs no rewrite anywhere, since every reference stores the stable `id`, not the label. Changing or retiring a tag's `id` is different: it requires rewriting every record that references it by that id, not only experiences. The `function` facet (Section 4) is consumed by JOBS as well as experiences, so an id change or retirement is a `tags.yaml` edit plus a one-time rewrite of every experience AND job referencing the old id, or, where a clean rewrite is impractical, a tombstone that keeps the old id resolvable to "retired" rather than silently becoming an unknown value.
3. Tags are **open-with-review**, not closed enums: the facet list is fixed (five facets, extensible only by a deliberate owner decision), but values within a facet grow organically through the propose flow above.
4. This same propose flow extends to the `function` facet (Section 4), including the case where a proposed function value has no corresponding ESCO concept; see Section 4's governance note.

### Multilingual concerns

The owner is in Switzerland; postings arrive in German and English. Recommendation: store tag `id` as a stable English slug (ASCII, kebab-case) and `label` as whatever language the owner typed, with an optional `label_de` field for a German display label. Do not attempt automatic translation. Job-side extraction (Section 4) may encounter German postings; at launch, the LLM pass is given each function facet entry's English and German labels/keywords as prompt context, so it can match a German posting to the right facet id without relying on translation alone. A separate deterministic German/English keyword-to-function-id matcher remains deferred future work (Section 4), not part of the launch path; the two approaches are not both adopted at once.

### Should an external standard replace this vocabulary?

The owner suggested "maybe UN?" For the skill/capability and skill/domain facets specifically: no. Evaluated against two real UN-adjacent candidates:

- **UN ISCO-08 skill-level framework**: operates at a granularity of 4 broad skill levels, nowhere near specific enough to express "Public speaking" or "Fintech."
- **ESCO skills pillar** (EU, not UN, but the closest existing standard): has roughly 13,000 skill/competence concepts, which is the opposite problem for a single person's 27 tags.

A small local vocabulary is the right fit here. Standard taxonomies earn their keep in Sections 3 and 4, where the task is classifying external entities (companies, job postings) against a shared frame of reference other data sources also use, which is a different problem from this personal tag set.

### Validation: why a prompt alone is not enough

The original draft of Section 4 described the LLM prompt as being given "the closed function facet list" and treated this as equivalent to a closed vocabulary, by analogy with the existing `skills`/`keywords` extraction. That analogy does not hold: `careeros/ingest.py`'s `parse_response` (around :109-138) accepts any string the model returns for `skills` and `keywords` (its `LIST_FIELDS`, defined around :16) with no validation against any controlled list, so "the existing closed-vocabulary discipline" for skills/keywords does not actually exist in the current code. A prompt instruction can bias the model toward the supplied facet ids, but it cannot guarantee the model never returns something else (a near-miss id, a translated label, a hallucinated value). Recommendation: validate every LLM-returned `function` id against `tags.yaml`'s known ids after parsing, in the same place `server.py`'s job-update merge logic already filters incoming fields; drop any id that is not a known facet value rather than trusting the model's output, and treat a dropped id the same as "no function identified" (empty list), not an error.

`server.py`'s `apply_llm_update` (around :102-147) already has its own allowlist of fields it is willing to copy from a parsed LLM response (`fillable`, around :106-108) before writing to the job record. Adding `function` support means adding `function` to that allowlist too, alongside the new tags.yaml-id validation step; both are required, not just the validation step on its own.

### Engineering breakdown

1. `tags.yaml` schema + `vault.load_tags`/`save_tags` (reuse `_read`/`_write`). Testable: round-trip load/save.
2. Validation: experience `tags` must reference existing `facet:id` pairs; reject unknown ones with a facet-aware error. Testable: save with bogus tag, expect `ValueError` naming the facet.
3. One-time migration: map the 27 existing free `skills` values into `tags.yaml` entries plus rewritten experience records. Owner reviews the mapping table before this runs.
4. Experience form: replace free-text skills textarea with a facet-grouped multi-select plus "Propose new tag" flow.
5. Keep `skills` as a deprecated, read-only field for one release (rendered if present, never written); for any payload that includes `skills` but omits `tags` during the overlap window, translate `skills` values into `tags` using the one-time mapping table rather than silently treating the absent `tags` key as "no tags," so an in-flight legacy submission does not appear to wipe tags that were never actually sent.

### Owner questions for this section

1. Tag facets: adopt the five-facet model (`skill/capability`, `skill/domain`, `function`, `experience-type`, `tool`). Default: yes, all five.
2. Tag governance: open-with-review rather than a closed enum. Default: open-with-review.
3. External tag standard for skill/capability and skill/domain: reject ESCO/ISCO as oversized, keep a small local vocabulary. Default: reject standard.
4. Legacy `skills`-to-`tags` translation during the overlap release: translate automatically using the mapping table, rather than treating a `skills`-only payload as "no tags." Default: yes, translate.

---

## 3. Company Sector and Size via Standard Taxonomies

### Current state

All 11 company records have `sector: null` and `size: null`. This is a different system from the company-level enrichment described below, and the original draft of this document conflated the two.

- `careeros/intake.py`'s `_extract` (around :281, size bucketing around :347-357) is part of the **job-posting** intake pipeline. When a posting's JSON-LD includes `hiringOrganization.numberOfEmployees`, `_extract` buckets it into `1-10`/`11-50`/`51-200`/`201-1000`/`1000+` and returns a raw `sector` string from JSON-LD `industry`, as fields on the extracted **job**, not the company. `server.py`'s `fill_company_metadata` (around :82-85) then copies that posting-derived `sector`/`size` onto the linked company record only if the company does not already have a value. This is existing code, but it is posting-derived, fill-empty-only, and has nothing to do with Wikidata, OSM, or a company's own website. Critically, `_extract`'s bucketing step converts `numberOfEmployees` to a local `float` only long enough to pick a bucket label, and returns only that bucket string (`size`) on the extracted dict; the raw count itself is never part of `_extract`'s return value and is discarded once the bucket is chosen. Any atomic `size_class`/`size_range` derivation that needs the raw count (see the Size section below) has nothing to work from on the posting-intake path as the pipeline is written today.
- `careeros/enrich.py`'s `enrich_company`/`regenerate_company` (around :17-48, :51-65) is a separate, already-existing mechanism: it aggregates fields already stored on a company's linked **jobs** (their `sector`/`sectors`/`industry`/`industries` values) into a nested `company.enrichment.sectors` list, plus other rollups like `top_keywords` and `hiring_activity`. `POST /api/companies/<id>/enrich` (`server.py` around :365) calls this aggregator. It performs no network IO and reads no external source; it only re-summarizes data the vault already has.
- There is no existing code anywhere in the repository that fetches a company's own website, queries Wikidata, or queries OpenStreetMap. The Wikidata/JSON-LD/OSM company-enrichment pipeline described below is entirely **new engineering**, distinct from both mechanisms above.
- `sector` is single-value on the company record today, where the owner now wants multi-select.

### Sector: evaluating standards

| Standard | Granularity | Wikidata/JSON-LD mapping | Multi-select fit | Swiss/human readability |
| --- | --- | --- | --- | --- |
| UN ISIC Rev.4 (sections, 21 top-level) | Coarse (21 sections) | Weak - Wikidata's P452 ("industry") links to free-form industry items, not ISIC codes directly; needs a lookup table | Good - few enough sections that multi-select stays usable | Globally recognized but not how a Swiss job seeker thinks about "Fintech" vs "Industrial software" |
| EU NACE Rev.2 | Same 21 sections as ISIC Rev.4 at the top level (NACE is an ISIC-aligned refinement); granularity grows only at NACE's deeper 2/3/4-digit levels (divisions/groups/classes, roughly 600 classes at the most detailed level) | Weak, same gap as ISIC | Fine at the section level, same as ISIC; the deeper levels are the ones that are poor for a simple multi-select, not the sections | More EU/Swiss-familiar than ISIC at the detailed levels, but still code-speak at depth |
| GICS | Moderate (11 sectors, 25 industry groups) | None open - GICS is a proprietary MSCI/S&P standard; there is no Wikidata property or open JSON-LD vocabulary that maps directly onto GICS codes | Good granularity for multi-select | Financial-markets framing (built for equity analysts), awkward for "is this company a logistics company or a software company" |
| NAICS | Fine (North American, 20 sectors, thousands of codes) | None directly; US-centric, no natural EU/Swiss mapping | Poor without level-capping | NAICS is a US standard; adds translation friction for Swiss/EU company data |

### RECOMMENDATION - Sector

Use **ISIC Rev.4 at the section level (21 sections)** as the controlled vocabulary, because:

- 21 sections is the right granularity for a multi-select chip UI, whether compared against ISIC or NACE at the section level (both have the same 21 sections; this document does not use NACE's section-level data as a point of distinction, since there is none).
- ISIC sections are stable and already the base that NACE refines, so a future "go finer" path exists without re-platforming.
- The mapping gap is bridged with a small static lookup table (`isic_sections.yaml`, ~21 rows) plus a best-effort keyword match against whatever free-text industry string an external source supplies. When no confident keyword match exists, the field stays empty rather than guessing.
- GICS is rejected specifically because no open, free mapping exists from Wikidata/JSON-LD onto its codes, not because "no free public mapping surface at all" exists in general; this is a scoped claim about GICS specifically. NACE is not rejected on granularity at the section level, since it matches ISIC there; a future deeper-level breakdown would need the level-capping NACE's lower levels require. NAICS is rejected as the wrong regional frame for a Switzerland-based vault.

Store as `sectors: [string]` (list of ISIC section codes, e.g. `["K", "J"]`), replacing the current single nullable `sector` string. Render human labels from the static lookup table.

### Size: evaluating standards

No ISO or UN classification standard for company size turned up during this review; this is the limit of what this review checked, not a claim that no such standard exists anywhere, since national statistical offices define their own thresholds too. Two real options surveyed:

| Option | Shape | Tradeoffs |
| --- | --- | --- |
| EU Recommendation 2003/361/EC (micro/small/medium/large) | Single-select enum, 4 buckets defined by employee count plus turnover/balance-sheet thresholds | Recognized within the EU/Swiss-adjacent business context, human-readable, but technically needs turnover data CareerOS will never have. CareerOS can only approximate this with an employee-count proxy; it should not be presented as full EU SME qualification, which also requires turnover/balance-sheet-total figures and an independence (ownership) test this vault has no data for. |
| Current `numberOfEmployees` buckets (1-10/11-50/51-200/201-1000/1000+) | Already implemented in `intake.py`'s posting extraction (see Current State above) | Already working, finer-grained than the EU 4-bucket scheme, but is an ad hoc scheme with no external legitimacy or recognition |

### RECOMMENDATION - Size

Keep the existing numeric bucket as `size_range` (renamed from `size` for clarity, see decision sheet), and add a derived `size_class` (EU micro/small/medium/large label, documented as an employee-count proxy, not full EU SME qualification) using the EU thresholds (micro: <10, small: <50, medium: <250, large: >=250).

Four correctness requirements the original draft missed:

- **Derive `size_class` from the raw employee count, never from the `size_range` bucket string.** The existing buckets do not align with the EU thresholds: a count of 9 and a count of 10 both fall in the `1-10` bucket, but only 9 is EU "micro" (10 is "small"); a count of 249 and 250 both fall in `201-1000`, but only 249 is "medium" (250 is "large"). Deriving `size_class` from the bucket label instead of the underlying count would misclassify exactly these boundary values.
- **Compute `size_range` and `size_class` together, in the same write, from the same employee-count input.** Treating them as two independent fill-empty merges risks desync if one gets set from one job's extraction and the other is recomputed later from a different job's employee count. A single derivation function should take the employee count once and set both fields atomically.
- **Partially populated pairs.** A record where exactly one of `size_range`/`size_class` is already set (for example `size_range: '201-1000'` with `size_class` still empty) is not the same case as both-empty or both-set, and fill-empty-only applies per field, not per pair: preserve whichever value is already present (owner-set or previously derived) and attempt to derive only the missing field. The count used to derive the missing field must first be checked for consistency against the already-populated field, whether that count is the original one that produced the existing field or a new count obtained later (for example, from a fresh external-fetch lookup): re-deriving `size_class` from a count must agree with the stored `size_range` (the count must fall inside that bucket's range), and re-deriving `size_range` from a count must agree with a stored `size_class` (the count must derive that same class). Never overwrite the already-populated field just to make the pair internally consistent; an owner-set value is never clobbered by a later derivation, consistent with the Precedence rule below. When no count is available at all, or the only count available contradicts the already-populated field (so the pair cannot be made consistent), leave the missing field empty rather than guessing or writing an inconsistent pair, and flag the record for owner review rather than silently leaving a half-filled pair with no indication anything is pending. This consistency check is not optional plumbing; Section 3's backfill cascade below applies this exact rule, not a looser one, when it fills a missing field from a freshly fetched count.
- **Precedence**: `size_class` is derived by default, but the owner may override it directly; once overridden, it is owner-set and excluded from any future automatic re-derivation, the same owner-wins rule other enrichment-derived fields already follow. The original draft said `size_class` was "purely derived" and also owner-editable, which cannot both be true without this precedence rule.

`size` as a field name is being retired in favor of `size_range` plus `size_class`; see the migration note in Section 1 above for how that rename is handled safely.

### Source-to-field mapping

| Field | Wikidata | JSON-LD | OSM |
| --- | --- | --- | --- |
| `sectors` | P452 (industry) label, keyword-matched to ISIC section | `industry` string, same keyword match | `office=*`/`shop=*` tag, same keyword match, lowest confidence of the three |
| `size_range`, `size_class` | P1128 (employees) | `numberOfEmployees` (existing mechanism, posting-side only; see Current State) | Not available - OSM's commonly used tagging schema has no widely adopted employee-count tag; this is based on standard OSM tag documentation, not an exhaustive survey of every local tagging convention |

Ambiguity and multi-value handling, per field: these are two different questions, and the original draft conflated them.

- **How many sectors apply** is a question of whether a company genuinely operates multiple, independently supported lines of business, which is a different question from two sources merely disagreeing about how to label the same single activity. Confidence alone cannot distinguish these: a company's own website JSON-LD confidently indicating `J` and a separate, confident Wikidata statement indicating `K` could mean the company has two real business lines, or it could mean both sources describe the same activity and one classification is simply wrong. Storing both whenever two confident classifications differ would silently turn source disagreement into a multi-sector claim the owner never warranted. Fix: require independent evidence that the two sources describe genuinely distinct activities, not just differing labels, for example each source's underlying business description (the free-text industry/activity text behind the classification, not just the resolved code) referring to materially different activities. When that evidence exists, store both; this is the intended multi-select case. When it does not, leave the conflict unresolved rather than guessing either way, and flag it for owner review, parallel to how the next bullet already leaves single-signal ambiguity empty rather than guessing.
- **Which single interpretation is right for one ambiguous signal** is a different question. If one signal (one source, one string) matches two or more ISIC sections with comparable confidence (for example, "Technology" could plausibly be `J` or `M`), leave `sectors` empty for that signal rather than guessing.
- **Source conflict**: when two sources disagree about what is plausibly the *same* underlying activity (not two genuinely different lines of business), confidence alone never resolves it, for the same reason the previous bullet rules out confidence-based multi-sector storage: two independently confident classifications of the same activity are still a disagreement about one thing, not evidence of two things. There is no source-priority order proposed here. Default behavior is to leave the field empty and flag the conflict for owner review, the same unresolved-conflict path the previous bullet describes, rather than accepting either source's classification merely because that source was confident. A priority order (for example, company-website JSON-LD outranking Wikidata) is a decision point below, not assumed.
- **Dated employee counts**: Wikidata employee-count statements (P1128) can carry a point-in-time qualifier. Preferring the most recent dated value when multiple statements exist, versus treating all statements as equally current, is a decision point below; this document does not assume one without owner input.
- For size, if `numberOfEmployees` is a range string rather than a point value (e.g. "50-100"), note that `intake.py`'s current extraction (around :350-357) calls `float(employees)` and catches `TypeError`/`ValueError`, so a range string like "50-100" fails to parse today and `size` is simply left `None`. Parsing range strings and choosing the upper bound is new engineering, not a description of existing behavior.

Fill-empty-only and owner-wins remain unchanged: enrichment only ever writes `sectors`/`size_range`/`size_class` when the existing value is empty and not owner-overridden, following the same pattern as the existing `fill_company_metadata` helper.

### Posting-intake plumbing for `employee_count`

Adding `employee_count` to `_extract`'s return dict and to the job defaults is not, by itself, enough to make it reach a company's `size_range`/`size_class`. Every point the value must pass through on the posting-intake path has to be named explicitly, or the feature is not implementable from this document as written:

1. **`intake.py`'s `_extract` (around :347-369).** Return the raw `employee_count` integer alongside the existing bucketed `size` string, per engineering item 2 below.
2. **`vault.py`'s job defaults (around :174-179).** Add `employee_count=None` to the defaults dict, per Section 1's migration note, so `_save_record`'s write-allowlist retains it on the job record.
3. **`server.py`'s `job_intake` handler (around :218 and :230).** `job_intake` currently pops `sector`/`size`/`locations` out of the extracted `data` dict into a separate `metadata` dict for the company (`metadata = {key: data.pop(key) for key in ('sector', 'size', 'locations')}`, around :218), then explicitly copies `sector` back onto the job payload at save time (`'sector': metadata['sector']`, around :230) while `size` is not copied back, so the job itself never ends up with a `size` field today. `employee_count` needs both halves of this, not just one: add `employee_count` to the pop-tuple at :218 so it reaches the company side, **and** explicitly copy it back into the job save payload at :230 (`'employee_count': metadata['employee_count']`, alongside `sector`) so the job itself retains it, the same field `vault.py`'s job defaults (point 2) now expects to be able to store. Adding the key to the pop-tuple alone, without the :230 reinjection, would deliver `employee_count` to the company side while silently discarding it from the job, defeating the point of adding it to the job schema.
4. **`server.py`'s `job_intake` handler's new-company branch (around :223-225) bypasses the derivation entirely.** `job_intake` has two branches after `find_company`: `if company is None and name:` creates a brand-new company by calling `storage.save_company(root, {'name': name, 'website': ..., 'name_source': 'auto'} | metadata)` directly (around :223-225); `elif company:` calls `fill_company_metadata(root, company, metadata)` on the existing record (around :227). Point 5 below places the `employee_count` -> `size_range`/`size_class` derivation inside `fill_company_metadata`, but only the `elif company:` branch ever calls that function. The new-company branch instead merges `metadata` straight into the creation payload, the same dict-union pattern already used for `sector`/`size`/`locations` today; those three keys happen to survive the merge because they are already company-schema keys in `vault.py`'s defaults dict (`sector`, `size`/`locations`), so passing them straight through at creation time is harmless (an empty record receiving its first value is the same outcome fill-empty-only would produce). `employee_count` is different: it is deliberately *not* added to the company defaults dict, since the company schema has no raw `employee_count` field, only the derived `size_range`/`size_class` (point 5). That means `_save_record`'s write-allowlist (`vault.py` around :183) silently discards `employee_count` from the creation payload, the company is created with `size_class` still empty (`size_range` may or may not already be set, depending on whether the legacy translation in Section 1's migration note populated it from the bucketed `size` string at creation time), and no derivation ever runs for it, since `fill_company_metadata` (and its dedicated branch in point 5) is never invoked on the new-company path at all. Confirmed against `server.py`'s `job_intake` source directly: the two branches are genuinely asymmetric, not a fill-empty-only variation of the same call. Fix, chosen over normalizing `employee_count` inline before the creation save: after the new-company branch's `storage.save_company(...)` call creates the record, call `fill_company_metadata(root, company, metadata)` on the result and reassign `company` to its return value, exactly as the existing-company branch already does. This is a re-save-after-creation, not a pre-creation normalization, for two reasons. First, `fill_company_metadata`'s dedicated `employee_count` branch (point 5) already is the one place that owns the fill-empty-only, consistency-checked derivation rule; normalizing inline before creation would require a second call site duplicating that same rule rather than reusing it. Second, a second `save_company` call against a just-created record is consistent with how this handler already works, not a new style: the existing-company branch can issue two sequential `save_company` calls for the same company (`fill_company_metadata` at :227 saves when metadata changes, and the website fallback at :229 saves only when the website is missing; depending on the record, zero, one, or two saves occur), so a second call on the new-company path is not an added complication. Net effect: both branches end up calling `fill_company_metadata` with the same `metadata` dict, one on a freshly created record and one on an existing record, and the function's own fill-empty-only logic handles both uniformly. A freshly created company can already carry a `size_range` value, since the legacy translation in Section 1's migration note can populate it from a bucketed `size` string at creation time; in that case the helper applies the partially-populated-pair consistency rule specified above rather than treating every target field as empty.
5. **`server.py`'s `fill_company_metadata` (around :82-85).** Its `changes` dict is built from a flat key tuple (`('sector', 'size', 'locations')`) that copies each key from `extracted` onto the company 1:1, fill-empty-only. That passthrough pattern is wrong for `employee_count` specifically: the company schema has no raw `employee_count` field, only the derived `size_range`/`size_class` (this section). `employee_count` must not be added to the generic passthrough tuple; instead, `fill_company_metadata` needs a dedicated branch that, when `extracted.get('employee_count')` is present, calls this section's atomic `size_class`/`size_range` derivation function (engineering item 6 below) and writes the result through the same fill-empty-only, consistency-checked rule the partially-populated-pair bullet above and the backfill cascade (engineering item 9 below) already use, never overwriting an already-populated field or writing a value inconsistent with one. Point 4 above routes the new-company branch through this same dedicated branch too, so this is the single place the derivation rule lives for the entire posting-intake path, not one of two.
6. **`server.py`'s `enrich_job` handler's `fill_fields` (around :256-259).** This is the field list the cross-review flagged as excluding `employee_count`: it governs which fields a re-extraction of an existing job's posting (`intake.ingest_posting` -> `_extract`, the same function from point 1) is allowed to fill in on the job record when they are still empty. Add `employee_count` to it, so re-enriching a job can retain a count the first extraction missed. `enrich_job` already calls `fill_company_metadata(root, target, extracted)` at :294, so once `employee_count` reaches `extracted` and `fill_fields`, it reaches the company side through the same fixed helper from point 5, with no separate code path needed.
7. **`server.py`'s `apply_llm_update` `fillable` tuple (around :106-108) is a different list and is not in scope for this field.** `fillable` governs fields parsed from the LLM's free-text response (`ingest.extract`/`extract_async`, built from `ingest.py`'s `TEXT_FIELDS`/`LIST_FIELDS`, around :14-16), which the model is never asked to produce an employee count from; `employee_count` comes exclusively from JSON-LD structured data in `_extract`, never from the LLM text pass, so it would always be absent from an `apply_llm_update` payload and must not be added to `fillable`.

Engineering items 2 and 6 below reference this subsection rather than repeating it.

### Engineering breakdown

1. `isic_sections.yaml` static reference file (21 rows: code, English label, optional German label).
2. Add a raw employee-count field to the job schema (e.g. `employee_count`, nullable integer) and populate it in `intake.py`'s `_extract` alongside the existing bucketed `size` string, instead of discarding the raw `numberOfEmployees` value once it has been bucketed (see Current State above for why the atomic derivation function in item 6 below needs this and does not have it today). This is point 1 of the "Posting-intake plumbing for `employee_count`" subsection above; points 2-7 there cover the job-defaults, `server.py` (both `job_intake` branches), and `fill_company_metadata` changes this item alone does not deliver. Testable: feed `_extract` a JSON-LD fixture with `numberOfEmployees: 42`, assert the returned dict carries both `size: '11-50'` and `employee_count: 42`.
3. Replace `sector: string|null` with `sectors: [string]` in company schema + validation + migration (11 existing null values become empty lists).
4. Keyword-match function: source industry string to zero or more ISIC section codes, with the ambiguity-refusal and multi-source rules above. Testable with synthetic industry strings per source.
5. New external-fetch pipeline (company website JSON-LD, Wikidata P452/P1128 lookup by company name, OSM tag lookup): this is new engineering, not an extension of `enrich.py`. It needs the same URL-safety treatment `intake.py`'s `check_url`/`fetch_url` already apply to posting fetches (no redirects, no private/loopback/link-local targets, bounded size and time) before fetching any company website, since this introduces network calls to domains the vault does not control.
6. Atomic `size_class` + `size_range` derivation function from a raw employee count, called from the new external-fetch path and from the posting-intake path now that item 2 above gives it a raw count to call with. On the posting-intake path, this is called from `fill_company_metadata`'s dedicated `employee_count` branch, per point 5 of the "Posting-intake plumbing for `employee_count`" subsection above, not from the generic fill-empty passthrough that handles `sector`/`size`/`locations`; per point 4 of that subsection, `job_intake`'s new-company branch reaches this same dedicated branch via a post-creation call to `fill_company_metadata`, so both branches derive through this one function.
7. Company detail page: multi-select chip editor for `sectors`, single-select dropdown for `size_class`, read-only display of `size_range`.
8. Companies list page: sector/size filter controls (new).
9. A triggerable backfill action (an explicit "Backfill sector/size" control or CLI command, not a silent automatic re-run), scoped to `kind: employer` companies only, per Section 1's matrix. `sectors` and size each get their own independent eligibility check and source cascade, since a company can be missing one without the other and the two fields have different zero-network tiers available:
   - **`sectors` cascade**: eligible whenever `sectors` is empty, regardless of whether `size_range`/`size_class` is already set. First, attempt to promote whatever `enrich.py`'s job-aggregation has already written to `company.enrichment.sectors`: those are raw industry strings, not validated ISIC codes (see Current State above), so each one is run through the keyword-match function above; a confident match promotes it into the top-level `sectors` list, an ambiguous or no match is dropped. If that promotion step yields nothing, fall back to the external-fetch pipeline (company website JSON-LD, Wikidata P452, OSM). If that also yields nothing, leave `sectors` empty.
   - **`size_range`/`size_class` cascade**: eligible whenever either field is empty, regardless of `sectors`. There is no zero-network first tier for size, since `enrich.py`'s aggregation derives no size at all (see Current State above); go directly to the external-fetch pipeline (Wikidata P1128, JSON-LD `numberOfEmployees`). When both fields are empty, run the fetched count through the atomic size-derivation function and set both at once. When only one field is already populated (the partially-populated-pair case above), this cascade must obey the same consistency rule the partially-populated-pair bullet above sets out, not a looser one: before writing the missing field, check whether the freshly fetched count is consistent with the already-populated field (for a preserved `size_range`, the fetched count must fall inside that bucket's range; for a preserved `size_class`, the fetched count must derive that same class). On a contradiction, for example a preserved `size_range` of `1-10` and a freshly fetched count of 500, do not write the missing field from that count, since deriving `size_class: large` while `size_range` still reads `1-10` would produce an inconsistent pair; leave the missing field empty and flag the record for owner review instead, same as the no-count-available case below. Only when the fetched count is consistent with the already-populated field does this cascade use the derivation function's output to fill the missing field, and it never overwrites the already-populated one regardless. If the external fetch yields nothing, leave whichever field was already empty still empty.
   - The two cascades are independent passes over the same company list: a company already holding `sectors` but missing `size_range`/`size_class` still runs the size cascade, and a company already holding `size_range`/`size_class` but missing `sectors` still runs the sectors cascade.
   - The external-fetch tier of either cascade performs new, owner-visible network calls that should not run unannounced, which is why the action stays an explicit trigger rather than an automatic re-run.

### Owner questions for this section

1. Sector standard: adopt ISIC Rev.4 at the section level over NACE/GICS/NAICS. Default: ISIC sections.
2. Sector field shape: multi-select `sectors: [string]` replacing `sector`. Default: yes.
3. Size field naming: `size_range` (renamed from `size`) plus new `size_class`. Default: yes.
4. Size precedence: `size_class` derived by default, owner override always wins and is excluded from re-derivation. Default: yes.
5. Ambiguous employee-count ranges (e.g. "50-100"): resolve to the upper bound. Default: upper bound.
6. Source-conflict handling for sectors: no source-priority order; require independent confident matches from each source, plus independent evidence of genuinely distinct activities before storing more than one sector, rather than picking a winner. Default: no priority order, distinct-activity evidence required.
7. Backfill mechanism for the 11 null `sector`/`size` records: an explicit, owner-triggered action, scoped to `kind: employer`, running independent per-field cascades (`sectors` tries the zero-network aggregation-promotion path first and the external-fetch pipeline second; size has no zero-network tier and goes straight to the external-fetch pipeline) rather than a silent automatic enrichment re-run or a single combined pass. Default: explicit trigger, independent per-field cascades.
8. Dated employee counts: when multiple Wikidata P1128 employee-count statements exist for the same company, prefer the most recently dated statement; if a statement carries no date qualifier, do not treat it as current, refuse to use it rather than guessing. Default: most-recent-dated value, refuse undated statements.

---

## 4. Job Function Taxonomy ("PM at a bank" problem)

### Problem statement

A job posting's title or extracted sector can conflate the company's industry with the role's actual function. "Product Manager" at a bank most often means financial-product management, not software product management, yet a naive sector- or title-based filter would group them.

### OPTIONS

| Standard | What it is | Granularity for "ICT product manager"-style distinctions | Fit |
| --- | --- | --- | --- |
| ILO ISCO-08 | UN occupation classification, 4-level hierarchy (major/sub-major/minor/unit groups), ~436 unit groups | Has a unit group for ICT service managers but nothing as specific as "ICT product manager" vs "financial product manager" on its own | Good as a stable top-level backbone, too coarse alone |
| EU ESCO occupations pillar | Built on top of ISCO-08, adds roughly 3000 finer occupation concepts, including an "ICT product manager" concept distinct from generic "product manager" | Close to the granularity needed for the stated problem | Best single fit |
| O*NET-SOC | US Department of Labor occupation taxonomy, ~1000 detailed occupations | Comparable granularity to ESCO but US-centric | Reasonable, but ESCO fits a Switzerland-based owner reading German+English postings better |

### RECOMMENDATION

Hybrid: store the ESCO occupation concept as the specific `function` tag, and derive its parent ISCO unit group from that concept's own metadata whenever a coarse roll-up is needed, rather than storing the ISCO group as a separate field that has to be kept in sync by hand. ESCO occupations each carry exactly one parent ISCO unit group as metadata, so any `function` tag backed by a real ESCO concept always has an unambiguous ISCO roll-up available on demand, with nothing to independently maintain. This guarantee is scoped to ESCO-backed entries only: a local extension such as `financial-product-manager` below has no ESCO concept and therefore no ISCO roll-up at all until an owner or a later review maps it to one. Any aggregate report that rolls job functions up to ISCO groups must treat local-extension tags as a distinct "unmapped" bucket rather than assuming every validated function tag resolves to a group.

This is the `function` facet seeded in Section 2's `tags.yaml`. Each entry's shape matches other facet entries (`id`, `label`), with two additional optional metadata keys when a value traces to ESCO:

```yaml
facets:
  function:
    label: "Job function"
    values:
      - id: ict-product-manager
        label: "ICT product manager"
        isco: "1330"
        esco_uri: "http://data.europa.eu/esco/occupation/a79170ad-0b7b-4697-864f-1748359aa10a"
      - id: financial-product-manager
        label: "Financial product manager"
        isco: null
        esco_uri: null
        source: local-extension
```

Two corrections to the original draft's worked numbers: ESCO maps "ICT product manager" to ISCO unit group **1330** (ICT service managers), not 2512; ISCO 2512 is software developers and 2412 is financial and investment advisers, neither of which is "ICT product manager." The ESCO concept URI above should be re-confirmed against the live ESCO portal before any lookup table is built from it, since this document cannot run a live web lookup; treat it as the review's best citation, not an already-verified fact. "Financial product manager" as a distinct ESCO occupation concept is **unverified** by this review; it is modeled above as a local extension (`source: local-extension`, no `isco`/`esco_uri`), governed the same way any other owner-proposed facet value is governed (Section 2), unless and until a real ESCO concept for it is found and confirmed.

`esco_occupations.yaml`, mentioned in the engineering breakdown below, is not a second live registry. `tags.yaml`'s `function` facet is the single canonical source consulted at runtime; `esco_occupations.yaml` is a one-time or periodic bulk-export reference file used only to seed or validate new `function` facet entries before they are added to `tags.yaml`.

Jobs get `function` tags from this facet, as a **list** (see below), consistently with every other facet's list-valued tags; companies keep `sectors` (Section 3, ISIC-based). Filtering/ranking combines both independently.

### List-valued function payloads, consistently

The original draft had the LLM pass return a single scalar-or-null function id, while the job schema's engineering breakdown proposed a list field "since a posting can occasionally span two functions." Those two cannot both be right. Fix: the `function` field is a list everywhere, matching the convention `ingest.py`'s existing `LIST_FIELDS` (around :16) already uses for `skills`/`keywords`/`certifications`/`responsibilities`. The LLM prompt asks for a list of matching facet ids (possibly empty, usually zero or one, occasionally more for a genuine hybrid role), not a single id-or-null.

### Governance for local function extensions

When the owner, or the UI acting as an intermediary during classification, proposes a new `function` value with no corresponding ESCO concept, it is created the same way any other owner-governed facet value is created (Section 2's propose flow), but flagged distinctly (for example a small "local" badge in the UI) so the owner can see at a glance that it will not roll up to an ISCO unit group in any aggregate report.

### Synthetic worked example

Posting text (synthetic): *"Wir suchen einen Product Manager (m/w/d) fuer unsere Kreditkarten-Plattform. Sie verantworten die Roadmap fuer digitale Zahlungsprodukte bei einer Schweizer Bank."*

1. Heuristic pass (offline, per the existing `ingest.heuristic_extract` pattern, around :152-186 of `ingest.py`): the synthetic text above is one paragraph with no `Title:` label and no English " at " separator, so `heuristic_extract` falls through to its last resort and returns the entire paragraph as `title`, which is useless as a job title. This is expected, not a bug to fix here: heuristics are deliberately conservative and offline-only, and producing a clean title from unlabeled prose, or pattern-matching German domain vocabulary ("Kreditkarten," "Zahlungsprodukte"), reliably is out of scope for simple regex. No function is inferred at this stage.
2. LLM pass (prompt built by `ingest.py`'s `build_prompt`, around :93-106, extended with the known `function` facet ids; offline-testable with a mocked client exactly as `tests/test_ingest.py` already mocks the client): the model is asked for a list of matching function ids, not asked to invent new values, and every returned id is validated against `tags.yaml` after parsing (see Section 2's validation note); any id that is not a known value is dropped rather than trusted. Expected output for this synthetic example: `["financial-product-manager"]`, distinct from `["ict-product-manager"]`, even though a title-only match on "Product Manager" (the generic English term the German posting and an ICT posting might share) could not tell the two apart; the LLM pass reaches this distinction from the surrounding Kreditkarten/Zahlungsprodukte/Bank context, not from the title string.
3. Company sector (`sectors: ["K"]`, from Section 3) stays on the company record, separate from the job's `function` tag, so a report like "financial-product-manager roles, by sector" still works for the rarer case of a financial-product-management role at a non-bank (e.g. a fintech software vendor, ISIC `J`, selling card-processing products).

### Engineering breakdown

1. `esco_occupations.yaml`: a curated bulk-export subset of ESCO occupation concepts relevant to the owner's job search, used to seed and validate new `tags.yaml` `function` entries (an import source, not a second runtime registry; see above).
2. Add `function` field to job schema as a list of strings + validation against the facet's known ids, with unknown ids dropped rather than rejected outright for LLM-sourced writes (consistent with Section 2's validation note), but rejected outright for direct owner edits (a typo in a manually entered id should surface as an error, not silently vanish).
3. Extend `ingest.py`'s `build_prompt` (around :93) with the known function-id list, including each entry's German/English labels and keywords as prompt context per Section 2's multilingual note, and add `function` to `LIST_FIELDS` (around :16), following the same pattern `skills`/`keywords` already use for list extraction. Add `function` to `server.py`'s `apply_llm_update` `fillable` allowlist (around :106-108) and `enrich_job`'s `fill_fields` (around :256-259), since both currently omit it. Offline-testable with the existing mocked-client test harness.
4. Heuristic fallback: no function guess (empty list) unless a future pass adds explicit German/English keyword-to-function-id mapping.
5. Job detail page: render `function` tags alongside existing `skills`/`certifications` sections.
6. Filter UI: add a function facet filter to the Jobs page, independent of the company sector filter.

### Owner questions for this section

1. Job function standard: adopt the ESCO-occupation-plus-derived-ISCO hybrid, with ISCO always derived from the validated ESCO concept rather than stored separately. Default: yes, hybrid, derived-not-stored.
2. Function extraction method: LLM-only at launch, no heuristic function guesser. Default: yes, LLM-only.
3. ESCO seed scope: curate a small subset of occupation concepts relevant to the owner's search rather than importing the full ESCO occupation list. Default: curated subset, grown on demand.
4. Local function extensions (no ESCO parent, like "financial product manager" until verified): allow them as owner-governed local values with a visible "local" marker. Default: yes, allow with marker.

---

## 5. Reusable Modern Scrollbar

### Current state

`.kanban` in `careeros/web/ui.py` uses `overflow-x:auto` with no scrollbar styling, so it renders the browser/OS default. `theme.py`'s `BASE_CSS` also puts `table { ...; overflow-x: auto; }` under the mobile breakpoint, and `.jobs-table` scrolls horizontally on narrow viewports via the same unstyled mechanism, both are the same underlying problem.

### OPTIONS

| Option | Description | Tradeoffs |
| --- | --- | --- |
| A. Per-surface scrollbar CSS | Style `.kanban` and `.jobs-table` separately wherever they appear | Quick, but duplicates the same five declarations twice today and a third time for every future overflow surface |
| B. One shared class, applied everywhere | A single `.scroll-thin` (or similar) rule block in `theme.py`'s `CSS_VARS`/`BASE_CSS`, referencing only existing CSS variables, applied via class or a universal `overflow-x: auto` selector | One definition, one visual language, matches the brief's "ONE modern reusable scrollbar style used app-wide" requirement directly |
| C. Global `*` scrollbar override | Style `::-webkit-scrollbar` on `*`/`html` with no opt-in class | Simplest markup (zero class additions needed), but removes the owner's ability to ever special-case a surface later without an override rule fighting the global one |

### RECOMMENDATION

Option B: a shared CSS rule block added to `theme.py`, scoped to the selectors that already exist (`.kanban`, the mobile `table` overflow rule) plus a shared `.scroll-thin` class any future overflow surface should opt into.

All colors below reference existing `CSS_VARS` tokens from `theme.py`, no new hex values.

```css
.scroll-thin, .kanban, table {
  scrollbar-width: thin;
  scrollbar-color: var(--border-standard) transparent;
}
.scroll-thin::-webkit-scrollbar, .kanban::-webkit-scrollbar, table::-webkit-scrollbar {
  height: 8px;
  width: 8px;
}
.scroll-thin::-webkit-scrollbar-track, .kanban::-webkit-scrollbar-track, table::-webkit-scrollbar-track {
  background: transparent;
}
.scroll-thin::-webkit-scrollbar-thumb, .kanban::-webkit-scrollbar-thumb, table::-webkit-scrollbar-thumb {
  background-color: var(--border-standard);
  border-radius: 8px;
  border: 2px solid transparent;
  background-clip: content-box;
}
.scroll-thin::-webkit-scrollbar-thumb:hover, .kanban::-webkit-scrollbar-thumb:hover, table::-webkit-scrollbar-thumb:hover {
  background-color: var(--text-faint);
}
.scroll-thin::-webkit-scrollbar-thumb:active, .kanban::-webkit-scrollbar-thumb:active, table::-webkit-scrollbar-thumb:active {
  background-color: var(--text-muted);
}
```

Placement: add this block to `theme.py` as a new constant, concatenated into the style tag alongside `CSS_VARS`/`BASE_CSS` in `page_shell`. `ui.py`'s existing `.kanban {overflow-x:auto; ...}` rule is untouched except for gaining this shared scrollbar styling, no layout change, purely a cosmetic override.

### Engineering breakdown

1. Add the CSS block above to `theme.py` as a new constant, concatenated into the style tag alongside `CSS_VARS`/`BASE_CSS` in `page_shell`.
2. Verify `.kanban` picks it up with no markup change.
3. Verify the mobile `table` overflow rule in `BASE_CSS` picks it up with no markup change.
4. Add `.scroll-thin` class to any future custom-scrolling container as those surfaces are built; no retrofitting needed today.
5. Manual visual check on a live instance: kanban board horizontal scroll, jobs table mobile horizontal scroll, confirm thumb/track colors read correctly in both idle and hover states.

### Owner questions for this section

1. Scrollbar scope: scoped selectors (`.kanban`, `table`) plus an opt-in `.scroll-thin` class for future surfaces, rather than a blanket `*` override. Default: scoped selectors plus opt-in class.

---

## Owner Decision Sheet

1. Company record type flag: use `kind: employer | institution | aggregate` on company records. Default: yes.
2. Institution/aggregate behavior: adopt the field-group matrix (enrichment eligibility, directory visibility, filter participation, job-derived aggregation) in Section 1, replacing a single on/off enrichment guard; the sector/size exclusion for institutions and aggregates covers both the top-level fields and the nested `enrichment.sectors` rollup, requiring `regenerate_company` to explicitly remove both, not merely gate them out of new aggregation, including when a company's `kind` changes after sectors were already stored. Default: yes, matrix, including the nested-rollup removal.
3. Company label display for linked experiences: resolve live from `company_id` at render time, rather than caching a synced label that can go stale on rename. Default: resolve at read time. (Fallback option: propagate renames into every linked experience's cached label instead, if the owner prefers a cache that survives company deletion.)
4. Deletion protection: block company deletion when linked experiences exist, extending the existing job-linked guard. Default: yes, block.
5. Experience write pattern: change `save_experience` to merge onto the existing stored record (like companies/jobs do today), rather than reconstructing the record from only the fields in the incoming payload. Default: yes, switch to merge.
6. Legacy form/API compatibility: because of decision 5, and because of the `sector`-to-`sectors` and `size`-to-`size_range`/`size_class` renames in Section 3, schema and allowlist changes must ship before the UI changes that depend on them; legacy `skills`-only experience payloads are translated into `tags` during a one-release overlap window, and legacy `sector`/`size` company payloads (from `company_detail.html` and `fill_company_metadata` until both are updated) are likewise translated into `sectors`/`size_range`, and into `size_class` only when a raw employee count is separately available, rather than silently dropped (a bucket-only legacy `size` string yields `size_range` but not a confident `size_class`, per Section 3); `sector`/`size` are retired from the write-allowlist only after translation, backfill, and the updated readers have all shipped. Default: yes, staged rollout with translation on both sides.
7. Experience-to-company linking: add optional `company_id` to experiences. Default: yes.
8. Company merge tool (combining two duplicate CO-### records): build now or defer. Default: defer.
9. Tag facets: adopt the five-facet model (`skill/capability`, `skill/domain`, `function`, `experience-type`, `tool`). Default: yes, all five.
10. Tag governance: open-with-review rather than a closed enum; id changes/retirement (as opposed to label-only renames) rewrite or tombstone every referencing experience AND job. Default: open-with-review.
11. Tag multilingual handling: English slug id, free-text label, optional `label_de`; German/English labels and keywords serve as LLM prompt context for function extraction at launch, with a deterministic keyword matcher deferred. Default: yes, no automatic translation.
12. External tag standard for skill/capability and skill/domain: reject ESCO/ISCO as oversized; keep a small local vocabulary. Default: reject standard.
13. Sector standard: adopt ISIC Rev.4 at the section level over NACE/GICS/NAICS. Default: ISIC sections.
14. Sector field shape: multi-select `sectors: [string]` replacing `sector`. Default: yes.
15. Size standard: combine EU Recommendation 2003/361/EC `size_class` (an employee-count proxy, not full SME qualification) with the existing numeric `size_range` bucket. Default: combine both.
16. Size field naming: `size_range` (renamed from `size`) plus new `size_class`. Default: yes.
17. Size precedence rule: `size_class` derived by default from the raw employee count (never from the `size_range` bucket), owner override always wins and is excluded from re-derivation. Default: yes.
18. Ambiguous employee-count ranges (e.g. "50-100"): resolve to the upper bound. Default: upper bound.
19. Dated employee counts: when multiple Wikidata P1128 statements exist for the same company, prefer the most recently dated one; refuse to use an undated statement rather than treating it as current. Default: most-recent-dated value, refuse undated statements.
20. Sector ambiguity handling: leave `sectors` empty when one signal matches multiple ISIC sections with comparable confidence; store multiple sectors only when independent sources confidently resolve to different sections AND provide independent evidence of genuinely distinct business activities, not just differing labels for what may be the same activity, otherwise leave the conflict unresolved and flag it for owner review. Default: yes, refuse per-signal ambiguity, require distinct-activity evidence for genuine multi-sector, flag unresolved conflicts for review.
21. Source-conflict handling for sectors: no source-priority order; confidence alone never resolves a same-activity conflict between sources, so an unresolved conflict is left empty and flagged for owner review rather than accepted from whichever source was confident, consistent with decision 20. Default: no priority order, unresolved conflicts flagged for review.
22. Job function standard: adopt the ESCO-occupation-plus-derived-ISCO hybrid, with ISCO always derived from the validated concept, never stored by hand; the guarantee of an available ISCO roll-up applies only to ESCO-backed entries, not local extensions. Default: yes, hybrid, derived-not-stored, ESCO-scoped guarantee.
23. Function extraction method: LLM-only at launch, with every returned id validated against `tags.yaml` and unknown ids dropped. Default: yes, LLM-only with validation.
24. ESCO seed scope: curate a small subset grown on demand, stored as the `function` facet inside `tags.yaml`; any bulk ESCO export file is an import source only, never a second runtime registry. Default: curated subset, one registry.
25. Local function extensions (no ESCO parent, e.g. "financial product manager" pending verification): allow as owner-governed local values with a visible marker; preserved in a distinct "unmapped" bucket in any ISCO roll-up report rather than excluded from that report entirely, matching Section 4's body. Default: yes, allow with marker, unmapped bucket in roll-ups.
26. Scrollbar scope: scoped selectors plus opt-in `.scroll-thin` class, rather than a blanket `*` override. Default: scoped selectors plus opt-in class.
27. Backfill mechanism for the 11 null `sector`/`size` company records, scoped to `kind: employer`: an explicit, owner-triggered action running independent per-field cascades, since `sectors` has a zero-network aggregation-promotion tier that size does not. Default: explicit trigger, independent per-field cascades.
