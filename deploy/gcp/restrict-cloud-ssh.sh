#!/usr/bin/env bash
# Run in authorized Cloud Shell. Narrows only this VM; never edits shared defaults.
set -euo pipefail
operator_cidr=${1:?Supply the current verified operator IPv4 CIDR, e.g. x.x.x.x/32}
python3 - "$operator_cidr" <<'PY'
import ipaddress,sys
network=ipaddress.ip_network(sys.argv[1],strict=True)
if network.version != 4 or network.prefixlen != 32:
    raise SystemExit('Supply one verified operator IPv4 /32; do not widen SSH access.')
PY
# Add allow/deny rules BEFORE applying their unique tag. No effect on other VMs.
gcloud compute firewall-rules create trustledger-allow-operator-ssh --project=technica2026 --network=default --direction=INGRESS --priority=900 --action=ALLOW --rules=tcp:22 --source-ranges="$operator_cidr" --target-tags=trustledger-demo
gcloud compute firewall-rules create trustledger-deny-other-ssh-rdp --project=technica2026 --network=default --direction=INGRESS --priority=1000 --action=DENY --rules=tcp:22,tcp:3389 --source-ranges=0.0.0.0/0 --target-tags=trustledger-demo
gcloud compute instances add-tags instance-20261018-124923 --project=technica2026 --zone=us-east1-b --tags=trustledger-demo
# Keep existing SSH open and test a second operator connection before logging out.
