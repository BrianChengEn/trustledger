# v0.0.0 implementation verification

Recorded: [2026/10/17 18:59] America/New_York. Companion: [繁體中文](Verification.zh-TW.md).

Baseline: latest merged [PR #3](https://github.com/BrianChengEn/trustledger/pull/3), `5be26c1`. Its consent-based memory changes were reviewed before implementation; no existing contract conflict was found. Q021 approves additive Admin endpoints; Q023 approves 24-hex and canonical UUID remote IDs; Q024 adopts the observed sandbox opening-balance behavior.

## Local and browser checks

- `bash scripts/check.sh`: ruff, 46 backend tests, TypeScript, three Vitest tests, Vite build and the isolated browser suite. Final invocation and PR checks are recorded below.
- `python3 scripts/generate_synthetic_data.py --check`: seven deterministic JSON files, six queries and seven comparison cases passed.
- Browser coverage: six query forms, validation, table/JSON without new queries, retained navigation state, paged history, saved comparison, stale selection, cancellation/Escape/focus return, single/all deletion, failed writes, empty/401/timeout, text-safe HTML-like content, consent/memory regression and 320/390/768px layouts. Screenshots visually inspected. Local artifacts: `artifacts/admin-desktop.png` and `artifacts/admin-mobile.png` (ignored).
- Tests use synthetic upstream responses and isolated SQLite. GitHub CI adds the same browser suite with no vendor credentials. Existing checks remain required.

## Live sandbox receipt

Verified at `2026-10-17T22:56:41Z`, separately from synthetic checks:

| Check | Observed result |
| --- | --- |
| Baseline import | 124 confirmed: 10 customers, 18 accounts, 48 deposits, 48 withdrawals |
| Six query types | Each returned HTTP 200 through Admin and saved history |
| App restart | Identical saved response read back |
| Saved comparison | Unchanged bodies; no fresh upstream request |
| Completed importer rerun | 142 GETs, **0 POSTs**, 124 confirmations retained |
| IDs | Server-generated canonical UUIDs; legacy 24-hex IDs remain accepted |
| Balances | Opening balances remain unchanged after transaction creation; offline fixture totals are separate |

The first customer remained pending when the initial ID validator rejected its UUID. It was reconciled after Q023, without another create. All eight probe entities were read back before bulk continuation. Q024 approved the actual balance semantics; no existing remote balance was updated. The credential-free JSON receipt is local at `artifacts/nessie-live-verification.json`. No remote ID, key, response body, database or credential fingerprint is committed.

## Review and delivery

An independent safety review found two import defects: a changed payload could evade an existing-marker check, and a changed probe transaction could evade the bulk balance-only preflight. Regression tests failed before fixes. The same reviewer verified both fixes with 14 passing focused tests before live continuation. Subsequent UUID/migration and balance tests passed.

Full PR integration review and GitHub CI are pending PR creation. No merge, release tag or deployment has occurred. Human teammate review remains required by the project PR checklist. Implementation assistance: OpenAI Codex and its independent AI reviewer; retain this credit for the submission.

- [2026/10/17 18:59] Final local gate passed: ruff, 46 backend tests, typecheck, three Vitest tests, build, isolated browser suite, fixture self-check, bilingual IDs/checklist/link checks and Git whitespace check. Existing Starlette/httpx deprecation warning remains; dependencies were not changed.
