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
- Jev is called through Backboard System One when BACKBOARD_API_KEY is set.
  The direct TypeSafe API is not the selected route. Nessie remains an extension
  point. Backboard memory is explicit CRUD for one consented category sentence.
  Inference does not set memory=Auto. A missing key stays on SQLite and is
  labelled local-fallback. A failed call stays degraded and must not be labelled
  backboard-live or rules+jev-live.
- Local memory must be labelled local-fallback; only write after normal confirmation + consent.
- Run bash scripts/check.sh. Do not claim tests pass if dependencies could not be installed.
- Never commit node_modules, .venv, .env, databases, or credentials.
- Credit AI tools in the submission. This starter includes AI-generated code and documentation.
