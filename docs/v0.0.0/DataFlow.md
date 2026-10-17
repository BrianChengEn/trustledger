# Data flow

Status: implemented; [verification](Verification.md) separates isolated and live evidence. Companion: [繁體中文](DataFlow.zh-TW.md). Contracts: [Backend P01–P10](Backend.md), [database tables](Database.md), [acceptance criteria](ArchitectureDecisions.md).

## DF01 — Live query and independent persistence

```text
Q-FUNC + optional Q-ID + Q-RUN
  → POST /api/v1/admin/nessie/query → P01 validation
  → P02 allowlisted Nessie GET with backend key
  → capture actual status/body or transport error; redact credentials
  → P04 INSERT query_history and COMMIT
  → P03 response envelope → Q-RESULT table / JSON + metadata
```

DF01 runs inside TrustLedger Admin. The API uses the existing server-selected demo owner and Store; it never changes the dashboard synthetic adapter or routes raw snapshots to AI/memory.

Inputs are a six-value query name and the required normalized resource ID. Upstream JSON remains structured; non-JSON content remains escaped text. The capture adds UTC time and monotonic duration, not fabricated upstream fields. A successful history insertion stores `query_name`, `resource_id`, `source`, time, status, duration, body format/body, and transport error in T-HISTORY, then yields `history_id`.

The frontend receives the same sanitized capture after the insert attempt; it need not reread SQLite just to display the live result. On local insertion failure, rollback, return null `history_id`, and show `failed to write` while preserving the captured response. This exception path implements Q018 rather than losing a successful API result. A non-2xx upstream response is displayed as an API error and is still eligible for history insertion. No HTTP response means null status/body and a transport error. Invalid input or missing configuration stops before the upstream step and is not recorded as an executed upstream query.

Expected outputs: a fresh source-labeled result, accurate API outcome, separate save state, and no credentials. Verify AC01–AC04, AC08, AC10, AC12 with success, empty success, 401/404/500, timeout, malformed input, and injected database-write failure.

## DF02 — History list and individual inspection

```text
Open V-HISTORY / H-MORE → GET /api/v1/admin/nessie/history → P05
  → read T-HISTORY metadata (ID-descending cursor) → history rows
H-VIEW-{id} → GET /api/v1/admin/nessie/history/{id} → P06
  → read stored body_format + response_body + metadata → H-DETAIL
```

Decode JSON only when the stored format is JSON, preserving JSON null versus absent body. Show the original query time and source. No API call, new query-history row, or replacement of old data occurs. A deleted ID returns 404 and refreshes the visible list; database failure shows a read error and preserves existing state. Verify restart persistence, cursor pagination, old-record inspection without outbound requests, and AC04–AC05.

## DF03 — Snapshot comparison

```text
H-L-{id} + H-R-{id} + H-COMPARE → POST /api/v1/admin/nessie/compare → P07
  → P06 reads two T-HISTORY records
  → same query/resource/source check
  → align success collections by unique _id; compare body and response outcome
  → differences + original left/right snapshots → V-COMPARE
```

Input IDs identify two saved executions, never a fresh Nessie request. Transformations produce JSON Pointer changes with presence flags, record additions/removals, and separate status/transport changes. Query timestamps, duration, and history IDs remain visible metadata, excluded from data changes. Original body ordering and business-date fields are preserved. Nothing is persisted by comparison.

Missing records produce 404; incompatible selections or ambiguous success-list IDs produce 409. No changes produces an explicit unchanged state. Verify CMP001–CMP007, missing-versus-null, `transaction_date` changes, and AC05–AC06. CMP004 must produce no data change for ordering alone; CMP005 must do so despite different query times and durations.

## DF04 — Manual history deletion

```text
H-DELETE-{id} / H-CLEAR → confirmation state
  → D-CANCEL: return without request
  → D-CONFIRM: DELETE local history endpoint with confirm=true → P08/P09
  → delete T-HISTORY within transaction → commit → update list/selections
```

The API validates confirmation independently of the browser. Roll back on database failure, report an error, and keep the displayed record until success is known. Clear stale selected IDs and comparison content when their records are deleted. T-SEED-RUN, T-SEED-RECORD, the fixture files, and all remote Nessie resources remain intact. Verify cancel makes no request, confirmation deletes only its intended scope, stale IDs return 404, and AC07.

## DF05 — Baseline setup and resume

```text
baseline.json + backend environment key → P10 validation and run identity
  → read/write seed_runs and seed_records (pending committed before POST)
  → CustomerCreate → confirmed customer remote ID
  → AccountCreate with mapped customer and opening balance → confirmed account ID
  → Deposit/Withdrawal create with mapped account → confirmed transaction IDs
  → verify upstream reads → persist confirmed mappings and completion
  → expose safe remote ID examples for the developer's query form
```

Strip response-only/local fields from create payloads. Add deterministic synthetic markers to allowed text fields and fingerprint exact payloads. The source files remain unchanged. T-SEED-RECORD parents supply remote IDs; local fixture IDs never enter a remote resource path. Probe one customer/account and six transactions before bulk continuation. Under approved Q024, live accounts retain the supplied opening balances and transactions are separate resources. Verify all eight probe entities and that opening balance before bulk writes; offline computed fixture balances are not live expectations.

If an acknowledgement lacks an ID or a write outcome is uncertain, reconcile the parent's collection using the synthetic marker and payload. Only a unique match becomes confirmed. Missing/ambiguous reconciliation blocks further writes. If local progress cannot be persisted, stop before issuing a new POST. On rerun, read and verify prior mappings, skip confirmed records, and create only genuinely missing work. Do not delete existing remote data or silently reset progress. Verify AC09, server-assigned relationships, all 124 intended baseline entities when accepted, and zero additional POSTs on a completed rerun. Synthetic fixtures alone cannot prove this live behavior.

## DF06 — Offline fixtures and evidence

`generate_synthetic_data.py` transforms deterministic invented inputs into five local snapshots, 32 synthetic executions, seven comparison expectations, and a manifest. Its self-check reads those JSON files and validates IDs, ownership, integer values, balance conventions, counts, and comparison facts. Temporary test-database adapters may load synthetic history using `source=synthetic`; production startup never imports fake executions into live history. Local fixtures simulate failures without modifying real Nessie data. Verify with `python3 scripts/generate_synthetic_data.py --check`; keep live probe receipts and fixture test receipts separate (AC11–AC12).
