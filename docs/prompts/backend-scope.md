# Backend Development Scope — TrustLedger

## Context
Technica 2026 B2C fraud-warning assistant. React frontend, FastAPI backend, Capital One Nessie transaction data, Jev risk assessment, and a future Gemini explanation layer.

The existing repository already contains a working synthetic MVP. **Do not rebuild it.** `contracts/internal-api.openapi.yaml` is the API source of truth; preserve existing `/api/v1` endpoints and behavior.

## Responsibilities
I own **FastAPI backend APIs, service orchestration, input/output validation, error handling, and backend tests**. Teammates own React/UI, architecture/security decisions, and the live Nessie data integration. Respect existing code ownership and coordinate any cross-boundary contract change.

## Decisions
1. **Gemini:** Defer the real client. When needed, add only a provider-neutral explanation interface/mock, without changing established routes or contracts unilaterally.
2. **Backend work:** I will send a feature-by-feature implementation checklist next. Do not implement yet.
3. **Nessie:** Preserve the documented list/get/health adapter boundary. Use mock/synthetic integration until the Data/API teammate supplies the verified live adapter; do not implement live Nessie yourself.
4. **Jev:** Treat as an external REST provider, but defer the real HTTP integration. Build against a mockable interface. Do not invent response schemas, score thresholds, or fraud probabilities; preserve deterministic fallback behavior.
5. **Backboard/memory:** Defer live provider integration. Keep the existing SQLite memory and consent controls intact; don't replace Backboard with Gemini.
6. **Deployment:** Defer production deployment. Keep baseline security from the start: secrets server-side, privacy-safe payloads and logs, strict validation, safe errors, consent boundaries.

## Working Rules
- Inspect `AGENTS.md`, relevant docs, and current implementations before proposing changes.
- Preserve functioning code; prefer minimal, feature-scoped changes with tests.
- Do not create parallel endpoints or modify frontend/contracts/security architecture without coordination.
- Clearly label mock behavior and unresolved provider assumptions.
- **This turn is read-only. No edits, installs, commits, or implementation.**

## Reply Only With
1. Your understanding of my backend ownership.
2. Existing components to preserve.
3. Mocked/deferred integrations.
4. Independent backend gaps ready for implementation.
5. Only critical blockers under these assumptions.

Keep the response concise. Wait for my feature checklist.
