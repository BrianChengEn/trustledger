# Team roles

Assignments below are the working agreement for Technica 2026. GitHub logins were checked against the repository collaborator list on 17 October 2026.

Paths are directories that exist today. Do not create a parallel application tree.

| Person | GitHub | Role | New-work branch | Already on the remote |
|---|---|---|---|---|
| Brian | `BrianChengEn` | AI Engineer / AI Architecture Lead | `feat/ai-engine` | `feat/local-memory-feedback` is merged. Do not recreate it |
| Benson | `benson5112` | Backend Engineer / Integration Lead | `feat/backend-integration` | `backend` exists and is not merged. Do not reset it |
| Ian | `IanChou89` | Frontend Engineer / UI/UX Lead | `feat/frontend` | `ianthechou` exists and has no commits of its own beyond older `main`. Do not reset it |
| Kenny | `mrkennylee` | Banking Data Engineer / Nessie API Lead | `feat/nessie-data` | `mrkennylee` exists. Its guide is already on `main`. Do not reset it |

`IanChou89` is the collaborator. The login `ianthechou89` does not exist. The remote branch name `ianthechou` is only a branch name.

Personal setup notes that are already merged: [docs/pr/mrkennylee.md](docs/pr/mrkennylee.md) and [docs/pr/mrkennylee.zh-TW.md](docs/pr/mrkennylee.zh-TW.md). Benson's unmerged environment note is on branch `backend` at `backend/README.md`. This file is the shared role agreement.

## Brian

1. **Name and GitHub.** Brian, `BrianChengEn`. Repository admin.
2. **Main role.** AI Engineer / AI Architecture Lead.
3. **Technologies owned.** Jev through the Backboard System One API, Backboard memory, the allowlisted payload, rules behavior, and AI tests. He does not own FastAPI routing, Nessie, or React. The direct TypeSafe HTTP API is not his selected integration.
4. **Primary responsibilities.** Jev integration, Backboard integration, classification behavior, persistent memory content, decision routing between rules and a future model, confidence meaning, payload minimization, and AI tests.
5. **Secondary responsibilities.** Explain AI limits in the demo. Review any API change that adds fields to `SafePayload` or memory text. Keep health modes honest: do not report `rules+jev-live` or `backboard-live` until a real call succeeds.
6. **Files and directories.** `backend/app/services/ai/**`, `backend/tests/unit/ai/**`. Today that is `privacy.py`, `rules.py`, `memory_policy.py`, `memory_sync.py`, `jev_client.py`, `backboard_client.py`, `test_privacy_rules.py`, `test_jev_backboard.py`, and `test_backboard_memory.py`.
7. **API interfaces.** He produces `Analysis`, `SafePayload`, and `PrivacyPreview` content. Benson exposes them at `POST /api/v1/analyses`, `GET /api/v1/alerts`, and `GET /api/v1/privacy/preview/{transaction_id}`. Memory sentences are stored by Benson's `Store` and read back through `prior_confirmation`.
8. **Dependencies.** Kenny supplies canonical `Transaction` records. Benson keeps routes, SQLite, and the OpenAPI contract aligned. Ian displays evidence and the inspector without rebuilding the payload in the browser.
9. **Coordination.** A new AI field, model version, or memory sentence format is a contract change. Agree with Benson before editing `contracts/internal-api.openapi.yaml` or `backend/app/schemas/api.py`. Agree with Kenny before putting raw banking fields into an AI request.
10. **Current status.** Rules, the allowlist, and local-fallback memory are on `main`. Jev inference goes through Backboard when `BACKBOARD_API_KEY` is set. The direct TypeSafe endpoint is not used. Consented Backboard memory CRUD is on the same key. A real memory create, read, reuse, isolation, restart, and delete succeeded on 17 October 2026. CI still mocks the provider. System One on this account returns HTTP 402, so classification is not live.
11. **Remaining tasks.**
    - **P1.** Keep the Backboard request limited to `SafePayload`. A failed or missing response stays `degraded` or `rules-only`, never `rules+jev-live`.
    - **P1.** System One credits are exhausted (`HTTP 402`). Do not buy credits or enable auto-reload. Memory CRUD already works without that call. SQLite stays `local-fallback` when the memory call fails or the key is empty.
    - **P2.** Record a small synthetic comparison between the rule and Jev's `pattern`. Do not quote accuracy without that evidence.
12. **Acceptance.** A unit test proves raw id, account token, merchant text, exact amount, and exact timestamp never enter the outbound body. A failed vendor call still returns the three demo alerts. `needs_human` stays true when a rule flags a transaction, including after a prior normal confirmation.
13. **Required tests.** `backend/tests/unit/ai/test_privacy_rules.py` and the memory section of `backend/tests/integration/test_api.py`. Run `bash scripts/check.sh`.
14. **Deliverables.** A live-or-fallback Jev client, a live-or-fallback Backboard client, tests, and a short note of the exact request fields. No keys in Git.
15. **Pull requests.** Branch `feat/ai-engine` from current `main`. One behavior per PR. Benson reviews contract or route changes. Ian reviews inspector copy. Do not push over `feat/local-memory-feedback`.

