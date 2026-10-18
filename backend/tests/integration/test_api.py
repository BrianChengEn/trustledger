import json
from pathlib import Path

import httpx
import yaml
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator


@pytest.mark.parametrize("consent", [1, "true", "false"])
def test_memory_requires_literal_boolean_consent(client, consent):
    response = client.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                           json={"decision": "normal", "consent_to_memory": consent})
    assert response.status_code == 422
    assert client.get("/api/v1/memories").json() == []


def test_memory_writes_are_disabled_by_default(monkeypatch):
    from app.core.config import Settings

    monkeypatch.delenv("ALLOW_MEMORY_WRITE", raising=False)
    assert Settings(_env_file=None).allow_memory_write is False


def test_failed_memory_does_not_undo_confirmation_or_retry_it(client):
    with client.app.state.store.connect() as db:
        db.execute("CREATE TRIGGER fail_memory BEFORE INSERT ON memories "
                   "BEGIN SELECT RAISE(FAIL, 'synthetic storage failure'); END")
    path = "/api/v1/alerts/alert_txn_syn_004/confirmations"
    body = {"decision": "normal", "consent_to_memory": True}
    response = client.post(path, json=body)
    assert response.status_code == 200
    assert response.json()["decision"] == "normal"
    assert response.json()["memory_status"] == "failed"
    assert response.json()["memory_id"] is None
    assert client.app.state.store.status("demo-user-001", "alert_txn_syn_004") == "normal"
    assert client.get("/api/v1/memories").json() == []
    assert client.post(path, json=body).json()["memory_status"] == "failed"


def test_transactions_use_persistent_sqlite_instead_of_json(client):
    store = client.app.state.store
    owner = client.app.state.settings.demo_user_id
    with store.connect() as db:
        db.execute("UPDATE demo_transactions SET amount_cents=1234 WHERE owner=? AND id=?",
                   (owner, "txn_syn_005"))
    rows = client.get("/api/v1/transactions").json()
    assert next(row for row in rows if row["id"] == "txn_syn_005")["amount"] == 12.34
    analysis = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_005"}).json()
    assert analysis["alert_type"] == "none"
    preview = client.get("/api/v1/privacy/preview/txn_syn_005").json()
    assert preview["safe_payload"]["amount_bucket"] == "10-25"

    from app.main import create_app

    with TestClient(create_app(client.app.state.settings)) as restarted:
        rows = restarted.get("/api/v1/transactions").json()
        assert len(rows) == 18
        assert next(row for row in rows if row["id"] == "txn_syn_005")["amount"] == 12.34


def test_contract_smoke(client):
    root = Path(__file__).resolve().parents[3]
    contract = yaml.safe_load((root / "contracts/internal-api.openapi.yaml").read_text())
    components = contract["components"]
    for path, schema_name in [
        ("/health", "HealthResponse"), ("/privacy/preview/txn_syn_004", "PrivacyPreview"),
    ]:
        r = client.get("/api/v1" + path)
        assert r.status_code == 200
        schema = {"$ref": f"#/components/schemas/{schema_name}", "components": components}
        Draft202012Validator(schema).validate(r.json())
    assert len(client.get("/api/v1/transactions").json()) == 18
    assert len(client.get("/api/v1/alerts").json()) == 3


def test_confirmation_memory_delete_idempotency(client):
    path = "/api/v1/alerts/alert_txn_syn_004/confirmations"
    body = {"decision": "normal", "consent_to_memory": True}
    first = client.post(path, json=body)
    assert first.status_code == 200
    assert first.json()["memory_status"] == "written"
    second = client.post(path, json=body)
    assert second.json()["memory_id"] == first.json()["memory_id"]
    assert client.post(path, json={"decision": "review", "consent_to_memory": False}).status_code == 409
    memories = client.get("/api/v1/memories").json()
    assert len(memories) == 1 and memories[0]["source"] == "local-fallback"
    assert "StreamWave" not in memories[0]["summary"]
    mid = first.json()["memory_id"]
    assert client.delete(f"/api/v1/memories/{mid}").status_code == 204
    assert client.get("/api/v1/memories").json() == []
    assert client.delete(f"/api/v1/memories/{mid}").status_code == 404


