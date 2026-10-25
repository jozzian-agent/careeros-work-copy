# Career OS deploy runbook

**The procedure is [`deploy/RUNBOOK.md`](../../deploy/RUNBOOK.md).** It is
the step-by-step version: every step says where it runs, what the exact
command is, what success looks like, and what to capture when it fails.
Start there. This file keeps only the two things that are not steps — what
the target machine is, and how a change travels from a pull request to
production.

This replaces the planning checklists that used to live here: the PR
briefs, the host-panel steps and the plan for a dress run on a spare
machine. That work is done, has moved into `deploy/`, or was dropped by
the owner.

## Principles

The agent writes code and opens pull requests; only you merge, release and
hold production access.

- The agent has no access to the VPS, to production secrets, or to merge
  and release rights.
- **Servers pull.** Each environment checks GitHub on a timer and deploys
  with a read-only deploy key, so nothing connects in from outside, and
  nothing on the VPS connects out.
- Staging never holds live data. Production changes only when you publish
  a release tag.

## The target VPS (verified on the machine, 2026-10-23)

- Ubuntu 26.04.1 LTS, kernel 7.0.0-38-generic, amd64.
- System `python3` is **3.14.4**. No version-suffixed interpreter exists
  on the box; `python3` is it, and every release venv is built with it.
- 2 vCPU, 1.9 GB RAM, 37.6 GB root disk, one disk, **no swap** as
  delivered. `deploy/setup-vps.sh` adds a 2 GB swap file and caps both
  services' memory, because **staging and production share this one box**.
- IPv4 179.237.122.209, IPv6 2001:1600:18:20c::27b, interface ens3.
- `app.career-os.ch` and `staging.career-os.ch` already resolve here (A
  and AAAA). No DNS work is outstanding.
- Login is the `ubuntu` account with the owner's SSH key; password login
  is already off. Nothing in `deploy/` touches SSH.
- `sudo -n true` is the check for passwordless sudo. Not `sudo -v`, which
  prompts on this box even where real commands do not. Ubuntu 26.04 may
  ship sudo-rs, so exotic sudo flags are avoided everywhere.

| Setting | Staging | Production |
| --- | --- | --- |
| URL | staging.career-os.ch | app.career-os.ch |
| Deploys when | a commit lands on `main` | you publish a tag `vX.Y.Z` |
| Local port | 8002 | 8001 |
| Service user | `careeros-stg` | `careeros-prod` |
| Data | test vault (synthetic) | live vault |
| LLM key | own key, small spend limit | own key |
| Access | password in Caddy | the app's own login |

One VPS is enough to start. For stronger isolation later, move staging to
its own small VPS; only its DNS record and its deploy timer move.

## The release flow

1. The agent opens a pull request in `jozzian-agent/careeros-work-copy`.
   CI runs there: the test suites, shellcheck and a secret scan.
2. You read the diff, with extra care for anything in `deploy/`, systemd
   units, auth, network or secrets, then merge it there.
3. You promote the merged code to `jozzian/careeros`. Only your own
   repository's `main` reaches the servers.
4. Within about 2 minutes staging deploys the new `main`, runs the health
   check and the smoke test, and rolls back by itself if either fails.
5. You click through staging against the synthetic vault.
6. When it is good, publish a release in your own repository: a tag such
   as `v0.1.0` on `main`.
7. Within about 5 minutes production backs up the vault, deploys, checks
   health, and rolls back by itself if it fails. Then you check it by
   hand.

Promote from your Mac, in your clone of `jozzian/careeros`. The first time
only:

```bash
git remote add agent https://github.com/jozzian-agent/careeros-work-copy.git
```

Each time:

```bash
git fetch agent
git log --oneline origin/main..agent/main
git diff origin/main agent/main
git merge --ff-only agent/main
git push origin main
```

The `diff` shows exactly what you are accepting, so read it before the
last two lines. Never commit to your own repository directly; ask the
agent instead, so the two histories stay in line. If `--ff-only` refuses,
the histories have diverged: stop there.

If production misbehaves after passing its health check, roll back
(`deploy.sh prod --rollback`, see `deploy/RUNBOOK.md`) or publish a new
tag on the last good commit. A hotfix takes the same path with a smaller
pull request.

## LLM keys

One key per environment, each with its own spend limit, entered only on
the server with `sudoedit` — never in chat, in git, or in a tracker. To
rotate: create the new key, edit the env file, restart the service, then
delete the old key. If a key leaks, delete it at the provider first.

The variables and what reads them are in [`.env.example`](../../.env.example);
where to put them is step 5 of `deploy/RUNBOOK.md`. Tests and CI need no
key at all.

## Main risks

- A hidden instruction in a job posting steering the agent into writing a
  harmful script. Covered by you reading every `deploy/` diff, since those
  scripts run as root, and by `setup-vps.sh --check`, which prints its
  whole plan and changes nothing.
- Staging and production sharing data or keys. Covered by separate users,
  separate vaults, separate env files and separate keys.
- Losing SSH access. Covered by nothing in `deploy/` touching SSH at all,
  and by the reset-the-server fallback in `deploy/RUNBOOK.md`.
- A surprise LLM bill. Covered by a spend limit on every key.

## Open questions

- Which of the five older LAN→prod scripts in `deploy/` are being kept now
  that `deploy.sh` takes its own pre-release vault archive?
  (`deploy/RUNBOOK.md`, Open questions.)
