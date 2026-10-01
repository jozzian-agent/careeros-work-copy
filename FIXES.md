# Chunk 0 deviations and assumptions

- The brief does not enumerate the vault layout. The synthetic scaffold uses
  `search/`, `experiences/`, `jobs/`, `companies/`, and `interviews/`. No real vault
  was inspected. These directories are empty as requested; README includes the
  recreation command because Git cannot retain empty directories.
- Package-index DNS is unavailable in the execution environment. Dependencies
  were installed into the newly created `.venv` from cached pip wheel archives,
  then pinned with `pip freeze`. No host Python packages were modified.
- The inherited fixed-width viewport was adapted to a responsive viewport and
  wrapping navigation for LAN viewing on smaller screens. The complete CSS_VARS
  palette and generic base styles are preserved; domain-specific helpers and
  selectors were removed. The generic screenshot helper remains unchanged.
- Full live verification was attempted but cannot complete in this sandbox:
  creating an IPv4 socket raises `PermissionError: [Errno 1] Operation not
  permitted`, so Flask exits before binding port 8788. Curl was attempted for
  all six routes and each failed to connect. Chromium revision 1228 is present
  but its launch is also denied by the sandbox; all five screenshot attempts
  failed. No PNGs were produced, and no verification server remains running.
  `/tmp/careeros-chunk0/` contains five rendered HTML pages and
  `verification.txt` recording the failures. The test-client suite passes all
  11 tests. Run the documented verification script in an environment permitting
  sockets and Chromium to complete visual review.

# Chunk 1 deviations and verification

- Extended the accepted shell without redesigning its palette or navigation.
  Removed inherited Google Fonts requests to meet the zero-external-network
  dependency constraint; existing local fallback font stacks remain in use.
- Filenames append the allocated ID to the company/title slug to prevent two
  positions with identical employer/title text from overwriting one another.
  Allocation uses the largest currently stored ID plus one. Writes are atomic,
  and API mutations are serialized within the single server process.
- Salary is shown in the shared form as a read-only file-managed field. API
  creation always writes null; edits preserve the existing file value. This
  enforces the brief's tier-3 file-only requirement. All three invented sample
  positions have null salary.
- The original 11 shell tests remain and pass. Their route fixture now uses an
  empty temporary vault so the empty-state contract remains meaningful with the
  newly populated sample vault. Added 15 test cases for Chunk 1 (26 total).
- Full verification was attempted using `.venv/bin/python scripts/verify.py`.
  All 26 pytest tests passed. The sandbox then rejected IPv4 socket creation
  with `PermissionError: [Errno 1] Operation not permitted`, before a server
  could bind :8788. Live curl/API checks and Chromium screenshots could not run;
  no screenshot PNGs were produced and no verification server was started.
  `/tmp/careeros-chunk1/verification.txt` records the failure.
- `scripts/verify.py` is the host-side fallback: it reruns all tests, boots
  :8788 with `--vault sample/vault`, curls every page route and JSON API,
  exercises criteria save and experience CRUD, checks browser add/edit/delete,
  and captures search view/edit, experience list/detail/new form, plus mobile
  search into `/tmp/careeros-chunk1/`. It restores synthetic YAML bytes and
  stops its server in a finally block. The orchestrator must run it outside
  this sandbox to complete live and visual verification. Work stops here as
  requested by the brief.
- No real vault was accessed, and no commit or push was made.

# Chunk 3 — job intake, company profiles, jobs board

- Built atomic YAML job/company storage and ID allocation; mocked-fetch-friendly
  posting intake with URL fallback, naive metadata/salary/location extraction,
  and case-insensitive company reuse. Added job CRUD/status APIs and company
  read/update APIs, a filtered board with optimistic intake and styled toasts,
  job detail/status/notes editing, and editable company profiles with linked jobs.
  Reused the Linear-dark controls and safe Markdown renderer; shell is Chunk 3.
- Added two synthetic companies and four jobs across four statuses, including
  a public salary disclosure and a pending-enrichment job. Experience salaries
  remain null. Updated schemas, API documentation, and README chunk status.
- Verification: **65 tests passed (26 previous + 39 new)**. Tests cover every new
  page/API route, CRUD/status transitions, validation, storage round-trips and
  IDs, malformed YAML tolerance, mocked intake success/failure/dedupe, extraction,
  salary badges, safe Markdown, and the no-new-host-vault-path check. Every intake
  test replaces the fetch hook; no test reaches the network. Python compilation
  of the changed backend and host verification script also passed.
- Rendered and inspected `/jobs`, `/jobs/JOB-001`, `/companies`, and
  `/companies/CO-001` using the Flask test client. HTML and inspection notes are
  in `/tmp/careeros-chunk3-html/`. Checked headings, navigation, company/job links,
  details, badges, editors, status options, and shared styles.
