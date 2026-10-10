# Batch D sketches — JOZ-270 and JOZ-271

## Intent anchor

Simplify editing search criteria and put the readable job summary first, serving
PROJECT.md's M1 audit and the Intent of helping job seekers find jobs they like.
Reuse the existing cards, criteria API, save rollback, native details control and
AI badge. Remove per-card edit controls and description splitting. No new surface,
dependency or data field is needed. This requested document records the approved
sketches and live acceptance checks; it is the only added file.

Visual contract: `/tmp/batchd_mockup.html`, fixed spacing version. Existing app dark
theme controls and tokens are reused. No broader design-system migration.

Owner verdict (verbatim): "ok, apart from spacing on this i guess it is fine".
Spacing was fixed in the approved mockup afterward.

## Search — single edit mode

### Purpose

Edit all criteria together, saving once or discarding the whole edit.

### Appears in

Search → Edit criteria → edit lists and notes → Done or Cancel.

### Minimal contents / text sketch

From the build brief:

> ONE right-aligned bar above the grid: a single "Edit criteria" primary button.
> While edit mode is ON, it is replaced by "Done" + "Cancel" (same bar position).
> Edit mode ON: every criteria card shows its add-input row (input flexes to
> near-full card width, Add button right) and each list item gets a × remove
> button. Notes swaps its read paragraph for a full-width textarea (label above).

```
                                      [Edit criteria]
[Roles                         ] [Must-haves                   ]
[Nice-to-haves                  ] [Avoid                        ]
[Notes                                                         ]

Editing:                              [Done] [Cancel]
Each list: item [×] … then [Add an item                  ] [Add]
Notes: label above full-width textarea
```

List rows use 6px vertical padding, subtle dividers except on the last item,
12px before ×, and 12px above add rows with an 8px gap.

### States

- No criteria: existing Create criteria path stays unchanged.
- Read: no per-card edit or remove controls. Empty lists say No items yet;
  empty notes say No notes yet. There is no filtering/no-match state.
- Editing: a working copy holds adds, removals and notes; nothing is sent yet.
- Done: one full-object POST, optimistic read view, concurrent saves blocked.
- Cancel: restore the entry backup without a POST.
- Save failure: restore the entry backup and show the error toast.

Approved 2026-10-10 (owner click-test, mockup)

Deferred: nothing.

### Open questions

None about the sketch. Live implementation acceptance remains an owner check.

## Job detail — summary first

### Purpose

Read the summary first and expand source text only when needed.

### Appears in

Jobs → job detail → read Summary → optionally expand Original posting text.

### Minimal contents / text sketch

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

### States

Summary and source description each render only when present; whitespace-only
source text stays hidden. Source text starts collapsed at every length, preserves
whitespace and escapes HTML. Summary provenance controls only the AI chip.
Pending/polling, retry, company review, watch, delete and job form stay unchanged.

Approved 2026-10-10 (owner click-test, mockup)

Deferred: nothing.

### Open questions

None about the sketch. Live implementation acceptance remains an owner check.

## Verification and live acceptance

Automated command: `.venv/bin/python -m pytest -q`. Flask tests cover single edit
affordance, card order, collapsed full source text and AI provenance. A Node test
executes the served Search script for local edits, Cancel, one POST, the busy
guard and failed-save rollback. All tests use synthetic fixtures.

Owner click-through on a running instance with sample data:

1. Open Search. Enter edit mode; add/remove in multiple cards and change notes.
   Cancel and verify every saved value returns.
2. Repeat and choose Done. Verify one save, persistence after reload, full-width
   add inputs and notes textarea, dark controls and list spacing on mobile too.
3. Open a job with summary and original text. Verify card order, the source text
   starts collapsed and expands in full; check AI and non-AI summary headings.

The existing `scripts/verify.py` was migrated in this change: its Search steps now
drive the single edit mode (`Edit criteria`, add input, `Done`) instead of the removed
per-card `Edit roles` button. Its pre-existing stale `Enrich pending` step on the Jobs
page predates this brief and is left for separate work. Broader restyling and API changes were skipped because existing
elements suffice; revisit only under a separate approved brief.

A supplemental Chromium click check was attempted on 2026-10-10 using rendered
sample-fixture HTML. Chromium could not launch in the sandbox (`Operation not
permitted`); no browser screenshot or live implementation acceptance is claimed.

Validation 2026-10-10: `.venv/bin/python -m pytest -q` — 892 passed,
0 skipped (skip list: none). Independent plan and diff reviews found no blockers.
