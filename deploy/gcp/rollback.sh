#!/usr/bin/env bash
set -euo pipefail
sha=${1:?Supply the previously verified release SHA}
[[ "$sha" =~ ^[0-9a-f]{40}$ ]]
release=/opt/trustledger/releases/$sha
[[ -x "$release/backend/.venv/bin/uvicorn" && -f "$release/frontend/dist/index.html" ]]
# Code-only rollback. Never restore, delete, reseed or replace SQLite files.
sudo systemctl stop trustledger
ln -s "$release" /opt/trustledger/current.next
mv -Tf /opt/trustledger/current.next /opt/trustledger/current
sudo systemctl start trustledger
curl --retry 10 --retry-connrefused --retry-delay 1 --fail --silent http://127.0.0.1:8000/api/v1/health
