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

## Open questions

Entity disambiguation and full field provenance remain later work; no new
implementation is authorized by these salvaged findings.