- Sandbox-blocked verification: listening sockets, real network intake, and
  Chromium/screenshots were not attempted, as instructed. Extended
  `scripts/verify.py` for host execution on :8788 with `--vault sample/vault`,
  curl coverage of every new page/API, real direct-employer intake from Mozilla's
  careers page, job/profile mutations, browser filters and editors, and desktop
  plus mobile screenshots in `/tmp/careeros-chunk3/`. It restores exact sample
  YAML bytes and removes temporary intake records in its finally block.
- Implementation choices/deviations: domain extraction is a best-effort suffix
  heuristic (including common multipart suffixes), not a full public-suffix
  database. Fetches cap HTML at two megabytes. No original company URL is guessed
  from an ATS URL; it remains nullable/editable through the API. Open-job counts
  exclude rejected, closed, and withdrawn statuses. GET company collection/detail
  APIs were added to support inspection and host verification. No other scope
  deviations. No real vault access, commit, or push.

# Chunk 3 fix round

- Finding 1: resolve posting hosts with `socket.getaddrinfo` before fetching
  and reject any private, loopback, link-local, multicast, reserved, or
  unspecified address, including mixed public/private DNS results. Disable
  redirects and environment proxies. Regression tests mock DNS and openers;
  the autouse fetcher guard remains and the default opener is also blocked.
- Finding 2: replace the job detail field dump with escaped title, location,
  source, posted date, and added date. Reuse the existing row/chip styles for
  remote, status, salary disclosure, and pending enrichment. Preserve posting
  links, status selection, notes editing, and rendered Markdown.
- Finding 3: enforce a 15-second caller deadline with a bounded queue wait and
  monotonic checks around chunked reads, retaining the two-megabyte cap and
  socket timeout. The daemon worker owns and closes its response; a blocked
  operation may finish after the caller times out. A mocked slow-stream test
  verifies TimeoutError and successful URL-only job creation through the API.
- Finding 4: add `novalidate` to intake while retaining the URL input type and
  existing server validation/styled error toast.
- Finding 5: give all four sample jobs distinct notes about their actual roles,
  including platform scope/compensation, developer tooling, backend design,
  and management interview preparation.
- TDD: observed all 12 new regression cases fail before implementation. Full
  verification: `.venv/bin/python -m pytest -q` — **77 passed**. No real network
  was used, no vault outside sample/vault was accessed (tests use temporary
  copies), and no commit or push was made.

# Chunk 3.5

- ATS extraction now prioritizes JSON-LD JobPosting objects, arrays and @graph,
  then employer metadata and known platform slug fallbacks. Added all requested
  ATS labels, jobs.ch employer handling, validated employer website hints,
  structured location/date/employment/expiry fields, and Swiss salary separators.
  ATS posting URLs are retained in both url and original_url. Unknown employers
  leave company_id null instead of creating an invalid empty company record.
- Jobs now render eight ordered kanban columns with counts and a sortable dense
  list. Board/List preference persists in localStorage; status filters apply to
  both views. Mobile boards scroll internally and list rows stack. Cards show
  employer, source, salary disclosure and added date using existing house styles.
- Added locked POST enrichment with guarded fetching, empty/default metadata
  merging, owner-field preservation, employer dedupe and shared-profile handling.
  Failures return 422 without writes. Detail Enrich and sequential visible-pending
  bulk enrichment provide feedback and refresh the views.
- Added synthetic Personio and jobs.ch sample jobs and employer profiles through
  vault.py. Updated schema semantics and the host verification script for view
  persistence, sorting, mobile layout and enrichment controls.
- Validation: `.venv/bin/python -m pytest -q` — **105 passed**, fully offline;
  `scripts/verify.py` compiles successfully. Existing SSRF, redirect, deadline and
  no-network fixture tests remain enforced. Added regression cases cover all ATS
  platforms, schema shapes/precedence, salary variants, missing employers,
  enrichment failure/merge, company reconciliation and view markup.
- Deviations/clarifications: existing nonempty titles are always preserved because
  title provenance is unavailable. Matching employer records take precedence over
  in-place renames to prevent duplicates. Employment type and valid-through hints
  are persisted as optional strings. Socket-based host verification was not run
  in the builder sandbox; its enrichment UI flows use browser response stubs,
  while offline API tests cover actual persistence. Removed the previous external
  live-fetch verification step. No commits/pushes or personal-vault access.

## Chunk 3.5 fix round

