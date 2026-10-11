---
type: Surface
title: "Preferences"
description: "Describe the approved single edit mode for search preferences."
timestamp: 2026-10-11
---

# Preferences

## Purpose

Edit all criteria together, saving once or discarding the whole edit.

## Appears in

Search → Edit criteria → edit lists and notes → Done or Cancel.

## Minimal contents

Visual contract: [approved mockup](batch-d-mockup.html), fixed spacing version. Existing app dark
theme controls and tokens are reused. No broader design-system migration.

Owner verdict (verbatim): "ok, apart from spacing on this i guess it is fine".
Spacing was fixed in the approved mockup afterward.


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

## States

- No criteria: existing Create criteria path stays unchanged.
- Read: no per-card edit or remove controls. Empty lists say No items yet;
  empty notes say No notes yet. There is no filtering/no-match state.
- Editing: a working copy holds adds, removals and notes; nothing is sent yet.
- Done: one full-object POST, optimistic read view, concurrent saves blocked.
- Cancel: restore the entry backup without a POST.
- Save failure: restore the entry backup and show the error toast.

Approved 2026-10-10 (owner click-test, mockup)

Deferred: nothing.

## Open questions

None about the sketch. Live implementation acceptance remains an owner check.


Live acceptance checks: edit multiple criteria, Cancel to restore, then Done and reload; check mobile spacing.

Verification: `.venv/bin/python -m pytest tests/ -q`. Owner implementation
click-test remains pending; the approved mockup is not implementation acceptance.
