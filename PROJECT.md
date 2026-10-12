# CareerOS

Method lives in AGENTS.md. This file holds what is specific to CareerOS. Items marked proposed have not been approved. Revised 2026-10-09 after the status brief.

## Intent

Job seekers get stuck on job sites. Postings are stale, suggestions are off target, nothing says whether you fit, and there is no place to track what you pursue. CareerOS gives them jobs they actually like, a board to track them, and later a detailed picture of their background that explains why a job fits and writes the CV.

## Where we are

As of 2026-10-09 the product is a personal tool for one owner. It runs on the owner's hardware, is reachable on the local network only, and has no multi-user support. Journey 1 steps 1 to 4 are shipped, which are URL normalizing, hard duplicate check, instant stub and company resolution. Steps 5 to 8 are open as JOZ-267 and JOZ-268. The Journey 1 spec and the ticket tracker are the source for status. This file does not copy them.

2026-10-10: experiences share the company database. Every experience links to a company record by company_id; the free-text company name is a frozen label. The former combined early-career record was split into one experience per employer, each linked, per owner decision; the staffing note (engaged via a third party) stays in the title and no staffing company record is created. Migration ran through the ordinary save path with a plan file kept outside the repo.

2026-10-10: backend JSON page parity for the React migration is implemented for review. Existing record APIs and Jinja remain live; [contracts, reuse decisions and verification](docs/surfaces/json-api.md). This does not mark a React cutover or owner click-test accepted.

2026-10-11: the React Jobs board (migration milestone R0, [sketch](docs/surfaces/jobs.md)) passed the owner click-test on the live instance. It is served behind the CAREEROS_REACT_UI flag; all other pages stay Jinja. One gap found and being fixed: the shared page navigation is missing from the React page. The Jinja Jobs page is removed only at the cutover after the nav parity lands and the owner re-tests.

2026-10-12: the Jobs board was rebuilt to the design brief (JOZ-278; [sketch update](docs/surfaces/jobs.md)): a fit chip per card (rated/"Needs your input"), a compact status control, hand-rolled native drag-and-drop between columns with per-card Undo, and an "Add a job" popup shell (title + Close only, opened from the plus button; the real intake field stays the one below the board until JOZ-279). A cross-review of that batch found and fixed three correctness issues before merge: a failed or undone move was rolling back the whole board's card list rather than just the moved card (clobbering any other card moved in between), a failed Undo could leave the displayed column out of sync with what the server actually kept, and a success toast could replace a still-outstanding error toast. All three are now per-card operations and the toasts are a dismiss-order-independent stack; see `frontend/BUILD_NOTES.md` "Jobs board rebuild (JOZ-278)" for the implementation detail.

## Product rules that shape the flows

The six owner rules live in the Journey 1 spec. These are the ones the flows below depend on.

- Human edits always win, and every field has provenance.
- Failures and unknowns are visible states with a reason, never silent.
- Only confident matches fill anything. Ambiguity raises a review flag.
- Pasted input is never rejected. A link always makes a job record.
- Done means live, per AGENTS.md.
- Ingest never assumes a human triggered it, so discovered jobs reuse the same path.

## Frame

