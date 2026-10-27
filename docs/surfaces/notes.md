---
type: Surface
title: "Notes"
description: "Describe the note, its editing window and the read-only Notes page."
timestamp: 2026-10-14
---

# Notes

Status: built 2026-10-14 (owner round on package 1). The owner asked for
this directly and approved the surfaces in the same message, reusing the
adopted Gestalt components only; the component gate is satisfied by that
direction. Owner click-test pending.

## Purpose

A note is something the owner wants to remember about one job or one
company: a title and a body. Before this round each record had one
free-text notes field, so a second thought overwrote the first and there
was nowhere to see what you had written across the vault.

A note belongs to exactly one record, and what associates them is that
the note lives in that record's file. Nothing indexes notes separately,
so a note can never point at a record that is gone.

CAREER-41 (owner decision 2026-10-26): a note also belongs to exactly
one author. Every signed-in user may add a note to a company, and a
company note is visible to its author alone -- the admin included. A
note written before authorship existed carries no `author_id`, reads as
the admin's, and is never rewritten to gain one. Somebody else's note
answers 404 on edit and delete, exactly like a note that never existed.
Job notes were already private (their record is) and are unchanged.

## Appears in

- Job detail → Notes section → Add a note / Edit / Delete.
- Company detail → Notes section → the same three.
- Nav → Notes (`/notes`) → a note's record link → that record's page.

Endpoints: `POST /api/jobs/<id>/notes`, `PATCH` and `DELETE` on
`/api/jobs/<id>/notes/<note_id>`, the same three under
`/api/companies/<id>`, and `GET /api/notes` for the page
([contracts](json-api.md)).

## Minimal contents

**The Notes section** (one component, both detail pages). One row per
note: the title in bold, the body's first line, and the date the note was
added. Edit and Delete per row, both naming their note, and "Add a note"
below the rows. With no notes, the dashed empty state says "No notes yet."
and holds the same "Add a note".

**The note window** (`NotePopup`). Title and a multi-line body, Save note
and Cancel. The same window adds a note and edits one, because writing a
note and rewriting it are the same act. The title field takes focus on
open, and Save note is disabled until there is a title. Notes are not in
Edit job or Edit company anymore.

**The Notes page** (`/notes`). Every note in the vault, newest first: the
title, the body's first line, a link reading "JOB-036 title" or "CO-044
name" to the record that holds it, then "Added <date>" and, only when it
says something more, "Updated <date>". Read-only: a note is written on
the page of its own record, so this page links through rather than being
a second editing surface.

## States

- A note needs a title; a body may be empty. The window refuses to save
  without a title and shows the endpoint's own message when a save fails,
  staying open so nothing typed is lost.
- Delete asks first, through the shared confirmation template, and a
  failed delete renders inside that confirmation.
- A record with no notes shows the dashed empty state. No notes anywhere
  shows the page's quiet message, which says notes are added from a job
  or a company page.
- Loading and a load error with Retry on the page.
- A note migrated out of the legacy free-text field has no write-time,
  because that field never recorded one. Every surface shows no date for
  it rather than inventing one, and it sorts last on the page.

## Open questions

- A note belongs to one record. The owner raised attaching one note to
  both a job and a company; that is not in this round, and containment
  would have to change for it.
- The legacy free-text `notes` field is still a writable record field for
  one release. Nothing in the interface writes it. Removing it is a
  separate change, once no record still holds notes only in that shape.
- Owner click-test on the live instance: pending.
