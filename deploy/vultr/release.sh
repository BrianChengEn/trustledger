#!/usr/bin/env bash
# Run as the non-root deployment account, with sudo for service activation only.
set -euo pipefail
sha=${1:?Usage: release.sh TESTED_SHA APPROVED_SHA}
approved=${2:?Supply the commit explicitly approved by the release owner}
[[ "$sha" =~ ^[0-9a-f]{40}$ && "$sha" == "$approved" ]] || { echo 'Exact tested and approved SHAs must match.' >&2; exit 1; }
repo=$(git rev-parse --show-toplevel)
[[ $(git -C "$repo" rev-parse "$sha^{commit}") == "$sha" ]]
release=/opt/trustledger/releases/$sha
[[ ! -e "$release" ]] || { echo 'Release already exists; use rollback.sh for a verified release.' >&2; exit 1; }
mkdir "$release"
git -C "$repo" archive "$sha" | tar -x -C "$release"
[[ ! -e "$release/backend/.env" ]]
python3 -m venv "$release/backend/.venv"
"$release/backend/.venv/bin/pip" install -r "$release/backend/requirements.lock.txt"
(cd "$release/frontend" && env -i PATH="$PATH" HOME="$HOME" npm ci && env -i PATH="$PATH" HOME="$HOME" npm run build)
# Never copy a database into a release or seed/reset persistent state here.
old=$(readlink -f /opt/trustledger/current || true)
sudo systemctl stop trustledger || true
if ! sudo python3 "$repo/deploy/vultr/backup.py"; then
    sudo systemctl start trustledger || true
    echo "Backup failed; activation cancelled." >&2
    exit 1
fi
ln -s "$release" /opt/trustledger/current.next
mv -Tf /opt/trustledger/current.next /opt/trustledger/current
sudo systemctl start trustledger
for attempt in {1..20}; do
    if curl --fail --silent http://127.0.0.1:8000/api/v1/health >/dev/null; then
        if [[ -n "$old" ]]; then
            ln -s "$old" /opt/trustledger/previous.next
            mv -Tf /opt/trustledger/previous.next /opt/trustledger/previous
        fi
        echo "Activated $sha; external HTTPS verification is still required."
        exit 0
    fi
    sleep 1
done
if [[ -n "$old" ]]; then
    ln -s "$old" /opt/trustledger/current.next
    mv -Tf /opt/trustledger/current.next /opt/trustledger/current
    sudo systemctl restart trustledger
else
    sudo systemctl stop trustledger
fi
echo 'Health failed; previous code restored when available. Persistent data was not restored or reset.' >&2
exit 1
