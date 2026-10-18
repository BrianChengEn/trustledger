# TrustLedger technology inventory

Verified from source, lockfiles, and GitHub on 17 October 2026. Versions below come from `frontend/package-lock.json` and `backend/requirements.lock.txt` unless noted. Ranges in `package.json` and `backend/requirements.txt` are wider than the locked pins.

Status words:

| Status | Meaning |
|---|---|
| IMPLEMENTED | Used by the running demo or by CI |
| LIVE INTEGRATION | This repository makes a real external call |
| LOCAL FALLBACK | A local substitute is what actually runs |
| MOCK / STUB | A file or mode exists and does not perform the integration |
| PLANNED | Documented target. Not present as a dependency or call |
| UNVERIFIED | Not proven from this repository or from a source checked for this update |

Nothing in this table is LIVE INTEGRATION.

## A. Programming languages

| Tool | Version | Purpose | Where | Owner | This workspace | Key | Runs | Status | Config |
|---|---|---|---|---|---|---|---|---|---|
| TypeScript | 5.9.3 | Frontend types and UI | `frontend/src` | Ian | Installed via `frontend/node_modules` | No | Local | IMPLEMENTED | `frontend/tsconfig.json`, `frontend/package.json` |
| Python | 3.12.15 on this Mac; `.python-version` is `3.12` | API, rules, storage | `backend/` | Benson, with Brian and Kenny in their directories | `backend/.venv` present | No | Local | IMPLEMENTED | `.python-version`, `backend/pyproject.toml` |
| Bash | System shell | Setup and dev scripts | `scripts/` | Benson coordinates | Present | No | Local | IMPLEMENTED | `scripts/*.sh` |
| SQL | SQLite via Python `sqlite3` | Confirmations and memory | `backend/app/core/store.py` | Benson owns persistence; Brian owns what may be stored | Stdlib | No | Local | LOCAL FALLBACK | `database_path` in `backend/app/core/config.py` |

Ruff's `target-version` is `py311`. CI and bootstrap install Python 3.12.

## B. Frontend frameworks

| Tool | Version | Purpose | Where | Owner | This workspace | Key | Runs | Status | Config |
|---|---|---|---|---|---|---|---|---|---|
| React | 19.3.1 | UI | `frontend/src/main.tsx` | Ian | Installed | No | Local browser | IMPLEMENTED | `frontend/package.json` |
| React DOM | 19.3.1 | Browser renderer | `frontend/src/main.tsx` | Ian | Installed | No | Local | IMPLEMENTED | `frontend/package.json` |
| Vite | 7.3.7 | Dev server and build | `frontend/vite.config.ts` | Ian | Installed | No | Local, `127.0.0.1:5173` | IMPLEMENTED | `frontend/vite.config.ts` |

`package.json` declares `react` and `react-dom` as `^19.0.0` and `vite` as `^7.0.0`. The lockfile pins the versions above. Node engine is `>=22.12.0`. `.nvmrc` is `22`. This workspace reported Node `v22.23.3`.