| Field | Content |
|---|---|
| Name | CareerOS for Zurich, a job board that starts from jobs you like or from you |
| Problem | Job sites show stale postings and off-target suggestions. They give no sense of fit, no inspiration and no tracking. |
| Target users | Job seekers who find the usual job sites useless. First version for people in Zurich. |
| First audience | Five friends in Zurich. The question they answer is whether it is useful. |
| In scope | Two entry paths, pick rounds, the board, similar-job suggestions, flags for closed or changed jobs, a company browse view. Fit score and CV reading are a decision, see M5. |
| Out of scope | Regions outside Zurich, the vault, CV generation, Glassdoor data, interview preparation, the company-page watcher |
| Smallest version as value | In one session you leave with three jobs you chose on a board, and you are told when one closes or changes. |
| Dependencies | Hosting that friends can reach. A per-user board on top of shared jobs and companies. A universe of at least 50 companies and 50 jobs in Zurich, built by hand. Pick rounds cannot run without the universe. JOZ-267 and JOZ-268 are not required for the first test, because the owner simulates what they would automate, see M4. |
| Expensive decisions | Gestalt as design system with blue and purple. Companies stay a top-level tab. Universe is a backend word and never appears in the interface. The edit model is per-user boards with the owner editing shared records. Gestalt integration mode: full React front end. Owner decision 2026-10-10 (JOZ-273, option C; see docs/decisions/design-system.md). |
| Success signal | Proposed. Four of five friends put at least three jobs on their board and return within a week. |
| Evidence | The owner's own frustration. Open. |
| Risks | The universe has nothing for a friend outside product and business roles. The local model is CPU-only and takes up to a minute per call, so reading a job or a CV is slow. Enrichment signals are weak, so many companies end up exhausted. The single YAML vault is untested beyond about 24 jobs. Friends upload personal data. A simulated M4 tests whether the experience is useful, and says nothing about whether the automation is fast or accurate enough. |
| Privacy check | Open. Before inviting friends, decide what is stored and where, tell them in plain words, and offer deletion on request. Data stays on the owner's hardware, which helps. Check Swiss data protection basics. |

## Later list

- Second service that watches company pages for new jobs, which is Journey 2
- Fit scoring against a profile, which is Journey 3, unless M5 says it joins the first test
- More regions
- Company profiles with Glassdoor information and typical interview questions
- The vault, where users add their background in detail with AI questions
- CV generation with the right terms
- Interview preparation
- Retry scheduling for exhausted enrichment
- Automating every step the owner did by hand in M4, in the order the friends' feedback makes them matter

## Inventory

### Roles

| Role | Can do |
|---|---|
| Owner | Everything, including editing jobs and companies, resolving review cards and retrying enrichment |
| Friend | Add jobs, manage their own board and preferences, send feedback |

### Concepts

| Word | Meaning | Replaces |
|---|---|---|
| Job | One posting | position, posting, opportunity, role |
| Company | One real organisation, never split by country | none |
| Experience | A position the user held | none |
| Preferences | The user's roles, must-haves, nice-to-haves and avoid lists. Tab is called Search today, rename proposed. | Search |
| Board | The user's jobs grouped by status. In the data this is the in-pipeline flag, which must become per user. | none |
| Needs attention | A filter showing every job with a reason, closed, changed or needs your input. Proposed merge of two existing ideas. | Needs your input as a separate indicator |

### Statuses

| Status | Kind |
|---|---|
| New | Decision. Anything that entered the board, by link, by title or by a pick. |
| Interested | Decision |
| Applied | Decision |
| Interviewing | Decision |
| Offer | Decision |
| Won | Decision |
| Rejected | Decision |
| Stopped | Decision. Replaces Withdrawn. |

Closed, Changed and Needs your input are facts or open questions about a job. They show as flags on the card and are not statuses. The board shows New to Offer as columns. Won, Rejected and Stopped sit together in one collapsed Ended lane. Proposed.

### Surfaces

| Surface | Flow step |
|---|---|
| Jobs, as board and as list | Board |
| Job | Reading a job, flags |
| Companies | Company browse |
| Company | Company browse |
| Experiences | Bring yourself |
| Preferences | Bring yourself |
| JSON page views, taxonomy and experience forms | Existing page flows for the React migration; [contracts and inventory](docs/surfaces/json-api.md) |

Interviews is removed from the navigation until it exists. Tab order is Jobs, Companies, Experiences, Preferences. Proposed.

### Actions

| Action | Where it lives | Who |
|---|---|---|
| Add a job by link or title | One field on Jobs | Everyone |
| Change a job's status | One control on the card | Everyone |
| Retry | On the card or company, visible after a failed or exhausted step | Owner |
| Resolve a company match | The review card | Owner |
| Remove from my board | On the card | Everyone |
| Edit preferences | One edit mode on Search (proposed name: Preferences); Edit criteria → Done / Cancel, batch D | Everyone |
| Add an experience | Experiences | Everyone |
| Send feedback | One link in the footer | Everyone |

Friends never delete jobs or companies. Only the owner edits shared records.

### Fixed lists, to settle in milestone M1

