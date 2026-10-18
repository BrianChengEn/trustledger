"""Level 2 relevant-memory retrieval. No live Backboard or Gemini calls."""
import json

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

ASSISTANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STREAMING = (
    "The demo user explicitly confirmed a streaming alert as normal. Recheck future evidence."
)
FITNESS = (
    "The demo user explicitly confirmed a fitness_subscription alert as normal. "
    "Recheck future evidence."
)
KEY = "synthetic-test-key"
FORBIDDEN = ("StreamWave", "Tech Harbor", "FitFlow", "txn_syn_", "acct_demo", "11.99", "849")


def app_client(path, handler, key):
    settings = Settings(
        _env_file=None, database_path=path, allow_memory_write=True, backboard_api_key=key)
    app = create_app(settings)
    if handler is not None:
        app.state.backboard_transport = httpx.MockTransport(handler)
    return TestClient(app)


def provider(remote, searches, fail_search):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"null")
        text = request.content.decode() if request.content else ""
        assert KEY not in text
        for marker in FORBIDDEN:
            assert marker not in text
        if request.method == "POST" and request.url.path == "/api/assistants":
            return httpx.Response(200, json={
                "name": body["name"], "assistant_id": ASSISTANT,
                "created_at": "2026-10-17T00:00:00Z",
            })
        if request.method == "GET" and request.url.path.endswith("/memories"):
            return httpx.Response(200, json={
                "memories": [{"id": item["id"], "content": item["content"]} for item in remote],
                "total_count": len(remote),
            })
        if request.method == "POST" and request.url.path.endswith("/memories"):
            assert set(body) == {"content"} and body["content"] == STREAMING
            remote.append({"id": "mem_remote_streaming", "content": body["content"]})
            return httpx.Response(201, json={"memory_id": "mem_remote_streaming", "content": body["content"]})
        if request.method == "POST" and request.url.path.endswith("/search"):
            searches.append(body)
            if fail_search[0]:
                return httpx.Response(503, json={"detail": "secret-body"})
            return httpx.Response(200, json={
                "memories": [
                    {"id": "mem_unapproved", "content": "User loves StreamWave", "score": 0.99},
                    {"id": "mem_fitness", "content": FITNESS, "score": 0.91},
                    {"id": "mem_remote_streaming", "content": STREAMING, "score": 0.2},
                ],
                "total_count": 3,
            })
        if request.method == "DELETE":
            remote.clear()
            return httpx.Response(200, json={"success": True, "message": "deleted"})
        return httpx.Response(500, json={"detail": "unexpected"})

    return handler


def decision(body):
    return {key: body[key] for key in ("alert_type", "severity", "needs_human", "evidence")}


