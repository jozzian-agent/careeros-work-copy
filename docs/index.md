---
type: Index
title: "Documentation"
description: "Catalog the current CareerOS documentation."
timestamp: 2026-10-15
---

# Documentation

- [Accounts and login](surfaces/accounts.md): Describe the login page, the logout affordance, the health check and the accounts command line.
- [Empty description and summary in the live vault](audits/redaction-residue.md): Name every live job whose description or summary is empty, what the record says about why, and what a re-read could restore.
- [Company enrichment](company-enrichment.md): Describe the company enrichment endpoint and stored output.
- [Organisation intake](capabilities/org-intake.md): Contract for the capability that resolves a loose organisation reference to a known, classified record.
- [Company classification](decisions/company-classification.md): Record the approved company classification scope and superseded draft choices.
- [JOZ-273 — Gestalt integration mode: decision note](decisions/design-system.md): Record the approved full React integration of Gestalt.
- [Enrichment evidence](decisions/enrichment-evidence.md): Preserve the implemented evidence and fallback choices for enrichment.
- [Intake persistence](decisions/intake-persistence.md): Preserve durable intake, duplicate and watcher persistence choices.
- [CareerOS — Journey Specs (handoff to coding agent)](flows/add-job-by-link.md): Describe adding a job by link and the constraints on later journeys.
- [Intake enrichment](intake-pipeline.md): Describe intake enrichment, concurrency and failure handling.
- [Kanban interactions](kanban.md): Describe interactions on the Jinja job board.
- [Learnings](learnings.md): Carry forward dated surprises from enrichment, intake and verification.
- [Link styling convention](link-styling.md): Describe the Jinja theme treatments for internal and external links.
- [Responsive breakpoint convention](responsive.md): Describe the Jinja theme breakpoint and responsive treatments.
- [Give a vault's jobs their coded value records](runbooks/migrate-job-value-records.md): Back up a vault, run the CAREER-57 classification migration against it, verify it, roll it back, and know what the second step still owes.
- [Move a vault onto the D7 status list](runbooks/migrate-board-d7.md): Back up a vault, run the one-time D7 status migration against it, verify it and roll it back.
- [Seed the function facet in a vault](runbooks/seed-function-facet.md): Run the one-time function-facet seed against a live vault and verify it.
- [Vault schemas — Chunk 3](schemas.md): Describe vault records and their JSON API representation.
- [Job](surfaces/job.md): Describe the approved summary-first job detail page.
- [Jobs](surfaces/jobs.md): Describe the approved React Jobs board and its acceptance state.
- [M1 JSON page contracts](surfaces/json-api.md): Describe JSON representations for existing dashboard pages.
- [Notes](surfaces/notes.md): Describe the note, its editing window and the read-only Notes page.
- [Preferences](surfaces/preferences.md): Describe the approved single edit mode for search preferences.
- [Taxonomy](surfaces/taxonomy.md): Describe the read-only vault-wide taxonomy page.

## Open questions

See PROJECT.md and each surface for unresolved product choices.
