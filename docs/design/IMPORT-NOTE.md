---
type: Note
title: "CAREER-120 — design package import record"
description: "What was imported into docs/design/ on 2026-10-31, what was not, and why."
timestamp: 2026-10-31
---

# CAREER-120 — design package import record

The owner's CareerOS design-system package was delivered over Telegram and
staged verbatim under `docs/design/` on 2026-10-31. Nothing in it was edited,
reformatted or renamed: the files are the imported artifact as authored.
`HANDOVER.md` carries the package's own date, "Updated 2026-10-26".

## What was verified

Checked against `docs/design/manifest.json` (`manifestVersion: 3`):

| Check | Result |
|---|---|
| `components[]` entries with a `components/<Name>/README.md` on disk | 30 / 30 |
| `files[]` paths present on disk | 32 / 33 — only `tokens.css` missing |
| Component directories on disk | 31 (the 30 above plus `Cover/`) |
| Imported package files (excluding ALIGNMENT.md and IMPORT-NOTE.md) | 57 |
| Total files currently under `docs/design/` | 59 |

`tokens.json` carries its own `"version": 2`; that is a separate field from the
manifest's `manifestVersion: 3` and the two do not contradict each other.

### `components/Cover/`

`Cover/` holds a `preview.html` and no `README.md`, and "Cover" is not an entry
in the manifest's `components[]`. It is kept as delivered rather than dropped,
because the package is staged verbatim.

### The preview files

21 of the 30 manifest components ship a `preview.html` alongside their README,
plus `Cover/preview.html`, for 22 in total. `preview.html` is not listed in the
manifest's `files[]` at all, in any directory — these are bonus renderings, not
a gap in the manifest. Within the imported package, `README.md`, `tokens.json`
and `manifest.json` are also outside `files[]`. The repository additionally
contains `ALIGNMENT.md` and `IMPORT-NOTE.md`, which are outside `files[]` too.

## `tokens.css`: listed, not delivered, not needed

`tokens.css` is the one `files[]` entry with nothing behind it. Owner ruling:
it is not needed. `tokens.json` holds the same values in structured form, and
the repo keeps `frontend/src/design/tokens.css` as its own implementation file —
that is the file `HANDOVER.md`'s PR 1 targets, by repo token name. Vendoring a
second `tokens.css` under `docs/` would put two editable copies of one value set
in the tree.

## The rendered HTML exports: received, deliberately not imported

Two rendered HTML exports came through the same chat and were intentionally left
out of the repo: `Blueprint(1).html`, and a canvas export of about 4.8 MB. Both
are large single-file renderings whose content already exists here as
`BLUEPRINT.md` and the component READMEs, so importing them would add
binary-ish, duplicate artifacts to version control. They remain in the
orchestrator's chat cache. UNVERIFIED: the two filenames and the 4.8 MB figure
are from the orchestrator's record of the chat, not checkable against this
repository, since neither file was imported.

## Supersedes the earlier handoff

This package supersedes the older design handoff that the repo refers to as the
"2026-10-26 handover" (`docs/decisions/design-system.md`,
`frontend/BUILD_NOTES.md`, `frontend/README.md`). That handoff was never
vendored here — only referenced — so the vocabulary change is visible in the
component names: the current set is the 30 in `manifest.json`.

UNVERIFIED: the specific claim that `CompanyCard`, `CriteriaCard` and
`ExperienceCard` are the earlier handoff's names for components this package
renames. Those three strings appear in no file in this repository (checked
across `.md`, `.jsx` and `.json`), so the old names cannot be confirmed from the
tree; they are reported from the owner's description of the earlier handoff.

## See also

`ALIGNMENT.md` — this package's `tokens.json` compared against the repo's
`frontend/src/design/tokens.css` and `docs/decisions/design-system.md`.