- Sector. Stored as ISIC, on purpose, so that Journey 3 can use standard codes. Show plain labels only if friends find the names confusing.
- Size. Check whether Small, Medium, Large and 1000+ come from one scale. If not, define one by headcount.
- Location. One format. The prototype shows the same place written several ways.
- Function. The filter exists, its values go in this list.

### Design system

Gestalt, React, with blue and purple replacing the default red. Full React front end decided by the owner 2026-10-10 (JOZ-273 option C, docs/decisions/design-system.md). Component inventory to record before the first polish round.

### Capabilities

| Name | Repository | Pinned version |
|---|---|---|
| Organisation intake | capa-repo, submodule at `vendor/capa-repo` | `9606d6d2a097c4c29b7b5844ba906a7defef0efc` |

### JOZ-276: Organisation intake extraction

2026-10-12: pin organisation intake as a submodule at `9606d6d`, per the
[approved contract](docs/capabilities/org-intake.md). The vault store adapter
uses the existing company record keys and save path; no vault format change
is needed. Product call sites now use the capability for identity,
classification, ATS recognition and URL normalization. The four duplicated
modules are removed. Posting IDs and company source records remain
product-owned; the existing intake, server and enrichment modules hold
that integration and vault persistence. The adapter is the only new product
module because the capability requires an injected store.

Owner ruling 2026-10-12: contract rule 5 wins over the previous first-match
fallback. Duplicate exact names produce `needs_review` / `ambiguous_exact`
and list all candidates, without a compatibility shim.

Resolved 2026-10-11: contract rule 8 (inclusive EU thresholds: 10 is micro,
250 is medium, 1001 is large) is owner-approved as recorded in commit
`4e48cf6`. The pre-extraction exclusive-threshold test expectations were
updated to the approved scale in task 2.4; the earlier product behavior
classified exact-boundary counts one class up.

## What the audit says to remove or merge

| Found in the prototype | Do this |
|---|---|
| Enrich with AI, Enrich pending, Backfill sector/size | One Retry, owner only. Enrichment already starts on ingest. Retry scheduling stays out of scope. DONE 2026-10-09 (visible to everyone until M2 roles). |
| Status shown as filter pills, columns, card dropdown and a Board and List switch | Columns are the filter. One control per card. Keep Function and add Needs attention. DONE 2026-10-09 (pills removed; Needs attention toggle added; Function kept; Board/List switch kept per owner decision A). |
| Notes appear twice on the company page | One notes field. DONE 2026-10-09 (read-only markdown card removed; the editable textarea is the one field). |
| Opportunities, Experience, Posting URL | Jobs, Experiences, Add a job by link or title. DONE 2026-10-10 (company page headings renamed; intake label renamed). |
| Custom fields JSON on the company | Check what reads it, then delete if nothing does. DONE 2026-10-09 (nothing rendered it; form control removed, stored data preserved on every company write path). |
| Interviews tab, the taxonomy sub-page text, an empty Updated line | Delete until the feature exists. Interviews tab and the empty Updated line DONE 2026-10-09 (nav entry, route, and page deleted; Updated span removed from Search). The taxonomy sub-page text stays: those pages exist. |
| Five Edit buttons on Search | One edit mode — batch D (JOZ-270), implemented; [approved sketches and live checks](docs/surfaces/preferences.md). Owner implementation click-test pending. |
| AI summary, AI responsibilities and original description on a job | Summary first, collapsed original directly below — batch D (JOZ-271); [approved sketches and live checks](docs/surfaces/job.md). Owner implementation click-test pending. |
| Chunk 4, JOB and CO identifiers | Delete from the interface. DONE 2026-10-10 (shell tag and its CSS removed; JOB/CO/EXP id labels removed from job, company, taxonomy and experience headers; ids stay in URLs and data attributes). |
| Delete company | Friends see Remove from my board. Deleting stays with the owner. |

## Flows

### Shared rule

The board needs three jobs as fast as possible. The number of pick rounds is three minus the jobs already on the board. Each round shows three jobs similar to the board's jobs and the user picks the one they like most. The pick lands in New and the others are not saved. Options per round is proposed. The first text used two for links and three for a profile.

### Bring jobs

