# Deploy runbook amendments — FINAL

Date: 2026-10-22. Author: Hermes. Reviewed by: Claude Code (operational, code-verified) and Codex (security/privacy, read-only). All findings adjudicated; owner ruled on every open decision 2026-10-22.
Status: FINAL — splice-ready. Each amendment below replaces or extends the corresponding part of the runbook at `/root/.hermes/cache/documents/doc_ea7e6da857e0_Career OS Deploy Runbook.md`.

## Owner decisions (ruled 2026-10-22)

1. Owner data authority: **split**. Pipeline outputs (postings, exports, classification runs, tenants metadata) are LAN-authoritative and sync one-way to prod. Owner-edited records (applications, statuses, notes, CV) are prod-authoritative once editing begins in prod; the sync never mirrors or deletes prod-owned paths.
2. Agent merge rights: **fork-based PR flow**. The agent account loses base-repository Write; PRs come from a fork, so "only the owner merges" is enforced by permissions, not trust.
3. Backup encryption: **yes**, public-key scheme. The VPS holds only the encryption (public) key and can create but never open backups; the recovery (private) key is kept offline by the owner.
4. Hosted LLM in prod: **launch disabled**. Prod is a read-only dashboard fed by locally classified data. No owner personal data leaves for an external model provider. Revisit later with a field-level privacy pass.
5. Backup cadence: **Sunday full backup of the synced subset, keep 5 (~1 month)**, exactly as the owner proposed. Plus daily backups of the small owner-data slice, 30 days, once prod accepts owner edits. Pre-deploy backups retained (keep 14).
6. Prod seed vault: **the test vault** (`/root/career-os-test`, holds the 704 imported universe jobs). The first owner-data import into prod is still ahead.
7. Nightly memory caps: raise `MemoryMax` 1200M → 2G, drop `MemoryHigh` (stall risk retired), fix the stale "3 GiB" header comment in `scripts/nightly_pipeline.sh`. (Hermes implements.)
8. Prod dependency split (`requirements-prod.txt`): **deferred, recorded**. Do not split now; measure VPS disk on the rehearsal VM first; revisit only if disk is tight.

## Measured facts that replace runbook numbers (verified 2026-10-22)

- Nightly runtime is now **≈7 hours** (2026-10-21: 17:00→23:57 UTC; classify leg alone ≈4.1 h, 870,727 tokens). The runbook's "~40–90 min" is stale.
- Tenant pool: **9,600** across six providers (personio 2,467, greenhouse 2,923, lever 91, ashby 3,038, recruitee 452, smartrecruiters 629).
- Serving-relevant data sizes: vault **792 KB**, `data/ats/exports` 3.3 MB, `data/classification` 7.3 MB, six `tenants.yaml` + `runs.yaml` ≈ 11 MB. Nightly sync delta **≈16 MB**. `state/` (707 MB) and `data/ats/*/snapshots` (bulk of 7.3 GB) are never read by the serving app and stay LAN-only.
- The app has hashed passwords and signed sessions; the accepted security gaps (PROJECT.md:245-248) are **no CSRF beyond SameSite=Lax and no login rate limiting** — acceptable on a LAN for five testers, NOT for the public internet.
- Migrations run automatically at every app startup (`server.py:660-673`, idempotent additive-only). There is no separate migration system to invoke in deploy.sh.
- The pipeline host clock is **UTC**; the 17:00 UTC cron is 19:00 Swiss only during summer time. DST ends **Sunday 2026-10-25**.

## Amendment 1 — Vault sync LAN → prod (new deliverable, PR 1.5)

Split-authority sync, pushed from the LAN after each successful nightly. The VPS never connects inward; "servers pull" survives for code only, and the principles section must say so out loud (the one real change to the threat model: data is pushed, and the push credential lives on an agent-owned host).

