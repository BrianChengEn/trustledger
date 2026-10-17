# Backend design

Status: implemented under Q020/D008 and the approved Q021 contract additions. Q023 adds canonical UUID IDs alongside 24-hex IDs; Q024 adopts observed opening-balance sandbox behavior. Authority: [D008 and AC01–AC12](ArchitectureDecisions.md). Companion: [繁體中文](Backend.zh-TW.md).

## Boundaries and files

Extend the existing FastAPI application rather than creating another server. `backend/app/api/admin_nessie.py` owns the new router; `backend/app/schemas/admin_nessie.py` extends the existing strict-model pattern for P01. `backend/app/services/nessie_console.py` owns P03/P07; `backend/app/adapters/nessie.py` gains P02 without replacing its existing transaction extension point. Extend the existing `Store` in `backend/app/core/store.py` for P04–P06/P08–P09 and seed progress; `backend/app/adapters/seed_nessie.py` owns P10. The Integrator owns router/schema/service/store changes; the Data owner owns adapter/seed changes. No generic proxy or new ledger is required.

`NESSIE_API_KEY` is read only by Python. The intended fixed upstream is `https://prod-api.nessieisreal.com`, from the retrieved [official specification](https://prod.nessieisreal.com/nessie-openapi-spec.yaml). Its `key` query parameter is attached only at the outbound boundary. Never log or return the resulting credential-bearing URL. Bind the service to `127.0.0.1`; allow only loopback Host values and the exact local app Origin. JSON mutations require an allowed Origin and `application/json`; never enable wildcard credential access. Reuse the existing Vite `/api` proxy and Settings secret field. Register the new router through `create_app` and retain its request-ID, safe-error, origin, and no-store middleware. Add Admin-specific loopback Host/Origin/JSON validation without breaking existing endpoints. Reuse `frontend/src/api.ts`: its current 8-second timeout is shorter than P02; add a per-call timeout so only Admin queries allow 25 seconds (15-second upstream wait plus SQLite commit and response margin). Other calls keep their existing behavior. Continue using the current two local development processes; static hosting is outside this design.

## Query allowlist

| Query name | Required resource ID | Nessie GET path |
| --- | --- | --- |
| `customers.list` | None | `/customers` |
| `accounts.list` | None | `/accounts` |
| `accounts.get` | Account | `/accounts/{id}` |
| `accounts.by_customer` | Customer | `/customers/{id}/accounts` |
| `deposits.by_account` | Account | `/accounts/{id}/deposits` |
| `withdrawals.by_account` | Account | `/accounts/{id}/withdrawals` |

`QueryRequest = {query, resource_id?}`. Reject unknown fields and query names. Trim IDs, accept either 24 hexadecimal characters or a canonical UUID, and normalize to lowercase. Require an ID for four queries; reject a nonempty ID on the two list queries. Validation failure makes no upstream call and creates no execution history. The frontend provides no key input.

## Local HTTP contracts

| Method and path | Input | Output / local status |
| --- | --- | --- |
| `POST /api/v1/admin/nessie/query` | `QueryRequest` | Captured execution envelope, HTTP 200; 422 invalid input; 503 missing configuration |
| `GET /api/v1/admin/nessie/history?before_id=…` | Optional positive cursor | `{items, next_cursor}`; newest IDs first, at most 50 metadata rows |
| `GET /api/v1/admin/nessie/history/{id}` | Positive history ID | Full saved execution, 200; 404 missing |
| `POST /api/v1/admin/nessie/compare` | `{left_id, right_id}`; distinct positive IDs | `{left, right, comparison}`, 200; 404 missing; 409 incompatible or unmatchable resource collection |
| `DELETE /api/v1/admin/nessie/history/{id}` | JSON `{confirm:true}` | `{deleted:1}`, 200; 404 missing; 422 confirmation absent |
| `DELETE /api/v1/admin/nessie/history` | JSON `{confirm:true}` | `{deleted:count}`, 200; 422 confirmation absent |

Origin/Host rejection is 403. History read, comparison read, or deletion failure is 500 with a safe local error. Reuse the existing error envelope `{error:{code,message,request_id}}` and `X-Request-ID`; never expose a traceback, SQL text, environment values, or the invalid request body. Invalid requests are 422, even if a framework default would echo submitted fields. Configuration errors do not attempt a Nessie call.

A captured execution uses these fields:

| Field | Type / meaning |
| --- | --- |
| `source` | `nessie` at runtime; `synthetic` only in isolated fixture tests |
| `query`, `resource_id` | Validated query identity; nullable ID for lists |
| `requested_at`, `duration_ms` | UTC ISO timestamp; nonnegative monotonic elapsed milliseconds |
| `http_status` | Actual upstream integer status, or null when no HTTP response exists |
| `body_format` | `json`, `text`, or `none` |
| `response_body` | Sanitized parsed JSON, plain text, or null; JSON null is distinguished by `body_format=json` |
| `transport_error` | Null, or safe `{type,message}` for timeout/connection failure |
| `history_id` | Saved positive integer ID, or null |
| `write_status`, `write_label` | `saved` and null, or `failed` and exactly `failed to write` |

The local 200 envelope reports the completed query attempt, not upstream success. The frontend displays `http_status` as **Nessie HTTP status** and treats non-2xx outcomes as errors. A transport failure has `http_status=null`, `body_format=none`, and no invented response body. A non-JSON HTTP body remains text. Automatic retries are disabled; a new user Query action is a new execution.

## Pseudocode and function boundaries

| ID | Implemented boundary | Behavior |
| --- | --- | --- |
| P01 | `QueryRequest.validate_id() -> QueryRequest` | Enforce the six-query enum, extra-field rejection, and ID rules. |
| P02 | `NessieClient.query(query, resource_id) -> UpstreamResult` | Make one allowlisted GET with a 15-second timeout; capture status/body or a safe transport error; redact credentials in every string and error path. |
| P03 | `nessie_console.execute_query(payload) -> ExecutionEnvelope` | P01; reject missing key; P02; attempt P04. On committed insert return saved ID; on persistence error return the same captured response with null ID and `failed to write`. |
| P04 | `Store.append_history(owner,result) -> int` | Parameterized INSERT and commit; return an ID only after success, rollback on failure. |
| P05 | `Store.list_history(owner,before_id=None) -> HistoryPage` | Read the next 50 rows in descending ID order; omit response bodies from the list. |
| P06 | `Store.get_history(owner,id) -> SavedExecution` | Read one record and decode its body according to format; return missing explicitly. |
| P07 | `nessie_console.compare_history(owner,left_id,right_id) -> ComparisonResult` | P06 twice; validate compatibility; calculate the differences described below. |
| P08 | `Store.delete_history(owner,id) -> int` | Require confirmation, delete one history row, commit or rollback. |
| P09 | `Store.delete_history(owner) -> int` | Require confirmation, delete only `query_history`, commit or rollback. |
| P10 | `seed_nessie.seed_baseline(probe=False) -> SeedSummary` | Validate baseline and scope, resume verified mappings, create parents before children, reconcile uncertain outcomes, and report confirmed progress. |

All persistence/read/delete/compare calls use the server-selected `Settings.demo_user_id`; callers cannot submit an owner. Admin snapshots and seed mappings are separate from confirmations/memories and never enter AI services. The TrustLedger dashboard continues to load the synthetic adapter. The word Admin names a local navigation surface and does not claim production authentication.

## Comparison contract

Require the same `query`, normalized `resource_id`, and source. Preserve original bodies. For successful top-level resource lists, require unique `_id` values and compare records by ID; missing/duplicate IDs return 409 instead of silently overwriting records. Other JSON objects compare recursively by key, nested non-resource arrays by index, and scalar/text bodies by value. Distinguish absent keys from explicit null with `before_present` and `after_present` flags. Credential redaction precedes persistence and comparison.

`comparison = {data_changed, changes, status_change, transport_change}`. A change is `{kind, record_id?, path, before_present, after_present, before, after}`; `kind` is `added`, `removed`, or `changed`, and `path` is a JSON Pointer. Compare response status and transport error independently. Query timestamps, durations, and local history IDs appear in headers, not in `changes`. Business fields such as `/transaction_date` remain comparable. Identical data with different ordering or query timestamps has `data_changed=false` unless its response outcome differs.

## Baseline setup protocol

P10 is a local CLI, not a runtime HTTP endpoint. Its source is only `datasets/nessie/baseline.json`; validate its checksum, relations, and integer values before writes. Persist run identity and pending work before each outbound POST. Bind progress to the upstream base URL and a nonreversible key fingerprint; a changed key, dataset, or environment requires reconciliation rather than silently reusing mappings.

Create customers with `CustomerCreate` fields, accounts under their mapped customers with opening balances, then deposits/withdrawals under mapped accounts. Strip local `_id`, envelope fields, and generated account numbers from create payloads. Use deterministic synthetic markers derived from source IDs and dataset identity in existing text fields for reconciliation. Record the exact outgoing payload fingerprint. Never treat a fixture ID as a remote ID.

The first probe imports one customer, one account, and its six transactions, then reads them back before bulk continuation. Q024 verified that the sandbox keeps the account opening balance after creating these transactions. Verify that opening balance on probe and before bulk continuation; offline fixture computed balances remain separate. A successful creation response may lack an ID, particularly the withdrawal response described as text in the current specification: reconcile by reading the mapped parent's collection and matching the synthetic marker and payload. Only a unique confirmed match permits storing a remote ID.

Timeouts, 5xx responses, malformed acknowledgements, or local failure after remote creation may leave an uncertain write. Reconcile first; if missing or ambiguous, mark the run blocked and stop. Do not blindly repeat POSTs or delete existing remote data. Skip completed records only after confirming their remote identity and parent. A normal completed rerun makes zero POST requests. No automatic remote cleanup/reset command is included.

## Frontend action mapping

| Control/action | Local operation | Functions |
| --- | --- | --- |
| NAV-ADMIN | Open the retained Admin view, initially V-QUERY | Local navigation; no upstream request |
| NAV-Q, NAV-H, NAV-C | Navigate; opening history reads its first page | P05 for NAV-H; otherwise local |
| H-TABLE, H-JSON | Switch saved response presentation | No request |
| Q-FUNC, Q-ID | Local form state and validation | P01 rules |
| Q-RUN | `POST /api/v1/admin/nessie/query` | P01–P04 |
| Q-TABLE, Q-JSON | Local presentation switch | No request |
| H-MORE | `GET /api/v1/admin/nessie/history` with cursor | P05 |
| H-VIEW-{id} | `GET /api/v1/admin/nessie/history/{id}` | P06 |
| H-L-{id}, H-R-{id} | Select distinct compatible IDs | Local selection |
| H-COMPARE | `POST /api/v1/admin/nessie/compare`, open V-COMPARE | P07 |
| H-DELETE-{id}, D-CONFIRM | Confirm, then delete one | P08 |
| H-CLEAR, D-CONFIRM | Confirm, then clear history | P09 |
| D-CANCEL, C-BACK | Cancel or return | No request |
| C-TABLE, C-JSON | Switch both snapshot presentations | No request |
| Setup command | Import baseline separately | P10 |

See [Frontend](Frontend.md), [DataFlow](DataFlow.md), [Database](Database.md), and [Plan](Plan.md). The checked-in OpenAPI includes these additive contracts. See [verification](Verification.md) for local and live receipts.
