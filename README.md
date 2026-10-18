# TrustLedger · Technica 2026

TrustLedger is a B2C, privacy-first financial assistant. It reviews simulated banking transactions, explains patterns that need a person, and stores only an explicit, minimized memory of what that person confirmed.

This repository is a working synthetic demo. It is not a live bank connection and it does not move money.

**Deadline:** 18 October 2026, 12:00 PM EDT.

**Repository:** https://github.com/BrianChengEn/trustledger (private; teammates must accept the invitation).

## Current status

Verified on `main` at `5be26c1` (merge of PR #3), plus the documentation in this commit.

| Area | Status |
|---|---|
| Synthetic transactions, rules, review UI, Privacy Inspector | Implemented |
| SQLite confirmations and consented category memory | Implemented, local fallback |
| Consented memory affects the next analysis | Implemented on `main` |
| Jev through Backboard | Implemented. Live only when `BACKBOARD_API_KEY` is set and the response parses |
| Direct TypeSafe API | Not selected and not called |
| Backboard persistent memory | Implemented behind `BACKBOARD_API_KEY`. No key uses SQLite. Live memory is not verified until a real provider response succeeds |
| Capital One Nessie | Stub. Synthetic fixture is the data source |
| GitHub Actions CI | Passing on the PR #3 merge to `main` |
| Production auth, hosting, deployment | Not started |

Health reports `synthetic`, `rules-only`, and `local-fallback` when `ALLOW_MEMORY_WRITE=true` and no live call has succeeded. Filling an API key does not by itself report `rules+jev-live` or `backboard-live`.

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

Older design notes remain in `docs/00` through `docs/07` and `docs/prompts/`. Where they describe Jev, Backboard, or Nessie as already called, treat them as the target design. [ARCHITECTURE.md](ARCHITECTURE.md) is the current implementation.

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
| Analysis | Deterministic rules, plus Jev through Backboard when a key is set |
| Memory | SQLite through the Python standard library |
| Banking | Synthetic fixture. Nessie is still a stub |

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

Expect 8 synthetic transactions and 3 alerts. Open **Possible duplicate**, read the evidence and Privacy Inspector, confirm normal with memory consent, then open **Confirmed memory** and delete the row. The inspector reloads after confirm and delete.

Shared steps, role-specific keys, and fixes: [TEAM-SETUP-60MIN.md](TEAM-SETUP-60MIN.md).

## Tests

```bash
bash scripts/check.sh
```

That runs backend Ruff and pytest, then frontend typecheck, Vitest, and production build. CI runs the same checks from `backend/requirements.lock.txt` and `frontend/package-lock.json`. CI has no vendor secrets and does not call live APIs.

## External APIs

| Service | In this repo | Credential | Called today |
|---|---|---|---|
| Jev through Backboard | `POST https://app.backboard.io/api/threads/messages` from `jev_client.py` | `BACKBOARD_API_KEY` | Only when that key is non-empty |
| Direct TypeSafe API | Not used. Optional vendor route | `JEV_API_KEY` is unused | No |
| Backboard memory | `backboard_client.py` still raises `NotImplementedError` | Assistant id is not read | No |
| Nessie sandbox | `backend/app/adapters/nessie.py` raises `NessieNotConfigured` | `NESSIE_API_KEY` is loaded and unused | No |

`docs/.env.example` lists extra URLs and model names. `backend/app/core/config.py` does not read those fields. Do not treat that example as the live configuration.

## Safety

- Localhost only. One server-selected demo user. No production login.
- Keys stay in `backend/.env`, which Git ignores. Bootstrap does not overwrite an existing `.env`.
- The AI payload is built from an allowlist. Raw ids, merchant text, exact amounts, and exact timestamps stay out.
- Memory is written only for decision `normal` plus explicit consent, and the UI labels it `local-fallback`.
- Do not commit `.env`, SQLite databases, `.venv`, or `node_modules`.
- No real customer financial data in the hackathon build.

## AI assistance

The starter application and the original design notes include material prepared with OpenAI Codex. Later memory-feedback work and this ownership documentation were prepared with Grok. Credit the tools the team actually uses in the Technica submission. Do not claim measured model accuracy, vendor cost, or compliance that this repository has not tested.
