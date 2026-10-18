# Benson 的 Backend 開發環境

工作分支：`backend`（GitHub：`benson5112`）。從專案根目錄執行以下指令。

## 安裝與啟動

使用 Python 3.12、Node 22，以及已提交的 dependency locks：

```bash
bash scripts/bootstrap-mac.sh
bash scripts/check.sh
```

在兩個 Terminal 分別啟動：

```bash
bash scripts/dev-backend.sh
```

```bash
bash scripts/dev-frontend.sh
```

前端：http://127.0.0.1:5173；API 文件：http://127.0.0.1:8000/docs。
後端啟動後可執行 `backend/.venv/bin/python scripts/smoke.py`。
預設使用 synthetic 資料、rules-only 分析與 local-fallback 記憶。
`backend/.env`、`.venv`、前端依賴與 SQLite 資料只留在本機。

## 提交與推送

```bash
git switch backend
bash scripts/check.sh
git status --short
# 只 stage 本次修改的檔案，再 commit。
git push origin backend
```

Backend 負責 API/core、整合測試、CI、共用依賴與契約；詳細分工見
`AGENTS.md` 與 `docs/04-fastapi-integration-deployment.md`。
契約變更先與隊友確認；合併 main 走團隊 review 流程。

本環境設定與 shell 換行修正由 OpenAI Codex 協助完成。

## F4 fraud provider boundary (mock only)

`app.core.fraud.FraudProvider.assess(FraudFeatures) -> FraudAssessment` is an internal
interface for a future REST adapter, not a Jev response schema. `FraudFeatures` uses
the eight existing privacy fields and the existing controlled category vocabulary.
It rejects extra fields, raw transactions, and invalid values before provider invocation.

The F5 service composes the existing components as follows:

```python
baseline = rules.analyze(transaction, history, request_id)
features = privacy.safe_payload(transaction, history)
provider = select_fraud_provider("mock-jev")  # default selection is "rules-only"
outcome = evaluate_fraud(baseline, features, provider)
# The analysis service returns outcome.analysis only.
```

F4 defines this boundary; F5 wires it into POST /api/v1/analyses.
Deterministic rules remain authoritative for outward results.
The mock returns a fixed assessment, independent of the input, and supports explicit
failure scenarios without credentials, HTTP calls, retries, or sleeping. Success
keeps outward `provider_mode=rules-only`; the mock assessment and its model version
are separate internal metadata. No mock is labelled `rules+jev-live`.

Timeout, unavailable, 401/402/429/5xx, malformed output, unsafe input, and unexpected
provider failures retain the original rule result with `provider_mode=degraded`.
No exception text or provider evidence is copied into outward analysis. Severity,
evidence, `needs_human`, request ID, model version, and confidence stay with the rule
baseline. Rule confidence is rule-match certainty, never a fraud probability.
An optional internal numeric score has unknown semantics and is never thresholded.

AI-owner questions before live integration:

- Which verified, sanitized REST response fixtures and field semantics may the adapter use?
- How should vendor numeric scores map to severity and human-review decisions, if at all?
- What should happen when rules and provider assessments disagree?
- Which model-version attribution and timeout/retry policy should F5/the REST adapter enforce?

These mapping decisions remain deferred; no shared contract was changed.


## F5 analysis orchestration

`app.core.analysis.AnalysisService` uses the request-scoped F3 `TransactionService`
for one history snapshot and one validated lookup, calls the unchanged rules and
privacy serializer, then invokes F4 `evaluate_fraud` once. The existing POST
`/api/v1/analyses` returns only the resulting `Analysis`; internal assessments,
provider metadata, failure details, and numeric scores are not added to the API.

`FRAUD_PROVIDER` defaults to `rules-only`; `mock-jev` explicitly selects the offline
mock. `backboard-jev` explicitly selects Main's Backboard System One client and
requires `BACKBOARD_API_KEY`; a key alone never enables it. Tests can override
`get_fraud_provider` without changing endpoints or the transaction provider.

Alerts and confirmations use the service's rules-derived alerts without provider
assessment calls. Privacy preview continues to use the same serializer as analysis.
Alert IDs/order and stored confirmation status are preserved. A failed POST provider
attempt is marked `degraded`; subsequent rules-only GET results are labelled
`rules-only`, not cached as if they repeated that failed provider attempt. Analysis
reads a request-local snapshot of eligible consented memory but never writes it.

The default and mock paths have no network operations, sleeps, or retries against
the frontend's 8-second timeout. An injected future REST implementation must enforce
its own bounded transport deadline/retry budget; the synchronous F4 interface does
not cancel an arbitrary blocking implementation. That transport is not implemented.
F3's existing 100-record context limit and live mapping/precedence questions remain.

## F6 confirmation and memory reliability

SQLite confirmation persistence now has two transaction boundaries:

1. Under `BEGIN IMMEDIATE`, check the owner/alert idempotency key and commit the
   decision, consent, and initial outcome. Eligible memory starts as `pending`;
   denied consent is `not-requested`, and disabled/non-normal memory is `skipped`.
2. In a separate transaction, insert the sanitized local memory and atomically
   change the confirmation outcome to `written`. A failure rolls back only this
   optional transaction, then records `failed` without undoing the confirmation.

If the database cannot persist the failure status, the durable outcome remains
`pending`. A process interruption between commits can also leave `pending`.
Identical replays return the stored outcome with the current request ID and never
retry or backfill memory. Recovery/retry of interrupted memory requires a separately
approved policy; there is no background worker. A concurrent replay from another
Store instance may observe `pending` while the original attempt is still running.
Conflicting decisions or consent continue to return 409. Existing database tables
and stored outcomes remain compatible; no schema migration is required.

The Store validates decisions/consent and enforces normal + explicit consent + the
route's enabled flag. The existing memory policy still builds sanitized summaries.
Connections are closed after commit/rollback. Memory insert and final status update
are atomic, preventing an orphan memory when the status update fails. List/delete
remain owner-scoped. Deleting a memory does not rewrite historical confirmations;
replaying a confirmation cannot recreate the deleted memory.

The approved Main integration uses sanitized category matching for prior context.
Only existing owner-scoped memories linked to a successful normal confirmation with
explicit consent are eligible. Missing, malformed, failed or deleted memory yields
`unknown`; other owners never contribute. Matches add context and never skip risk
analysis or mark a transaction safe. See `docs/main-integration-resolution.md`.

The older integration document says `ALLOW_MEMORY_WRITE=false` by default; current
Settings and the example environment use `true`. F6 preserves the current source
default and all explicit consent gates. Resolving that policy discrepancy remains
an owner decision. Backboard memory and Gemini remain unimplemented; explicit Backboard/Jev inference
is separate from memory operations.


## Approved Main integration

`core/jev.py::BackboardJevProvider` implements F4's synchronous interface in the
FastAPI worker thread, using Main's async `classify` with an isolated async client.
A three-second total inference deadline covers connection, response and parsing;
no automatic retries occur. HTTP failures map to typed F4 failures and degraded
rules fallback. Missing credentials fail before any HTTP call. Health and alerts
remain rules-only and never infer readiness from a previous analysis.

Successful validated external calls set only `provider_mode=rules+jev-live` and
`model_version`; all risk fields and evidence remain authoritative rules output.
The internal assessment permits `needs_human=None` (unmapped), like nullable
severity; the public Analysis boolean remains mandatory. Vendor choice confidence
and needs_review scores are not thresholded or promoted to fraud probabilities.
Live credentials/vendor behavior have not been verified: offline tests use mock
transports. React still initiates no POST analysis itself, so live inference needs
an explicit API call until the frontend owner adds an analysis action.