1. The user pastes one or more links, or types a title, into the one field.
2. A link is normalized and checked against the user's board. A stub card appears at once. Reading, company matching and extraction fill in afterwards and never block.
3. If the job already exists in the shared records, it joins the user's board. If not, it is added to them first.
4. If the company match is ambiguous, the job still lands. The company shows as being checked, and the review card goes to the owner.
5. A title shows matching jobs. The user picks one and it lands in New.
6. If the board has fewer than three jobs, pick rounds run until it has three.
7. The board opens with suggestions of similar jobs the user can add to New.

### Bring yourself

Decision pending in M5. If it is in the first test the steps are these.

1. The user adds a CV or a LinkedIn profile, or only answers questions.
2. Experiences and Preferences are filled from it. Every filled value is labeled AI-made and can be edited.
3. A few questions fill gaps in Preferences.
4. Three pick rounds run, since the board is empty.
5. The board opens. Every job shows a fit score and a one-line reason. Score format is open.

A user who started with links can add a profile later. Fit appears on every job and the user's own order stays.

### What the user sees when

| Situation | Behavior |
|---|---|
| First visit, nothing on the board | The one field and a line saying what to paste |
| Link cannot be read, or is not a job | The job record exists. The card says reading failed, and offers retry or pasting the text. |
| The user already has the job on their board | Show it side by side with the existing card and offer to open it |
| Seed job already closed | Use it as a taste signal, say it is closed, do not count it toward three |
| Reading is still running | The card shows each field as pending. Rounds start when the seed's fields are ready. How long to wait is open. |
| Fewer similar jobs than a round needs | Show what exists. If none, say we do not have jobs like this yet and offer the feedback link. |
| Nothing in the universe fits the user | Same as above. Do not show weak matches as good ones. |
| User likes none of the options | A none of these button shows a fresh set. After two misses, offer a different starting point. |
| CV cannot be read | Offer to paste the text or answer the questions directly |
| A saved job closes or changes | Flag on the card with one line on what changed. The job stays in its column. |

## Goal and milestones

Goal. Five friends in Zurich have used CareerOS for two weeks and told us whether it is useful. This serves the Intent by testing the core of the idea before building the vault.

Each milestone is accepted when the owner clicks through a running instance. Tasks are the tickets in the tracker and are not copied here.

| Milestone | Outcome | Not in scope |
|---|---|---|
| M1 The app matches the inventory | Every item in the audit table is removed or merged, the fixed lists are settled and existing records follow them, and the inventory lists every page, action and word. A reviewer checks the inventory diff. | New features, restyling |
| M2 Friends can reach their own board | A person outside the local network signs in, adds a job and sees only their own board. Edits to shared records stay with the owner. Needs the edit model decision. | Fit, CV reading |
| M3 The universe is big enough | At least 50 companies and 50 jobs in Zurich, each with sector, size and location from the fixed lists. Verified by a count. | Other regions, the company-page watcher |
| M4 Bring jobs works for a friend | A fresh friend account pastes one link and ends with three jobs in New after two rounds. The owner may fill extracted fields and choose the round options by hand. Every manual step is written down as it happens. Needs M2 and M3. | Automating the manual steps, profile, fit |
| M5 Decision on fit and CV reading | Recorded. Either they join the first test and become a milestone, or they move to the later list. The reason is stated. Fit needs the Journey 3 spec and JOZ-267. | Building either |
| M6 Changes are visible | A job closed or changed in test data shows its flag and appears under Needs attention after the next check. | New jobs appearing on company pages |
| M7 Friends can try it | The privacy note, the feedback link and five invitations exist. | Anything beyond the five friends |

## First task brief

Status: SHIPPED 2026-10-09, merged to main via PR #4 (main 5d238b0).
Option A: Retry visible to everyone until roles land in M2. All three
buttons removed; company Retry via per-company endpoint reusing the
sector and size cascades. Two follow-up fixes rode the same branch:
LLM sector recall (ISIC letter table inlined in the prompt, runtime uses
native requests with thinking disabled) and the resolved sector
label on the company detail page (same mapping as the directory card).
Owner click-tested live; dual cross-review READY; suite 889 passed.

