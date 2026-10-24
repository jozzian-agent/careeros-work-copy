"""Organisation intake capability.

Resolves a loose organisation reference (a posting URL, a free-text
employer name, or both) to one known record, reusing an existing one
whenever the evidence supports it and creating a fresh one when it does
not, then classifies that record by ISIC Rev.4 section and EU
employee-count size class. See docs/capabilities/org-intake.md (the
approved contract this package implements) for the full behavior
specification.

Public entry points, re-exported here for convenience:

    resolve_identity(store, *, url, employer_name=None, fallback_name=None,
                     existing=None, legacy_hint=None,
                     tenant_employer_names=None) -> dict
    classify_sector(record, *, fetch=None, warn=None, deadline=None,
                    collector=None, signals=...) -> (codes_or_None, flag_or_None)
    classify_size(record, *, fetch=None, warn=None, deadline=None,
                  collector=None, signals=...) -> (updates_or_None, flag_or_None)
    detect_ats(url) -> {"provider": str, "tenant": str} | None
    normalize_url(url) -> str

This package never imports a product's storage layer, HTTP client, LLM
client, or clock: every dependency crosses the boundary as a parameter
(store, fetch, warn, deadline). See store.py for the store adapter
protocol.
"""
from org_intake.ats import detect_ats
from org_intake.enrich import classify_sector, classify_size
from org_intake.identity import resolve_identity
from org_intake.url import normalize_url

__all__ = ['resolve_identity', 'classify_sector', 'classify_size', 'detect_ats', 'normalize_url']
