You are the CROSS-REVIEWER for a conceptual design document (no code diff to review; this is a design review).

Context: repo /root/work/careeros-dashboard (Flask + YAML-vault job-hunt dashboard "CareerOS"). Baseline commit: current HEAD of main. The artifact under review is the UNCOMMITTED new file tmp-concept-taxonomy.md (design only; no repo code was modified, verify with git status). The authoring brief that produced it is tmp-brief-concept-taxonomy.md. The owner will make decisions from this doc BEFORE any engineering, so correctness and completeness of the concept matter more than style.

Read tmp-concept-taxonomy.md, tmp-brief-concept-taxonomy.md, and the relevant code (careeros/vault.py, ingest.py, enrich.py, intake.py, server.py, web/theme.py, web/ui.py, templates/) as needed.

Review focus, priority order:
1. FACTUAL ACCURACY about the codebase: every claim the doc makes about current behavior (e.g. "enrich.py derives size buckets from numberOfEmployees", "server.py has find_company casefold dedupe", "vault.py validate pattern", "_save_record defaults allowlist", "intake.py LIST_FIELDS pattern", "theme.py CSS_VARS/BASE_CSS/page_shell concatenation") must actually be true. Verify each with grep/read. A concept built on a false premise about the code is a MAJOR.
2. TAXONOMY CLAIMS: check the external-standard facts the doc asserts (ISIC Rev.4 has 21 sections; ISCO-08 unit group numbers cited, e.g. 1330 "ICT service managers", 2512, 2412; ESCO includes an ICT product manager concept distinct from generic PM; EU 2003/361/EC thresholds micro<10, small<50, medium<250; ESCO occupations carry parent ISCO mapping; Wikidata P452 industry / P1128 employees properties). Flag wrong codes/thresholds as MAJOR, imprecise framing as MINOR. You may use web search if available; if not, flag anything you cannot confirm as UNVERIFIED rather than asserting.
3. INTERNAL CONSISTENCY: section 2 facet model vs section 4 function facet vs section 3 sectors; tags.yaml facet-qualified id format ("skill/capability:project-management" - is a slash inside a YAML mapping key + colon inside a tag id sane? consider parsing and URL-encoding implications); kind flag vs enrichment guards vs aggregate hiding; company_id sync-cache rule vs owner-wins rule.
4. MIGRATION/COMPATIBILITY RISKS: additive migrations claimed backwards compatible - any hidden breakage for existing loaders, watcher hash_version (does adding fields to company/experience records affect the watcher's structured hash or history?), API consumers, the fill-empty-only enrichment merge rule?
5. COMPLETENESS vs the authoring brief: all 5 requirements covered, options + recommendation + decision points + engineering breakdown in each, consolidated decision sheet at end.
6. CONSTRAINTS: no contractions, no em/en dashes (hyphens fine); no real owner career content (check the examples are synthetic/plausible, no real salary data); no LAN IPs/ports/LLM provider or model names anywhere in the doc; no hardcoded LLM endpoint proposals.

Rules: review only, modify NOTHING. At the end run git status and confirm only the two tmp-*.md files are untracked and nothing else changed.

Findings format: MAJOR / MINOR / NIT, each with file:line (tmp-concept-taxonomy.md lines) or code file:line evidence, and a concrete suggested fix for each. Use in-memory/deterministic probes (python - <<PY snippets, grep) to substantiate suspicions about code claims - do not report a code-fact finding without a probe.

End with a one-paragraph verdict: is this concept doc ready to present to the owner for decisions, what must be fixed first.
