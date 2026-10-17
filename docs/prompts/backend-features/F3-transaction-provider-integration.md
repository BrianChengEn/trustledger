# F3 — Transaction Service / Provider Boundary
**Priority:** P0 | **Prerequisites:** F1 helpful | **Mode:** IMPLEMENT with mocks only

## Goal
Make the existing transaction/read paths work through a replaceable provider interface, ready for the Data/API teammate's Nessie adapter, while keeping synthetic behavior working.

## Inspect first
- `backend/app/adapters/synthetic.py`, `backend/app/adapters/nessie.py`
- `backend/app/schemas/transaction.py`, `backend/app/api/routes.py`
- `docs/03-nessie-data.md`, `docs/prompts/nessie-data.prompt.md`
- application dependencies and tests

## Implementation tasks
- [ ] Inspect actual documented provider contract (`list`, `get`, `health` or actual method names); reuse existing interface if present. If undocumented, define the **smallest backend-side Protocol/interface**, no changes to Data-owned live Nessie implementation.
- [ ] Provide synthetic provider conforming to that interface; preserve existing fixtures and transaction ordering, limit behavior, IDs and DTO shape.
- [ ] Add a backend dependency/factory to resolve the active transaction provider. Synthetic remains the default; make selection explicit and fail closed for invalid modes.
- [ ] Refactor current transaction lookup, `/api/v1/transactions`, `/api/v1/analyses`, `/api/v1/alerts` and privacy/confirmation paths **only where necessary** to share a coherent provider and avoid mismatched IDs.
- [ ] Define internal typed adapter failure categories (unavailable, timeout, malformed upstream data, not-found) and a deterministic synthetic fallback policy **only if current documentation explicitly authorizes it**; do not silently disguise live data as real when fallback occurs.
- [ ] Keep raw Nessie IDs out of client-facing and AI-safe DTOs, using pre-existing tokenization strategy if available. Do not invent live Nessie endpoint URLs or response mappings.
- [ ] Add fake Nessie-like test provider through dependency override; do **not** call a real vendor API or implement another teammate's client.

## Tests / acceptance
- [ ] Existing synthetic API outputs still pass their tests.
- [ ] Dependency override with fake provider yields the expected canonical transactions; `.get` consistency and empty data are tested.
- [ ] Failure paths test not-found, timeout/unavailable and invalid adapter output; responses don't reveal vendor tokens.
- [ ] No contract/frontend change; no actual Nessie network dependency.

## Stop/coordinate
If a provider shape cannot be defined from docs and existing code, record a clear interface proposal for the Data/API owner instead of guessing live service behavior.

# Shared constraints (apply to every feature)

- Work in the **current repository**, not a fresh project. Before edits, read `AGENTS.md`, `README.md`, `contracts/internal-api.openapi.yaml`, relevant `docs/` files and actual implementation. Treat the earlier audit as a pointer, **not guaranteed current truth**.
- Scope: FastAPI backend and backend tests. No frontend edits, no architecture/security policy decisions on behalf of another owner, no live Nessie API implementation, no real Jev HTTP calls, no real Gemini/Backboard integration unless explicitly authorized.
- Preserve existing `/api/v1` routes, JSON `snake_case`, fixed server-side demo user, current OpenAPI schema and working synthetic MVP. **Never create parallel endpoints** (`/api/transactions`, `/api/fraud/analyze`, `/api/assistant/explain`).
- `contracts/internal-api.openapi.yaml` is the team-owned public contract. If completion requires contract changes, **STOP that part**, describe the proposed diff and coordination needed; continue only independent non-breaking work.
- Maintain privacy controls: no raw banking/customer identifiers or merchant text in AI payloads; redact secrets/PII from logs, errors, and tests. `confidence` is NOT a fraud probability. Never claim confirmed fraud or automate account/banking actions.
- Use mocks/stubs for external services. Tests must be deterministic, offline and secret-free; do not install new packages without explaining necessity. Follow existing versions/tools (`pytest`, `ruff`, `scripts/check.sh`).
- Implement **only the requested feature**, make minimal code changes, add targeted tests, run relevant checks, and report changes, test results, unresolved assumptions and any coordination blockers. **Do not commit or push automatically**.
