# capa-repo

Portable capability packages developed under the agent-toolkit convention.
Each package is a self-contained, product-agnostic Python package with its
own contract, test suite, and no runtime dependency on any host product.

## Packages

### org_intake

Employer-intake capability: resolves a loose organisation name or URL into a
canonical identity record, then enriches it with sector, size-class, and
identifier signals from structured lookups, network evidence, and (optionally)
an LLM signal, under strict provenance and owner-write rules.

- Contract: `docs/capabilities/org-intake.md` in the owning product
  (careeros-dashboard), tracker JOZ-276.
- Ported from the product's `careeros/intake.py`; attribution kept in
  docstrings, no runtime imports from the product.
- Tests: `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q` (233 passing).

## Layout

    org_intake/    capability package
    tests/         full test suite