Official docs: [React](https://react.dev/), [Vite](https://vite.dev/).

## C. Frontend libraries

| Tool | Version | Purpose | Where | Owner | This workspace | Key | Runs | Status | Config |
|---|---|---|---|---|---|---|---|---|---|
| `@types/react` | 19.3.0 | React types | devDependency | Ian | Installed | No | Local typecheck | IMPLEMENTED | lockfile |
| `@types/react-dom` | 19.3.0 | React DOM types | devDependency | Ian | Installed | No | Local typecheck | IMPLEMENTED | lockfile |

There is no router, component library, state library, or ESLint dependency. The UI is one component in `frontend/src/main.tsx` plus `frontend/src/styles.css`. API access is `fetch` in `frontend/src/api.ts`.

## D. Backend frameworks

| Tool | Locked version | Purpose | Where | Owner | This workspace | Key | Runs | Status | Config |
|---|---|---|---|---|---|---|---|---|---|
| FastAPI | 0.143.3 | HTTP API | `backend/app/main.py`, `backend/app/api/routes.py` | Benson | Installed in `.venv` | No | Local, `127.0.0.1:8000` | IMPLEMENTED | `backend/requirements.txt` |
| Uvicorn | 0.54.0 | ASGI server | `scripts/dev-backend.sh` | Benson | Installed | No | Local | IMPLEMENTED | script binds localhost and disables access logs |
| Starlette | 1.8.0 | FastAPI's underlying toolkit | Transitive, used by FastAPI | Benson | Installed | No | Local | IMPLEMENTED | lockfile |
| Pydantic | 2.14.1 | Request and response models | `backend/app/schemas/` | Benson for API models; Kenny for `transaction.py` | Installed | No | Local | IMPLEMENTED | lockfile |
| pydantic-settings | 2.16.0 | Environment settings | `backend/app/core/config.py` | Benson | Installed | Reads keys, does not send them | Local | IMPLEMENTED | `backend/.env.example` |

Direct backend requirements are `fastapi`, `uvicorn`, `pydantic-settings`, `httpx`, `pytest`, `ruff`, `PyYAML`, and `jsonschema`. Other lockfile pins, including `opentelemetry-api==1.45.1`, are transitive. Application code does not import OpenTelemetry.

Official docs: [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), [Pydantic](https://docs.pydantic.dev/).

## E. API clients

| Tool | Version | Purpose | Where | Owner | This workspace | Key | Runs | Status | Config |
|---|---|---|---|---|---|---|---|---|---|
| Browser `fetch` | Platform | Call `/api/v1` | `frontend/src/api.ts` | Ian | Browser | No | Local. Vite proxies `/api` to port 8000 | IMPLEMENTED | `frontend/vite.config.ts`, `frontend/.env.example` |
| httpx | 0.28.1 | Async Backboard client | `backend/app/services/ai/jev_client.py` | Brian uses it; Benson owns the lockfile | Installed | Header `X-API-Key` only | Remote when the key is set | IMPLEMENTED | `backend/requirements.lock.txt` |
| FastAPI `TestClient` | From the installed Starlette | In-process API tests | `backend/tests/conftest.py` | Benson | Installed | No | Local tests | IMPLEMENTED | pytest |

No generated OpenAPI client and no vendor SDK are dependencies.

## F. AI models

| Model | Version in official docs checked 17 Oct 2026 | Purpose | Where in this repo | Owner | Status |
|---|---|---|---|---|---|
| TypeSafe Jev | Requested alias `jev-latest`. The response field `system_one.model` is stored as `model_version` | Bounded classification of `SafePayload` | `backend/app/services/ai/jev_client.py` | Brian | IMPLEMENTED through Backboard. Not a local model |

Jev is a remote model. This repository does not run it locally and does not call TypeSafe's host directly.

The rules engine sets `confidence=1.0` when a deterministic rule matches. That number stays the rule confidence even after a live Jev label is attached.

## G. AI infrastructure services

| Service | Integration in this repo | Credential this repo knows | Official interface checked | Owner | Status |
|---|---|---|---|---|---|
| Backboard System One, selected Jev route | `httpx` async `POST /threads/messages` | `BACKBOARD_API_KEY` | [System One](https://docs.backboard.io/concepts/system-one). `llm_provider=typesafe`, `model_name=jev-latest`, `stream=false` | Brian | IMPLEMENTED. Live only when the key is set and the response parses |
| Direct TypeSafe API | Not called | `JEV_API_KEY` is loaded and unused. Official SDK name is `TYPESAFE_API_KEY` | `POST https://api.typesafe.ai/v1/systemone` | Brian | Optional route, not selected |
| Backboard memory | `httpx` async CRUD under `/assistants/{assistant_id}/memories`. One stored assistant per demo owner | `BACKBOARD_API_KEY`. `BACKBOARD_ASSISTANT_ID` is not read | [Memory](https://docs.backboard.io/concepts/memory), [SDK memory](https://docs.backboard.io/sdk/memory). Manual add, list, get, search, and delete. Inference still omits `memory` | Brian | IMPLEMENTED. Mocked in CI. Live only after a real memory response. No key stays `local-fallback` |

`docs/.env.example` sets `JEV_BASE_URL=https://jev-ai.org/api/v1`. The running client does not read or request that host.

`httpx` 0.28.1 is the client. `typesafe-sdk` and `backboard-sdk` are not installed.

## H. Banking data services

| Service | Integration | Credential | Where | Owner | Status |
|---|---|---|---|---|---|
| Capital One Nessie sandbox | `NessieNotConfigured` | `NESSIE_API_KEY`, unused | `backend/app/adapters/nessie.py` | Kenny | MOCK / STUB |
| Synthetic fixture | 8 authored transactions | None | `fixtures/synthetic-transactions.json`, loaded by `backend/app/adapters/synthetic.py` | Kenny | IMPLEMENTED |

Public product page: [api.nessieisreal.com](http://api.nessieisreal.com/). The request schema, current base URL, and key placement are UNVERIFIED in this repository because no client calls Nessie. `docs/.env.example` contains `NESSIE_BASE_URL=https://prod-api.nessieisreal.com`. Settings ignore that variable.

There is no Nessie SDK in Python or JavaScript dependencies. A third-party JavaScript SDK exists upstream and is not used here.

## I. Database and storage

| Store | Purpose | Where | Owner | Key | Status |
|---|---|---|---|---|---|
| SQLite file `backend/data/trustledger-demo.db` | Confirmations, memory sentences, and the owner-to-assistant map for `demo-user-001` | `backend/app/core/store.py` | Benson | No | LOCAL FALLBACK. Remote rows are labeled `backboard` only after a parsed write |
| JSON fixture | Source transactions | `fixtures/synthetic-transactions.json` | Kenny | No | IMPLEMENTED |

`backend/data/` and `*.db` are gitignored. Tests use a temporary database. `DATABASE_URL` in `docs/.env.example` is not read. The setting that exists is `database_path`.

## J. Security and privacy tools

| Control | Where | Owner | Status |
|---|---|---|---|
| Allowlisted `SafePayload` | `backend/app/services/ai/privacy.py`, `backend/app/schemas/api.py` | Brian | IMPLEMENTED |
| Privacy Inspector returns that same object | `GET /api/v1/privacy/preview/{id}` and the React panel | Brian builds it; Ian displays it | IMPLEMENTED |
| Strict request bodies (`extra=forbid`) | API schemas | Benson | IMPLEMENTED |
| Error body hides validation input | `backend/app/main.py` | Benson | IMPLEMENTED |
| CORS plus an origin check on POST and DELETE | `backend/app/main.py` | Benson | IMPLEMENTED |
| 16 KiB body limit, `nosniff`, `no-store`, request id | `backend/app/main.py` | Benson | IMPLEMENTED |
| Secret fields use `SecretStr` and `repr=False` | `backend/app/core/config.py` | Benson | IMPLEMENTED |
| Access log disabled | `scripts/dev-backend.sh` | Benson | IMPLEMENTED |
| Git ignore for env files and databases | `.gitignore` | Benson | IMPLEMENTED |

No dedicated secret scanner, auth library, or rate limiter is installed. GitHub secret scanning and branch protection could not be confirmed: the protection and ruleset APIs returned HTTP 403 on this private repository.

## K. Testing and code quality

| Tool | Locked version | Purpose | Where | Owner | This workspace | Status |
|---|---|---|---|---|---|---|
| pytest | 8.4.2 | Backend tests | `backend/tests` | Benson for integration; Brian and Kenny for their unit tests | Installed | IMPLEMENTED |
| Ruff | 0.17.1 | Lint `E4`, `E7`, `E9`, `F` | `backend/pyproject.toml` | Benson | Installed | IMPLEMENTED |
| Vitest | 3.2.7 | Frontend unit tests | `frontend/src/api.test.ts` | Ian | Installed | IMPLEMENTED |
| TypeScript `tsc --noEmit` | 5.9.3 | Frontend typecheck | `npm run typecheck` | Ian | Installed | IMPLEMENTED |
| jsonschema | 4.26.0 | Validate samples against OpenAPI components | `backend/tests/integration/test_api.py` | Benson | Installed | IMPLEMENTED |
| PyYAML | 6.0.3 | Read the contract in that test | same test | Benson | Installed | IMPLEMENTED |
| Playwright | 1.64.1 | Browser smoke in `scripts/browser-smoke.mjs` and the bootstrap workflow | `frontend/package.json` | Ian for UI behavior; Benson for the workflow | Package installed. Chromium browser install was not rechecked for this doc update | IMPLEMENTED as a script. Browser binary UNVERIFIED on this run |

`bash scripts/check.sh` does not run Playwright. The bootstrap workflow runs it only after backend and frontend checks pass.

## L. Deployment and hosting

No Dockerfile, process file, or hosting config is in the repository. The demo is local. Deployment is PLANNED and owned by Benson. Do not expose the current unauthenticated API through a public tunnel.

## M. GitHub collaboration tools

| Tool | Where | Owner | This workspace | Status |
|---|---|---|---|---|
| GitHub repository `BrianChengEn/trustledger` | `origin` | Benson coordinates; BrianChengEn is admin | `gh` authenticated as BrianChengEn | IMPLEMENTED |
| Pull requests and [PR template](.github/PULL_REQUEST_TEMPLATE.md) | `.github/` | Benson | Used for PR #2 and PR #3, both merged | IMPLEMENTED |
| GitHub Actions | `.github/workflows/ci.yml`, `.github/workflows/bootstrap.yml` | Benson | Latest `main` push after PR #3 succeeded: run `39075769257` | IMPLEMENTED |
| Actions checkout v4, setup-python v5, setup-node v4, upload-artifact v4 | workflow files | Benson | Remote CI | IMPLEMENTED |
| Collaborators | GitHub API | — | `BrianChengEn` admin; `benson5112`, `IanChou89`, `mrkennylee` write | IMPLEMENTED |
| Branch protection | GitHub API | Benson | HTTP 403. UNVERIFIED | UNVERIFIED |

`ci.yml` runs on push, pull request, and manual dispatch. It installs the lockfiles and does not receive vendor secrets.

`bootstrap.yml` runs when `starter-source.zip` or that workflow file changes. It can commit generated locks. Leave it alone during normal feature work.

## N. Local development tools

| Tool | Purpose | How this repo uses it | Owner | Status |
|---|---|---|---|---|
| Homebrew | Install Git, Node 22, Python 3.12, GitHub CLI | `scripts/bootstrap-mac.sh` | Each developer | IMPLEMENTED for macOS |
| GitHub CLI `gh` | Auth, clone, PRs | README and setup guide | Each developer | IMPLEMENTED |
| EditorConfig | Basic editor defaults | `.editorconfig` | Shared | IMPLEMENTED |
| `scripts/doctor.sh` | Check Git, Node >= 22.12, npm, Python | Called by bootstrap | Benson | IMPLEMENTED |
| `scripts/smoke.py` | Hit health, transactions, alerts, analysis, privacy | Manual, backend must be up | Benson | IMPLEMENTED |

## O. AI coding tools

These tools do not run inside the demo.

| Tool | Evidence | Status |
|---|---|---|
| OpenAI Codex | README and starter notes; Kenny's and Benson's branch notes credit Codex for those docs | Used to produce repository material. Not a runtime dependency |
| Grok Build | Memory-feedback PR and this documentation update | Used to prepare those changes. Not a runtime dependency |
| Cursor | Named by the team as an editor | UNVERIFIED from repository files. No `.cursor` project rules are checked in |

## Credentials the backend actually loads

From `backend/.env.example` into `Settings`:

```text
APP_ENV, ALLOW_MEMORY_WRITE, DEMO_USER_ID, FRONTEND_ORIGIN,
NESSIE_API_KEY, JEV_API_KEY, BACKBOARD_API_KEY
```

`database_path` has a code default and is not in the example file. Empty keys are valid. They do not enable vendors.

`frontend/.env.example` contains only `VITE_API_BASE_URL=`. Leave it empty to use the Vite proxy. Do not put vendor keys in any `VITE_` variable.
