# F4 — Fraud Engine Provider Interface (Mock Jev)
**Priority:** P0 | **Prerequisites:** F1, preferably F3 | **Mode:** IMPLEMENT mock/interface only

## Goal
Introduce a testable fraud/transaction-anomaly provider boundary for **future Jev REST integration**, retaining existing deterministic rule-based analysis and explicit degraded behavior.

## Inspect first
- `backend/app/services/ai/rules.py`, `backend/app/services/ai/jev_client.py`
- `backend/app/services/ai/privacy.py`
- `backend/app/schemas/api.py`
- `docs/01-ai-engineer-jev-backboard.md` (Jev request/state/questions and error behavior)
- `contracts/internal-api.openapi.yaml`

## Implementation tasks
- [ ] Model a minimal internal input: existing **privacy-safe allowlisted features**, not raw Transaction, account IDs or arbitrary merchant descriptions.
- [ ] Define an abstract provider contract returning a **validated internal assessment** with provider metadata; distinguish unsupported/unknown numeric semantics from validated severity. Do not invent score thresholds or map Jev scores to fraud probabilities.
- [ ] Implement a deterministic mock Jev provider for local tests, with explicit fake results and controllable timeout/invalid-output/error cases.
- [ ] Wrap existing rule engine as a compatible provider or stable fallback path rather than reimplementing detection logic.
- [ ] Add a selector/orchestrator boundary that can fall back to existing rules on provider timeout, 401/402/429/5xx, malformed response and unavailable provider; do not add actual network calls.
- [ ] Preserve currently documented alert types, severity, evidence, `needs_human`, `provider_mode`, model version and request ID semantics.
- [ ] Where rules and Jev could disagree, **do not invent model precedence**: retain existing rules for outward behavior until the AI/architecture owner confirms a policy, and document the undecided mapping.
- [ ] Keep `jev_client.py` placeholder or adapt it only as needed for interface compatibility; do not ship a guessed live Jev parser.

## Tests / acceptance
- [ ] Mock result passes internal validation and can be invoked without credentials/network.
- [ ] All provider failures exercise deterministic rules fallback; degraded/fallback mode is truthful and distinguishable.
- [ ] Privacy-safe payload is the only input at the provider boundary (test with sentinel PII).
- [ ] No `confidence=1.0` displayed as 100% fraud probability.
- [ ] Existing `/api/v1/analyses` JSON contract unchanged.

## Stop/coordinate
Need AI owner approval for: verified Jev response fixtures, numeric thresholds, rules-vs-model priority and severity mapping. Output a short question list for the owner; do not fabricate answers.

# Shared constraints (apply to every feature)

- Work in the **current repository**, not a fresh project. Before edits, read `AGENTS.md`, `README.md`, `contracts/internal-api.openapi.yaml`, relevant `docs/` files and actual implementation. Treat the earlier audit as a pointer, **not guaranteed current truth**.
- Scope: FastAPI backend and backend tests. No frontend edits, no architecture/security policy decisions on behalf of another owner, no live Nessie API implementation, no real Jev HTTP calls, no real Gemini/Backboard integration unless explicitly authorized.
- Preserve existing `/api/v1` routes, JSON `snake_case`, fixed server-side demo user, current OpenAPI schema and working synthetic MVP. **Never create parallel endpoints** (`/api/transactions`, `/api/fraud/analyze`, `/api/assistant/explain`).
- `contracts/internal-api.openapi.yaml` is the team-owned public contract. If completion requires contract changes, **STOP that part**, describe the proposed diff and coordination needed; continue only independent non-breaking work.
- Maintain privacy controls: no raw banking/customer identifiers or merchant text in AI payloads; redact secrets/PII from logs, errors, and tests. `confidence` is NOT a fraud probability. Never claim confirmed fraud or automate account/banking actions.
- Use mocks/stubs for external services. Tests must be deterministic, offline and secret-free; do not install new packages without explaining necessity. Follow existing versions/tools (`pytest`, `ruff`, `scripts/check.sh`).
- Implement **only the requested feature**, make minimal code changes, add targeted tests, run relevant checks, and report changes, test results, unresolved assumptions and any coordination blockers. **Do not commit or push automatically**.
