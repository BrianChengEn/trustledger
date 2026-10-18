#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export SOURCE_DATABASE_DIR="${SOURCE_DATABASE_DIR:-$PWD/backend/data/sources}"
# Resolve the source browser's registry; never seed or overwrite sources.
if [[ -z "${DEMO_ACCOUNT_TOKEN:-}" ]]; then
  DEMO_ACCOUNT_TOKEN=$(backend/.venv/bin/python - <<'PY'
import json, os, sqlite3
from pathlib import Path
path = Path(os.environ['SOURCE_DATABASE_DIR']) / 'account-demo'
json.loads((path / 'manifest.json').read_text())
assert all((path / f'{source}.db').is_file() for source in ('nessie', 'banksim'))
with sqlite3.connect((path / 'nessie.db').as_uri() + '?mode=ro', uri=True) as db:
    row = db.execute('SELECT account_token FROM accounts ORDER BY label LIMIT 1').fetchone()
    if row is None:
        raise SystemExit('Generate account-demo data first; see README.')
    print(row[0])
PY
  )
fi
export DEMO_ACCOUNT_TOKEN
export DATABASE_PATH="$PWD/backend/data/account-user-demo.db"
export TRANSACTION_PROVIDER=account-demo FRAUD_PROVIDER=rules-only ALLOW_MEMORY_WRITE=true ALLOW_DEMO_EDIT=false
export BACKBOARD_API_KEY='' GEMINI_API_KEY='' JEV_API_KEY='' NESSIE_API_KEY=''
export BACKBOARD_LIVE_TEST=0 GEMINI_LIVE_TEST=0 BACKBOARD_LIVE_SEARCH_TEST=0
export FRONTEND_ORIGIN=http://127.0.0.1:5174
printf 'Local synthetic Nessie history: %s (100 records)\n' "$DEMO_ACCOUNT_TOKEN"
cd backend
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-access-log