## Benson

1. **Name and GitHub.** Benson, `benson5112`. Write access. GitHub profile name: Yi Yan Ho.
2. **Main role.** Backend Engineer / Integration Lead.
3. **Technologies owned.** FastAPI, Uvicorn, API contract, SQLite persistence, CI, shared dependency locks, and deployment when it exists.
4. **Primary responsibilities.** Routes, orchestration, review and confirmation endpoints, error handling, secrets on the server, backend tests, end-to-end integration, GitHub Actions, and coordinating shared interfaces.
5. **Secondary responsibilities.** Keep `main` runnable. Help teammates with bootstrap failures that come from shared scripts. Refuse PRs that commit `.env`, databases, or live keys.
6. **Files and directories.** `backend/app/api/**`, `backend/app/core/**`, `backend/app/main.py`, `backend/app/schemas/api.py`, `backend/tests/integration/**`, `backend/tests/conftest.py`, `backend/pyproject.toml`, `backend/requirements.txt`, `backend/requirements.lock.txt`, `contracts/**`, `.github/**`, and `scripts/**`.
7. **API interfaces.** The internal contract in `contracts/internal-api.openapi.yaml`. He is the only person who merges a contract change after the affected owners have agreed.
8. **Dependencies.** Brian supplies analysis and privacy functions. Kenny supplies `load_transactions()` that returns `Transaction` objects. Ian consumes the contract and must not invent response fields.
9. **Coordination.** If two people need `routes.py` or the contract, Benson sequences the edits or pairs on one branch. He does not rewrite AI policy or the Nessie mapping inside those files.
10. **Current status.** Synthetic API, SQLite, idempotent confirmation, origin checks, and CI are on `main`. Authentication, rate limits, and deployment are not started. Branch `backend` has an unmerged environment note and `.gitattributes` only.
11. **Remaining tasks.**
    - **P0.** Keep CI green and the synthetic demo starting from `scripts/dev-backend.sh`.
    - **P1.** When Brian or Kenny land a client, wire health modes and preserve the synthetic path on failure.
    - **P1.** Add deployment only if it can stay free of secrets and real bank data. Document the URL and the git SHA.
    - **P2.** Authentication beyond `demo-user-001`, if the demo needs it. The current API is a local demo, not an auth design.
12. **Acceptance.** `bash scripts/check.sh` passes. Unknown JSON fields return 422 without echoing input. A conflicting confirmation returns 409. Health never says `nessie-live`, `rules+jev-live`, or `backboard-live` unless that call succeeded in-process.
13. **Required tests.** `backend/tests/integration/test_api.py`. CI workflow `.github/workflows/ci.yml` on the PR.
14. **Deliverables.** Reviewed API behavior, green CI, and a rollback path for every live integration PR.
15. **Pull requests.** Continue on `backend` or open `feat/backend-integration` from current `main`. Do not force-push `backend`. Brian reviews AI wiring. Kenny reviews transaction-loading changes. Ian reviews response changes the UI must show.

## Ian

1. **Name and GitHub.** Ian, `IanChou89`. Write access.
2. **Main role.** Frontend Engineer / UI/UX Lead.
3. **Technologies owned.** React, TypeScript, Vite, frontend tests, and the demo UI.
4. **Primary responsibilities.** Dashboard, transaction list and detail, alert explanation, human confirmation, Privacy Inspector display, memory list and delete, API integration, loading and error states, responsive layout, accessibility, and demo polish.
5. **Secondary responsibilities.** Keep mode labels visible: synthetic, rules-only, local-fallback. Do not relabel a stub as Jev or Backboard.
6. **Files and directories.** `frontend/**`. He should not need to edit `backend/app/services/ai/**` or `backend/app/adapters/**`.
7. **API interfaces.** `frontend/src/api.ts` must match the contract. The Vite proxy sends `/api` to `127.0.0.1:8000`. `VITE_API_BASE_URL` stays empty in local demo.
8. **Dependencies.** Benson's API must be up for a full click-through. Brian's preview endpoint is the only source of `safe_payload`. Kenny's transaction shape is what the table renders.
9. **Coordination.** A UI need for a new field starts as a contract conversation with Benson, not as a private response shape. Inspector changes that alter meaning need Brian's review.
10. **Current status.** One-page UI loads transactions, alerts, evidence, confirmation, inspector JSON, and memory delete. It reloads the preview after confirm and delete. Tests cover money formatting and safe error text only. No component test and no mobile pass is recorded in the repo.
11. **Remaining tasks.**
    - **P1.** Make the 8-transaction review path obvious on a phone-width window and a laptop.
    - **P1.** Show the prior-confirmation evidence sentence clearly when the API returns it.
    - **P2.** Add a frontend test for the confirm and delete refresh if time remains.
    - **P2.** Accessibility pass: labels, focus, and contrast on the existing controls.
