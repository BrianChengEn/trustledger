#!/usr/bin/env bash
set -euo pipefail
# Install as /usr/local/sbin/trustledger-renew-certificate, root-owned.
# Certbot must be >=5.4, with an existing webroot IP certificate lineage.
/opt/trustledger-certbot/bin/certbot renew --cert-name 35.227.39.10 --quiet --deploy-hook '/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx'
