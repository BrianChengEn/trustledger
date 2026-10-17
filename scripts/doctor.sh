#!/usr/bin/env bash
set -euo pipefail
for executable in git node npm; do
  command -v "$executable" >/dev/null || { echo "Missing: $executable"; exit 1; }
done
git --version
node --version
npm --version
node -e 'const [major,minor]=process.versions.node.split(".").map(Number);if(major<22||(major===22&&minor<12)){console.error("Node >=22.12 is required");process.exit(1)}'
if command -v python3.12 >/dev/null; then python3.12 --version;
elif command -v python3 >/dev/null; then python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"; print(sys.version)';
else echo 'Python 3.12 is missing'; exit 1; fi
echo 'Toolchain checks passed.'
