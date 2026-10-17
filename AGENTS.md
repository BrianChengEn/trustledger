# TrustLedger team implementation rules

Read README.md, TEAM-SETUP-60MIN.md, docs/START-HERE.md, the assigned role document,
and contracts/internal-api.openapi.yaml before changing code.

- Synthetic-only default. No live bank accounts, real financial data or automatic financial action.
- API keys stay in backend/.env or runtime secrets. Never send raw IDs or merchant text to AI.
- AI owner: backend/app/services/ai/** and backend/tests/unit/ai/**.
- Frontend owner: frontend/**. Data owner: backend/app/adapters/**,
  backend/app/schemas/transaction.py and fixtures/**.
- Integrator owner: backend/app/api/**, backend/app/core/**, backend/app/main.py,
  shared dependencies, integration tests, CI, contracts/**.
- Agree on contract changes before implementation; preserve the synthetic baseline.
- Jev, Backboard and Nessie files are explicit extension points, not live implementations.
- Local memory must be labelled local-fallback; only write after normal confirmation + consent.
- Run bash scripts/check.sh. Do not claim tests pass if dependencies could not be installed.
- Never commit node_modules, .venv, .env, databases, or credentials.
- Credit AI tools in the submission. This starter includes AI-generated code and documentation.

## Lifecycle and Nessie design work

Use `/Users/kenny/Desktop/project-development-workflow/SKILL.md` and its `rule.md` as the sole lifecycle router; preserve all team ownership, safety, contract, and CI requirements above.

The Nessie console design is indexed at [docs/v0.0.0/README.md](docs/v0.0.0/README.md), with [Traditional Chinese](docs/v0.0.0/README.zh-TW.md). Q020 selects integration through the left WORKSPACE → Admin entry. Preserve the synthetic baseline and consent-based memory; agree on additive Admin contracts before implementation. The fixture check is `python3 scripts/generate_synthetic_data.py --check`.
