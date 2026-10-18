# TrustLedger · Technica 2026

TrustLedger is a B2C, privacy-first financial assistant. It reviews simulated banking transactions, explains patterns that need a person, and stores only an explicit, minimized memory of what that person confirmed.

This repository is a working synthetic demo. It is not a live bank connection and it does not move money.

**Deadline:** 18 October 2026, 12:00 PM EDT.

**Repository:** https://github.com/BrianChengEn/trustledger (private; teammates must accept the invitation).

## Current status

The v0.3.1 update integrates Ian’s updated frontend (`ianthechou`, `9c40b01`) with the v0.3.0 synthetic/Nessie backend. It retains the new palette, viewport-scaled frame, navigation menus, customizable widgets and Auto/Light/Dark themes. Today, Activity, Case, Privacy and Memory share the same components in the main workspace and isolated Data sources/Admin customer reviews. Synthetic remains the default. Existing generators, 18 offline records, common account codes, legacy aliases and explicit Nessie setup are retained. Connected data actions still require fresh Nessie acquisition. On 17 October 2026, explicit Backboard memory CRUD was checked against the live API: create, store, retrieve, reuse, two-owner isolation, restart, and delete. System One classification on that same account returned HTTP 402 `Insufficient credits for System One`. Failed inference preserves the rule result and reports `degraded`. Do not buy credits or turn on auto-reload.

| Area | Status |
|---|---|
| Synthetic transactions, rules, review UI, Privacy Inspector | Implemented |
| SQLite synthetic data, confirmations and consented category memory | Implemented; JSON remains an offline fixture only |
| Consented memory affects the next analysis | Implemented on `main` |
| Jev through Backboard | Explicitly configured POST analyses may attempt inference. HTTP 402 preserves rules and reports request-specific degraded mode; GET/confirmation stays rules-only |
| Gemini explanations | Explicit case action in the main or scoped customer workspace; privacy-safe summary only. Missing key uses a rules template; failed calls use a labelled fallback. Explanations do not change decisions or memory. |
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

## Sign in (user and admin)

The app opens on a sign-in page. Choose **User** or **Admin**, then type the passcode set in `backend/.env`
(copy `backend/.env.example`; that file is git-ignored):

| Role | Sees | Passcode setting |
| --- | --- | --- |
| User | Today, Activity, Privacy, Memory | `DEMO_USER_PASSCODE` |
| Admin | Demo data editor (add, edit, delete charges, inject scenarios, reset), Data sources (Nessie console), "Preview as user" | `DEMO_ADMIN_PASSCODE` |

Set `REQUIRE_LOGIN=true`, `ALLOW_DEMO_EDIT=true` and a random `SESSION_SECRET`, then restart the backend. This is a
localhost demo gate, not production authentication. Admin edits only change synthetic data; the first edit makes a
`.pre-demo-edit.bak` copy of the database, and **Reset demo** restores the original 18 charges.

## Local account datasets

The Admin **Data sources → 交易資料來源** table browses source-isolated local accounts through the existing search, selector, table, and record pages. The `account-demo-v3` batch preserves **every BankSim transaction under its original customer**, with one local account per customer, while generating **100 Nessie records per account across all four transaction kinds**. The original source views, explicit Nessie refresh and default 18-record product demo remain unchanged. No banking records are created remotely.

Prepare an existing normalized Nessie snapshot, then explicitly generate a **new** local batch:

```bash
backend/.venv/bin/python scripts/import_source_databases.py --nessie-cache backend/data/trustledger-demo.db
backend/.venv/bin/python scripts/generate_account_demo.py --banksim-csv /path/to/banksim.csv --nessie-db backend/data/sources/nessie.db
```

The complete checked BankSim CSV produces 4,112 accounts and **594,643 transactions**, with **5–265 records per original user**. No row is sampled away, duplicated, reassigned to another customer or padded to 100. Source transaction IDs/row keys, customer/merchant features, all 15 categories, exact EUR amounts and simulation days are preserved. Ground-truth labels remain offline: all 7,200 original positive rows are retained without imposing a quota on individual customers.

