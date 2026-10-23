# Deploy toolchain — what was built, what was proven, what was not

Branch `deploy-toolchain`. Nothing committed, nothing pushed, no VPS
contacted. Brief: `tmp-brief-deploy-toolchain.md`.

---

## 1. Files

### Added

| File | Lines | What it is |
| --- | --- | --- |
| `deploy/setup-vps.sh` | 489 | Idempotent first-time VM setup, root. `--dry-run`. |
| `deploy/deploy.sh` | 425 | One deploy of one environment, `stg`/`prod`/`--rollback`. |
| `deploy/README.md` | 380 | Owner's copy-paste steps, plus **Known gaps**. |
| `deploy/Caddyfile` | 32 | Exactly runbook Part 4, hash left as `PASTE_HASH_HERE`. |
| `deploy/systemd/careeros-prod.service` | 68 | 127.0.0.1:8001, hardened. |
| `deploy/systemd/careeros-stg.service` | 49 | 127.0.0.1:8002, same shape. |
| `deploy/systemd/careeros-deploy@.service` | 44 | `%i` = stg\|prod, oneshot, under flock. |
| `deploy/systemd/careeros-deploy-stg.timer` | 28 | `OnUnitActiveSec=2min`, `Persistent=true`. |
| `deploy/systemd/careeros-deploy-prod.timer` | 28 | `OnUnitActiveSec=5min`, `Persistent=true`. |
| `tests/smoke.sh` | 168 | POSIX. `/healthz`, login, three authenticated surfaces. |
| `tests/test_deploy_config.py` | 317 | 29 tests: `/healthz`, env config, mock, disabled. |
| `.env.example` | 104 | Every variable, placeholders only. |
| `.github/workflows/ci.yml` | 124 | One job named `ci`. |
| `ruff.toml` | 24 | Pins what `ruff check` means. See §4. |

The six existing scripts in `deploy/` are **untouched**, as required.

### Changed — the app (deliverable 2)

- **`careeros/server.py`** — added `GET /healthz` → `200 {"status":"ok"}`,
  unauthenticated (added to `PUBLIC_ENDPOINTS`); `/api/health` unchanged.
  `SESSION_COOKIE_SECURE` now reads `SESSION_COOKIE_SECURE == '1'`,
  default `False`. `main()` takes `--host`/`--port` defaults from
  `CAREEROS_HOST`/`CAREEROS_PORT`, falling back to `0.0.0.0:8788`; an
  explicit flag still wins. (Vault path was already `CAREEROS_VAULT`.)
- **`careeros/llm_client.py`** — `LLM_MOCK=1` → `MockLLMClient`, canned
  reply, no socket, needs no base URL/model/key. `LLM_DISABLED=1` →
  `LLMDisabled(RuntimeError)` with the message `LLM disabled`, raised
  before anything reads configuration. Disabled wins over mock.
- **`careeros/ingest.py`** — the disabled check sits in `_call_llm`
  *before* the injected `client` is used, so an off host makes no call
  even through a client handed in from elsewhere. Lands as the existing
  `not_configured` reason — no new state vocabulary.
- **`careeros/classify/llm.py`** — `Config.client()` honours both
  switches; `mock_answer()` answers `unknown` for every field the prompt
  asked for, read back off the request itself.
- **`careeros/enrich.py`** — `classification_options()` withholds the
  client entirely when disabled, so the capability skips its LLM
  fallback signal instead of collecting one failure per company.

### Changed — lint debt cleared to make the CI gate green (§4)

`careeros/feeds/personio.py`, `careeros/vault.py`, `careeros/enrich.py`,
`scripts/migrate_record_owner.py`, and seven test files. All lint-only:
five dead imports, six unused locals, four `lambda`→`def`, one
semicolon, one pointless `f`-string, nine `# noqa: E402` on deliberate
mid-file imports. **One exception, which is a real bug fix — read §5.**

