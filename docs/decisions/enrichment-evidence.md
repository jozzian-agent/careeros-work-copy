---
type: Decision
title: "Enrichment evidence"
description: "Preserve the implemented evidence and fallback choices for enrichment."
timestamp: 2026-10-11
---

# Enrichment evidence

Recorded implementation decisions from the enrichment fixes of 2026-10-07
(JOZ-260 through JOZ-262); this record does not imply a new owner approval.

- Every considered signal and field records matched, ambiguous, empty,
  not-attempted, rate-limited or fetch-error. A failure for one field must not
  discard valid evidence for the other. Skipped signals remain distinguishable
  from attempted signals that found nothing.
- Sector ambiguity fills nothing and raises review flags (Decision-20).
  Specific phrases defeat generic keywords only through substring specificity;
  unrelated activities remain ambiguous. Conflicting sources do not acquire
  priority merely by returning a confident answer.
- Structured evidence runs before optional AI fallback. AI is not invoked after
  a usable structured result or a structured conflict. Its feature gate lives
  in the signal wrapper so direct callers receive the same protection.
- AI sector and size hints require high confidence. A valid sector code can be
  accepted without a keyword match, but a confidently contradictory rationale
  is refused. Prompts use company-identifying fields, never job descriptions.
- A size-class hint fills only size_class, never an invented count or range.
  Both count and hint paths preserve populated values, check consistency with
  the other size field, and flag contradictions rather than overwrite them.
- Employee counts prefer the latest usable date on a non-deprecated statement;
  otherwise use the first non-deprecated statement. This supersedes the draft
  taxonomy decision 19, which proposed refusing undated statements. Missing or
  unparseable counts are absent evidence, not transport failures.
- Network planning stays outside the vault write lock; local application stays
  under it. Rate-limit retries are bounded, honor numeric and date Retry-After
  values, and use synchronized pacing.

## Open questions

None introduced by this salvage. Product-wide provenance and asynchronous
write guarantees remain in the [add-job flow](../flows/add-job-by-link.md).