def test_consent_off_and_unknown_owner_input(client):
    r = client.post("/api/v1/alerts/alert_txn_syn_005/confirmations",
                    json={"decision": "normal", "consent_to_memory": False})
    assert r.json()["memory_status"] == "not-requested"
    assert client.get("/api/v1/memories").json() == []
    r = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004", "user_id": "another"})
    assert r.status_code == 422
    assert "another" not in r.text
    assert client.get("/api/v1/privacy/preview/missing").status_code == 404


def test_store_owner_isolation(client):
    store = client.app.state.store
    store.confirm("other-user", "alert", "normal", True, "Other user fact", "rid")
    assert client.get("/api/v1/memories").json() == []
    foreign_id = store.list_memories("other-user")[0].memory_id
    assert client.delete("/api/v1/memories/" + foreign_id).status_code == 404


def test_origin_size_and_safe_errors(client):
    assert client.post("/api/v1/analyses", headers={"origin": "https://unexpected.example"},
                       json={"transaction_id": "txn_syn_004"}).status_code == 403
    assert client.post("/api/v1/analyses", content="x" * 17000).status_code == 413
    response = client.post("/api/v1/analyses", json={"transaction_id": {"private": "secret"}})
    assert response.status_code == 422
    assert "secret" not in response.text
    assert set(response.json()["error"]) == {"code", "message", "request_id"}


def test_consented_memory_is_used_on_the_next_analysis(client):
    declined = client.post("/api/v1/alerts/alert_txn_syn_005/confirmations",
                           json={"decision": "normal", "consent_to_memory": False})
    assert declined.json()["memory_status"] == "not-requested"
    review = client.post("/api/v1/alerts/alert_txn_syn_008/confirmations",
                         json={"decision": "review", "consent_to_memory": True})
    assert review.json()["memory_status"] == "skipped"
    assert client.get("/api/v1/privacy/preview/txn_syn_005").json()["safe_payload"][
        "prior_user_confirmation"] == "unknown"
    assert client.get("/api/v1/privacy/preview/txn_syn_008").json()["safe_payload"][
        "prior_user_confirmation"] == "unknown"

    saved = client.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                        json={"decision": "normal", "consent_to_memory": True})
    assert saved.status_code == 200 and saved.json()["memory_status"] == "written"
    preview = client.get("/api/v1/privacy/preview/txn_syn_003").json()
    assert preview["safe_payload"]["prior_user_confirmation"] == "normal"
    assert "StreamWave" not in json.dumps(preview["safe_payload"])
    same = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
    assert same["alert_type"] == "duplicate" and same["needs_human"] is True
    assert any("category as normal" in line for line in same["evidence"])
    unrelated = client.get("/api/v1/privacy/preview/txn_syn_005").json()["safe_payload"]
    assert unrelated["prior_user_confirmation"] == "unknown"
    assert client.delete(f"/api/v1/memories/{saved.json()['memory_id']}").status_code == 204
    cleared = client.get("/api/v1/privacy/preview/txn_syn_004").json()["safe_payload"]
    assert cleared["prior_user_confirmation"] == "unknown"


def test_backboard_failure_and_success_keep_the_rule_contract(monkeypatch, tmp_path):
    from app.core.config import Settings
    from app.main import create_app
    from app.services.ai.jev_client import JevCallError, JevClassification

    settings = Settings(_env_file=None, database_path=tmp_path / "live.db",
                        allow_memory_write=True, backboard_api_key="synthetic-test-key",
                        fraud_provider="backboard-jev")

    async def failed(*_args, **_kwargs):
        raise JevCallError("request_failed")

    monkeypatch.setattr("app.core.jev.classify", failed)
    with TestClient(create_app(settings)) as live:
        body = live.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
        assert body["alert_type"] == "duplicate"
        assert body["provider_mode"] == "degraded"
        assert body["model_version"] is None
        assert live.get("/api/v1/health").json()["analysis_mode"] == "rules-only"
        assert "StreamWave" not in json.dumps(body["safe_payload"] if "safe_payload" in body else body)

    async def succeeded(payload, api_key, client=None):
        assert api_key == "synthetic-test-key"
        assert "merchant_display" not in payload.model_dump()
        return JevClassification(pattern="duplicate", needs_review=0.93,
                                 choice_confidence=0.81, model_version="jev-1.13.0")

    monkeypatch.setattr("app.core.jev.classify", succeeded)
    with TestClient(create_app(settings)) as live:
        body = live.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
        assert body["provider_mode"] == "rules+jev-live"
        assert body["model_version"] == "jev-1.13.0"
        assert body["alert_type"] == "duplicate" and body["needs_human"] is True
        alerts = live.get("/api/v1/alerts").json()
        assert len(alerts) == 3
        assert {item["provider_mode"] for item in alerts} == {"rules-only"}
        assert live.get("/api/v1/health").json()["analysis_mode"] == "rules-only"


