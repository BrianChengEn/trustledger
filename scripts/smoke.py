"""Run only against the local synthetic development server. Uses standard-library HTTP."""
import json
from urllib.request import Request, urlopen


def call(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request("http://127.0.0.1:8000/api/v1" + path, data=data,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=5) as response:
        return json.load(response)


health = call("/health")
assert health["data_mode"] == "synthetic"
assert len(call("/transactions")) == 8
alerts = call("/alerts")
assert len(alerts) == 3
assert call("/analyses", {"transaction_id": "txn_syn_004"})["alert_type"] == "duplicate"
preview = call("/privacy/preview/txn_syn_004")["safe_payload"]
assert len(preview) == 8 and "account_token" not in preview
print("PASS: health, eight transactions, three alerts, analysis, eight safe features.")