```
## Intent anchor
A friend opening the board should see only what they need, and the owner must not lose a way to retry a failed step. This serves milestone M1.
## Task
Merge the three enrichment buttons into one Retry control that only the owner sees.
## Reuses
The existing enrichment cascade, its signal accounting and the AI-generated badge.
## Adds
Nothing. The Retry control is the existing action under one name.
## Removes
Enrich with AI, Enrich pending and Backfill sector/size.
## Outcome
State. A failed or exhausted job and a failed or exhausted company each show one Retry for the owner and none for a friend. The owner clicks Retry on one of each and sees the state change. No other enrichment button remains.
## Not in scope
New fields, retry scheduling, changes to the fixed lists, restyling.
```

## Open questions

- Edit model for the friend test. Per-user boards with owner-only edits to shared records is proposed. The brief lists it as open.
- Which parts of M4 are done by hand, and how friends are told, if at all.
- Whether fit and CV reading join the first test, see M5.
- Merging Needs attention and Needs your input.
- Rename the Search tab to Preferences.
- Options per round, two or three.
- Format of the fit score.
- How a title is matched to shared jobs.
- How often the job-status checker runs, which sets the check cycle in M6.
- Whether the single YAML vault holds up for five users. Untested beyond about 24 jobs.
- Privacy approach, see the Frame table.
- Schemas doc update: `docs/schemas.md` predates the Journey-1 job fields
  (normalized_url, in_pipeline, origin, source_id, ingest_state, ingest_error,
  ats_provider, tenant, posting_id). Owner ruled 2026-10-11: update deferred
  to the Part 2 intake-capability rewrite, which owns the record shape.
- verify.py: the UI smoke script still clicks the removed Enrich pending and
  Enrich buttons and fails on main. Owner ruled 2026-10-11: fix folded into
  the Part 4 test audit (repair or supersede with real-backend smoke tests),
  not a side quest.

### Unconfirmed taxonomy choices

The concept draft explicitly called these proposals, not approvals. Confirm or
close them in the later audit; implementation alone is not approval. The company
kind ruling is in [Company classification](docs/decisions/company-classification.md).
The undated-count proposal was superseded in [Enrichment evidence](docs/decisions/enrichment-evidence.md).

