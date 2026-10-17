#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo 'This script is for macOS. See README for manual setup.'; exit 1
fi
# Homebrew may be absent from PATH in a new Terminal session.
for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  if [[ -x "$candidate" ]]; then eval "$("$candidate" shellenv)"; break; fi
done
if ! command -v brew >/dev/null; then
  echo 'Install Homebrew from https://brew.sh/ or install Git, Node 22 and Python 3.12 manually.'
  echo 'Then reopen Terminal and rerun this script.'; exit 1
fi
brew install git node@22 python@3.12 gh
export PATH="$(brew --prefix node@22)/bin:$(brew --prefix python@3.12)/bin:$PATH"
bash scripts/doctor.sh
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
if [[ -f backend/requirements.lock.txt ]]; then
  backend/.venv/bin/python -m pip install -r backend/requirements.lock.txt
else
  backend/.venv/bin/python -m pip install -r backend/requirements.txt
fi
if [[ ! -f backend/.env ]]; then cp backend/.env.example backend/.env; fi
if [[ ! -f frontend/.env.local ]]; then cp frontend/.env.example frontend/.env.local; fi
if [[ -f frontend/package-lock.json ]]; then
  (cd frontend && npm ci)
else
  (cd frontend && npm install)
fi
echo 'Setup complete. Next: bash scripts/check.sh'
echo 'Use two terminals: bash scripts/dev-backend.sh and bash scripts/dev-frontend.sh'
