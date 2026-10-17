# Nessie developer console implementation plan

Status: completed initial design plan for TrustLedger WORKSPACE → Admin (Q020/D008). S0–S4 and local/live S5 verification are implemented; final PR integration review is recorded below. Companion: [繁體中文](Plan.zh-TW.md).

**Goal:** implement the six-query local console, persistent history, snapshot comparison, and resumable baseline setup specified in [ArchitectureDecisions](ArchitectureDecisions.md).

**Architecture:** extend the existing React/TypeScript/Vite shell, FastAPI app, and Settings/Store SQLite database. Python makes allowlisted Nessie calls and stores sanitized history plus independent seed progress in SQLite. Setup writes are isolated from runtime read-query controls.

**Routing:** use `/Users/kenny/Desktop/project-development-workflow/SKILL.md` and its `rule.md` as the sole lifecycle router. Execute and verify one spike before the next. Primary agent owns integration; no delegation or release is implied by this plan.

## Global constraints and file ownership

- Preserve `idea.md`, confirmed Q001–Q020, AC01–AC12, P01–P10, DF01–DF06, UF01–UF05, and stable frontend IDs. Keep initial language pairs synchronized.
- Read-only runtime, fresh queries, backend-only key, loopback access, exact `failed to write`, no expiry, no blind uncertain-write retries. Admin snapshots never enter AI or confirmed-memory services.
- Integrator: `backend/app/api/admin_nessie.py`, `backend/app/schemas/admin_nessie.py`, `backend/app/services/nessie_console.py`, existing `core/store.py`, `main.py`, and additive `contracts/internal-api.openapi.yaml` changes. Agree on the contract before implementation; keep all current endpoints and consent semantics.
- Data owner: extend `backend/app/adapters/nessie.py` for P02 and add `seed_nessie.py` for P10. Preserve the existing synthetic transaction adapter and source fixtures.
- Frontend owner: extend `main.tsx`, `api.ts`, and `styles.css`; add `Admin.tsx` and `frontend/tests/admin-console.spec.mjs`. Reuse React state, typed client, and installed Playwright; do not add a framework or dependency.
- Use existing pytest/ruff, TypeScript/Vitest/build, locked dependencies, Settings secret, database path, and ignore rules. New focused tests live in `backend/tests/unit/data/test_nessie.py`, `test_seed.py`, `backend/tests/integration/test_admin_nessie.py`, and `backend/tests/unit/test_compare.py`.
- Existing startup/CI commands remain available. New Admin endpoints, seed modules, focused tests, and browser-script commands below are planned until their spike is implemented. Run pytest from `backend/`, or set `PYTHONPATH=backend` for the root commands below. No bootstrap, version upgrade, release, or deployment belongs to this design task.

## Review focus

1. A POST commits upstream but its acknowledgement/local mapping is lost: stop and reconcile, never duplicate it (S1).
2. API success with an unwritable database: preserve the result and exact `failed to write` label (S2/S4).
3. Identical bodies with reordered records or different execution times: no data difference; business-date changes still count (S3).
4. History deleted while selected, or IDs cleared then reused: no stale comparison of unrelated new records (S2/S4).
5. Credential-bearing errors and HTML-like fixture strings: no secret leakage or executable markup (S1/S4).

## S0 — Requirements, fixtures, and reviewable design

Outcome: an internally consistent bilingual design baseline and usable local references. Dependency: confirmed Q020. Scope/owner: primary agent, docs/references and existing fixture preparation only.

- [x] Prepare five deterministic datasets, 32 history records, seven comparison cases, and a generator/self-check (D003, AC11).
- [x] Resolve Q001–Q020 and record explicit user choices, timestamp semantics, failure label, and resumable import.
- [x] Draft all applicable bilingual design documents and two references for each view, with matched IDs and working links.
- [x] Verify fixture checks, bilingual IDs/checklists, links, HTML structure, JavaScript syntax, and reference browser interactions; record actual evidence in D007/D009.
- [x] Record Q020 B, finalize WORKSPACE → Admin integration and module placement, and verify references, bilingual consistency, existing-contract preservation, and required CI (D008/D009).

