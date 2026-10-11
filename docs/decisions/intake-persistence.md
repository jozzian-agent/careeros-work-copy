---
type: Decision
title: "Intake persistence"
description: "Preserve durable intake, duplicate and watcher persistence choices."
timestamp: 2026-10-11
---

# Intake persistence

Recorded implementation choices from the intake and watcher fixes, including
JOZ-265 on 2026-10-08; this record does not imply a new owner approval.

- Preserve url as the raw pasted input and original_url as the extracted
  canonical URL; normalized_url is the comparison key. This resolves the
  journey draft's conflicting proposal to repurpose original_url.
- Persist the stub before DNS or fetching. The request still waits for the
  fetch; true pre-fetch response and manual paste-text recovery were deferred
  to JOZ-267. Durable storage is not immediate display acceptance.
- A failed fetch retains URL-derived heuristics and a visible reason. No usable
  extraction result records the specific failure, including absent runtime
  configuration. An empty description does not pretend extraction was tried.
- Re-read under the write lock and apply asynchronous fields only when their
  values still match the intake snapshot. Changed URLs invalidate stale work.
- Hard ATS identity includes provider, tenant and posting ID; host suffixes
  must be dot-bounded. An owner-approved additional provider uses a numeric
  tenant and publication path, retaining publication suffixes in its identity.
  The provider registry in code remains the authoritative list.
- Duplicate choices include Open existing and Add anyway, plus Promote for
  records outside the pipeline. Cancel and Escape create nothing.
- Startup migration fills missing job fields independently, preserves existing
  user values and isolates malformed records. It deliberately differs from
  earlier explicitly triggered taxonomy migrations.
- Watcher baselines use normalized posting content, excluding page chrome;
  old hash versions migrate without invented change events. History retains
  the newest 50 entries and does not invent events for legacy records.
- Salary on experiences remains file-managed; API creation writes null and
  edits preserve the stored value. Record filenames retain IDs to prevent
  same-title collisions, and writes use atomic replacement.

## Open questions

The deferred intake work remains in the [add-job flow](../flows/add-job-by-link.md).
