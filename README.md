# TrustLedger · Technica 2026

TrustLedger is a B2C, privacy-first financial assistant. It reviews simulated banking transactions, explains patterns that need a person, and stores only an explicit, minimized memory of what that person confirmed.

This repository is a working synthetic demo. It is not a live bank connection and it does not move money.

**Deadline:** 18 October 2026, 12:00 PM EDT.

**Repository:** https://github.com/BrianChengEn/trustledger (private; teammates must accept the invitation).

## Current status

The local v0.3.0 candidate integrates the UI from `main` after PR #13 with the existing synthetic/Nessie data work. Today, Activity, Case, Privacy and Memory share the same components in the main workspace and isolated Data sources/Admin customer reviews. Synthetic remains the default. Existing generators, 18 offline records, common account codes, legacy aliases and explicit Nessie setup are retained. Connected data actions still require fresh Nessie acquisition. On 17 October 2026, explicit Backboard memory CRUD was checked against the live API: create, store, retrieve, reuse, two-owner isolation, restart, and delete. System One classification on that same account returned HTTP 402 `Insufficient credits for System One`. Failed inference preserves the rule result and reports `degraded`. Do not buy credits or turn on auto-reload.

| Area | Status |
|---|---|
| Synthetic transactions, rules, review UI, Privacy Inspector | Implemented |
| SQLite synthetic data, confirmations and consented category memory | Implemented; JSON remains an offline fixture only |
| Consented memory affects the next analysis | Implemented on `main` |
| Jev through Backboard | Explicitly configured POST analyses may attempt inference. HTTP 402 preserves rules and reports request-specific degraded mode; GET/confirmation stays rules-only |
| Direct TypeSafe API | Not selected and not called |
| Backboard persistent memory | Implemented and checked live. No key uses SQLite and labels it `local-fallback`. A key alone does not flip health to `backboard-live` |
| Capital One Nessie | Shared Overview/Admin customer workspace; structured SQLite account and movement cache, per-collection freshness/failure; eight Admin queries with typed SQLite projections; explicit baseline CLI retained |
| GitHub Actions CI | Backend, frontend and Admin browser checks run for each PR |
| Production auth, hosting, deployment | Not started |

With the default synthetic provider, health reports `synthetic`, `rules-only`, and `local-fallback` when `ALLOW_MEMORY_WRITE=true`, or memory `off` otherwise. Connected Nessie health reflects its SQLite snapshot and per-collection failures. Filling an API key does not by itself activate inference or report `backboard-live`.

## Documentation

| Document | What it answers |
|---|---|
| [TECH_STACK.md](TECH_STACK.md) | Every tool, version, owner, and implemented vs planned |
| [TEAM_ROLES.md](TEAM_ROLES.md) | Brian, Benson, Ian, and Kenny |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Runtime data flow and what is mocked |
| [TEAM-SETUP-60MIN.md](TEAM-SETUP-60MIN.md) | Four-Mac setup, run, and test |
| [docs/05-github-collaboration.md](docs/05-github-collaboration.md) | Branches, review, conflicts, secrets |
| [docs/06-security-privacy-threat-model.md](docs/06-security-privacy-threat-model.md) | Threat model and current controls |
| [contracts/internal-api.openapi.yaml](contracts/internal-api.openapi.yaml) | Internal API contract |
| [docs/diagrams/index.md](docs/diagrams/index.md) | Six architecture diagrams |
| [AGENTS.md](AGENTS.md) | File ownership for contributors and coding agents |

The offline viewer `docs/index.html` is the original starter snapshot. Prefer the Markdown files above when they disagree with that snapshot.

The guides in `docs/00` through `docs/07` govern implementation. Versioned design updates remain local under `docs/vx.x.x` and are not published. [ARCHITECTURE.md](ARCHITECTURE.md) describes the current implementation; offline viewer snapshots may lag behind it.

## Team

