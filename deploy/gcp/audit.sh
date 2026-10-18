#!/usr/bin/env bash
# Read-only host inspection; never reads application secrets or cloud tokens.
set -u
uname -a
cat /etc/os-release
free -m
nproc
df -h / /var /opt
python3 --version
node --version 2>/dev/null || true
nginx -v 2>&1 || true
certbot --version 2>/dev/null || true
sudo -n -l
sudo -n ss -lntp
sudo -n ufw status verbose
systemctl is-active nginx trustledger || true
apt-cache policy python3 python3-venv nginx certbot nodejs
for field in project/project-id instance/name instance/zone instance/machine-type instance/tags; do
    printf '\n%s: ' "$field"
    curl --max-time 3 -fsS -H 'Metadata-Flavor: Google' "http://metadata.google.internal/computeMetadata/v1/$field" || true
    printf '\n'
done
# Existing data: filenames/permissions only; never dump SQLite or runtime.env.
sudo -n find /var/lib/trustledger -maxdepth 2 -type f -printf '%m %u %s %p\n' 2>/dev/null || true
