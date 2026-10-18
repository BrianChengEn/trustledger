# F7 — Future Gemini Explanation: Internal Interface Only
**Priority:** P1 | **Prerequisites:** F4/F5 recommended | **Mode:** IMPLEMENT minimal internal mock; NO public endpoint

## Goal
Prepare a replaceable, privacy-safe explanation service behind the backend for future Gemini integration, without implementing the real Gemini client or changing shared API contracts.

## Inspect first
- existing `Analysis` and `SafePayload` schemas
- privacy feature allowlist and forbidden-field policy
- `contracts/internal-api.openapi.yaml`
- `docs/06-security-privacy-threat-model.md`
- existing user-facing evidence/alert text

## Implementation tasks
- [ ] Define a **provider-neutral internal** explanation request derived from existing validated analysis and allowlisted safe fields only; no raw transaction/customer identifiers, merchant text, exact amounts or arbitrary user-provided prompt.
- [ ] Define an internal explanation result with conservative plain-language summary, evidence references/reason labels and suggested **user verification actions**. Clearly separate generated prose from authoritative assessment metadata.
- [ ] Provide a deterministic mock/template-based explanation provider that can be unit-tested offline. Label/mock it as synthetic, not a true AI decision.
- [ ] Validate bounded output and sanitize/escape potentially untrusted content. Never allow explanations to change severity, score, evidence of record, confirmation, memory or transfers.
- [ ] Provide error/fallback handling: explanation failure must not erase a valid fraud assessment; safe plain-text fallback is acceptable.
- [ ] Use an internal service boundary callable by future orchestrator. **Do not add** `/api/assistant/explain` or any public route, frontend field or shared OpenAPI changes without team agreement.
- [ ] Do not add real Gemini key, SDK, external network call, or change Backboard behavior.
- [ ] Add a short proposed API contract appendix *as a proposal only* if frontend later needs to display generated explanations.

## Tests / acceptance
- [ ] Mock request/output validated; failed explanation returns safe fallback.
- [ ] Sentinel PII and prompt-injection-like merchant text never reach provider.
- [ ] An explanation cannot modify risk outcome or trigger a bank action.
- [ ] Existing eight endpoints and OpenAPI contract remain unchanged.

## Stop/coordinate
Before making this externally visible, obtain frontend approval for UI timing/shape and architecture/security approval for allowed Gemini fields, model, timeout and retention policy.

# Shared constraints (apply to every feature)

- Work in the **current repository**, not a fresh project. Before edits, read `AGENTS.md`, `README.md`, `contracts/internal-api.openapi.yaml`, relevant `docs/` files and actual implementation. Treat the earlier audit as a pointer, **not guaranteed current truth**.
- Scope: FastAPI backend and backend tests. No frontend edits, no architecture/security policy decisions on behalf of another owner, no live Nessie API implementation, no real Jev HTTP calls, no real Gemini/Backboard integration unless explicitly authorized.
- Preserve existing `/api/v1` routes, JSON `snake_case`, fixed server-side demo user, current OpenAPI schema and working synthetic MVP. **Never create parallel endpoints** (`/api/transactions`, `/api/fraud/analyze`, `/api/assistant/explain`).
- `contracts/internal-api.openapi.yaml` is the team-owned public contract. If completion requires contract changes, **STOP that part**, describe the proposed diff and coordination needed; continue only independent non-breaking work.
- Maintain privacy controls: no raw banking/customer identifiers or merchant text in AI payloads; redact secrets/PII from logs, errors, and tests. `confidence` is NOT a fraud probability. Never claim confirmed fraud or automate account/banking actions.
- Use mocks/stubs for external services. Tests must be deterministic, offline and secret-free; do not install new packages without explaining necessity. Follow existing versions/tools (`pytest`, `ruff`, `scripts/check.sh`).
- Implement **only the requested feature**, make minimal code changes, add targeted tests, run relevant checks, and report changes, test results, unresolved assumptions and any coordination blockers. **Do not commit or push automatically**.
