# F8 — Backend Integration, Contract and Failure Tests
**Priority:** P0, CONTINUOUS | **Prerequisites:** execute incrementally after F1–F7 | **Mode:** IMPLEMENT tests and narrowly scoped bug fixes

## Goal
Make backend behavior reproducible, contract-compliant and resilient to fake external provider failures, using offline tests with no real secrets.

## Inspect first
- `backend/tests/` and its fixture conventions
- `contracts/internal-api.openapi.yaml`
- `scripts/check.sh`, `.github/workflows/ci.yml`
- modules changed in the completed features

## Implementation tasks
- [ ] Expand contract coverage from existing health/privacy tests to all eight existing operations with representative successes/errors where schema definitions exist.
- [ ] Add service-level tests with dependency overrides for transaction provider, fraud provider and explanation mock.
- [ ] Exercise expected provider failures: unavailable, timeout, 401/402/429/5xx-like typed failures, malformed response, invalid enum/risk metadata, and mock recovery; no live calls.
- [ ] Verify timeout behavior, 8s frontend deadline compatibility where relevant, rules fallback and truthful `provider_mode`/degraded semantics.
- [ ] Exercise valid/invalid request body sizes (including absent Content-Length), allowed/disallowed Origin, safe errors and consistent headers.
- [ ] Add data privacy tests with sentinel account numbers, raw merchant text, exact timestamps and malicious strings; verify sanitized AI payload, responses and captured logs.
- [ ] Cover SQLite confirmation persistence when memory write fails, consent gate, idempotency, conflicting confirmation, owner scoped memory list/delete.
- [ ] Verify deterministic fixture behavior, stable IDs, empty/no-data cases, no network, no SDK credentials. Do not rely on test order or leftover DB state.
- [ ] Run targeted unit/integration tests and `scripts/check.sh` if viable; document any unrelated failing frontend checks separately.

## Acceptance
- [ ] All new and existing backend tests pass offline; Ruff clean.
- [ ] Contract samples validate, fallback results cannot be mistaken for confirmed fraud, and failure outputs contain no secrets/PII.
- [ ] CI needs no external keys; tests are deterministic and independently runnable.
- [ ] Any production bug discovered is fixed only within the feature scope and reported.

## Stop/coordinate
If upstream provider success schemas are unverified, test the internal mock/interface boundary; explicitly label live provider contract tests as pending, not passed.

# Shared constraints (apply to every feature)

- Work in the **current repository**, not a fresh project. Before edits, read `AGENTS.md`, `README.md`, `contracts/internal-api.openapi.yaml`, relevant `docs/` files and actual implementation. Treat the earlier audit as a pointer, **not guaranteed current truth**.
- Scope: FastAPI backend and backend tests. No frontend edits, no architecture/security policy decisions on behalf of another owner, no live Nessie API implementation, no real Jev HTTP calls, no real Gemini/Backboard integration unless explicitly authorized.
- Preserve existing `/api/v1` routes, JSON `snake_case`, fixed server-side demo user, current OpenAPI schema and working synthetic MVP. **Never create parallel endpoints** (`/api/transactions`, `/api/fraud/analyze`, `/api/assistant/explain`).
- `contracts/internal-api.openapi.yaml` is the team-owned public contract. If completion requires contract changes, **STOP that part**, describe the proposed diff and coordination needed; continue only independent non-breaking work.
- Maintain privacy controls: no raw banking/customer identifiers or merchant text in AI payloads; redact secrets/PII from logs, errors, and tests. `confidence` is NOT a fraud probability. Never claim confirmed fraud or automate account/banking actions.
- Use mocks/stubs for external services. Tests must be deterministic, offline and secret-free; do not install new packages without explaining necessity. Follow existing versions/tools (`pytest`, `ruff`, `scripts/check.sh`).
- Implement **only the requested feature**, make minimal code changes, add targeted tests, run relevant checks, and report changes, test results, unresolved assumptions and any coordination blockers. **Do not commit or push automatically**.
