# Local database design

Status: additive Admin schema implemented; existing TrustLedger SQLite tables remain intact. Q023 migrates 24-only history schemas to 24/36-character IDs without losing records or the AUTOINCREMENT high-water mark. Authority: [D008](ArchitectureDecisions.md). Companion: [繁體中文](Database.zh-TW.md).

Reuse the existing `Settings.database_path` and `Store`, defaulting to `backend/data/trustledger-demo.db`, through Python's `sqlite3`. Add only the three tables below; preserve `confirmations` and `memories`, including their consent semantics. Keep the existing `backend/data/` ignore rule and credentials outside version control; restrict directory/file permissions to the local user. Enable foreign keys on every connection, use parameterized SQL, and commit each write transaction before reporting success. History survives restart with no automatic expiration. A database service and separate customer/account/transaction tables are unnecessary: Nessie is authoritative and responses are snapshots.

## T-HISTORY — `query_history`

One row represents one attempted upstream query whose history insertion committed. An invalid frontend request is not an upstream attempt; a failed insert creates no row.

| Column | SQLite type / constraint | Meaning |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Stable local history ID; no reuse after clearing |
| `owner` | TEXT NOT NULL | Server-selected demo user; included in every history read/write/delete predicate |
| `source` | TEXT NOT NULL; `nessie` or `synthetic` | Synthetic rows belong only to isolated fixture tests |
| `query_name` | TEXT NOT NULL; six-value allowlist | Maps to API field `query` |
| `resource_id` | TEXT NULL; length 24 or 36 when present | Normalized customer/account ID; null for list queries |
| `requested_at` | TEXT NOT NULL | UTC ISO timestamp |
| `http_status` | INTEGER NULL; 100–599 when present | Actual upstream status |
| `duration_ms` | INTEGER NOT NULL; >= 0 | Measured elapsed milliseconds |
| `body_format` | TEXT NOT NULL; `json`, `text`, `none` | Decoder for stored body |
| `response_body` | TEXT NULL | JSON serialization or plain text; JSON null is stored as text `null` |
| `transport_error` | TEXT NULL | Sanitized JSON `{type,message}` |

Application validation enforces query/ID consistency and 24-hex or canonical UUID IDs. A row with no HTTP status requires `body_format=none`, SQL NULL body, and a transport error; a row with an HTTP status has no transport error. Schema checks enforce those combinations. Never store the key, credential-bearing URL, unsafe exception text, or a persistent `write_status` column: only committed rows are saved. `write_status=failed` is a transient response state.

Add index `(owner,id)`. Read with `owner=? AND id < before_id ORDER BY id DESC LIMIT 51` (omit the cursor condition on the first page). Return 50 items; only if a 51st row exists, use the last returned row's ID as `next_cursor`, so no row is skipped. Do not list full bodies. P06 loads a selected full body. P08/P09 delete from this table only. AUTOINCREMENT prevents stale browser selections from identifying a new record after clearing.

## T-SEED-RUN — `seed_runs`

One row identifies an import of a particular baseline into one credential/environment scope.

| Column | SQLite type / constraint | Meaning |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | Parent of progress records |
| `owner` | TEXT NOT NULL | Server-selected demo user, matching history scope |
| `dataset_sha256` | TEXT NOT NULL | Baseline identity |
| `api_base_url` | TEXT NOT NULL | Approved upstream without credentials |
| `credential_fingerprint` | TEXT NOT NULL | SHA-256 scope fingerprint; never the key itself; backend-only |
| `state` | TEXT NOT NULL; `active`, `complete`, `blocked` | Import state |
| `created_at`, `updated_at` | TEXT NOT NULL | UTC timestamps |

Unique `(owner, dataset_sha256, api_base_url, credential_fingerprint)`. A different scope does not authorize deleting or silently reusing old remote resources. Keep these fields out of frontend history responses.

## T-SEED-RECORD — `seed_records`

One row tracks one synthetic source record and its remote creation outcome.

| Column | SQLite type / constraint | Meaning |
| --- | --- | --- |
| `run_id` | INTEGER NOT NULL; FK `seed_runs.id` | Import scope |
| `kind` | TEXT NOT NULL; `customer`, `account`, `deposit`, `withdrawal` | Resource kind |
| `local_id` | TEXT NOT NULL; 24 characters | Original fixture ID |
| `parent_kind`, `parent_local_id` | TEXT NULL | Customer parent for accounts; account parent for transactions |
| `remote_id` | TEXT NULL | Confirmed server-assigned ID |
| `request_fingerprint` | TEXT NOT NULL | Hash of the exact allowed create payload without the API key |
| `state` | TEXT NOT NULL; `pending`, `confirmed`, `failed`, `uncertain` | Creation/reconciliation state |
| `safe_error` | TEXT NULL | Credential-free error description |
| `updated_at` | TEXT NOT NULL | UTC timestamp |

Primary key `(run_id, kind, local_id)`; unique `(run_id, kind, remote_id)` when non-null. Composite FK `(run_id,parent_kind,parent_local_id)` references the parent progress row. Both parent fields are null only for customers. A confirmed row requires a remote ID; a child may be submitted only after its parent is confirmed. Foreign-key consistency does not replace that application precondition.

Commit `pending` before sending a create request. Record `confirmed` only after validating the remote ID and relationship. If the response or subsequent local commit leaves the result unknown, preserve `pending`/`uncertain` and reconcile via upstream reads before any retry. Never reset the table to solve an ambiguous import.

## Relationships and access chains

```text
seed_runs.id 1 ── N seed_records.run_id
                    └─ customer progress 1 ── N account progress
                                                └─ 1 ── N deposit/withdrawal progress

query_history is independent of seed progress and existing confirmations/memories.
```

| DataFlow chain | Reads / writes |
| --- | --- |
| DF01 live query | P04 inserts T-HISTORY, including failures with a captured response or transport outcome |
| DF02 inspect | P05 reads metadata; P06 reads body and format from T-HISTORY |
| DF03 compare | P06/P07 read two T-HISTORY rows; no persistent comparison table |
| DF04 delete | P08/P09 delete selected/all owner-scoped T-HISTORY rows; seed tables, confirmations, and memories stay intact |
| DF05 seed | P10 reads/writes T-SEED-RUN and T-SEED-RECORD, translates parent IDs, and verifies remote outcomes |

The API response wrapper derives `history_id` and saved state from the committed insert. If the database is unavailable, return the captured result with `failed to write` under Q018. No application database schema is imposed on the existing JSON fixture envelopes; test adapters map fixture labels such as H003 to temporary database IDs.

Verification must cover rollback, restart persistence, source identity, missing-versus-null body decoding, cursor behavior after deletes, parent constraints, and clearing history without losing import mappings. See [Backend](Backend.md), [DataFlow](DataFlow.md), and [Plan](Plan.md).