`docs/runbooks/deploy-runbook.md` also shows as modified; that edit
(the owner's 2026-10-23 decision to skip the rehearsal VM) appeared on
disk during the session and was left exactly as found.

---

## 2. Gate results

Every command run from the repo root on 2026-10-23. `shellcheck 0.11.0`
and `ruff 0.17.2` were installed into `.venv` for this (`pip install
ruff shellcheck-py`); neither was present before.

| Command | Result |
| --- | --- |
| `.venv/bin/shellcheck deploy/*.sh tests/smoke.sh` | **pass** — exit 0, no findings |
| `for f in deploy/*.sh scripts/*.sh; do bash -n "$f"; done` | **pass** — exit 0 |
| `sh -n tests/smoke.sh` | **pass** — exit 0 (it is POSIX, not bash) |
| `.venv/bin/ruff check` | **pass** — "All checks passed!" |
| `env -u LLM_MOCK -u LLM_DISABLED .venv/bin/python -m pytest tests/ -q` | **pass** — `2546 passed, 1 skipped in 274.76s` |
| `.venv/bin/python -m pytest tests/test_deploy_config.py -q` | **pass** — `29 passed` |

Baseline before this work was `2517 passed, 1 skipped`; +29 is exactly
the new file, so nothing existing changed behaviour.

**The server still boots on the new env-driven defaults**: verified by
the full suite, which builds the app through `create_app` hundreds of
times with nothing set, and by the three default-value assertions in
`test_deploy_config.py` (`SESSION_COOKIE_SECURE is False`, host/port
`0.0.0.0:8788`, vault from `CAREEROS_VAULT`).

### One gate finding worth knowing about

My first draft of `ci.yml` exported `LLM_MOCK=1` for the whole job.
That **broke 12 existing tests** (`test_configuration_required`, the
`not_configured` cases in `test_ingest`/`test_jobs`/
`test_requirement_groups`, five in `test_async_ai`): they assert what
happens when this environment has *no* LLM configured, and mock mode
changes what that means. Removed. The suite already needs no key —
`conftest.py`'s `offline` fixture makes `urllib.request.build_opener`
raise, and every LLM-touching test injects its own client — so the
brief's "no test may need a key" holds without the global flag, and the
two switches are covered per-test in `test_deploy_config.py` instead.

---

## 3. What I actually ran `deploy.sh` against

Not a VM, but not nothing. I built a throwaway stand-in under `/tmp`: a
synthetic git repo whose `careeros.server` module answers `/healthz` and
the three smoke paths the way the real one does, a `systemctl`
stand-in that really starts and stops it, and two env files. Then drove
`deploy.sh` through 24 scenarios. **All of these are confirmed working:**

- First deploy: mirror clone → checkout → venv → `pip install -r
  requirements.txt` → import check → symlink flip → restart → `/healthz`
  200 → smoke test → done, exit 0.
- Re-run with nothing new: `already running <ref> -- nothing to do`, exit 0.
- Second commit: `previous` recorded, `current` flipped, old release pruned.
- **Forced health failure**: `/healthz` never answered 200 → rolled back
  to `previous` → restarted → re-polled 200 → wrote `failed.ref` → exit 1.
- **Forced smoke failure** (health fine, `/jobs` 500): same rollback path.
- The same failed ref is not retried; a *newer* good commit deploys over
  it and clears `failed.ref`.
- `--rollback`: flips back, restarts, writes `rollback.pin`, exit 0.
- While pinned: `deploying nothing`, exit 0. After `rm` of the pin: deploys.
- Production: newest `v*` tag by **version** sort (`v0.10.0` beat
  `v0.9.0`), vault archived and verified before anything else, archive
  pruning to the keep count, releases pruned to 2 + whatever the symlinks
  hold.
- No vault to archive → deploys nothing, touches no backup.
- Concurrent run → refuses with a message, does not queue.
- Bad/missing arguments → usage, exit 64.
- `tests/smoke.sh` on its own: credentials from the environment (pass),
  credentials from an env file (pass), wrong password (exit 1, one ALERT
  line), no credentials (exit 2 — a loud skip, which is why a first
  deploy is not rolled back for lacking a tester account), no URL (exit 1).

Two findings came out of this and are fixed in the committed script:
the re-exec-under-flock argument handling was broken (replaced with
`exec 9>$LOCK; flock -n 9`, which also gives a real message), and release
pruning compared resolved paths where it should compare names.

**This proves the script's own logic. It proves nothing about real
systemd, real Caddy, real ufw, apt, or a real GitHub deploy key.**

---

## 4. The `ruff.toml` decision — please look at this

`ruff check` over this repo reported **27 findings before I touched
anything**, and ~450 with the full rule catalogue. A CI job whose lint
step is red on arrival is worth nothing, so I had to pick something.

What I did: `ruff.toml` pins the rule set to ruff's own documented
default (`E4`, `E7`, `E9`, `F`) and excludes `vendor` (the pinned
capability submodule — another repo's code). That default is what the
`# noqa: E402` and `# noqa: F401` comments already scattered through
`careeros/`, `scripts/` and `tests/` were written against, so this names
a convention the repo already had rather than inventing one. Then I
fixed the 27 — all one-liners, no behaviour change, except the one in §5.

What I deliberately did **not** do: widen the rule set. The other ~420
findings are style opinions the code makes on purpose (import order,
`dict()` over `{}`, blind `except`). Picking those fights is its own
task with you, not something to smuggle into a CI job.

---

## 5. A real bug I had to fix to get the gate green

`careeros/server.py`, in the extraction callback `on_result`:

```python
if new_company_id is not None and shared:      # <- `shared` named nothing
```

`shared` is a local of `apply_llm_update`, not of this callback, so
**any extraction that created a new company raised `NameError`** — which
the surrounding handler caught and turned into a job stuck at
`extract_failed` with no visible reason. Pyflakes (`F821`) is what
surfaced it.

I replaced it with `company_enrichment.contributes_to_shared(root,
current)` — the same call, on the same record, that
`apply_llm_update` makes to compute `shared` in the first place, so it
is the value the line was written to mean rather than a guess. It is
still a behaviour change in a path the brief did not ask me to touch:
**review this one specifically.** If you would rather I had left it
alone, reverting it means re-opening the ruff question in §4.

---

## 6. What I could NOT verify — be sceptical of all of this

### Not exercised at all
- **systemd.** No unit was ever loaded. Hardening directives
  (`ProtectSystem=strict`, `ReadWritePaths`), `EnvironmentFile` ordering,
  `flock -E 0` in the `ExecStart`, `ExecStartPre=install -d`, timer
  `OnUnitActiveSec`/`Persistent` behaviour — all unrun. I reasoned about
  each; none is tested. The one I am least sure of: whether the vault is
  genuinely the only path the app needs writable under
  `ProtectSystem=strict`. I grepped every write in `careeros/` and they
  all land under the vault root (atomic temp-file-then-rename in the same
  directory) with `PrivateTmp` covering the rest — but a missing
  `ReadWritePaths` shows up as a 500, not as a startup failure.
- **Caddy.** The Caddyfile was never validated by Caddy. `basic_auth`
  (not `basicauth`) is the v2.8+ spelling and matches the runbook;
  if your Caddy is older, that block is the thing that will fail
  `caddy validate`.
- **ufw, apt, unattended-upgrades, the cloudsmith Caddy repo.**
  `setup-vps.sh` was never run, not even `--dry-run` against a real
  Ubuntu box. Its guards are read-the-state-first throughout, but
  "idempotent" is a claim here, not a measurement.
- **GitHub deploy keys.** No key was generated, added or used. The
  `ssh-keyscan` of `github.com` and `StrictHostKeyChecking=yes` path is
  untested.
- **The CI workflow.** Never ran. Written against the documented
  behaviour of `actions/checkout@v4`, `actions/setup-python@v5` and
  `gitleaks/gitleaks-action@v2`. The step most likely to fail first is
  the submodule checkout — see gap 2 below.

### Known gaps — three decisions that are yours
These are in `deploy/README.md` in full. Short version:

1. **Most pages will 404.** `deploy.sh` does not build the React front
   end and `setup-vps.sh` does not install Node (`vite ^8` needs Node
   20+; Ubuntu 24.04 ships 18). So `/`, `/companies`, `/experiences`,
   `/taxonomy`, `/notes` and every detail page answer 404; `/jobs` in
   its Jinja rendering and the whole JSON API work. This was outside the
   brief, so I did not build it — but it means a deploy today serves a
   crippled app. `tests/smoke.sh` deliberately asserts only
   renderer-independent routes so it stays honest about this.
2. **The submodule may be unfetchable, which blocks deploys outright.**
   `vendor/capa-repo` is recorded with an HTTPS URL and
   `careeros/server.py` imports `org_intake` from it at module level.
   `deploy.sh` runs `git submodule update --init --recursive` and fails
   the deploy with a clear message if it cannot. That works **only if
   `jozzian/capa-repo` is public.** If it is private, a deploy key will
   not help: GitHub allows a key to be a deploy key on exactly one
   repository. Same problem in CI. Decide this before the first deploy.
3. **Flask's built-in server.** The units run `python -m careeros.server`
   — what `main()` actually does, per the brief's "make the units match
   reality". No uvicorn/gunicorn exists in `requirements.txt`. Fine
   behind Caddy for one owner and a tester; one line to change later.

### Secrets check
No real secret and no VPS IP in anything added. `179.237.122.209`
appears only in `docs/runbooks/deploy-runbook.md`, where it already was.
Credentials in new files are `PASTE_HASH_HERE`, `paste-the-key-here`,
`<the key for THIS environment>` and the like. The one literal is
`CLASSIFY_LLM_API_KEY=ollama` in `.env.example`, which is the fixed
string Ollama's API wants and is already `DEFAULT_API_KEY` in
`careeros/classify/llm.py`.

---

## 7. Element accounting (AGENTS.md)

Added: 14 files, two app env switches (`LLM_MOCK`, `LLM_DISABLED`), one
env setting (`SESSION_COOKIE_SECURE`), two host/port env settings, one
endpoint (`/healthz`), and two deploy state files (`rollback.pin`,
`failed.ref`).

`failed.ref` is the one I would argue about. It is not in the brief. I
added it because without it a bad tag is redeployed every 5 minutes
forever, and each prod attempt takes a vault backup — which would churn
the 14-archive window out of existence inside two hours. It is one file,
one check, and `rm` undoes it.

Not added, on purpose: a second smoke script (`tests/smoke.sh` reuses
`deploy/smoke.sh`'s security approach, not its code, because that file
must stay untouched — the two should be merged once `tests/smoke.sh` has
proven itself on the VPS); a Node toolchain; extra deploy keys.

## 8. Open questions for you

- Gap 2 (the submodule) blocks everything. Public, machine user, or
  vendor it?
- Gap 1 (the front end): build on the VPS, build on your Mac and copy,
  or commit `dist/`?
- The §5 bug fix — keep it, or revert it and re-open §4?
- Retire the six carry-over scripts now that `deploy.sh` takes its own
  pre-deploy backup?
- With the rehearsal VM skipped, do you want me to extend
  `tests/test_deploy_scripts.py` to cover `deploy.sh` the way it covers
  the other six (subprocess + PATH stubs)? That would turn the §3
  rehearsal into something CI re-runs instead of something I ran once.
