---
type: Learning
title: "Learnings"
description: "Carry forward dated surprises from enrichment, intake and verification."
timestamp: 2026-10-11
---

# Learnings

## 2026-10-07 — Company enrichment diagnosis

Structured sources supplied useful classifications for only a small minority
of the companies examined. Empty evidence, missing prerequisites, rate limits
and fetch errors had been conflated. Outcome: fixed per-field accounting and
bounded retry handling; optional AI remains a last-resort source, not proof.

A global longest-keyword rule silently picked one of two unrelated activities.
Outcome: fixed specificity to require substring specialization; independent
matches remain ambiguous and require review.

A single status for two fields discarded valid employee counts when industry
lookup failed, and vice versa. Outcome: fixed separate field outcomes. A size
class is not a headcount, and numeric ranges cross class boundaries. Outcome:
fixed consistency checks without fabricating a range from a class hint.

Top-result entity matching can select a namesake or subsidiary rather than the
intended organisation. Outcome: later, improve entity disambiguation; do not
interpret a successful fetch as proof of identity.

## 2026-10-08 — Intake and concurrent edits

A durable stub before fetching does not make the HTTP response immediate.
Outcome: retain the storage guarantee and defer the async worker to JOZ-267.
Snapshot equality protects changed values but cannot detect a human changing a
value and restoring its baseline. Outcome: later, field provenance under the
journey's owner-wins rule; do not claim snapshot equality is full provenance.

Duplicate IDs were scoped to provider but not tenant, and substring host checks
accepted lookalike domains. Outcome: fixed tenant-aware identity and dot-bounded
hosts. One malformed legacy URL could stop migration. Outcome: fixed per-record
isolation and independent missing-field backfill.

## 2026-10-11 — Salvaging earlier verification findings

Earlier chunk verification showed that template/test-client checks could pass
while sockets and Chromium were unavailable to the builder. Outcome: retain
live owner click-through as a separate acceptance condition. Those historical
sandbox failures do not establish a permanent limit on every environment.

Watcher comparisons that include ads, navigation or relative timestamps can
report false posting changes. Outcome: fixed structured posting selection and
cleaned-text fallback; arbitrary site chrome remains a limitation of fallback.

An ambient timeout override broke tests that expected the default budget.
Outcome: keep runtime configuration separate from isolated verification settings.

## 2026-10-21 — The nightly pipeline's OOM, and what the cap really does

The kernel's OOM killer picks the biggest process in the slice, not the
one that is growing, so a memory bug in an unattended script showed up as
an unrelated service dying: two nights running, the ATS fetch exhausted
the 3 GiB VM and `hermes-gateway` — the owner's Telegram bot, ~1.3 GiB
resident — was killed instead of the script. Outcome: fixed the growth
itself (the fetch loop folds each tenant into the store and keeps only
its numbers) and put every python leg in its own `systemd-run --scope`
with a memory cap, so the kernel's choice is made inside the scope. Do
not read a service that died of `oom-kill` as a problem with that
service.

`MemoryHigh` is throttling and not a limit, and that is a different
promise than it reads like. Measured on this host: a leg held at
`MemoryHigh` with swap allowed is pushed into the host's 1 GiB of swap
and crawls; with `MemorySwapMax=0` it still stalls rather than dying —
over three minutes and still going, where `MemoryMax` alone ends it in
under a second. Outcome: keep `MemoryHigh` (a throttled leg cannot push
anything else out of memory, which is what the cap is for), keep
`MemorySwapMax=0`, and record that nothing yet puts a wall-clock limit on
a stalled leg. A cap is not a timeout.

Accumulating per-item results to build one run summary at the end is the
shape of this bug, and it is invisible in the output: every number the
summary printed could be folded per tenant and came out identical. The
only aggregate that needed thought was "the 20 first unresolved office
names", which is the same answer taken from the union of each tenant's
own first 20. Outcome: when a loop's summary is built from retained
items, the summary is the thing to make small, not the loop.

## Open questions

Entity disambiguation and full field provenance remain later work; no new
implementation is authorized by these salvaged findings.
