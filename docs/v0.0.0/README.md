# Nessie developer console documentation

The TrustLedger Admin console helps one local developer execute six Nessie read queries, inspect table/JSON responses, retain query history, and compare two saved snapshots. Its entry is **left sidebar → WORKSPACE → Admin**; query, history, and comparison are inner tabs. The original [idea](../../idea.md) remains user-authored and read-only. Companion: [繁體中文](README.zh-TW.md).

Q020 confirms integration with the existing TrustLedger app. Reuse its React/TypeScript shell, FastAPI app, typed API client, Settings, and SQLite Store. Existing team ownership, synthetic demonstration, consent-based memory, CI, and contract review remain binding. Admin paths are additive under `/api/v1/admin/nessie`, approved in Q021 and included in OpenAPI.

## Current state

v0.0.0 implements the Admin console, query-history and seed tables, baseline importer, and saved comparison. Q001–Q024 are resolved. The live sandbox contains 124 confirmed baseline entities; all six reads returned 200 and an importer rerun made zero POSTs. [Verification](Verification.md) separates local, browser, live, and PR evidence.

## Effective version documents

| Document | English | Traditional Chinese |
| --- | --- | --- |
| Requirements and decisions | [ArchitectureDecisions](ArchitectureDecisions.md) | [決策紀錄](ArchitectureDecisions.zh-TW.md) |
| Views and controls | [Frontend](Frontend.md) | [前端](Frontend.zh-TW.md) |
| APIs and pseudocode | [Backend](Backend.md) | [後端](Backend.zh-TW.md) |
| Data movement | [DataFlow](DataFlow.md) | [資料流](DataFlow.zh-TW.md) |
| User transitions | [UserFlow](UserFlow.md) | [使用者流程](UserFlow.zh-TW.md) |
| Persistent storage | [Database](Database.md) | [資料庫](Database.zh-TW.md) |
| Initial spikes | [Plan](Plan.md) | [計畫](Plan.zh-TW.md) |
| Verification | [Verification](Verification.md) | [驗證](Verification.zh-TW.md) |

## Visual references

| View | Selected working reference | Alternative |
| --- | --- | --- |
| Query | [Option 1](html/view-query/option-1.html) | [Option 2](html/view-query/option-2.html) |
| History | [Option 1](html/view-history/option-1.html) | [Option 2](html/view-history/option-2.html) |
| Comparison | [Option 1](html/view-compare/option-1.html) | [Option 2](html/view-compare/option-2.html) |

Open an HTML file locally; its assets are local and its content is explicitly synthetic. These pages demonstrate controls and states, not network integration or real persistence. The primary agent selected option 1 as the working layout baseline.

## Available commands

From the project root, with Python 3 and no extra dependencies:

```sh
python3 scripts/generate_synthetic_data.py --check
python3 scripts/generate_synthetic_data.py
```

The first validates existing fixtures without writing. The second regenerates and overwrites seven JSON files. [Dataset instructions](../../datasets/nessie/README.md) describe five scenarios, 32 simulated executions, and seven comparison cases. Fixtures contain no real key or personal records.

Keep the existing [startup](../../README.md) and [team setup](../../TEAM-SETUP-60MIN.md). `bash scripts/check.sh` now includes the isolated browser suite. Reuse locked dependencies and `Settings.database_path`; confirmations and consent-based local-fallback memory remain intact. Put `NESSIE_API_KEY` only in ignored `backend/.env` or runtime secrets. Admin accepts 24-hex IDs and canonical UUIDs. The live sandbox keeps opening balances when these independent transactions are created (Q024); offline computed balances remain fixture conventions.

```sh
bash scripts/check.sh
node frontend/tests/admin-console.spec.mjs
cd backend
.venv/bin/python -m app.adapters.seed_nessie --probe
.venv/bin/python -m app.adapters.seed_nessie
```

The seed commands create synthetic sandbox resources and retain progress; run the probe before full import. They stop on uncertain outcomes instead of blindly retrying. History deletion never deletes seed progress or remote resources. The browser suite uses isolated synthetic upstream/database state and no vendor calls.

## Omitted components and records

No MCP server, natural-language parser, public hosting, standalone Swagger frontend, remote database service, duplicate customer/account ledger, automatic retention cleanup, or runtime seeding UI is required. No release tag or deployment is requested; PR status is recorded in Verification. [CHANGELOG](../CHANGELOG.md) records actual changes; [MISTAKE](../MISTAKE.md) records real process corrections. Repository-specific operating guidance is in [AGENTS.md](../../AGENTS.md).
