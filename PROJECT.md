# CareerOS

Method lives in AGENTS.md. This file holds what is specific to CareerOS. Items marked proposed have not been approved. Revised 2026-10-09 after the status brief.

## Intent

Job seekers get stuck on job sites. Postings are stale, suggestions are off target, nothing says whether you fit, and there is no place to track what you pursue. CareerOS gives them jobs they actually like, a board to track them, and later a detailed picture of their background that explains why a job fits and writes the CV.

## Where we are

As of 2026-10-09 the product is a personal tool for one owner. It runs on the owner's hardware, is reachable on the local network only, and has no multi-user support. Journey 1 steps 1 to 4 are shipped, which are URL normalizing, hard duplicate check, instant stub and company resolution. Steps 5 to 8 are open as JOZ-267 and JOZ-268. The Journey 1 spec and the ticket tracker are the source for status. This file does not copy them.

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
| Expensive decisions | Gestalt as design system with blue and purple. Companies stay a top-level tab. Universe is a backend word and never appears in the interface. The edit model is per-user boards with the owner editing shared records. Proposed. |
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

Interviews is removed from the navigation until it exists. Tab order is Jobs, Companies, Experiences, Preferences. Proposed.

### Actions

| Action | Where it lives | Who |
|---|---|---|
| Add a job by link or title | One field on Jobs | Everyone |
| Change a job's status | One control on the card | Everyone |
| Retry | On the card or company, visible after a failed or exhausted step | Owner |
| Resolve a company match | The review card | Owner |
| Remove from my board | On the card | Everyone |
| Edit preferences | One edit mode on Preferences | Everyone |
| Add an experience | Experiences | Everyone |
| Send feedback | One link in the footer | Everyone |

Friends never delete jobs or companies. Only the owner edits shared records.

### Fixed lists, to settle in milestone M1

- Sector. Stored as ISIC, on purpose, so that Journey 3 can use standard codes. Show plain labels only if friends find the names confusing.
- Size. Check whether Small, Medium, Large and 1000+ come from one scale. If not, define one by headcount.
- Location. One format. The prototype shows the same place written several ways.
- Function. The filter exists, its values go in this list.

### Design system

Gestalt, React, with blue and purple replacing the default red. Component inventory to record before the first polish round.

## What the audit says to remove or merge

| Found in the prototype | Do this |
|---|---|
| Enrich with AI, Enrich pending, Backfill sector/size | One Retry, owner only. Enrichment already starts on ingest. Retry scheduling stays out of scope. DONE 2026-10-09 (visible to everyone until M2 roles). |
| Status shown as filter pills, columns, card dropdown and a Board and List switch | Columns are the filter. One control per card. Keep Function and add Needs attention. DONE 2026-10-09 (pills removed; Needs attention toggle added; Function kept; Board/List switch kept per owner decision A). |
| Notes appear twice on the company page | One notes field. DONE 2026-10-09 (read-only markdown card removed; the editable textarea is the one field). |
| Opportunities, Experience, Posting URL | Jobs, Experiences, Add a job by link or title |
| Custom fields JSON on the company | Check what reads it, then delete if nothing does. DONE 2026-10-09 (nothing rendered it; form control removed, stored data preserved on every company write path). |
| Interviews tab, the taxonomy sub-page text, an empty Updated line | Delete until the feature exists. Interviews tab and the empty Updated line DONE 2026-10-09 (nav entry, route, and page deleted; Updated span removed from Search). The taxonomy sub-page text stays: those pages exist. |
| Five Edit buttons on Search | One edit mode |
| AI summary, AI responsibilities and original description on a job | Show the AI version, collapse the original under the source |
| Chunk 4, JOB and CO identifiers | Delete from the interface |
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
LLM sector recall (ISIC letter table inlined in the prompt, model is
now qwen3:30b-a3b with native think:false) and the resolved sector
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
