# TrustLedger team implementation rules

Read README.md, TEAM_ROLES.md, TECH_STACK.md, ARCHITECTURE.md, TEAM-SETUP-60MIN.md,
and contracts/internal-api.openapi.yaml before changing code.

People: Brian (`BrianChengEn`, AI), Benson (`benson5112`, API and CI),
Ian (`IanChou89`, frontend), Kenny (`mrkennylee`, Nessie and fixtures).
New branches: `feat/ai-engine`, `feat/backend-integration`, `feat/frontend`,
`feat/nessie-data`. Do not reset existing `backend`, `ianthechou`, `mrkennylee`,
or `feat/local-memory-feedback`.

- Synthetic-only default. No live bank accounts, real financial data or automatic financial action.
- API keys stay in backend/.env or runtime secrets. Never send raw IDs or merchant text to AI.
- AI owner: backend/app/services/ai/** and backend/tests/unit/ai/**.
- Frontend owner: frontend/**. Data owner: backend/app/adapters/**,
  backend/app/schemas/transaction.py and fixtures/**.
- Integrator owner: backend/app/api/**, backend/app/core/**, backend/app/main.py,
  shared dependencies, integration tests, CI, contracts/**.
- Agree on contract changes before implementation; preserve the synthetic baseline.
- Jev is called through Backboard System One only with FRAUD_PROVIDER=backboard-jev
  and a BACKBOARD_API_KEY. A key alone never activates inference; only POST analyses
  may call it, at most once. Rules remain authoritative.
  The direct TypeSafe API is not the selected route. The Nessie dashboard adapter
  remains an extension point. Backboard memory uses explicit consented CRUD;
  inference memory stays off. Admin sandbox reads and the explicit SQLite baseline
  CLI are implemented. A missing key uses rules-only/local-fallback; failed calls
  are degraded and must not be labeled rules+jev-live or backboard-live.
  `bash scripts/check.sh` must not call Backboard. The opt-in live memory test is
  `BACKBOARD_LIVE_TEST=1` pytest `backend/tests/integration/test_backboard_live.py`.
- Local memory must be labelled local-fallback; only write after normal confirmation + consent.
- Run bash scripts/check.sh. Do not claim tests pass if dependencies could not be installed.
- Never commit node_modules, .venv, .env, databases, or credentials.
- Credit AI tools in the submission. This starter includes AI-generated code and documentation.

## Update rules

- Use `docs/00-*.md` through `docs/07-*.md` as the governing implementation constraints; keep the effective update designs under local `docs/vx.x.x/`. Preserve historical designs and user-authored notes.
- Use `/Users/kenny/Desktop/project-development-workflow/SKILL.md` and its `rule.md` as the sole lifecycle router; preserve ownership, contract, safety and CI requirements above.
- Runtime synthetic data uses structured SQLite; JSON files are offline compatibility fixtures only. Admin uses local resource codes and stores status/time metadata, never raw response bodies or browser-facing remote IDs. Content comparison is disabled.
- Every PR excludes all newly added Markdown files. Honor the tracked ignore rule and never force-add local design documents. Check compatibility and the governing constraints before each update.
