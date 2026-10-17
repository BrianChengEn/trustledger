# F8 coverage audit and integration readiness

## Pre-implementation audit (399-test baseline)

This is a behavioral coverage audit, not a measured line/branch coverage percentage.
Reviewed the F1–F7 test implementations and fixtures, their production boundaries,
shared OpenAPI, `scripts/check.sh`, and CI configuration before adding F8 tests.

| Area | Existing coverage | Gap selected for F8 |
| --- | --- | --- |
| Canonical data/rules | `unit/data/test_synthetic.py`, `unit/ai/test_privacy_rules.py`: deterministic fixtures, rule cases, privacy and consent policy | Reuse these; do not duplicate rule thresholds |
| Contract | `test_api.py`, `test_contract.py`: all eight operations, 404/409/422 envelopes, field/ID/query boundaries, dates | Validate all eight in a combined injected-provider/recovery workflow, including documented error responses |
| Request security | `test_security.py`: actual byte cap, raw ASGI chunks, spoofed/missing lengths, disconnects, CORS, all response headers, safe exceptions | Verify rejected requests do not reach newly wired providers and subsequent valid requests recover |
| Transaction boundary | `test_transaction_provider.py`: list/get/health, errors, malformed shapes, owner scope, consistency, fixed history window | Same-app failure → recovery across analysis, health and consent; finite numeric data at the API boundary |
| Fraud boundary/pipeline | `unit/core/test_fraud.py`, `test_fraud_boundary.py`, `test_analysis_pipeline.py`: all mock failures, safe input, authoritative rules, no implicit writes | Combined transaction+fraud overrides, sequential recovery, database restart, exact contract validation |
| Confirmation/memory | `unit/core/test_store_reliability.py`, `test_confirmation_reliability.py`: separate commits, SQL failures, crash/pending, replay/conflict, ownership and Store concurrency | Concurrent HTTP requests across two app/Store instances sharing a DB; full-workflow failure recovery |
| Explanation | `unit/core/test_explanation.py`, `test_explanation_boundary.py`: strict models, injection/PII rejection, fallback, immutable risk, no public integration | Failure → recovery using the same internal service and the analysis from the combined workflow |
| Offline isolation | One pipeline test denies socket connections; fixtures use per-test SQLite files | Suite-wide network/DNS denial, including attempts swallowed by provider fallback |

Existing failure matrices will be retained, not copied. New tests focus on transitions,
combined boundaries, concurrent HTTP behavior, and missing malformed-data cases.
The shared contract does not document every existing 400/403/413/422/500 response;
those responses can be checked against ErrorEnvelope but cannot be claimed as
fully documented operation responses. Shared YAML edits require team coordination.

## Results and remaining readiness

F8 adds 12 cases in `tests/integration/test_backend_readiness.py`:

- Three full eight-operation workflows: fraud timeout/unavailable/malformed output,
  then successful recovery with unchanged authoritative severity, confidence, evidence,
  model version and human-review decision. Validate responses against shared YAML,
  exact eight-feature privacy payloads, stable transaction IDs, and consent-only memory.
  F7 timeout → recovery is exercised separately through its internal service.
- Two transaction timeout/unavailable transitions: failed analysis and confirmation,
  degraded health, no fraud calls or memory, then healthy operation on the same app.
- Three malformed numeric cases: positive infinity, negative infinity and NaN must
  fail before fraud assessment; replacing the records restores successful analysis.
- One middleware/request rejection sequence (413/403/422/404) followed by success.
- Two concurrent HTTP confirmation cases across separate apps sharing SQLite:
  identical requests and conflicting decisions; reopen the database and verify the
  durable winner, one-or-zero permitted memory rows, and replay identity.
- One memory storage failure → recovery workflow: confirmation survives a failing
  SQLite trigger, replay never backfills memory, new consent can write memory after
  storage recovers, and conflicting decisions still return 409. Sensitive error
  markers are absent from responses and captured application logs.

The existing failure matrices continue to cover missing/empty data, all typed fraud
failures including 401/402/429/5xx-like errors, malformed assessments, explanation
privacy/injection and failure cases, owner isolation, and raw ASGI byte-limit cases.
The suite-wide autouse fixture denies Python internet socket connections and DNS,
and records attempts so provider fallback cannot silently swallow a network attempt.
This is a Python test guard, not an OS-level network sandbox for native code or subprocesses.

### Bug found and fixed

The new positive-infinity case initially returned HTTP 200 from analysis: Pydantic's
non-negative amount constraint accepted infinity. `app/core/transactions.py` now
requires finite amounts at the existing canonical provider boundary. Malformed data
uses the existing safe provider-error HTTP 500 envelope; no public schema or Data-owned
adapter was changed. Negative infinity and NaN were already rejected and remain covered.

### Validation

- `bash scripts/check.sh`: Ruff passed; **411 backend tests**, **3 frontend tests**,
  frontend typecheck and production build passed.
- `git diff --check`: passed (repository line-ending conversion warnings only).
- Existing Starlette/httpx TestClient deprecation warning remains; no dependency upgrade.
- No observed F1–F7 regression. No frontend, shared YAML, deployment or live-provider edits.

### Integration readiness and remaining decisions

**Internal integration is passing; live-provider integration is not verified.**
Synthetic transactions, deterministic rules, injected mock fraud assessments,
privacy projection, alerts, consented SQLite memory, and internal template explanations
are covered together. Rules remain authoritative; confidence is not fraud probability.
There is no explanation endpoint or implicit memory write during analysis.

| Boundary | Still missing / requires owner coordination |
| --- | --- |
| Nessie | Verified upstream response fixtures, credential/transport behavior, tokenization and pagination/history semantics. Current analysis history is limited to the existing latest-100 interface. No live calls tested. |
| Jev | Verified REST contract, risk/score mappings and rules/model precedence, error mapping and bounded transport deadlines. Internal mock assessments are not vendor response schemas. |
| Gemini | Approved model/retention policy, generated-prose validation, transport timeout and future UI/Analysis mapping. Current explanation service uses reviewed templates only and is not publicly wired. |
| Backboard | Remote persistence and failure behavior remain untested; local SQLite is the working implementation. |
| Frontend/shared contract | No change required for this F8 work. Explanation presentation or additional response fields need team approval. Several existing middleware/validation/provider error status codes remain undocumented in operation responses; tests validate their ErrorEnvelope without claiming complete YAML status coverage. |

No known blocker to the current synthetic demo was found after the finite-amount fix.
Potential demo failures remain explicit: unavailable transaction data returns safe 500
rather than invented fallback records; an unavailable primary SQLite database can block
confirmation; optional memory can remain failed/pending without automatic retries.
Prior-confirmation matching remains `unknown` until a privacy-safe strategy is approved.
Mock exceptions verify timeout handling, not actual transport cancellation: arbitrary
blocking injected providers are not bounded by these synchronous interfaces. The current
suite completes quickly, but this is not proof of the frontend's eight-second deadline
under real network latency, production load or database contention. Load, process-crash,
and live vendor contract tests remain outside this offline phase.

F8 changed files: `app/core/transactions.py`, `tests/conftest.py`,
`tests/integration/test_backend_readiness.py`, and this report. Earlier F1–F7 work remains
in the working tree. No commit or push was performed.
