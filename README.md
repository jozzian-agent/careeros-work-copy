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
git submodule update --init
.venv/bin/python - <<'PY'
from pathlib import Path
import sysconfig
package_root = Path('vendor/capa-repo').resolve()
pth = Path(sysconfig.get_path('purelib')) / 'org_intake_vendor.pth'
pth.write_text(str(package_root) + '\n')
PY
CAREEROS_REACT_UI=0 .venv/bin/python -m careeros.server --vault sample/vault
```

After cloning, initialize the pinned capability submodule and register its path
in the product venv with the commands above. Repeat the path registration if
the checkout moves or the venv is recreated.

Every page and every API call needs a logged-in user, and there is no public
signup, so create an account before starting the server. The first admin
cannot sign in to create themselves, so accounts are managed from the command
line. An account is a real credential, so put it in a personal vault outside
the repository rather than in `sample/vault`:

```bash
export CAREEROS_VAULT=~/.careeros/vault
# bash or zsh: type the phrase without it appearing on screen.
printf 'Password for the new account: ' && read -rs NEW_PASSWORD && echo
.venv/bin/python -m careeros.users \
  create --email you@example.com --name 'Your Name' --role admin \
  --password "$NEW_PASSWORD"
unset NEW_PASSWORD
```

Then start the server on that same vault: with `CAREEROS_VAULT` exported,
`.venv/bin/python -m careeros.server` reads it, so the account you just made
is the one the login page accepts. An account created in one vault cannot sign
in to another.

Reading the phrase with `read -rs` keeps it off the screen and out of shell
history. It is still passed as an argument, so it is visible in `ps` for the
length of the call: create accounts on a machine nobody else is logged in to.
Never type a password into this file or into a committed script.

`list`, `reset-password`, `disable` and `enable` are the other commands; see
[schemas](docs/schemas.md) for the user record and the full usage.

To develop against the fictional sample records instead, pass
`--vault sample/vault` to both commands. Signing in there writes a signing key
and a user record into `sample/vault`; Git ignores both, and they are still
credentials, so prefer a personal vault for anything but a quick look.

Open the address printed by Flask, log in with that account, and the board
opens. Log out from the affordance in the app header. Stop the server with
Ctrl-C. `--vault PATH` takes precedence over `CAREEROS_VAULT`; pass it
explicitly to select the intended data, for the accounts command as much as
for the server. Missing or empty vaults are supported.

The session is a signed cookie whose key is kept in the vault (`secret_key`,
mode 0600), so signing in survives a server restart and a browser restart.
Deleting that file signs everybody out.

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

AI work runs off the request path (CAREER-36). The enrich, extract and re-extract
endpoints answer `202 {"status": "queued"}` and the reading runs on a queue inside
the same process, one unit at a time; where it stands is read back off the record
(`ai_status`, `ai_error`, `ai_started`, `ai_finished`). Because the queue lives in
the process, stopping the server abandons whatever it held, so a record left
queued or running is marked failed with the reason `interrupted by server restart`
the next time the server starts.

Browser verification needs Node, an installed Chromium executable, and an
environment that permits local sockets and browser launch. Earlier restricted
builders could run Flask test-client tests but could not perform live browser
checks; that is not a claim that this host has the same restriction.

```bash
.venv/bin/python -m pytest tests/ -q                       # product suite
(cd vendor/capa-repo && ../../.venv/bin/python -m pytest tests -q)  # capability suite
(cd frontend && npx playwright test)                       # browser suite
```

Run the two pytest suites separately, each from its own root: `tests/test_enrich.py`
exists in both trees, and pytest refuses to collect two test modules of the same
name in one run. The browser suite reads `frontend/playwright.config.js`, which
starts the Vite dev server itself, so it has to run from `frontend`.

Tests use temporary fixture vaults. There is no single live-check script: the
browser suite covers the front end against mocked API responses, the pytest
suites cover the backend against sample-vault fixtures, and the live checks a
surface needs are recorded with that surface. Acceptance is the owner clicking
through a running instance, per AGENTS.md.