12. **Acceptance.** With the backend running, a person can open the duplicate, inspect the payload, confirm normal with consent, see the memory row, delete it, and see the inspector return to `unknown`. Loading and API-down states stay understandable. The screen never claims a bank or a model was contacted.
13. **Required tests.** `npm test`, `npm run typecheck`, and `npm run build` inside `frontend/`, or `bash scripts/check.sh`. Browser smoke is `node scripts/browser-smoke.mjs` only when both servers and Playwright's browser are installed.
14. **Deliverables.** A demo UI a teammate can operate without narration, plus screenshots that contain no keys and no real financial data.
15. **Pull requests.** Create `feat/frontend` from current `main`. Do not reset `ianthechou`. Benson reviews API-client changes. Brian reviews inspector wording.

## Kenny

1. **Name and GitHub.** Kenny, `mrkennylee`. Write access. GitHub profile name: Li-Yi Mao.
2. **Main role.** Banking Data Engineer / Nessie API Lead.
3. **Technologies owned.** Nessie sandbox access, synthetic datasets, normalization into `Transaction`, data validation, and banking-layer tests.
4. **Primary responsibilities.** Nessie client, sandbox testing, transaction retrieval, normalization, demo scenarios, feature fields the rules need, sensitive-field filtering before data leaves the adapter, Nessie errors, and a written list of Nessie limits.
5. **Secondary responsibilities.** Keep the 8-transaction fixture stable so Brian's rule tests and Ian's demo keep their expected alerts. Add rows only with a test update the other owners have seen.
6. **Files and directories.** `backend/app/adapters/**`, `backend/app/schemas/transaction.py`, `fixtures/**`, `backend/tests/unit/data/**`. Runtime synthetic rows live in SQLite, initialized from deterministic code. JSON files remain offline goldens; update them with the existing generator/checker when the approved baseline changes.
7. **API interfaces.** `load_transactions(store, owner)` returns `list[Transaction]` from SQLite. Each API request reads one owner-scoped snapshot. Separate Nessie Admin reads and the explicit baseline CLI do not switch dashboard data. A future dashboard mapper must preserve that canonical type and keep Nessie ids out of AI payloads.
8. **Dependencies.** Benson switches the app onto the adapter and sets health `data_mode`. Brian consumes only the canonical fields he already allowlists. Ian displays `merchant_display` and `source`.
9. **Coordination.** A new `Transaction` field is a contract change. Nessie customer ids, account ids, and raw descriptions stay inside the adapter and tests, never in frontend fixtures or AI requests.
10. **Current status.** Canonical synthetic data and import fixtures use SQLite. Nessie Admin supports six allowlisted reads, safe projections/local codes and metadata-only history; the explicit baseline CLI preserves resumable import safety. The dashboard purchase mapper remains an extension point. No sandbox account or key is committed.
11. **Remaining tasks.**
    - **P1.** Implement a read-only sandbox adapter with a timeout. On missing key, timeout, or schema mismatch, the app keeps the synthetic fixture and reports `synthetic` or `degraded`, not `nessie-live`.
    - **P1.** Map sandbox purchases into `Transaction` and document which Nessie resources are unused.
    - **P2.** Add one extra synthetic scenario only if the demo needs it and the rule tests are updated in the same PR.
12. **Acceptance.** Unit tests cover the mapper without a network call. A separate test or manual note shows one successful sandbox read when a key is present locally. That test is skipped in CI. Logs and assertions do not print the key or raw customer payload. `source` is `nessie` only for records that came from Nessie.
13. **Required tests.** `backend/tests/unit/data/test_synthetic.py` and new adapter tests that default to no network. `bash scripts/check.sh` must pass with an empty `NESSIE_API_KEY`.
14. **Deliverables.** Adapter, tests, and a short limitation note: what was read, what was not, and how to revoke the sandbox key.
15. **Pull requests.** Create `feat/nessie-data` from current `main`. Do not reset `mrkennylee`. Benson reviews the loader switch. Brian reviews any field that could reach `privacy.py`.

## Shared expectations

- Pull `main` with fast-forward before branching.
- Stage explicit paths. Do not `git add .` a dirty tree.
- Run `bash scripts/check.sh` before opening a PR.
- One other teammate reviews. The author does not merge their own functional PR unless the team is inside the last-hour rule in `docs/05-github-collaboration.md` and CI is green.
- Contract changes name the endpoint, whether they are breaking, and who agreed.
- Keys, `.env`, SQLite files, and raw provider bodies stay out of commits, screenshots, and PR text.
