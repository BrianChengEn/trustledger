#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
backend/.venv/bin/python scripts/seed_level2_pair.py
# Empty environment values override .env. Auth settings are intentionally inherited.
export DATABASE_PATH="$PWD/backend/data/level2-similar-alerts.db"
export SOURCE_DATABASE_DIR="$PWD/backend/data/level2-sources"
export TRANSACTION_PROVIDER=synthetic FRAUD_PROVIDER=rules-only ALLOW_MEMORY_WRITE=true
export BACKBOARD_API_KEY='' GEMINI_API_KEY='' JEV_API_KEY='' NESSIE_API_KEY=''
export BACKBOARD_LIVE_TEST=0 GEMINI_LIVE_TEST=0 BACKBOARD_LIVE_SEARCH_TEST=0
cd backend
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
