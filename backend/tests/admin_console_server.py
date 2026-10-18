"""Browser-test app with isolated SQLite and an in-process synthetic upstream."""

import httpx
import uvicorn
import hashlib

from app.adapters.nessie import NessieClient
from app.adapters.nessie_fixture import load_baseline
from app.adapters.nessie_fixture import BASELINE_SHA256
from app.adapters.nessie import API_BASE
from app.adapters.synthetic import load_transactions
from app.core.config import Settings
from app.main import create_app

accounts_calls = 0


def upstream(request):
    global accounts_calls
    path = request.url.path
    if "f" * 24 in path:
        raise httpx.ReadTimeout("synthetic timeout")
    if "d" * 24 in path:
        return httpx.Response(401, text="Synthetic unauthorized")
    if path == "/customers":
        return httpx.Response(200, json=list(reversed(data["customers"])))
    if path == "/accounts":
        accounts_calls += 1
        return httpx.Response(200, json=list(reversed(data["accounts"])) if accounts_calls % 2
                              else data["accounts"])
    resource = path.split("/")[2]
    if path.startswith("/customers/"):
        result = [a for a in data["accounts"] if a["customer_id"] == resource]
    elif path.endswith('/purchases'):
        result = [dict(_id=f'{index:024x}', amount=row.amount, purchase_date=row.occurred_at.isoformat(),
                       status='completed', payer_id=resource) for index, row in enumerate(
                           [row for row in load_transactions() if row.kind == 'purchase'], 1)] \
            if resource == data['accounts'][0]['_id'] else []
        if result:
            result.append(dict(_id=f'{9:024x}', amount=450, purchase_date='2026-10-13T12:00:00-04:00',
                               status='completed', payer_id=resource))
            result.append(dict(_id=f'{10:024x}', amount=350, purchase_date='2026-10-12T12:00:00-04:00',
                               status='completed', payer_id=resource))
    elif path.endswith('/transfers'):
        result = [dict(id=f'{index + 100:024x}', amount=10 + index * 7,
                       transaction_date=f'2026-10-{18 - index:02d}',
                       status='completed', description='PRIVATE TRANSFER') for index in range(1, 11)]
    elif path.endswith("/deposits") or path.endswith("/withdrawals"):
        kind = path.split("/")[-1]
        result = data[kind + "_by_account"].get(resource, [])
    else:
        result = next((a for a in data["accounts"] if a["_id"] == resource),
                      {"_id": resource, "nickname": '<script>window.injected=true</script>'})
    return httpx.Response(200, json=result)


settings = Settings(_env_file=None, nessie_api_key="isolated-browser-test-key",
                    fraud_provider='rules-only',
                    backboard_api_key="", jev_api_key="", gemini_api_key="", allow_memory_write=True,
                    require_login=True, demo_user_passcode="browser-user-pass", demo_admin_passcode="browser-admin-pass",
                    session_secret="browser-test-session-secret-0123456789abcdef", allow_demo_edit=True)
app = create_app(settings)
data = load_baseline(app.state.store)
with app.state.store.connect() as db:
    run = db.execute('INSERT INTO seed_runs(owner,dataset_sha256,api_base_url,credential_fingerprint,'
                     "state,created_at,updated_at) VALUES(?,?,?,?,'complete','now','now')",
                     (settings.demo_user_id, BASELINE_SHA256, API_BASE,
                      hashlib.sha256(settings.nessie_api_key.get_secret_value().encode()).hexdigest())).lastrowid
    db.execute("INSERT INTO seed_records(run_id,kind,local_id,remote_id,request_fingerprint,state,updated_at) "
               "VALUES(?,'customer',?,?,'browser-test','confirmed','now')",
               (run, data['customers'][0]['_id'], data['customers'][0]['_id']))
app.state.nessie = NessieClient(settings.nessie_api_key.get_secret_value(),
                               transport=httpx.MockTransport(upstream))
append = app.state.store.append_history


for _ in range(52):
    append(settings.demo_user_id, {"source": "synthetic", "query": "accounts.list",
           "resource_id": None, "requested_at": "2026-10-17T10:00:00+00:00", "duration_ms": 1,
           "http_status": 200, "body_format": "json", "response_body": [], "transport_error": None})
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8123, log_level="warning")