Nessie type quotas use the pinned [2025 DCPC research profile](fixtures/dcpc2025-kind-profile.json): **85.652453% purchase, 5.330061% transfer, 7.987865% deposit and 1.029620% withdrawal**. These are analyst-derived, individually weighted probabilities conditional on identifiable diary events, not official Federal Reserve bank-ledger shares. The fixture records the official source URLs, archive fingerprint, exact weighted counts, classification and exclusions. It contains aggregates only, not respondents' financial histories. The original cache's 1/180/48/48 inventory no longer determines quotas.

Round the cohort's 100-per-account slots by largest fractional remainder, then balance remaining slots deterministically over the seeded account order. The 18-account cohort has **1,542 purchases, 96 transfers, 144 deposits and 18 withdrawals**: 12 accounts have 86/5/8/1 and six have 85/6/8/1. A single-account demonstration rounds to 86/5/8/1. Finite integer quotas approximate the target probabilities; they are controlled synthetic scenarios, not independent random samples or observed account histories. Select matching templates only from the same account. A missing account/type gets a local template explicitly recorded under `nessie-synthetic-kinds-v1`; it inherits only that account's base amount, date precision and settlement, uses a simulated type-appropriate direction and supplies no invented merchant/category/subscription fact. The batch remains labelled synthetic-derived, never live acquisition. `manifest.json` records the research profile ID, input inventory, cohort/account quotas and missing-template coverage. The batch signature includes the calibration file fingerprint; derived owners also include the signature, isolating decisions and memories when sources, seed or calibration change. Amount, merchant, timestamp, settlement, subscription and fraud distributions are not recalibrated.

Fraud labels are separate from these transaction kinds. Nessie's 22 simulated positive assignments remain offline examples, not observed fraud or measured detector accuracy. No labels enter runtime SQLite, browser responses, rules, Gemini, Jev or Backboard. The original CSV and source/product databases remain unchanged.

Existing v1/v2 data remains historical. V1 sampled/reassigned BankSim cases; v2 preserved complete BankSim histories but used cache-frequency Nessie quotas (1/63/18/18 for the checked source). **Do not overwrite installed directories or replace published assets.** Generate v3 alongside them with `--output-dir backend/data/v3/sources/account-demo --labels-dir evaluation/datasets/account-demo-v3-labels`, then start the backend with `SOURCE_DATABASE_DIR` set to the absolute `backend/data/v3/sources` path. Use the same source directory for the Nessie account-demo launcher. Source hashes, generator version, calibration fingerprint and seed identify each batch; altered inputs require a new output directory. A v3 dataset Release has not been published by this change; use explicit local generation rather than assuming the older v2 download contains the new probabilities.

### Share the same account snapshot through GitHub Releases

Git tracks the schema, generator, and installer. A versioned **dataset Release** distributes the two generated SQLite snapshots without adding databases to Git history. Teammates download the same starting transactions; their later confirmations and memories remain independent. No live provider key or original CSV is needed to install a snapshot. Repository access is required for the private Release.

In a fresh checkout containing this installer, run `bash scripts/bootstrap-mac.sh`, then download both assets from the selected dataset Release. For the corrected v2 bundle (the historical v1 Release remains available):

```bash
gh release download dataset-2026-10-18-v2 --repo BrianChengEn/trustledger \
  --pattern 'trustledger-account-demo-2026-10-18-v2.zip*' --dir artifacts/account-demo-download
backend/.venv/bin/python scripts/account_demo_bundle.py install \
  --archive artifacts/account-demo-download/trustledger-account-demo-2026-10-18-v2.zip \
  --sha256 "$(cut -d ' ' -f 1 artifacts/account-demo-download/trustledger-account-demo-2026-10-18-v2.zip.sha256)"
```

Use the Release's tagged code (or the source-fidelity PR before merge); older main checkouts lack this installer. Obtain the checksum from the authenticated, trusted Release alongside the archive. Installation checks it before opening the archive, accepts only the five documented members, validates SQLite integrity/schema/counts, and publishes a complete batch under `backend/data/sources/account-demo`. It rejects existing directories and symlinks. To preserve an existing batch, use `--output-dir backend/data/another-source/sources/account-demo` and start the backend with `SOURCE_DATABASE_DIR` set to the absolute path of `backend/data/another-source/sources`. Stop the backend before installing or changing source directories.

