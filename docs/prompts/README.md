# TrustLedger — FastAPI Backend Feature Implementation Plan

**Context:** Technica 2026, synthetic-first B2C transaction anomaly / financial-safety assistant.
**Source:** Repository audit supplied by the team (audited `backend` branch at `0ab14b8`); the audit is historical. Codex must re-inspect the current branch before any change.
**Your ownership:** FastAPI APIs, service orchestration, validation, failure handling, backend tests. React, high-level security architecture and live Nessie data integration are teammates' responsibilities.

## How to use with Codex CLI
1. Copy this folder into the repository, for example `docs/prompts/backend-features/`.
2. Give Codex one scoped file at a time: `Read docs/prompts/backend-features/F1-api-contract-compliance.md and implement ONLY F1. Observe the shared constraints in README.md in that folder.`
3. After each feature, read the diff and test report before proceeding. **Do not feed all F1–F9 in one implementation request.**
4. If a feature requires changes to the shared OpenAPI contract, frontend, or another teammate's vendor client, Codex must stop *that part* and propose the precise coordination needed.

## Current baseline from the audit
- Working synthetic FastAPI MVP with **8** `/api/v1` operations: `GET /health`, `GET /transactions`, `POST /analyses`, `GET /alerts`, `GET /privacy/preview/{transaction_id}`, `POST /alerts/{alert_id}/confirmations`, `GET /memories`, `DELETE /memories/{memory_id}`.
- React client already calls `/api/v1`; shared contract lives in `contracts/internal-api.openapi.yaml`.
- Synthetic rules, privacy inspector, SQLite confirmations/consented memories work locally, but contract/safety and persistence gaps remain.
- Nessie, Jev and Backboard are stubs; **Gemini does not yet exist in the repo**. For this phase: interfaces/mocks only; *no real vendor clients*.
- Rule-matched confidence is not a validated fraud probability. No definitive fraud verdict, financial advice, automated transfer or account blocking.

## Feature order and delivery

| Feature | Priority | Deliverable | Dependencies | Type |
|---|---|---|---|---|
| **F1** Contract Compliance | P0 | Accurate validation, error model, contract tests | None | Backend |
| **F2** Error & Baseline Security | P0 | Actual body cap, safe errors, consistent headers | F1 helpful | Backend |
| **F3** Transaction Provider | P0 | Synthetic/mock provider interface, backend wiring | F1 helpful | Backend + Data coordination |
| **F4** Fraud Provider | P0 | Mock Jev interface + rules fallback | F1, F3 helpful | Backend + AI coordination |
| **F5** Analysis Pipeline | P0 | Transaction → safe features → provider → Analysis | F3, F4 | Backend |
| **F6** Confirmation & Memory | P1 | Independent durable confirmation, safe prior memory | Can run after F1 | Backend |
| **F7** Explanation Stub | P1 | Internal privacy-safe Gemini-ready mock interface | F4/F5 helpful | Backend; frontend contract deferred |
| **F8** Failure/Contract Tests | P0, throughout | Offline regressions, adverse cases | After each feature | Backend |
| **F9** Release Readiness | P2, deferred | Readiness audit and later hardening | F1–F8 | Shared ownership |

### Hackathon critical path
For a reliable Demo: **F1 (focused) → F2 (minimum controls) → F3 → F4 → F5**, writing feature-specific F8 tests throughout. Address **F6** if confirmations/memory appear in the demo. **F7** mock only if it demonstrably helps integration; live Gemini later. **F9** plan only until authorized. Avoid sinking the limited hackathon window into nonblocking polish.

### Definition of done for each feature
- Existing contract and frontend-compatible outputs retained.
- Unit/integration tests cover success, invalid input and failure/degraded behavior.
- No leaks of keys/raw banking or PII in provider requests/errors/logs.
- Local synthetic demo remains available with no vendor API credentials.
- Codex reports exact changed files, behavior, commands/results, deferred assumptions and owner questions, without auto-committing.

## Shared constraints
- Work in the **current repository**, not a fresh project. Before edits, read `AGENTS.md`, `README.md`, `contracts/internal-api.openapi.yaml`, relevant `docs/` files and actual implementation. Treat the earlier audit as a pointer, **not guaranteed current truth**.
- Scope: FastAPI backend and backend tests. No frontend edits, no architecture/security policy decisions on behalf of another owner, no live Nessie API implementation, no real Jev HTTP calls, no real Gemini/Backboard integration unless explicitly authorized.
- Preserve existing `/api/v1` routes, JSON `snake_case`, fixed server-side demo user, current OpenAPI schema and working synthetic MVP. **Never create parallel endpoints** (`/api/transactions`, `/api/fraud/analyze`, `/api/assistant/explain`).
- `contracts/internal-api.openapi.yaml` is the team-owned public contract. If completion requires contract changes, **STOP that part**, describe the proposed diff and coordination needed; continue only independent non-breaking work.
- Maintain privacy controls: no raw banking/customer identifiers or merchant text in AI payloads; redact secrets/PII from logs, errors, and tests. `confidence` is NOT a fraud probability. Never claim confirmed fraud or automate account/banking actions.
- Use mocks/stubs for external services. Tests must be deterministic, offline and secret-free; do not install new packages without explaining necessity. Follow existing versions/tools (`pytest`, `ruff`, `scripts/check.sh`).
- Implement **only the requested feature**, make minimal code changes, add targeted tests, run relevant checks, and report changes, test results, unresolved assumptions and any coordination blockers. **Do not commit or push automatically**.

## Feature files
- [F1-api-contract-compliance.md](F1-api-contract-compliance.md)
- [F2-error-security-handling.md](F2-error-security-handling.md)
- [F3-transaction-provider-integration.md](F3-transaction-provider-integration.md)
- [F4-fraud-provider-interface.md](F4-fraud-provider-interface.md)
- [F5-fraud-analysis-orchestration.md](F5-fraud-analysis-orchestration.md)
- [F6-confirmation-memory-reliability.md](F6-confirmation-memory-reliability.md)
- [F7-explanation-interface-mock.md](F7-explanation-interface-mock.md)
- [F8-backend-tests-failures.md](F8-backend-tests-failures.md)
- [F9-production-readiness.md](F9-production-readiness.md)