- **Finding 1:** Added validated company `name_source` provenance. Intake and enrichment creations set `auto`; every company PUT forces `owner`, even when changing unrelated fields. Missing provenance is treated as owner-controlled. Owner names and links are preserved, with websites filled only when empty; matching profiles also use fill-only website updates. Synthetic sample companies declare `auto`. Tests cover automatic rename/dedupe, owner edits, both website branches, unrelated PUTs, and legacy records.
- **Finding 2:** Salary fields are eligible for filling only before the first successful enrichment. Repeat enrichment preserves explicit false/empty salary decisions while other empty metadata remains fillable.
- **Finding 3:** URL checking, fetching and extraction run outside the mutation lock. Reconciliation reloads the current job and saves under the lock. A lock spy verifies fetch-outside/save-inside behavior. Concurrent edits are preserved; deletion returns 404 and a changed posting URL returns 409 without applying stale extraction.
- **Finding 4:** Mobile list view hides the table header and provides a labelled Sort by selector with ascending/descending options. It shares the desktop sort function and delegated event handling, including after refresh. Rendered HTML tests retain desktop headers; browser verification now checks responsive visibility and mobile ordering.
- **Finding 5:** Collect all JSON-LD JobPosting candidates and prefer request URL/path matches in `url` or `mainEntityOfPage` (including object references), otherwise use the first candidate. Tests place the matching posting both first and second; single-node coverage remains intact.
- **Finding 6:** Salary extraction accepts trailing currency ranges, including `95,000-110,000 CHF` and `120k-150k USD`. Tests retain prefixed CHF and reject ordinary experience numbers and product prices.
- **Validation:** Findings 1–3 had failing regression tests before implementation (six parametrized failures: four provenance cases, salary preservation, and lock placement). Final host-side `.venv/bin/python -m pytest -q`: **129 passed**. The autouse offline fixture and fetch-path SSRF guards remain intact. `git diff --check` passes. Schema documentation covers provenance and salary fill semantics.
- **Deviations / environment limit:** `scripts/verify.py` was attempted; its then-current pytest run passed **123 tests**, but the sandbox rejected `socket.socket()` with `PermissionError: [Errno 1] Operation not permitted` before the localhost server could start. Therefore API/browser verification cannot be claimed as passing here; rerun `.venv/bin/python scripts/verify.py` on a host allowing localhost sockets. No approval escalation is available. The 404/409 race handling and preservation of owner-linked companies are defensive consequences of moving fetch outside the lock and respecting owner provenance. No commit or push; no real vault accessed.

## Chunk 3.5b (delete + company extraction)

- Added atomic company-file deletion with an unknown-ID ValueError and DELETE
  /api/companies/<id>. The server checks all linked jobs under the write lock;
  linked companies return 409 with count and "Still linked to N jobs".
  No jobs are cascade-deleted.
- Added red Delete job / Delete company buttons on detail pages, with native
  confirm(), error toasts, and navigation back to the collection after success.
  Lists/board cards have no delete controls. Experience detail already had a
  confirmation dialog and working delete flow, so it was preserved.
- JSON-LD company extraction now carries industry to sector, numberOfEmployees
  (including QuantitativeValue.value) to size buckets, and jobLocation locality,
  region, and country to job location and company locations. Intake and enrich
  fill empty company metadata only; nonempty values and existing name_source
  reconciliation rules are preserved. Documented sources and semantics.
- Extended verify.py with a throwaway intake-fallback company/API delete round
  trip and browser checks for cancellation, linked-company feedback, and
  successful job/company deletion. Its child server uses verification-only
  mocked DNS and blocked fetching to keep that round trip offline. Production
  SSRF code and the pytest autouse no-network fixture are unchanged.
- TDD: new tests first produced 19 failures / 105 passes in test_jobs.py.
  After implementation the full suite passed: **151 passed** (22 added).
  verify.py also completed its 151-test phase successfully. git diff --check
  passed.
- Deviations / verification limitation: this execution sandbox prohibits socket
  creation (PermissionError: [Errno 1] Operation not permitted), so verify.py
  stopped at its port-availability check before starting the server. Live curl
  and browser checks could not run here and still require a host-side run of
  .venv/bin/python scripts/verify.py. The shared boundary 1000 is assigned to
  201-1000; 1000+ means values above 1000. Organization address does not override
  the explicitly requested jobLocation source.
- No commit or push. No external/owner vault was accessed; application
  verification targets sample/vault and pytest uses isolated fixture copies.

## Chunk 4 (watcher)

- Added posting scans, normalized SHA-256 baselines, immediate HTTP 404/410
  removal detection, three-consecutive-error escalation, recovery counters,
  gone-job skipping and reactivation on a real status change into a watched
  status. Salary discovery fills only empty salary fields. Atomic watcher
  writes append history and persist watch metadata under `watch`.