| Person | GitHub | Owns |
|---|---|---|
| Brian | [BrianChengEn](https://github.com/BrianChengEn) | AI services and AI privacy |
| Benson | [benson5112](https://github.com/benson5112) | FastAPI, integration, CI, deployment |
| Ian | [IanChou89](https://github.com/IanChou89) | React application |
| Kenny | [mrkennylee](https://github.com/mrkennylee) | Nessie and banking data |

Details, directories, and remaining tasks: [TEAM_ROLES.md](TEAM_ROLES.md).

## Stack in one page

| Layer | What actually runs |
|---|---|
| Frontend | React 19.3.1, TypeScript 5.9.3, Vite 7.3.7 |
| Backend | Python 3.12, FastAPI 0.143.3, Uvicorn 0.54.0 |
| Analysis | Deterministic rules; explicit `FRAUD_PROVIDER=backboard-jev` enables a bounded provider attempt only for POST analyses |
| Memory | SQLite index/fallback; explicit consented Backboard CRUD when enabled and configured |
| Banking | Synthetic SQLite by default; explicit `TRANSACTION_PROVIDER=nessie` connects the mapped synthetic sandbox customer |

Versions are the lockfiles, not the ranges in `package.json`. Full inventory: [TECH_STACK.md](TECH_STACK.md).

## Run the demo on macOS

Install Xcode Command Line Tools and [Homebrew](https://brew.sh/) once. Then:

```bash
brew install git gh
gh auth login
gh auth setup-git
git clone https://github.com/BrianChengEn/trustledger.git
cd trustledger
bash scripts/bootstrap-mac.sh
bash scripts/check.sh
```

Two terminals from the repository root:

```bash
bash scripts/dev-backend.sh
```

```bash
bash scripts/dev-frontend.sh
```

- App: http://127.0.0.1:5173
- API docs: http://127.0.0.1:8000/docs
- Smoke check, with the backend already running: `backend/.venv/bin/python scripts/smoke.py`

Expect 18 synthetic transactions (8 original purchase scenarios plus 10 transfers) and 3 alerts. Memory writes default off; explicitly enable `ALLOW_MEMORY_WRITE` locally to test consented memory. In **Today**, open **Possible duplicate**, read the case evidence and follow the privacy link. Optional AI analysis runs only when explicitly requested. Choose normal with separate memory consent, then open **Memory** and confirm deletion. **Activity** keeps the selected frontend's original search/filter/sort and merchant/date/result/amount table; open a merchant row for its case. Existing date/type fields reflect actual movement data. The inspector reloads after confirm and delete.

For the connected main workspace, keep the provided `NESSIE_API_KEY` in `backend/.env` and explicitly set `TRANSACTION_PROVIDER=nessie`. It resolves the first baseline customer from the existing confirmed import mapping; an absent mapping returns `workspace_not_linked` and never chooses another customer. **Data sources > Admin > 使用者交易** selects local customer codes and reuses the updated review pages inside that customer scope. Main navigation returns to the unchanged main identity; it is not a global customer switch. Refresh reads accounts, purchases, transfers, deposits and withdrawals into structured SQLite. All connected data actions, including privacy, confirmations and memory, first refresh Nessie. A failed required collection stops the action with a safe error; previously displayed rows remain labelled cached/unavailable. Transfer records without direction evidence show direction unknown and do not contribute to spending or direction-based rules. Only the latest 100 movements are displayed/analyzed. Nessie lacks validated merchant/category grouping here, so duplicate and subscription assertions are unavailable. A transfer 404 is an error, never an empty success or an automatic creation request.

Shared steps, role-specific keys, and fixes: [TEAM-SETUP-60MIN.md](TEAM-SETUP-60MIN.md).

Explicit synthetic transfer setup is available from `backend/` with `.venv/bin/python -m app.adapters.seed_nessie --transfers`. It requires the selected Nessie provider, backend key and confirmed existing baseline account mappings. It retains existing transfers, adds only the deficit to 10 per account, and verifies each creation through readback. Repeating the verified setup created zero records. The current sandbox has 18 accounts and 180 transfers. Ordinary browsing and refresh never create banking records; genuine provider failures still stop connected actions.

## Tests

```bash
bash scripts/check.sh
```

That runs backend Ruff and pytest, frontend typecheck, Vitest, production build and Admin browser checks. CI uses `backend/requirements.lock.txt` and `frontend/package-lock.json`, has no vendor secrets and does not call live APIs. Offline golden fixtures are checked with `python3 scripts/generate_synthetic_data.py --check`.

The live memory check is separate and spends a small number of Backboard calls. It creates two temporary assistants, proves they do not share memories, then deletes them. From `backend/`:

```bash
BACKBOARD_LIVE_TEST=1 .venv/bin/python -m pytest -q tests/integration/test_backboard_live.py
```

Leave that variable unset for `bash scripts/check.sh`. The key stays in `backend/.env`. The test does not print it.

## Show that memory is really Backboard

Start the backend with `ALLOW_MEMORY_WRITE=true` and `BACKBOARD_API_KEY` set in `backend/.env`. The frontend never receives that key.

1. `GET /api/v1/health` before any memory call in this process. Expect `memory_mode=local-fallback`. A saved key does not change that by itself.
2. Confirm an **open** flagged alert as `normal` with `consent_to_memory=true`. Repeating an alert that was already confirmed does not write a new remote memory. `alert_txn_syn_005` is the electronics amount alert in the fixture.
3. `GET /api/v1/memories`. The row `source` is `backboard`. The summary is only the category sentence, with no merchant or amount.
4. `GET /api/v1/privacy/preview/txn_syn_005`. `prior_user_confirmation` is `normal` for electronics and stays `unknown` for another category.
5. `GET /api/v1/health` after that preview. `memory_mode` is `backboard-live`.
6. Stop and start the backend. Repeat steps 3 and 4. The same row is still there.
7. Send the same confirmation again. The stored `memory_id` comes back, and the memory list does not grow.

GETs and confirmations never invoke fraud inference. Only an explicitly configured POST analysis attempts the provider; a failure leaves the rule result and reports degraded for that request. The prior confirmation adds one evidence line without clearing `needs_human`. Admin customer contexts use server-resolved, credential-scoped owners; the same connected customer shares decisions with Overview while other customers and the offline baseline remain isolated.

## External APIs

| Service | In this repo | Credential | Called today |
|---|---|---|---|
| Jev through Backboard | Bounded System One call through `core/jev.py` | `BACKBOARD_API_KEY` | Explicit `FRAUD_PROVIDER=backboard-jev`, only POST analyses; key alone does not enable it |
| Direct TypeSafe API | Not used. Optional vendor route | `JEV_API_KEY` is unused | No |
| Backboard memory | Explicit CRUD in `backboard_client.py`; committed consent and durable recovery in SQLite | `BACKBOARD_API_KEY`; owner assistant stored in SQLite | Only for enabled, explicitly consented memory or subsequent read/delete |
| Nessie sandbox | Allowlisted GETs, shared cached workspace and explicit `app.adapters.seed_nessie` baseline CLI | `NESSIE_API_KEY` stays backend-only | Connected data actions, Admin queries and metadata prerequisites, or explicit CLI invocation; browsing never creates banking records |

`docs/.env.example` lists extra URLs and model names. `backend/app/core/config.py` does not read those fields. Do not treat that example as the live configuration.

## Safety

- Localhost only. One server-selected demo user. No production login.
- Keys stay in `backend/.env`, which Git ignores. Bootstrap does not overwrite an existing `.env`.
- The AI payload is built from an allowlist. Raw ids, merchant text, exact amounts, and exact timestamps stay out.
- Memory writes default off and require decision `normal` plus explicit consent. Sources are labelled `local-fallback` or `backboard`; uncertain writes stay pending and are never automatically posted again.
- Admin displays local resource codes and safe typed projections read back from SQLite. History stores status/time metadata only; startup removes legacy raw history, preserving confirmations and import progress.
- Do not commit `.env`, SQLite databases, `.venv`, or `node_modules`.
- No real customer financial data in the hackathon build.

## AI assistance

The starter application and the original design notes include material prepared with OpenAI Codex. Later memory-feedback work and this ownership documentation were prepared with Grok. Credit the tools the team actually uses in the Technica submission. Do not claim measured model accuracy, vendor cost, or compliance that this repository has not tested.

The v0.2.0/v0.2.1 Nessie updates and v0.3.0 UI/data integration were implemented and checked with OpenAI Codex.
