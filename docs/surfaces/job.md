---
type: Surface
title: "Job"
description: "Describe the approved summary-first job detail page."
timestamp: 2026-10-11
---

# Job

## Purpose

Read the summary first and expand source text only when needed.

## Appears in

Jobs → job detail → read Summary → optionally expand Original posting text.

## Minimal contents

Visual contract: [approved mockup](batch-d-mockup.html), fixed spacing version. Existing app dark
theme controls and tokens are reused. No broader design-system migration.

Owner verdict (verbatim): "ok, apart from spacing on this i guess it is fine".
Spacing was fixed in the approved mockup afterward.


From the build brief:

> Give it an explicit <h2>Summary</h2> with the "AI-generated" chip inside the
> heading — only when job.summary_source == 'ai'. Non-AI summary: no chip.
> Original description: collapse into a <details class="original-desc"> with
> summary text "Original posting text (from source)" placed directly UNDER the
> summary card (its own card).
> choose whole-text-in-details (simpler, one element less).

```
Header / pending and company-review blocks (unchanged)
[Summary  [AI-generated only for AI source]                     ]
[▸ Original posting text (from source)                          ]
[Skills                                                        ]
[Responsibilities                                              ]
[Background required, if present                               ]
[Function, if present                                          ]
[Classification                                                ]
[Certifications, if present                                    ]
[Existing metadata / Check posting                             ]
Existing job form, notes, deletion and history
```

Secondary cards preserve their actual existing relative order: Background,
Function, Classification, Certifications. This resolves the brief's differently
ordered enumeration using its explicit instruction to keep relative order.

## States

Summary and source description each render only when present; whitespace-only
source text stays hidden. Source text starts collapsed at every length, preserves
whitespace and escapes HTML. Summary provenance controls only the AI chip.
Pending/polling, retry, company review, watch, delete and job form stay unchanged.

Approved 2026-10-10 (owner click-test, mockup)

Deferred: nothing.

## Open questions

None about the sketch. Live implementation acceptance remains an owner check.


Live acceptance checks: check summary and source order, expand the whole source, and compare AI and non-AI headings.

Verification: `.venv/bin/python -m pytest tests/ -q`. Owner implementation
click-test remains pending; the approved mockup is not implementation acceptance.