- **Allowlist, not exclusion.** Sync exactly: `data/ats/exports/`, `data/classification/`, the six `tenants.yaml` + `runs.yaml`, and vault data files that are pipeline-owned. Never sync: session-signing key (`users.py:120` stores `secret_key` in the vault), user/account records, environment files, logs, backups, `state/`, snapshots. Prod provisions its own signing key and accounts (owner-run, Part 3).
- **Prod-owned paths are untouchable.** Anything under the owner-data subtree is excluded from `--delete` semantics entirely; the sync must not be able to mirror over or remove prod-authored records (also protects `migrate_record_owner.py` results from being nightly-overwritten by un-migrated LAN copies).
- **Empty-source guard.** Before transfer: require a pipeline completion manifest for the run day, verify source identity, mandatory files present, plausible record counts. A deletion threshold above which the sync aborts and alerts instead of propagating. Never `--ignore-errors`; deletion only ever applies inside disposable incoming trees.
- **Upload/promotion separation.** LAN pushes into an isolated `incoming/<generation>/` directory via `rrsync -wo` (write-only, confined). A separate VPS-side promotion step (local, not the uploader) takes exclusive control of a completed generation, validates manifest/schema, rejects symlinks and special files, enforces modes, then promotes by same-filesystem rename of a temporary symlink under a fixed root. The uploader cannot write the live pointer, active generations, backups, code, or `/etc`.
- **Atomicity is required, not preferred.** Stable source snapshot; unique incoming dir; rsync exit 0 + validation before promotion; serialize promotion against deploys and backup snapshot selection; keep the previous generation until readers drain. Rehearse: interrupted transfer, full disk, concurrent runs — none may promote partial data.
- **Chaining, not clock.** Sync fires on pipeline completion (systemd `OnSuccess=` or appended to `nightly_pipeline.sh`), with `$DAY` passed as an argument — never a separate fixed-time cron and never a recomputed `date +%F` (the nightly can cross midnight UTC).
- **SSH hardening.** Dedicated LAN key for this push only; `restrict`, no forwarding/PTY; pinned VPS host key; `StrictHostKeyChecking=yes`, `BatchMode=yes`, `IdentitiesOnly=yes`; key file 0600 in a 0700 dir, unreadable by app users; restrict source address to the LAN's public egress if stable; document revocation/rotation. Exactly **one target: prod** — staging is seeded from `sample/vault/` only, never from the LAN (staging never holds live data).
- **Credentials are owner work** (Part 3): key generation, VPS account creation, authorization placement. Never in chat or git.
- **Failure visibility:** non-zero exit + alert on the LAN side; prod keeps serving the last good generation; stale-sync alerting (track last successful generation, alarm if > 36 h, without logging personal content).

## Amendment 2 — Backup policy (replaces "keep the last 14" vault backups)

- **Sunday full backup** of the prod-synced subset, zstd-compressed and **public-key encrypted on the VPS before any copy leaves**, keep the last 5 (~1 month). At ~16 MB payload this is trivial.
- **Daily owner-data backup** (applications, statuses, notes, CV — the prod-authoritative slice), encrypted, keep 30. Mandatory off-VPS copy: a LAN job **pulls** completed encrypted archives over a separate read-only SSH credential (VPS cannot reach in; LAN pulls). Versioned NAS snapshots that VPS/app credentials cannot delete are preferred over a second Proxmox disk (independent failure domain). The LAN vault remains single-copy master for pipeline data — the Sunday job also drops a copy off-VM.
- **Pre-deploy backup** retained (different failure mode: bad release; also the safety net for the automatic additive migrations that run before the health check), timestamped, keep 14, same encrypted-subset scope. Stored at `/var/backups/careeros`. The empty, unused `/root/career-os/backups/` is deleted in the same change and nothing recreates it.
- **Retention as max-age, not just counts**: prune only after successful creation + verification + confirmed remote copy; handle missed runs; alert on stale backups; **test a full isolated restore including decryption, ownership, permissions, and app startup** at least once before go-live, then quarterly.

## Amendment 3 — Prod auth (replaces "public, or your own login")

