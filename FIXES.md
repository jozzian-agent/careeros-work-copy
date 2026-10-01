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
