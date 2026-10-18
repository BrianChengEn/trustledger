# F1 — API Contract Compliance
**Priority:** P0 | **Prerequisites:** none | **Mode:** IMPLEMENT after inspection

## Goal
Make current FastAPI request/response validation conform to the *existing* OpenAPI contract without changing routes or successful response shapes.

## Inspect first
- `contracts/internal-api.openapi.yaml` (actual authoritative constraints)
- `backend/app/api/routes.py`
- `backend/app/schemas/api.py`, `backend/app/schemas/transaction.py`
- `backend/app/main.py`
- existing backend API/contract tests

## Implementation tasks
- [ ] Inventory all 8 current operations and compare declared parameter types, bounds, required fields, additional properties, status codes, response envelopes and examples against actual FastAPI behavior.
- [ ] Enforce **actual contract-defined** path ID minimum/maximum length, without choosing arbitrary values. Preserve 404 semantics for valid-but-unknown IDs; invalid shape must produce a safe validation error.
- [ ] Enforce evidence item length (audit indicates maximum **180 characters**, confirm in YAML), evidence count, and any other documented field constraints through Pydantic validation.
- [ ] Ensure `Transaction.occurred_at` is timezone-aware according to canonical transaction/data documentation; reject or normalize naive values **only as documented** and keep consistent ISO 8601 responses.
- [ ] Reconcile Pydantic types/config with contract: reject unknown request fields where required and avoid leaking extra response fields.
- [ ] If the current code has error responses not fully represented by `ErrorEnvelope`, implement internal typed validation/error models **without changing existing wire payloads**, unless approval is required.
- [ ] Preserve `/api/v1` routes and fixed demo identity; do not add authentication or new request owner parameters.

## Tests / acceptance
- [ ] Add positive and boundary tests for path IDs, evidence sizes, query `limit` (documented 1–100, default 25), strict request bodies, and timezone-aware transaction data.
- [ ] Validate representative success payloads against the actual contract; include safe 404/409/422 behavior where currently documented.
- [ ] Existing frontend-facing response fields and the original eight operations remain unchanged.
- [ ] Run backend unit/integration tests and Ruff; record exactly what passed.

## Stop/coordinate
If any rule in docs contradicts contract or code, report the discrepancy and propose a contract update, but do not silently choose or edit the shared YAML.

# Shared constraints (apply to every feature)

- Work in the **current repository**, not a fresh project. Before edits, read `AGENTS.md`, `README.md`, `contracts/internal-api.openapi.yaml`, relevant `docs/` files and actual implementation. Treat the earlier audit as a pointer, **not guaranteed current truth**.
- Scope: FastAPI backend and backend tests. No frontend edits, no architecture/security policy decisions on behalf of another owner, no live Nessie API implementation, no real Jev HTTP calls, no real Gemini/Backboard integration unless explicitly authorized.
- Preserve existing `/api/v1` routes, JSON `snake_case`, fixed server-side demo user, current OpenAPI schema and working synthetic MVP. **Never create parallel endpoints** (`/api/transactions`, `/api/fraud/analyze`, `/api/assistant/explain`).
- `contracts/internal-api.openapi.yaml` is the team-owned public contract. If completion requires contract changes, **STOP that part**, describe the proposed diff and coordination needed; continue only independent non-breaking work.
- Maintain privacy controls: no raw banking/customer identifiers or merchant text in AI payloads; redact secrets/PII from logs, errors, and tests. `confidence` is NOT a fraud probability. Never claim confirmed fraud or automate account/banking actions.
- Use mocks/stubs for external services. Tests must be deterministic, offline and secret-free; do not install new packages without explaining necessity. Follow existing versions/tools (`pytest`, `ruff`, `scripts/check.sh`).
- Implement **only the requested feature**, make minimal code changes, add targeted tests, run relevant checks, and report changes, test results, unresolved assumptions and any coordination blockers. **Do not commit or push automatically**.
