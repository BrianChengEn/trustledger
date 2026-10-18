# Approved Main/backend integration

Backend parent: `aae05b4`; Main parent: `6f64037`.
The team explicitly approved explicit-only Jev activation and owner-scoped consented
category matching. This supersedes the earlier two-policy-blocker review checkpoint.

## Resolution and implementation

- `api/routes.py`: resolve the base/ours/theirs conflict with F3 validated lookup,
  F5 orchestration, bounded F1 IDs and F6 confirmation-first writes. Main's async
  orchestration is not duplicated in routes. Preview now uses the same request-local
  memory context and serializer as analysis. No new endpoints or schema changes.
- `api/dependencies.py`, `core/config.py`: `FRAUD_PROVIDER=rules-only` remains default;
  `mock-jev` is offline; `backboard-jev` explicitly selects the adapter. A key alone
  cannot enable it. Adapter construction on other routes performs no network work.
- `core/jev.py`: adapt Main's async `services/ai/jev_client.classify` to synchronous
  F4 `assess` in FastAPI's worker thread. Validate safe input and returned classification;
  a missing/blank key fails before HTTP. Use an isolated client/event loop, fixed vendor
  endpoint, no redirects/retries, typed status errors and a three-second total inference
  timeout. Do not call the policy-bearing `decision.review` from the backend workflow.
- `core/fraud.py`: preserve the FraudProvider interface; internal `needs_human` may
  be None when unmapped, like nullable severity. This does not change the public
  Analysis boolean. Do not map choice_confidence or needs_review to confidence,
  probability, severity or a boolean threshold. On validated Jev success, only provenance
  (`rules+jev-live`, model version) changes; all rule risk fields and evidence are retained.
  Failures retain rules with degraded mode and no upstream text.
- `core/store.py`: add an owner-scoped read joining extant memory to a successful
  normal+consent confirmation and its stored written memory ID. Cross-owner, orphan,
  deleted, failed or pending memories are ineligible. No write-path changes. Optional
  memory reads use a 100ms SQLite lock wait instead of consuming the frontend deadline.
- `core/memory.py`: query at most once per request, accept only reviewed sanitized
  category sentences and reuse Main's prior_confirmation helper. Query/parsing failures
  safely return unknown, without logging records. Category context includes approved
  controlled `other`; it is not merchant-level identity or evidence of legitimacy.
- `core/analysis.py`: supply the same context to rules, safe features, alerts and preview.
  A match can add Main's contextual evidence sentence, but never bypasses normal rules,
  reduces severity/confidence or removes human review. No implicit memory writes occur.

Health reports current transaction readiness and rules-authoritative analysis, never a
cached previous inference. Only explicit POST /analyses can invoke Jev, at most once.
GET alerts, confirmation, preview, memory and health operations do not invoke inference.
Backboard inference is independent of SQLite memory reads/writes. Main's decision/client,
helper modules, tests, React changes and documentation remain in the merge; the frontend
was not additionally edited during resolution. Main's direct decision service is not
part of this application route path, and its score threshold is not adopted by F4.

## Test reconciliation and validation

Main's integration test now opts in via provider selection and patches the adapter's
classification boundary. It expects request-local live/degraded provenance and rules-only
health/GET alerts. F6's old unknown-after-consent expectation now follows approved matching;
missing consent/review outcomes still remain unknown. No tests were deleted or skipped.

Added `tests/integration/test_approved_integration.py` (22 cases): key-only vs explicit
activation, one-call analysis, zero inference on other operations, actual adapter with
MockTransport success/auth/timeout/unavailable/malformed failures, no retries, authoritative
rules, safe provider inputs, absent credentials, one memory snapshot per request,
consented matching without suppressing duplicate rules, owner isolation/cross-owner links,
orphan/malformed records, memory failure/lock fallback, and durable confirmation despite
optional write failure independently of Jev availability.

Validation:

- `bash scripts/check.sh`: Ruff passed; **440 backend tests passed, zero failed**;
  **3 frontend tests**, frontend typecheck and production build passed.
- Focused Jev, consent/memory, contract and F8 end-to-end tests passed (115 cases).
- `git diff --check` and staged whitespace validation passed.
- All eight operations and original F1–F8 coverage are included. Approved policy
  expectations were updated explicitly. Offline network guard remained enabled.
- Existing Starlette/httpx TestClient deprecation warning remains; no dependency upgrade.

## Live integration limitations

No real keys or external APIs were exercised. Main's Backboard wire format has only been
validated against repository fixtures/mock transport, not against current vendor responses.
A successful mocked response tests provenance mechanics; it is not live operational evidence.
Nessie remains synthetic, Gemini remains an internal mock, and memory remains local-fallback.
React still does not issue POST /analyses; a frontend-owned action is required to demonstrate
live inference in the UI. Its inspector copy also needs coordination before live presentation.
GET alert cards correctly remain rules-only even after a live POST analysis.

The three-second inference budget leaves headroom within React's eight-second timeout for
the current synthetic/local pipeline. This is not a production latency/load guarantee;
future live transaction calls must share an end-to-end deadline. The synchronous adapter
must remain in a worker thread; an async route would need explicit thread offloading.
Category memories have no newly invented expiry/relevance window or merchant matching.
Deployment/authentication, real provider verification and model-risk mappings remain out
of scope. Shared OpenAPI, dependencies and deployment configuration were not changed.

## Files edited during the approved resolution

`AGENTS.md`, `backend/.env.example`, `backend/README.md`,
`backend/app/api/dependencies.py`, `backend/app/api/routes.py`,
`backend/app/core/analysis.py`, `backend/app/core/config.py`,
`backend/app/core/fraud.py`, `backend/app/core/jev.py`, `backend/app/core/memory.py`,
`backend/app/core/store.py`, `backend/docs/explanation-proposal.md`,
`backend/docs/main-integration-resolution.md`,
`backend/tests/integration/test_api.py`,
`backend/tests/integration/test_confirmation_reliability.py`,
`backend/tests/integration/test_approved_integration.py`.
