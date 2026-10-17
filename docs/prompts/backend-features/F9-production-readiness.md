# F9 — Production Readiness (deferred until explicitly authorized)
**Priority:** P2 | **Prerequisites:** F1–F8 as appropriate | **Mode:** AUDIT / PLAN by default; DO NOT DEPLOY

## Goal
Identify and, only when authorized, implement backend-specific release hardening without changing team-owned hosting/security architecture.

## Inspect first
- `docs/04-fastapi-integration-deployment.md`
- `docs/06-security-privacy-threat-model.md`
- `backend/app/main.py`, `backend/app/core/config.py`
- `scripts/check.sh`, README, runtime/deployment configuration

## Readiness checklist
- [ ] Decide actual deployment environment with architecture/security owner; document trusted HTTPS/TLS termination, proxy headers and secret injection.
- [ ] Separate development from production CORS: production exact approved origin(s), no localhost extras or wildcard.
- [ ] Define app mode/provider mode and vendor URLs/timeouts consistently between env docs and actual Settings; do not activate unsupported `.env` keys silently.
- [ ] Add agreed request/rate limits for an unauthenticated public demo; enforce maximum body size and safe failure behavior.
- [ ] Verify safe structured logs, request IDs, redaction and no keys in URLs, logs or exception traces.
- [ ] Validate health/readiness responses without exposing secret or upstream details; do not misrepresent synthetic mode as a connected bank.
- [ ] Confirm data retention, SQLite persistence scope, cleanup and backup requirements; encryption-at-rest design is **not yet defined** and needs security owner decision.
- [ ] Run backend/CI checks and a documented local deployment rehearsal; verify graceful provider failure and fallback.
- [ ] Document rollback and demonstration fallback; prepare a checklist for HTTPS, CORS and monitoring validation after hosting is selected.

## Acceptance
A concise release readiness report identifies PASS / FAIL / BLOCKED and exact supporting files/tests. No actual cloud deployment or live vendor calls without explicit authorization.

## Stop/coordinate
Never decide authentication model, TLS/KMS, vendor data agreements, production secrets or public exposure unilaterally. These need architecture/security and project owner approval.

# Shared constraints (apply to every feature)

- Work in the **current repository**, not a fresh project. Before edits, read `AGENTS.md`, `README.md`, `contracts/internal-api.openapi.yaml`, relevant `docs/` files and actual implementation. Treat the earlier audit as a pointer, **not guaranteed current truth**.
- Scope: FastAPI backend and backend tests. No frontend edits, no architecture/security policy decisions on behalf of another owner, no live Nessie API implementation, no real Jev HTTP calls, no real Gemini/Backboard integration unless explicitly authorized.
- Preserve existing `/api/v1` routes, JSON `snake_case`, fixed server-side demo user, current OpenAPI schema and working synthetic MVP. **Never create parallel endpoints** (`/api/transactions`, `/api/fraud/analyze`, `/api/assistant/explain`).
- `contracts/internal-api.openapi.yaml` is the team-owned public contract. If completion requires contract changes, **STOP that part**, describe the proposed diff and coordination needed; continue only independent non-breaking work.
- Maintain privacy controls: no raw banking/customer identifiers or merchant text in AI payloads; redact secrets/PII from logs, errors, and tests. `confidence` is NOT a fraud probability. Never claim confirmed fraud or automate account/banking actions.
- Use mocks/stubs for external services. Tests must be deterministic, offline and secret-free; do not install new packages without explaining necessity. Follow existing versions/tools (`pytest`, `ruff`, `scripts/check.sh`).
- Implement **only the requested feature**, make minimal code changes, add targeted tests, run relevant checks, and report changes, test results, unresolved assumptions and any coordination blockers. **Do not commit or push automatically**.
