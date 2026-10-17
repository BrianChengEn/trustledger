#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [[ ! -x .venv/bin/python ]]; then echo 'Run bootstrap-mac.sh first.'; exit 1; fi
# Bind localhost and suppress URL access logs (future Nessie query keys must never be logged).
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log