def add_later_duplicate(store, owner="demo-user-001"):
    """Test-only second streaming duplicate. The shared baseline is left unchanged."""
    with store.connect() as db:
        db.execute(
            """INSERT INTO demo_transactions
               (owner,id,occurred_at,amount_cents,currency,direction,merchant_display,
                merchant_category,source,account_token,is_subscription,kind)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (owner, "txn_syn_009", "2026-10-17T16:00:00-04:00", 1199, "USD", "debit",
             "StreamWave", "streaming", "synthetic", "acct_demo_a1", 1, "purchase"))


def test_similar_alert_uses_consented_memory_without_changing_rules(tmp_path):
    remote, searches, fail_search = [], [], [False]
    path = tmp_path / "live.db"
    with app_client(path, provider(remote, searches, fail_search), KEY) as live:
        add_later_duplicate(live.app.state.store)
        absent = live.get("/api/v1/transactions/txn_syn_009/relevant-memory")
        assert absent.status_code == 200
        assert absent.json()["memory_status"] == "no-relevant-memory"
        assert absent.json()["alert_type"] == "duplicate" and absent.json()["needs_human"] is True
        assert absent.json()["summary"] is None and searches == []
        saved = live.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                          json={"decision": "normal", "consent_to_memory": True})
        assert saved.status_code == 200 and saved.json()["memory_status"] == "written"
        declined = live.post("/api/v1/alerts/alert_txn_syn_005/confirmations",
                             json={"decision": "normal", "consent_to_memory": False})
        assert declined.json()["memory_status"] == "not-requested"
        ruled = live.post("/api/v1/analyses", json={"transaction_id": "txn_syn_009"}).json()
        found = live.get("/api/v1/transactions/txn_syn_009/relevant-memory")
        assert found.status_code == 200
        body = found.json()
        assert body["memory_status"] == "backboard-live"
        assert body["memory_id"] == "mem_remote_streaming"
        assert body["summary"] == STREAMING
        assert body["relevance"] == "same-category"
        assert body["retrieval"] == "backboard-search"
        assert body["source"] == "backboard"
        assert body["still_requires_review"] is True
        assert body["alert_id"] == "alert_txn_syn_009"
        assert decision(body) == decision(ruled)
        assert body["alert_type"] == "duplicate" and body["needs_human"] is True
        assert "category as normal" in " ".join(body["evidence"])
        later = live.post("/api/v1/analyses", json={"transaction_id": "txn_syn_009"}).json()
        assert decision(later) == decision(ruled)
        status = next(row for row in live.get("/api/v1/alerts").json()
                      if row["transaction_id"] == "txn_syn_009")
        assert status["status"] == "open"
        assert live.app.state.store.status("demo-user-001", "alert_txn_syn_009") == "open"
        unrelated = live.get("/api/v1/transactions/txn_syn_005/relevant-memory").json()
        assert unrelated["memory_status"] == "no-relevant-memory"
        assert unrelated["summary"] is None
        assert unrelated["alert_type"] == "amount_anomaly"
        assert searches == [{"query": "confirmed a streaming alert as normal", "limit": 5}]
        assert FITNESS not in body["summary"]
        assert "User loves StreamWave" not in found.text
        for marker in FORBIDDEN:
            assert marker not in body["summary"]
        assert live.delete("/api/v1/memories/mem_remote_streaming").status_code == 204
        cleared = live.get("/api/v1/transactions/txn_syn_009/relevant-memory").json()
        assert cleared["memory_status"] == "no-relevant-memory"
        assert cleared["summary"] is None and cleared["memory_id"] is None
        assert searches == [{"query": "confirmed a streaming alert as normal", "limit": 5}]
        assert remote == []


def test_search_miss_is_local_and_search_error_is_unavailable(tmp_path):
    remote, searches, fail_search = [], [], [False]

    def missing(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/search"):
            searches.append(json.loads(request.content))
            return httpx.Response(200, json={
                "memories": [{"id": "mem_junk", "content": "User loves StreamWave", "score": 1}],
                "total_count": 1,
            })
        return provider(remote, searches, fail_search)(request)

    with app_client(tmp_path / "miss.db", missing, KEY) as live:
        saved = live.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                          json={"decision": "normal", "consent_to_memory": True})
        assert saved.json()["memory_status"] == "written"
        ruled = live.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
        found = live.get("/api/v1/transactions/txn_syn_004/relevant-memory").json()
        assert found["memory_status"] == "local-fallback"
        assert found["retrieval"] == "category-filter"
        assert found["summary"] == STREAMING
        assert found["source"] == "local-fallback"
        assert "StreamWave" not in found["summary"]
        again = live.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
        assert decision(again) == decision(ruled) == decision(found)

    fail_search[0] = True
    remote.clear()
    searches.clear()
    with app_client(tmp_path / "down.db", provider(remote, searches, fail_search), KEY) as live:
        assert live.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                         json={"decision": "normal", "consent_to_memory": True}).json()["memory_status"] == "written"
        ruled = live.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
        found = live.get("/api/v1/transactions/txn_syn_004/relevant-memory")
        assert found.status_code == 200
        assert found.json()["memory_status"] == "unavailable"
        assert found.json()["summary"] is None and found.json()["memory_id"] is None
        assert "secret-body" not in found.text
        again = live.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
        assert decision(again) == decision(ruled)
        assert live.get("/api/v1/health").json()["memory_mode"] == "backboard-live"


def test_local_memory_persists_across_processes_and_stays_isolated(tmp_path):
    path = tmp_path / "local.db"
    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request.url.path)
        return httpx.Response(500, json={"detail": "secret-body"})

    with app_client(path, handler, "") as first:
        saved = first.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                           json={"decision": "normal", "consent_to_memory": True})
        assert saved.json()["memory_status"] == "written"
        assert saved.json()["memory_id"]
        first.app.state.store.confirm(
            "other-user", "alert_other", "normal", True, FITNESS, "request")
        found = first.get("/api/v1/transactions/txn_syn_003/relevant-memory").json()
        assert found["memory_status"] == "local-fallback"
        assert found["summary"] == STREAMING
        assert found["retrieval"] == "category-filter"
        other = first.get("/api/v1/transactions/txn_syn_008/relevant-memory").json()
        assert other["memory_status"] == "no-relevant-memory"
        assert FITNESS not in json.dumps(other)
        assert called == []
    with app_client(path, handler, "") as second:
        found = second.get("/api/v1/transactions/txn_syn_003/relevant-memory").json()
        assert found["memory_status"] == "local-fallback"
        assert found["summary"] == STREAMING
        assert called == []


def test_unknown_transaction_is_not_found(tmp_path):
    with app_client(tmp_path / "missing.db", None, "") as live:
        response = live.get("/api/v1/transactions/txn_missing/relevant-memory")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_retrieval_does_not_call_the_fraud_provider(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("fraud provider")

    monkeypatch.setattr("app.core.analysis.evaluate_fraud", boom)
    with app_client(tmp_path / "rules.db", None, "") as live:
        response = live.get("/api/v1/transactions/txn_syn_004/relevant-memory")
        assert response.status_code == 200
        assert response.json()["memory_status"] == "no-relevant-memory"
        assert response.json()["needs_human"] is True
