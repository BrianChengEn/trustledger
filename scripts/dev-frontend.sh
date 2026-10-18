#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"
for brew_bin in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  if [[ -x "$brew_bin" ]]; then export PATH="$PATH:$("$brew_bin" --prefix node@22)/bin"; break; fi
done
exec npm run dev