Start the backend and frontend normally, sign in as Admin when login is enabled, and use **Data sources → 交易資料來源** to select a BankSim or Nessie account. The v2 snapshot contains 4,112 complete BankSim accounts/594,643 rows and 18 Nessie accounts/1,800 rows (596,443 total). The installer accepts v1, v2 and v3 while enforcing each version's own history and quota semantics. The ordinary product demo still has 18 transactions; the optional selected-account user workspace incorporates the behavior reviewed in PR #34. This download does not activate live Nessie or AI services. `DATASET-INFO.json` records the compatible code commit, generator version, original/exported fingerprints and counts; retain it and `LICENSE-BANKSIM.txt` with the installed batch.

Maintainers create a new snapshot with the existing backend environment:

```bash
backend/.venv/bin/python scripts/account_demo_bundle.py pack \
  --source-dir backend/data/sources/account-demo \
  --output artifacts/trustledger-account-demo-YYYY-MM-DD-vN.zip \
  --code-ref FULL_COMPATIBLE_CODE_COMMIT_SHA
```

Pack reads a closed, complete generator batch whose fingerprints match its manifest. It refuses noncanonical tables, review/prediction/cache rows, and SQLite sidecars. It copies and revalidates the exact manifest-addressed database bytes, compacts them to remove deleted-page remnants, replaces Nessie credential-scoped provenance owners with opaque local bindings, and preserves all transaction IDs, amounts, currencies, dates, directions, kinds, and source-record provenance. Exported database fingerprints therefore differ from the originals. It includes source attribution and the repository-recorded CC BY-NC-SA 4.0 terms for BankSim-derived data. Original CSVs, product databases, confirmations, memories, credentials, and offline labels are excluded. The corrected v2 snapshot uses the original BankSim fingerprint `e37006f76d993bfaec3a02d717b4f0bdc1ebfa5d36449e91fb7c07e225278377` from `data/manifests/banksim.yaml`. Historical v1 used the separately recorded `ad04de75f3e95e45a04ddba1d7780e66aa812eaf7d21af33883a744c95989a67` input; neither identity is silently relabelled.

The installer reserves a fresh directory and publishes its `manifest.json` readiness marker last. An ordinary failure removes only its own staged files. A process crash can leave an unpublished directory; preserve it for inspection and choose a fresh destination on retry. No existing dataset is replaced.

After validating an install and reviewing the contents, attach the ZIP and its `.sha256` sidecar to a new private-repository dataset Release pinned to the reviewed code commit. Never replace an existing dataset version or commit the generated artifacts. Changes to source inputs require a new dataset version. Bundle tooling and verification were assisted by OpenAI Codex.
### Offline selected-account user workspace

To use one generated Nessie account in the **user's Today / Activity / Case / Privacy / Memory** workspace, start the explicit offline account demo after generating the batch:

```bash
bash scripts/dev-account-demo-backend.sh
# In a second terminal:
cd frontend
API_PROXY_TARGET=http://127.0.0.1:8001 npm run dev -- --port 5174
```

Open `http://127.0.0.1:5174`. The launcher selects the first registered Nessie account and prints its local code; set `DEMO_ACCOUNT_TOKEN=acct_...` before launching to select another Nessie account. It reads the same 100 transaction IDs and fields as the source browser, uses a separate `account-user-demo.db` for account-scoped decisions/memory, clears vendor keys and reports **Synthetic demo data**. Missing or incomplete account data fails without falling back to 18 fixtures. Existing synthetic and live Nessie modes are unchanged. The USD product workspace only accepts Nessie-derived accounts; BankSim remains in the source browser with EUR and simulation days. Date-only rows retain their precision, with no invented merchant identity or recurring-payment inference.

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

The v0.2.0/v0.2.1 Nessie updates and v0.3.0/v0.3.1 UI/data integration were implemented with OpenAI Codex.
