# CareerOS

CareerOS is a personal job-search dashboard for saving postings, tracking jobs,
reviewing companies, and maintaining experiences and search preferences. Records
live in a YAML vault. The current app is for one owner; the friend test is planned
in [PROJECT.md](PROJECT.md).

## Run

Use Python 3.11 and a local virtual environment. The sample vault contains
fictional records; use it for development rather than personal data.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
CAREEROS_REACT_UI=0 .venv/bin/python -m careeros.server --vault sample/vault
```

Open the address printed by Flask, then go to `/jobs`. Stop with Ctrl-C.
`--vault PATH` takes precedence over `CAREEROS_VAULT`; pass it explicitly to
select the intended data. Missing or empty vaults are supported.

To use the React Jobs board, build its assets with Node and npm first:

```bash
npm --prefix frontend ci
npm --prefix frontend run build
CAREEROS_REACT_UI=1 .venv/bin/python -m careeros.server --vault sample/vault
```

The flag selects React for Jobs when the build exists. Other pages still use
Jinja. Build output stays out of Git. See the [frontend guide](frontend/README.md)
for frontend development and browser checks.

## Documentation

- [Flows](docs/flows/): user journeys, starting with adding a job by link.
- [Surfaces](docs/surfaces/): screens, API contracts and approval artifacts.
- [Decisions](docs/decisions/): recorded choices and their consequences.
- [Learnings](docs/learnings.md): dated findings carried forward from real work.
- [Documentation index](docs/index.md): remaining schema and implementation docs.
- [PROJECT.md](PROJECT.md): intent, inventory, milestones and open questions.

## Environment limits

Run one server process per vault: pending enrichment is process-local. Extraction
needs runtime `LLM_BASE_URL` and `LLM_MODEL` configuration; without it, usable
posting text can reach a visible extraction failure. JavaScript-only and protected
postings may not yield readable content through the plain HTTP fetcher.

Browser verification needs Node, an installed Chromium executable, and an
environment that permits local sockets and browser launch. Earlier restricted
builders could run Flask test-client tests but could not perform live browser
checks; that is not a claim that this host has the same restriction.

```bash
.venv/bin/python -m pytest tests/ -q
```

Tests use temporary fixture vaults. The existing `scripts/verify.py` provides
additional live checks, but contains a stale enrichment-button step; it is not a
complete current acceptance checklist. Live checks are recorded with each surface.
