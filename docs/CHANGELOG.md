# Changelog

Companion: [繁體中文](CHANGELOG.zh-TW.md). Entries record actual work, not future plan completion.

## v0.0.0 — Unreleased Nessie design proposal

- [2026/10/17 18:24] Recorded Q001–Q019 and drafted the bilingual frontend, backend, data-flow, user-flow, database, and initial-plan documents, with a [version index](v0.0.0/README.md).
- [2026/10/17 18:24] Added six local HTML references, two per view, using explicitly synthetic data. Headless Chrome smoke checks passed for both layouts: six queries, JSON/table switches, failed persistence, timeout/empty states, history inspect/cancel/delete/clear, comparison, ordering/timestamp exclusion, outcome change, and mobile overflow. Eight grouped checks passed with no page errors; receipt and screenshots are under `/var/folders/m9/_c877nqx7x96qvrk297jjhzr0000gn/T/hackerton-design-evidence-5LJ8z9/`.
- [2026/10/17 18:24] Retained five deterministic datasets, 32 synthetic executions, seven comparison cases, and the standard-library generator/self-check.
- [2026/10/17 18:24] Preserved the concurrently introduced TrustLedger application, team ownership, and contract. Restored tracked AGENTS and documentation index content, then added separate Nessie links. Q020 remains pending for independent versus integrated scope.
- [2026/10/17 18:24] Existing TrustLedger `bash scripts/check.sh` passed: backend lint, 15 backend tests, frontend typecheck, three frontend tests, and build. One dependency deprecation warning was emitted; no dependency changes were made for this proposal.
- [2026/10/17 18:24] No new Nessie runtime, SQLite application schema, live baseline import, or live API verification was executed. No commit, PR, merge, tag, release, or deployment was performed by this task. The existing TrustLedger runtime is separate from this proposal.

- [2026/10/17 18:35] Resolved Q020 B: integrate the console into TrustLedger left WORKSPACE → Admin, with query/history/comparison inner tabs. Finalized additive API/module/Store design, preserving synthetic/consent/AI boundaries and existing contract review. S0 is complete; S1–S5 remain future implementation.
- [2026/10/17 18:35] Updated all six HTML references to the integrated sidebar; 12 browser groups passed, including both layouts and all views at 320px/390px. Bilingual IDs/checklists, authored Markdown links, fixture check, JavaScript syntax, and shared-file preservation passed. Evidence: `/var/folders/m9/_c877nqx7x96qvrk297jjhzr0000gn/T/hackerton-design-evidence-i110PE/`. Required `bash scripts/check.sh` again passed lint, 15 backend tests, typecheck, three frontend tests, and build; one existing deprecation warning remains. No runtime source/contract changes, Nessie calls/import, release, or deployment.

## v0.0.0 — Nessie Admin implementation

- [2026/10/17 18:59] Implemented WORKSPACE → Admin query/history/compare views, additive OpenAPI contracts, local Host/Origin/JSON guards, persistent history, and resumable baseline-only setup. Preserved PR #3 memory feedback and the synthetic dashboard.
- [2026/10/17 18:59] Q021 approved the contract; Q023 approved UUID plus 24-hex IDs after live server mismatch; Q024 approved opening balances with independent transactions. Migrated history constraints without losing rows or deleted-ID sequence progress.
- [2026/10/17 18:59] Live sandbox confirmed 124 entities; six queries returned 200; saved history survived restart and comparison made no upstream call. Full rerun made 142 GETs and zero POSTs. No existing remote balance was updated.
- [2026/10/17 18:59] Independent safety review found and verified fixes for duplicate-marker and incomplete-probe-preflight risks. Local verification includes 46 backend tests, three frontend tests, build/typecheck, fixture check and browser flows. Full PR review/CI are pending; no merge, tag or deployment. [Evidence](v0.0.0/Verification.md). AI assistance: OpenAI Codex.

- [2026/10/17 19:05] Opened [PR #4](https://github.com/BrianChengEn/trustledger/pull/4); full independent AI integration review passed after stale-history-response and per-account opening-balance regressions were fixed. Final local CI passed 47 backend tests plus browser checks; fresh live read-only rerun verified all account balances with zero POSTs. Initial GitHub CI passed; final update will run CI again. Human teammate review pending; no merge/tag/deployment.
