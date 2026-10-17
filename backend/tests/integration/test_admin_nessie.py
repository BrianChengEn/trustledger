from datetime import datetime, timezone
from pathlib import Path
import runpy

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.nessie import NessieClient, QUERIES
from app.core.config import Settings
from app.main import create_app

PREFIX = "/api/v1/admin/nessie"
ORIGIN = {"origin": "http://localhost:5173"}


def test_browser_server_never_uses_ambient_ai_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "browser.db"))
    monkeypatch.setenv("BACKBOARD_API_KEY", "synthetic-ambient-key")
    monkeypatch.setenv("JEV_API_KEY", "synthetic-ambient-key")
    calls = []

    async def unexpected_provider(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Browser tests must not call AI providers")

    monkeypatch.setattr("app.services.ai.decision.classify", unexpected_provider)
    server = runpy.run_path(str(Path(__file__).parents[1] / "admin_console_server.py"))
    with TestClient(server["app"]) as browser:
        response = browser.get("/api/v1/alerts")
        assert response.status_code == 200
        assert len(response.json()) == 3
        assert {row["provider_mode"] for row in response.json()} == {"rules-only"}
    assert calls == []


@pytest.fixture
def admin(tmp_path):
    settings = Settings(_env_file=None, database_path=tmp_path / "db", nessie_api_key="sentinel")
    app = create_app(settings)
    calls = []

    def upstream(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=[{"_id": "1" * 24, "name": "Example"}])

    app.state.nessie = NessieClient("sentinel", transport=httpx.MockTransport(upstream))
    with TestClient(app, base_url="http://127.0.0.1", headers=ORIGIN) as client:
        yield client, calls


def test_six_queries_are_fresh_and_invalid_requests_do_not_execute(admin):
    client, calls = admin
    for query in QUERIES:
        body = {"query": query}
        if "{id}" in QUERIES[query]:
            body["resource_id"] = " A" + "B" * 23 + " "
        for _ in range(2):
            result = client.post(PREFIX + "/query", json=body)
            assert result.status_code == 200, result.text
            saved = result.json()
            assert saved["http_status"] == 200 and saved["write_status"] == "saved"
            assert saved["history_id"] > 0 and saved["source"] == "nessie"
            assert saved["body_format"] == "json"
    assert len(calls) == 12
    for body in [{"query": "invalid"}, {"query": "accounts.get"},
                 {"query": "accounts.get", "resource_id": "../private"},
                 {"query": "accounts.list", "resource_id": "a" * 24},
                 {"query": "accounts.list", "key": "secret"}]:
        result = client.post(PREFIX + "/query", json=body)
        assert result.status_code == 422
        assert "secret" not in result.text
    assert len(calls) == 12


def test_history_write_failure_preserves_result(admin):
    client, calls = admin
    with client.app.state.store.connect() as db:
        db.execute("CREATE TRIGGER fail_history AFTER INSERT ON query_history "
                   "BEGIN SELECT RAISE(FAIL, 'private SQL'); END")
    result = client.post(PREFIX + "/query", json={"query": "accounts.list"}).json()
    assert result["http_status"] == 200 and result["response_body"]
    assert result["history_id"] is None and result["write_status"] == "failed"
    assert result["write_label"] == "failed to write"
    assert "private SQL" not in str(result)
    assert client.get(PREFIX + "/history").json()["items"] == []
    assert len(calls) == 1


def test_loopback_origin_json_and_configuration_guards(admin):
    client, calls = admin
    path = PREFIX + "/query"
    body = {"query": "accounts.list"}
    assert client.post(path, json=body, headers={"host": "remote.example"}).status_code == 403
    assert client.post(path, json=body, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post(path, content='{}', headers={"content-type": "text/plain"}).status_code == 403
    client.headers.pop("origin")
    assert client.post(path, json=body).status_code == 403
    client.headers.update(ORIGIN)
    client.app.state.settings.nessie_api_key = ""
    assert client.post(path, json=body).status_code == 503
    assert calls == []


@pytest.mark.parametrize("status,body", [(200, []), (401, "unauthorized"), (404, {"error": "missing"}),
                                        (500, "failure")])
def test_captured_outcomes_match_checked_in_contract(admin, status, body):
    from pathlib import Path

    import yaml
    from jsonschema import Draft202012Validator

    client, _ = admin
    client.app.state.nessie = NessieClient("sentinel", transport=httpx.MockTransport(
        lambda r: httpx.Response(status, json=body)))
    response = client.post(PREFIX + "/query", json={"query": "customers.list"})
    result = response.json()
    assert result["http_status"] == status and result["response_body"] == body
    contract = yaml.safe_load((Path(__file__).resolve().parents[3] /
                               "contracts/internal-api.openapi.yaml").read_text())
    schema = {"$ref": "#/components/schemas/AdminExecution", "components": contract["components"]}
    Draft202012Validator(schema).validate(result)


def capture():
    return {"source": "synthetic", "query": "accounts.list", "resource_id": None,
            "requested_at": datetime.now(timezone.utc).isoformat(), "duration_ms": 1,
            "http_status": 200, "body_format": "json", "response_body": None,
            "transport_error": None}


def test_paging_restart_delete_owner_and_stale_ids(admin):
    client, calls = admin
    store = client.app.state.store
    owner = client.app.state.settings.demo_user_id
    ids = [store.append_history(owner, capture()) for _ in range(55)]
    foreign = store.append_history("another", capture())
    first = client.get(PREFIX + "/history").json()
    assert len(first["items"]) == 50
    assert "response_body" not in first["items"][0]
    second = client.get(PREFIX + "/history", params={"before_id": first["next_cursor"]}).json()
    assert [r["history_id"] for r in first["items"] + second["items"]] == ids[::-1]
    assert second["next_cursor"] is None
    saved = client.get(PREFIX + f"/history/{ids[0]}").json()
    with TestClient(create_app(client.app.state.settings), base_url="http://localhost",
                    headers=ORIGIN) as restarted:
        assert restarted.get(PREFIX + f"/history/{ids[0]}").json() == saved
    assert saved["body_format"] == "json" and saved["response_body"] is None
    assert client.request("DELETE", PREFIX + "/history", json={}).status_code == 422
    assert client.request("DELETE", PREFIX + "/history", json={"confirm": False}).status_code == 422
    assert client.request("DELETE", PREFIX + f"/history/{foreign}",
                          json={"confirm": True}).status_code == 404
    assert client.request("DELETE", PREFIX + "/history", json={"confirm": True}).json() == {
        "deleted": 55}
    assert client.get(PREFIX + f"/history/{ids[0]}").status_code == 404
    assert store.append_history(owner, capture()) > foreign
    assert store.get_history("another", foreign) is not None
    assert calls == []


def test_compare_uses_saved_rows_and_rejects_stale_or_same_ids(admin):
    client, calls = admin
    store = client.app.state.store
    owner = client.app.state.settings.demo_user_id
    left = store.append_history(owner, capture())
    right = store.append_history(owner, capture())
    result = client.post(PREFIX + "/compare", json={"left_id": left, "right_id": right})
    assert result.status_code == 200
    assert result.json()["comparison"]["data_changed"] is False
    assert client.post(PREFIX + "/compare", json={"left_id": left,
                                                 "right_id": left}).status_code == 422
    assert client.post(PREFIX + "/compare", json={"left_id": left,
                                                 "right_id": 999}).status_code == 404
    assert len(client.get(PREFIX + "/history").json()["items"]) == 2
    assert calls == []


def test_uuid_query_normalizes_and_persists(admin):
    client, calls = admin
    remote_id = "01234567-89ab-cdef-0123-456789abcdef"
    result = client.post(PREFIX + "/query", json={"query": "accounts.get",
                         "resource_id": " " + remote_id.upper() + " "})
    assert result.status_code == 200
    assert result.json()["resource_id"] == remote_id
    assert calls == ["/accounts/" + remote_id]
    assert client.get(PREFIX + "/history/" + str(result.json()["history_id"])).json()[
        "resource_id"] == remote_id


def test_uuid_schema_migration_preserves_rows_and_deleted_id_sequence(tmp_path):
    from app.core.store import Store

    store = Store(tmp_path / "migration.db")
    with store.connect() as db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name='query_history'").fetchone()[0]
        db.execute("DROP TABLE query_history")
        db.execute(sql.replace("length(resource_id) IN (24,36)", "length(resource_id)=24"))
    first = store.append_history("owner", capture())
    last = store.append_history("owner", capture())
    store.delete_history("owner", last)
    restarted = Store(store.filename)
    assert restarted.get_history("owner", first)["response_body"] is None
    uuid_capture = {**capture(), "query": "accounts.get",
                    "resource_id": "01234567-89ab-cdef-0123-456789abcdef"}
    assert restarted.append_history("owner", uuid_capture) > last
