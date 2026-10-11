---
type: Decision
title: "Company classification"
description: "Record the approved company classification scope and superseded draft choices."
timestamp: 2026-10-11
status: approved 2026-10-07
---

# Company classification

Approved 2026-10-07: the owner accepted the classification wireframe with
aggregate removed from the company-kind vocabulary (commit ba4e5e8).
Companies use employer or institution; there is no aggregate directory toggle.
Job classification has function and controlled tags, with company sectors read
through the linked company. Company classification holds kind, ISIC sectors,
size class and review flags rather than duplicating them in the general form.

The earlier taxonomy concept proposed employer, institution and aggregate.
The owner's removal supersedes that proposal and its aggregate-specific rules.
ISIC section storage is also recorded as deliberate in PROJECT.md. Experience
company linking and the frozen fallback label were confirmed on 2026-10-10 in
PROJECT.md; the draft's rename-propagation alternative is not a new decision.

## Open questions

Unconfirmed choices from the draft are preserved in PROJECT.md's open questions,
not promoted to approved decisions merely because code was written.
