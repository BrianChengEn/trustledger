import logging

import pytest

from app.api.dependencies import get_fraud_provider
from app.core.fraud import MockJevProvider
from app.core.store import Store

PATH = "/api/v1/alerts/alert_txn_syn_004/confirmations"
BODY = {"decision": "normal", "consent_to_memory": True}


def test_memory_insert_failure_returns_safe_failed_confirmation(client, caplog):
    store = client.app.state.store
    with store.connect() as db:
        db.execute("""CREATE TRIGGER fail_memory BEFORE INSERT ON memories
                      BEGIN SELECT RAISE(ABORT, 'key=synthetic-private-marker'); END""")
    caplog.set_level(logging.INFO, logger="app.core.http")
    response = client.post(PATH, json=BODY)
    assert response.status_code == 200
    assert response.json()["memory_status"] == "failed" and response.json()["memory_id"] is None
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    assert "synthetic-private-marker" not in response.text + caplog.text
    assert client.get("/api/v1/alerts").json()[0]["status"] == "normal"
    assert client.get("/api/v1/memories").json() == []
    client.app.state.store = Store(store.filename)
    replay = client.post(PATH, json=BODY)
    assert replay.json()["memory_status"] == "failed"
    assert replay.json()["request_id"] != response.json()["request_id"]
    conflict = client.post(PATH, json={"decision": "review", "consent_to_memory": True})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "confirmation_conflict"
    with store.connect() as db:
        db.execute("DROP TRIGGER fail_memory")
    assert client.post(PATH, json=BODY).json()["memory_status"] == "failed"
    assert client.get("/api/v1/memories").json() == []


@pytest.mark.parametrize("decision,consent,enabled,status", [
    ("normal", True, True, "written"), ("normal", True, False, "skipped"),
    ("normal", False, True, "not-requested"), ("review", True, True, "skipped"),
    ("review", False, False, "not-requested"),
])
def test_http_gates_and_durability(client, decision, consent, enabled, status):
    client.app.state.settings.allow_memory_write = enabled
    response = client.post(PATH, json={"decision": decision, "consent_to_memory": consent})
    assert response.status_code == 200 and response.json()["memory_status"] == status
    reopened = Store(client.app.state.store.filename)
    assert reopened.status(client.app.state.settings.demo_user_id, "alert_txn_syn_004") == decision
    assert len(reopened.list_memories(client.app.state.settings.demo_user_id)) == (1 if status == "written" else 0)


@pytest.mark.parametrize("body", [{"decision": "fraud", "consent_to_memory": True},
                                  {"decision": "normal"},
                                  {"decision": "normal", "consent_to_memory": "true"}])
def test_invalid_confirmation_cannot_persist_or_write_memory(client, body):
    assert client.post(PATH, json=body).status_code == 422
    assert client.get("/api/v1/memories").json() == []
    assert client.get("/api/v1/alerts").json()[0]["status"] == "open"


def test_sanitized_memory_and_owner_scoping(client):
    tx = client.app.state.store.list_transactions(client.app.state.settings.demo_user_id)[4]
    tx.merchant_display = "PRIVATE PERSON key=synthetic-marker"
    tx.merchant_category = "private-category"
    with client.app.state.store.connect() as db:
        db.execute("UPDATE demo_transactions SET merchant_display=?,merchant_category=? WHERE owner=? AND id=?",
                   (tx.merchant_display, tx.merchant_category, client.app.state.settings.demo_user_id, tx.id))
    response = client.post("/api/v1/alerts/alert_txn_syn_005/confirmations", json=BODY)
    assert response.status_code == 200 and response.json()["memory_status"] == "written"
    rows = client.get("/api/v1/memories").json()
    assert len(rows) == 1 and rows[0]["source"] == "local-fallback"
    for value in [tx.id, tx.account_token, tx.merchant_display, tx.merchant_category, "849", "2026-"]:
        assert value not in rows[0]["summary"]
    store = client.app.state.store
    other = store.confirm("other-owner", "alert_other", "normal", True,
                          "Other owner's sanitized summary", "rid")
    assert len(client.get("/api/v1/memories").json()) == 1
    assert client.delete("/api/v1/memories/" + other.memory_id).status_code == 404
    assert len(store.list_memories("other-owner")) == 1
    assert client.delete("/api/v1/memories/" + response.json()["memory_id"]).status_code == 204


@pytest.mark.parametrize("decision,consent", [("normal", True), ("normal", False), ("review", True)])
def test_prior_confirmation_uses_only_consented_normal_matching(client, decision, consent):
    response = client.post(PATH, json={"decision": decision, "consent_to_memory": consent})
    assert response.status_code == 200
    client.app.state.store.confirm("other-owner", "alert", "normal", True,
                                   "Other owner's sanitized summary", "rid")
    expected = "normal" if decision == "normal" and consent else "unknown"
    seen = []

    class Spy(MockJevProvider):
        def assess(self, features):
            seen.append(features.prior_user_confirmation)
            return super().assess(features)

    client.app.dependency_overrides[get_fraud_provider] = lambda: Spy()
    for tx_id in ["txn_syn_004", "txn_syn_003"]:
        preview = client.get("/api/v1/privacy/preview/" + tx_id)
        assert preview.json()["safe_payload"]["prior_user_confirmation"] == expected
        assert client.post("/api/v1/analyses", json={"transaction_id": tx_id}).status_code == 200
    assert seen == [expected, expected]