- Caddy `basic_auth` on prod with a strong owner-set password, **kept as defense-in-depth even after app auth hardening** — justified precisely because the app has no login rate limiting.
- Before PR 2 merges, the app must gain: `SESSION_COOKIE_SECURE=True` + host-only cookies in prod (currently hardcoded False, `server.py:530`), CSRF tokens + exact-origin validation on every state-changing request (no mutations via GET; cover login/logout), and shortened session lifetime. SameSite is defense-in-depth, not the protection. Staging and prod are sibling origins — test cross-origin requests from both.
- Prod account hygiene: disable/reset every account carried over from LAN; remove test accounts; unique strong passwords; login throttling. Note `users create --password` lands in shell history (`users.py:490`) — run with a leading space or `HISTFILE=/dev/null`.
- The runbook's prod Caddy example, access table, and "loads the app" check are **replaced**, not merely annotated. TLS + auth on every route including APIs and downloads; backend ports loopback-only; strip the `Authorization` header before proxying if the app doesn't need it; confirm HTTP-only redirects; test missing/wrong credentials externally.
- Incident revocation documented: rotating the signing key requires a service restart (deleting the file doesn't unload the in-memory key).

## Amendment 4 — Ordering and correctness fixes

1. **Ruleset sequencing:** enable PR-required + approval + stale-approval dismissal + force-push/deletion protection **immediately** in Part 1; add the required `ci` check only after ci.yml exists and runs green on main (the repo currently has 0 tags and no workflows dir — the deadlock is real). Create the main ruleset **after** the agent account is invited and can be approved, or the first PR cannot be merged by anyone.
2. **Fork flow:** remove agent base-repo Write; agent pushes to its fork; owner merges. Verify private-repo ruleset support on the current plan and **test actual denials** rather than assuming.
3. **Token retirement is three verifiable steps:** revoke `GITHUB_CAREEROS` in GitHub; delete the variable from the Hermes environment (it is live in the agent environment today — a re-issued token under the same name would silently restore push rights); confirm `git push --dry-run origin main` from the agent host fails.
4. **deploy.sh drops "run migrations"** — they execute automatically at startup (`server.py:660-673`). The runbook says why, and why the pre-deploy backup therefore matters.
5. **SSH hardening order fix:** test fresh key-authenticated sudo + provider-console recovery **before** any script touches sshd or the firewall. Validate with `sshd -t`, inspect effective config including includes, reload while keeping the working session open. Disable password + keyboard-interactive auth and root login where unused. Verify firewall covers IPv4 **and** IPv6.
6. **AAAA records:** checklist item with verification — copy prod's AAAA to staging only if `app.career-os.ch` already resolves and serves over IPv6; otherwise neither name gets one. A wrong AAAA can stall Caddy certificate issuance.
7. **Timezone:** cron entry gets explicit `TZ=Europe/Zurich` (or state UTC everywhere); fix the script header; add VPS timezone to the owner checklist (the Sunday backup and retention crons derive weekday names). **DST ends Sunday 2026-10-25** — without the fix the nightly silently shifts to 18:00 Swiss.
8. **Smoke test with eyes:** dedicated smoke account (`users create --role tester`), password in `/etc/careeros/prod.env` (root-owned 0640); `smoke.sh` POSTs JSON to `/login`, then asserts 200 on `/`, `/jobs`, and one job-detail page. Without a session, auto-rollback cannot detect a 404-ing UI.
9. **Deploy identity and release selection:** builds/tests/imports run as non-root, environment-specific identities; privileged helpers and units root-owned and unwritable by services; deploy pins an exact immutable commit from an owner-authorized `v*` tag, verifying reviewed-main ancestry and successful CI; rollback stays pinned (the next timer must not undo it).
10. **Rehearsal VM** created by Hermes on the Proxmox host per owner instruction; gets no LAN vault data, no real credentials, and network isolation from the live vault, Proxmox management, and prod credentials. Measure VPS disk need there: venv (full test stack today — split deferred per decision 8) + node_modules + 2 releases + backups.
11. **Secret scanning:** verify the plan's actual entitlement before relying on it; gitleaks in CI as the floor; exclude live vaults/backups/transcripts from git and CI artifacts; revoke-then-clean on any leak.
12. **Hosted LLM:** prod launches with external LLM calls disabled (decision 4). The runbook records that enabling them later requires a documented field-level privacy pass (which fields, provider routing, retention/training settings, prompts out of logs).
13. **Prompt-injection stance tightened:** permission separation — content-processing agents get no prod/deploy/sync credentials; model output is untrusted data, never commands, validated before persistence; review covers executable changes beyond `deploy/`; check stored-HTML/script injection and block app-side URL fetches to loopback/private/metadata ranges.
14. **Ops hygiene:** alert on failed/stale syncs and backups; cap incoming storage and clean abandoned transfers; security-update/reboot checks; HSTS after HTTPS verification + framing protection headers.

## Amendment 5 — Principles section additions

- "Servers pull" holds for **code** only; data is pushed from a LAN host the agent owns — state this explicitly as the one change to the threat model.
- Prod seed = test vault (704 universe jobs); first owner-data import into prod remains a separate, owner-run step.
- Memory caps: nightly `MemoryMax=2G`, `MemoryHigh` removed, header comment corrected (worst measured leg: 779 MiB; VM now 8 GiB).

--- END OF FINAL AMENDMENTS ---
