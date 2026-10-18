"""Browser-test app with isolated SQLite and an in-process synthetic upstream."""

import httpx
import uvicorn

from app.adapters.nessie import NessieClient
from app.adapters.nessie_fixture import load_baseline
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
        return httpx.Response(200, json=data["customers"])
    if path == "/accounts":
        accounts_calls += 1
        return httpx.Response(200, json=list(reversed(data["accounts"])) if accounts_calls % 2
                              else data["accounts"])
    resource = path.split("/")[2]
    if path.startswith("/customers/"):
        result = [a for a in data["accounts"] if a["customer_id"] == resource]
    elif path.endswith("/deposits") or path.endswith("/withdrawals"):
        kind = path.split("/")[-1]
        result = data[kind + "_by_account"].get(resource, [])
    else:
        result = next((a for a in data["accounts"] if a["_id"] == resource),
                      {"_id": resource, "nickname": '<script>window.injected=true</script>'})
    return httpx.Response(200, json=result)


settings = Settings(_env_file=None, nessie_api_key="isolated-browser-test-key",
                    backboard_api_key="", jev_api_key="", allow_memory_write=True)
app = create_app(settings)
data = load_baseline(app.state.store)
app.state.nessie = NessieClient(settings.nessie_api_key.get_secret_value(),
                               transport=httpx.MockTransport(upstream))
append = app.state.store.append_history


for _ in range(52):
    append(settings.demo_user_id, {"source": "synthetic", "query": "accounts.list",
           "resource_id": None, "requested_at": "2026-10-17T10:00:00+00:00", "duration_ms": 1,
           "http_status": 200, "body_format": "json", "response_body": [], "transport_error": None})
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8123, log_level="warning")