def _memory_client(tmp_path, monkeypatch, handler):
    from app.core.config import Settings
    from app.main import create_app
    from app.services.ai.jev_client import JevCallError

    async def no_jev(*_args, **_kwargs):
        raise JevCallError("request_failed")

    monkeypatch.setattr("app.services.ai.decision.classify", no_jev)
    settings = Settings(_env_file=None, database_path=tmp_path / "memory.db",
                        allow_memory_write=True, backboard_api_key="synthetic-test-key")
    app = create_app(settings)
    app.state.backboard_transport = httpx.MockTransport(handler)
    return TestClient(app)


def test_backboard_memory_success_retrieval_and_delete(tmp_path, monkeypatch):
    remote = ["The demo user explicitly confirmed a streaming alert as normal. Recheck future evidence."]
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"null")
        if request.method == "POST" and request.url.path == "/api/assistants":
            text = request.content.decode()
            assert "demo-user-001" not in text and "StreamWave" not in text
            assert "synthetic-test-key" not in text
            return httpx.Response(200, json={
                "name": body["name"],
                "assistant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "created_at": "2026-10-17T00:00:00Z",
            })
        if request.method == "POST" and request.url.path.endswith("/memories"):
            posts.append(body)
            assert set(body) == {"content"} and "StreamWave" not in body["content"]
            remote[:] = [body["content"]]
            return httpx.Response(201, json={"memory_id": "mem_remote_streaming", "content": body["content"]})
        if request.method == "GET" and request.url.path.endswith("/memories"):
            return httpx.Response(200, json={
                "memories": [{"id": "mem_remote_streaming", "content": item} for item in remote],
                "total_count": len(remote),
            })
        if request.method == "DELETE":
            remote.clear()
            return httpx.Response(200, json={"success": True, "message": "deleted"})
        return httpx.Response(500, json={"detail": "unexpected"})

    with _memory_client(tmp_path, monkeypatch, handler) as live:
        assert live.get("/api/v1/health").json()["memory_mode"] == "local-fallback"
        path = "/api/v1/alerts/alert_txn_syn_004/confirmations"
        body = {"decision": "normal", "consent_to_memory": True}
        saved = live.post(path, json=body)
        assert saved.status_code == 200
        assert saved.json()["memory_status"] == "written"
        assert saved.json()["memory_id"] == "mem_remote_streaming"
        again = live.post(path, json=body)
        assert again.json()["memory_id"] == "mem_remote_streaming"
        assert len(posts) == 1
        memories = live.get("/api/v1/memories").json()
        assert len(memories) == 1 and memories[0]["source"] == "backboard"
        assert "StreamWave" not in memories[0]["summary"]
        preview = live.get("/api/v1/privacy/preview/txn_syn_004").json()["safe_payload"]
        assert preview["prior_user_confirmation"] == "normal"
        assert live.get("/api/v1/health").json()["memory_mode"] == "backboard-live"
        assert live.delete("/api/v1/memories/mem_remote_streaming").status_code == 204
        assert live.get("/api/v1/memories").json() == []
        cleared = live.get("/api/v1/privacy/preview/txn_syn_004").json()["safe_payload"]
        assert cleared["prior_user_confirmation"] == "unknown"


