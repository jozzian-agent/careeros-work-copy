# Scheduled jobs: the one overview

Every job that runs on its own, in one table, so "what runs when, where,
and who hears about it" has a single answer. Each row links to the
detailed doc; this page is deliberately shallow — if a fact lives twice,
the linked doc wins.

Two machines run jobs, and they are easy to confuse:

- **the LAN host** (192.168.1.203, where the repo, the nightly pipeline
  and the owner's local dashboard live) runs Hermes cron jobs;
- **the VPS** (staging + prod behind careeros domains) runs systemd
  timers.

## The table

| # | Job | Machine | Schedule | What it does | Who hears about it | Detail |
|---|---|---|---|---|---|---|
| 1 | `careeros-nightly-pipeline` | LAN host, Hermes cron `488ba0fa1330` | 19:00 UTC daily (20:00 Swiss in winter; fires on UTC per `cron list`, see nightly-pipeline.md DST record) | Wrapper `~/.hermes/scripts/careeros_nightly.sh` → `scripts/nightly_pipeline.sh` in the cron checkout: compresses old snapshots, fetches all six ATS providers (reads their public feeds), exports the pool and classifies it with the local LLM (192.168.1.10). Writes `data/ats/…`, `data/ats/exports/golden_set_pool_<date>.yaml`, `data/classification/run_<date>.yaml`, `data/nightly/nightly_<date>.log` | Telegram: one-line summary every night (a run with fails says so and exits non-zero). Stop it: `cron` pause/remove job `488ba0fa1330` (pause keeps the record); never by deleting the wrapper — the cron entry would then fail nightly | [nightly-pipeline.md](nightly-pipeline.md) |
| 2 | `careeros-posting-watcher` | LAN host, Hermes cron `50e5d8ed7098` | every 6 h | `python -m careeros.watcher --vault <owner-vault>` — scans the owner's live vault (exact path in the wrapper) for posting events | Telegram, watchdog style: **silent when nothing happened**, one line per event | wrapper `careeros_watch.sh` in the Hermes scripts dir on the LAN host |
| 3 | `careeros-deploy-stg.timer` | VPS, systemd | every 2 min (from end of last run) | Pulls `main`, deploys staging if the ref moved | journal only | [deploy-runbook.md](deploy-runbook.md), unit comments in `deploy/systemd/careeros-deploy-stg.timer` |
| 4 | `careeros-deploy-prod.timer` | VPS, systemd | every 5 min | Pulls the published tag, backs up the vault, deploys prod; honours `rollback.pin` | journal only | [deploy-runbook.md](deploy-runbook.md); **installed but NOT enabled by default** — enable with `systemctl enable --now careeros-deploy-prod.timer` once prod.env is filled in |
| 5 | `careeros-company-requests.timer` | VPS, systemd | 03:30 daily + up to 30 min jitter (`Persistent=true`: a missed night runs once after a reboot) | Runs `scripts/resolve_company_requests.py` over the prod vault: matches filed company requests against shared companies, links what it can, parks the rest as `needs_admin` | **No message to anyone.** Parked requests appear on the admin-only Company requests page; counts land in the journal | [company-requests.md](../surfaces/company-requests.md), the script's own docstring, unit comments in `deploy/systemd/careeros-company-requests.{service,timer}` |
| 6 | `career-131-postnightly-report` *(one-shot, spent)* | LAN host, Hermes cron `f9252cdad3fd` | fired once, 2026-11-04 05:30 UTC; no longer in the cron store (a one-shot job is removed after its run) | LLM agent job, no wrapper script: read `data/classification/run_2026-11-03.yaml` and ran `scripts/family_suggestions.py list` in the cron checkout (read-only) to report the first CAREER-131 family-suggestion night | Telegram: two small tables (run metrics, top-15 proposals); its honest finding was that the run predates merge `00282e7`, so zero suggestions existed. Nothing to stop — it cannot fire again; output kept in the Hermes cron output dir | the run's own output file (`…/cron/output/f9252cdad3fd/2026-11-04_05-40-19.md` on the LAN host) |

## Which jobs are enabled out of the box

| Job | Enabled by | Status after a fresh setup |
|---|---|---|
| nightly pipeline, posting watcher | Hermes cron on the LAN host | live as long as Hermes runs |
| deploy-stg | `deploy/setup-vps.sh` | live |
| deploy-prod | nobody — installed, not enabled | **owner enables by hand** |
| company-requests | owner, by hand | **enabled on the VPS since 2026-11-01** (owner decision; not verifiable from the LAN host — check with `systemctl is-enabled careeros-company-requests.timer` on the VPS) |

### Enabling the company-request resolver on the VPS, once

Done 2026-11-01. The steps stay here for a fresh setup: the unit files
ship in the repo but nothing places them; that is deliberate — the
resolver writes the production vault, so a human decides when that
starts happening.

```bash
# on the VPS, as root
cp /srv/careeros/prod/app/current/deploy/systemd/careeros-company-requests.service /etc/systemd/system/
cp /srv/careeros/prod/app/current/deploy/systemd/careeros-company-requests.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now careeros-company-requests.timer

# prove it is scheduled:
systemctl list-timers careeros-company-requests.timer

# optional: one pass right now instead of waiting for 03:30
systemctl start careeros-company-requests.service
journalctl -u careeros-company-requests -n 50 --no-pager
```

The service runs as `careeros-prod` with `CAREEROS_VAULT` pinned to the
prod vault (the `Environment=` line after `EnvironmentFile=` wins on
purpose, so an env-file edit cannot repoint it). `COMPANY_REQUEST_AUTO_CREATE`
in `/etc/careeros/prod.env` decides what a pass does with an unmatched
request: unset (the default) parks it for the admin; `1` creates the
company itself. A quiet night writes nothing and exits in under a second.

## Adding or changing a job

- A **LAN-host** job is a Hermes cron entry wrapping a script in
  `~/.hermes/scripts/`; keep the watchdog contract (empty stdout =
  silent) if it is a watcher, or the short-summary contract if it is a
  pipeline whose stdout goes to Telegram verbatim.
- A **VPS** timer is a unit file in `deploy/systemd/` with its reasoning
  in comments, plus a row here. Anything that writes the prod vault is
  installed by hand, never by `setup-vps.sh`.
- Either way: **update this table in the same change.** A job that is
  documented only in its own corner is how the resolver's timer came to
  be "maybe enabled, nobody checked".

### The standing rule (owner decision 2026-11-04)

Any change to a scheduled job, any new job, and any change to the
nightly pipeline (`scripts/nightly_pipeline.sh`), the vault sync
(`deploy/sync_vault_to_prod.sh`, `deploy/promote_incoming.sh`) or the
release flow (`deploy/deploy.sh` and the runbooks) must update the
documentation that describes it **in the same PR**, and the PR
description must list which docs were checked.

`docs-fresh` cannot enforce this: it only regenerates `docs/as-built/`
from the running app and diffs it. A CI job could: fail when the PR's
changed files touch any of the paths above and the PR description has
no `Docs checked:` line (`github.event.pull_request.body` is available
to the workflow). Proposed here, not implemented — a workflow change is
not a docs-only change.