Integration: [Frontend](Frontend.md), [Backend](Backend.md), [DataFlow](DataFlow.md), [UserFlow](UserFlow.md), [Database](Database.md). Current fixture command: `python3 scripts/generate_synthetic_data.py --check`.

## S1 — Production integration slice and resumable baseline setup

Outcome: validated upstream adapter and resumable setup with confirmed remote ID mappings. Dependencies: S0, Integrator agreement on the additive Admin contract before implementation, and securely available backend key. Scope: `backend/app/adapters/nessie.py`, `backend/app/core/store.py`, `backend/app/adapters/seed_nessie.py`, existing Settings/Store/ignore rules, `backend/tests/unit/data/test_nessie.py`, `backend/tests/unit/data/test_seed.py`. Interfaces: P02 `call_nessie(spec) -> UpstreamResult`; P10 `seed_baseline(probe=False) -> SeedSummary`; T-SEED-RUN/T-SEED-RECORD.

- [x] Write failing transport tests: a synthetic 401 body is captured with status 401; timeout has null status/body; no result/error/log includes a sentinel key. Assert only allowlisted paths are called.
- [x] Write failing seed tests: parents confirmed before children; local IDs never become remote paths; `pending` commits before POST; lost acknowledgement blocks another POST; completed rerun makes zero creates; history clear preserves mappings.
- [x] Implement P02, additive Store tables and progress without changing confirmations/memories, and P10 according to DF05. Retain this as production code with tests, not an unreviewed throwaway probe.
- [x] Run planned `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/unit/data/test_nessie.py` and `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/unit/data/test_seed.py`; expect passing assertions before live writes.
- [x] Run planned `cd backend && .venv/bin/python -m app.adapters.seed_nessie --probe`: create/read back one baseline customer, one account, and its six transactions. Verify actual ID and status/balance semantics, including text-only acknowledgements. Stop on incompatibility and update the question log if requirements must change.
- [x] After probe verification, run planned `cd backend && .venv/bin/python -m app.adapters.seed_nessie` to complete the 124 intended baseline entities when supported. Verify unique remote mappings and parent ownership; rerun and prove zero new POSTs. Record credential-free receipts.

Acceptance: AC02/AC09/AC10/AC12, P02/P10, DF05/UF05. Integration point: confirmed remote IDs are available for all six live-query acceptance checks; source fixtures remain unchanged.

## S2 — Query and history API

Outcome: P01/P03–P06/P08/P09 with accurate live/error/save semantics. Dependency: S1. Scope: `backend/app/api/admin_nessie.py`, history storage in `backend/app/core/store.py`, `backend/tests/integration/test_admin_nessie.py`.

- [x] Write failing tests for six-query ID validation, unknown fields, missing key, fresh repeated GETs, and success/empty/401/404/500/timeout captures.
- [x] Write `test_history_write_failure_preserves_result`: upstream 200/body stays visible, `history_id is None`, `write_status == 'failed'`, `write_label == 'failed to write'`; no partial history row exists.
- [x] Write persistence/deletion tests: restart reads identical saved bodies; cursor pages have no repeated IDs; confirmation absent makes no deletion; clear touches only T-HISTORY; a stale selected ID is 404 and IDs are not reused.
- [x] Implement the local HTTP contracts and guard Admin Host/Origin/JSON boundaries, reuse safe errors/request IDs, and scope all Store operations to the server-selected owner. Require extra-field rejection without echoing unknown submitted bodies. Persist parsed JSON versus text versus no-body distinctly.
- [x] Run planned `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/integration/test_admin_nessie.py`; verify AC01–AC05/AC07–AC08/AC10/AC12 and DF01/DF02/DF04.

Integration: output envelopes consumed by the frontend; P06 supplies full snapshots to S3. Database errors never claim a successful save or deletion.

## S3 — Saved snapshot comparison

