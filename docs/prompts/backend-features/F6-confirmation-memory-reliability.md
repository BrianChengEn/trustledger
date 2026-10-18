# F6 — Confirmation Persistence & Memory Reliability
**Priority:** P1 | **Prerequisites:** F1; may be done independently of F3–F5 | **Mode:** IMPLEMENT

## Goal
Ensure the user's confirmation is durably recorded even when optional memory writing fails; preserve explicit consent and locally stored sanitized summaries.

## Inspect first
- `backend/app/core/store.py`
- `backend/app/services/ai/memory_policy.py`, `privacy.py`
- `backend/app/api/routes.py`, `schemas/api.py`
- `docs/04-fastapi-integration-deployment.md` (confirmation failure semantics)
- `docs/01-ai-engineer-jev-backboard.md`, OpenAPI

## Implementation tasks
- [ ] Trace current SQLite transaction boundaries. Fix ordering/transaction handling so **confirmation persists first**; subsequent optional memory failure cannot roll back the confirmation.
- [ ] Keep idempotency and existing 409 conflict semantics. Repeat same confirmation should not insert duplicates or create multiple memories; conflicting updates still behave as documented.
- [ ] Keep memory creation gated by **normal outcome + explicit consent + enabled setting**. Reject or skip writes otherwise; do not automatically backfill without permission.
- [ ] Preserve owner-scoped list/delete and avoid storing raw IDs, merchant names, exact amounts or full transaction text in memory.
- [ ] Handle optional write failure clearly but **without changing the external confirmation response schema** without approval. If status reporting needs new fields, propose separately.
- [ ] Implement lookup of prior confirmed *safe* memory into `prior_user_confirmation` when it is documented and truly relevant; retain `unknown` when missing, and prevent unsafe cross-owner inference or raw data leakage.
- [ ] Use existing SQLite/local memory only; do not wire real Backboard or Gemini.
- [ ] Be careful about concurrent requests/SQLite locking and atomicity of the authoritative confirmation record.

## Tests / acceptance
- [ ] Inject a memory insert failure and assert confirmation remains committed.
- [ ] Test normal+consent+enabled, missing consent, disabled writes and non-normal outcomes.
- [ ] Test idempotent repeat, conflicting repeat (409), list/delete owner scope and prior-confirmation safe lookup.
- [ ] Confirm current request/response contract and security boundaries remain intact.

## Stop/coordinate
If current docs disagree on `ALLOW_MEMORY_WRITE` default or safe memory lookup keys, use behavior currently required by the authoritative contract/source and report the unresolved policy rather than silently changing global defaults.

# Shared constraints (apply to every feature)

- Work in the **current repository**, not a fresh project. Before edits, read `AGENTS.md`, `README.md`, `contracts/internal-api.openapi.yaml`, relevant `docs/` files and actual implementation. Treat the earlier audit as a pointer, **not guaranteed current truth**.
- Scope: FastAPI backend and backend tests. No frontend edits, no architecture/security policy decisions on behalf of another owner, no live Nessie API implementation, no real Jev HTTP calls, no real Gemini/Backboard integration unless explicitly authorized.
- Preserve existing `/api/v1` routes, JSON `snake_case`, fixed server-side demo user, current OpenAPI schema and working synthetic MVP. **Never create parallel endpoints** (`/api/transactions`, `/api/fraud/analyze`, `/api/assistant/explain`).
- `contracts/internal-api.openapi.yaml` is the team-owned public contract. If completion requires contract changes, **STOP that part**, describe the proposed diff and coordination needed; continue only independent non-breaking work.
- Maintain privacy controls: no raw banking/customer identifiers or merchant text in AI payloads; redact secrets/PII from logs, errors, and tests. `confidence` is NOT a fraud probability. Never claim confirmed fraud or automate account/banking actions.
- Use mocks/stubs for external services. Tests must be deterministic, offline and secret-free; do not install new packages without explaining necessity. Follow existing versions/tools (`pytest`, `ruff`, `scripts/check.sh`).
- Implement **only the requested feature**, make minimal code changes, add targeted tests, run relevant checks, and report changes, test results, unresolved assumptions and any coordination blockers. **Do not commit or push automatically**.
