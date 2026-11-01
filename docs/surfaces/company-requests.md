---
type: Surface
title: "Company requests"
description: "Describe the nightly company request pass and the admin review list that answers what it cannot."
timestamp: 2026-11-01
---

# Company requests

Status: built 2026-11-01. Owner ruling of the same day, which asked for
the resolution half of the company request filed by PR #44. The review
list reuses adopted Gestalt components only (Table, Button, TextField,
Text, Box, Flex) under the shared `PageLayout`, so the component gate is
satisfied by that direction. Owner click-test pending.

## Purpose

A company is shared universe and the admin alone writes one, so a user
who meets a posting whose employer is not on file cannot create it. They
ask instead: the job page's company ask files a private company request
with the name they typed ([schemas](../schemas.md), `company_requests`).

That ask has to be answered, or the record is a promise nobody keeps.
Most of them need no judgement at all -- the company IS on file, under a
name that differs by a legal form or by nothing but case -- so those are
answered by a pass that runs while nobody is working. What is left is a
real question, and a question needs a person: the admin, who is the one
person who may write the answer.

Two surfaces, one module. `careeros/company_requests.py` holds the
matching and the writes, and both surfaces call it, so an answer by hand
and an answer overnight write the same fields.

## Appears in

Company browse. The pass has no interface; the review list is a
navigation entry for the admin and for nobody else.

## The nightly pass

`scripts/resolve_company_requests.py`, run by
`deploy/systemd/careeros-company-requests.timer` at 03:30 with up to
half an hour of jitter, and by hand whenever the owner wants the queue
drained. Its own docstring is the contract; what matters here:

Every open request is grouped with the other open requests asking for
the same company, because the same employer gets asked for by several
people and resolving one of them would send the rest round another
night. The group is matched against the shared companies on three rungs,
each an equality:

1. the exact normalized name, which also matches a company's
   `name_variant` identifiers, so a fuzzy case the owner once resolved by
   hand answers itself from then on;
2. a `name_variant` identifier equal to the name as typed;
3. suffix-stripped equality -- "Northwind AG" and "Northwind" are one
   employer (`careeros/company_suffixes.py` holds the curated list of
   legal forms and the one function that takes one off).

A fuzzy candidate is never linked. `org_intake.identity.fuzzy_candidates`
is read in one place only, to put a scored suggestion in front of the
admin, and nothing acts on its output. More than one company matching a
rung is an ambiguity and goes to the admin, never a first-wins pick.

A confident match links every waiting job in the group and settles every
request as `linked`. No match is decided by
`COMPANY_REQUEST_AUTO_CREATE`: off (the default) parks the group as
`needs_admin` and writes no company at all; set to `1` the pass creates
the company itself, links the jobs, settles them as `created` and runs
the same sector/size cascade an intake-created company gets. The switch
only decides what happens when nothing matches.

Two outcomes are settled before any matching, because a request outlives
the job it came from: a request whose job was deleted is `rejected` with
a note saying so, and one whose job somebody has already linked is
settled against the company that job really points at. Neither writes a
company, and neither touches an existing link -- human edits win.

The pass logs counts and never a name, a job id or a user id. The
journal on the box is read by whoever can read the journal, and a
requested company name is a fact about one person's private record.

## Minimal contents (the review list)

One table, one row per request waiting for the admin:

- the name that was asked for;
- who asked, and the posting it came from. The posting is named by its
  id, and by its title only where the admin may read that job: a request
  comes from somebody else's private record, and decision D3 is that the
  admin reaches no part of one;
- the date it was asked;
- the companies already on file that are close to the name, each with its
  score, as a button that links to that one;
- Approve, which creates a company with the requested name and links the
  jobs, and Reject, which takes an optional note.

Nothing else. No filtering, paging or sorting: the queue is what one
nightly pass could not settle, which is a handful of rows, and a control
that exists for a list this short is an element with nothing to do.

Either answer settles every open request asking for that same company,
except a rejection, which is about the one ask it was given.

## States

- **Empty.** The normal state: one box saying no requests are waiting.
  Not a gap to fill, so there is no action in it.
- **Rows.** The table above.
- **Not the admin.** The server's own 403 message, rendered as the page's
  error. The navigation entry is absent for them, all three endpoints
  refuse them, and this page does not restate the rule in order to show
  a friendlier sentence.
- **Load failed.** The message and a Retry, like every other list page.

## Contracts

`GET /api/company-requests`, `POST /api/company-requests/<id>/approve`
and `POST /api/company-requests/<id>/reject`, all admin only. Request and
response shapes are in [JSON page contracts](json-api.md); the stored
record is in [schemas](../schemas.md).

## Open questions

- Whether the requester is told their request was answered. Nothing
  notifies them today: they see it on the job page, which now shows the
  company their posting resolved to. A rejection is the case that reads
  worst, because the ask simply comes back.
- Whether `COMPANY_REQUEST_AUTO_CREATE` ever goes on in production. It
  turns a name one user typed into a shared record nobody reviewed, which
  is exactly what the admin-approval default exists to prevent; the
  switch is there because a queue nobody drains is worse.
- Whether the review list should carry the posting's own extracted
  employer name beside the requested one. It is the evidence the admin
  would most want, and it is text out of a private record, so it needs
  the same decision D3 ruling the job title got here.
