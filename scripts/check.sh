#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for brew_bin in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  if [[ -x "$brew_bin" ]]; then export PATH="$("$brew_bin" --prefix node@22)/bin:$PATH"; break; fi
done
PYTHON=.venv/bin/python
if [[ ! -x "backend/$PYTHON" ]]; then echo 'Run bash scripts/bootstrap-mac.sh first.'; exit 1; fi
(cd backend && "$PYTHON" -m ruff check app tests && "$PYTHON" -m pytest -q)
(cd frontend && npm run typecheck && npm test && npm run build)
node frontend/tests/admin-console.spec.mjs
echo 'PASS: backend tests/lint and frontend typecheck/tests/build.'