def test_backboard_failure_keeps_local_memory_and_label(tmp_path, monkeypatch):
    from app.services.ai.memory_policy import memory_sentence
    from app.adapters.synthetic import load_transactions

    rows = load_transactions()
    fitness = next(row for row in rows if row.id == "txn_syn_008")
    existing = memory_sentence(fitness, "normal", True, True)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/assistants":
            return httpx.Response(200, json={
                "name": "TrustLedger preference memory",
                "assistant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "created_at": "2026-10-17T00:00:00Z",
            })
        return httpx.Response(503, json={"detail": "secret-body"})

    with _memory_client(tmp_path, monkeypatch, handler) as live:
        live.app.state.store.confirm("demo-user-001", "alert_old", "normal", True, existing, "rid")
        saved = live.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                          json={"decision": "normal", "consent_to_memory": True})
        assert saved.status_code == 200
        assert saved.json()["decision"] == "normal"
        assert saved.json()["memory_status"] == "failed"
        memories = live.get("/api/v1/memories").json()
        assert len(memories) == 2
        assert {item["source"] for item in memories} == {"local-fallback"}
        assert existing in {item["summary"] for item in memories}
        assert "secret-body" not in saved.text
        preview = live.get("/api/v1/privacy/preview/txn_syn_004").json()["safe_payload"]
        assert preview["prior_user_confirmation"] == "normal"
        health = live.get("/api/v1/health").json()
        assert health["memory_mode"] == "degraded"
        refused = live.post("/api/v1/alerts/alert_txn_syn_005/confirmations",
                            json={"decision": "normal", "consent_to_memory": False})
        assert refused.json()["memory_status"] == "not-requested"


def test_invalid_backboard_memory_is_not_labeled_remote(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/assistants":
            return httpx.Response(200, json={
                "name": "TrustLedger preference memory",
                "assistant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "created_at": "2026-10-17T00:00:00Z",
            })
        return httpx.Response(201, json={})

    with _memory_client(tmp_path, monkeypatch, handler) as live:
        saved = live.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                          json={"decision": "normal", "consent_to_memory": True})
        assert saved.json()["memory_status"] == "failed"
        memories = live.get("/api/v1/memories").json()
        assert len(memories) == 1 and memories[0]["source"] == "local-fallback"
        assert live.get("/api/v1/health").json()["memory_mode"] == "degraded"


def test_remote_delete_failure_keeps_the_row(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/assistants":
            return httpx.Response(200, json={
                "name": "TrustLedger preference memory",
                "assistant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "created_at": "2026-10-17T00:00:00Z",
            })
        if request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(201, json={"memory_id": "mem_remote_streaming", "content": body["content"]})
        if request.method == "GET":
            return httpx.Response(200, json={"memories": [], "total_count": 0})
        return httpx.Response(503, json={"detail": "secret-body"})

    with _memory_client(tmp_path, monkeypatch, handler) as live:
        saved = live.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                          json={"decision": "normal", "consent_to_memory": True})
        assert saved.json()["memory_status"] == "written"
        denied = live.delete("/api/v1/memories/mem_remote_streaming")
        assert denied.status_code == 502
        assert denied.json()["error"]["code"] == "memory_delete_failed"
        assert "secret-body" not in denied.text
        memories = live.get("/api/v1/memories").json()
        assert len(memories) == 1 and memories[0]["source"] == "backboard"
        assert live.get("/api/v1/health").json()["memory_mode"] == "degraded"


def test_analysis_matches_preview_and_get_limit(client):
    assert client.get("/api/v1/transactions?limit=0").status_code == 422
    assert len(client.get("/api/v1/transactions?limit=2").json()) == 2
    analysis = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
    assert analysis["alert_type"] == "duplicate" and analysis["provider_mode"] == "rules-only"
    payload = client.get("/api/v1/privacy/preview/txn_syn_004").json()["safe_payload"]
    assert payload["same_category_same_amount_24h_count"] == 2