- Draft taxonomy choice 2: Institution/removed aggregate kind behavior: adopt the field-group matrix (enrichment eligibility, directory visibility, filter participation, job-derived aggregation) in Section 1, replacing a single on/off enrichment guard; the sector/size exclusion for institutions and removed aggregate kinds covers both the top-level fields and the nested `enrichment.sectors` rollup, requiring `regenerate_company` to explicitly remove both, not merely gate them out of new aggregation, including when a company's `kind` changes after sectors were already stored. Default: yes, matrix, including the nested-rollup removal.
- Draft taxonomy choice 4: Deletion protection: block company deletion when linked experiences exist, extending the existing job-linked guard. Default: yes, block.
- Draft taxonomy choice 5: Experience write pattern: change `save_experience` to merge onto the existing stored record (like companies/jobs do today), rather than reconstructing the record from only the fields in the incoming payload. Default: yes, switch to merge.
- Draft taxonomy choice 6: Legacy form/API compatibility: because of decision 5, and because of the `sector`-to-`sectors` and `size`-to-`size_range`/`size_class` renames in Section 3, schema and allowlist changes must ship before the UI changes that depend on them; legacy `skills`-only experience payloads are translated into `tags` during a one-release overlap window, and legacy `sector`/`size` company payloads (from `company_detail.html` and `fill_company_metadata` until both are updated) are likewise translated into `sectors`/`size_range`, and into `size_class` only when a raw employee count is separately available, rather than silently dropped (a bucket-only legacy `size` string yields `size_range` but not a confident `size_class`, per Section 3); `sector`/`size` are retired from the write-allowlist only after translation, backfill, and the updated readers have all shipped. Default: yes, staged rollout with translation on both sides.
- Draft taxonomy choice 8: Company merge tool (combining two duplicate CO-### records): build now or defer. Default: defer.
- Draft taxonomy choice 9: Tag facets: adopt the five-facet model (`skill/capability`, `skill/domain`, `function`, `experience-type`, `tool`). Default: yes, all five.
- Draft taxonomy choice 10: Tag governance: open-with-review rather than a closed enum; id changes/retirement (as opposed to label-only renames) rewrite or tombstone every referencing experience AND job. Default: open-with-review.
- Draft taxonomy choice 11: Tag multilingual handling: English slug id, free-text label, optional `label_de`; German/English labels and keywords serve as LLM prompt context for function extraction at launch, with a deterministic keyword matcher deferred. Default: yes, no automatic translation.
- Draft taxonomy choice 12: External tag standard for skill/capability and skill/domain: reject ESCO/ISCO as oversized; keep a small local vocabulary. Default: reject standard.
- Draft taxonomy choice 14: Sector field shape: multi-select `sectors: [string]` replacing `sector`. Default: yes.
- Draft taxonomy choice 15: Size standard: combine EU Recommendation 2003/361/EC `size_class` (an employee-count proxy, not full SME qualification) with the existing numeric `size_range` bucket. Default: combine both.
- Draft taxonomy choice 16: Size field naming: `size_range` (renamed from `size`) plus new `size_class`. Default: yes.
- Draft taxonomy choice 17: Size precedence rule: `size_class` derived by default from the raw employee count (never from the `size_range` bucket), owner override always wins and is excluded from re-derivation. Default: yes.
- Draft taxonomy choice 18: Ambiguous employee-count ranges (e.g. "50-100"): resolve to the upper bound. Default: upper bound.
- Draft taxonomy choice 20: Sector ambiguity handling: leave `sectors` empty when one signal matches multiple ISIC sections with comparable confidence; store multiple sectors only when independent sources confidently resolve to different sections AND provide independent evidence of genuinely distinct business activities, not just differing labels for what may be the same activity, otherwise leave the conflict unresolved and flag it for owner review. Default: yes, refuse per-signal ambiguity, require distinct-activity evidence for genuine multi-sector, flag unresolved conflicts for review.
- Draft taxonomy choice 21: Source-conflict handling for sectors: no source-priority order; confidence alone never resolves a same-activity conflict between sources, so an unresolved conflict is left empty and flagged for owner review rather than accepted from whichever source was confident, consistent with decision 20. Default: no priority order, unresolved conflicts flagged for review.
- Draft taxonomy choice 22: Job function standard: adopt the ESCO-occupation-plus-derived-ISCO hybrid, with ISCO always derived from the validated concept, never stored by hand; the guarantee of an available ISCO roll-up applies only to ESCO-backed entries, not local extensions. Default: yes, hybrid, derived-not-stored, ESCO-scoped guarantee.
- Draft taxonomy choice 23: Function extraction method: LLM-only at launch, with every returned id validated against `tags.yaml` and unknown ids dropped. Default: yes, LLM-only with validation.
- Draft taxonomy choice 24: ESCO seed scope: curate a small subset grown on demand, stored as the `function` facet inside `tags.yaml`; any bulk ESCO export file is an import source only, never a second runtime registry. Default: curated subset, one registry.
- Draft taxonomy choice 25: Local function extensions (no ESCO parent, e.g. "financial product manager" pending verification): allow as owner-governed local values with a visible marker; preserved in a distinct "unmapped" bucket in any ISCO roll-up report rather than excluded from that report entirely, matching Section 4's body. Default: yes, allow with marker, unmapped bucket in roll-ups.
- Draft taxonomy choice 26: Scrollbar scope: scoped selectors plus opt-in `.scroll-thin` class, rather than a blanket `*` override. Default: scoped selectors plus opt-in class.
- Draft taxonomy choice 27: Backfill mechanism for the 11 null `sector`/`size` company records, scoped to `kind: employer`: an explicit, owner-triggered action running independent per-field cascades, since `sectors` has a zero-network aggregation-promotion tier that size does not. Default: explicit trigger, independent per-field cascades.

### React migration milestones

The React plan uses R0–R6, distinct from the product milestones M1–M7.

- R0: Toolchain and Jobs board proof — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md).
- R1: JSON API parity — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md).
- R2: Search page — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md).
- R3: Job detail — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md).
- R4: Companies and company detail — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md).
- R5: Experiences, forms and taxonomy pages — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md).
- R6: Component registry and retirement of absorbed styling work — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md).
