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

2026-10-12: the filter bar and add-job popup were rebuilt to the design brief (JOZ-279; [sketch update](docs/surfaces/jobs.md)). The filter bar replaces the single Function select and plain Needs-attention toggle with chips for Fit, Function, Location, More filters (Industry, Company size) and Needs attention (now with a count); the first four each open a Popover or side panel, while Needs attention stays a plain toggle chip. A removable-Tag active-filters row with Clear all and a live result count sits below, and Clear all now resets Needs attention too, not only the five grouped filters. The add-job popup fills in JOZ-278's shell with the full link-field flow and its five states (ready, reading, not a link, already on your board, couldn't read with retry), wired to the existing intake endpoint; the inline "Posting URL" field it superseded is removed, so intake now lives only behind the plus button, inside the add-job popup. Industry and Company size are new client-computed facets introduced in this batch (not carried over from JOZ-278) — no backend contract change. See `frontend/BUILD_NOTES.md` "Filter bar and add-job popup rebuild (JOZ-279)" for the implementation detail.

2026-10-12: the Job, Experience, Company and Company Classification detail pages were rebuilt on a shared DetailHeader/SectionCard skeleton in React (JOZ-280; [sketch](docs/surfaces/detail-pages.md)), replacing the four Jinja pages with no coexistence — those routes now exist only behind CAREEROS_REACT_UI, with the Jinja routes, views and templates removed rather than kept as a flag-off fallback (an owner decision narrower than the Jobs board's own dual-mode cutover). Client-side routing (`react-router-dom`) was added to the SPA for this. Four edit popups and one delete confirmation, designed and owner-approved in this ticket's own Phase A (not in the original design brief), write through existing PUT/DELETE endpoints with no backend schema change; the job record's `fit` field gets its first writer (a new Fit dropdown under the Job header) through the existing generic job PUT (superseded 2026-10-15: no control writes `fit` and nothing on any surface asks for a rating until fit scoring exists, decision M0-4). Two gaps are flagged rather than silently dropped: the company-review resolution UI (picking a candidate or creating a company for a `needs_review` job) is not yet ported from the old Jinja page, and the old page's live-polling for in-progress enrichment is not carried over. Converting the many Jinja-markup-rendering tests this cutover broke moved most of their coverage to the unchanged JSON API instead of deleting it outright; see `frontend/BUILD_NOTES.md` "Detail pages rebuild (JOZ-280)" for the full accounting and implementation detail.

2026-10-13: Search (home), Experiences list and Companies list were migrated to React (JOZ-283; [sketches](docs/surfaces/experiences.md), [companies](docs/surfaces/companies.md), [search/preferences](docs/surfaces/preferences.md)), the same no-coexist cutover JOZ-280 used for the detail pages: `/`, `/experiences` and `/companies` exist only behind CAREEROS_REACT_UI, with the three Jinja templates, their views and the redundant `/search` URL removed rather than kept as a flag-off fallback. No backend API or JSON contract changed, since all three pages read the existing `view=page` endpoints unmodified. `/experiences/new`, `/experiences/<id>/edit` and the taxonomy pages are untouched. See `frontend/BUILD_NOTES.md` "List pages rebuild (JOZ-283)" for implementation detail and the test-conversion accounting.

2026-10-14: the Job and Company detail pages were realigned to the owner's canvas (package 1, [sketch update](docs/surfaces/detail-pages.md)), and the owner click-tested that build and asked for six changes, all of which are in. Five are adjustments to the two pages: the extraction popup now carries the read timestamp the row shows, the expanded Original posting carries the posting's own link, and Classification and History are collapsed accordions like Original posting and Details already were. "On both pages" for History applied only to the Job page, because a company record stores no history and giving it one is a feature rather than a collapse. The sixth is a feature: [notes](docs/surfaces/notes.md) stop being one free-text field per record and become a list of titled notes, each written in its own window, with a read-only Notes page that shows every note in the vault linked to the job or company that holds it. That is the first stored-schema change since JOZ-267: records gain `note_list`, and the legacy `notes` string is surfaced as a record's first note on read and persisted into the list on the owner's first note write, so no existing notes text is lost and no file is rewritten by a read. The legacy field stays a writable record field for one release; nothing in the interface writes it.

2026-10-14: requirements stop being two flat lists and become grouped
requirements (package 2, [sketch update](docs/surfaces/detail-pages.md)).
A job stores `requirement_groups`, a list of `{group, level, text}` over
a fixed five-group vocabulary (Education, Experience, Skills, Languages,
Certifications), where a requirement the extractor cannot place lands in
Skills, so no sixth group can appear. The extraction prompt and parser
emit the groups, and the flat must/nice lists fold in behind whatever the
model grouped, under Skills, so the field fills with or without the model
and a partial answer loses no line the posting asked for. Migration
is the owner's own per-job action and nothing else: a job written before
this round keeps its flat lists and keeps rendering them, until the owner
presses Re-extract on that job (`POST /api/jobs/<id>/re-extract`, which
reads the stored posting text and fetches nothing). Languages get their
first stored home, and with it an editor in Edit job. The `skills` field
and the Skills group overlap, and the owner's decision is to keep both,
so the Requirements section shows the group plus any stored skill the
group does not carry.

2026-10-15: the Companies list was reworked against the owner's locked
decisions ([sketch update](docs/surfaces/companies.md)). The grid is now a
real grid — equal card widths and a fixed card height, so a long ISIC
label can no longer stretch one card past its neighbours — a company name
is shown as at most 30 characters plus an ellipsis with the full name as
its tooltip, and the open-jobs chip reads "1 open job" / "N open jobs" /
"No open jobs" instead of the old always-plural badge on every company,
zero-count ones included. The two coexisting size scales are settled in
favour of the classes (see the Size fixed list below): the page shows the
class, the Jobs board's own Company size facet now reads each job's
company class over the same backend vocabulary instead of bucketing raw
employee counts in JS, and `scripts/migrate_company_size_scale.py` retires
the stored numeric ranges — dry run by default, `--apply` owner-gated and
not run as part of this build. The page also gained the Jobs board's own
FilterBar (sector, size, open jobs, a "Needs your input" toggle over any
review flag, active-filter chips, Clear all, result count, remembered in
localStorage with no URL state), which made the component's groups, count
noun and toggle label props rather than jobs-only constants. Backend:
"open" is one definition in one place (`vault.ENDED_STATUSES` /
`is_open_job`), which the count and the Open jobs filter both read.

2026-10-15: the Jobs board was reworked to the owner's status decision D7
([brief](docs/briefs/2026-10-15-jobs-board-d7.md),
[surface](docs/surfaces/jobs.md)), backend half. The statuses are now New,
Interested, Applied, Interviewing, Offer, Won, Rejected, Stopped:
Withdrawn is renamed to Stopped, and Closed stops being a status at all,
because a posting that is gone is a fact about the posting rather than the
owner's decision. It becomes a `closed` flag with a `closed_at` date, set
by the watcher's existing "posting gone" event without touching the job's
status. Open means not ended, defined once in `vault.ENDED_STATUSES` with
`vault.OPEN_STATUSES` derived from it, which the board split, the status
vocabulary and the Companies list count all read. A job also gains an
optional `end_reason` from two fixed suggestion lists (see the Fixed lists
below), whose free-text half is an ordinary dated note rather than a
second field, and a `closed_reviewed_at` marker the closed-postings review
sets when the owner keeps a job anyway. History says it in plain words:
"Status changed from Applied to Stopped", and "Stopped: Salary or
conditions" for the reason, which is its own event because a reason
arrives on its own schedule. The board payload gained the open/ended
split, the status words, the suggestion lists, the closed-postings review
list (a job before Applied whose posting has been gone over 7 days and
that has not been kept) and the "Your search so far" counts, all read from
history so an ended job still counts for the interview it got. Nothing new
was endpointed: a move, a reason and the Keep marker all go through the
existing job PUT, and the free-text note through the existing notes
endpoint. `scripts/migrate_board_d7_statuses.py` moves a stored vault onto
the list (dry run by default, `--apply` owner-gated, not run as part of
this build; [runbook](docs/runbooks/migrate-board-d7.md)). The board
layout the brief draws (five open columns, the Ended lane, the ending
chooser, the reason popup, the banner and its review popup, "Your search
so far" and the phone layout) is the frontend chunk, built the same day;
see the entry below.

2026-10-15: the Jobs board frontend was built to the owner's D7 design
brief, following the D7 canvas (claude.ai artifact 7PBPPwtEXZEmQdeNXd4b8S,
approved 2026-10-15) by its prose; the artifact was never opened by the
agent, so canvas conformance is for the owner click-test to confirm
([brief](docs/briefs/2026-10-15-jobs-board-d7.md),
[surface](docs/surfaces/jobs.md),
[components](docs/decisions/design-system.md)). The board now shows five
open columns and one pinned Ended lane that is collapsed on every load,
rather than one column per status. Ending a job is one gesture with one
flow behind it: dropping a card on the collapsed lane asks how it ended,
dropping on a group of the expanded lane picks that outcome, and the
status select offers the same three statuses under a divider, which is the
keyboard and screen-reader route. Won always asks first and never touches
another job; Rejected and Stopped move at once with Undo and an optional
reason, where a picked suggestion is the ordinary job PUT and the free text
beside it is a dated note. Skip writes nothing, so a job never waits for a
reason. The closed posting is a chip and a question rather than a column:
the card shows the neutral chip, or a warning chip with the day count for
the jobs the payload asks about, and the banner above the board offers
Review, whose popup keeps a job (a PUT of closed_reviewed_at) or stops it
with the reason "Posting closed" in one write. The Ended lane heads with
"Your search so far". The filter bar loses the Fit facet, which the brief
removes until fit is calculated, and gains a "Hide closed postings"
toggle; neither that toggle nor the lane remembers its state, by owner
decision. Below 720px the board shows one column at a time from a chip
row, nothing is draggable, and popups open as full-width sheets. No
backend contract changed: every write is the existing job PUT or the
existing notes endpoint. `frontend/tests/fixtures/board.json` was stale
(it still listed rejected, closed and withdrawn as columns) and now
carries the D7 payload, so the Playwright suite exercises the real
contract.

2026-10-16: a stability batch with no new surface (CAREER-29 to
CAREER-33), recorded here because four of the five change what the
product records rather than what it shows.

- **The job-function vocabulary is wider and pinned** (CAREER-29). The
  seed in `careeros/data/esco_occupations.yaml` grows from 28 to 31
  entries, and five existing entries gain keywords, each gap found by
  reading the owner's own stored postings: an IT/technology
  consultant, a business development or strategy manager and an
  innovation manager had no id to land in. Every `isco` is a four-digit
  ISCO-08 unit group, settled here as the level to record because a
  coarser roll-up is a prefix of it. `tests/test_function_facet.py`
  pins the full id list the way `tests/test_board_d7.py` pins the
  stopped reasons, plus one line per posting shape. The live vault's
  facet was already seeded with the 28 (2026-10-15), so the owner's
  action is one more run of the [seed runbook](docs/runbooks/seed-function-facet.md).
  Carried further the same day by the follow-up round below, which is
  what settles the ESCO identities.
- **No drop on the way into a record is silent** (CAREER-30). The
  function-id drop already said so; redaction emptying a field, a
  payload key the record does not store, and an unusable extracted
  contact address now do too — a log line in every case (naming the
  field or key, never the value), plus a `field_status_reason` on the
  record wherever `field_status` reports the field. See the drop sites
  in the [add-a-job flow](docs/flows/add-job-by-link.md).
- **The empty descriptions in the live vault are audited, not fixed**
  (CAREER-31): 8 of 44 records, what each one's own history says about
  why, and the command per record. The commissioning premise does not
  hold — none of the 8 can be pinned on the redaction defect, and two
  have a different recorded cause — and the audit says so
  ([audit](docs/audits/redaction-residue.md)). The re-read is the
  owner's action.
- **`scripts/verify.py` is retired** (CAREER-32). The UI smoke script
  drove the Jinja app, failed on main, and the two guards in it that
  still meant something (no uncaught script error, no request to any
  other origin) are now `frontend/tests/page-health.spec.js`, over
  nine routes instead of one run. What went with it is in the open
  questions below.
- **Nothing derives the retired numeric size scale any more**
  (CAREER-33). `vault.save_company` already dropped a `size_range`
  from every payload; now the capability's own derivation stops
  offering one, so the second scale is gone at both ends. This edits
  the pinned submodule, so the pin moves. One more write went with
  it: a posting's headcount was bucketed in `intake._extract` and
  stored in the company's legacy `size` field beside the class
  derived from that same count, so one signal wrote both scales under
  two field names. The count now fills the class only. A stored
  legacy `size` is still read, and an owner PUT can still set one.

2026-10-16, same day: a reviewer accepted the batch above with notes,
and the follow-up round that answers them also carries two owner
decisions. Two of the three change what the product records.

- **The function vocabulary is the golden set's, and its ESCO
  identities are citations** (CAREER-29 follow-up). The seed grows from
  31 to 40 entries. Ten of them now carry an `esco_uri` fetched from the
  live ESCO API on 2026-10-16, with the preferred label and the concept
  `code` matching what the entry records, so `isco` is the first four
  digits of a real concept's code rather than a reading of the standard.
  Four of those ten are new entries for ESCO concepts the seed had no
  home for (product manager 1223, banking products manager 1221,
  business consultant 2421, ICT business analysis manager 2511). Five
  more new entries are the owner labels whose golden-set URIs **404**:
  chief product officer, digital transformation manager, innovation
  officer, embedded systems security engineer, digital marketing
  manager. Those are choice-25 local extensions, marked `local: true`
  in the seed and `source: local-extension` in a vault, carrying no ISCO
  code at all, because choice 22 scopes the roll-up guarantee to
  ESCO-backed entries and a hand-picked code is the thing it forbids.
  Two keyword absorptions went with them: a "Security Expert" posting
  landed on ICT security manager (1330) where the golden ISCO is 2529,
  and a blanket `head of product` keyword made ICT product manager
  (1330) the only home for the top product role (1223). Re-running the
  seed is no longer a no-op either: it confirms or updates `esco_uri`,
  `isco` and the local marker on an entry a vault already holds, and
  merges in new keywords, which is what makes the extraction prompt
  (built from the vault's own facet, never from the seed file) see them.
- **A posting's headcount is kept as company size evidence** (owner
  decision). It stays on the job as the raw `employee_count`, and the
  company aggregation carries it into `enrichment.employee_count` with
  an `employee_count_evidence` record of which posting stated it and
  when. That is the zero-network tier of the capability's size cascade,
  so a company whose only size signal is one of its own postings now
  gains evidence a later size run derives `size_class` from, instead of
  the number being read once at intake and then invisible. Evidence
  toward the class and nothing else: it never overwrites a stored class,
  a count that contradicts one raises the inconsistency flag, a
  non-employer keeps none of it, and neither retired scale (`size_range`,
  the legacy `size` string) is written.
- **`careeros/web/screenshot.py` is deleted** (owner decision).
  `scripts/verify.py` was its only importer and went with CAREER-32;
  the specimen screenshots AGENTS.md's component gate asks for are an
  agent's own business, not a module this repo keeps unreferenced.

2026-10-17: the app has a door. Every page and every API call requires a
logged-in user, the admin creates accounts from the command line and
there is no public signup (M1 of the multi-user test release, goal
CAREER-39, decisions CAREER-40 D1/D2/D3 as filed; that goal's own
milestone list lives in the tracker and is not copied here, like every
other ticket). The vault stays one shared world: data ownership did not
change, so every logged-in person still sees everything, and hanging
data off the new identity is the next milestone. What this adds is a
`users/` area in the vault (one YAML per user:
[schemas](docs/schemas.md)), a `secret_key` file the session cookie is
signed with so a session survives a server restart, a `/login` page, a
logout affordance in the app header ([surface](docs/surfaces/accounts.md)), one unauthenticated health check
(`GET /api/health`), and the gate itself, which is one `before_request`:
an API call without a session gets `401 {"error": "login required"}` and
nothing else, a page request gets a redirect to `/login`
([contracts](docs/surfaces/json-api.md)). Accounts are created, listed,
reset, disabled and enabled with `python -m careeros.users`, because the
first admin cannot sign in to create themselves; a web UI for user
management is not in this milestone. Two limits are accepted rather than
solved, for a test of five people: no CSRF token beyond what
`SameSite=Lax` plus same-origin JSON gives, and no rate limiting on the
login endpoint. Vocabulary: the Roles table below calls the two roles
Owner and Friend, while the stored fixed list is `admin` and `tester`;
the mapping is in that table, and the owner decided 2026-10-17 to keep
both: the stored names stay as they are.

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

| Role | Stored as | Can do |
|---|---|---|
| Owner | `admin` | Everything, including editing jobs and companies, resolving review cards and retrying enrichment. Creates every account from the command line. |
| Friend | `tester` | Add jobs, manage their own board and preferences, send feedback |

The stored ids are the fixed list below, set on a user record from M1,
2026-10-17. Nothing reads the role yet: the gate asks whether there is a
user and never which kind, because the vault is still one shared world.
Which of the two words to keep is an open question.

### Concepts

| Word | Meaning | Replaces |
|---|---|---|
| Job | One posting | position, posting, opportunity, role |
| Company | One real organisation, never split by country | none |
| Experience | A position the user held | none |
| Preferences | The user's roles, must-haves, nice-to-haves and avoid lists. Tab is called Search today, rename proposed. | Search |
| Board | The user's jobs grouped by status. In the data this is the in-pipeline flag, which must become per user. | none |
| Needs attention | A filter showing every job with a reason, closed, changed or needs your input. Proposed merge of two existing ideas. | Needs your input as a separate indicator |
| Note | One thing the user wants to remember about one job or one company: a title and a body. A record holds any number of them. | The single notes field per record |
| User | One person with an account: an email, a name, a role and a password nobody stores in the clear. Added M1, 2026-10-17. | none |
| Session | Being logged in. One signed cookie holding one user id, re-checked against the record on every request. Added M1, 2026-10-17. | none |

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

Settled by owner decision D7, 2026-10-15, and in force in the data
(`vault.STATUSES`, in this order). Closed, Changed and Needs your input
are facts or open questions about a job, so they are flags on the record
and never statuses: a closed posting is the `closed` flag with its
`closed_at` date. The board shows New to Offer as columns, and Won,
Rejected and Stopped sit together in one Ended lane that is collapsed on
every load, built 2026-10-15.

Reading state is a second, independent status on a job record, added
2026-10-17 with async enrichment (CAREER-36/37). Fixed values: absent
(never tried), `queued`, `running`, `done`, `failed` (`ai_status`, with
`ai_error` as a visible reason and `ai_started` / `ai_finished`
timestamps). It describes the machine reading of a posting, never the
owner decision, so the two never overwrite each other. On startup a
sweep settles any record left `queued` or `running` by a crashed process
as `failed` with reason "interrupted by server restart", so no zombie
state survives a restart.

### Surfaces

| Surface | Flow step |
|---|---|
| Jobs, as board and as list | Board |
| Job | Reading a job, flags |
| Companies | Company browse |
| Company | Company browse |
| Experiences | Bring yourself |
| Preferences | Bring yourself |
| Notes | Reading a job, company browse; every note in one place, each linked to its record ([surface](docs/surfaces/notes.md)) |
| Log in | The way into every other surface. Email, password, one message for a refused attempt. Added M1, 2026-10-17 ([surface](docs/surfaces/accounts.md), [contracts](docs/surfaces/json-api.md)) |
| JSON page views, taxonomy and experience forms | Existing page flows for the React migration; [contracts and inventory](docs/surfaces/json-api.md) |
| Accounts command line | Creating, listing, resetting, disabling and enabling an account, since the first admin cannot sign in to create themselves. Added M1, 2026-10-17 ([surface](docs/surfaces/accounts.md), [schemas](docs/schemas.md)) |
| Health check | `GET /api/health`, the one unauthenticated read: is the process up. Added M1, 2026-10-17 ([surface](docs/surfaces/accounts.md)) |

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
| Add a note | The Notes section of a job or a company, in its own window | Everyone |
| Re-extract | The extraction row on a job, enabled once posting text exists | Owner |
| Send feedback | One link in the footer | Everyone |
| Log in | The Log in page | Everyone |
| Log out | One affordance in the app header | Everyone |
| Create, reset, disable or enable an account | `python -m careeros.users` | Owner |

Friends never delete jobs or companies. Only the owner edits shared records.

### Fixed lists

- Role. `admin`, `tester` (`careeros.users.ROLES`), stored on a user
  record. Settled by the M1 brief, 2026-10-17: one admin role and up to
  five tester accounts, which is the friend test's own number. The five
  is the plan and not a rule the code enforces
  (`careeros.users.TESTER_PLAN`): refusing a sixth account would be a
  refusal the brief does not ask for. A new account is a tester unless
  `--role admin` is asked for, so an admin is never created by leaving an
  argument out. Whether an account is off is the separate `disabled`
  boolean on the same record, which is the admin's decision and ends that
  account's session on its next request.
- Requirement group. Education, Experience, Skills, Languages,
  Certifications. Settled by owner decision 2026-10-14; a requirement the
  extractor cannot place goes to Skills, and no free-form group exists.
  Stored as the lower-case id on `requirement_groups`
  ([schemas](docs/schemas.md)); the five words above are the labels the
  interface shows.
- Requirement level. Must have, nice to have. Stored as `must` and
  `nice`; a requirement with no stated level is a must-have, since a
  posting insists unless it says otherwise.
- Company size. Micro, Small, Medium, Large, by headcount (micro up to
  10, small up to 50, medium up to 250, above that large — the
  `org_intake.classify` thresholds), stored as `size_class` over
  `vault.SIZE_CLASSES`. Settled by owner decision 2026-10-15: the class
  is the ONLY size scale, so the numeric `size_range` the intake cascade
  used to derive as well is retired by `scripts/migrate_company_size_scale.py` (dry
  run by default, `--apply` owner-gated) and every surface shows the
  class. Where a record still carries both, the class wins. No product
  write persists a range any more either: `vault.save_company` drops one
  from every payload (M0-7), so only a record written before that still
  carries one, and only an explicit clear is let through. Nothing
  derives one for writing any more either (CAREER-33, 2026-10-16):
  `org_intake.classify.derive_size` and the size cascade answer with the
  class alone, and only read a stored range to check evidence against
  it. That edit is in the capability working tree and moves the pin. The
  legacy `size` string is read-only from the same date: a posting's
  headcount fills the class and no longer also fills `size` from a
  bucket derived from that same count. An owner PUT can still set one.
  The headcount itself is kept rather than dropped (owner decision
  2026-10-16): it stays on the job as `employee_count` and is
  aggregated onto the company as `enrichment.employee_count`, with
  `enrichment.employee_count_evidence` naming the posting it came
  from, which is evidence the size cascade's zero-network tier can
  derive the class from. Evidence only: the fill-empty-only and
  conflict-flag rules are unchanged and no retired scale is written.
- Job statuses that end a job. Won, rejected, stopped
  (`vault.ENDED_STATUSES`, owner decision D7 2026-10-15). A job in any
  other status is open, which is what `vault.OPEN_STATUSES` is derived
  from and what the board's open/ended split and the Companies list count
  and filter on.
- Reason a job ended. Optional, picked never typed, and stored verbatim as
  `end_reason`. Stopped: Not interested anymore, Salary or conditions,
  Location or commute, Took another offer, Withdrew application, Posting
  closed, No response. Rejected: No reason given, After interview,
  Experience did not match, Position filled (`vault.STOPPED_REASONS`,
  `vault.REJECTED_REASONS`).
  Won has none. Free text the owner adds beside a reason is a dated note
  on the job, under `vault.END_NOTE_TITLE`, not a second field.

### Fixed lists, to settle in milestone M1

- Sector. Stored as ISIC, on purpose, so that Journey 3 can use standard codes. Show plain labels only if friends find the names confusing.
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
| Notes appear twice on the company page | One notes field. DONE 2026-10-09 (read-only markdown card removed; the editable textarea is the one field). Superseded 2026-10-14 by the owner round: notes are a list of titled notes with one window and one Notes page, so there is one notes surface rather than one field. |
| Opportunities, Experience, Posting URL | Jobs, Experiences, Add a job by link or title. DONE 2026-10-10 (company page headings renamed; intake label renamed); the inline Posting URL field itself was later removed, so intake now lives only in the add-job popup opened from the plus button (JOZ-279). |
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
- No browser check runs against the real backend, and none runs against
  the built front end either. `scripts/verify.py` was the only one and is
  gone (CAREER-32, 2026-10-16, see the entry above). The Playwright suite
  drives the **Vite dev server** (`playwright.config.js` starts
  `npm run dev`) with every API response mocked, and the pytest suites
  drive the real handlers with no browser. So the gap is wider than
  "no real backend": the bundle Flask actually serves (`frontend/dist`,
  built by `npm run build`) is never loaded by any automated check, so a
  break that only appears in a production build — a dependency missing
  from the bundle, a path that resolves only through the dev server — is
  invisible too. The owner click-test is what covers both. Whether that
  is worth a second Playwright project serving `frontend/dist` from Flask
  over a sample vault is open; the 2026-10-11 ruling folded it into
  "repair or supersede with real-backend smoke tests" and the repair half
  is now settled.

### Unconfirmed taxonomy choices

The concept draft explicitly called these proposals, not approvals. Confirm or
close them in the later audit; implementation alone is not approval. The company
kind ruling is in [Company classification](docs/decisions/company-classification.md).
The undated-count proposal was superseded in [Enrichment evidence](docs/decisions/enrichment-evidence.md).

**2026-10-16: choices 22, 23, 24 and 25 are confirmed by the owner** through the
golden-set labelling of the live vault (42 jobs, LLM-assisted with per-row
confidence, runner-up and note). The standing labelling approach: LLM-assisted
rows carrying confidence, runner-up and note, and **every ESCO URI validated
against the live ESCO API before it enters the vocabulary** — validation of the
labelled file found 5 of 15 distinct URIs fabricated by the labelling model
(digital transformation manager, chief product officer, innovation officer,
embedded systems security engineer, digital marketing manager); those labels are
recorded as choice-25 local extensions with a visible marker, never as
ESCO-backed entries. The 10 verified URIs seed the `function` facet. Golden set:
`/root/careeros-golden-set/golden-set-2026-10-16.csv`; rows at or below ~35%
confidence are scored separately by the M1 harness.

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
- R2: Search page — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md). Search page itself done 2026-10-13 (JOZ-283).
- R3: Job detail — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md).
- R4: Companies and company detail — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md). Company detail done 2026-10-12 (JOZ-280); Companies list done 2026-10-13 (JOZ-283).
- R5: Experiences, forms and taxonomy pages — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md). Experience detail done 2026-10-12 (JOZ-280); Experiences list done 2026-10-13 (JOZ-283). Forms and taxonomy pages stay Jinja, out of scope for both tickets.
- R6: Component registry and retirement of absorbed styling work — [external plan](../careeros-dashboard-plans/2026-10-10_gestalt-react-frontend.md).