def test_uncertain_memory_survives_restart_and_delete_reconciles_remote(tmp_path, monkeypatch):
    remote = []
    state = {"unavailable": False, "posts": 0, "deletes": 0}

    def handler(request):
        if request.url.path == "/api/assistants":
            return httpx.Response(200, json={"name": "Synthetic memory", "assistant_id":
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "created_at": "2026-10-17"})
        if request.method == "POST":
            store = live.app.state.store
            assert store.status("demo-user-001", "alert_txn_syn_004") == "normal"
            assert store.memory_job("demo-user-001", alert_id="alert_txn_syn_004")["state"] == "pending"
            state["posts"] += 1
            remote.append({"id": "mem_lost_ack", "content": json.loads(request.content)["content"]})
            state["unavailable"] = True
            raise httpx.ReadTimeout("Synthetic lost acknowledgement")
        if request.method == "DELETE":
            assert request.url.path.endswith('/mem_lost_ack')
            state["deletes"] += 1
            remote.clear()
            return httpx.Response(200, json={"success": True, "message": "deleted"})
        if state["unavailable"]:
            return httpx.Response(503, json={"detail": "Synthetic unavailable"})
        return httpx.Response(200, json={"memories": remote, "total_count": len(remote)})

    with _memory_client(tmp_path, monkeypatch, handler) as live:
        path = "/api/v1/alerts/alert_txn_syn_004/confirmations"
        body = {"decision": "normal", "consent_to_memory": True}
        saved = live.post(path, json=body)
        assert saved.status_code == 200 and saved.json()["memory_status"] == "pending"
        memory_id = saved.json()["memory_id"]
        assert memory_id and len(remote) == 1
        assert live.delete("/api/v1/memories/" + memory_id).status_code == 502
        assert len(live.get("/api/v1/memories").json()) == 1
        settings = live.app.state.settings
    from app.main import create_app

    app = create_app(settings)
    app.state.backboard_transport = httpx.MockTransport(handler)
    with TestClient(app) as live:
        assert live.post(path, json=body).json()["memory_status"] == "pending"
        assert state["posts"] == 1
        state["unavailable"] = False
        assert live.delete("/api/v1/memories/" + memory_id).status_code == 204
        assert state["deletes"] == 1 and remote == []
        assert live.get("/api/v1/memories").json() == []
        preview = live.get("/api/v1/privacy/preview/txn_syn_004").json()
        assert preview["safe_payload"]["prior_user_confirmation"] == "unknown"
        assert state["posts"] == 1


def test_uncertain_memory_never_deletes_a_preexisting_remote_fact(tmp_path, monkeypatch):
    content = "The demo user explicitly confirmed a streaming alert as normal. Recheck future evidence."
    remote = [{"id": "mem_preexisting", "content": content}]
    calls = {"posts": 0, "deletes": 0}

    def handler(request):
        if request.url.path == "/api/assistants":
            return httpx.Response(200, json={"name": "Synthetic memory", "assistant_id":
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "created_at": "2026-10-17"})
        if request.method == "POST":
            calls["posts"] += 1
            raise httpx.ReadTimeout("Synthetic uncertain dispatch")
        if request.method == "DELETE":
            calls["deletes"] += 1
            raise AssertionError("Preexisting memory must never be deleted")
        return httpx.Response(200, json={"memories": remote, "total_count": len(remote)})

    with _memory_client(tmp_path, monkeypatch, handler) as live:
        saved = live.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                          json={"decision": "normal", "consent_to_memory": True}).json()
        assert saved["memory_status"] == "pending"
        assert live.delete("/api/v1/memories/" + saved["memory_id"]).status_code == 502
        assert calls == {"posts": 1, "deletes": 0} and len(remote) == 1


def test_confirmation_failure_prevents_every_remote_memory_write(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.method)
        raise AssertionError("Uncommitted confirmation must not call memory provider")

    with _memory_client(tmp_path, monkeypatch, handler) as live:
        with live.app.state.store.connect() as db:
            db.execute("CREATE TRIGGER fail_confirmation BEFORE INSERT ON confirmations "
                       "BEGIN SELECT RAISE(FAIL, 'Synthetic confirmation failure'); END")
        response = live.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                             json={"decision": "normal", "consent_to_memory": True})
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert "Synthetic confirmation failure" not in response.text
        assert live.app.state.store.status("demo-user-001", "alert_txn_syn_004") == "open"
    assert calls == []
