# F5 — End-to-End Backend Analysis Orchestration
**Priority:** P0 | **Prerequisites:** F3, F4 | **Mode:** IMPLEMENT

## Goal
Wire the working backend path: transaction lookup → deterministic/privacy-safe features → mockable fraud provider → existing `Analysis`/alerts output, without breaking confirmation or existing frontend UX.

## Inspect first
- `/api/v1/analyses`, `/api/v1/alerts` implementations in `routes.py`
- current transaction selection and rule implementation
- `privacy.py`, schemas, provider interfaces from F3/F4
- OpenAPI contract, relevant tests

## Implementation tasks
- [ ] Extract orchestration into a backend service instead of placing vendor/risk logic in HTTP routes; keep route thin.
- [ ] Lookup transaction only for the fixed server-side demo identity/current provider; reject unknown IDs through existing error convention.
- [ ] Build a privacy-safe feature snapshot, validate allowlisted shape, feed only this to the mock fraud provider, and prevent raw merchant/account identifiers from being passed downstream.
- [ ] Validate internal provider assessment, then construct the **existing** `Analysis` model, preserving identifiers, evidence limits, request ID, model/provider metadata and human-review flag.
- [ ] Implement safe deterministic fallback on provider failure; never mark an unscored/unavailable result as low risk solely because the provider failed.
- [ ] Confirm `/api/v1/alerts` continues to derive/serve alerts coherently with analyses, including transaction consistency and stable UI consumption; avoid extra model/API calls on GET unless already documented.
- [ ] Ensure timeouts fit the frontend's documented 8s client timeout; do not add synchronous external provider calls in this phase.
- [ ] Maintain current consent flow; analysis must not write long-term memory implicitly.
- [ ] Keep Gemini explanation out of this feature (F7 handles an internal stub only).

## Tests / acceptance
- [ ] One fixture transaction yields the documented analysis and corresponding alert with stable IDs/semantics.
- [ ] Empty/not-found, invalid provider response, exception, and timeout all return correct safe behavior.
- [ ] Verify provider receives only safe features and no raw inputs.
- [ ] All eight existing HTTP operations remain operable and frontend-compatible.
- [ ] Backend lint and test suite pass.

## Stop/coordinate
If mapping requires unknown Jev score semantics or a new outward response field, keep current deterministic rules outwardly and document the proposed future change.

# Shared constraints (apply to every feature)

- Work in the **current repository**, not a fresh project. Before edits, read `AGENTS.md`, `README.md`, `contracts/internal-api.openapi.yaml`, relevant `docs/` files and actual implementation. Treat the earlier audit as a pointer, **not guaranteed current truth**.
- Scope: FastAPI backend and backend tests. No frontend edits, no architecture/security policy decisions on behalf of another owner, no live Nessie API implementation, no real Jev HTTP calls, no real Gemini/Backboard integration unless explicitly authorized.
- Preserve existing `/api/v1` routes, JSON `snake_case`, fixed server-side demo user, current OpenAPI schema and working synthetic MVP. **Never create parallel endpoints** (`/api/transactions`, `/api/fraud/analyze`, `/api/assistant/explain`).
- `contracts/internal-api.openapi.yaml` is the team-owned public contract. If completion requires contract changes, **STOP that part**, describe the proposed diff and coordination needed; continue only independent non-breaking work.
- Maintain privacy controls: no raw banking/customer identifiers or merchant text in AI payloads; redact secrets/PII from logs, errors, and tests. `confidence` is NOT a fraud probability. Never claim confirmed fraud or automate account/banking actions.
- Use mocks/stubs for external services. Tests must be deterministic, offline and secret-free; do not install new packages without explaining necessity. Follow existing versions/tools (`pytest`, `ruff`, `scripts/check.sh`).
- Implement **only the requested feature**, make minimal code changes, add targeted tests, run relevant checks, and report changes, test results, unresolved assumptions and any coordination blockers. **Do not commit or push automatically**.
