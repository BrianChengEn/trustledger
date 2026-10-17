# Synthetic Nessie datasets

These deterministic JSON fixtures contain invented data only. They support the six agreed read queries and local testing of tables, JSON views, history, and comparison. They are not captured API responses, a running mock service, or records uploaded to Nessie. All durations and timestamps in the history are simulated.

Companion: [Traditional Chinese](README.zh-TW.md).

## Files

| Dataset | Customers | Accounts | Deposits | Withdrawals | Purpose |
| --- | ---: | ---: | ---: | ---: | --- |
| [baseline.json](baseline.json) | 10 | 18 | 48 | 48 | Normal relationships, multiple account types and transaction states. Customer `c0000000000000000000000a` has no accounts; accounts ending in `11` and `12` have empty transaction lists. |
| [changed.json](changed.json) | 10 | 17 | 51 | 52 | A later synthetic state with additions, removals, changed fields, and updated balances. |
| [empty.json](empty.json) | 0 | 0 | 0 | 0 | Successful empty customer and account lists. |
| [boundary.json](boundary.json) | 3 | 4 | 2 | 1 | Zero balance and amount, large integer balance, Unicode, long strings, quotes, line breaks, and HTML-like text. |
| [volume.json](volume.json) | 50 | 100 | 300 | 300 | A larger local fixture for table rendering; not a performance benchmark. |

[history.json](history.json) contains 32 simulated executions and seven comparison cases. It includes empty successes, invalid-ID, unauthorized, missing-account, server-error, and transport-timeout cases. Error bodies are synthetic examples, not promises about the server's exact messages or all possible status codes. A timeout has no upstream HTTP status or response body.

[manifest.json](manifest.json) lists counts, provenance, and one history-record example for each of the six queries.

## Snapshot layout and queries

Each snapshot has `synthetic: true`, a `dataset_id`, `customers`, `accounts`, `deposits_by_account`, `withdrawals_by_account`, and `opening_balances`. This is a local dataset envelope, not an upstream API response shape. Account IDs are the dictionary keys for transaction ownership; transaction bodies do not acquire an invented `account_id` field.

| GET query | Local data used for its response body |
| --- | --- |
| `/customers` | `customers` |
| `/accounts` | `accounts` |
| `/accounts/{id}` | Account whose `_id` matches the ID |
| `/customers/{id}/accounts` | Accounts whose `customer_id` matches the ID |
| `/accounts/{id}/deposits` | `deposits_by_account[id]` |
| `/accounts/{id}/withdrawals` | `withdrawals_by_account[id]` |

Customer, account, and deposit fields follow the [official OpenAPI 1.0.0](https://prod.nessieisreal.com/nessie-openapi-spec.yaml) retrieved during requirements research. The specification describes withdrawal list items only as generic objects; their fixture fields follow the resource example in the [official documentation](https://prod.nessieisreal.com/docs). Context7 had no matching banking API documentation.

The fixture convention is that only transactions with status `completed` affect balance. For each account, `balance = opening_balances[id] + completed deposits - completed withdrawals`. Opening balances are local bookkeeping metadata. Amounts use the integer representation in the retrieved specification; the datasets do not establish currency or conversion rules. Values such as zero-amount transactions and fictional addresses are boundary fixtures, not validated live creation payloads.

Names and addresses are deliberately synthetic. The 24-character hexadecimal IDs and 16-digit account-number strings are fabricated fixture values. They are not valid references to a user's Nessie account. Importing data later would require a separately authorized API import and mapping server-assigned IDs; these files are not directly importable POST payloads.

## History and comparisons

Every history record has `source: synthetic`, a query and resource ID, a method and path without credentials, a synthetic timestamp and duration, an optional HTTP status, a response body, and an optional transport error. `manifest.json` links the six baseline examples to records `H001` through `H006`.

Comparison cases reference two history IDs for the same query and resource ID:

- `CMP001`: changed account fields.
- `CMP002`: added, removed, and modified deposits.
- `CMP003`: added, removed, and modified customers, including a nested address field.
- `CMP004`: identical account records in a different order.
- `CMP005`: identical response bodies.
- `CMP006`: an account present in the earlier state and missing in the later state, with HTTP status changing from 200 to 404.
- `CMP007`: added withdrawals, modified fields, and a transaction status transition.

The expectations describe fixture facts for future comparison tests; no application comparison implementation is included. Render HTML-like strings as text in a future frontend.

## Regeneration and verification

Run from the project root with Python 3 and no third-party dependencies:

```sh
python3 scripts/generate_synthetic_data.py
python3 scripts/generate_synthetic_data.py --check
```

Generation overwrites the seven generated JSON files. It does not read credentials or perform network requests. The check command reads existing files without writing them and verifies schema-relevant fields, ID uniqueness, relationships, integer amounts, balance consistency, manifest counts, query coverage, history metadata, comparison expectations, and deterministic output.

Successful local checks do not establish live API authentication, server behavior, UI behavior, or remote data availability. The existing requirement to call Nessie on every application query remains in effect; these fixtures do not silently replace that behavior.
