# F2 — Error Handling & Baseline Security
**Priority:** P0 | **Prerequisites:** F1 recommended | **Mode:** IMPLEMENT

## Goal
Close audit-identified backend request-handling weaknesses without taking over architecture/security ownership.

## Inspect first
`backend/app/main.py`, `backend/app/core/config.py`, `docs/06-security-privacy-threat-model.md`, API error contract, existing middleware/tests.

## Implementation tasks
- [ ] Refactor common response handling so security headers and `X-Request-ID` appear on **success, validation failure and middleware early-return errors** (including blocked Origin and oversized request), subject to current contract.
- [ ] Enforce request-body size against **actual bytes received**, not only `Content-Length`. Reject absent/incorrect Content-Length and chunked/streamed oversized bodies. Avoid reading unbounded content into memory. Preserve request-body streaming/ASGI semantics and avoid consuming the body twice.
- [ ] Keep existing safe error shape `{"error":{"code":"…","message":"…","request_id":"…"}}` and prevent exception details, keys, URLs with API-key query parameters, tokens or raw transaction data from leaking.
- [ ] Validate effective CORS origins against existing **development** policy; **do not** unilaterally decide production policy or introduce permissive wildcards.
- [ ] Confirm environment values containing secrets are stored server-side and not printed (Pydantic `SecretStr` where applicable); do not alter other owners' `.env` contents.
- [ ] Add request correlation in safe structured logging only if achievable without sensitive payloads; keep log redaction explicit.
- [ ] Keep legitimate privacy/consent behavior intact. Rate limiting/production deployment changes belong to F9 unless an immediate local security flaw requires action.

## Tests / acceptance
- [ ] Test missing/spoofed/oversized Content-Length, actual oversized body, malformed JSON, Origin rejection, and unexpected exception.
- [ ] Assert consistent safe error envelope, request ID, cache/security headers and no raw sensitive strings in output/log capture.
- [ ] Assert normal POST body parsing still works; no regression in frontend calls or eight API operations.
- [ ] Backend tests and lint pass; mention performance trade-offs of middleware design.

## Stop/coordinate
If fixing an issue requires changing frontend behavior, deployment infrastructure or security architecture, produce a minimal proposal instead of making the cross-owner change.

# Shared constraints (apply to every feature)

- Work in the **current repository**, not a fresh project. Before edits, read `AGENTS.md`, `README.md`, `contracts/internal-api.openapi.yaml`, relevant `docs/` files and actual implementation. Treat the earlier audit as a pointer, **not guaranteed current truth**.
- Scope: FastAPI backend and backend tests. No frontend edits, no architecture/security policy decisions on behalf of another owner, no live Nessie API implementation, no real Jev HTTP calls, no real Gemini/Backboard integration unless explicitly authorized.
- Preserve existing `/api/v1` routes, JSON `snake_case`, fixed server-side demo user, current OpenAPI schema and working synthetic MVP. **Never create parallel endpoints** (`/api/transactions`, `/api/fraud/analyze`, `/api/assistant/explain`).
- `contracts/internal-api.openapi.yaml` is the team-owned public contract. If completion requires contract changes, **STOP that part**, describe the proposed diff and coordination needed; continue only independent non-breaking work.
- Maintain privacy controls: no raw banking/customer identifiers or merchant text in AI payloads; redact secrets/PII from logs, errors, and tests. `confidence` is NOT a fraud probability. Never claim confirmed fraud or automate account/banking actions.
- Use mocks/stubs for external services. Tests must be deterministic, offline and secret-free; do not install new packages without explaining necessity. Follow existing versions/tools (`pytest`, `ruff`, `scripts/check.sh`).
- Implement **only the requested feature**, make minimal code changes, add targeted tests, run relevant checks, and report changes, test results, unresolved assumptions and any coordination blockers. **Do not commit or push automatically**.