Outcome: P07 computes response differences without fresh calls or comparison persistence. Dependency: S2. Scope: `backend/app/services/nessie_console.py`, compare route in `backend/app/api/admin_nessie.py`, `backend/tests/unit/test_compare.py`.

- [x] Write failing fixture assertions for CMP001–CMP007. CMP004/CMP005 must have `data_changed is False`; CMP006 must report 200→404; assert `/transaction_date` changes count while `requested_at`/`duration_ms` do not.
- [x] Write tests for missing versus null, incompatible query/resource/source, the same history ID twice, missing history, and duplicate/missing `_id` in a successful collection. Assert no outbound call and no new history row.
- [x] Implement P07's explicit presence flags, JSON Pointer paths, record matching, status/transport comparison, and safe errors. Preserve original bodies.
- [x] Run planned `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/unit/test_compare.py`; expect all cases to pass (AC05–AC06; DF03).

Integration: return `{left,right,comparison}` to V-COMPARE without a new comparison table.

## S4 — React views and local browser flow

Outcome: V-QUERY/V-HISTORY/V-COMPARE/V-CONFIRM implement UF01–UF04. Dependencies: S2 and S3. Scope: `frontend/` and browser tests; add Admin under left WORKSPACE, retain existing overview/memory flows and Admin session state; use option 1 references as the working baseline.

- [x] Write browser tests for six query selections, conditional ID input, table/JSON switching without new requests, loading/empty/error states, and exact `failed to write` with data still visible.
- [x] Add history/restart display, cursor load, compatible two-record selection, comparison, unchanged bodies with different timestamps, and missing-record recovery.
- [x] Add confirmed single/all deletion and cancellation tests. Assert history deletion never resets seed progress or sends upstream writes.
- [x] Render all provider strings as text; assert the HTML-like boundary fixture creates no executable script. Verify keyboard labels, focus return from confirmation, and narrow-window reading.
- [x] Implement NAV-ADMIN and the views using stable control IDs; reuse the typed API client and provide a 25-second Admin query timeout while keeping current calls at 8 seconds; runtime reads the real backend, never the reference-data JavaScript. Do not expose P-STATE/P-CASE preview controls in the product.
- [x] Run planned `npm --prefix frontend run build` and `node frontend/tests/admin-console.spec.mjs`; the new browser script must be added in S4 using the installed Playwright dependency and a local isolated upstream/database. Verify Admin entry/return, no fresh queries on navigation, and existing overview/memory/consent regressions.

Acceptance: AC01/AC03–AC08/AC10–AC12, all Frontend/UserFlow controls. Integration: existing local frontend/API development processes; no public hosting.

## S5 — Actual verification and closeout

Outcome: implemented behavior, design, and evidence agree. Dependency: S4 and passing targeted checks. Owner: primary integration, bounded independent review if warranted by implemented risk; no PR/release unless separately in scope.

- [x] Verify all six live GETs using mapped baseline IDs; prove history survives restart and a completed importer rerun still creates zero records. Treat live credentials/data as private and retain sanitized receipts.
- [x] Run `python3 scripts/generate_synthetic_data.py --check`, required `bash scripts/check.sh` (ruff, pytest, typecheck, Vitest, build), and the added browser suite. Preserve existing CI/security/independent PR review requirements; do not substitute synthetic tests for live integration evidence.
- [ ] Review uncertain-import recovery, redaction, storage failure, stale selections, comparison edge cases, and accessibility; fix findings and rerun only affected checks before the final gate.
- [x] Update both language copies of designs, Plan checkboxes, README, timestamped CHANGELOG, and real MISTAKE entries to actual outcomes. No fake tags, release, deployment, or passing tests.

Implementation and live verification completed; PR integration review is the remaining delivery gate. See Verification.md.

## Execution receipt — [2026/10/17 18:59]

S1: transport/import tests passed; live probe confirmed eight; full import confirmed 124; completed rerun made zero POSTs. S2/S3: API/history, migration and seven comparison cases passed. S4: browser suite and responsive screenshots passed. S5: complete local CI and all six live GETs passed; same-reviewer PR integration review pending. See [Verification](Verification.md).