- Added automatic created/status_changed/note_added/first-enriched history;
  legacy records gain no invented events. API payloads cannot replace history
  or watch metadata. Detail pages show escaped, newest-first muted timelines
  and a Check posting button with inline results and no reload.
- Added all-job and single-job POST /api/watch/scan, plus the silent-unless-news
  CLI with job IDs, single-line Telegram output and byte-preserving dry runs.
  Fetches use the unchanged intake SSRF guard outside the write lock; records
  are reloaded and mutated inside it. Concurrent deletion, URL/status changes,
  and newer scan results discard stale fetch results. Owner edits survive.
  Server mutations and CLI scans share directory flock locking across processes
  plus thread locking; dry runs create no lock files.
- Synthetic sample jobs now have explicit seed-created events; JOB-001 has a
  stale demo content hash. Moved the existing autouse offline fixture into
  conftest.py so it covers the whole suite. Added 29 watcher/history tests,
  including error escalation, recovery, salary preservation, dry-run bytes,
  CLI output, legacy records, API targeting, races and lock placement.
- TDD: watcher tests first failed at collection because the module did not
  exist; subsequent runs exposed missing timeline/button rendering before those
  were implemented. Final `.venv/bin/python -m pytest -q`: **180 passed**
  (151 existing + 29 new). `scripts/verify.py` also passed its 180-test phase,
  then failed at socket creation with `PermissionError: Operation not permitted`
  before starting any server. Live API/browser verification therefore remains
  unverified and requires the orchestrator's host run with port 8788 free.
  Extended that script to check timeline rendering and click Check posting;
  verification-only DNS maps sample hosts to loopback so the real SSRF guard
  deterministically rejects them, while disposable intake retains its offline
  fallback. Production intake code is unchanged. `git diff --check` passes.
- Brief clarifications/deviations: retained existing `url`, `salary_info`, and
  `salary_note` schema rather than introducing duplicate posting/salary fields
  (`url` is the sole posting URL field). `watch_started` is
  persisted in history but excluded from returned notification events and CLI
  stdout. The fetch default is resolved at call time for offline injection.
  Optional keyword arguments support single-job scans and the server lock;
  single-job responses add watch_status so transient errors can render inline
  without generating cron news. HTTP errors other than 404/410 follow retry
  escalation. No other scope deviations. Live verification is blocked as above.
- No commit or push, no processes killed or stopped, and no access to
  /root/career-os. Tree intentionally left dirty for owner review.


## Chunk 4 fix round

- Addressed all six cross-review findings. Hash version 2 uses canonical title,
  company, location, posted date, salary text, and whitespace-normalized
  description. Structured JobPosting data is isolated before intake extraction
  so ads and page chrome cannot contaminate salary/location fallbacks. Comments,
  scripts, and styles do not contribute description text. Existing unversioned
  or version-1 baselines migrate silently, without `posting_changed` events.
- History appends retain the newest 50 entries. Nested acquisition of the same
  WriteLock raises the requested RuntimeError before opening another descriptor;
  the outer lock stays held and the instance remains reusable after release.
- Ineligible single-job scans return `not_watched` with the requested reason.
  The detail page disables the button with that reason as its tooltip; client
  responses show the reason inline. Check posting now sits beside Enrich in
  the summary action row. Results with events reload to refresh history, while
  unchanged/not-watched/error results stay inline. The header reads the shared
  `careeros.CHUNK` constant, currently `Chunk 4`.
- Removed the nonexistent `posting_url` fallback and corrected the original
  Chunk 4 deviation note above.
- TDD: added 15 offline regression cases, observed failures before implementing
  the behavior fixes, then ran the full suite: **195 passed**. Client behavior
  tests execute the rendered handler in Node with mocked DOM/API objects and
  no networking. `git diff --check` passes. The existing suite-wide offline
  fixture and production SSRF guard are unchanged. Fetch/extraction remain
  outside the write lock; reload and mutation remain inside it.
- Verification: the orchestrator's earlier host-side `scripts/verify.py` run
  already passed, as recorded in tmp-fix5.md. This round did not start a server
  or rerun that script against the owner's occupied port 8788; the updated-tree
  host-side verification remains assigned to the orchestrator.
- Deviations: intake does not expose a description field, so the watcher reuses
  its Posting parser and JobPosting selection before calling `intake.extract`.
  Pages without structured JobPosting data use cleaned visible text, removing
  common chrome containers and relative “posted N hours ago” timestamps. This
  fallback cannot identify every site's arbitrary chrome markup. No change to
  the intake/SSRF implementation was needed. Node is required for the three
  isolated client-handler tests.
- No commit/push, no processes killed, and no access to /root/career-os. Existing
  owner changes are preserved and the tree is intentionally left dirty.
